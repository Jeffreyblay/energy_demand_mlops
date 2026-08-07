"""
GridVision — Postgres helpers (Phase 5+).

Project data lives here: a static `region` reference table, `forecast`
(forward-looking P10/P50/P90 per region/hour), `region_summary` (latest
per-region snapshot for the dashboard), and `promotion_log` (the gate's audit
trail, migrated off Parquet — see src/promotion_log.py).

Distinct from Airflow's OWN metadata Postgres in docker-compose.yaml — that
one is internal to Airflow (DAG runs, task state) and application code never
touches it. This module talks to the separate `db` service.

Run from the project root to (re)create the schema:
    python -m src.db
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import POSTGRES_DSN, REGIONS

_engine: Engine | None = None


# Returns the module-level SQLAlchemy engine, creating it on first call.
def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(POSTGRES_DSN, pool_pre_ping=True)
    return _engine


SCHEMA_STATEMENTS = [
    # Enables ST_MakePoint/ST_Buffer/ST_DWithin used by the coverage/nearby
    # queries in api/main.py. region/forecast keep plain lat/lon floats —
    # geometry is constructed inline from those at query time, so no
    # migration/backfill is needed for existing rows.
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """
    CREATE TABLE IF NOT EXISTS region (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        lat DOUBLE PRECISION NOT NULL,
        lon DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast (
        region_code TEXT NOT NULL REFERENCES region(code),
        ts TIMESTAMPTZ NOT NULL,
        model_version TEXT,
        p10 DOUBLE PRECISION NOT NULL,
        p50 DOUBLE PRECISION NOT NULL,
        p90 DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (region_code, ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS region_summary (
        region_code TEXT PRIMARY KEY REFERENCES region(code),
        updated_at TIMESTAMPTZ NOT NULL,
        peak_forecast_mw DOUBLE PRECISION,
        delta_vs_prior_run_mw DOUBLE PRECISION,
        temperature DOUBLE PRECISION,
        model_version TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promotion_log (
        id SERIAL PRIMARY KEY,
        decided_at TIMESTAMPTZ NOT NULL,
        decision TEXT NOT NULL,
        version TEXT,
        candidate_mape DOUBLE PRECISION,
        production_mape DOUBLE PRECISION,
        baseline_mape DOUBLE PRECISION,
        reason TEXT
    )
    """,
]

_UPSERT_REGION = text(
    """
    INSERT INTO region (code, name, lat, lon)
    VALUES (:code, :name, :lat, :lon)
    ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon
    """
)


# Creates all tables/extensions if missing and upserts the static region reference data.
def init_schema() -> None:
    """Create tables if missing and seed/refresh the static region table.

    Idempotent and cheap (CREATE TABLE IF NOT EXISTS + upserts) — safe to call
    at the top of every writer, not just once.
    """
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(text(stmt))
        for code, meta in REGIONS.items():
            conn.execute(
                _UPSERT_REGION,
                {"code": code, "name": meta["name"], "lat": meta["lat"], "lon": meta["lon"]},
            )


if __name__ == "__main__":
    init_schema()
    print("Schema ready.")
