"""Terminal renderer for FieldLineage chains. ANSI auto-disables off-TTY."""
from __future__ import annotations

import shutil
import sys
from typing import Optional

from schemas.lineage_schema import FieldLineage


_COLOR = {
    "paper_span":         "\x1b[36m",   # cyan
    "enricher_fill":      "\x1b[35m",   # magenta
    "oracle_reading":     "\x1b[33m",   # yellow
    "replanner_revision": "\x1b[32m",   # green
    "verified":           "\x1b[32m",
    "content_mismatch":   "\x1b[31m",
    "unreachable":        "\x1b[33m",
    "fail":               "\x1b[1;31m",
    "ok":                 "\x1b[1;32m",
    "reset":              "\x1b[0m",
}


def _c(s: str, key: str, enabled: bool) -> str:
    if not enabled:
        return s
    return _COLOR.get(key, "") + s + _COLOR["reset"]


def _walk_oldest_first(head: FieldLineage) -> list[FieldLineage]:
    chain: list[FieldLineage] = []
    cur: Optional[FieldLineage] = head
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    return list(reversed(chain))


def _format_record(fl: FieldLineage, color: bool, registry) -> list[str]:
    lines: list[str] = []
    header = f"{fl.source_type}"
    if fl.iteration_index is not None:
        header += f"  [iter {fl.iteration_index}]"
    lines.append(_c(header, fl.source_type, color))
    lines.append(f"  value = {fl.value!r}")
    lines.append(f"  placed_at = {fl.placed_at.isoformat()}")
    if fl.source_type == "paper_span" and fl.paper_span:
        lines.append(f"  doc_url   = {fl.paper_span.doc_url}")
        lines.append(f"  span_id   = {fl.paper_span.span_id}")
        lines.append(f"  quoted    = \"{fl.paper_span.quoted_text[:120]}\"")
    elif fl.source_type == "enricher_fill" and fl.enricher_fill:
        lines.append(f"  phase     = {fl.enricher_fill.phase}")
        lines.append(f"  confidence= {fl.enricher_fill.confidence:.2f}")
        if fl.enricher_fill.tavily_url:
            lines.append(f"  url       = {fl.enricher_fill.tavily_url}")
    elif fl.source_type == "oracle_reading" and fl.oracle_reading:
        o = fl.oracle_reading
        lines.append(f"  instrument= {o.instrument}")
        lines.append(f"  cq        = {o.cq}")
        lines.append(f"  regime    = {o.regime_label}")
        lines.append(f"  no_amp    = {o.no_amplification}")
        if o.raw_record_path:
            lines.append(f"  raw_csv   = {o.raw_record_path}")
    elif fl.source_type == "replanner_revision" and fl.replanner_revision:
        r = fl.replanner_revision
        lines.append(f"  action    = {r.action}")
        lines.append(f"  rule_id   = {r.rule_id}")
        if r.citation_failure:
            lines.append(_c("  citation_failure: yes", "fail", color))
        lines.append(f"  rationale = {_truncate_rationale(r.rationale)}")
        lines.append(f"  parent_value = {r.parent_value}")
        if r.parent_cq is not None:
            lines.append(f"  parent_cq    = {r.parent_cq}")
    if fl.citations:
        lines.append("  citations:")
        for key in fl.citations:
            tag = f"    - {key}"
            if registry and key in registry:
                cit = registry[key]
                status = cit.verification_status
                icon = {
                    "verified": "✓", "content_mismatch": "✗",
                    "unreachable": "⚠", "unchecked": "·",
                }.get(status, "·")
                tag += f"  [{_c(icon, status if status != 'unchecked' else 'reset', color)}]"
                if cit.quoted_text:
                    tag += f"  — \"{cit.quoted_text[:80]}\""
            lines.append(tag)
    return lines


def render_lineage_tree(
    head: FieldLineage, *, color: Optional[bool] = None, registry=None,
) -> str:
    """Render the lineage chain oldest-first as a flat, indented sequence
    of records. The chain is linear (every record has one parent), so a
    full tree is not needed — sequential rendering preserves ancestry."""
    if color is None:
        color = sys.stdout.isatty()
    if registry is None:
        try:
            from tools.citation_registry import REGISTRY as _R
            registry = _R
        except Exception:
            registry = {}
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)

    chain = _walk_oldest_first(head)
    out: list[str] = []
    for i, fl in enumerate(chain):
        prefix = "└─ " if i == len(chain) - 1 else "├─ "
        record_lines = _format_record(fl, color, registry)
        out.append(prefix + record_lines[0])
        for line in record_lines[1:]:
            out.append("│  " + line if i < len(chain) - 1 else "   " + line)
        if i < len(chain) - 1:
            out.append("│")
    return "\n".join(out)


def _count_by_source_type(fields: dict) -> dict[str, int]:
    counts = {
        "paper_span": 0, "enricher_fill": 0,
        "oracle_reading": 0, "replanner_revision": 0,
    }
    for head in fields.values():
        cur = head
        while cur is not None:
            counts[cur.source_type] = counts.get(cur.source_type, 0) + 1
            cur = cur.parent
    return counts


def _truncate_rationale(text: str, limit: int = 160) -> str:
    """Truncate *text* to at most *limit* chars on a word boundary.

    If no truncation is needed the original string is returned unchanged.
    If there is no whitespace within the first *limit* chars the text is hard-
    cut at *limit* (avoids returning an empty string).
    """
    if len(text) <= limit:
        return text
    idx = text.rfind(" ", 0, limit)
    cut = idx if idx > 0 else limit
    return text[:cut] + "…"


def _iteration_outcome(iters) -> tuple[str, str]:
    """Returns (color_key, label).

    Five states:
      DISABLED       — iteration was never enabled for this run
      CONVERGED      — loop exited with converged=True
      DIAGNOSE_REQUIRED — loop exited with diagnosis_required=True
      CAP_REACHED    — loop exhausted max iterations without converging
      NOT_REACHED    — enabled but no iterations actually completed yet
      PENDING        — enabled, some iterations done but no terminal flag set
    """
    if not iters.enabled:
        return "reset", "DISABLED"
    if iters.converged:
        return "ok", "CONVERGED"
    if iters.diagnosis_required:
        return "unreachable", "DIAGNOSE_REQUIRED"
    if iters.cap_reached:
        return "fail", "CAP_REACHED"
    if iters.iterations_completed == 0:
        return "reset", "NOT_REACHED"
    return "reset", "PENDING"


def render_aggregate_summary(
    task_id: str,
    all_field_lineages: dict,
    iterations_state,
    registry=None,
    *,
    color: Optional[bool] = None,
) -> str:
    """L22 — addresses the demo asymmetry. Per-field trees underplay the
    paper-extraction breadth; this header foregrounds it."""
    if color is None:
        color = sys.stdout.isatty()
    if registry is None:
        try:
            from tools.citation_registry import REGISTRY as _R
            registry = _R
        except Exception:
            registry = {}

    counts = _count_by_source_type(all_field_lineages)
    n_fields = len(all_field_lineages)
    color_key, outcome = _iteration_outcome(iterations_state)
    outcome_str = _c(outcome, color_key, color)

    verified = sum(1 for c in registry.values()
                   if c.verification_status == "verified")
    mismatch = sum(1 for c in registry.values()
                   if c.verification_status == "content_mismatch")
    unreachable = sum(1 for c in registry.values()
                      if c.verification_status == "unreachable")

    lines = [
        f"╭──── Lineage Summary · task {task_id} {'─' * 30}╮",
        f"│  Fields with lineage: {n_fields}",
        f"│    • paper_span:           {counts['paper_span']:>3} records  ({_c('cyan', 'paper_span', color)})",
        f"│    • enricher_fill (PIE):  {counts['enricher_fill']:>3} records  ({_c('magenta', 'enricher_fill', color)})",
        f"│    • oracle_reading:       {counts['oracle_reading']:>3} records  ({_c('yellow', 'oracle_reading', color)})",
        f"│    • replanner_revision:   {counts['replanner_revision']:>3} records  ({_c('green', 'replanner_revision', color)})",
        f"│  Citation health: {verified} verified · {mismatch} content_mismatch · {unreachable} unreachable",
        f"│  Iteration outcome: {outcome_str} in {iterations_state.iterations_completed} iterations",
        f"╰{'─' * 70}╯",
    ]
    return "\n".join(lines)
