"""Synthesizer Agent — Reporter: reads workspace artifacts and writes the final Markdown report."""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from openai import OpenAI

from tools.token_tracker import track_call
from tools.file_tool import load_json, load_text, save_text

_client: OpenAI | None = None

STATE_PATH = "workspace/state.json"
COMBINED_RESEARCH_TEMPLATE = "workspace/raw_research/{task_id}_combined.json"
PROTOCOL_TEMPLATE = "workspace/extracted_protocols/protocol_{task_id}.json"
ENRICHMENT_LOG_TEMPLATE = "workspace/extracted_protocols/enrichment_{task_id}.json"
WET_SCRIPT_TEMPLATE = "workspace/generated_code/protocol_{task_id}.py"
DRY_RUN_LOG_TEMPLATE = "workspace/generated_code/dry_lab_{task_id}_run.json"
REPORT_TEMPLATE = "workspace/final_reports/report_{task_id}.md"


def _get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _contract(
    status: str,
    output_files: list[str],
    message: str,
    retry_count: int,
    error_detail: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "output_files": output_files,
        "message": message,
        "retry_count": retry_count,
        "error_detail": error_detail,
    }


def _system_prompt_wet_lab() -> str:
    return """You are the BioSwarm Reporter Agent. You write a single structured Markdown report for WET LAB mode.

You MUST respond with ONLY valid JSON containing exactly one key:
{ "report": "<full Markdown report as a single string; use \\n for newlines inside the string>" }

The Markdown report MUST include these sections IN THIS EXACT ORDER (use clear ## headings):

1. ## Protocol summary — Summarize what the paper / protocol describes (physical methodology, goal, key steps).
2. ## Generated Opentrons script — Include the FULL Python script provided in the user context inside ONE fenced code block with language tag python (```python ... ```).
3. ## Simulation result — State Pass or Fail based on the coding state. Include any warnings or notable messages from simulation output if provided.
4. ## Confidence notes from extraction — If `pie_ran` is true in the protocol JSON (or an enrichment log is provided), lead with a PIE summary: state how many gaps were identified and how many were filled, list each filled field with its confidence score and source URL, list any conflicts that were not applied and why, and list fields still null after enrichment with the stated reasons. Then list any remaining items from extraction_notes. If PIE did not run, list null fields and extraction_notes as before.
5. ## Source citations — List source URLs with short labels; use the URLs from the research bundle (all_sources, search results, extraction_url, etc.).

Base every factual claim on the provided JSON and text. Do not invent URLs or simulation outcomes not supported by the context. If something is unknown from the inputs, say so briefly."""


def _system_prompt_dry_lab() -> str:
    return """You are the BioSwarm Reporter Agent. You write a single structured Markdown report for DRY LAB (computational reproducibility) mode.

You MUST respond with ONLY valid JSON containing exactly one key:
{ "report": "<full Markdown report as a single string; use \\n for newlines inside the string>" }

IMPORTANT: Your analysis must be EVIDENCE-BASED. Cite actual package names, exact error messages, specific file paths, and concrete version numbers from the provided logs and JSON. Do NOT make generic or vague statements — every claim must reference data from the context provided.

Determine the Reproducibility Score using these rules:
- PASS — ALL of the following: (1) dependencies installed without errors, (2) the main script ran to completion with exit_code=0, (3) expected output files were generated or downloaded successfully, (4) no critical warnings or data-loading failures in stdout.
- PARTIAL — At least one of: (1) dependencies installed but some packages had warnings or version conflicts, (2) main script ran but exited non-zero or produced partial output, (3) some but not all expected outputs were generated, (4) random seeds are absent making exact reproduction uncertain but execution succeeded.
- FAIL — Any of: (1) dependency installation failed entirely, (2) main script could not be executed or crashed, (3) repository could not be cloned, (4) critical data files are missing and code attempts to load them, (5) no expected outputs were produced.

The Markdown report MUST include these 9 sections IN THIS EXACT ORDER (use clear ## headings):

1. ## Paper & Repository Summary — Summarize the paper's computational goal, the repository structure, and what was attempted. Include the GitHub URL, main script path, and README highlights if available from the diagnostics. Mention the paper title and source.

2. ## Reproducibility Score — State exactly one of **PASS**, **PARTIAL**, or **FAIL** on its own line, in bold and ALL CAPS. Follow with 2-3 sentences justifying the score with specific evidence (e.g., "pip install exited with code 0 and no failure lines were detected" or "main script exited with code 1; stderr shows ModuleNotFoundError for package X").

3. ## Dependency Analysis — List key packages from requirements.txt (cite actual names). Report pip install exit_code and success status. If there were dep_failures in diagnostics, list each failed line verbatim. Note any version pins, conflicts, or missing packages. If NO_REQUIREMENTS_FILE, state that explicitly.

4. ## Data Availability — Report what data files were found in the repository (from diagnostics.data_files_found). Cross-reference with data-loading code references (diagnostics.data_load_code_refs). Flag any files the code tries to load that are not present in the repo. Note any data_download_urls from the protocol.

5. ## Reproducibility Practices — Analyze reproducibility signals from diagnostics: random seeds (diagnostics.random_seeds_set — present or absent, cite specific lines), GPU/CUDA dependencies (diagnostics.gpu_required — cite specific references). State whether the code sets deterministic seeds and whether results would be reproducible across runs. Note if the README has clear setup/run instructions.

6. ## Execution Results — Report the main script command, exit_code, and success status. Quote relevant portions of stdout (first/last lines showing key results, errors, or warnings). If the script produced output files (from diagnostics.generated_files), list them. Note any generated figures (diagnostics.generated_figures).

7. ## Output Verification — Compare expected_outputs from the protocol against expected_outputs_found and expected_outputs_missing in the run log. For each expected output, state whether it was found and downloaded, or report the download_error. If diagnostics.generated_files differ from expected, note discrepancies.

8. ## Recommendations — Provide 3-5 specific, actionable recommendations for improving reproducibility. Examples: "Pin numpy to version X.Y.Z as seen in the error log", "Add a random seed call before the training loop in script.py", "Include the missing dataset file X.csv or add a download script", "Add a requirements.txt with pinned versions". Each recommendation must reference specific evidence from the analysis above.

9. ## Source Citations — List all source URLs with short descriptive labels. Include GitHub URL, paper URL (paper_source), any data_download_urls, and URLs from the research bundle (all_sources, search results). Use Markdown link format.

Base every factual claim on the provided JSON and logs. Do not invent GitHub URLs, paper details, package names, or error messages not present in the context. If data for a section is missing from the inputs, state explicitly what is unavailable and why the assessment is limited."""


def _read_file_if_exists(path: str) -> tuple[str, str | None]:
    """Returns (description, content_or_none)."""
    if not path or not os.path.isfile(path):
        return path, None
    try:
        if path.endswith(".json"):
            data = load_json(path)
            return path, json.dumps(data, indent=2, ensure_ascii=False)
        return path, load_text(path)
    except OSError as e:
        return path, f"<read error: {e}>"


def _collect_research_bundle(state: dict[str, Any], task_id: str) -> str:
    paths: list[str] = []
    seen: set[str] = set()
    for p in (state.get("research") or {}).get("files") or []:
        if p and p not in seen:
            seen.add(p)
            paths.append(p)
    combined = COMBINED_RESEARCH_TEMPLATE.format(task_id=task_id)
    if combined not in seen:
        paths.append(combined)

    chunks: list[str] = []
    for p in paths:
        label, content = _read_file_if_exists(p)
        if content is None:
            chunks.append(f"--- {label} ---\n<missing or not found>\n")
        else:
            chunks.append(f"--- {label} ---\n{content}\n")
    return "\n".join(chunks)


def _collect_generated_code_artifacts(
    mode: str, task_id: str, state: dict[str, Any]
) -> str:
    coding = state.get("coding") or {}
    chunks: list[str] = []

    if mode == "wet_lab":
        script_path = coding.get("script_file") or WET_SCRIPT_TEMPLATE.format(
            task_id=task_id
        )
        label, content = _read_file_if_exists(script_path)
        chunks.append(f"--- Script file: {label} ---\n")
        if content is None:
            chunks.append("<missing or not found>\n")
        else:
            chunks.append(content)

        chunks.append("\n--- Coding state (from workspace state.json) ---\n")
        chunks.append(
            json.dumps(
                {
                    "simulation_passed": coding.get("simulation_passed"),
                    "error_log": coding.get("error_log"),
                    "retry_count": coding.get("retry_count"),
                },
                indent=2,
            )
        )
        return "\n".join(chunks)

    # dry_lab
    run_path = DRY_RUN_LOG_TEMPLATE.format(task_id=task_id)
    label, content = _read_file_if_exists(run_path)
    chunks.append(f"--- Run log: {label} ---\n")
    if content is None:
        chunks.append("<missing or not found>\n")
    else:
        chunks.append(content)

    pattern = f"workspace/generated_code/*{task_id}*"
    for extra in sorted(glob.glob(pattern)):
        if extra == run_path:
            continue
        if os.path.isfile(extra):
            try:
                if extra.endswith(".json"):
                    chunks.append(f"\n--- {extra} ---\n")
                    chunks.append(
                        json.dumps(load_json(extra), indent=2, ensure_ascii=False)
                    )
                elif extra.endswith((".py", ".txt", ".md", ".csv", ".log")):
                    chunks.append(f"\n--- {extra} ---\n")
                    chunks.append(load_text(extra))
                else:
                    size = os.path.getsize(extra)
                    chunks.append(
                        f"\n--- {extra} (binary or non-text; {size} bytes) ---\n"
                        "<omitted: not inlined as text>\n"
                    )
            except OSError as e:
                chunks.append(f"\n--- {extra} ---\n<read error: {e}>\n")

    chunks.append("\n--- Coding state (from workspace state.json) ---\n")
    chunks.append(
        json.dumps(
            {
                "script_file": coding.get("script_file"),
                "simulation_passed": coding.get("simulation_passed"),
                "error_log": coding.get("error_log"),
                "retry_count": coding.get("retry_count"),
            },
            indent=2,
        )
    )
    return "\n".join(chunks)


def _build_user_payload(
    state: dict[str, Any], task_id: str, mode: str
) -> str:
    mismatch = ""
    st_tid = state.get("task_id")
    if st_tid and st_tid != task_id:
        mismatch = (
            f"\nNote: state.json task_id ({st_tid}) differs from synthesizer "
            f"parameter task_id ({task_id}); artifacts use paths built with the parameter.\n"
        )

    protocol_path = (state.get("extraction") or {}).get(
        "protocol_file"
    ) or PROTOCOL_TEMPLATE.format(task_id=task_id)
    _, protocol_text = _read_file_if_exists(protocol_path)

    research_bundle = _collect_research_bundle(state, task_id)
    generated = _collect_generated_code_artifacts(mode, task_id, state)

    # PIE enrichment log (wet lab only — file may not exist for dry lab or pre-PIE runs)
    enrichment_section = ""
    if mode == "wet_lab":
        enrichment_path = ENRICHMENT_LOG_TEMPLATE.format(task_id=task_id)
        _, enrichment_text = _read_file_if_exists(enrichment_path)
        if enrichment_text:
            enrichment_section = f"\n--- PIE Enrichment Log ({enrichment_path}) ---\n{enrichment_text}\n"

    parts = [
        f"Task ID: {task_id}",
        f"Mode: {mode}",
        f"User input: {state.get('user_input', '')}",
        mismatch,
        "",
        f"Protocol / extraction JSON path: {protocol_path}",
        "--- Protocol JSON ---",
        protocol_text if protocol_text else "<missing or not found>",
        enrichment_section,
        "--- Raw research files (includes combined sources) ---",
        research_bundle,
        "",
        "--- Generated code / run results ---",
        generated,
    ]
    return "\n".join(parts)


def synthesizer_agent(task_id: str) -> dict[str, Any]:
    """Read workspace artifacts for task_id and write workspace/final_reports/report_{task_id}.md."""
    if not task_id or not str(task_id).strip():
        return _contract(
            "error",
            [],
            "task_id is required",
            0,
            "empty task_id",
        )

    try:
        state = load_json(STATE_PATH)
    except FileNotFoundError:
        return _contract(
            "error",
            [],
            f"State file not found: {STATE_PATH}",
            0,
            f"Missing {STATE_PATH}",
        )
    except json.JSONDecodeError as e:
        return _contract(
            "error",
            [],
            "state.json is not valid JSON",
            0,
            str(e),
        )

    mode = state.get("mode")
    if mode not in ("wet_lab", "dry_lab"):
        return _contract(
            "error",
            [],
            f"Invalid or missing mode in state: {mode!r}",
            0,
            "state.mode must be wet_lab or dry_lab",
        )

    protocol_path = (state.get("extraction") or {}).get(
        "protocol_file"
    ) or PROTOCOL_TEMPLATE.format(task_id=task_id)
    if not os.path.isfile(protocol_path):
        return _contract(
            "error",
            [],
            f"Protocol file not found at {protocol_path}",
            0,
            f"Missing protocol: {protocol_path}",
        )

    system = (
        _system_prompt_wet_lab()
        if mode == "wet_lab"
        else _system_prompt_dry_lab()
    )
    user_content = _build_user_payload(state, task_id, mode)

    try:
        response = _get_openai_client().chat.completions.create(
            model="gpt-5.4-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        track_call("synthesizer", response)
        raw = response.choices[0].message.content
        if not raw:
            return _contract(
                "error",
                [],
                "Empty LLM response",
                0,
                "choices[0].message.content was empty",
            )
        data = json.loads(raw)
    except Exception as e:
        return _contract(
            "error",
            [],
            "Failed to generate report via GPT-5.4 mini",
            0,
            str(e),
        )

    report = data.get("report")
    if not isinstance(report, str) or not report.strip():
        return _contract(
            "error",
            [],
            'LLM JSON must contain non-empty string key "report"',
            0,
            str(data)[:2000],
        )

    out_path = REPORT_TEMPLATE.format(task_id=task_id)
    try:
        save_text(report, out_path)
    except OSError as e:
        return _contract(
            "error",
            [],
            f"Failed to save report to {out_path}",
            0,
            str(e),
        )

    return _contract(
        "success",
        [out_path],
        f"Final Markdown report saved to {out_path}",
        0,
        None,
    )
