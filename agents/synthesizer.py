"""Synthesizer Agent — Reporter: reads workspace artifacts and writes the final Markdown report."""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from openai import OpenAI

from tools.file_tool import load_json, load_text, save_text

_client: OpenAI | None = None

STATE_PATH = "workspace/state.json"
COMBINED_RESEARCH_TEMPLATE = "workspace/raw_research/{task_id}_combined.json"
PROTOCOL_TEMPLATE = "workspace/extracted_protocols/protocol_{task_id}.json"
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
4. ## Confidence notes from extraction — List any null or missing fields in the protocol JSON, and every item from extraction_notes. If none, state that clearly.
5. ## Source citations — List source URLs with short labels; use the URLs from the research bundle (all_sources, search results, extraction_url, etc.).

Base every factual claim on the provided JSON and text. Do not invent URLs or simulation outcomes not supported by the context. If something is unknown from the inputs, say so briefly."""


def _system_prompt_dry_lab() -> str:
    return """You are the BioSwarm Reporter Agent. You write a single structured Markdown report for DRY LAB (computational reproducibility) mode.

You MUST respond with ONLY valid JSON containing exactly one key:
{ "report": "<full Markdown report as a single string; use \\n for newlines inside the string>" }

Determine the Reproducibility Score using these rules:
- PASS — Dependencies installed successfully AND the main script ran without errors AND outputs align with the paper's expected/claimed results (or the run log supports success and consistency).
- PARTIAL — Some steps succeeded (e.g. deps installed) but outputs differ from claims, partial errors, or incomplete alignment with expected_outputs.
- FAIL — Code did not run, dependencies failed, major missing components, or the run log shows fundamental failure.

The Markdown report MUST include these sections IN THIS EXACT ORDER (use clear ## headings):

1. ## Paper summary — Summarize the paper's computational goal and what was attempted (from ReproducibilityTarget / protocol JSON and context).
2. ## Reproducibility Score — Exactly one line prominently stating: **PASS**, **PARTIAL**, or **FAIL** (use those words in ALL CAPS), consistent with the rules above.
3. ## Environment setup result — Whether dependencies installed (quote exit/success from requirements_install in the run log when available).
4. ## Execution result — Whether the main script ran without errors (quote exit_code / success from main_script in the run log when available).
5. ## Output comparison — Compare expected_outputs from extraction to what the run produced or downloaded; note download_errors if any.
6. ## Specific failure points — If the score is FAIL (or PARTIAL with notable issues), list concrete failures (missing data, dependency errors, wrong paths, etc.). If PASS, state "None" or briefly "N/A".
7. ## Source citations — List source URLs with short labels from the research bundle (all_sources, queries, etc.).

Base every factual claim on the provided JSON and logs. Do not invent GitHub or paper details not present in the context. If data is missing, say so."""


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

    parts = [
        f"Task ID: {task_id}",
        f"Mode: {mode}",
        f"User input: {state.get('user_input', '')}",
        mismatch,
        "",
        f"Protocol / extraction JSON path: {protocol_path}",
        "--- Protocol JSON ---",
        protocol_text if protocol_text else "<missing or not found>",
        "",
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
            model="gpt-5.4",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
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
            "Failed to generate report via GPT-5.4",
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
