"""Replanner heuristic: every (regime, cq, ambiguous, no_amp, template) cell."""
import pytest
from tools.mock_qpcr import QPCRReading
from agents.replanner import decide_action


def _reading(template_ng, cq, ambiguous, no_amp, regime):
    return QPCRReading(
        template_ng=template_ng, cq=cq, ambiguous=ambiguous,
        no_amplification=no_amp, regime_label=regime,
        raw_record_path="x", citations=[],
    )


def test_clean_in_optimal_range_converges():
    r = _reading(25.0, 27.4, False, False, "clean")
    action, value, rule_id = decide_action(r, 25.0)
    assert action == "converged"
    assert value is None
    assert rule_id == "rule.converged.clean_optimal_range"


def test_clean_cq_too_low_does_not_converge_yet():
    r = _reading(200.0, 20.0, False, False, "clean")
    action, _, _ = decide_action(r, 200.0)
    assert action != "converged"


def test_no_amp_high_template_reduces():
    r = _reading(200.0, None, False, True, "inhibition_suspected")
    action, value, rule_id = decide_action(r, 200.0)
    assert action == "reduce_template"
    assert value == 50.0  # 200 * 0.25
    assert rule_id == "rule.no_amp.high_template.reduce"


def test_no_amp_low_template_increases():
    r = _reading(0.2, None, False, True, "low_copy_suspected")
    action, value, rule_id = decide_action(r, 0.2)
    assert action == "increase_template"
    assert abs(value - 0.8) < 0.01  # 0.2 * 4.0
    assert rule_id == "rule.no_amp.low_template.increase"


def test_ambiguous_high_template_reduces():
    r = _reading(100.0, 35.0, True, False, "inhibition_suspected")
    action, value, rule_id = decide_action(r, 100.0)
    assert action == "reduce_template"
    assert value == 25.0
    assert rule_id == "rule.ambiguous.high_template.reduce"


def test_ambiguous_low_template_increases():
    r = _reading(2.0, 35.0, True, False, "low_copy_suspected")
    action, value, rule_id = decide_action(r, 2.0)
    assert action == "increase_template"
    assert abs(value - 8.0) < 0.01
    assert rule_id == "rule.ambiguous.low_template.increase"


def test_ambiguous_mid_template_diagnose_required():
    """L20: ambiguous Cq at mid-range template (5-50 ng) — cannot be resolved
    by template adjustment alone. Loop must exit with diagnose_required."""
    r = _reading(25.0, 35.0, True, False, "inhibition_suspected")
    action, value, rule_id = decide_action(r, 25.0)
    assert action == "diagnose_required"
    assert value is None
    assert rule_id == "rule.ambiguous.mid_template.diagnose_required"


def test_clamp_lower_bound():
    # 0.02 * 4.0 = 0.08, clamped to 0.1 (spec input of 0.05 would yield 0.2,
    # not triggering the lower bound; corrected to 0.02 per advisor review)
    r = _reading(0.02, None, False, True, "low_copy_suspected")
    _, value, _ = decide_action(r, 0.02)
    assert value == 0.1
