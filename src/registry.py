"""
GridVision — MLflow model registry helpers.

Thin wrapper around the MLflow client for the operations the pipeline needs:
list versions, set the `production` alias, and load the production model back.
The Phase 3-4 promotion gate will call `set_production()`; FastAPI/forecast code
will call `load_production()`.

CLI (from the project root):

    python -m src.registry                 # show registry status
    python -m src.registry --promote-latest # alias newest version as production
    python -m src.registry --promote 3      # alias version 3 as production
    python -m src.registry --check          # load production model + predict sample
"""
from __future__ import annotations

import argparse

import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

from src.config import (
    FEATURE_COLS,
    FEATURES_PARQUET,
    MLFLOW_TRACKING_URI,
    PRODUCTION_ALIAS,
    REGISTERED_MODEL_NAME,
)

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)


def _client() -> MlflowClient:
    return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)


def list_versions() -> list:
    c = _client()
    versions = c.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")
    return sorted(versions, key=lambda v: int(v.version))


def latest_version() -> str | None:
    versions = list_versions()
    return versions[-1].version if versions else None


def production_version() -> str | None:
    """Version currently aliased `production`, or None if unset."""
    try:
        mv = _client().get_model_version_by_alias(REGISTERED_MODEL_NAME, PRODUCTION_ALIAS)
        return mv.version
    except Exception:
        return None


def set_production(version: str) -> None:
    _client().set_registered_model_alias(
        REGISTERED_MODEL_NAME, PRODUCTION_ALIAS, str(version)
    )
    print(f"Set {REGISTERED_MODEL_NAME}@{PRODUCTION_ALIAS} → v{version}")


def load_production():
    """Load the production-aliased QuantileForecaster as an MLflow pyfunc."""
    uri = f"models:/{REGISTERED_MODEL_NAME}@{PRODUCTION_ALIAS}"
    return mlflow.pyfunc.load_model(uri)


def _status() -> None:
    versions = list_versions()
    prod = production_version()
    if not versions:
        print(f"No versions registered for '{REGISTERED_MODEL_NAME}' yet. Run train.")
        return
    print(f"Registered model: {REGISTERED_MODEL_NAME}")
    for v in versions:
        marker = "  <-- production" if v.version == prod else ""
        print(f"  v{v.version:<3} run={v.run_id[:8]}{marker}")
    if prod is None:
        print("No production alias set. Use --promote-latest.")


def _check() -> None:
    """Load production model and predict on the most recent feature rows."""
    prod = production_version()
    if prod is None:
        print("No production model set — run --promote-latest first.")
        return
    model = load_production()
    df = pd.read_parquet(FEATURES_PARQUET).sort_values("ts").tail(3)
    preds = model.predict(df[FEATURE_COLS])
    out = df[["region", "ts"]].reset_index(drop=True).join(preds.reset_index(drop=True))
    print(f"Loaded {REGISTERED_MODEL_NAME}@{PRODUCTION_ALIAS} (v{prod}). Sample predictions:")
    with pd.option_context("display.float_format", lambda v: f"{v:,.1f}", "display.width", 160):
        print(out.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="GridVision MLflow registry")
    parser.add_argument("--promote-latest", action="store_true")
    parser.add_argument("--promote", metavar="VERSION")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.promote_latest:
        v = latest_version()
        if v is None:
            print("Nothing to promote — no registered versions.")
        else:
            set_production(v)
    elif args.promote:
        set_production(args.promote)
    elif args.check:
        _check()
    else:
        _status()


if __name__ == "__main__":
    main()
