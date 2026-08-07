"""
GridVision — promotion/rejection audit trail.

Every gate decision (promote OR reject) appends one row here. This is the
"promotion timeline" the dashboard renders and the interview talking point:
concrete dates where the model improved or was held back, and why.

Stored in Postgres (see src/db.py) — migrated off the earlier Parquet file
now that Phase 5 stands up real project storage. A rejection is informative
signal, not a failure.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from src.db import get_engine, init_schema

COLUMNS = [
    "decided_at",
    "decision",          # "promote" | "reject"
    "version",           # candidate model version
    "candidate_mape",
    "production_mape",
    "baseline_mape",
    "reason",
]


def append_record(record: dict) -> None:
    """Insert one decision record (missing keys stored as NULL)."""
    init_schema()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO promotion_log
                    (decided_at, decision, version, candidate_mape,
                     production_mape, baseline_mape, reason)
                VALUES
                    (:decided_at, :decision, :version, :candidate_mape,
                     :production_mape, :baseline_mape, :reason)
                """
            ),
            {col: record.get(col) for col in COLUMNS},
        )


def read_log() -> pd.DataFrame:
    # NOT pd.read_sql: pandas 2.3's SQLAlchemy-connectable detection needs
    # SQLAlchemy>=2.0, but Airflow's containers pin 1.4.x (its own metadata
    # engine depends on that pin) — read_sql silently falls back to a raw
    # DBAPI2 path that doesn't understand SQLAlchemy Engine/Connection at
    # all and errors. Build the frame from the raw result instead.
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT * FROM promotion_log ORDER BY decided_at DESC")
        )
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


if __name__ == "__main__":
    print(read_log().to_string(index=False))
