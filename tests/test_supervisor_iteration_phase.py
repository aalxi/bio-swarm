"""Iteration phase: runs only when enabled; appends lineage records;
converges OR diagnose-required-exits; cap_reached only on exhaustion."""
import json
from pathlib import Path
from unittest.mock import patch

from schemas.state_schema import WorkspaceState, IterationsState
from agents.supervisor import _run_iteration_phase, DEMO_FIELD_PATH


def _seed_protocol(tmp_workspace, template_ng: float) -> str:
    path = "workspace/extracted_protocols/protocol_t1.json"
    Path(path).write_text(json.dumps({
        "protocol_name": "Demo", "paper_source": "x",
        "labware_setup": ["opentrons_96_wellplate_200ul_pcr_full_skirt"],
        "pipettes": ["p20_single_gen2"], "reagents": [], "extraction_notes": [],
        "pie_ran": True,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "template_amount_ng": template_ng, "volume_ul": 20.0,
             "source_location": "A1", "destination_location": "B1",
             "field_lineage": {}},
        ],
    }))
    return path


def test_iteration_phase_skipped_when_disabled(tmp_workspace):
    state = WorkspaceState(
        task_id="t1", mode="wet_lab", user_input="x", status="iteration",
        iterations=IterationsState(enabled=False),
    )
    protocol_path = _seed_protocol(tmp_workspace, 25.0)
    result = _run_iteration_phase(state, protocol_path, status_callback=None)
    assert result["status"] == "success"
    assert state.iterations.done is False  # untouched


def test_iteration_phase_converges_when_in_optimal_range(tmp_workspace):
    """Starting at 25 ng → clean regime, replanner mocked to return converged."""
    state = WorkspaceState(
        task_id="t1", mode="wet_lab", user_input="x", status="iteration",
        iterations=IterationsState(enabled=True),
    )
    protocol_path = _seed_protocol(tmp_workspace, 25.0)
    with patch("agents.supervisor.replanner_agent") as mock_replanner:
        mock_replanner.return_value = {
            "status": "success", "output_files": [protocol_path],
            "message": "converged", "retry_count": 0, "error_detail": None,
            "action": "converged", "new_value": None,
            "rule_id": "rule.converged.clean_optimal_range",
            "rationale": "ok", "citation_keys": [], "citation_failure": False,
        }
        result = _run_iteration_phase(state, protocol_path, status_callback=None)
    assert result["status"] == "success"
    assert state.iterations.converged is True
    assert state.iterations.cap_reached is False
    assert state.iterations.iterations_completed == 1


def test_iteration_phase_diagnose_required_exits(tmp_workspace):
    state = WorkspaceState(
        task_id="t1", mode="wet_lab", user_input="x", status="iteration",
        iterations=IterationsState(enabled=True),
    )
    protocol_path = _seed_protocol(tmp_workspace, 25.0)
    with patch("agents.supervisor.replanner_agent") as mock_replanner:
        mock_replanner.return_value = {
            "status": "success", "output_files": [protocol_path],
            "message": "diag", "retry_count": 0, "error_detail": None,
            "action": "diagnose_required", "new_value": None,
            "rule_id": "rule.ambiguous.mid_template.diagnose_required",
            "rationale": "x", "citation_keys": [], "citation_failure": False,
        }
        result = _run_iteration_phase(state, protocol_path, status_callback=None)
    assert state.iterations.diagnosis_required is True
    assert state.iterations.converged is False
    assert state.iterations.cap_reached is False
