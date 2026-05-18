"""Synthesizer wet-lab report includes a 'Field Lineage Summary' section
when state.iterations.iterations_completed > 0. Test injects fake state
and asserts the section appears in the rendered output."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _seed_artifacts(tmp_workspace, task_id: str):
    Path(f"workspace/extracted_protocols/protocol_{task_id}.json").write_text(json.dumps({
        "protocol_name": "Demo", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": False,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "template_amount_ng": 25.0,
             "field_lineage": {
                 "template_amount_ng": {
                     "source_type": "replanner_revision",
                     "value": 25.0,
                     "placed_at": "2026-05-16T12:00:00+00:00",
                     "iteration_index": 1,
                     "replanner_revision": {
                         "iteration": 1, "action": "reduce_template",
                         "rule_id": "rule.no_amp.high_template.reduce",
                         "rationale": "lowered to break inhibition",
                         "parent_value": 100.0, "parent_cq": None,
                         "citation_failure": False,
                     },
                     "citations": ["MIQE_essential_inhibition_testing"],
                 },
             }},
        ],
    }))
    Path(f"workspace/generated_code/protocol_{task_id}.py").write_text("# stub")
    Path("workspace/state.json").write_text(json.dumps({
        "task_id": task_id, "mode": "wet_lab", "user_input": "demo",
        "status": "synthesis",
        "extraction": {"protocol_file": f"workspace/extracted_protocols/protocol_{task_id}.json",
                       "done": True, "schema_valid": True},
        "coding": {"script_file": f"workspace/generated_code/protocol_{task_id}.py",
                   "done": True, "simulation_passed": True},
        "iterations": {
            "enabled": True, "iterations_completed": 1,
            "converged": False, "diagnosis_required": False, "cap_reached": False,
            "records": [{"iteration_index": 1, "code_file": "x",
                         "sim_passed": True, "cq": None,
                         "regime_label": "inhibition_suspected",
                         "raw_record_path": "x"}],
            "revisions": [{"iteration_index": 1, "action": "reduce_template",
                           "rationale": "lowered", "citation_keys": [],
                           "citation_failure": False}],
            "done": True,
        },
    }))


def test_synthesizer_includes_field_lineage_summary_when_iterations_present(
    tmp_workspace, monkeypatch,
):
    task_id = "tabc"
    _seed_artifacts(tmp_workspace, task_id)
    from agents.synthesizer import _render_field_lineage_section
    out = _render_field_lineage_section(task_id)
    assert "Field Lineage Summary" in out
    assert "step_1.template_amount_ng" in out
    assert "reduce_template" in out
    assert "MIQE_essential_inhibition_testing" in out
