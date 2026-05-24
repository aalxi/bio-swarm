"""P2.3 + P2.4 — Coder codegen prompts must describe per-well loops and
out-of-scope handling, and _compute_step_coverage must exclude OOS steps
from the denominator so an honest 4-LH + 3-OOS protocol shows 100%, not 4/7.
"""
from __future__ import annotations

from agents import coder


def test_codegen_prompt_describes_per_well_loops():
    p = coder.WET_LAB_CODEGEN_SYSTEM_PROMPT
    assert "applies_to_wells" in p
    # Either explicit `for well in plate.wells()` or mention of plate.wells()
    assert "plate.wells()" in p or "for well" in p


def test_codegen_prompt_describes_oos_handling():
    p = coder.WET_LAB_CODEGEN_SYSTEM_PROMPT
    for tag in ("out_of_scope_setup", "out_of_scope_qc",
                "off_deck_instrument", "manual_only"):
        assert tag in p, f"missing OOS tag {tag!r}"


def test_codegen_prompt_forbids_fake_transfers_for_oos():
    p = coder.WET_LAB_CODEGEN_SYSTEM_PROMPT.lower()
    # Must explicitly say comment-only for OOS steps
    assert "protocol.comment" in p


def test_compute_step_coverage_excludes_oos_steps():
    """OOS steps don't count toward the denominator: a protocol with
    4 LH steps + 3 off-deck steps and 4 LH calls = 100%, not 4/7."""
    script = """
def run(p):
    # STEP 1
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 2
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 3
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 4
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 5
    protocol.comment("out_of_scope: FACS sort")
    # STEP 6
    protocol.comment("out_of_scope: Bioanalyzer")
    # STEP 7
    protocol.comment("out_of_scope: manual UV exposure")
"""
    coverage, skipped, method = coder._compute_step_coverage(
        script, total_steps=7, oos_step_numbers=[5, 6, 7],
    )
    assert coverage == 1.0
    assert method == "markers"
    assert skipped == []


def test_compute_step_coverage_no_oos_argument_back_compat():
    """Calling without oos_step_numbers must still work — coverage_method
    tests and other callers use the old 2-arg signature."""
    script = """
def run(p):
    # STEP 1
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 2
    p.transfer(1, p.wells()[0], p.wells()[1])
"""
    coverage, _, method = coder._compute_step_coverage(script, total_steps=2)
    assert coverage == 1.0
    assert method == "markers"


def test_compute_step_coverage_partial_with_oos():
    """If only some in-scope steps emit LH calls, ratio reflects only the
    in-scope subset."""
    script = """
def run(p):
    # STEP 1
    p.transfer(1, p.wells()[0], p.wells()[1])
    # STEP 2
    protocol.comment("no LH")
    # STEP 3
    protocol.comment("out_of_scope: FACS")
"""
    coverage, skipped, method = coder._compute_step_coverage(
        script, total_steps=3, oos_step_numbers=[3],
    )
    # In-scope = {1, 2}; active = {1}; ratio = 1/2 = 0.5
    assert coverage == 0.5
    assert skipped == [2]
    assert method == "markers"


def test_compute_step_coverage_heuristic_fallback_with_oos():
    """When no STEP markers are present, heuristic uses total_steps - len(oos)
    as denominator."""
    script = """
def run(p):
    p.transfer(1, p.wells()[0], p.wells()[1])
    p.transfer(1, p.wells()[0], p.wells()[1])
"""
    coverage, _, method = coder._compute_step_coverage(
        script, total_steps=5, oos_step_numbers=[3, 4, 5],
    )
    assert method == "heuristic_fallback"
    # In-scope = 5 - 3 = 2; LH calls = 2; ratio = 1.0
    assert coverage == 1.0
