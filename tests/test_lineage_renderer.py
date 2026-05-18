"""Renderer: golden-file comparison with ANSI escapes stripped."""
import re
from datetime import datetime, UTC

from schemas.lineage_schema import (
    FieldLineage, PaperSpanDetail, EnricherFillDetail,
    OracleReadingDetail, ReplannerRevisionDetail,
)
from tools.lineage_renderer import render_lineage_tree


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    return ANSI_RE.sub("", s)


def _fixture_chain() -> FieldLineage:
    t = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    root = FieldLineage(
        value=100.0, placed_at=t, source_type="paper_span",
        paper_span=PaperSpanDetail(
            doc_url="https://pmc/x", span_id="step_1_template",
            quoted_text="100 ng template per reaction",
        ),
    )
    enr = FieldLineage(
        value=100.0, placed_at=t, source_type="enricher_fill",
        enricher_fill=EnricherFillDetail(phase="tavily", confidence=0.85,
                                         tavily_url="https://pmc/y"),
        parent=root,
    )
    oracle = FieldLineage(
        value=100.0, placed_at=t, source_type="oracle_reading",
        iteration_index=1,
        oracle_reading=OracleReadingDetail(
            instrument="mock_qpcr_v1", cq=None, ambiguous=False,
            no_amplification=True, regime_label="inhibition_suspected",
            raw_record_path="workspace/iterations/1/qpcr_raw_10000.csv",
        ),
        citations=[
            "MIQE_essential_inhibition_testing",
            "PCR_inhibition_matrix_specific_schrader_2012",
        ],
        parent=enr,
    )
    replanner = FieldLineage(
        value=25.0, placed_at=t, source_type="replanner_revision",
        iteration_index=1,
        replanner_revision=ReplannerRevisionDetail(
            iteration=1, action="reduce_template",
            rule_id="rule.no_amp.high_template.reduce",
            rationale="High template → suspected inhibition; reducing 4x.",
            parent_value=100.0, parent_cq=None,
        ),
        citations=["MIQE_essential_inhibition_testing"],
        parent=oracle,
    )
    return replanner


def test_render_tree_includes_all_four_source_types():
    out = _strip(render_lineage_tree(_fixture_chain(), color=False))
    assert "paper_span" in out
    assert "enricher_fill" in out
    assert "oracle_reading" in out
    assert "replanner_revision" in out


def test_render_tree_includes_action_and_rule_id():
    out = _strip(render_lineage_tree(_fixture_chain(), color=False))
    assert "reduce_template" in out
    assert "rule.no_amp.high_template.reduce" in out


def test_render_tree_includes_registry_keys_as_citations():
    out = _strip(render_lineage_tree(_fixture_chain(), color=False))
    assert "PCR_inhibition_matrix_specific_schrader_2012" in out


def test_render_tree_root_is_first_record():
    out = _strip(render_lineage_tree(_fixture_chain(), color=False))
    pos_paper = out.find("paper_span")
    pos_replanner = out.find("replanner_revision")
    assert pos_paper >= 0 and pos_replanner >= 0
    assert pos_paper < pos_replanner


from schemas.state_schema import IterationsState, IterationRevision, IterationOracleRecord
from tools.lineage_renderer import render_aggregate_summary


def _fields_dict():
    head = _fixture_chain()
    return {"step_1.template_amount_ng": head}


def test_aggregate_summary_lists_source_type_counts():
    iters = IterationsState(
        enabled=True, iterations_completed=1, converged=True,
        records=[IterationOracleRecord(
            iteration_index=1, code_file="x.py", sim_passed=True,
            cq=None, regime_label="inhibition_suspected", raw_record_path="x",
        )],
        revisions=[IterationRevision(
            iteration_index=1, action="reduce_template",
            rationale="x", citation_keys=[],
        )],
    )
    out = _strip(render_aggregate_summary(
        task_id="abc123", all_field_lineages=_fields_dict(),
        iterations_state=iters, color=False,
    ))
    assert "task abc123" in out
    assert "paper_span" in out
    assert "enricher_fill" in out
    assert "oracle_reading" in out
    assert "replanner_revision" in out
    assert "Iteration outcome" in out


def test_aggregate_summary_diagnose_required_outcome():
    iters = IterationsState(
        enabled=True, iterations_completed=2, diagnosis_required=True,
    )
    out = _strip(render_aggregate_summary(
        task_id="t", all_field_lineages=_fields_dict(),
        iterations_state=iters, color=False,
    ))
    assert "DIAGNOSE_REQUIRED" in out
