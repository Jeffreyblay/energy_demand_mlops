"""
GridVision — the evaluation gate.

The single most important piece of logic in the pipeline: decide whether a newly
trained candidate model should be promoted to production. Kept as a PURE,
deterministic function with no dependency on Airflow or MLflow so it can be unit
tested in isolation (see tests/test_promote.py).

Double gate — a candidate is promoted only if it beats BOTH:
  1. the current production model, AND
  2. the naive (seasonal) baseline.

All scores are MAPE in percent (lower is better).

Rationale for the double gate: beating a previous *bad* production model is not
enough; the candidate must also beat a meaningful, always-available benchmark.
This prevents a slow drift of successively mediocre models from looking like
progress.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Default: candidate must be at least this fraction better than production
# (relative). 0.0 = strictly-better is enough. Raise to require a margin and
# avoid churn on statistical noise.
DEFAULT_MIN_REL_IMPROVEMENT = 0.0


@dataclass(frozen=True)
class Decision:
    promote: bool
    reason: str

    def __bool__(self) -> bool:  # allows `if decision:`
        return self.promote


def _validate(name: str, value: float) -> None:
    if value is None or math.isnan(value):
        raise ValueError(f"{name} MAPE is missing/NaN")
    if value <= 0:
        raise ValueError(f"{name} MAPE must be positive, got {value}")


def decide_promotion(
    candidate_mape: float,
    baseline_mape: float,
    production_mape: float | None = None,
    min_rel_improvement: float = DEFAULT_MIN_REL_IMPROVEMENT,
) -> Decision:
    """Return a Decision to promote or reject the candidate.

    Args:
        candidate_mape:   candidate model MAPE (%), lower is better.
        baseline_mape:    naive seasonal baseline MAPE (%) on the same window.
        production_mape:  current production model MAPE (%), or None on cold start
                          (no production model exists yet).
        min_rel_improvement: required fractional improvement over production
                          (e.g. 0.01 = candidate must be >=1% better).

    Raises:
        ValueError: if candidate/baseline (or a provided production) MAPE is
                    missing, NaN, or non-positive, or if min_rel_improvement < 0.
    """
    _validate("candidate", candidate_mape)
    _validate("baseline", baseline_mape)
    if min_rel_improvement < 0:
        raise ValueError("min_rel_improvement must be >= 0")

    # Gate 1: must beat the naive baseline (always applies).
    if not candidate_mape < baseline_mape:
        return Decision(
            False,
            f"rejected: candidate {candidate_mape:.3f}% does not beat baseline "
            f"{baseline_mape:.3f}%",
        )

    # Cold start: no production model to compare against — baseline gate suffices.
    if production_mape is None:
        return Decision(
            True,
            f"promoted (cold start): candidate {candidate_mape:.3f}% beats baseline "
            f"{baseline_mape:.3f}%; no production model yet",
        )

    _validate("production", production_mape)

    # Gate 2: must beat production by the required relative margin.
    threshold = production_mape * (1.0 - min_rel_improvement)
    if not candidate_mape < threshold:
        margin_txt = (
            f" (needed < {threshold:.3f}% = {min_rel_improvement:.1%} better)"
            if min_rel_improvement > 0
            else ""
        )
        return Decision(
            False,
            f"rejected: candidate {candidate_mape:.3f}% does not beat production "
            f"{production_mape:.3f}%{margin_txt}",
        )

    return Decision(
        True,
        f"promoted: candidate {candidate_mape:.3f}% beats production "
        f"{production_mape:.3f}% and baseline {baseline_mape:.3f}%",
    )
