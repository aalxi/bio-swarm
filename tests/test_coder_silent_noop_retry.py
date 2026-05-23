"""P1.3 — Silent no-op (sim passes but zero liquid-handling calls) triggers
fresh regen rather than immediate pipeline abort."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from agents.coder import _wet_lab_flow


def _seed_protocol(tmp_workspace, task_id: str) -> None:
    protocol = {
        "protocol_name": "NEBNext Test", "paper_source": "https://example.com",
        "labware_setup": ["opentrons_96_wellplate_200ul_pcr_full_skirt"],
        "pipettes": ["p300_single_gen2"], "reagents": ["Buffer"],
        "extraction_notes": [], "pie_ran": False,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": 50.0, "source_location": "A1", "destination_location": "B1"},
            {"step_number": 2, "action": "mix",
             "volume_ul": 30.0, "source_location": "B1", "destination_location": "B1"},
        ],
    }
    path = Path(f"workspace/extracted_protocols/protocol_{task_id}.json")
    path.write_text(json.dumps(protocol))


# A script with NO liquid-handling calls (comment-only, triggers no-op detector)
_NOOP_SCRIPT = """\
from opentrons import protocol_api
metadata = {"apiLevel": "2.13"}
def run(protocol: protocol_api.ProtocolContext):
    # STEP 1
    protocol.comment("no transfer here")
    # STEP 2
    protocol.comment("also nothing")
"""

# A real script with liquid-handling calls
_REAL_SCRIPT = """\
from opentrons import protocol_api
metadata = {"apiLevel": "2.13"}
def run(protocol: protocol_api.ProtocolContext):
    tiprack = protocol.load_labware("opentrons_96_tiprack_300ul", 1)
    p = protocol.load_instrument("p300_single_gen2", "left", tip_racks=[tiprack])
    plate = protocol.load_labware("nest_96_wellplate_200ul_flat", 2)
    res = protocol.load_labware("nest_12_reservoir_15ml", 3)
    # STEP 1
    p.transfer(50, res["A1"], plate["A1"])
    # STEP 2
    p.mix(3, 30, plate["A1"])
"""


def _make_sandbox_mocks():
    """Return mock (daytona, sandbox) and a run_cmd side_effect generator."""
    mock_daytona = MagicMock()
    mock_sandbox = MagicMock()
    mock_sandbox.id = "mock-sandbox-id"
    return mock_daytona, mock_sandbox


def test_silent_noop_retries_and_succeeds(tmp_workspace):
    """First generation → noop. Second generation → real script. Pipeline succeeds."""
    task_id = "noop_retry_test"
    _seed_protocol(tmp_workspace, task_id)

    call_count = {"n": 0}

    def fake_generate(protocol):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _NOOP_SCRIPT, []
        return _REAL_SCRIPT, []

    mock_daytona, mock_sandbox = _make_sandbox_mocks()

    sim_success = {"exit_code": 0, "stdout": "Simulating...\nAll good.", "success": True}
    cmd_ok = {"exit_code": 0, "stdout": "ok", "success": True}

    def fake_run_cmd(sandbox, command, cwd=None, timeout=60):
        if "opentrons_simulate" in command:
            return sim_success
        return cmd_ok

    with (
        patch("agents.coder.daytona_tool.create_sandbox", return_value=(mock_daytona, mock_sandbox)),
        patch("agents.coder.daytona_tool.run_cmd", side_effect=fake_run_cmd),
        patch("agents.coder.daytona_tool.upload_file"),
        patch("agents.coder.daytona_tool.cleanup"),
        patch("agents.coder._generate_opentrons_script", side_effect=fake_generate),
    ):
        result = _wet_lab_flow(task_id)

    assert result["status"] == "success", (
        f"Expected success after noop regen but got: {result['message']}"
    )
    assert call_count["n"] == 2, (
        f"Expected _generate_opentrons_script called twice (noop then real), got {call_count['n']}"
    )
    # Both attempt files should exist
    assert Path(f"workspace/generated_code/protocol_{task_id}_attempt1.py").exists(), \
        "Attempt 1 (the noop) must be persisted"
    assert Path(f"workspace/generated_code/protocol_{task_id}_attempt2.py").exists(), \
        "Attempt 2 (the real script) must be persisted"


def test_silent_noop_exhausted_returns_error(tmp_workspace):
    """All regenerations return noop → pipeline returns error contract."""
    task_id = "noop_exhaust_test"
    _seed_protocol(tmp_workspace, task_id)

    mock_daytona, mock_sandbox = _make_sandbox_mocks()

    sim_success = {"exit_code": 0, "stdout": "Simulating...\nAll good.", "success": True}
    cmd_ok = {"exit_code": 0, "stdout": "ok", "success": True}

    def fake_run_cmd(sandbox, command, cwd=None, timeout=60):
        if "opentrons_simulate" in command:
            return sim_success
        return cmd_ok

    with (
        patch("agents.coder.daytona_tool.create_sandbox", return_value=(mock_daytona, mock_sandbox)),
        patch("agents.coder.daytona_tool.run_cmd", side_effect=fake_run_cmd),
        patch("agents.coder.daytona_tool.upload_file"),
        patch("agents.coder.daytona_tool.cleanup"),
        patch("agents.coder._generate_opentrons_script", return_value=(_NOOP_SCRIPT, [])),
    ):
        result = _wet_lab_flow(task_id)

    assert result["status"] == "error"
    assert "no liquid-handling" in result["message"].lower() or \
           "liquid" in result["error_detail"].lower()
