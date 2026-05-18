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


import os
from openai import OpenAI

from tools.citation_registry import REGISTRY
from tools.token_tracker import track_call

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _chat_completion(**kwargs):
    """Wrapped for monkeypatch in tests."""
    return _get_client().chat.completions.create(**kwargs)


REPLANNER_SYSTEM_PROMPT = """\
You are writing the rationale string for an action that has already been
decided by a deterministic rule. Do not change the action. Do not invent
citations. You may cite ONLY from this list of registry keys:

{registry_keys}

Any citation_key not in this list will cause your output to be rejected.

For action='diagnose_required': explain that the regime (ambiguous Cq at
mid-range template, 5-50 ng) cannot be resolved by template adjustment
alone — possible causes include inhibitor contamination, primer issues,
or non-template factors. The user should diagnose with a 4-5 log dilution
series per MIQE before changing the protocol.

Output strict JSON: {{"rationale": str, "citation_keys": [str, ...]}}.
"""


def _llm_call_with_retry(
    prompt: str, action: str, rule_id: str,
) -> tuple[str, list[str], bool]:
    """Returns (rationale, citation_keys, citation_failure_flag).
    L21: on second consecutive failure, rationale is REPLACED ENTIRELY with
    a deterministic string. No preserved LLM prose."""
    registry_keys = sorted(REGISTRY.keys())
    sys_prompt = REPLANNER_SYSTEM_PROMPT.format(registry_keys=registry_keys)
    user_messages = [{"role": "user", "content": prompt}]

    rejected_keys: list[str] = []
    for attempt in (1, 2):
        if attempt == 2 and rejected_keys:
            user_messages.append({
                "role": "user",
                "content": (
                    f"Your previous response cited unknown keys: {rejected_keys}. "
                    f"Cite ONLY from the registry. Retry."
                ),
            })
        try:
            response = _chat_completion(
                model="gpt-5.4-mini",
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": sys_prompt}, *user_messages],
            )
            try:
                track_call("replanner", response)
            except Exception:
                pass
            raw = response.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            keys = parsed.get("citation_keys", []) or []
            rationale = parsed.get("rationale", "") or ""
            unknown = [k for k in keys if k not in REGISTRY]
            if not unknown:
                return rationale, keys, False
            rejected_keys = unknown
        except Exception:
            rejected_keys = ["<llm_error>"]

    # L21: deterministic fallback — never preserve hallucinated prose
    deterministic = (
        f"Citation validation failed; action {action} chosen per "
        f"deterministic rule {rule_id}. See state.iterations.revisions "
        f"for the rule trace."
    )
    return deterministic, [], True
