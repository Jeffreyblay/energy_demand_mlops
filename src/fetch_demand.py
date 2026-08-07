"""
GridVision — EIA demand ingestion.

Pulls ~2 years of hourly electricity demand (type=D) for all 9 balancing
authorities from EIA API v2 and writes a single tidy Parquet file:

    data/raw/demand.parquet   [ region | ts (UTC) | demand_mw ]

Run from the project root:

    python -m src.fetch_demand
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import requests

from src.config import (
    DEMAND_PARQUET,
    EIA_API_KEY,
    EIA_BASE,
    REGION_CODES,
    REGIONS,
    date_range,
)

PAGE = 5000          # EIA max rows per request
TIMEOUT = 60
POLITE_SLEEP = 0.2   # seconds between requests


def _fetch_region(code: str, start: str, end: str) -> list[dict]:
    """Paginate through all hourly demand rows for one respondent."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": code,
            "facets[type][]": "D",  # D = Demand
            "start": start,
            "end": end,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": offset,
            "length": PAGE,
        }
        r = requests.get(EIA_BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()["response"]
        batch = payload["data"]
        rows.extend(batch)

        total = int(payload.get("total", len(rows)))
        offset += PAGE
        if offset >= total or not batch:
            break
        time.sleep(POLITE_SLEEP)

    return rows


def fetch_all() -> pd.DataFrame:
    if not EIA_API_KEY:
        sys.exit("ERROR: EIA_API_KEY is empty — add it to .env")

    start_d, end_d = date_range()
    start = f"{start_d}T00"
    end = f"{end_d}T23"
    print(f"Fetching EIA demand {start} → {end} for {len(REGION_CODES)} regions\n")

    frames: list[pd.DataFrame] = []
    for code in REGION_CODES:
        raw = _fetch_region(code, start, end)
        df = pd.DataFrame(raw)
        if df.empty:
            print(f"  [{code}] {REGIONS[code]['name']:<24} WARNING: 0 rows")
            continue
        out = pd.DataFrame(
            {
                "region": code,
                "ts": pd.to_datetime(df["period"], utc=True),
                "demand_mw": pd.to_numeric(df["value"], errors="coerce"),
            }
        )
        n_null = int(out["demand_mw"].isna().sum())
        frames.append(out)
        print(
            f"  [{code}] {REGIONS[code]['name']:<24} {len(out):>6} rows"
            f"  ({n_null} null demand)"
        )

    if not frames:
        sys.exit("ERROR: no data fetched for any region")

    result = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["region", "ts"])
        .sort_values(["region", "ts"])
        .reset_index(drop=True)
    )
    return result


def main() -> None:
    df = fetch_all()
    df.to_parquet(DEMAND_PARQUET, index=False)
    print(f"\nWrote {len(df):,} rows → {DEMAND_PARQUET}")
    print(f"Date span: {df['ts'].min()} → {df['ts'].max()}")
    print(f"Regions:   {df['region'].nunique()} / {len(REGION_CODES)}")


if __name__ == "__main__":
    main()