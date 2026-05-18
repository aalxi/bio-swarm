from agents.methodology import _attach_paper_span_lineage


def test_attach_paper_span_wraps_volume_ul_when_present():
    proto = {
        "protocol_name": "x", "paper_source": "https://pmc.x/article/Y",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": ["50 µL reactions per well"],
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": 50.0, "template_amount_ng": 25.0,
             "field_lineage": {}},
        ],
    }
    _attach_paper_span_lineage(proto)
    step = proto["sequential_steps"][0]
    assert "volume_ul" in step["field_lineage"]
    fl = step["field_lineage"]["volume_ul"]
    assert fl["source_type"] == "paper_span"
    assert fl["value"] == 50.0
    assert fl["paper_span"]["doc_url"] == "https://pmc.x/article/Y"


def test_attach_paper_span_skips_null_fields():
    proto = {
        "protocol_name": "x", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [],
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": None, "field_lineage": {}},
        ],
    }
    _attach_paper_span_lineage(proto)
    assert proto["sequential_steps"][0]["field_lineage"] == {}


def test_attach_paper_span_preserves_existing_lineage():
    proto = {
        "protocol_name": "x", "paper_source": "x",
        "labware_setup": [], "pipettes": [], "reagents": [],
        "extraction_notes": [],
        "sequential_steps": [
            {"step_number": 1, "action": "transfer",
             "volume_ul": 50.0,
             "field_lineage": {
                 "volume_ul": {
                     "source_type": "enricher_fill", "value": 50.0,
                     "placed_at": "2026-01-01T00:00:00+00:00",
                     "enricher_fill": {"phase": "tavily", "confidence": 0.9,
                                       "tavily_url": "http://y"},
                     "citations": [], "iteration_index": None,
                 },
             }},
        ],
    }
    _attach_paper_span_lineage(proto)
    fl = proto["sequential_steps"][0]["field_lineage"]["volume_ul"]
    assert fl["source_type"] == "enricher_fill"
