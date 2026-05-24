"""P2.3 + P2.4 — Methodology agent must instruct the LLM to populate
applies_to_wells and to categorize off-deck steps with the new OOS
action values rather than fake transfers.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

from agents import methodology


def test_methodology_prompt_mentions_applies_to_wells():
    p = methodology.WET_LAB_SYSTEM_PROMPT
    assert "applies_to_wells" in p
    assert "plate" in p  # the default value
    assert "A1_only" in p
    assert "custom" in p


def test_methodology_prompt_mentions_out_of_scope_categories():
    p = methodology.WET_LAB_SYSTEM_PROMPT
    for cat in ("out_of_scope_setup", "out_of_scope_qc",
                "off_deck_instrument", "manual_only"):
        assert cat in p, f"missing OOS category {cat!r} in WET_LAB_SYSTEM_PROMPT"


def test_methodology_prompt_warns_against_fake_transfers():
    """The prompt must explicitly tell the LLM not to fabricate a transfer
    action for an off-deck step — that's the May-04 FACS-as-transfer bug."""
    p = methodology.WET_LAB_SYSTEM_PROMPT.lower()
    # Some clear instruction against the failure mode. Accept multiple phrasings.
    assert ("never" in p and "out_of_scope" in p.lower()) or "do not" in p


def test_methodology_validates_facs_as_off_deck(monkeypatch, tmp_path):
    """Given a paper that describes FACS sorting, Methodology should
    save a protocol with action='off_deck_instrument', not 'transfer'."""
    canned = {
        "protocol_name": "Smart-seq3 lite",
        "paper_source": "test://smartseq3",
        "labware_setup": ["opentrons_96_wellplate_200ul_pcr_full_skirt"],
        "pipettes": ["p20_single_gen2"],
        "reagents": ["lysis buffer"],
        "sequential_steps": [
            {
                "step_number": 1, "action": "off_deck_instrument",
                "applies_to_wells": "plate",
                "notes": "FACS-sort single cells into 96-well plate.",
                "field_lineage": {},
            },
            {
                "step_number": 2, "action": "transfer",
                "volume_ul": 2.0, "applies_to_wells": "plate",
                "source_location": "A1", "destination_location": "A1",
                "notes": "Add 2 uL lysis buffer to each well.",
                "field_lineage": {},
            },
        ],
        "extraction_notes": [],
    }
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(canned)
    mock_resp.usage = MagicMock(
        prompt_tokens=10, completion_tokens=10, total_tokens=20,
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    monkeypatch.setattr(methodology, "_get_openai_client", lambda: mock_client)

    src = tmp_path / "src.json"
    src.write_text(json.dumps({
        "raw_content": "FACS into 96-well plate; then lyse with 2 µL lysis buffer per well",
        "source_url": "test://smartseq3",
    }))
    researcher_result = {"status": "success", "output_files": [str(src)]}

    os.makedirs("workspace/extracted_protocols", exist_ok=True)

    result = methodology.methodology_agent(researcher_result, "test_b2")
    assert result["status"] == "success", result
    proto_path = result["output_files"][0]
    proto = json.loads(open(proto_path).read())
    assert proto["sequential_steps"][0]["action"] == "off_deck_instrument"
    assert proto["sequential_steps"][0]["applies_to_wells"] == "plate"
    assert proto["sequential_steps"][1]["action"] == "transfer"


def test_methodology_validates_plate_scope_round_trip(monkeypatch, tmp_path):
    """A parallel-plate protocol must round-trip applies_to_wells='plate'."""
    canned = {
        "protocol_name": "qPCR setup",
        "paper_source": "test://qpcr",
        "labware_setup": ["opentrons_96_wellplate_200ul_pcr_full_skirt"],
        "pipettes": ["p20_single_gen2"],
        "reagents": ["master mix"],
        "sequential_steps": [
            {
                "step_number": 1, "action": "transfer",
                "volume_ul": 18.0, "applies_to_wells": "plate",
                "source_location": "A1", "destination_location": "A1",
                "field_lineage": {},
            },
        ],
        "extraction_notes": [],
    }
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(canned)
    mock_resp.usage = MagicMock(
        prompt_tokens=10, completion_tokens=10, total_tokens=20,
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    monkeypatch.setattr(methodology, "_get_openai_client", lambda: mock_client)

    src = tmp_path / "src.json"
    src.write_text(json.dumps({
        "raw_content": "Add 18 µL master mix to every well of the 96-well plate",
        "source_url": "test://qpcr",
    }))
    researcher_result = {"status": "success", "output_files": [str(src)]}

    os.makedirs("workspace/extracted_protocols", exist_ok=True)
    result = methodology.methodology_agent(researcher_result, "test_b2_plate")
    assert result["status"] == "success", result
    proto = json.loads(open(result["output_files"][0]).read())
    assert proto["sequential_steps"][0]["applies_to_wells"] == "plate"
