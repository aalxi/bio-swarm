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
