"""
GridVision — Phase 1 local prototype runner.

Chains the full manual pipeline in order:

    fetch_demand -> fetch_weather -> build_features -> train -> backtest

Usage (from the project root):

    python run_local.py                # run everything (re-fetches from APIs)
    python run_local.py --skip-fetch   # reuse cached data/raw/*.parquet
    python run_local.py --skip-fetch --skip-train   # features + backtest only

This is the Phase-1 deliverable: a single command that takes live API data all
the way to a model validated against a baseline. Phases 2+ move each step into
Airflow / MLflow.
"""
from __future__ import annotations

import argparse
import time

from src import backtest, build_features, fetch_demand, fetch_weather, train


# Runs one pipeline step with a labeled banner and timing.
def _step(name: str, fn) -> None:
    print("\n" + "=" * 70)
    print(f"▶ {name}")
    print("=" * 70)
    t0 = time.perf_counter()
    fn()
    print(f"✔ {name} done in {time.perf_counter() - t0:.1f}s")


# CLI entrypoint: chains fetch/build/train/backtest with optional skip flags.
def main() -> None:
    parser = argparse.ArgumentParser(description="GridVision Phase-1 pipeline")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="reuse cached data/raw/*.parquet instead of re-fetching")
    parser.add_argument("--skip-train", action="store_true",
                        help="skip model training (still runs the backtest)")
    args = parser.parse_args()

    t0 = time.perf_counter()

    if not args.skip_fetch:
        _step("fetch_demand (EIA)", fetch_demand.main)
        _step("fetch_weather (Open-Meteo)", fetch_weather.main)
    else:
        print("Skipping fetch — using cached raw parquet.")

    _step("build_features", build_features.main)

    if not args.skip_train:
        _step("train (LightGBM quantiles)", train.main)

    _step("backtest (walk-forward vs seasonal-naive)", backtest.main)

    print(f"\n🎉 Pipeline complete in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
