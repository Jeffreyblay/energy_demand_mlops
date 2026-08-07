"""
GridVision — API connectivity smoke test.

Run this ONCE (after putting your EIA key in .env) to confirm both data sources
respond before we build the real pipeline. It is a throwaway diagnostic, not
part of the pipeline.

    conda activate energy-mlops
    pip install -r requirements-dev.txt   # requests + python-dotenv
    python check_apis.py                  # test one region (ERCO)
    python check_apis.py --all            # test all 9 regions

Exit code 0 = everything reachable; 1 = at least one failure.
"""
from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY", "").strip()

EIA_BASE = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# The 9 unique balancing authorities. NOTE: the design doc listed "SPP" and
# "Southwest Power Pool" separately, but they are the same BA (respondent SWPP),
# so there are 9 unique regions, not 10.
# Coordinates are a representative point per BA, used only for weather.
REGIONS = {
    "ERCO": {"name": "ERCOT (Texas)",        "lat": 29.76, "lon": -95.37},
    "MISO": {"name": "Midcontinent ISO",     "lat": 39.77, "lon": -86.16},
    "PJM":  {"name": "PJM Interconnection",  "lat": 39.95, "lon": -75.17},
    "NYIS": {"name": "New York ISO",         "lat": 40.71, "lon": -74.01},
    "ISNE": {"name": "ISO New England",      "lat": 42.36, "lon": -71.06},
    "SWPP": {"name": "Southwest Power Pool", "lat": 37.69, "lon": -97.34},
    "CISO": {"name": "California ISO",        "lat": 34.05, "lon": -118.24},
    "PACW": {"name": "PacifiCorp West",      "lat": 45.52, "lon": -122.68},
    "PACE": {"name": "PacifiCorp East",      "lat": 40.76, "lon": -111.89},
}

TIMEOUT = 30


# Checks EIA connectivity by pulling the most recent hourly demand for one respondent.
def check_eia(respondent: str) -> tuple[bool, str]:
    """Pull the most recent hourly demand (type=D) for one respondent."""
    if not EIA_API_KEY:
        return False, "EIA_API_KEY is empty — add it to .env"

    params = {
        "api_key": EIA_API_KEY,
        "frequency": "hourly",
        "data[0]": "value",
        "facets[respondent][]": respondent,
        "facets[type][]": "D",  # D = Demand
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": 5,
    }
    try:
        r = requests.get(EIA_BASE, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f"network error: {e}"

    if r.status_code == 403:
        return False, "403 Forbidden — API key rejected (check the key)"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"

    try:
        rows = r.json()["response"]["data"]
    except (ValueError, KeyError) as e:
        return False, f"unexpected response shape: {e}"

    if not rows:
        return False, "200 OK but no data rows returned"

    latest = rows[0]
    return True, (
        f"latest {latest['period']} = {latest['value']} "
        f"{latest.get('value-units', 'MWh')}"
    )


# Checks Open-Meteo connectivity by pulling recent hourly temperature for a coordinate.
def check_open_meteo(lat: float, lon: float) -> tuple[bool, str]:
    """Pull recent hourly 2m temperature for a coordinate."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "past_days": 2,
        "forecast_days": 1,
        "timezone": "UTC",
    }
    try:
        r = requests.get(OPEN_METEO_BASE, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f"network error: {e}"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"

    try:
        hourly = r.json()["hourly"]
        times, temps = hourly["time"], hourly["temperature_2m"]
    except (ValueError, KeyError) as e:
        return False, f"unexpected response shape: {e}"

    if not times:
        return False, "200 OK but no hourly data"

    return True, f"{len(times)} hrs, latest {times[-1]} = {temps[-1]}°C"


# CLI entrypoint: runs the EIA + Open-Meteo smoke test for one or all regions.
def main() -> int:
    parser = argparse.ArgumentParser(description="GridVision API smoke test")
    parser.add_argument(
        "--all", action="store_true", help="test all 9 regions (default: ERCO only)"
    )
    args = parser.parse_args()

    codes = list(REGIONS) if args.all else ["ERCO"]

    print("=" * 68)
    print("GridVision API smoke test")
    print(f"EIA key: {'present (' + str(len(EIA_API_KEY)) + ' chars)' if EIA_API_KEY else 'MISSING'}")
    print("=" * 68)

    all_ok = True
    for code in codes:
        region = REGIONS[code]
        print(f"\n[{code}] {region['name']}")

        eia_ok, eia_msg = check_eia(code)
        print(f"  EIA demand   : {'OK  ' if eia_ok else 'FAIL'} — {eia_msg}")

        wx_ok, wx_msg = check_open_meteo(region["lat"], region["lon"])
        print(f"  Open-Meteo   : {'OK  ' if wx_ok else 'FAIL'} — {wx_msg}")

        all_ok = all_ok and eia_ok and wx_ok

    print("\n" + "=" * 68)
    print("RESULT:", "ALL PASS ✅" if all_ok else "FAILURES ❌ — see above")
    print("=" * 68)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
