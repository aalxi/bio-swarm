"""Protocol Intelligence Enrichment (PIE) Agent.

Inserts between Methodology and Coder in the wet-lab pipeline.
Reads a sparse extracted protocol, identifies null critical fields,
launches targeted Tavily searches, and fills fields with confidence >= CONFIDENCE_THRESHOLD.
Overwrites protocol_{task_id}.json in place; saves enrichment_{task_id}.json
as an audit trail.

Wet-lab only. Non-blocking on failure — caller should treat errors as warnings
and continue the pipeline with the unchanged sparse protocol.

PIE v2 improvements over v1:
  - Phase 0: notes mining (find values already stated in extraction_notes/step notes)
  - Domain-filtered Tavily searches (prioritize PMC, protocols.io; suppress paywalled publishers)
  - include_raw_content=True for full inline page text
  - Bulk PMC/biorxiv extraction via extract_urls_bulk()
  - CONFIDENCE_THRESHOLD lowered to 0.55 (allows "standard for this assay" inferences)
  - Concise search_hint-based query templates (not long protocol_name quotes)
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from openai import OpenAI

from schemas.opentrons_schema import OpentronsProtocol
from tools.file_tool import load_json, save_json
from tools.tavily_tool import extract_urls_bulk, search_web
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

# Minimum confidence to apply a Tavily-sourced fill.
# 0.55 allows "standard for this assay class" inferences, not just explicit quotes.
CONFIDENCE_THRESHOLD: float = 0.60

# Confidence assigned to values sourced from the protocol's own notes
# (they came from the source paper, just weren't placed into the field).
NOTES_DERIVED_CONFIDENCE: float = 0.88

# Open-access domains to prefer in PIE searches (full-text available).
OPEN_ACCESS_DOMAINS: list[str] = [
    "pmc.ncbi.nlm.nih.gov",
    "biorxiv.org",
    "protocols.io",
    "openwetware.org",
    "addgene.org",
    "benchling.com",
    "pubmed.ncbi.nlm.nih.gov",
]

# Paywalled publishers — suppress when we already have a hit from one of them,
# since their search snippets are truncated and full text is inaccessible.
PAYWALL_DOMAINS: list[str] = [
    "nature.com",
    "science.org",
    "cell.com",
    "sciencedirect.com",
    "wiley.com",
    "springer.com",
]

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


# ── Phase 0: Notes Mining ─────────────────────────────────────────────────────

NOTES_MINER_SYSTEM_PROMPT = """\
You are reading a biology protocol's text notes to find values that are explicitly
mentioned in the notes but not yet assigned to structured fields.

You receive the full protocol JSON and a list of gaps (null critical fields).
For each gap, check if the answer can be found in:
  - The protocol's top-level `extraction_notes` list
  - Individual step `notes` strings

Examples of what to look for:
  - "70 µl reaction" in extraction_notes → volume_ul = 70.0 for steps of this single-volume assay
  - "p300 single channel pipette" in a note → pipettes = ["p300_single_gen2"]
  - "25°C room temperature incubation" in step notes → temperature_celsius = 25.0
  - "5 minutes" in step notes where duration_seconds is null → duration_seconds = 300

Use confidence 0.88 when the value is explicitly stated in a note (it came from the source paper).
Use confidence 0.70 when the value is strongly implied by the note (e.g. "short spin" → 3000 rpm).
Do NOT invent values not present in the notes.

Type requirements (CRITICAL):
  - volume_ul: Python float (e.g. 70.0)
  - temperature_celsius: Python float (e.g. 42.0)
  - duration_seconds: Python int (e.g. 300)
  - speed_rpm: Python int (e.g. 3000)
  - pipettes: list of Opentrons pipette name strings (e.g. ["p300_single_gen2"])
  - labware_setup: list of Opentrons labware API name strings
  - source_location / destination_location: string (e.g. "A1")

Return ONLY valid JSON:
{
  "note_fills": [
    {
      "field": "<field name>",
      "step_number": <int or null for top-level fields>,
      "value": <correctly-typed value>,
      "confidence": <float>,
      "source_note": "<verbatim text from the note containing this value>",
      "rationale": "<one sentence>"
    }
  ]
}
If no values can be derived from notes, return: {"note_fills": []}
"""


def _mine_notes(protocol: dict[str, Any], gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase 0: find values already stated in extraction_notes / step notes."""
    data = _llm(
        NOTES_MINER_SYSTEM_PROMPT,
        (
            f"Protocol JSON:\n{json.dumps(protocol, indent=2)}\n\n"
            f"Gaps to fill:\n{json.dumps(gaps, indent=2)}"
        ),
    )
    note_fills = data.get("note_fills", [])
    _log(f"Notes mining: {len(note_fills)} values found in protocol notes")
    return note_fills


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

For each gap found, generate a search_hint: a SHORT, concise search string (4-8 words)
that would help find the missing value from published protocols or papers.
Derive the search_hint from fields that ARE populated (reagent names, step notes).
Do NOT use the full protocol_name in search_hint — it is too long for exact-match queries.
Do NOT invent context not present in the JSON.

Return ONLY valid JSON:
{
  "gaps": [
    {
      "field": "<field name>",
      "step_number": <int or null for top-level fields>,
      "priority": "critical",
      "context": "<one sentence of non-null context from the protocol>",
      "search_hint": "<short targeted search string, 4-8 words>"
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

# Templates use {search_hint} (short, LLM-generated) not {protocol_name} (too long for exact-match).
# site: prefixes pin results to full-text open-access sources.
QUERY_TEMPLATES: dict[str, list[str]] = {
    "volume_ul": [
        '"{search_hint}" reaction volume microliters',
        'site:pmc.ncbi.nlm.nih.gov "{search_hint}" µl reaction',
    ],
    "pipettes": [
        'Opentrons OT-2 protocols.io "{assay_type}" pipette p20 p300',
        '"{assay_type}" liquid handler pipette channel volume range',
    ],
    "labware_setup": [
        'opentrons labware "{search_hint}" API name',
        'site:labware.opentrons.com "{search_hint}"',
    ],
    "temperature_celsius": [
        '"{search_hint}" incubation temperature celsius protocol',
        'site:pmc.ncbi.nlm.nih.gov "{search_hint}" temperature °C',
    ],
    "duration_seconds": [
        '"{search_hint}" incubation time minutes protocol',
        'site:pmc.ncbi.nlm.nih.gov "{search_hint}" duration minutes',
    ],
    "speed_rpm": [
        '"{search_hint}" centrifuge speed rpm protocol',
        '"{search_hint}" g-force centrifuge conditions',
    ],
    "source_location": [
        'site:protocols.io opentrons "{assay_type}" deck layout wells',
        'opentrons OT-2 "{search_hint}" source well plate',
    ],
    "destination_location": [
        'site:protocols.io opentrons "{assay_type}" destination well plate',
        'opentrons OT-2 "{search_hint}" destination slot labware',
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
  0.9+     — value is stated explicitly and unambiguously in the source
  0.75–0.89 — value is strongly implied or is a well-established default for this exact assay/kit
  0.60–0.74 — value is plausible, from a closely related protocol or general assay standard — ACCEPTABLE to fill
  < 0.55   — speculative; set found=false

Type requirements (CRITICAL — failure to match type will fail validation):
  - volume_ul: Python float (e.g. 25.0, NOT "25 uL")
  - temperature_celsius: Python float (e.g. 42.0)
  - duration_seconds: Python int (convert minutes to seconds, e.g. 5 min → 300)
  - speed_rpm: Python int (e.g. 3000)
  - source_location: string well/slot identifier (e.g. "A1", "slot 1")
  - destination_location: string well/slot identifier
  - pipettes: list of Opentrons pipette name strings (e.g. ["p300_single_gen2"])
  - labware_setup: list of Opentrons labware name strings (e.g. ["opentrons_96_wellplate_200ul_pcr_full_skirt"])

For volume_ul: if the source states a single reaction volume (e.g. "70 µl reactions")
without breaking it down per-step, use that value for all liquid-handling steps in a
single-vessel assay — this is standard practice.
"""


def _build_queries(gap: dict[str, Any], protocol: dict[str, Any]) -> list[str]:
    """Expand query templates for a gap using protocol context."""
    field = gap["field"]
    search_hint = gap.get("search_hint", "")
    protocol_name = protocol.get("protocol_name", "")

    # Derive a short assay type label (first 4 words of protocol name)
    assay_type = " ".join(protocol_name.split()[:4]) if protocol_name else search_hint

    templates = QUERY_TEMPLATES.get(field, [
        f'"{search_hint}" biology protocol',
        f'"{search_hint}" {field} methods',
    ])

    queries = []
    for t in templates:
        q = (
            t.replace("{assay_type}", assay_type)
             .replace("{search_hint}", search_hint)
        )
        # Strip empty quoted strings that would confuse search
        q = q.replace('""', "").strip()
        queries.append(q)
    return queries[:2]  # Max 2 queries per gap


def _search_for_gap(
    gap: dict[str, Any],
    protocol: dict[str, Any],
    research_urls: list[str],
    already_paywalled: bool,
) -> list[dict]:
    """Run Tavily searches for a single gap. Returns combined result list.

    Uses open-access domain filtering and inline raw_content.
    After search, bulk-extracts any PMC/biorxiv URLs (from results + research bundle)
    for full Methods section content.
    """
    queries = _build_queries(gap, protocol)
    all_results: list[dict] = []

    exclude = PAYWALL_DOMAINS if already_paywalled else []

    for q in queries:
        try:
            results = search_web(
                q,
                max_results=5,
                search_depth="advanced",
                include_raw_content=True,
                include_domains=OPEN_ACCESS_DOMAINS,
                exclude_domains=exclude,
            )
            all_results.extend(results)
            _log(f"  search '{q[:70]}' → {len(results)} results")
        except Exception as e:
            _log(f"  search failed for '{q[:70]}': {e}")

    # Collect PMC / biorxiv URLs from search results + original research bundle
    seen_urls: set[str] = set()
    pmc_urls: list[str] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            if "pmc.ncbi.nlm.nih.gov" in url or "biorxiv.org" in url:
                pmc_urls.append(url)
                seen_urls.add(url)

    for url in research_urls:
        if url and url not in seen_urls:
            if any(d in url for d in ["pmc.ncbi.nlm.nih.gov", "biorxiv.org", "protocols.io"]):
                pmc_urls.append(url)
                seen_urls.add(url)

    if pmc_urls:
        try:
            bulk = extract_urls_bulk(
                pmc_urls[:5],
                extract_depth="advanced",
                query=gap.get("search_hint", ""),
            )
            for br in bulk:
                raw = br.get("raw_content", "")
                if raw:
                    all_results.append({
                        "url": br.get("url", ""),
                        "title": "Full-text extraction",
                        "content": "",
                        "raw_content": raw,
                        "score": 1.0,
                    })
            _log(f"  bulk extracted {len(bulk)} PMC/biorxiv URLs")
        except Exception as e:
            _log(f"  bulk extract failed: {e}")

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
        result_text += f"\n--- {title} ({url}) ---\n{content[:2000]}\n"

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
    field: str,
    step_number: int | None,
    value: Any,
    confidence: float,
    source_url: str | None,
) -> None:
    """Mutate protocol_dict in place, applying value to the correct location."""
    if field in ("pipettes", "labware_setup"):
        if isinstance(value, list) and value:
            protocol_dict[field] = value
        return

    if step_number is None:
        return

    for step in protocol_dict.get("sequential_steps", []):
        if step.get("step_number") == step_number:
            step[field] = value
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
    identifies critical null fields, and fills them via:
      Phase 0 — notes mining (values already stated in extraction_notes/step notes)
      Phase 1 — gap analysis (identify remaining nulls + generate search hints)
      Phase 2 — targeted Tavily searches with open-access domain filtering + bulk PMC extraction
      Phase 3 — Pydantic re-validation and in-place overwrite

    Returns the Agent Return Contract dict (plus extra key 'gaps_filled').
    Non-blocking: errors should be caught by the caller and treated as warnings.
    """
    protocol_path = f"workspace/extracted_protocols/protocol_{task_id}.json"

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

    # Save a deep backup before any mutation
    protocol_backup = copy.deepcopy(protocol_dict)

    # ── Load original research bundle for known URLs ─────────────────────────
    research_bundle_path = f"workspace/raw_research/{task_id}_combined.json"
    try:
        research_bundle = load_json(research_bundle_path)
        research_urls: list[str] = research_bundle.get("all_sources", [])
        already_paywalled = any(
            any(d in url for d in PAYWALL_DOMAINS)
            for url in research_urls
        )
    except Exception:
        research_urls = []
        already_paywalled = False

    # ── Phase 1: Gap analysis ────────────────────────────────────────────────
    try:
        gaps = _analyze_gaps(protocol_dict)
    except Exception as e:
        return _contract("error", [], "Gap analysis LLM call failed", 0, str(e))

    if not gaps:
        _log("No critical gaps found — protocol is already fully populated")
        protocol_dict["pie_ran"] = True
        protocol_dict["enrichment_log"] = {
            "gaps_identified": 0,
            "gaps_filled": 0,
            "note_fills": 0,
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

    # ── Phase 0: Notes mining ────────────────────────────────────────────────
    fills: list[dict] = []
    filled_keys: set[tuple] = set()  # (field, step_number) pairs already filled

    try:
        note_fills = _mine_notes(protocol_dict, gaps)
    except Exception as e:
        _log(f"Notes mining failed (non-fatal): {e}")
        note_fills = []

    for nf in note_fills:
        field = nf.get("field")
        step_number = nf.get("step_number")
        value = nf.get("value")
        confidence = float(nf.get("confidence", NOTES_DERIVED_CONFIDENCE))

        if not field or value is None:
            continue
        if confidence < CONFIDENCE_THRESHOLD:
            continue

        key = (field, step_number)
        if key in filled_keys:
            continue  # already filled by a prior note fill

        _apply_fill(protocol_dict, field, step_number, value, confidence, source_url=None)
        fills.append({
            "field": field,
            "step_number": step_number,
            "filled_value": value,
            "confidence": confidence,
            "source_url": None,
            "source_note": nf.get("source_note", ""),
            "rationale": nf.get("rationale", "derived from protocol notes"),
        })
        filled_keys.add(key)
        _log(f"  ✓ [notes] filled {field} (step {step_number}) = {repr(value)[:40]} [conf={confidence:.2f}]")

    _log(f"Phase 0 complete: {len(fills)} fields filled from notes")

    # Determine which gaps are still open after notes mining
    remaining_gaps = [
        g for g in gaps
        if (g["field"], g.get("step_number")) not in filled_keys
    ]

    # Apply query budget cap (2 queries per gap)
    gaps_to_search = remaining_gaps[: MAX_QUERIES // 2]
    if len(remaining_gaps) > len(gaps_to_search):
        _log(f"Query budget cap: searching {len(gaps_to_search)}/{len(remaining_gaps)} remaining gaps")

    # ── Phase 2: Targeted search + fill ─────────────────────────────────────
    conflicts: list[dict] = []
    still_null: list[dict] = []
    queries_executed = 0

    for gap in gaps_to_search:
        field = gap["field"]
        step_number = gap.get("step_number")
        _log(f"Processing gap: field={field} step={step_number}")

        search_results = _search_for_gap(gap, protocol_dict, research_urls, already_paywalled)
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

        key = (field, step_number)

        # Conflict detection: if we already filled this key, check for disagreement
        existing_fill = next(
            (f for f in fills if f["field"] == field and f["step_number"] == step_number),
            None,
        )
        if existing_fill:
            existing_val = existing_fill.get("filled_value")
            if existing_val != value:
                conflicts.append({
                    "field": field,
                    "step_number": step_number,
                    "candidates": [
                        {"value": existing_val, "confidence": existing_fill["confidence"],
                         "source": existing_fill.get("source_url")},
                        {"value": value, "confidence": confidence,
                         "source": extracted.get("source_url")},
                    ],
                    "resolution": "not_filled",
                    "note": "Two sources disagree — field left as-is",
                })
                # Revert the previously-applied fill
                fills = [f for f in fills if not (f["field"] == field and f["step_number"] == step_number)]
                filled_keys.discard(key)
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

        _apply_fill(protocol_dict, field, step_number, value, confidence, extracted.get("source_url"))
        fills.append({
            "field": field,
            "step_number": step_number,
            "filled_value": value,
            "confidence": confidence,
            "source_url": extracted.get("source_url"),
            "rationale": extracted.get("rationale", ""),
        })
        filled_keys.add(key)
        _log(f"  ✓ filled {field} (step {step_number}) = {repr(value)[:40]} [conf={confidence:.2f}]")

    # Gaps in original list that are still null after both phases
    for gap in gaps:
        key = (gap["field"], gap.get("step_number"))
        if key not in filled_keys and not any(
            c["field"] == gap["field"] and c["step_number"] == gap.get("step_number")
            for c in conflicts
        ):
            if not any(
                s["field"] == gap["field"] and s["step_number"] == gap.get("step_number")
                for s in still_null
            ):
                still_null.append({
                    "field": gap["field"],
                    "step_number": gap.get("step_number"),
                    "reason": "Gap not searched (budget cap or notes-filled)",
                })

    gaps_filled_count = len(fills)
    note_fills_count = sum(1 for f in fills if "source_note" in f)
    _log(
        f"PIE complete: {gaps_filled_count}/{len(gaps)} gaps filled "
        f"({note_fills_count} from notes, {gaps_filled_count - note_fills_count} from Tavily), "
        f"{len(conflicts)} conflicts, {len(still_null)} still null"
    )

    # ── Build enrichment log ─────────────────────────────────────────────────
    enrichment_log = {
        "gaps_identified": len(gaps),
        "gaps_filled": gaps_filled_count,
        "note_fills": note_fills_count,
        "tavily_queries_executed": queries_executed,
        "fills": fills,
        "conflicts": conflicts,
        "still_null": still_null,
    }

    protocol_dict["pie_ran"] = True
    protocol_dict["enrichment_log"] = enrichment_log

    # ── Phase 3: Re-validate and save ────────────────────────────────────────
    try:
        OpentronsProtocol.model_validate(protocol_dict)
    except Exception as validation_err:
        _log(f"Re-validation failed after enrichment: {validation_err} — reverting")
        protocol_backup["pie_ran"] = True
        protocol_backup["enrichment_log"] = {
            "gaps_identified": len(gaps),
            "gaps_filled": 0,
            "note_fills": 0,
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

    save_json(protocol_dict, protocol_path)
    log_path = _save_enrichment_log(enrichment_log, task_id)

    return _contract(
        "success",
        [protocol_path, log_path],
        (
            f"PIE complete: {gaps_filled_count}/{len(gaps)} critical fields enriched "
            f"({note_fills_count} from notes, {gaps_filled_count - note_fills_count} from Tavily; "
            f"{len(conflicts)} conflicts, {len(still_null)} still null)"
        ),
        0,
        None,
        gaps_filled=gaps_filled_count,
    )
