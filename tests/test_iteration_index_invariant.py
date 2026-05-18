"""L19 invariants on a synthesized lineage chain:
- paper_span / enricher_fill -> iteration_index is None
- oracle_reading / replanner_revision -> iteration_index is non-None
- monotonically non-decreasing along .parent (records within one iteration share)
- strictly increasing across iteration boundaries
- at most one oracle_reading and one replanner_revision per iteration_index
"""
from datetime import datetime, UTC

import pytest

from schemas.lineage_schema import (
    FieldLineage, PaperSpanDetail, EnricherFillDetail,
    OracleReadingDetail, ReplannerRevisionDetail,
)


def _chain():
    root = FieldLineage(
        value=100.0, placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="paper_span",
        paper_span=PaperSpanDetail(doc_url="x", span_id="x", quoted_text="100 ng"),
    )
    enr = FieldLineage(
        value=100.0, placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="enricher_fill",
        enricher_fill=EnricherFillDetail(phase="tavily", confidence=0.9),
        parent=root,
    )
    o1 = FieldLineage(
        value=100.0, placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="oracle_reading", iteration_index=1,
        oracle_reading=OracleReadingDetail(
            instrument="mock_qpcr_v1", cq=None, ambiguous=False,
            no_amplification=True, regime_label="inhibition_suspected",
            raw_record_path="x",
        ),
        parent=enr,
    )
    r1 = FieldLineage(
        value=25.0, placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="replanner_revision", iteration_index=1,
        replanner_revision=ReplannerRevisionDetail(
            iteration=1, action="reduce_template",
            rule_id="rule.no_amp.high_template.reduce",
            rationale="x", parent_value=100.0, parent_cq=None,
        ),
        parent=o1,
    )
    o2 = FieldLineage(
        value=25.0, placed_at=datetime(2026, 5, 16, tzinfo=UTC),
        source_type="oracle_reading", iteration_index=2,
        oracle_reading=OracleReadingDetail(
            instrument="mock_qpcr_v1", cq=27.4, ambiguous=False,
            no_amplification=False, regime_label="clean", raw_record_path="x",
        ),
        parent=r1,
    )
    return o2


def _walk(head: FieldLineage):
    out = []
    cur = head
    while cur is not None:
        out.append(cur)
        cur = cur.parent
    return list(reversed(out))


def test_pre_loop_records_have_none_iteration_index():
    head = _chain()
    chain = _walk(head)
    for fl in chain:
        if fl.source_type in ("paper_span", "enricher_fill"):
            assert fl.iteration_index is None


def test_in_loop_records_have_non_none_iteration_index():
    head = _chain()
    for fl in _walk(head):
        if fl.source_type in ("oracle_reading", "replanner_revision"):
            assert fl.iteration_index is not None


def test_monotonically_non_decreasing_iteration_index():
    head = _chain()
    chain = _walk(head)
    last_in_loop = None
    for fl in chain:
        if fl.iteration_index is None:
            continue
        if last_in_loop is not None:
            assert fl.iteration_index >= last_in_loop
        last_in_loop = fl.iteration_index


def test_at_most_one_oracle_and_one_replanner_per_iteration():
    head = _chain()
    chain = _walk(head)
    by_iter: dict[int, dict[str, int]] = {}
    for fl in chain:
        if fl.iteration_index is None:
            continue
        bucket = by_iter.setdefault(fl.iteration_index, {})
        bucket[fl.source_type] = bucket.get(fl.source_type, 0) + 1
    for i, bucket in by_iter.items():
        assert bucket.get("oracle_reading", 0) <= 1, f"iter {i}: too many oracle records"
        assert bucket.get("replanner_revision", 0) <= 1, f"iter {i}: too many replanner records"
