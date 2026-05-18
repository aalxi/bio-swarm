"""FieldLineage data model — the unified provenance type for every field
value in a protocol. See docs/superpowers/2026-05-16-field-lineage-and-
closed-loop-design.md §4 for the full design rationale."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class PaperSpanDetail(BaseModel):
    doc_url: str
    span_id: str
    quoted_text: str


class EnricherFillDetail(BaseModel):
    phase: Literal["notes_mining", "tavily"]
    confidence: float
    tavily_url: Optional[str] = None  # for PIE-migrated records w/o registry entry


class OracleReadingDetail(BaseModel):
    instrument: str
    cq: Optional[float]
    ambiguous: bool
    no_amplification: bool
    regime_label: Literal[
        "clean", "inhibition_suspected", "low_copy_suspected", "no_amplification"
    ]
    raw_record_path: Optional[str]


class ReplannerRevisionDetail(BaseModel):
    iteration: int
    action: Literal[
        "converged", "reduce_template", "increase_template", "diagnose_required"
    ]
    rule_id: str
    rationale: str
    parent_value: Optional[float | int | str] = None
    parent_cq: Optional[float] = None
    citation_failure: bool = False


class FieldLineage(BaseModel):
    """The lineage of a single typed value in a protocol field.

    Exactly one of (paper_span | enricher_fill | oracle_reading |
    replanner_revision) is populated, matching `source_type`. Validators
    enforce that and the citation-registry-key invariant."""

    value: Optional[float | int | str] = None         # L14
    placed_at: datetime                                # always UTC

    source_type: Literal[
        "paper_span", "enricher_fill", "oracle_reading", "replanner_revision"
    ]

    paper_span:         Optional[PaperSpanDetail]         = None
    enricher_fill:      Optional[EnricherFillDetail]      = None
    oracle_reading:     Optional[OracleReadingDetail]     = None
    replanner_revision: Optional[ReplannerRevisionDetail] = None

    citations: list[str] = []
    iteration_index: Optional[int] = None              # L15
    parent: Optional["FieldLineage"] = None

    # L24: flat-lookup keys; auto-computed
    id: Optional[str] = None
    parent_id: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one_detail(self) -> "FieldLineage":
        details = {
            "paper_span":         self.paper_span,
            "enricher_fill":      self.enricher_fill,
            "oracle_reading":     self.oracle_reading,
            "replanner_revision": self.replanner_revision,
        }
        if details[self.source_type] is None:
            raise ValueError(f"{self.source_type} requires its matching detail")
        other = [
            k for k, v in details.items()
            if k != self.source_type and v is not None
        ]
        if other:
            raise ValueError(
                f"{self.source_type} should not also populate {other}"
            )
        return self

    @model_validator(mode="after")
    def _citations_in_registry(self) -> "FieldLineage":
        from tools.citation_registry import REGISTRY
        unknown = [k for k in self.citations if k not in REGISTRY]
        if unknown:
            raise ValueError(f"Unregistered citation keys: {unknown}")
        return self

    @model_validator(mode="after")
    def _iteration_index_matches_source(self) -> "FieldLineage":
        in_loop = self.source_type in {"oracle_reading", "replanner_revision"}
        if in_loop and self.iteration_index is None:
            raise ValueError(f"{self.source_type} requires iteration_index")
        if (not in_loop) and self.iteration_index is not None:
            raise ValueError(f"{self.source_type} must not set iteration_index")
        return self

    @model_validator(mode="after")
    def _compute_ids(self) -> "FieldLineage":
        if self.id is None:
            parts = [
                self.source_type,
                str(self.iteration_index),
                self.placed_at.isoformat(),
                str(self.value),
                ":".join(sorted(self.citations)),
            ]
            self.id = hashlib.md5(":".join(parts).encode()).hexdigest()[:12]
        if self.parent is not None and self.parent_id is None:
            self.parent_id = self.parent.id
        return self
