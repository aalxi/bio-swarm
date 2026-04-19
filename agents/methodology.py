"""Methodology Agent — Extractor: raw research → validated Pydantic JSON.

Reads raw research files from workspace/raw_research/, sends content to GPT-5.4 mini
to extract structured protocol data matching the target Pydantic schema, validates
the output, and saves it to workspace/extracted_protocols/.
"""

import json
import re
from openai import OpenAI
from tools.file_tool import load_json, save_json
from tools.token_tracker import track_call
from tools.tavily_tool import search_web
from schemas.opentrons_schema import OpentronsProtocol
from schemas.dry_lab_schema import ReproducibilityTarget

_client = None


def _get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


WET_LAB_SYSTEM_PROMPT = """\
You are a methodology extraction agent for a biology research pipeline.
Your job is to read raw research data (search results, scraped page content) and extract
a structured protocol that matches the OpentronsProtocol schema EXACTLY.

You MUST return ONLY valid JSON with these exact fields and types:

{
  "protocol_name": string,           // name for this protocol
  "paper_source": string,            // paper title or DOI
  "labware_setup": [string],         // Opentrons API labware names (e.g. "opentrons_96_wellplate_200ul_pcr_full_skirt")
  "pipettes": [string],              // e.g. ["p300_single_gen2", "p20_single_gen2"]
  "reagents": [string],              // list of reagent names used
  "sequential_steps": [              // ordered list of protocol steps
    {
      "step_number": int,
      "action": "transfer" | "distribute" | "consolidate" | "mix" | "incubate" | "centrifuge" | "aspirate" | "dispense",
      "volume_ul": float or null,
      "source_location": string or null,       // e.g. "A1"
      "destination_location": string or null,
      "duration_seconds": int or null,         // for incubate/centrifuge
      "speed_rpm": int or null,                // for centrifuge
      "temperature_celsius": float or null,    // for incubate
      "notes": string or null                  // ambiguities from the paper
    }
  ],
  "extraction_notes": [string]       // list of notes about missing or ambiguous fields
}

CRITICAL RULES:
- If a value is ambiguous or not stated in the source material, set it to null and add an explanation to extraction_notes[].
- Do NOT hallucinate or invent scientific values. Only use data present in the source.
- Every step must have a valid "action" from the allowed list.
- Return ONLY the JSON object, no other text.
"""

DRY_LAB_SYSTEM_PROMPT = """\
You are a methodology extraction agent for a computational biology reproducibility pipeline.
Your job is to read raw research data (search results, scraped page content) and extract
a structured reproducibility target that matches the ReproducibilityTarget schema EXACTLY.

You MUST return ONLY valid JSON with these exact fields and types:

{
  "paper_title": string,                // title of the paper
  "paper_source": string,               // DOI or URL of the paper
  "github_url": string or null,         // URL of the code repository, null if not found
  "requirements_file": string or null,  // full contents of requirements.txt or environment.yml
  "data_download_urls": [string],       // URLs for datasets needed to reproduce
  "main_script": string or null,        // entry point filename (e.g. "main.py", "run.sh")
  "expected_outputs": [string],         // figures, tables, or results the paper claims to produce
  "extraction_notes": [string]          // notes about missing or ambiguous fields
}

CRITICAL RULES:
- If a value is ambiguous or not found in the source material, set it to null and add an explanation to extraction_notes[].
- Do NOT hallucinate or invent values. Only use data present in the source.
- For github_url: extract any URLs that point to github.com found in the research data. If the paper mentions a software tool/package name (e.g. "SCANPY", "DeepChem", "Cellpose"), look for github.com/<author>/<package-name> patterns in the research content. If no github link is found in the source, set to null and note it in extraction_notes.
- Return ONLY the JSON object, no other text.
"""


def _gather_research_content(output_files: list[str]) -> tuple[str, str]:
    """Load all research files and return (mode, combined_text).

    Reads every file from the researcher's output_files list, determines the mode
    from the combined summary file, and concatenates all content into a single text
    block for the LLM.
    """
    mode = "wet_lab"
    chunks = []

    for filepath in output_files:
        try:
            data = load_json(filepath)
        except Exception:
            continue

        # The combined file contains the mode
        if "mode" in data:
            mode = data["mode"]

        # Search result files — extract the useful content from each result
        if "results" in data:
            for r in data["results"]:
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                raw = r.get("raw_content") or ""
                # Prefer raw_content if available, fall back to snippet
                text = raw if len(raw) > len(content) else content
                if text:
                    chunks.append(f"--- Source: {title} ({url}) ---\n{text}")

        # Extracted full-page content
        if "raw_content" in data and "source_url" in data:
            chunks.append(
                f"--- Full extraction: {data['source_url']} ---\n{data['raw_content']}"
            )

    combined_text = "\n\n".join(chunks)
    # Truncate to avoid hitting token limits — keep first ~80k chars
    if len(combined_text) > 30000:
        combined_text = combined_text[:30000] + "\n\n[TRUNCATED]"

    return mode, combined_text


def _extract_with_llm(research_text: str, mode: str) -> dict:
    """Call GPT-5.4 mini to extract structured data from raw research text."""
    system_prompt = WET_LAB_SYSTEM_PROMPT if mode == "wet_lab" else DRY_LAB_SYSTEM_PROMPT

    response = _get_openai_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Extract the structured protocol from the following research data:\n\n{research_text}",
            },
        ],
    )
    track_call("methodology", response)
    return json.loads(response.choices[0].message.content)


def _fix_with_llm(research_text: str, mode: str, bad_json: dict, validation_error: str) -> dict:
    """Ask GPT-5.4 mini to fix invalid JSON given the Pydantic validation error."""
    system_prompt = WET_LAB_SYSTEM_PROMPT if mode == "wet_lab" else DRY_LAB_SYSTEM_PROMPT

    response = _get_openai_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Extract the structured protocol from the following research data:\n\n{research_text}",
            },
            {"role": "assistant", "content": json.dumps(bad_json)},
            {
                "role": "user",
                "content": (
                    f"The JSON you returned failed Pydantic validation with this error:\n\n"
                    f"{validation_error}\n\n"
                    f"Fix the JSON so it passes validation. Return ONLY the corrected JSON."
                ),
            },
        ],
    )
    track_call("methodology", response)
    return json.loads(response.choices[0].message.content)


def _validate(data: dict, mode: str):
    """Validate extracted data against the appropriate Pydantic model.

    Returns the validated model instance. Raises ValueError on failure.
    """
    if mode == "wet_lab":
        return OpentronsProtocol(**data)
    else:
        return ReproducibilityTarget(**data)


def _find_missing_github_url(extracted: dict, mode: str) -> str | None:
    """For dry lab mode: if github_url is null, try to find it by searching for package name + github.

    Extracts a package/tool name from paper_title and searches for its GitHub repository.
    Returns the GitHub URL if found, otherwise None.
    """
    if mode != "dry_lab" or extracted.get("github_url"):
        return None

    paper_title = extracted.get("paper_title", "")

    # Try to find a package name (usually the first capitalized word or acronym)
    # Examples: "SCANPY", "DeepChem", "Cellpose"
    words = paper_title.split()
    package_names = [w.strip(".,;:") for w in words if w and (w[0].isupper() or w.isupper())]

    if not package_names:
        return None

    # Try each candidate package name
    for pkg in package_names[:3]:  # Try first 3 candidates
        try:
            results = search_web(f"{pkg} github repository", max_results=3, search_depth="basic")
            for r in results:
                url = r.get("url", "")
                if "github.com" in url:
                    # Make sure it's actually the package repo, not someone's fork
                    if pkg.lower() in url.lower():
                        return url
        except Exception:
            pass  # Silent fail, return None below

    return None


def methodology_agent(researcher_result: dict, task_id: str) -> dict:
    """Run the Methodology Agent pipeline.

    1. Reads all raw research files from researcher_result["output_files"].
    2. Determines mode (wet_lab / dry_lab) from the combined data.
    3. Sends research content to GPT-5.4 mini for structured extraction.
    4. Validates against the target Pydantic schema.
    5. On validation failure, retries once with the error fed back to GPT-5.4 mini.
    6. Saves validated output to workspace/extracted_protocols/protocol_{task_id}.json.

    Returns the Agent Return Contract dict.
    """
    output_files = researcher_result.get("output_files", [])
    if not output_files:
        return {
            "status": "error",
            "output_files": [],
            "message": "No research files provided — nothing to extract from",
            "retry_count": 0,
            "error_detail": "researcher_result['output_files'] was empty",
        }

    # Step 1: Gather all research content
    try:
        mode, research_text = _gather_research_content(output_files)
    except Exception as e:
        return {
            "status": "error",
            "output_files": [],
            "message": "Failed to read research files",
            "retry_count": 0,
            "error_detail": str(e),
        }

    if not research_text.strip():
        return {
            "status": "error",
            "output_files": [],
            "message": "Research files contained no usable content",
            "retry_count": 0,
            "error_detail": "All research files were empty or unreadable",
        }

    # Step 2: First extraction attempt
    try:
        extracted = _extract_with_llm(research_text, mode)
    except Exception as e:
        return {
            "status": "error",
            "output_files": [],
            "message": "LLM extraction call failed",
            "retry_count": 0,
            "error_detail": str(e),
        }

    # Step 3: Validate against Pydantic schema
    try:
        validated = _validate(extracted, mode)
    except Exception as first_error:
        # Step 4: Retry once — feed the validation error back to GPT-5.4 mini
        try:
            fixed = _fix_with_llm(research_text, mode, extracted, str(first_error))
            validated = _validate(fixed, mode)
        except Exception as second_error:
            return {
                "status": "error",
                "output_files": [],
                "message": "Extraction failed Pydantic validation after retry",
                "retry_count": 1,
                "error_detail": (
                    f"First attempt error: {first_error}\n\n"
                    f"Second attempt error: {second_error}"
                ),
            }

    # Step 4b: For dry lab mode, try to find missing GitHub URL
    if mode == "dry_lab" and not validated.github_url:
        try:
            found_url = _find_missing_github_url(extracted, mode)
            if found_url:
                # Update the validated object with the found URL
                data = validated.model_dump()
                data["github_url"] = found_url
                validated = _validate(data, mode)
        except Exception:
            pass  # Silent fail, keep validated as-is with null github_url

    # Step 5: Save validated output
    protocol_path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    try:
        save_json(validated.model_dump(), protocol_path)
    except Exception as e:
        return {
            "status": "error",
            "output_files": [],
            "message": "Failed to save validated protocol",
            "retry_count": 0,
            "error_detail": str(e),
        }

    return {
        "status": "success",
        "output_files": [protocol_path],
        "message": f"Protocol extracted and validated ({mode} mode) — saved to {protocol_path}",
        "retry_count": 0,
        "error_detail": None,
    }
