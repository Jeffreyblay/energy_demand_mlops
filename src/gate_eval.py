"""
GridVision — gate evaluation.

Computes the three MAPE numbers the promotion gate compares, all on the SAME
holdout window (the most recent HOLDOUT_DAYS), so the comparison is fair:

  - candidate_mape  : the freshly trained candidate (from data/models bundle)
  - production_mape : the current production model (via the git model store), or
                       None if none exists yet (cold start)
  - baseline_mape   : seasonal-naive (demand_lag_168h)

Returns a JSON-safe dict for the retrain pipeline to hand to the gate.
"""
from __future__ import annotations

import joblib
import pandas as pd
from sklearn.metrics import mean_absolute_percentage_error

from src import model_store
from src.config import FEATURE_COLS, FEATURES_PARQUET, TARGET
from src.train import MODEL_PATH, time_split


# Computes MAPE as a percentage given true and predicted values.
def _mape(y_true, y_pred) -> float:
    return float(mean_absolute_percentage_error(y_true, y_pred) * 100)


# Computes candidate/baseline/production MAPE on the same holdout window, for the promotion gate.
def evaluate() -> dict:
    df = pd.read_parquet(FEATURES_PARQUET)
    _, test = time_split(df)
    X = test[FEATURE_COLS]
    y = test[TARGET]

    # Candidate: the bundle just written by run_training().
    bundle = joblib.load(MODEL_PATH)
    candidate_mape = _mape(y, bundle["p50"].predict(X))

    # Baseline: seasonal-naive = demand one week ago (already a feature).
    baseline_mape = _mape(y, test["demand_lag_168h"])

    # Production: current production model, if one is aliased.
    production_mape = None
    if model_store.production_version() is not None:
        prod = model_store.load_production()
        production_mape = _mape(y, prod.predict(X)["p50"])

    return {
        "candidate_mape": candidate_mape,
        "baseline_mape": baseline_mape,
        "production_mape": production_mape,
        "n_test": int(len(test)),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(evaluate(), indent=2))
