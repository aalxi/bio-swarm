from datetime import datetime, UTC
import pytest
from pydantic import ValidationError

from schemas.opentrons_schema import ProtocolStep, OpentronsProtocol
from schemas.lineage_schema import FieldLineage, PaperSpanDetail


def _example_lineage() -> FieldLineage:
    return FieldLineage(
        value=25.0,
        placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="paper_span",
        paper_span=PaperSpanDetail(
            doc_url="http://x", span_id="s1", quoted_text="25 ng",
        ),
    )


def test_step_has_template_amount_ng_field():
    s = ProtocolStep(step_number=1, action="transfer", template_amount_ng=25.0)
    assert s.template_amount_ng == 25.0


def test_step_lineage_dict_keyed_by_field_name():
    s = ProtocolStep(
        step_number=1, action="transfer", template_amount_ng=25.0,
        field_lineage={"template_amount_ng": _example_lineage()},
    )
    assert "template_amount_ng" in s.field_lineage
    assert s.field_lineage["template_amount_ng"].value == 25.0


def test_old_field_confidence_is_no_longer_a_field():
    s = ProtocolStep(step_number=1, action="transfer")
    assert not hasattr(s, "field_confidence")
    assert not hasattr(s, "field_sources")


def test_protocol_pie_ran_default():
    p = OpentronsProtocol(
        protocol_name="x", paper_source="y", labware_setup=[], pipettes=[],
        reagents=[], sequential_steps=[], extraction_notes=[],
    )
    assert p.pie_ran is False
