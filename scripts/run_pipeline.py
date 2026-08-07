"""
GridVision — live retrain pipeline (GitHub Actions entrypoint).

The GitHub Actions equivalent of dags/demand_retrain_dag.py: same task graph,
run as a single sequential script instead of an Airflow DAG, because Actions
runners are ephemeral and can't host a persistent scheduler. Model promotion
state is git-committed (src/model_store.py) instead of living in an MLflow
registry, so it survives between runs.

Flow: fetch_demand + fetch_weather -> build_features -> train -> backtest ->
gate -> (promote | reject) -> generate_forecast -> write to Postgres.

Run from the project root:
    python scripts/run_pipeline.py

Exits non-zero on any step failure so the Actions run shows red.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Running this file directly (`python scripts/run_pipeline.py`) puts
# scripts/ on sys.path, not the repo root — so `src` isn't importable
# unless we add the root ourselves (module mode `python -m` would do this
# automatically, but the Actions workflow invokes it as a plain script).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import (
    build_features,
    fetch_demand,
    fetch_weather,
    forecaster,
    gate_eval,
    model_store,
    promotion_log,
    train,
)
from src.promote import decide_promotion


# Runs the full fetch → train → gate → promote/reject → forecast pipeline sequentially.
def main() -> None:
    print("=== fetch_demand ===")
    fetch_demand.main()

    print("=== fetch_weather ===")
    fetch_weather.main()

    print("=== build_features ===")
    build_features.main()

    print("=== train ===")
    retrain = train.run_training()

    print("=== backtest ===")
    backtest = gate_eval.evaluate()

    print("=== gate ===")
    decision = decide_promotion(
        candidate_mape=backtest["candidate_mape"],
        baseline_mape=backtest["baseline_mape"],
        production_mape=backtest["production_mape"],
    )
    print(decision.reason)

    if decision.promote:
        version = model_store.set_production(retrain["model_path"], backtest["candidate_mape"])
        decision_name = "promote"
    else:
        version = model_store.production_version()
        decision_name = "reject"

    promotion_log.append_record(
        {
            "decided_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "decision": decision_name,
            "version": str(version) if version is not None else None,
            "candidate_mape": backtest["candidate_mape"],
            "production_mape": backtest["production_mape"],
            "baseline_mape": backtest["baseline_mape"],
            "reason": decision.reason,
        }
    )

    print("=== generate_forecast ===")
    forecast_df = forecaster.generate()
    forecaster.write_to_postgres(forecast_df)

    prod_txt = (
        f"{backtest['production_mape']:.2f}%"
        if backtest["production_mape"] is not None
        else "none (cold start)"
    )
    print(
        "\n=== GridVision retrain summary ===\n"
        f"  candidate           MAPE {backtest['candidate_mape']:.2f}%\n"
        f"  production           {prod_txt}\n"
        f"  seasonal-naive       {backtest['baseline_mape']:.2f}%\n"
        f"  decision: {decision_name.upper()} — {decision.reason}\n"
        f"  forecast rows written: {len(forecast_df)} "
        f"({forecast_df['region'].nunique()} regions)"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure as a non-zero exit
        print(f"\nPIPELINE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
