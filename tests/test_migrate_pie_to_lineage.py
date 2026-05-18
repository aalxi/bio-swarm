from __future__ import annotations

import json
from pathlib import Path

from scripts.migrate_pie_to_lineage import migrate_one


def _legacy_protocol() -> dict:
    return {
        "protocol_name": "Demo",
        "paper_source": "Paper X",
        "labware_setup": [],
        "pipettes": [],
        "reagents": [],
        "extraction_notes": [],
        "pie_ran": True,
        "enrichment_log": {"gaps_filled": 1},
        "sequential_steps": [
            {
                "step_number": 1, "action": "transfer",
                "volume_ul": 25.0, "temperature_celsius": 42.0,
                "field_confidence": {"volume_ul": 0.88, "temperature_celsius": 0.7},
                "field_sources": {
                    "volume_ul": "https://pmc.ncbi.nlm.nih.gov/articles/PMCx/",
                    "temperature_celsius": None,
                },
            },
        ],
    }


def test_migrate_drops_legacy_keys(tmp_workspace):
    p = Path("workspace/extracted_protocols/legacy.json")
    p.write_text(json.dumps(_legacy_protocol()))
    migrate_one(str(p))
    out = json.loads(p.read_text())
    step = out["sequential_steps"][0]
    assert "field_confidence" not in step
    assert "field_sources" not in step
    assert "field_lineage" in step


def test_migrate_builds_one_lineage_per_filled_field(tmp_workspace):
    p = Path("workspace/extracted_protocols/legacy.json")
    p.write_text(json.dumps(_legacy_protocol()))
    migrate_one(str(p))
    step = json.loads(p.read_text())["sequential_steps"][0]
    fl = step["field_lineage"]
    assert set(fl.keys()) == {"volume_ul", "temperature_celsius"}
    assert fl["volume_ul"]["source_type"] == "enricher_fill"
    assert fl["volume_ul"]["enricher_fill"]["tavily_url"].startswith("https://pmc")
    assert fl["volume_ul"]["citations"] == []
    assert fl["volume_ul"]["value"] == 25.0


def test_migrate_handles_no_legacy_keys(tmp_workspace):
    proto = _legacy_protocol()
    del proto["sequential_steps"][0]["field_confidence"]
    del proto["sequential_steps"][0]["field_sources"]
    p = Path("workspace/extracted_protocols/clean.json")
    p.write_text(json.dumps(proto))
    migrate_one(str(p))  # must not raise
    step = json.loads(p.read_text())["sequential_steps"][0]
    assert step["field_lineage"] == {}
