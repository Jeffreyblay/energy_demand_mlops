"""
GridVision — Open-Meteo weather ingestion.

Pulls ~2 years of hourly 2m temperature for each region's representative
coordinate from the Open-Meteo ARCHIVE (ERA5) API and writes:

    data/raw/weather.parquet   [ region | ts (UTC) | temperature ]

The archive is keyless. Note ERA5 lags real time by a few days, so the most
recent hours may be null — that is expected and handled downstream.

Run from the project root:

    python -m src.fetch_weather
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import requests

from src.config import (
    OPEN_METEO_ARCHIVE,
    REGION_CODES,
    REGIONS,
    WEATHER_PARQUET,
    date_range,
)

TIMEOUT = 60
POLITE_SLEEP = 0.3


def _fetch_region(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": "temperature_2m",
        "timezone": "UTC",
    }
    r = requests.get(OPEN_METEO_ARCHIVE, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    hourly = r.json()["hourly"]
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(hourly["time"], utc=True),
            "temperature": pd.to_numeric(
                pd.Series(hourly["temperature_2m"]), errors="coerce"
            ),
        }
    )


def fetch_all() -> pd.DataFrame:
    start_d, end_d = date_range()
    start, end = str(start_d), str(end_d)  # archive wants YYYY-MM-DD
    print(f"Fetching Open-Meteo temp {start} → {end} for {len(REGION_CODES)} regions\n")

    frames: list[pd.DataFrame] = []
    for code in REGION_CODES:
        meta = REGIONS[code]
        df = _fetch_region(meta["lat"], meta["lon"], start, end)
        df.insert(0, "region", code)
        n_null = int(df["temperature"].isna().sum())
        frames.append(df)
        print(
            f"  [{code}] {meta['name']:<24} {len(df):>6} rows"
            f"  ({n_null} null temp)"
        )
        time.sleep(POLITE_SLEEP)

    if not frames:
        sys.exit("ERROR: no weather fetched")

    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["region", "ts"])
        .sort_values(["region", "ts"])
        .reset_index(drop=True)
    )


def main() -> None:
    df = fetch_all()
    df.to_parquet(WEATHER_PARQUET, index=False)
    print(f"\nWrote {len(df):,} rows → {WEATHER_PARQUET}")
    print(f"Date span: {df['ts'].min()} → {df['ts'].max()}")


if __name__ == "__main__":
    main()