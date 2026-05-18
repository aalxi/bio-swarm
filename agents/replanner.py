"""Replanner agent. Architecture (L8):
- Deterministic heuristic decides (action, new_value, rule_id)
- LLM narrates rationale string, constrained to registry-keyed citations
- On second consecutive citation-validation failure, rationale is replaced
  entirely with a deterministic string (L21).

The agent appends a FieldLineage(replanner_revision) record to the field's
chain and writes an IterationRevision to state.iterations.revisions.
# TODO(2.8): IterationRevision write happens in supervisor wiring
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any, Optional

from schemas.lineage_schema import (
    FieldLineage, ReplannerRevisionDetail,
)
from tools.mock_qpcr import QPCRReading


def _clamp(x: float) -> float:
    return max(0.1, min(200.0, x))


def decide_action(
    reading: QPCRReading, current_template_ng: float,
) -> tuple[str, Optional[float], str]:
    """Returns (action, new_value, rule_id). Pure function. Decision can't drift."""
    if (
        reading.regime_label == "clean"
        and reading.cq is not None
        and 22.0 <= reading.cq <= 32.0
    ):
        return ("converged", None, "rule.converged.clean_optimal_range")

    if reading.no_amplification:
        if current_template_ng > 50:
            return (
                "reduce_template", _clamp(current_template_ng * 0.25),
                "rule.no_amp.high_template.reduce",
            )
        return (
            "increase_template", _clamp(current_template_ng * 4.0),
            "rule.no_amp.low_template.increase",
        )

    # ambiguous (Cq 33-37)
    if current_template_ng > 50:
        return (
            "reduce_template", _clamp(current_template_ng * 0.25),
            "rule.ambiguous.high_template.reduce",
        )
    if current_template_ng < 5:
        return (
            "increase_template", _clamp(current_template_ng * 4.0),
            "rule.ambiguous.low_template.increase",
        )
    # L20: ambiguous mid-range (5-50 ng) cannot be resolved by template alone
    return (
        "diagnose_required", None,
        "rule.ambiguous.mid_template.diagnose_required",
    )
