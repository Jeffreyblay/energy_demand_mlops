"""
GridVision — central configuration.

Single source of truth for regions, paths, the training window, and model
hyperparameters. Every pipeline module imports from here so there are no magic
constants scattered around.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FEATURES_DIR = DATA_DIR / "features"
MODELS_DIR = DATA_DIR / "models"

DEMAND_PARQUET = RAW_DIR / "demand.parquet"
WEATHER_PARQUET = RAW_DIR / "weather.parquet"
FEATURES_PARQUET = FEATURES_DIR / "features.parquet"

for _d in (RAW_DIR, FEATURES_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Secrets / endpoints
# --------------------------------------------------------------------------- #
EIA_API_KEY = os.getenv("EIA_API_KEY", "").strip()
EIA_BASE = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
# Forecast (not archive) endpoint — used by forecaster.py for FUTURE hours,
# since actual future temperature isn't observed yet.
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# --------------------------------------------------------------------------- #
# Postgres (Phase 5+) — project data: regions, forecasts, promotion log.
# Distinct from Airflow's OWN metadata Postgres in docker-compose.yaml (that
# one is internal to Airflow and never touched by application code).
# Default matches .env for host-side tools (psql, local uvicorn); the Airflow
# containers override this to the Compose DNS name ("db") via docker-compose.yaml.
# --------------------------------------------------------------------------- #
POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN", "postgresql://gridvision:gridvision@localhost:5432/gridvision"
)

# --------------------------------------------------------------------------- #
# MLflow (Phase 2+)
# --------------------------------------------------------------------------- #
# Default to a local sqlite tracking DB in the project root; artifacts land in
# ./mlartifacts. Override via MLFLOW_TRACKING_URI in .env (e.g. a remote server).
MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI", f"sqlite:///{(PROJECT_ROOT / 'mlflow.db').as_posix()}"
)
MLFLOW_EXPERIMENT = "gridvision_demand"
REGISTERED_MODEL_NAME = "gridvision_demand"
PRODUCTION_ALIAS = "production"

# --------------------------------------------------------------------------- #
# Regions — the 9 unique balancing authorities.
# NOTE: the design doc listed 10, but "SPP" and "Southwest Power Pool" are the
# same BA (respondent SWPP). `code` is the EIA respondent code; lat/lon is a
# representative point per BA used only for weather.
# --------------------------------------------------------------------------- #
REGIONS: dict[str, dict] = {
    "ERCO": {"name": "ERCOT (Texas)",        "lat": 29.76, "lon": -95.37,  "tz": "America/Chicago"},
    "MISO": {"name": "Midcontinent ISO",     "lat": 39.77, "lon": -86.16,  "tz": "America/Chicago"},
    "PJM":  {"name": "PJM Interconnection",  "lat": 39.95, "lon": -75.17,  "tz": "America/New_York"},
    "NYIS": {"name": "New York ISO",         "lat": 40.71, "lon": -74.01,  "tz": "America/New_York"},
    "ISNE": {"name": "ISO New England",      "lat": 42.36, "lon": -71.06,  "tz": "America/New_York"},
    "SWPP": {"name": "Southwest Power Pool", "lat": 37.69, "lon": -97.34,  "tz": "America/Chicago"},
    "CISO": {"name": "California ISO",        "lat": 34.05, "lon": -118.24, "tz": "America/Los_Angeles"},
    "PACW": {"name": "PacifiCorp West",      "lat": 45.52, "lon": -122.68, "tz": "America/Los_Angeles"},
    "PACE": {"name": "PacifiCorp East",      "lat": 40.76, "lon": -111.89, "tz": "America/Denver"},
}
REGION_CODES = list(REGIONS)

# --------------------------------------------------------------------------- #
# Training window
# --------------------------------------------------------------------------- #
HISTORY_DAYS = 730  # ~2 years rolling window

# Number of most-recent days held out for evaluation.
HOLDOUT_DAYS = 7

# How far ahead generate_forecast predicts. Kept to 24h so demand_lag_24h
# always resolves to an already-observed hour (no recursive multi-step
# forecasting needed) — see src/forecaster.py.
FORECAST_HORIZON_HOURS = 24


# Returns the (start, end) date span covering the last `history_days`, ending yesterday.
def date_range(history_days: int = HISTORY_DAYS) -> tuple[date, date]:
    """(start, end) covering the last `history_days`, ending yesterday.

    Yesterday because EIA finalizes the prior day's hourly data on a lag.
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=history_days)
    return start, end


# --------------------------------------------------------------------------- #
# Features / target
# --------------------------------------------------------------------------- #
TARGET = "demand_mw"

FEATURE_COLS = [
    "demand_lag_24h",
    "demand_lag_168h",
    "temperature",
    "hour_of_day",
    "day_of_week",
    "is_holiday",
    "demand_rolling_7d",
]

# --------------------------------------------------------------------------- #
# LightGBM — quantile regression for P10 / P50 / P90 intervals
# --------------------------------------------------------------------------- #
QUANTILES = {"p10": 0.10, "p50": 0.50, "p90": 0.90}

LGBM_PARAMS = {
    "objective": "quantile",
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 30,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}