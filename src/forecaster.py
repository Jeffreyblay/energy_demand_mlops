"""
GridVision — forward-looking forecast generation.

Produces a genuine forecast for the next FORECAST_HORIZON_HOURS (24h) per
region, using the current production model, and writes it to Postgres.

Scoped to 24h deliberately: within that window `demand_lag_24h` and
`demand_lag_168h` always resolve to already-observed actual demand (the
lookback never crosses into the forecast horizon itself), so no recursive
multi-step forecasting is needed. Temperature comes from Open-Meteo's
FORECAST endpoint (not the ARCHIVE one fetch_weather.py uses) — future
temperature isn't observed yet, only predicted.

Run from the project root:
    python -m src.forecaster
"""
from __future__ import annotations

import holidays
import pandas as pd
import requests
from sqlalchemy import text

from src import model_store
from src.config import (
    FEATURE_COLS,
    FEATURES_PARQUET,
    FORECAST_HORIZON_HOURS,
    OPEN_METEO_FORECAST,
    REGIONS,
    REGION_CODES,
)
from src.db import get_engine, init_schema

TIMEOUT = 30


def _fetch_forecast_temp(lat: float, lon: float, hours: int) -> pd.DataFrame:
    """Hourly temperature FORECAST (not archive), UTC, for the next `hours` hours."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "forecast_days": 2,  # guarantees >= `hours` of future coverage
        "timezone": "UTC",
    }
    r = requests.get(OPEN_METEO_FORECAST, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    hourly = r.json()["hourly"]
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(hourly["time"], utc=True),
            "temperature": pd.to_numeric(pd.Series(hourly["temperature_2m"]), errors="coerce"),
        }
    )
    now = pd.Timestamp.now(tz="UTC").floor("h")
    return df[(df["ts"] > now) & (df["ts"] <= now + pd.Timedelta(hours=hours))]


def _build_future_rows(region: str, history: pd.DataFrame) -> pd.DataFrame:
    """Feature rows for the next FORECAST_HORIZON_HOURS hours for one region."""
    meta = REGIONS[region]
    hist = history[history["region"] == region].sort_values("ts").set_index("ts")

    weather = _fetch_forecast_temp(meta["lat"], meta["lon"], FORECAST_HORIZON_HOURS)
    if weather.empty:
        raise RuntimeError(f"no forecast weather returned for {region}")

    years = range(weather["ts"].dt.year.min(), weather["ts"].dt.year.max() + 1)
    us_holidays = holidays.US(years=list(years))

    rows = []
    for w in weather.itertuples(index=False):
        ts = w.ts
        lag_24 = hist["demand_mw"].asof(ts - pd.Timedelta(hours=24))
        lag_168 = hist["demand_mw"].asof(ts - pd.Timedelta(hours=168))
        roll_window = hist.loc[: ts - pd.Timedelta(hours=1)].tail(168)["demand_mw"]
        local = ts.tz_convert(meta["tz"])
        rows.append(
            {
                "region": region,
                "ts": ts,
                "demand_lag_24h": lag_24,
                "demand_lag_168h": lag_168,
                "temperature": w.temperature,
                "hour_of_day": local.hour,
                "day_of_week": local.dayofweek,
                "is_holiday": int(local.date() in us_holidays),
                "demand_rolling_7d": roll_window.mean() if len(roll_window) else None,
            }
        )
    return pd.DataFrame(rows)


def generate() -> pd.DataFrame:
    """Forecast the next FORECAST_HORIZON_HOURS hours for every region."""
    if not FEATURES_PARQUET.exists():
        raise RuntimeError("run build_features first")
    history = pd.read_parquet(FEATURES_PARQUET)[["region", "ts", "demand_mw"]]

    model = model_store.load_production()
    prod_version = model_store.production_version()
    if prod_version is None:
        raise RuntimeError("no production model set — run the gate first")

    frames = [_build_future_rows(code, history) for code in REGION_CODES]
    future = pd.concat(frames, ignore_index=True)

    before = len(future)
    future = future.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    if len(future) < before:
        print(f"Dropped {before - len(future)} forecast rows missing a feature")

    # Match build_features.py's dtypes: hour_of_day/day_of_week come from
    # `.dt.hour`/`.dt.dayofweek` there (int32), but scalar Timestamp.hour/
    # .dayofweek here default to pandas' int64 — keep them aligned with
    # what the model was trained on.
    future["hour_of_day"] = future["hour_of_day"].astype("int32")
    future["day_of_week"] = future["day_of_week"].astype("int32")

    preds = model.predict(future[FEATURE_COLS])
    out = future[["region", "ts", "temperature"]].copy()
    out["p10"], out["p50"], out["p90"] = preds["p10"], preds["p50"], preds["p90"]
    out["model_version"] = prod_version
    return out


def write_to_postgres(df: pd.DataFrame) -> None:
    """Upsert into `forecast`, then refresh the per-region `region_summary`."""
    init_schema()
    engine = get_engine()
    now = pd.Timestamp.now(tz="UTC")

    with engine.begin() as conn:
        for row in df.itertuples(index=False):
            conn.execute(
                text(
                    """
                    INSERT INTO forecast (region_code, ts, model_version, p10, p50, p90)
                    VALUES (:region, :ts, :model_version, :p10, :p50, :p90)
                    ON CONFLICT (region_code, ts) DO UPDATE
                        SET model_version = EXCLUDED.model_version,
                            p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90
                    """
                ),
                {
                    "region": row.region,
                    "ts": row.ts.to_pydatetime(),
                    "model_version": row.model_version,
                    "p10": float(row.p10),
                    "p50": float(row.p50),
                    "p90": float(row.p90),
                },
            )

        prior_peaks = dict(
            conn.execute(
                text("SELECT region_code, peak_forecast_mw FROM region_summary")
            ).all()
        )

        for region, g in df.groupby("region"):
            g = g.sort_values("ts")
            peak = float(g["p50"].max())
            prev_peak = prior_peaks.get(region)
            conn.execute(
                text(
                    """
                    INSERT INTO region_summary
                        (region_code, updated_at, peak_forecast_mw,
                         delta_vs_prior_run_mw, temperature, model_version)
                    VALUES (:region, :now, :peak, :delta, :temp, :version)
                    ON CONFLICT (region_code) DO UPDATE
                        SET updated_at = EXCLUDED.updated_at,
                            peak_forecast_mw = EXCLUDED.peak_forecast_mw,
                            delta_vs_prior_run_mw = EXCLUDED.delta_vs_prior_run_mw,
                            temperature = EXCLUDED.temperature,
                            model_version = EXCLUDED.model_version
                    """
                ),
                {
                    "region": region,
                    "now": now.to_pydatetime(),
                    "peak": peak,
                    "delta": (peak - prev_peak) if prev_peak is not None else None,
                    "temp": float(g["temperature"].iloc[0]),
                    "version": g["model_version"].iloc[0],
                },
            )


if __name__ == "__main__":
    forecast_df = generate()
    write_to_postgres(forecast_df)
    print(f"Wrote {len(forecast_df)} forecast rows for {forecast_df['region'].nunique()} regions")
    print(forecast_df.head(10).to_string(index=False))
