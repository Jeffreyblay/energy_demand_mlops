"""
GridVision — LightGBM quantile training.

Trains P10 / P50 / P90 demand models on the feature set, evaluates on a
time-based holdout (the most recent HOLDOUT_DAYS), and saves the models:

    data/models/lgbm_quantile.joblib   { "p10": booster, "p50": ..., "p90": ...,
                                          "features": [...], "trained_at": ... }

Run from the project root:

    python -m src.train
"""
from __future__ import annotations

from datetime import datetime, timezone

import joblib
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_percentage_error, root_mean_squared_error

from src.config import (
    FEATURE_COLS,
    FEATURES_PARQUET,
    HOLDOUT_DAYS,
    LGBM_PARAMS,
    MODELS_DIR,
    QUANTILES,
    TARGET,
)

MODEL_PATH = MODELS_DIR / "lgbm_quantile.joblib"


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train = older rows; test = most recent HOLDOUT_DAYS. No leakage."""
    cutoff = df["ts"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train = df[df["ts"] <= cutoff]
    test = df[df["ts"] > cutoff]
    return train, test


def train_quantiles(train: pd.DataFrame) -> dict[str, LGBMRegressor]:
    models: dict[str, LGBMRegressor] = {}
    X = train[FEATURE_COLS]
    y = train[TARGET]
    for name, alpha in QUANTILES.items():
        model = LGBMRegressor(**LGBM_PARAMS, alpha=alpha)
        model.fit(X, y)
        models[name] = model
    return models


def evaluate(models: dict, test: pd.DataFrame) -> pd.DataFrame:
    X = test[FEATURE_COLS]
    pred = test[["region", "ts", TARGET]].copy()
    for name in QUANTILES:
        pred[name] = models[name].predict(X)

    def _metrics(g: pd.DataFrame) -> pd.Series:
        inside = ((g[TARGET] >= g["p10"]) & (g[TARGET] <= g["p90"])).mean()
        return pd.Series(
            {
                "n": len(g),
                "MAPE_%": mean_absolute_percentage_error(g[TARGET], g["p50"]) * 100,
                "RMSE_MW": root_mean_squared_error(g[TARGET], g["p50"]),
                "coverage_%": inside * 100,
            }
        )

    per_region = test.assign(
        p10=pred["p10"], p50=pred["p50"], p90=pred["p90"]
    ).groupby("region").apply(_metrics, include_groups=False)

    overall = _metrics(pred).rename("ALL")
    return pd.concat([per_region, overall.to_frame().T])


def run_training() -> dict:
    """Train, evaluate, persist. Returns a JSON-safe summary dict (used by
    both the CLI and the retrain pipeline script)."""
    if not FEATURES_PARQUET.exists():
        raise FileNotFoundError("features parquet missing — run build_features first")

    df = pd.read_parquet(FEATURES_PARQUET)
    train, test = time_split(df)
    print(
        f"Train: {len(train):,} rows (→ {train['ts'].max()})\n"
        f"Test : {len(test):,} rows (last {HOLDOUT_DAYS} days)\n"
    )

    models = train_quantiles(train)
    report = evaluate(models, test)

    with pd.option_context("display.float_format", lambda v: f"{v:,.2f}"):
        print("Holdout performance (P50 point forecast):")
        print(report.to_string())

    # Persist the booster bundle locally — this is the candidate the gate
    # (src/gate_eval.py) evaluates and src/model_store.py may promote.
    joblib.dump(
        {
            **models,
            "features": FEATURE_COLS,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        },
        MODEL_PATH,
    )
    print(f"\nSaved models → {MODEL_PATH}")

    return {
        "model_path": str(MODEL_PATH),
        "candidate_mape": float(report.loc["ALL", "MAPE_%"]),
    }


def main() -> None:
    run_training()


if __name__ == "__main__":
    main()
