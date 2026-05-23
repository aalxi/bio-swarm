"""P0.2 — run_pipeline_from_demo must wire coder observability fields into state."""
import json
from pathlib import Path
from unittest.mock import patch

from agents.supervisor import run_pipeline_from_demo


def _seed_demo_protocol(tmp_workspace, task_id: str) -> str:
    protocol = {
        "protocol_name": "Demo", "paper_source": "demo://rt_qpcr_v1",
        "labware_setup": ["opentrons_96_wellplate_200ul_pcr_full_skirt"],
        "pipettes": ["p20_single_gen2"], "reagents": [], "extraction_notes": [],
        "pie_ran": False,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "template_amount_ng": 25.0, "volume_ul": 20.0,
             "source_location": "A1", "destination_location": "B1",
             "field_lineage": {}},
        ],
    }
    path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    Path(path).write_text(json.dumps(protocol))
    return path


def _fake_coder_result(output_files, **extras):
    base = {
        "status": "success",
        "output_files": output_files,
        "message": "ok",
        "retry_count": 0,
        "error_detail": None,
        "attempts": [{"attempt": 1, "script_path": "x.py", "stderr_path": "x.stderr",
                       "exit_code": 0, "success": True,
                       "liquid_handling_calls": 3,
                       "liquid_step_coverage": 1.0,
                       "coverage_method": "markers"}],
        "liquid_step_coverage": 1.0,
        "skipped_step_numbers": [],
        "coverage_method": "markers",
        "fidelity_warning": True,
        "labware_substitutions": [{"original": "nest_96_wellplate_2ml_deep",
                                    "substituted": "nest_96_wellplate_200ul_flat",
                                    "reason": "deep-well not available",
                                    "volume_significant": True}],
    }
    base.update(extras)
    return base


def test_demo_path_wires_fidelity_warning(tmp_workspace):
    task_id = "demo_wire_test"
    protocol_path = _seed_demo_protocol(tmp_workspace, task_id)
    script_path = f"workspace/generated_code/protocol_{task_id}.py"
    Path(script_path).write_text("# stub")
    report_path = f"workspace/final_reports/report_{task_id}.md"
    Path(report_path).write_text("# report stub")

    coder_result = _fake_coder_result([script_path])

    with (
        patch("agents.supervisor.coder_agent", return_value=coder_result),
        patch("agents.supervisor._run_iteration_phase", return_value={
            "status": "success", "output_files": [], "message": "skipped",
            "retry_count": 0, "error_detail": None,
        }),
        patch("agents.supervisor.synthesizer_agent", return_value={
            "status": "success",
            "output_files": [report_path],
            "message": "report saved",
            "retry_count": 0,
            "error_detail": None,
        }),
    ):
        result = run_pipeline_from_demo(
            user_input="demo",
            mode="wet_lab",
            task_id=task_id,
            protocol_path=protocol_path,
            enable_iteration=False,
        )

    assert result["status"] == "success", f"Pipeline failed: {result}"
    coding = result["state"]["coding"]
    assert coding["fidelity_warning"] is True, (
        "fidelity_warning must be True — the demo path dropped it before P0.2"
    )
    assert coding["coverage_method"] == "markers"
    assert coding["liquid_step_coverage"] == 1.0
    assert len(coding["labware_substitutions"]) == 1
    assert coding["labware_substitutions"][0]["volume_significant"] is True


def test_demo_path_wires_fields_on_error(tmp_workspace):
    """Even on coder error, observability fields must land in state."""
    task_id = "demo_wire_error_test"
    protocol_path = _seed_demo_protocol(tmp_workspace, task_id)
    report_path = f"workspace/final_reports/report_{task_id}.md"
    Path(report_path).write_text("# partial report")

    coder_error = {
        "status": "error",
        "output_files": [],
        "message": "sim failed",
        "retry_count": 2,
        "error_detail": "opentrons_simulate exited 1",
        "attempts": [],
        "liquid_step_coverage": 0.0,
        "skipped_step_numbers": [],
        "coverage_method": "heuristic_fallback",
        "fidelity_warning": True,
        "labware_substitutions": [],
    }

    with (
        patch("agents.supervisor.coder_agent", return_value=coder_error),
        patch("agents.supervisor.synthesizer_agent", return_value={
            "status": "success",
            "output_files": [report_path],
            "message": "partial report",
            "retry_count": 0,
            "error_detail": None,
        }),
    ):
        result = run_pipeline_from_demo(
            user_input="demo",
            mode="wet_lab",
            task_id=task_id,
            protocol_path=protocol_path,
            enable_iteration=False,
        )

    assert result["status"] == "error"
    coding = result["state"]["coding"]
    assert coding["fidelity_warning"] is True, "fidelity_warning must survive error path"
    assert coding["coverage_method"] == "heuristic_fallback"
