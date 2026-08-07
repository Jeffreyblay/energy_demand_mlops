"""
GridVision — feature engineering.

Joins raw demand + weather, then builds the model feature set:

    data/features/features.parquet
        region | ts (UTC) | demand_mw (target)
        demand_lag_24h | demand_lag_168h | temperature
        hour_of_day | day_of_week | is_holiday | demand_rolling_7d

Design notes:
- Calendar features are derived from each region's LOCAL time (config `tz`), so
  the daily demand cycle aligns across regions for a single global model.
- Lags/rolling are computed per region on the contiguous hourly grid. Rows whose
  lag/rolling windows aren't fully populated (first 7 days per region) are
  dropped, along with any row still missing a feature.

Run from the project root:

    python -m src.build_features
"""
from __future__ import annotations

import sys

import holidays
import pandas as pd

from src.config import (
    DEMAND_PARQUET,
    FEATURE_COLS,
    FEATURES_PARQUET,
    REGIONS,
    TARGET,
    WEATHER_PARQUET,
)

LAG_24 = 24
LAG_168 = 168
ROLL_WINDOW = 168  # 7 days


def _load() -> pd.DataFrame:
    if not DEMAND_PARQUET.exists() or not WEATHER_PARQUET.exists():
        sys.exit("ERROR: run fetch_demand and fetch_weather first")
    demand = pd.read_parquet(DEMAND_PARQUET)
    weather = pd.read_parquet(WEATHER_PARQUET)
    df = demand.merge(weather, on=["region", "ts"], how="inner")
    return df.sort_values(["region", "ts"]).reset_index(drop=True)


def _add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """hour_of_day / day_of_week / is_holiday from each region's LOCAL time."""
    parts = []
    # US federal holidays over the span (national by date).
    years = range(df["ts"].dt.year.min(), df["ts"].dt.year.max() + 1)
    us_holidays = holidays.US(years=list(years))

    for code, sub in df.groupby("region", sort=False):
        local = sub["ts"].dt.tz_convert(REGIONS[code]["tz"])
        sub = sub.copy()
        sub["hour_of_day"] = local.dt.hour
        sub["day_of_week"] = local.dt.dayofweek
        sub["is_holiday"] = local.dt.date.isin(us_holidays).astype(int)
        parts.append(sub)

    return pd.concat(parts).sort_values(["region", "ts"]).reset_index(drop=True)


def _add_lags(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("region", sort=False)["demand_mw"]
    df["demand_lag_24h"] = g.shift(LAG_24)
    df["demand_lag_168h"] = g.shift(LAG_168)
    # Rolling mean of the PRIOR 7 days (shift(1) so the current hour is excluded).
    df["demand_rolling_7d"] = g.transform(
        lambda s: s.shift(1).rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).mean()
    )
    return df


def build() -> pd.DataFrame:
    df = _load()
    n_raw = len(df)

    # Non-physical demand (<= 0, e.g. EIA reporting outages) is treated as
    # missing, then interpolated per region on the contiguous hourly grid.
    # Interpolating (vs dropping) preserves the hourly index the lags rely on.
    n_bad = int((df["demand_mw"] <= 0).sum()) + int(df["demand_mw"].isna().sum())
    df.loc[df["demand_mw"] <= 0, "demand_mw"] = pd.NA
    df["demand_mw"] = df.groupby("region", sort=False)["demand_mw"].transform(
        lambda s: s.interpolate(limit=12)
    )
    print(f"Cleaned {n_bad} non-physical/missing demand values via interpolation")

    df = _add_calendar(df)
    df = _add_lags(df)

    cols = ["region", "ts", TARGET] + FEATURE_COLS
    df = df[cols]

    before = len(df)
    df = df.dropna().reset_index(drop=True)
    print(f"Rows: {n_raw:,} joined → {before:,} → {len(df):,} after dropping "
          f"warm-up/NaN ({before - len(df):,} dropped)")
    return df


def main() -> None:
    df = build()
    df.to_parquet(FEATURES_PARQUET, index=False)
    print(f"\nWrote {len(df):,} rows → {FEATURES_PARQUET}")
    print(f"Regions: {df['region'].nunique()}  |  span {df['ts'].min()} → {df['ts'].max()}")
    print("\nFeature preview (first ERCOT row with full windows):")
    with pd.option_context("display.max_columns", None, "display.width", 160):
        print(df[df.region == "ERCO"].head(1).to_string(index=False))
    print("\nTarget summary by region (demand_mw):")
    print(df.groupby("region")["demand_mw"].agg(["mean", "min", "max"]).round(0))


if __name__ == "__main__":
    main()
