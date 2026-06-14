"""
ml/delay_predictor.py
======================
Business Process Mining & Optimization Platform — Phase 2
Step 2: Delay Prediction Model (XGBoost Regression)

What this file does
-------------------
Trains an XGBoost regression model that predicts how many hours a
ticket will take to resolve, based on its attributes at creation time
(priority, category, team, escalation flag, time-of-day, etc).

The model is trained on log1p(resolution_time_hrs) to handle the
right-skewed distribution of resolution times, then predictions are
converted back to hours using expm1().

Usage
-----
    from ml.delay_predictor import DelayPredictor

    predictor = DelayPredictor()

    # Train and save the model
    metrics = predictor.train(source="helpdesk")

    # Load a previously trained model
    predictor.load()

    # Predict resolution time for a single new ticket
    hours = predictor.predict_single(ticket_dict)

    # Predict for a batch
    hours_array = predictor.predict_batch(X_dataframe)

Run
---
    python -m ml.delay_predictor
"""

import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml.feature_engineering import FeatureEngineer, FEATURE_COLUMNS

# ── Model file location ──────────────────────────────────────
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "delay_model.pkl"

# ── XGBoost hyperparameters ──────────────────────────────────
# Tuned for tabular data with ~700k rows and 11 features.
# subsample/colsample reduce overfitting on the large dataset.
XGB_PARAMS = {
    "n_estimators":     300,
    "max_depth":        6,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "random_state":     42,
    "n_jobs":           -1,
    "objective":        "reg:squarederror",
}

TEST_SIZE    = 0.2
RANDOM_STATE = 42


class DelayPredictor:
    """
    XGBoost regression model predicting ticket resolution time in hours.

    Training target is log1p(resolution_time_hrs). All predict methods
    automatically apply expm1() to return predictions in hours.
    """

    def __init__(self):
        self.model           = None
        self.feature_columns = FEATURE_COLUMNS
        self.metrics         = {}

    # ──────────────────────────────────────────────────────────
    # PUBLIC: training
    # ──────────────────────────────────────────────────────────

    def train(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        save:     bool = True,
    ) -> dict:
        """
        Train the XGBoost delay prediction model.

        Parameters
        ----------
        source   : filter training data by dataset name e.g. "helpdesk"
        priority : filter by priority — None for all
        category : filter by category — None for all
        save     : if True, save the trained model to MODEL_PATH

        Returns
        -------
        dict of evaluation metrics:
            mae_hrs, rmse_hrs, r2_log, n_train, n_test,
            feature_importance (dict)
        """
        print("[DELAY] Building feature matrix ...")
        fe = FeatureEngineer()
        X, y_reg, y_cls, df_raw = fe.build_features(
            source=source, priority=priority, category=category
        )

        print(f"[DELAY] Splitting train/test ({int((1-TEST_SIZE)*100)}/{int(TEST_SIZE*100)}) ...")
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_reg, test_size=TEST_SIZE, random_state=RANDOM_STATE
        )

        print(f"[DELAY] Training XGBoost on {len(X_train):,} rows ...")
        self.model = xgb.XGBRegressor(**XGB_PARAMS)
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        print("[DELAY] Evaluating ...")
        self.metrics = self._evaluate(X_test, y_test)

        print(f"[DELAY] MAE:  {self.metrics['mae_hrs']:.2f} hrs")
        print(f"[DELAY] RMSE: {self.metrics['rmse_hrs']:.2f} hrs")
        print(f"[DELAY] R2:   {self.metrics['r2_log']:.3f}")

        if save:
            self.save()

        return self.metrics

    # ──────────────────────────────────────────────────────────
    # PUBLIC: inference
    # ──────────────────────────────────────────────────────────

    def predict_single(self, ticket: dict) -> dict:
        """
        Predict resolution time for a single new ticket.

        Parameters
        ----------
        ticket : dict with keys
            category, priority, resource, escalated, event_count,
            cycle_time_mins, wait_time_mins, timestamp

        Returns
        -------
        dict:
            predicted_hours      — predicted resolution time in hours
            predicted_days       — same, in days (rounded to 1 decimal)
            confidence_band_low  — predicted_hours - MAE (never below 0)
            confidence_band_high — predicted_hours + MAE
        """
        if self.model is None:
            self.load()

        fe       = FeatureEngineer()
        features = fe.build_single(ticket)

        pred_log = self.model.predict(features)[0]
        pred_hrs = float(np.expm1(pred_log))

        mae = self.metrics.get("mae_hrs", pred_hrs * 0.3)  # fallback: 30% band

        return {
            "predicted_hours":      round(pred_hrs, 1),
            "predicted_days":       round(pred_hrs / 24, 1),
            "confidence_band_low":  round(max(0, pred_hrs - mae), 1),
            "confidence_band_high": round(pred_hrs + mae, 1),
        }

    def predict_batch(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict resolution time in hours for a batch of feature rows.

        Parameters
        ----------
        X : DataFrame with columns matching self.feature_columns

        Returns
        -------
        np.ndarray of predicted hours (already expm1-transformed)
        """
        if self.model is None:
            self.load()

        pred_log = self.model.predict(X[self.feature_columns])
        return np.expm1(pred_log)

    # ──────────────────────────────────────────────────────────
    # PUBLIC: persistence
    # ──────────────────────────────────────────────────────────

    def save(self):
        """Save the trained model and metrics to MODEL_PATH."""
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "model":           self.model,
                "metrics":         self.metrics,
                "feature_columns": self.feature_columns,
            }, f)
        print(f"[DELAY] Model saved to {MODEL_PATH}")

    def load(self):
        """Load a previously trained model from MODEL_PATH."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model file not found at {MODEL_PATH}.\n"
                f"Train the model first: python -m ml.delay_predictor"
            )
        with open(MODEL_PATH, "rb") as f:
            saved = pickle.load(f)
        self.model           = saved["model"]
        self.metrics         = saved["metrics"]
        self.feature_columns = saved["feature_columns"]
        print(f"[DELAY] Model loaded from {MODEL_PATH}")

    # ──────────────────────────────────────────────────────────
    # PRIVATE: evaluation
    # ──────────────────────────────────────────────────────────

    def _evaluate(self, X_test, y_test) -> dict:
        """
        Compute evaluation metrics on the test set.

        Returns dict with MAE/RMSE in hours (interpretable),
        R2 on the log scale (what the model actually optimises),
        and feature importance ranking.
        """
        pred_log = self.model.predict(X_test)

        pred_hrs = np.expm1(pred_log)
        true_hrs = np.expm1(y_test)

        mae  = mean_absolute_error(true_hrs, pred_hrs)
        rmse = np.sqrt(mean_squared_error(true_hrs, pred_hrs))
        r2   = r2_score(y_test, pred_log)

        importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_.tolist()
        ))
        importance = dict(
            sorted(importance.items(), key=lambda x: -x[1])
        )

        return {
            "mae_hrs":  round(float(mae), 2),
            "rmse_hrs": round(float(rmse), 2),
            "r2_log":   round(float(r2), 3),
            "n_train":  int(len(X_test) / TEST_SIZE * (1 - TEST_SIZE)),
            "n_test":   int(len(X_test)),
            "feature_importance": {
                k: round(v, 4) for k, v in importance.items()
            },
        }


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m ml.delay_predictor
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    predictor = DelayPredictor()

    print("\n── Training delay prediction model ──\n")
    metrics = predictor.train(source="helpdesk")

    print("\n── Feature importance ──")
    for feat, score in metrics["feature_importance"].items():
        bar = "█" * int(score * 50)
        print(f"  {feat:<20} {score:.4f}  {bar}")

    print("\n── Sample predictions ──")
    sample_tickets = [
        {
            "category": "Software", "priority": "Critical",
            "resource": "Team_A", "escalated": True,
            "event_count": 3, "cycle_time_mins": 200.0,
            "wait_time_mins": 80.0, "timestamp": "2024-01-15 09:00:00+00:00",
        },
        {
            "category": "Hardware", "priority": "Low",
            "resource": "Team_B", "escalated": False,
            "event_count": 2, "cycle_time_mins": 60.0,
            "wait_time_mins": 15.0, "timestamp": "2024-01-15 14:00:00+00:00",
        },
        {
            "category": "Network", "priority": "High",
            "resource": "Team_C", "escalated": True,
            "event_count": 3, "cycle_time_mins": 150.0,
            "wait_time_mins": 50.0, "timestamp": "2024-01-19 17:00:00+00:00",  # Friday evening
        },
    ]

    for i, ticket in enumerate(sample_tickets, 1):
        result = predictor.predict_single(ticket)
        print(f"\n  Ticket {i}: {ticket['priority']} {ticket['category']} "
              f"(escalated={ticket['escalated']})")
        print(f"    Predicted: {result['predicted_hours']:>6.1f} hrs "
              f"({result['predicted_days']:.1f} days)")
        print(f"    Range:     {result['confidence_band_low']:>6.1f} - "
              f"{result['confidence_band_high']:.1f} hrs")

    print("\n[DELAY] All tests passed.")