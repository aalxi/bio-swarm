"""P0.1 — _STEP_MARKER_RE must match indented markers as emitted by the LLM."""
from agents.coder import _compute_step_coverage

_INDENTED_SCRIPT = """\
from opentrons import protocol_api

metadata = {"apiLevel": "2.13"}

def run(protocol: protocol_api.ProtocolContext):
    tiprack = protocol.load_labware("opentrons_96_tiprack_300ul", 1)
    pipette = protocol.load_instrument("p300_single_gen2", "left", tip_racks=[tiprack])
    plate = protocol.load_labware("nest_96_wellplate_200ul_flat", 2)
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", 3)

    # STEP 1
    pipette.pick_up_tip()
    pipette.transfer(50, reservoir["A1"], plate["A1"], new_tip="never")
    pipette.drop_tip()

    # STEP 2
    pipette.pick_up_tip()
    pipette.transfer(50, reservoir["A2"], plate["B1"], new_tip="never")
    pipette.drop_tip()
"""


def test_indented_step_marker_gives_markers_method():
    coverage, skipped, method = _compute_step_coverage(_INDENTED_SCRIPT, total_steps=2)
    assert method == "markers", (
        f"Expected method='markers' but got '{method}'. "
        "This means _STEP_MARKER_RE requires column-0 anchoring and misses indented markers."
    )
    assert coverage == 1.0, f"Expected full coverage but got {coverage}"
    assert skipped == [], f"Expected no skipped steps but got {skipped}"


def test_column_zero_marker_still_matches():
    script = "# STEP 1\npipette.transfer(50, src, dst)\n"
    _, _, method = _compute_step_coverage(script, total_steps=1)
    assert method == "markers"


def test_zero_steps_returns_markers_method():
    _, _, method = _compute_step_coverage("", total_steps=0)
    assert method == "markers"
