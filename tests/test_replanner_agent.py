"""replanner_agent integration: decide → narrate → emit FieldLineage."""
import json
from pathlib import Path

from tools.mock_qpcr import QPCRReading
from agents.replanner import replanner_agent


def _seed_protocol(tmp_workspace, current_value: float) -> str:
    path = "workspace/extracted_protocols/protocol_test.json"
    Path(path).write_text(json.dumps({
        "protocol_name": "Demo", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": True,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "template_amount_ng": current_value, "field_lineage": {
                 "template_amount_ng": {
                     "source_type": "oracle_reading",
                     "value": current_value,
                     "placed_at": "2026-05-16T12:00:00+00:00",
                     "oracle_reading": {
                         "instrument": "mock_qpcr_v1", "cq": None,
                         "ambiguous": False, "no_amplification": True,
                         "regime_label": "inhibition_suspected",
                         "raw_record_path": "x.csv",
                     },
                     "citations": ["MIQE_essential_inhibition_testing"],
                     "iteration_index": 1,
                 },
             }},
        ],
    }))
    return path


def test_replanner_appends_replanner_revision_lineage(tmp_workspace, monkeypatch):
    """Mock the LLM to avoid real API calls."""
    import agents.replanner as rp
    monkeypatch.setattr(
        rp, "_llm_call_with_retry",
        lambda prompt, action, rule_id: (
            "reducing template", ["MIQE_essential_inhibition_testing"], False,
        ),
    )

    protocol_path = _seed_protocol(tmp_workspace, current_value=200.0)
    reading = QPCRReading(
        template_ng=200.0, cq=None, ambiguous=False, no_amplification=True,
        regime_label="inhibition_suspected", raw_record_path="x.csv",
        citations=["MIQE_essential_inhibition_testing"],
    )
    result = replanner_agent(
        reading=reading, protocol_path=protocol_path,
        iteration_index=1, field_path="step_1.template_amount_ng",
        current_value=200.0,
    )
    assert result["status"] == "success"
    assert result["action"] == "reduce_template"
    assert result["new_value"] == 50.0

    proto = json.loads(Path(protocol_path).read_text())
    fl = proto["sequential_steps"][0]["field_lineage"]["template_amount_ng"]
    assert fl["source_type"] == "replanner_revision"
    assert fl["replanner_revision"]["action"] == "reduce_template"
    assert fl["replanner_revision"]["rule_id"] == "rule.no_amp.high_template.reduce"
    assert fl["iteration_index"] == 1


def test_replanner_converged_emits_no_new_value(tmp_workspace, monkeypatch):
    import agents.replanner as rp
    monkeypatch.setattr(
        rp, "_llm_call_with_retry",
        lambda prompt, action, rule_id: ("ok", [], False),
    )
    protocol_path = _seed_protocol(tmp_workspace, current_value=25.0)
    reading = QPCRReading(
        template_ng=25.0, cq=27.4, ambiguous=False, no_amplification=False,
        regime_label="clean", raw_record_path="x.csv", citations=[],
    )
    result = replanner_agent(
        reading=reading, protocol_path=protocol_path,
        iteration_index=1, field_path="step_1.template_amount_ng",
        current_value=25.0,
    )
    assert result["action"] == "converged"
    assert result["new_value"] is None
