"""Protocol Intelligence Enrichment (PIE) Agent.

Inserts between Methodology and Coder in the wet-lab pipeline.
Reads a sparse extracted protocol, identifies null critical fields,
launches targeted Tavily searches, and fills fields with confidence >= 0.7.
Overwrites protocol_{task_id}.json in place; saves enrichment_{task_id}.json
as an audit trail.

Wet-lab only. Non-blocking on failure — caller should treat errors as warnings
and continue the pipeline with the unchanged sparse protocol.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from typing import Any

from openai import OpenAI

from schemas.opentrons_schema import OpentronsProtocol
from tools.file_tool import load_json, save_json
from tools.tavily_tool import search_web
from tools.token_tracker import track_call

# ── Constants ─────────────────────────────────────────────────────────────────

# Fields that directly determine whether the coder can emit executable code.
# Listed in fill-priority order (most impactful first).
CRITICAL_FIELDS: list[str] = [
    "volume_ul",
    "pipettes",           # top-level list, handled separately
    "labware_setup",      # top-level list, handled separately
    "temperature_celsius",
    "duration_seconds",
    "speed_rpm",
    "source_location",
    "destination_location",
]

# Per-run Tavily query cap to avoid burning API credits on hopeless protocols.
MAX_QUERIES: int = 20

# Minimum confidence required to write a value into the protocol.
CONFIDENCE_THRESHOLD: float = 0.7

_client: OpenAI | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[enricher {_ts()}] {msg}", flush=True)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _llm(system: str, user: str) -> dict[str, Any]:
    """Single GPT-5.4-mini call with json_object response format."""
    response = _get_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    track_call("enricher", response)
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty LLM response in enricher")
    return json.loads(raw)


def _contract(
    status: str,
    output_files: list[str],
    message: str,
    retry_count: int,
    error_detail: str | None,
    gaps_filled: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "output_files": output_files,
        "message": message,
        "retry_count": retry_count,
        "error_detail": error_detail,
        "gaps_filled": gaps_filled,
    }


# ── Phase 1: Gap Analysis ─────────────────────────────────────────────────────

GAP_ANALYSIS_SYSTEM_PROMPT = """\
You are a protocol gap analyzer for a biology automation pipeline.
You receive an OpentronsProtocol JSON and must identify every null or missing
critical field that would prevent an Opentrons OT-2 script from being executable.

Critical fields (by priority):
  - volume_ul (per step) — required for all transfer/aspirate/dispense/mix/distribute/consolidate steps
  - pipettes (top-level list) — required for any liquid-handling
  - labware_setup (top-level list) — required for deck configuration; flag if list is empty or contains non-Opentrons names
  - temperature_celsius (per step) — required for incubate steps
  - duration_seconds (per step) — required for incubate and centrifuge steps
  - speed_rpm (per step) — required for centrifuge steps
  - source_location (per step) — required for transfer/aspirate steps
  - destination_location (per step) — required for transfer/dispense/distribute steps

For each gap found, generate a search_hint: a concise search string that would
help find the missing value from published protocols, kit inserts, or papers.
Derive the search_hint from fields that ARE populated (reagent names, protocol_name,
paper_source, step notes). Do NOT invent context not present in the JSON.

Return ONLY valid JSON:
{
  "gaps": [
    {
      "field": "<field name>",
      "step_number": <int or null for top-level fields>,
      "priority": "critical",
      "context": "<one sentence of non-null context from the protocol>",
      "search_hint": "<targeted search string to find this value>"
    }
  ]
}

If no critical nulls exist, return: {"gaps": []}
"""


def _analyze_gaps(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    """Phase 1: ask GPT-5.4-mini to identify all critical null fields."""
    data = _llm(
        GAP_ANALYSIS_SYSTEM_PROMPT,
        f"Analyze this protocol for critical null fields:\n\n{json.dumps(protocol, indent=2)}",
    )
    gaps = data.get("gaps", [])
    _log(f"Gap analysis: {len(gaps)} critical nulls identified")
    return gaps


# ── Phase 2: Targeted Search + Fill ──────────────────────────────────────────

QUERY_TEMPLATES: dict[str, list[str]] = {
    "volume_ul": [
        '"{protocol_name}" "{reagent}" reaction volume microliters protocol',
        '"{search_hint}" microliters standard volume',
    ],
    "pipettes": [
        'Opentrons OT-2 "{assay_type}" protocol pipette p20 p300 p1000 gen2',
        'opentrons "{search_hint}" pipette model channel',
    ],
    "labware_setup": [
        'Opentrons labware API name "{search_hint}" site:labware.opentrons.com',
        'opentrons labware library "{search_hint}" API string',
    ],
    "temperature_celsius": [
        '"{protocol_name}" "{search_hint}" incubation temperature celsius',
        '"{search_hint}" reaction temperature protocol methods',
    ],
    "duration_seconds": [
        '"{protocol_name}" "{search_hint}" incubation time minutes',
        '"{search_hint}" duration centrifuge time protocol',
    ],
    "speed_rpm": [
        '"{search_hint}" centrifuge speed rpm protocol',
        '"{protocol_name}" centrifuge speed rpm conditions',
    ],
    "source_location": [
        'Opentrons OT-2 "{assay_type}" deck layout slot position labware',
        'site:protocols.io Opentrons "{search_hint}" deck slot',
    ],
    "destination_location": [
        'Opentrons OT-2 "{assay_type}" destination well plate position',
        'site:protocols.io Opentrons "{search_hint}" destination slot',
    ],
}

VALUE_EXTRACT_SYSTEM_PROMPT = """\
You are extracting a single specific value from web search results for a
biology protocol enrichment task.

Return ONLY valid JSON with this exact structure:
{
  "found": true or false,
  "value": <the extracted value as the correct Python type, or null>,
  "confidence": <float 0.0-1.0>,
  "source_url": "<URL of the source where you found it, or null>",
  "rationale": "<one sentence explaining the evidence>"
}

Confidence scale:
  0.9+   — value is stated explicitly and unambiguously in the source
  0.7–0.89 — value is strongly implied or is a well-established default for this exact assay/kit
  0.5–0.69 — value is plausible but from a related protocol, not this exact one
  < 0.5  — speculative; set found=false

Type requirements (CRITICAL — failure to match type will fail validation):
  - volume_ul: Python float (e.g. 25.0, NOT "25 uL")
  - temperature_celsius: Python float (e.g. 42.0)
  - duration_seconds: Python int (convert minutes to seconds, e.g. 5 min → 300)
  - speed_rpm: Python int (e.g. 3000)
  - source_location: string well/slot identifier (e.g. "A1", "slot 1")
  - destination_location: string well/slot identifier
  - pipettes: list of Opentrons pipette name strings (e.g. ["p300_single_gen2"])
  - labware_setup: list of Opentrons labware name strings (e.g. ["opentrons_96_wellplate_200ul_pcr_full_skirt"])

NEVER return confidence >= 0.7 if the value is not clearly supported by the
search results provided.
"""


def _build_queries(gap: dict[str, Any], protocol: dict[str, Any]) -> list[str]:
    """Expand query templates for a gap using protocol context."""
    field = gap["field"]
    search_hint = gap.get("search_hint", "")
    protocol_name = protocol.get("protocol_name", "")
    reagents = protocol.get("reagents", [])
    reagent = reagents[0] if reagents else ""

    # Derive assay type from protocol name (first meaningful token pair)
    assay_type = " ".join(protocol_name.split()[:4]) if protocol_name else search_hint

    templates = QUERY_TEMPLATES.get(field, [
        f'"{search_hint}" biology protocol',
        f'"{protocol_name}" {field} protocol methods',
    ])

    queries = []
    for t in templates:
        q = (
            t.replace("{protocol_name}", protocol_name)
             .replace("{reagent}", reagent)
             .replace("{assay_type}", assay_type)
             .replace("{search_hint}", search_hint)
        )
        # Strip empty quoted strings that would confuse search
        q = q.replace('""', "").strip()
        queries.append(q)
    return queries[:2]  # Max 2 queries per gap


def _search_for_gap(gap: dict[str, Any], protocol: dict[str, Any]) -> list[dict]:
    """Run Tavily searches for a single gap. Returns combined result list."""
    queries = _build_queries(gap, protocol)
    all_results: list[dict] = []
    for q in queries:
        try:
            results = search_web(q, max_results=3, search_depth="advanced")
            all_results.extend(results)
            _log(f"  search '{q[:60]}...' → {len(results)} results")
        except Exception as e:
            _log(f"  search failed for '{q[:60]}': {e}")
    return all_results


def _extract_value(
    gap: dict[str, Any], search_results: list[dict], protocol: dict[str, Any]
) -> dict[str, Any]:
    """Phase 2b: call GPT-5.4-mini to extract the specific missing value."""
    field = gap["field"]
    context = gap.get("context", "")
    step_number = gap.get("step_number")

    # Summarize search results for the LLM (cap to avoid token overflow)
    result_text = ""
    for r in search_results[:6]:
        url = r.get("url", "")
        title = r.get("title", "")
        content = r.get("raw_content") or r.get("content") or ""
        result_text += f"\n--- {title} ({url}) ---\n{content[:1500]}\n"

    user_msg = (
        f"Field to extract: {field}\n"
        f"Step context: {context}\n"
        f"Step number: {step_number}\n"
        f"Protocol name: {protocol.get('protocol_name', '')}\n"
        f"Reagents: {json.dumps(protocol.get('reagents', []))}\n\n"
        f"Search results:\n{result_text}"
    )

    try:
        return _llm(VALUE_EXTRACT_SYSTEM_PROMPT, user_msg)
    except Exception as e:
        return {
            "found": False,
            "value": None,
            "confidence": 0.0,
            "source_url": None,
            "rationale": f"LLM extraction failed: {e}",
        }


def _apply_fill(
    protocol_dict: dict[str, Any],
    gap: dict[str, Any],
    extracted: dict[str, Any],
) -> None:
    """Mutate protocol_dict in place, applying the extracted value to the right location."""
    field = gap["field"]
    step_number = gap.get("step_number")
    value = extracted["value"]
    confidence = extracted["confidence"]
    source_url = extracted.get("source_url")

    if field in ("pipettes", "labware_setup"):
        # Top-level list fields
        if isinstance(value, list) and value:
            protocol_dict[field] = value
        return

    if step_number is None:
        return

    # Per-step fields
    for step in protocol_dict.get("sequential_steps", []):
        if step.get("step_number") == step_number:
            step[field] = value
            # Record enrichment metadata on the step
            if "field_confidence" not in step or step["field_confidence"] is None:
                step["field_confidence"] = {}
            if "field_sources" not in step or step["field_sources"] is None:
                step["field_sources"] = {}
            step["field_confidence"][field] = confidence
            step["field_sources"][field] = source_url
            break


# ── Phase 3: Re-validate and Save ────────────────────────────────────────────

def _save_enrichment_log(log: dict[str, Any], task_id: str) -> str:
    path = f"workspace/extracted_protocols/enrichment_{task_id}.json"
    save_json(log, path)
    return path


# ── Main entry point ──────────────────────────────────────────────────────────

def enricher_agent(methodology_result: dict, task_id: str) -> dict[str, Any]:
    """Protocol Intelligence Enrichment (PIE) Agent.

    Reads the sparse protocol from workspace/extracted_protocols/protocol_{task_id}.json,
    identifies critical null fields, hunts for their values via targeted Tavily searches,
    fills fields with confidence >= 0.7, and overwrites the protocol file in place.

    Returns the Agent Return Contract dict (plus extra key 'gaps_filled').
    Non-blocking: errors should be caught by the caller and treated as warnings.
    """
    protocol_path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    enrichment_path = f"workspace/extracted_protocols/enrichment_{task_id}.json"

    # ── Load protocol ────────────────────────────────────────────────────────
    try:
        protocol_dict = load_json(protocol_path)
    except FileNotFoundError:
        return _contract(
            "error", [], f"Protocol file not found: {protocol_path}", 0,
            f"Missing: {protocol_path}",
        )
    except json.JSONDecodeError as e:
        return _contract("error", [], "Protocol JSON is invalid", 0, str(e))

    # Save a backup before any mutation
    protocol_backup = copy.deepcopy(protocol_dict)

    # ── Phase 1: Gap analysis ────────────────────────────────────────────────
    try:
        gaps = _analyze_gaps(protocol_dict)
    except Exception as e:
        return _contract("error", [], "Gap analysis LLM call failed", 0, str(e))

    if not gaps:
        _log("No critical gaps found — protocol is already fully populated")
        # Mark pie_ran and save (no changes to field values)
        protocol_dict["pie_ran"] = True
        protocol_dict["enrichment_log"] = {
            "gaps_identified": 0,
            "gaps_filled": 0,
            "tavily_queries_executed": 0,
            "fills": [],
            "conflicts": [],
            "still_null": [],
        }
        save_json(protocol_dict, protocol_path)
        log_path = _save_enrichment_log(protocol_dict["enrichment_log"], task_id)
        return _contract(
            "success",
            [protocol_path, log_path],
            "PIE: no critical gaps found — protocol fully populated",
            0, None, gaps_filled=0,
        )

    # Apply query budget cap
    gaps_to_process = gaps[:MAX_QUERIES // 2]  # 2 queries per gap
    if len(gaps) > len(gaps_to_process):
        _log(f"Query budget cap: processing {len(gaps_to_process)}/{len(gaps)} gaps")

    # ── Phase 2: Search and fill ─────────────────────────────────────────────
    fills: list[dict] = []
    conflicts: list[dict] = []
    still_null: list[dict] = []
    queries_executed = 0

    # Group gaps by (field, step_number) so we detect conflicts across sources
    # For each gap: run searches, extract value candidates, apply if confident
    for gap in gaps_to_process:
        field = gap["field"]
        step_number = gap.get("step_number")
        _log(f"Processing gap: field={field} step={step_number}")

        search_results = _search_for_gap(gap, protocol_dict)
        queries_executed += len(_build_queries(gap, protocol_dict))

        if not search_results:
            still_null.append({
                "field": field,
                "step_number": step_number,
                "reason": "No search results returned",
            })
            continue

        extracted = _extract_value(gap, search_results, protocol_dict)
        confidence = extracted.get("confidence", 0.0)
        found = extracted.get("found", False)
        value = extracted.get("value")

        _log(
            f"  extracted: found={found} confidence={confidence:.2f} "
            f"value={repr(value)[:60]}"
        )

        if not found or confidence < CONFIDENCE_THRESHOLD or value is None:
            reason = extracted.get("rationale", "Confidence below threshold")
            still_null.append({
                "field": field,
                "step_number": step_number,
                "reason": reason,
            })
            continue

        # Check for conflicts with already-applied fills for the same field/step
        existing_fill = next(
            (f for f in fills if f["field"] == field and f["step_number"] == step_number),
            None,
        )
        if existing_fill:
            existing_val = existing_fill.get("filled_value")
            if existing_val != value:
                # Conflict — record but do not overwrite
                conflicts.append({
                    "field": field,
                    "step_number": step_number,
                    "candidates": [
                        {
                            "value": existing_val,
                            "confidence": existing_fill["confidence"],
                            "source": existing_fill.get("source_url"),
                        },
                        {
                            "value": value,
                            "confidence": confidence,
                            "source": extracted.get("source_url"),
                        },
                    ],
                    "resolution": "not_filled",
                    "note": "Two sources disagree — field left as-is",
                })
                # Remove the previously applied fill to revert the mutation
                fills = [f for f in fills if not (f["field"] == field and f["step_number"] == step_number)]
                # Revert the field in protocol_dict to the backup value
                if step_number is not None:
                    for step in protocol_dict.get("sequential_steps", []):
                        if step.get("step_number") == step_number:
                            backup_step = next(
                                (s for s in protocol_backup.get("sequential_steps", [])
                                 if s.get("step_number") == step_number),
                                {},
                            )
                            step[field] = backup_step.get(field)
                            break
                else:
                    protocol_dict[field] = protocol_backup.get(field)
                continue

        # Apply fill
        _apply_fill(protocol_dict, gap, extracted)
        fills.append({
            "field": field,
            "step_number": step_number,
            "filled_value": value,
            "confidence": confidence,
            "source_url": extracted.get("source_url"),
            "rationale": extracted.get("rationale", ""),
        })
        _log(f"  ✓ filled {field} (step {step_number}) = {repr(value)[:40]} [conf={confidence:.2f}]")

    gaps_filled_count = len(fills)
    _log(
        f"PIE complete: {gaps_filled_count}/{len(gaps)} gaps filled, "
        f"{len(conflicts)} conflicts, {len(still_null)} still null"
    )

    # ── Build enrichment log ─────────────────────────────────────────────────
    enrichment_log = {
        "gaps_identified": len(gaps),
        "gaps_filled": gaps_filled_count,
        "tavily_queries_executed": queries_executed,
        "fills": fills,
        "conflicts": conflicts,
        "still_null": still_null,
    }

    # Embed summary into protocol JSON
    protocol_dict["pie_ran"] = True
    protocol_dict["enrichment_log"] = enrichment_log

    # ── Phase 3: Re-validate and save ────────────────────────────────────────
    try:
        OpentronsProtocol.model_validate(protocol_dict)
    except Exception as validation_err:
        _log(f"Re-validation failed after enrichment: {validation_err} — reverting")
        # Revert to backup, but still record the attempt in a lean enrichment log
        protocol_backup["pie_ran"] = True
        protocol_backup["enrichment_log"] = {
            "gaps_identified": len(gaps),
            "gaps_filled": 0,
            "tavily_queries_executed": queries_executed,
            "fills": [],
            "conflicts": conflicts,
            "still_null": [
                {"field": g["field"], "step_number": g.get("step_number"),
                 "reason": "Reverted: enrichment caused Pydantic validation failure"}
                for g in gaps
            ],
        }
        save_json(protocol_backup, protocol_path)
        log_path = _save_enrichment_log(protocol_backup["enrichment_log"], task_id)
        return _contract(
            "error",
            [protocol_path, log_path],
            "PIE enrichment caused validation failure — reverted to sparse protocol",
            0,
            str(validation_err),
            gaps_filled=0,
        )

    # Save enriched protocol (overwrites in place)
    save_json(protocol_dict, protocol_path)
    # Save standalone enrichment audit log
    log_path = _save_enrichment_log(enrichment_log, task_id)

    return _contract(
        "success",
        [protocol_path, log_path],
        (
            f"PIE complete: {gaps_filled_count}/{len(gaps)} critical fields enriched "
            f"({len(conflicts)} conflicts, {len(still_null)} still null)"
        ),
        0,
        None,
        gaps_filled=gaps_filled_count,
    )
