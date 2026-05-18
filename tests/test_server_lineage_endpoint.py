"""GET /lineage/{task_id} returns fields + registry."""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def app_client(tmp_workspace):
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


def _seed_protocol(task_id: str) -> str:
    path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    Path(path).write_text(json.dumps({
        "protocol_name": "x", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [], "pie_ran": False,
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": 25.0,
             "field_lineage": {
                 "volume_ul": {
                     "source_type": "paper_span", "value": 25.0,
                     "placed_at": "2026-05-16T12:00:00+00:00",
                     "paper_span": {
                         "doc_url": "x", "span_id": "s1", "quoted_text": "25 ul",
                     },
                     "citations": [], "iteration_index": None,
                 },
             }},
        ],
    }))
    return path


def test_lineage_endpoint_returns_fields_and_registry(app_client):
    task_id = "tabc"
    _seed_protocol(task_id)
    r = app_client.get(f"/lineage/{task_id}")
    assert r.status_code == 200
    data = r.json()
    assert "fields" in data
    assert "registry" in data
    assert "step_1.volume_ul" in data["fields"]
    assert "MIQE_2009" in data["registry"]


def test_lineage_endpoint_404_when_missing(app_client):
    r = app_client.get("/lineage/does_not_exist")
    assert r.status_code == 404
