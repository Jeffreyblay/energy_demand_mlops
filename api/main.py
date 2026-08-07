"""
GridVision — FastAPI forecast-serving layer.

Reads PRE-COMPUTED forecasts, region summaries, and the promotion/rejection
history from Postgres (written by dags/demand_retrain_dag.py). This API NEVER
recomputes a forecast on request — that split (DAG writes, API only reads) is
a deliberate design-doc constraint: forecasting is expensive and scheduled,
serving must be cheap and fast.

Run locally (against the Dockerized `db` service, exposed on host :5432):
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.db import get_engine

app = FastAPI(title="GridVision API", version="0.1.0")

# Dashboard dev server (Vite) runs on a different origin/port than the API —
# without this, the browser blocks every request before it even reaches us.
# In production this is the GitHub Pages origin (set DASHBOARD_ORIGIN, e.g.
# "https://<username>.github.io"); defaults to "*" for local dev when unset.
_dashboard_origin = os.getenv("DASHBOARD_ORIGIN", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_dashboard_origin],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    try:
        with get_engine().begin() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok}


@app.get("/regions")
def regions() -> dict:
    """GeoJSON FeatureCollection — one Point feature per balancing authority.

    Shaped for MapLibre GL JS: drop straight into a GeoJSON source and extrude
    by `peak_forecast_mw` for the Phase-6 3D dashboard.
    """
    with get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT r.code, r.name, r.lat, r.lon,
                       s.peak_forecast_mw, s.delta_vs_prior_run_mw,
                       s.temperature, s.model_version, s.updated_at
                FROM region r
                LEFT JOIN region_summary s ON s.region_code = r.code
                ORDER BY r.code
                """
            )
        ).mappings().all()

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": {
                    "code": row["code"],
                    "name": row["name"],
                    "peak_forecast_mw": row["peak_forecast_mw"],
                    "delta_vs_prior_run_mw": row["delta_vs_prior_run_mw"],
                    "temperature": row["temperature"],
                    "model_version": row["model_version"],
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                },
            }
            for row in rows
        ],
    }


@app.get("/forecast")
def forecast(region: str) -> dict:
    """Hourly P10/P50/P90 for the requested region's forecast horizon."""
    region = region.upper()
    with get_engine().begin() as conn:
        if conn.execute(text("SELECT 1 FROM region WHERE code = :code"), {"code": region}).first() is None:
            raise HTTPException(404, f"unknown region '{region}'")

        rows = conn.execute(
            text(
                """
                SELECT ts, p10, p50, p90, model_version
                FROM forecast
                WHERE region_code = :code
                ORDER BY ts
                """
            ),
            {"code": region},
        ).mappings().all()

    return {
        "region": region,
        "hours": [
            {
                "ts": row["ts"].isoformat(),
                "p10": row["p10"],
                "p50": row["p50"],
                "p90": row["p90"],
                "model_version": row["model_version"],
            }
            for row in rows
        ],
    }


@app.get("/history")
def history(limit: int = 50) -> dict:
    """Recent promotion/rejection gate decisions — the audit trail."""
    limit = max(1, min(limit, 500))
    with get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT decided_at, decision, version, candidate_mape,
                       production_mape, baseline_mape, reason
                FROM promotion_log
                ORDER BY decided_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()

    return {
        "decisions": [
            {
                "decided_at": row["decided_at"].isoformat(),
                "decision": row["decision"],
                "version": row["version"],
                "candidate_mape": row["candidate_mape"],
                "production_mape": row["production_mape"],
                "baseline_mape": row["baseline_mape"],
                "reason": row["reason"],
            }
            for row in rows
        ]
    }
