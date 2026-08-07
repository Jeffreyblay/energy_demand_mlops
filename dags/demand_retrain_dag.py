"""
GridVision — daily demand retrain DAG.

Orchestrates the retrain + evaluation-gate pipeline with the Airflow TaskFlow
API. Storage is still Parquet + sqlite/MLflow-service (Postgres migration is a
later phase), so tasks call the same `src` modules used in the local prototype.

Flow:
    fetch_demand ┐
                 ├→ build_features → retrain_model → backtest_candidate
    fetch_weather┘                                        │
                                                    gate_decision
                                                          │
                                              branch_on_performance
                                              ┌───────────┴───────────┐
                                        promote_model            log_rejection
                                              └───────────┬───────────┘
                                                  generate_forecast
                                                          │
                                                       notify

`generate_forecast` runs after EITHER branch, not just promote_model — even on
a day the gate rejects the candidate, the unchanged production model still
needs a fresh 24h forecast from today's data, or the dashboard goes stale.
`write_dashboard_data` (React/MapLibre-specific payload shaping) arrives in
Phase 6; for now generate_forecast writes straight to Postgres, which is what
FastAPI reads from.
"""
from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

from src import (
    build_features,
    fetch_demand,
    fetch_weather,
    forecaster,
    gate_eval,
    promotion_log,
    registry,
    train,
)
from src.promote import decide_promotion


@dag(
    dag_id="demand_retrain_dag",
    schedule="0 6 * * *",  # 6am daily, after prior day's EIA data finalizes
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    tags=["gridvision", "mlops"],
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=2)},
    doc_md=__doc__,
)
def demand_retrain_dag():
    @task
    def fetch_demand_data() -> str:
        fetch_demand.main()
        return "ok"

    @task
    def fetch_weather_data() -> str:
        fetch_weather.main()
        return "ok"

    @task
    def build_features_task() -> str:
        build_features.main()
        return "ok"

    @task
    def retrain_model() -> dict:
        # Trains candidate, logs + registers a new MLflow version.
        return train.run_training()

    @task
    def backtest_candidate() -> dict:
        # Candidate vs production vs seasonal-naive on the same holdout window.
        return gate_eval.evaluate()

    @task
    def gate_decision(backtest: dict) -> dict:
        d = decide_promotion(
            candidate_mape=backtest["candidate_mape"],
            baseline_mape=backtest["baseline_mape"],
            production_mape=backtest["production_mape"],
        )
        print(d.reason)
        return {"promote": d.promote, "reason": d.reason}

    @task.branch
    def branch_on_performance(decision: dict) -> str:
        return "promote_model" if decision["promote"] else "log_rejection"

    @task
    def promote_model(retrain: dict, backtest: dict, decision: dict) -> None:
        registry.set_production(retrain["version"])
        promotion_log.append_record(
            {
                "decided_at": pendulum.now("UTC").isoformat(),
                "decision": "promote",
                "version": retrain["version"],
                "candidate_mape": backtest["candidate_mape"],
                "production_mape": backtest["production_mape"],
                "baseline_mape": backtest["baseline_mape"],
                "reason": decision["reason"],
            }
        )

    @task
    def log_rejection(retrain: dict, backtest: dict, decision: dict) -> None:
        promotion_log.append_record(
            {
                "decided_at": pendulum.now("UTC").isoformat(),
                "decision": "reject",
                "version": retrain["version"],
                "candidate_mape": backtest["candidate_mape"],
                "production_mape": backtest["production_mape"],
                "baseline_mape": backtest["baseline_mape"],
                "reason": decision["reason"],
            }
        )

    @task(trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
    def generate_forecast() -> dict:
        df = forecaster.generate()
        forecaster.write_to_postgres(df)
        return {"n_rows": len(df), "regions": int(df["region"].nunique())}

    @task(trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
    def notify(retrain: dict, backtest: dict, decision: dict) -> None:
        status = "PROMOTED" if decision["promote"] else "REJECTED"
        prod = backtest["production_mape"]
        prod_txt = f"{prod:.2f}%" if prod is not None else "none (cold start)"
        print(
            "=== GridVision retrain summary ===\n"
            f"  candidate v{retrain['version']}  MAPE {backtest['candidate_mape']:.2f}%\n"
            f"  production            {prod_txt}\n"
            f"  seasonal-naive        {backtest['baseline_mape']:.2f}%\n"
            f"  decision: {status} — {decision['reason']}"
        )

    d = fetch_demand_data()
    w = fetch_weather_data()
    feats = build_features_task()
    retrain = retrain_model()
    backtest = backtest_candidate()
    decision = gate_decision(backtest)
    branch = branch_on_performance(decision)
    promo = promote_model(retrain, backtest, decision)
    rej = log_rejection(retrain, backtest, decision)
    fc = generate_forecast()
    notif = notify(retrain, backtest, decision)

    [d, w] >> feats >> retrain >> backtest >> decision >> branch
    branch >> [promo, rej] >> fc >> notif


demand_retrain_dag()
