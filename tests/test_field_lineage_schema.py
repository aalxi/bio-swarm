"""FieldLineage schema: detail models + validators."""
import pytest
from pydantic import ValidationError

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
