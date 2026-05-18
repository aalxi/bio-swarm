"""FieldLineage schema: detail models + validators."""
import pytest
from pydantic import ValidationError
from datetime import datetime, UTC

from schemas.lineage_schema import (
    PaperSpanDetail, EnricherFillDetail, OracleReadingDetail,
    ReplannerRevisionDetail,
)


def test_paper_span_detail_roundtrip():
    d = PaperSpanDetail(
        doc_url="http://x", span_id="s1", quoted_text="words from paper",
    )
    assert PaperSpanDetail.model_validate(d.model_dump()) == d


def test_enricher_fill_detail_phases_constrained():
    EnricherFillDetail(phase="notes_mining", confidence=0.88)
    EnricherFillDetail(phase="tavily", confidence=0.7, tavily_url="http://x")
    with pytest.raises(ValidationError):
        EnricherFillDetail(phase="random", confidence=0.5)


def test_oracle_reading_detail_regime_constrained():
    OracleReadingDetail(
        instrument="mock_qpcr_v1", cq=27.4, ambiguous=False,
        no_amplification=False, regime_label="clean",
        raw_record_path="workspace/iterations/1/qpcr_raw_3.csv",
    )
    with pytest.raises(ValidationError):
        OracleReadingDetail(
            instrument="mock_qpcr_v1", cq=27.4, ambiguous=False,
            no_amplification=False, regime_label="wrong",
            raw_record_path="x",
        )


def test_replanner_revision_detail_actions_constrained():
    ReplannerRevisionDetail(
        iteration=1, action="converged",
        rule_id="rule.converged.clean_optimal_range",
        rationale="optimal", parent_value=25.0, parent_cq=27.4,
    )
    with pytest.raises(ValidationError):
        ReplannerRevisionDetail(
            iteration=1, action="abandon",
            rule_id="x", rationale="x", parent_value=None, parent_cq=None,
        )


from schemas.lineage_schema import FieldLineage


def _ps_lineage(**over):
    base = dict(
        value=25.0,
        placed_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC),
        source_type="paper_span",
        paper_span=PaperSpanDetail(
            doc_url="http://x", span_id="s1", quoted_text="25 ng template",
        ),
    )
    base.update(over)
    return FieldLineage(**base)


def test_field_lineage_value_can_be_none():
    """L14: null-marking extends to the analytical end."""
    fl = _ps_lineage(value=None)
    assert fl.value is None


def test_exactly_one_detail_rejects_multi_population():
    with pytest.raises(ValidationError, match="should not also populate"):
        FieldLineage(
            value=1,
            placed_at=datetime(2026, 5, 16, tzinfo=UTC),
            source_type="paper_span",
            paper_span=PaperSpanDetail(doc_url="x", span_id="x", quoted_text="x"),
            enricher_fill=EnricherFillDetail(phase="tavily", confidence=0.7),
        )


def test_exactly_one_detail_rejects_missing_required():
    with pytest.raises(ValidationError, match="requires its matching detail"):
        FieldLineage(
            value=1,
            placed_at=datetime(2026, 5, 16, tzinfo=UTC),
            source_type="paper_span",
        )


def test_citations_must_be_registered():
    with pytest.raises(ValidationError, match="Unregistered citation keys"):
        _ps_lineage(citations=["totally_made_up_key"])


def test_citations_from_registry_accepted():
    fl = _ps_lineage(citations=["MIQE_essential_reaction_volume_and_template"])
    assert fl.citations == ["MIQE_essential_reaction_volume_and_template"]


def test_iteration_index_required_for_loop_records():
    with pytest.raises(ValidationError, match="requires iteration_index"):
        FieldLineage(
            value=25.0,
            placed_at=datetime(2026, 5, 16, tzinfo=UTC),
            source_type="oracle_reading",
            oracle_reading=OracleReadingDetail(
                instrument="mock_qpcr_v1", cq=27.4, ambiguous=False,
                no_amplification=False, regime_label="clean",
                raw_record_path=None,
            ),
        )


def test_iteration_index_forbidden_outside_loop():
    with pytest.raises(ValidationError, match="must not set iteration_index"):
        _ps_lineage(iteration_index=1)


def test_id_is_auto_computed():
    fl = _ps_lineage()
    assert fl.id is not None and len(fl.id) == 12


def test_parent_id_auto_set_from_parent():
    parent = _ps_lineage()
    child = FieldLineage(
        value=100.0,
        placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="enricher_fill",
        enricher_fill=EnricherFillDetail(phase="tavily", confidence=0.7),
        parent=parent,
    )
    assert child.parent_id == parent.id
