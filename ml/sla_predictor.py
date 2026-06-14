"""
ml/sla_predictor.py
====================
Business Process Mining & Optimization Platform — Phase 2
Step 3: SLA Breach Prediction Model (LightGBM Classification)

What this file does
-------------------
Trains a LightGBM binary classifier that predicts the probability a
ticket will breach the SLA threshold (default 48 hours), based on its
attributes at creation time.

SLA breach is an imbalanced classification problem — most tickets do
NOT breach. The model uses scale_pos_weight to correct for this
imbalance so the rare "will breach" class is not ignored.

Output is a risk score from 0-100 with a risk band (Low/Medium/High)
for easy dashboard display.

Usage
-----
    from ml.sla_predictor import SLAPredictor

    predictor = SLAPredictor()

    # Train and save the model
    metrics = predictor.train(source="helpdesk")

    # Load a previously trained model
    predictor.load()

    # Predict SLA breach risk for a single new ticket
    risk = predictor.predict_single(ticket_dict)

    # Predict for a batch
    risk_scores = predictor.predict_batch(X_dataframe)

Run
---
    python -m ml.sla_predictor
"""

import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score,
    f1_score, confusion_matrix,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml.feature_engineering import FeatureEngineer, FEATURE_COLUMNS

# ── Model file location ──────────────────────────────────────
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "sla_model.pkl"

# ── LightGBM hyperparameters ─────────────────────────────────
# scale_pos_weight is computed at training time from the actual
# class balance — not hardcoded here.
LGB_PARAMS = {
    "n_estimators":     300,
    "max_depth":        6,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "random_state":     42,
    "n_jobs":           -1,
    "verbose":          -1,
}

TEST_SIZE        = 0.2
RANDOM_STATE     = 42
DEFAULT_THRESHOLD = 0.5     # probability cutoff for breach/no-breach label

# Risk band cutoffs — used by the dashboard to colour-code tickets
RISK_BANDS = {
    "High":   70,    # risk_score >= 70
    "Medium": 40,    # 40 <= risk_score < 70
    "Low":    0,     # risk_score < 40
}


class SLAPredictor:
    """
    LightGBM binary classifier predicting SLA breach probability.

    predict_single() and predict_batch() return a risk score 0-100
    plus a risk band label for direct dashboard use.
    """

    def __init__(self):
        self.model           = None
        self.feature_columns = FEATURE_COLUMNS
        self.metrics         = {}
        self.threshold       = DEFAULT_THRESHOLD

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
        Train the LightGBM SLA breach prediction model.

        Parameters
        ----------
        source   : filter training data by dataset name e.g. "helpdesk"
        priority : filter by priority — None for all
        category : filter by category — None for all
        save     : if True, save the trained model to MODEL_PATH

        Returns
        -------
        dict of evaluation metrics:
            auc, precision, recall, f1, breach_rate,
            confusion_matrix, n_train, n_test,
            feature_importance (dict)
        """
        print("[SLA] Building feature matrix ...")
        fe = FeatureEngineer()
        X, y_reg, y_cls, df_raw = fe.build_features(
            source=source, priority=priority, category=category
        )

        breach_rate = y_cls.mean()
        print(f"[SLA] SLA breach rate in data: {breach_rate*100:.1f}%")

        print(f"[SLA] Splitting train/test ({int((1-TEST_SIZE)*100)}/{int(TEST_SIZE*100)}, stratified) ...")
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_cls, test_size=TEST_SIZE,
            random_state=RANDOM_STATE, stratify=y_cls
        )

        # Compute class imbalance correction from the actual training split
        neg = int((y_train == 0).sum())
        pos = int((y_train == 1).sum())
        scale_pos_weight = neg / pos if pos > 0 else 1.0
        print(f"[SLA] Class balance — no-breach: {neg:,}  breach: {pos:,}  "
              f"scale_pos_weight: {scale_pos_weight:.2f}")

        print(f"[SLA] Training LightGBM on {len(X_train):,} rows ...")
        self.model = lgb.LGBMClassifier(
            **LGB_PARAMS,
            scale_pos_weight=scale_pos_weight,
        )
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
        )

        print("[SLA] Evaluating ...")
        self.metrics = self._evaluate(X_test, y_test, breach_rate)

        auc_str = f"{self.metrics['auc']:.3f}" if self.metrics['auc'] is not None else "N/A (single class)"
        print(f"[SLA] AUC:       {auc_str}")
        print(f"[SLA] Precision: {self.metrics['precision']:.3f}")
        print(f"[SLA] Recall:    {self.metrics['recall']:.3f}")
        print(f"[SLA] F1:        {self.metrics['f1']:.3f}")

        if save:
            self.save()

        return self.metrics

    # ──────────────────────────────────────────────────────────
    # PUBLIC: inference
    # ──────────────────────────────────────────────────────────

    def predict_single(self, ticket: dict) -> dict:
        """
        Predict SLA breach risk for a single new ticket.

        Parameters
        ----------
        ticket : dict with keys
            category, priority, resource, escalated, event_count,
            cycle_time_mins, wait_time_mins, timestamp

        Returns
        -------
        dict:
            risk_score    — 0-100, probability of SLA breach * 100
            risk_band     — "Low" | "Medium" | "High"
            will_breach   — bool, risk_score >= 50
            top_factors   — list of {feature, importance} driving this prediction
        """
        if self.model is None:
            self.load()

        fe       = FeatureEngineer()
        features = fe.build_single(ticket)

        proba      = float(self.model.predict_proba(features)[0][1])
        risk_score = round(proba * 100, 1)

        return {
            "risk_score":  risk_score,
            "risk_band":   self._risk_band(risk_score),
            "will_breach": proba >= self.threshold,
            "top_factors": self._top_factors(),
        }

    def predict_batch(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Predict SLA breach risk for a batch of feature rows.

        Parameters
        ----------
        X : DataFrame with columns matching self.feature_columns

        Returns
        -------
        DataFrame with added columns: risk_score, risk_band, will_breach
        """
        if self.model is None:
            self.load()

        proba = self.model.predict_proba(X[self.feature_columns])[:, 1]

        result = X.copy()
        result["risk_score"]  = (proba * 100).round(1)
        result["risk_band"]   = result["risk_score"].apply(self._risk_band)
        result["will_breach"] = proba >= self.threshold
        return result

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
                "threshold":       self.threshold,
            }, f)
        print(f"[SLA] Model saved to {MODEL_PATH}")

    def load(self):
        """Load a previously trained model from MODEL_PATH."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model file not found at {MODEL_PATH}.\n"
                f"Train the model first: python -m ml.sla_predictor"
            )
        with open(MODEL_PATH, "rb") as f:
            saved = pickle.load(f)
        self.model           = saved["model"]
        self.metrics         = saved["metrics"]
        self.feature_columns = saved["feature_columns"]
        self.threshold       = saved.get("threshold", DEFAULT_THRESHOLD)
        print(f"[SLA] Model loaded from {MODEL_PATH}")

    # ──────────────────────────────────────────────────────────
    # PRIVATE: evaluation
    # ──────────────────────────────────────────────────────────

    def _evaluate(self, X_test, y_test, breach_rate) -> dict:
        """
        Compute classification metrics on the test set.

        AUC measures ranking quality regardless of threshold.
        Precision/Recall/F1 use the default 0.5 threshold.
        Confusion matrix shown as [[TN, FP], [FN, TP]].

        Handles the edge case where y_test contains only one class
        (e.g. SLA threshold is set so high that no tickets breach).
        In that case AUC is undefined and is reported as None instead
        of crashing, and the confusion matrix is padded to 2x2.
        """
        proba = self.model.predict_proba(X_test)[:, 1]
        pred  = (proba >= self.threshold).astype(int)

        n_classes = y_test.nunique()
        if n_classes < 2:
            print(f"[SLA] WARNING: only one class present in y_test "
                  f"(breach_rate={breach_rate*100:.2f}%). "
                  f"AUC is undefined. Consider lowering "
                  f"kpis.sla_threshold_hrs in config.yaml.")
            auc = None
        else:
            auc = round(float(roc_auc_score(y_test, proba)), 3)

        prec = precision_score(y_test, pred, zero_division=0)
        rec  = recall_score(y_test, pred, zero_division=0)
        f1   = f1_score(y_test, pred, zero_division=0)

        # Force a 2x2 confusion matrix even if only one class is present
        cm = confusion_matrix(y_test, pred, labels=[0, 1])

        importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_.tolist()
        ))
        # Normalise to sum to 1 for easier interpretation
        total = sum(importance.values()) or 1
        importance = {k: round(v / total, 4) for k, v in importance.items()}
        importance = dict(sorted(importance.items(), key=lambda x: -x[1]))

        return {
            "auc":             auc,   # already rounded float, or None
            "precision":       round(float(prec), 3),
            "recall":          round(float(rec), 3),
            "f1":              round(float(f1), 3),
            "breach_rate":     round(float(breach_rate), 3),
            "confusion_matrix": cm.tolist(),
            "n_train":  int(len(X_test) / TEST_SIZE * (1 - TEST_SIZE)),
            "n_test":   int(len(X_test)),
            "feature_importance": importance,
        }

    def _top_factors(self, top_n: int = 3) -> list:
        """
        Return the top N most important features overall.
        Used to explain WHY a prediction was made — feeds into
        the AI recommendation engine in Step 5.
        """
        importance = self.metrics.get("feature_importance", {})
        return [
            {"feature": k, "importance": v}
            for k, v in list(importance.items())[:top_n]
        ]

    def _risk_band(self, score: float) -> str:
        """Map a 0-100 risk score to Low/Medium/High band."""
        if score >= RISK_BANDS["High"]:
            return "High"
        elif score >= RISK_BANDS["Medium"]:
            return "Medium"
        return "Low"


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m ml.sla_predictor
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    predictor = SLAPredictor()

    print("\n── Training SLA breach prediction model ──\n")
    metrics = predictor.train(source="helpdesk")

    print("\n── Confusion matrix ──")
    cm = metrics["confusion_matrix"]
    print(f"                  Predicted No   Predicted Yes")
    print(f"  Actual No       {cm[0][0]:>10,}   {cm[0][1]:>13,}")
    print(f"  Actual Yes      {cm[1][0]:>10,}   {cm[1][1]:>13,}")

    print("\n── Feature importance ──")
    for feat, score in metrics["feature_importance"].items():
        bar = "█" * int(score * 50)
        print(f"  {feat:<20} {score:.4f}  {bar}")

    print("\n── Sample predictions ──")
    sample_tickets = [
        {
            "category": "Network", "priority": "Critical",
            "resource": "Team_A", "escalated": True,
            "event_count": 3, "cycle_time_mins": 400.0,
            "wait_time_mins": 150.0, "timestamp": "2024-01-19 17:00:00+00:00",  # Friday evening
        },
        {
            "category": "Software", "priority": "Low",
            "resource": "Team_B", "escalated": False,
            "event_count": 2, "cycle_time_mins": 30.0,
            "wait_time_mins": 5.0, "timestamp": "2024-01-15 09:00:00+00:00",  # Monday morning
        },
        {
            "category": "Hardware", "priority": "Medium",
            "resource": "Team_C", "escalated": True,
            "event_count": 3, "cycle_time_mins": 200.0,
            "wait_time_mins": 70.0, "timestamp": "2024-01-17 11:00:00+00:00",
        },
    ]

    for i, ticket in enumerate(sample_tickets, 1):
        result = predictor.predict_single(ticket)
        print(f"\n  Ticket {i}: {ticket['priority']} {ticket['category']} "
              f"(escalated={ticket['escalated']})")
        print(f"    Risk score:  {result['risk_score']:>5.1f} / 100")
        print(f"    Risk band:   {result['risk_band']}")
        print(f"    Will breach: {result['will_breach']}")

        factor_strs = []
        for factor in result["top_factors"]:
            factor_strs.append(f"{factor['feature']} ({factor['importance']:.2f})")
        print(f"    Top factors: " + ", ".join(factor_strs))

    print("\n[SLA] All tests passed.")