"""
GridVision — git-committed model store (replaces the MLflow registry).

GitHub Actions runners are ephemeral: each scheduled run starts from a clean
checkout with no memory of yesterday's "production" model. MLflow's registry
solved that with a persistent tracking server, but there's nowhere free to
keep one running continuously. Instead, the production model IS a file in
the repo — `models/production/model.joblib` + `models/production/metadata.json`
— committed back to git by the workflow whenever the gate promotes a
candidate. Reading it back next run is just `git checkout` + a file read.

Bundle shape matches src/train.py's MODEL_PATH exactly: a dict of
{"p10": booster, "p50": booster, "p90": booster, "features": [...], "trained_at": ...}.

CLI (from the project root):

    python -m src.model_store                 # show current production status
    python -m src.model_store --check          # load production model + predict sample
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from src.config import FEATURE_COLS, FEATURES_PARQUET, PROJECT_ROOT

PRODUCTION_DIR = PROJECT_ROOT / "models" / "production"
PRODUCTION_MODEL_PATH = PRODUCTION_DIR / "model.joblib"
PRODUCTION_METADATA_PATH = PRODUCTION_DIR / "metadata.json"

QUANTILE_KEYS = ("p10", "p50", "p90")


class _QuantileModel:
    """Predict-only wrapper around a joblib quantile bundle — the same
    interface QuantileForecaster (src/model.py) exposed via MLflow pyfunc,
    minus MLflow."""

    # Unpacks the joblib bundle into per-quantile boosters and the feature column list.
    def __init__(self, bundle: dict) -> None:
        self._models = {q: bundle[q] for q in QUANTILE_KEYS}
        self._features = bundle["features"]

    # Predicts all three quantiles for the given input and returns them as a DataFrame.
    def predict(self, model_input: pd.DataFrame) -> pd.DataFrame:
        X = model_input[self._features]
        out = pd.DataFrame(index=model_input.index)
        for q in QUANTILE_KEYS:
            out[q] = self._models[q].predict(X)
        return out


# Reads the current production model version from metadata, or None if unset.
def production_version() -> int | None:
    """Version currently in production, or None if none has been set yet."""
    if not PRODUCTION_METADATA_PATH.exists():
        return None
    return json.loads(PRODUCTION_METADATA_PATH.read_text())["version"]


# Loads the current production quantile bundle from disk.
def load_production() -> _QuantileModel:
    """Load the production quantile bundle."""
    bundle = joblib.load(PRODUCTION_MODEL_PATH)
    return _QuantileModel(bundle)


# Copies the candidate model over production, bumps the version, and writes metadata.
def set_production(candidate_model_path: Path, mape: float) -> int:
    """Promote the candidate at `candidate_model_path` to production.

    Copies the candidate bundle over the production one, bumps the version,
    and writes metadata. Does NOT git-commit — the caller (a GitHub Actions
    workflow step, or a human running this locally) is responsible for that,
    so this function behaves identically whether or not it's inside CI.
    """
    prior = production_version()
    version = (prior or 0) + 1

    PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate_model_path, PRODUCTION_MODEL_PATH)
    PRODUCTION_METADATA_PATH.write_text(
        json.dumps(
            {
                "version": version,
                "mape": mape,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )
    print(f"Set production → v{version} (MAPE {mape:.3f}%)")
    return version


# Prints the current production model's version, MAPE, and promotion timestamp.
def _status() -> None:
    version = production_version()
    if version is None:
        print("No production model set yet (cold start).")
        return
    meta = json.loads(PRODUCTION_METADATA_PATH.read_text())
    print(f"Production model: v{meta['version']}")
    print(f"  MAPE        : {meta['mape']:.3f}%")
    print(f"  promoted_at : {meta['promoted_at']}")


# Loads the production model and prints sample predictions on recent feature rows.
def _check() -> None:
    """Load production model and predict on the most recent feature rows."""
    if production_version() is None:
        print("No production model set — nothing to check.")
        return
    model = load_production()
    df = pd.read_parquet(FEATURES_PARQUET).sort_values("ts").tail(3)
    preds = model.predict(df[FEATURE_COLS])
    out = df[["region", "ts"]].reset_index(drop=True).join(preds.reset_index(drop=True))
    print("Loaded production model. Sample predictions:")
    with pd.option_context("display.float_format", lambda v: f"{v:,.1f}", "display.width", 160):
        print(out.to_string(index=False))


# CLI entrypoint: shows production status, or runs a sample prediction check with --check.
def main() -> None:
    parser = argparse.ArgumentParser(description="GridVision git-committed model store")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        _check()
    else:
        _status()


if __name__ == "__main__":
    main()
