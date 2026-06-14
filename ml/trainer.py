"""
ml/trainer.py
=============
Business Process Mining & Optimization Platform — Phase 2
Step 4: Training Orchestrator

What this file does
-------------------
Single entry point that trains BOTH Phase 2 ML models:
    - DelayPredictor (XGBoost regression — resolution time in hours)
    - SLAPredictor   (LightGBM classification — SLA breach risk)

Both models are trained on the same feature matrix from
FeatureEngineer, so the encoder fit happens once and is shared
(the second model's training call reuses the already-saved encoders).

After training, a metrics log is written to models/training_log.json
with a timestamped entry — useful for tracking model performance
across retraining runs as your dataset grows or SLA threshold changes.

Usage
-----
    from ml.trainer import ModelTrainer

    trainer = ModelTrainer()
    results = trainer.train_all(source="helpdesk")

Run
---
    python -m ml.trainer

    # Train on a filtered subset
    python -m ml.trainer --source helpdesk --priority Critical
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml.delay_predictor import DelayPredictor
from ml.sla_predictor    import SLAPredictor

# ── Training log location ────────────────────────────────────
LOG_PATH = Path(__file__).resolve().parent.parent / "models" / "training_log.json"


class ModelTrainer:
    """
    Orchestrates training of both Phase 2 ML models and logs
    evaluation metrics for tracking over time.
    """

    def __init__(self):
        self.delay_predictor = DelayPredictor()
        self.sla_predictor   = SLAPredictor()

    # ──────────────────────────────────────────────────────────
    # PUBLIC: train everything
    # ──────────────────────────────────────────────────────────

    def train_all(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> dict:
        """
        Train both models on the same filtered dataset and log results.

        Parameters
        ----------
        source   : filter training data by dataset name e.g. "helpdesk"
        priority : filter by priority — None for all
        category : filter by category — None for all

        Returns
        -------
        dict:
            delay_model — metrics dict from DelayPredictor.train()
            sla_model   — metrics dict from SLAPredictor.train()
            trained_at  — ISO timestamp
            filters     — the filters used for this training run
        """
        print("=" * 60)
        print("  Phase 2 Model Training")
        print(f"  Filters: source={source} priority={priority} category={category}")
        print("=" * 60)

        # ── Train delay model (XGBoost) ──────────────────────
        print("\n" + "─" * 60)
        print("  [1/2] Training Delay Predictor (XGBoost)")
        print("─" * 60)
        delay_metrics = self.delay_predictor.train(
            source=source, priority=priority, category=category
        )

        # ── Train SLA model (LightGBM) ───────────────────────
        # Reuses the encoders saved by delay_predictor's training run
        # since FeatureEngineer.build_features() re-fits and re-saves
        # them identically — both models see the same encoding.
        print("\n" + "─" * 60)
        print("  [2/2] Training SLA Predictor (LightGBM)")
        print("─" * 60)
        sla_metrics = self.sla_predictor.train(
            source=source, priority=priority, category=category
        )

        # ── Build result and log ─────────────────────────────
        result = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "filters": {
                "source": source, "priority": priority, "category": category
            },
            "delay_model": delay_metrics,
            "sla_model":   sla_metrics,
        }

        self._append_log(result)
        self._print_summary(result)

        return result

    # ──────────────────────────────────────────────────────────
    # PRIVATE: logging
    # ──────────────────────────────────────────────────────────

    def _append_log(self, result: dict):
        """
        Append this training run to models/training_log.json.
        Creates the file with an empty list if it doesn't exist.
        """
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        if LOG_PATH.exists():
            with open(LOG_PATH, "r") as f:
                try:
                    log = json.load(f)
                except json.JSONDecodeError:
                    log = []
        else:
            log = []

        log.append(result)

        with open(LOG_PATH, "w") as f:
            json.dump(log, f, indent=2, default=str)

        print(f"\n[TRAINER] Training run logged to {LOG_PATH}")

    def _print_summary(self, result: dict):
        """Print a clean summary table of both models' key metrics."""
        dm = result["delay_model"]
        sm = result["sla_model"]

        print("\n" + "=" * 60)
        print("  Training Summary")
        print("=" * 60)
        print(f"  Trained at: {result['trained_at']}")
        print(f"  Filters:    {result['filters']}")
        print()
        print("  Delay Predictor (XGBoost)")
        print(f"    MAE:  {dm['mae_hrs']:.2f} hrs")
        print(f"    RMSE: {dm['rmse_hrs']:.2f} hrs")
        print(f"    R2:   {dm['r2_log']:.3f}")
        print(f"    Top feature: "
              f"{list(dm['feature_importance'].keys())[0]} "
              f"({list(dm['feature_importance'].values())[0]:.3f})")
        print()
        print("  SLA Predictor (LightGBM)")
        auc_str = f"{sm['auc']:.3f}" if sm['auc'] is not None else "N/A"
        print(f"    AUC:       {auc_str}")
        print(f"    Precision: {sm['precision']:.3f}")
        print(f"    Recall:    {sm['recall']:.3f}")
        print(f"    F1:        {sm['f1']:.3f}")
        print(f"    Breach rate: {sm['breach_rate']*100:.1f}%")
        print(f"    Top feature: "
              f"{list(sm['feature_importance'].keys())[0]} "
              f"({list(sm['feature_importance'].values())[0]:.3f})")
        print("=" * 60)
        print()
        print("  Both models saved to models/")
        print("    - models/delay_model.pkl")
        print("    - models/sla_model.pkl")
        print("    - models/encoders.pkl")
        print("    - models/training_log.json")
        print()
        print("  Next: build api/routes_v2.py to serve predictions")


# ──────────────────────────────────────────────────────────────
# CLI ENTRY POINT — python -m ml.trainer [--source X] [--priority Y]
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train Phase 2 ML models (delay predictor + SLA predictor)"
    )
    parser.add_argument("--source",   type=str, default="helpdesk",
                        help="Dataset source filter (default: helpdesk)")
    parser.add_argument("--priority", type=str, default=None,
                        help="Priority filter e.g. Critical, High, Medium, Low")
    parser.add_argument("--category", type=str, default=None,
                        help="Category filter e.g. Software, Hardware, Network")

    args = parser.parse_args()

    trainer = ModelTrainer()
    trainer.train_all(
        source=args.source,
        priority=args.priority,
        category=args.category,
    )