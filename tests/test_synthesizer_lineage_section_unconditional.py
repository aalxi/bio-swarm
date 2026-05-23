"""P1.2 — Field Lineage Summary renders on non-iteration protocols with lineage data.

The original gate was `iters["enabled"]`, so real wet-lab runs with paper_span
records from Methodology or enricher_fill records from PIE never showed the
section. The fix gates on any(step.get("field_lineage") for step in steps).
"""
import json
from pathlib import Path


def _seed_non_iteration_lineage_protocol(tmp_workspace, task_id: str) -> None:
    """Protocol with paper_span lineage on 3 steps but no iteration records."""
    protocol = {
        "protocol_name": "NEBNext Ultra II", "paper_source": "https://example.com",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": True,
        "sequential_steps": [
            {
                "step_number": 1, "action": "transfer",
                "volume_ul": 50.0,
                "field_lineage": {
                    "volume_ul": {
                        "source_type": "paper_span",
                        "value": 50.0,
                        "placed_at": "2026-05-22T12:00:00+00:00",
                        "iteration_index": None,
                        "paper_span": {
                            "doc_url": "https://protocols.io/abc",
                            "span_id": "step1_volume",
                            "quoted_text": "Add 50 µL of enzyme mix",
                        },
                        "citations": [],
                        "parent": None,
                    }
                },
            },
            {
                "step_number": 2, "action": "incubate",
                "temperature_celsius": 65.0,
                "field_lineage": {
                    "temperature_celsius": {
                        "source_type": "enricher_fill",
                        "value": 65.0,
                        "placed_at": "2026-05-22T12:01:00+00:00",
                        "iteration_index": None,
                        "enricher_fill": {
                            "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123",
                            "confidence": 0.91,
                            "search_query": "NEBNext adapter ligation temperature",
                        },
                        "citations": [],
                        "parent": None,
                    }
                },
            },
            {
                "step_number": 3, "action": "transfer",
                "volume_ul": 30.0,
                "field_lineage": {},  # empty — should not generate a block
            },
        ],
    }
    Path(f"workspace/extracted_protocols/protocol_{task_id}.json").write_text(json.dumps(protocol))
    Path(f"workspace/generated_code/protocol_{task_id}.py").write_text("# stub")
    # State: iterations disabled (iterations.enabled = False)
    Path("workspace/state.json").write_text(json.dumps({
        "task_id": task_id, "mode": "wet_lab", "user_input": "NEBNext Ultra II",
        "status": "synthesis",
        "extraction": {
            "protocol_file": f"workspace/extracted_protocols/protocol_{task_id}.json",
            "done": True, "schema_valid": True,
        },
        "coding": {
            "script_file": f"workspace/generated_code/protocol_{task_id}.py",
            "done": True, "simulation_passed": True,
        },
        "iterations": {
            "enabled": False,
            "iterations_completed": 0,
            "converged": False,
            "diagnosis_required": False,
            "cap_reached": False,
            "records": [],
            "revisions": [],
            "done": False,
        },
    }))


def test_lineage_section_renders_without_iterations(tmp_workspace):
    task_id = "neb_lineage_test"
    _seed_non_iteration_lineage_protocol(tmp_workspace, task_id)

    from agents.synthesizer import _render_field_lineage_section
    out = _render_field_lineage_section(task_id)

    assert out != "", "Section must be non-empty when steps have lineage data"
    assert "Field Lineage Summary" in out, "Heading must appear"
    # paper_span and enricher_fill records must be counted
    assert "paper_span=1" in out, f"Expected paper_span=1 in counts, got:\n{out}"
    assert "enricher_fill=1" in out, f"Expected enricher_fill=1 in counts, got:\n{out}"
    # No iteration-outcome line when iterations were disabled
    assert "Iteration outcome" not in out, (
        "Iteration-outcome line must not appear when iterations were disabled"
    )


def test_lineage_section_absent_when_all_lineage_empty(tmp_workspace):
    task_id = "no_lineage_test"
    protocol = {
        "protocol_name": "Minimal", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": False,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer", "field_lineage": {}},
        ],
    }
    Path(f"workspace/extracted_protocols/protocol_{task_id}.json").write_text(json.dumps(protocol))
    Path("workspace/state.json").write_text(json.dumps({
        "task_id": task_id, "mode": "wet_lab", "user_input": "x",
        "status": "synthesis", "iterations": {"enabled": False},
    }))

    from agents.synthesizer import _render_field_lineage_section
    out = _render_field_lineage_section(task_id)
    assert out == "", f"Section must be empty when all field_lineage dicts are empty; got:\n{out}"


def test_lineage_section_still_renders_with_iteration_data(tmp_workspace):
    """Existing iteration-test case: section still includes iteration outcome."""
    task_id = "iter_lineage_test"

    protocol = {
        "protocol_name": "Demo", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": True,
        "sequential_steps": [
            {
                "step_number": 1, "action": "transfer",
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
                            "rationale": "lowered",
                            "parent_value": 100.0, "parent_cq": None,
                            "citation_failure": False,
                        },
                        "citations": ["MIQE_essential_inhibition_testing"],
                        "parent": None,
                    }
                },
            },
        ],
    }
    Path(f"workspace/extracted_protocols/protocol_{task_id}.json").write_text(json.dumps(protocol))
    Path("workspace/state.json").write_text(json.dumps({
        "task_id": task_id, "mode": "wet_lab", "user_input": "demo",
        "status": "synthesis",
        "iterations": {
            "enabled": True, "iterations_completed": 1,
            "converged": False, "diagnosis_required": False, "cap_reached": False,
            "records": [], "revisions": [], "done": True,
        },
    }))

    from agents.synthesizer import _render_field_lineage_section
    out = _render_field_lineage_section(task_id)

    assert "Field Lineage Summary" in out
    assert "Iteration outcome" in out
    assert "PENDING" in out  # converged=False, no cap
    assert "reduce_template" in out
