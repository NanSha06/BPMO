"""
ml/feature_engineering.py
==========================
Business Process Mining & Optimization Platform — Phase 2
Step 1: Feature Engineering

What this file does
-------------------
Reads the event_log and cases tables from PostgreSQL and builds a
flat feature matrix — one row per ticket — ready for ML model training
and real-time inference.

Every ML model in Phase 2 (delay predictor, SLA predictor) consumes
the exact output of this module. Nothing else should build features.

Features produced
-----------------
Categorical (encoded):
    priority_encoded    — ordinal: Critical=3, High=2, Medium=1, Low=0
    category_encoded    — label encoded integer
    team_encoded        — label encoded integer (assigned team)

Numeric (from event log):
    escalated_int       — 0 or 1
    event_count         — number of events in the case
    cycle_time_mins     — total duration from open to last event
    wait_time_mins      — avg wait time across all events in the case

Time-based (from ticket creation timestamp):
    hour_of_day         — 0-23, when the ticket was created
    day_of_week         — 0=Monday, 6=Sunday
    is_weekend          — 1 if Saturday or Sunday
    month               — 1-12

Targets:
    log_resolution_hrs  — log1p(resolution_time_hrs) for regression
    sla_breach          — 1 if resolution_time_hrs > SLA_THRESHOLD else 0
    resolution_time_hrs — raw hours (kept for inverse-transform after prediction)

Usage
-----
    from ml.feature_engineering import FeatureEngineer

    fe = FeatureEngineer()

    # Build full feature matrix for training
    X, y_reg, y_cls, df_raw = fe.build_features(source="helpdesk")

    # Build features for a single new ticket (inference)
    features = fe.build_single(ticket_dict)

    # Get the feature column names (needed by model trainer)
    cols = fe.feature_columns

Run
---
    python -m ml.feature_engineering
"""

import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import get_database_url, config

# ── Constants ────────────────────────────────────────────────
SLA_THRESHOLD_HRS = config["kpis"]["sla_threshold_hrs"]

# Ordinal encoding for priority — order matters for the model
PRIORITY_ORDER = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}

# Columns that go into the model as features
FEATURE_COLUMNS = [
    "priority_encoded",
    "category_encoded",
    "team_encoded",
    "escalated_int",
    "event_count",
    "cycle_time_mins",
    "wait_time_mins",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "month",
]

# Path where label encoders are saved so inference uses the same mapping
ENCODER_PATH = Path(__file__).resolve().parent.parent / "models" / "encoders.pkl"


def _get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


class FeatureEngineer:
    """
    Builds the ML feature matrix from PostgreSQL event_log and cases tables.

    Maintains LabelEncoder state between fit (training) and transform
    (inference) so unseen categories at inference time are handled
    gracefully rather than crashing.
    """

    def __init__(self):
        self.engine           = _get_engine()
        self.le_category      = LabelEncoder()
        self.le_team          = LabelEncoder()
        self._encoders_fitted = False
        self.feature_columns  = FEATURE_COLUMNS

    # ──────────────────────────────────────────────────────────
    # PUBLIC: full feature matrix for training
    # ──────────────────────────────────────────────────────────

    def build_features(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> tuple:
        """
        Build the complete feature matrix from PostgreSQL for model training.

        Fits the LabelEncoders on the full dataset and saves them to disk
        so the same encoding is used at inference time.

        Parameters
        ----------
        source   : filter by dataset name e.g. "helpdesk"
        priority : filter by priority — pass None for all
        category : filter by category — pass None for all

        Returns
        -------
        X        : pd.DataFrame — feature matrix, shape (n_cases, 11)
        y_reg    : pd.Series    — log1p(resolution_time_hrs) for regression
        y_cls    : pd.Series    — binary SLA breach flag for classification
        df_raw   : pd.DataFrame — full raw DataFrame including targets and case_id
        """
        print("[FEATURES] Loading data from PostgreSQL ...")
        df = self._load_data(source, priority, category)
        print(f"[FEATURES] {len(df):,} cases loaded.")

        print("[FEATURES] Engineering features ...")
        df = self._add_features(df, fit=True)

        # Save encoders so inference uses identical mapping
        self._save_encoders()

        X     = df[FEATURE_COLUMNS].copy()
        y_reg = df["log_resolution_hrs"].copy()
        y_cls = df["sla_breach"].copy()

        # Drop rows where any feature or target is null
        mask  = X.notnull().all(axis=1) & y_reg.notnull() & y_cls.notnull()
        X, y_reg, y_cls = X[mask], y_reg[mask], y_cls[mask]
        df_raw = df[mask].copy()

        print(f"[FEATURES] Final matrix: {X.shape[0]:,} rows × {X.shape[1]} features")
        print(f"[FEATURES] SLA breach rate: {y_cls.mean()*100:.1f}%")
        print(f"[FEATURES] Avg resolution: {np.expm1(y_reg).mean():.1f} hrs")
        return X, y_reg, y_cls, df_raw

    # ──────────────────────────────────────────────────────────
    # PUBLIC: single-ticket features for inference
    # ──────────────────────────────────────────────────────────

    def build_single(self, ticket: dict) -> pd.DataFrame:
        """
        Build a one-row feature DataFrame for a single ticket.
        Used by the API to get real-time predictions.

        The ticket dict must contain:
            category, priority, resource (team), escalated (bool),
            event_count (int), cycle_time_mins (float),
            wait_time_mins (float), timestamp (str or datetime)

        Returns
        -------
        pd.DataFrame with one row and columns = FEATURE_COLUMNS
        """
        if not self._encoders_fitted:
            self._load_encoders()

        df = pd.DataFrame([ticket])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

        df = self._add_features(df, fit=False)

        # Handle unseen categories gracefully
        df["category_encoded"] = df["category_encoded"].fillna(0).astype(int)
        df["team_encoded"]     = df["team_encoded"].fillna(0).astype(int)

        return df[FEATURE_COLUMNS].copy()

    # ──────────────────────────────────────────────────────────
    # PRIVATE: data loader
    # ──────────────────────────────────────────────────────────

    def _load_data(self, source, priority, category) -> pd.DataFrame:
        """
        Load one row per case from PostgreSQL by joining:
            cases         — resolution time, escalation, priority, category
            event_log     — event count, avg wait time, first timestamp

        This join gives us everything we need for features and targets
        in a single query.
        """
        conditions, params = [], {}

        if source:
            conditions.append("c.source = :source")
            params["source"] = source
        if priority and priority.lower() != "all":
            conditions.append("c.priority = :priority")
            params["priority"] = priority
        if category and category.lower() != "all":
            conditions.append("c.category = :category")
            params["category"] = category

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT
                c.case_id,
                c.category,
                c.priority,
                c.escalated,
                c.cycle_time_mins,
                c.event_count,
                c.resolution_time_hrs,

                -- Average wait time per case from event log
                AVG(e.wait_time_mins)          AS wait_time_mins,

                -- Assigned team from first event
                MODE() WITHIN GROUP
                    (ORDER BY e.resource)      AS resource,

                -- Ticket creation timestamp from earliest event
                MIN(e.timestamp)               AS timestamp

            FROM   cases c
            JOIN   event_log e ON e.case_id = c.case_id
            {where}
            GROUP  BY
                c.case_id, c.category, c.priority, c.escalated,
                c.cycle_time_mins, c.event_count, c.resolution_time_hrs
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

        # Drop cases with no resolution time — can't use as training targets
        df = df.dropna(subset=["resolution_time_hrs"])
        df = df[df["resolution_time_hrs"] > 0]

        return df

    # ──────────────────────────────────────────────────────────
    # PRIVATE: feature computation
    # ──────────────────────────────────────────────────────────

    def _add_features(self, df: pd.DataFrame, fit: bool) -> pd.DataFrame:
        """
        Add all engineered feature columns to the DataFrame in place.

        Parameters
        ----------
        df  : DataFrame with raw columns from PostgreSQL
        fit : if True, fit LabelEncoders on this data (training mode)
              if False, transform using previously fitted encoders (inference)
        """
        df = df.copy()

        # ── Priority: ordinal encoding ────────────────────────
        # Critical > High > Medium > Low — order carries meaning
        df["priority_encoded"] = (
            df["priority"]
            .str.strip()
            .map(PRIORITY_ORDER)
            .fillna(1)           # unknown priority → Medium
            .astype(int)
        )

        # ── Category: label encoding ──────────────────────────
        df["category"] = df["category"].fillna("unknown").str.strip()
        if fit:
            self.le_category.fit(df["category"])
            self._encoders_fitted = True
        df["category_encoded"] = self._safe_label_transform(
            self.le_category, df["category"]
        )

        # ── Team: label encoding ──────────────────────────────
        df["resource"] = df["resource"].fillna("unknown").str.strip()
        if fit:
            self.le_team.fit(df["resource"])
        df["team_encoded"] = self._safe_label_transform(
            self.le_team, df["resource"]
        )

        # ── Escalation: bool → int ────────────────────────────
        df["escalated_int"] = df["escalated"].fillna(False).astype(int)

        # ── Event count: fill missing ─────────────────────────
        df["event_count"] = df["event_count"].fillna(2).astype(int)

        # ── Cycle time: fill missing ──────────────────────────
        df["cycle_time_mins"] = df["cycle_time_mins"].fillna(
            df["cycle_time_mins"].median() if "cycle_time_mins" in df else 120
        )

        # ── Wait time: fill missing ───────────────────────────
        df["wait_time_mins"] = df["wait_time_mins"].fillna(0.0)

        # ── Time features from creation timestamp ────────────
        if "timestamp" in df.columns and df["timestamp"].notna().any():
            ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df["hour_of_day"] = ts.dt.hour.fillna(9).astype(int)
            df["day_of_week"] = ts.dt.dayofweek.fillna(0).astype(int)
            df["is_weekend"]  = (df["day_of_week"] >= 5).astype(int)
            df["month"]       = ts.dt.month.fillna(1).astype(int)
        else:
            df["hour_of_day"] = 9
            df["day_of_week"] = 0
            df["is_weekend"]  = 0
            df["month"]       = 1

        # ── Targets ──────────────────────────────────────────
        if "resolution_time_hrs" in df.columns:
            df["log_resolution_hrs"] = np.log1p(
                df["resolution_time_hrs"].clip(lower=0)
            )
            df["sla_breach"] = (
                df["resolution_time_hrs"] > SLA_THRESHOLD_HRS
            ).astype(int)

        return df

    # ──────────────────────────────────────────────────────────
    # PRIVATE: encoder persistence
    # ──────────────────────────────────────────────────────────

    def _safe_label_transform(self, encoder: LabelEncoder,
                               series: pd.Series) -> pd.Series:
        """
        Transform a series using a fitted LabelEncoder.
        Unseen values (not in training set) are encoded as 0
        instead of raising an error — safe for inference.
        """
        known   = set(encoder.classes_)
        mapped  = series.apply(
            lambda x: encoder.transform([x])[0] if x in known else 0
        )
        return mapped.astype(int)

    def _save_encoders(self):
        """Save fitted LabelEncoders to disk for use at inference time."""
        ENCODER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ENCODER_PATH, "wb") as f:
            pickle.dump({
                "le_category": self.le_category,
                "le_team":     self.le_team,
            }, f)
        print(f"[FEATURES] Encoders saved to {ENCODER_PATH}")

    def _load_encoders(self):
        """Load previously saved LabelEncoders from disk."""
        if not ENCODER_PATH.exists():
            raise FileNotFoundError(
                f"Encoder file not found at {ENCODER_PATH}.\n"
                f"Run the trainer first: python -m ml.trainer"
            )
        with open(ENCODER_PATH, "rb") as f:
            encoders = pickle.load(f)
        self.le_category      = encoders["le_category"]
        self.le_team          = encoders["le_team"]
        self._encoders_fitted = True
        print(f"[FEATURES] Encoders loaded from {ENCODER_PATH}")


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m ml.feature_engineering
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    fe = FeatureEngineer()

    print("\n── Building feature matrix ──\n")
    X, y_reg, y_cls, df_raw = fe.build_features(source="helpdesk")

    print("\n── Feature matrix sample ──")
    print(X.head(5).to_string())

    print("\n── Feature stats ──")
    print(X.describe().round(2).to_string())

    print("\n── Target distribution ──")
    print(f"  Regression target  (log_resolution_hrs) — mean: {y_reg.mean():.3f}  std: {y_reg.std():.3f}")
    print(f"  Regression target  (resolution_hrs raw) — mean: {y_reg.apply(lambda x: round(__import__('numpy').expm1(x),1)).mean():.1f} hrs")
    print(f"  Classification target (sla_breach)       — breach: {y_cls.sum():,}  ({y_cls.mean()*100:.1f}%)")

    print("\n── Single-ticket inference test ──")
    sample_ticket = {
        "category":        "Software",
        "priority":        "High",
        "resource":        df_raw["resource"].iloc[0],
        "escalated":       True,
        "event_count":     3,
        "cycle_time_mins": 180.0,
        "wait_time_mins":  45.0,
        "timestamp":       "2024-01-15 09:30:00+00:00",
    }
    single = fe.build_single(sample_ticket)
    print(single.to_string())
    print("\n[FEATURES] All tests passed.")