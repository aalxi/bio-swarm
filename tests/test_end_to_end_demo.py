"""End-to-end test of _run_iteration_phase using the demo cache. LLM mocked.
Asserts: convergence OR diagnose_required within MAX_ITERATIONS; lineage
chain on the demo field has the expected source_type sequence."""
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from schemas.state_schema import WorkspaceState, IterationsState
from agents.supervisor import _run_iteration_phase, DEMO_FIELD_PATH


def _install_demo_cache_as_protocol(tmp_workspace, task_id: str) -> str:
    src = Path(__file__).parent.parent / "workspace/demo_cache/rt_qpcr_protocol.json"
    dst = Path(f"workspace/extracted_protocols/protocol_{task_id}.json")
    shutil.copy(src, dst)
    return str(dst)


def test_demo_completes_with_valid_lineage_chain(tmp_workspace):
    task_id = "demo_rt_qpcr"
    protocol_path = _install_demo_cache_as_protocol(tmp_workspace, task_id)
    state = WorkspaceState(
        task_id=task_id, mode="wet_lab", user_input="demo",
        status="iteration", iterations=IterationsState(enabled=True),
    )

    def fake_llm(prompt, action, rule_id):
        return (f"narrating {action}", ["MIQE_essential_inhibition_testing"], False)

    with patch("agents.replanner._llm_call_with_retry", side_effect=fake_llm):
        result = _run_iteration_phase(state, protocol_path, status_callback=None)

    assert result["status"] == "success"
    # Must exit cleanly — converged, diagnose_required, or cap_reached (no errors)
    assert (state.iterations.converged
            or state.iterations.diagnosis_required
            or state.iterations.cap_reached)
    assert state.iterations.iterations_completed >= 1

    proto = json.loads(Path(protocol_path).read_text())
    fl = proto["sequential_steps"][0]["field_lineage"]["template_amount_ng"]
    # Head must be a replanner_revision (oracle is appended first, then replanner)
    assert fl["source_type"] == "replanner_revision"

    # Walk parent chain; record source_types
    types_seen = []
    cur = fl
    while cur is not None:
        types_seen.append(cur["source_type"])
        cur = cur.get("parent")
    types_seen.reverse()
    # Must contain at least one oracle_reading and one replanner_revision
    assert "oracle_reading" in types_seen
    assert "replanner_revision" in types_seen
