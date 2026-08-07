"""
Unit tests for the evaluation gate (src/promote.py).

This is the pipeline's most critical logic, so every branch is covered:
beats-both, fails-baseline, fails-production, ties, cold start, the improvement
threshold, and input validation.

Run from the project root:

    python -m pytest tests/test_promote.py -v
"""
import math

import pytest

from src.promote import Decision, decide_promotion


# --------------------------------------------------------------------------- #
# Happy path — beats both gates
# --------------------------------------------------------------------------- #
# Candidate beating both production and baseline should promote.
def test_promote_when_beats_production_and_baseline():
    d = decide_promotion(candidate_mape=4.0, baseline_mape=12.0, production_mape=5.0)
    assert d.promote is True
    assert bool(d) is True
    assert "promoted" in d.reason


# --------------------------------------------------------------------------- #
# Baseline gate
# --------------------------------------------------------------------------- #
# Candidate worse than baseline should reject regardless of production.
def test_reject_when_worse_than_baseline():
    d = decide_promotion(candidate_mape=13.0, baseline_mape=12.0, production_mape=5.0)
    assert d.promote is False
    assert "baseline" in d.reason


# A tie with baseline should not count as beating it.
def test_reject_when_equal_to_baseline():
    # Ties do not count as beating.
    d = decide_promotion(candidate_mape=12.0, baseline_mape=12.0, production_mape=5.0)
    assert d.promote is False
    assert "baseline" in d.reason


# --------------------------------------------------------------------------- #
# Production gate
# --------------------------------------------------------------------------- #
# Beating baseline alone isn't enough if the candidate is worse than production.
def test_reject_when_worse_than_production_even_if_beats_baseline():
    d = decide_promotion(candidate_mape=6.0, baseline_mape=12.0, production_mape=5.0)
    assert d.promote is False
    assert "production" in d.reason


# A tie with production should not count as beating it.
def test_reject_when_equal_to_production():
    d = decide_promotion(candidate_mape=5.0, baseline_mape=12.0, production_mape=5.0)
    assert d.promote is False
    assert "production" in d.reason


# --------------------------------------------------------------------------- #
# Cold start (no production model yet)
# --------------------------------------------------------------------------- #
# With no production model, beating baseline alone should promote.
def test_cold_start_promotes_when_beats_baseline():
    d = decide_promotion(candidate_mape=8.0, baseline_mape=12.0, production_mape=None)
    assert d.promote is True
    assert "cold start" in d.reason


# With no production model, still must beat baseline to promote.
def test_cold_start_rejects_when_fails_baseline():
    d = decide_promotion(candidate_mape=13.0, baseline_mape=12.0, production_mape=None)
    assert d.promote is False
    assert "baseline" in d.reason


# Omitting production_mape entirely should behave the same as passing None.
def test_production_defaults_to_none():
    # production_mape is optional; omitting it means cold start.
    d = decide_promotion(candidate_mape=8.0, baseline_mape=12.0)
    assert d.promote is True


# --------------------------------------------------------------------------- #
# Improvement threshold (min_rel_improvement)
# --------------------------------------------------------------------------- #
# An improvement smaller than the required relative margin should reject.
def test_threshold_rejects_marginal_improvement():
    # 4.96% is better than 5.0% but not by the required 1%.
    d = decide_promotion(
        candidate_mape=4.96, baseline_mape=12.0, production_mape=5.0,
        min_rel_improvement=0.01,
    )
    assert d.promote is False
    assert "production" in d.reason


# An improvement meeting the required relative margin should promote.
def test_threshold_promotes_sufficient_improvement():
    # 4.90% is >=1% better than 5.0% (needs < 4.95%).
    d = decide_promotion(
        candidate_mape=4.90, baseline_mape=12.0, production_mape=5.0,
        min_rel_improvement=0.01,
    )
    assert d.promote is True


# With no improvement margin required, being strictly better is enough.
def test_zero_threshold_is_strictly_better():
    d = decide_promotion(
        candidate_mape=4.999, baseline_mape=12.0, production_mape=5.0,
        min_rel_improvement=0.0,
    )
    assert d.promote is True


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [float("nan"), 0.0, -1.0, None])
# A missing/NaN/non-positive candidate MAPE should raise ValueError.
def test_invalid_candidate_raises(bad):
    with pytest.raises(ValueError):
        decide_promotion(candidate_mape=bad, baseline_mape=12.0, production_mape=5.0)


@pytest.mark.parametrize("bad", [float("nan"), 0.0, -1.0, None])
# A missing/NaN/non-positive baseline MAPE should raise ValueError.
def test_invalid_baseline_raises(bad):
    with pytest.raises(ValueError):
        decide_promotion(candidate_mape=4.0, baseline_mape=bad, production_mape=5.0)


@pytest.mark.parametrize("bad", [float("nan"), 0.0, -1.0])
# A provided but invalid production MAPE should raise ValueError (None is fine).
def test_invalid_production_raises(bad):
    # A provided production MAPE must be valid (None is allowed = cold start).
    with pytest.raises(ValueError):
        decide_promotion(candidate_mape=4.0, baseline_mape=12.0, production_mape=bad)


# A negative min_rel_improvement should raise ValueError.
def test_negative_threshold_raises():
    with pytest.raises(ValueError):
        decide_promotion(
            candidate_mape=4.0, baseline_mape=12.0, production_mape=5.0,
            min_rel_improvement=-0.1,
        )


# --------------------------------------------------------------------------- #
# Decision dataclass
# --------------------------------------------------------------------------- #
# Decision is a frozen dataclass — mutating it after creation should fail.
def test_decision_is_frozen():
    d = Decision(True, "x")
    with pytest.raises(Exception):
        d.promote = False


# Sanity check against a real Phase-1 result, cold start.
def test_realistic_gridvision_numbers():
    # The actual Phase-1 result: model 4.21% vs naive 12.06%, cold start.
    d = decide_promotion(candidate_mape=4.21, baseline_mape=12.06)
    assert d.promote is True
