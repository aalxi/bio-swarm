"""P0.5 — _iteration_outcome five-state logic."""
import re
import pytest

from schemas.state_schema import IterationsState
from tools.lineage_renderer import _iteration_outcome, render_aggregate_summary


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    return ANSI_RE.sub("", s)


# ── _iteration_outcome unit tests ────────────────────────────────────────────

def test_disabled():
    iters = IterationsState(enabled=False)
    key, label = _iteration_outcome(iters)
    assert label == "DISABLED"
    assert key == "reset"


def test_converged():
    iters = IterationsState(enabled=True, iterations_completed=2, converged=True)
    key, label = _iteration_outcome(iters)
    assert label == "CONVERGED"
    assert key == "ok"


def test_diagnose_required():
    iters = IterationsState(enabled=True, iterations_completed=2, diagnosis_required=True)
    key, label = _iteration_outcome(iters)
    assert label == "DIAGNOSE_REQUIRED"
    assert key == "unreachable"


def test_cap_reached():
    iters = IterationsState(enabled=True, iterations_completed=3, cap_reached=True)
    key, label = _iteration_outcome(iters)
    assert label == "CAP_REACHED"
    assert key == "fail"


def test_not_reached():
    # Enabled but no iterations completed yet — not mid-run PENDING.
    iters = IterationsState(enabled=True, iterations_completed=0)
    key, label = _iteration_outcome(iters)
    assert label == "NOT_REACHED"
    assert key == "reset"


def test_pending_mid_run():
    # Enabled, some iterations done, but no terminal flag set.
    iters = IterationsState(enabled=True, iterations_completed=1)
    key, label = _iteration_outcome(iters)
    assert label == "PENDING"
    assert key == "reset"


# ── Integration: render_aggregate_summary surfaces the correct label ─────────

def test_aggregate_disabled_label():
    out = _strip(render_aggregate_summary(
        task_id="t", all_field_lineages={},
        iterations_state=IterationsState(enabled=False),
        color=False,
    ))
    assert "DISABLED" in out
    assert "PENDING" not in out


def test_aggregate_not_reached_label():
    out = _strip(render_aggregate_summary(
        task_id="t", all_field_lineages={},
        iterations_state=IterationsState(enabled=True, iterations_completed=0),
        color=False,
    ))
    assert "NOT_REACHED" in out


def test_aggregate_converged_label():
    out = _strip(render_aggregate_summary(
        task_id="t", all_field_lineages={},
        iterations_state=IterationsState(enabled=True, iterations_completed=2, converged=True),
        color=False,
    ))
    assert "CONVERGED" in out
