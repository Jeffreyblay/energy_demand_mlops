"""
GridVision — walk-forward backtest vs a seasonal-naive baseline.

For each of the last HOLDOUT_DAYS days, train a P50 model on all prior data,
predict that day, and roll forward (expanding window). Compare the model's MAPE
against the seasonal-naive baseline (demand exactly 168h / 1 week ago).

    Baseline:  y_hat(t) = demand(t - 168h)   == the demand_lag_168h feature

If the model can't beat "just use last week's value", it isn't earning its
complexity. This is the comparison the promotion gate will reuse in Phase 3-4.

Run from the project root:

    python -m src.backtest
"""
from __future__ import annotations

import sys

import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_percentage_error

from src.config import (
    FEATURE_COLS,
    FEATURES_PARQUET,
    HOLDOUT_DAYS,
    LGBM_PARAMS,
    TARGET,
)


def _fit_p50(train: pd.DataFrame) -> LGBMRegressor:
    params = {**LGBM_PARAMS, "alpha": 0.50}
    model = LGBMRegressor(**params)
    model.fit(train[FEATURE_COLS], train[TARGET])
    return model


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """Expanding-window daily backtest over the last HOLDOUT_DAYS."""
    df = df.sort_values("ts")
    last_day = df["ts"].max().normalize()
    test_days = [last_day - pd.Timedelta(days=i) for i in range(HOLDOUT_DAYS - 1, -1, -1)]

    preds = []
    for d in test_days:
        day_end = d + pd.Timedelta(days=1)
        train = df[df["ts"] < d]
        test = df[(df["ts"] >= d) & (df["ts"] < day_end)]
        if test.empty or train.empty:
            continue
        model = _fit_p50(train)
        block = test[["region", "ts", TARGET, "demand_lag_168h"]].copy()
        block["model_pred"] = model.predict(test[FEATURE_COLS])
        block["naive_pred"] = block["demand_lag_168h"]  # seasonal-naive
        preds.append(block)
        print(f"  {d.date()}  trained on {len(train):,} rows, scored {len(test):,}")

    return pd.concat(preds, ignore_index=True)


def summarize(preds: pd.DataFrame) -> pd.DataFrame:
    def _row(g: pd.DataFrame) -> pd.Series:
        model = mean_absolute_percentage_error(g[TARGET], g["model_pred"]) * 100
        naive = mean_absolute_percentage_error(g[TARGET], g["naive_pred"]) * 100
        return pd.Series(
            {
                "model_MAPE_%": model,
                "naive_MAPE_%": naive,
                "improvement_%": naive - model,
                "beats_naive": model < naive,
            }
        )

    per_region = preds.groupby("region").apply(_row, include_groups=False)
    overall = _row(preds).rename("ALL")
    return pd.concat([per_region, overall.to_frame().T])


def main() -> None:
    if not FEATURES_PARQUET.exists():
        sys.exit("ERROR: run build_features first")

    df = pd.read_parquet(FEATURES_PARQUET)
    print(f"Walk-forward backtest over last {HOLDOUT_DAYS} days:\n")
    preds = walk_forward(df)

    report = summarize(preds)
    with pd.option_context("display.float_format", lambda v: f"{v:,.2f}"):
        print("\nModel vs seasonal-naive baseline:")
        print(report.to_string())

    overall = report.loc["ALL"]
    verdict = "✅ MODEL BEATS BASELINE" if overall["beats_naive"] else "❌ MODEL FAILS BASELINE"
    print(
        f"\n{verdict} — model {overall['model_MAPE_%']:.2f}% vs "
        f"naive {overall['naive_MAPE_%']:.2f}% "
        f"({overall['improvement_%']:+.2f} pts)"
    )


if __name__ == "__main__":
    main()
