"""Enricher writes FieldLineage(enricher_fill) records, not field_confidence/
field_sources dicts. We test _apply_fill in isolation — the LLM is not called.
"""
from agents.enricher import _apply_fill


def test_apply_fill_writes_field_lineage_on_step():
    proto = {
        "sequential_steps": [
            {"step_number": 1, "action": "transfer", "volume_ul": None,
             "field_lineage": {}},
        ],
    }
    _apply_fill(proto, "volume_ul", 1, 25.0, 0.88, "http://x")
    step = proto["sequential_steps"][0]
    assert step["volume_ul"] == 25.0
    assert "field_confidence" not in step
    assert "field_sources" not in step
    fl = step["field_lineage"]["volume_ul"]
    assert fl["source_type"] == "enricher_fill"
    assert fl["enricher_fill"]["confidence"] == 0.88
    assert fl["enricher_fill"]["tavily_url"] == "http://x"
    assert fl["value"] == 25.0


def test_apply_fill_notes_phase_when_no_url():
    proto = {
        "sequential_steps": [
            {"step_number": 1, "action": "transfer", "volume_ul": None,
             "field_lineage": {}},
        ],
    }
    _apply_fill(proto, "volume_ul", 1, 25.0, 0.88, None)
    fl = proto["sequential_steps"][0]["field_lineage"]["volume_ul"]
    assert fl["enricher_fill"]["phase"] == "notes_mining"
    assert fl["enricher_fill"]["tavily_url"] is None


def test_apply_fill_top_level_list_fields_no_lineage():
    proto = {"pipettes": [], "sequential_steps": []}
    _apply_fill(proto, "pipettes", None, ["p300_single_gen2"], 0.9, "http://x")
    assert proto["pipettes"] == ["p300_single_gen2"]
