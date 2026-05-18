"""Results reader: pure deterministic interpreter. Appends a FieldLineage
record of source_type='oracle_reading' to the demo field's chain."""
import json
from pathlib import Path

from tools.mock_qpcr import QPCRReading
from agents.results_reader import results_reader_agent


def _make_protocol(tmp_workspace) -> str:
    path = "workspace/extracted_protocols/protocol_test.json"
    Path(path).write_text(json.dumps({
        "protocol_name": "Demo", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": True,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": 20.0, "template_amount_ng": 25.0,
             "field_lineage": {}},
        ],
    }))
    return path


def test_reader_appends_oracle_reading_lineage(tmp_workspace):
    protocol_path = _make_protocol(tmp_workspace)
    reading = QPCRReading(
        template_ng=25.0, cq=27.4, ambiguous=False, no_amplification=False,
        regime_label="clean", raw_record_path="workspace/iterations/1/x.csv",
        citations=[],
    )
    result = results_reader_agent(
        reading, protocol_path, iteration_index=1,
        field_path="step_1.template_amount_ng",
    )
    assert result["status"] == "success"
    proto = json.loads(Path(protocol_path).read_text())
    fl = proto["sequential_steps"][0]["field_lineage"]["template_amount_ng"]
    assert fl["source_type"] == "oracle_reading"
    assert fl["iteration_index"] == 1
    assert fl["oracle_reading"]["regime_label"] == "clean"


def test_reader_records_iteration_oracle_record(tmp_workspace):
    protocol_path = _make_protocol(tmp_workspace)
    reading = QPCRReading(
        template_ng=25.0, cq=27.4, ambiguous=False, no_amplification=False,
        regime_label="clean", raw_record_path="workspace/iterations/1/x.csv",
        citations=[],
    )
    result = results_reader_agent(
        reading, protocol_path, iteration_index=1,
        field_path="step_1.template_amount_ng",
    )
    rec = result["oracle_record"]
    assert rec["iteration_index"] == 1
    assert rec["cq"] == 27.4
    assert rec["regime_label"] == "clean"


def test_reader_handles_no_amp(tmp_workspace):
    protocol_path = _make_protocol(tmp_workspace)
    reading = QPCRReading(
        template_ng=200.0, cq=None, ambiguous=False, no_amplification=True,
        regime_label="inhibition_suspected",
        raw_record_path="workspace/iterations/1/x.csv",
        citations=[
            "MIQE_essential_inhibition_testing",
            "PCR_inhibition_matrix_specific_schrader_2012",
        ],
    )
    result = results_reader_agent(
        reading, protocol_path, iteration_index=1,
        field_path="step_1.template_amount_ng",
    )
    proto = json.loads(Path(protocol_path).read_text())
    fl = proto["sequential_steps"][0]["field_lineage"]["template_amount_ng"]
    assert fl["oracle_reading"]["no_amplification"] is True
    assert "PCR_inhibition_matrix_specific_schrader_2012" in fl["citations"]
