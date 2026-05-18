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

VERDICT (ALWAYS the very first line of the report — NO heading, just bold text):
- If a FAILURE CONTEXT block is provided in the user payload: `**Verdict:** Fail at {phase}` (use the exact phase name from the FAILURE CONTEXT).
- Else if the coding state shows `simulation_passed=true` AND `fidelity_warning=false`: `**Verdict:** Pass`.
- Else if `simulation_passed=true` AND `fidelity_warning=true`: `**Verdict:** Pass with caveats`.
- Else: `**Verdict:** Fail at coding`.

After the verdict line, the Markdown report MUST include these sections IN THIS EXACT ORDER (use clear ## headings). Section 6 (Retry attempts) is optional — see the rule below.

1. ## Fidelity warnings — A bulleted list of every concern, in this priority order. EMIT THE HEADING EVEN IF EMPTY (write `_No fidelity concerns detected._` as the only body in that case — never omit the section).
   - If `coding.fidelity_warning` is true and `coding.liquid_step_coverage` is below 0.5: write a bullet like "Only {n}/{total} steps emitted liquid-handling calls; skipped step numbers: {list}". Compute n = round(coverage × total) where total is the number of `sequential_steps` from the protocol JSON.
   - If `coding.coverage_method == "heuristic_fallback"`: write a bullet starting with "Coverage estimated from heuristic — LLM did not emit `# STEP N` markers; metric is approximate."
   - For every entry in the PIE `enrichment_log.conflicts` (if present): write one bullet describing the conflict (field, step, candidate values, why it was reverted).
   - For every entry in the PIE `enrichment_log.still_null` (if present): write one bullet ("step{N}.{field}: still null — {reason}"). These are INFORMATION, not verdict-modifiers.
   - If the generated script contains `# SKIPPED:` comments: write one bullet ("{count} step fields were skipped during code generation").
2. ## Protocol summary — Summarize what the paper / protocol describes (physical methodology, goal, key steps).
3. ## Generated Opentrons script — Include the FULL Python script provided in the user context inside ONE fenced code block with language tag python (```python ... ```).
4. ## Simulation result — State Pass or Fail based on the coding state. Include any warnings or notable messages from simulation output if provided.
5. ## Confidence notes from extraction — If `pie_ran` is true in the protocol JSON (or an enrichment log is provided), lead with a PIE summary: state how many gaps were identified and how many were filled, list any conflicts that were not applied and why, and list fields still null after enrichment with the stated reasons. Then list any remaining items from extraction_notes. If PIE did not run, list null fields and extraction_notes as before.

   PROVENANCE SENTINEL — Whenever the protocol JSON's `sequential_steps[].field_confidence` or `field_sources` indicates a PIE-filled field, you MUST emit one bullet per (step, field) tuple in this EXACT, machine-parseable, ASCII-ONLY format on its own line:

       - step{step_number}.{field_name}: {value} [unit={unit_or_none}, conf={confidence:.2f}, src={url}]

   Example: `- step3.volume_ul: 5 [unit=uL, conf=0.92, src=https://protocols.io/abc]`

   Use ASCII unit codes only: `uL` (microliters — never µL or μL), `mL`, `s`, `min`, `C`, `rpm`, `none`. Field-to-unit mapping: volume_ul→uL, duration_seconds→s, temperature_celsius→C, speed_rpm→rpm, source_location/destination_location→none. For string-typed values like locations, render the value as-is and use `unit=none`.

   If `field_sources[field]` starts with the literal `notes_mining`, render `src=extraction_notes` instead of a URL. Do NOT omit the bracketed `[unit=..., conf=..., src=...]` segment for any PIE-filled field — future agents parse this back. Use exactly two decimal places for confidence (e.g. `0.92`, not `0.9` or `0.920`).
6. ## Retry attempts — ONLY emit this section when the user payload includes a "Retry attempts" block (i.e. coding.attempts has ≥2 entries). For each attempt, render the attempt number, a fenced ```python code block with the attempt's script, and a fenced ```text block with the attempt's stderr. End each attempt with the metrics line provided in the payload. If no Retry-attempts block is present, OMIT this section entirely (do not write the heading, do not write a placeholder).
7. ## Source citations — List source URLs with short labels; use the URLs from the research bundle (all_sources, search results, extraction_url, etc.).

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

HARD SCORE FLOORS (apply BEFORE the rubric above; do not soften with hedging):
- If `requirements_install.discovery.completeness_score < 1.0`, the score MUST be at most PARTIAL.
- If `requirements_install.discovery.completeness_score < 0.5`, the score MUST be FAIL.
- If `requirements_install.discovery.strategy == "none"`, the score MUST be FAIL.
- If `fabricated_success_check.fabricated == true`, the score MUST be FAIL (clean exit but no scientific work happened).

The Markdown report MUST include these 9 sections IN THIS EXACT ORDER (use clear ## headings):

1. ## Paper & Repository Summary — Summarize the paper's computational goal, the repository structure, and what was attempted. Include the GitHub URL, main script path, and README highlights if available from the diagnostics. Mention the paper title and source.

2. ## Reproducibility Score — State exactly one of **PASS**, **PARTIAL**, or **FAIL** on its own line, in bold and ALL CAPS. Follow with 2-3 sentences justifying the score with specific evidence (e.g., "pip install exited with code 0 and no failure lines were detected" or "main script exited with code 1; stderr shows ModuleNotFoundError for package X").

3. ## Dependency Analysis — Read `requirements_install.discovery` and render exactly the variant that matches `strategy`:
   - `pip_requirements` (completeness 1.0): "Installed from `requirements.txt`."
   - `pip_requirements+editable`: "Installed from `requirements.txt` plus the repo itself in editable mode (`pip install -e .`)."
   - `env_yml_translated` with completeness 1.0: "Translated `env.yml`/`environment.yml` to pip; all packages installable from PyPI."
   - `env_yml_translated` with completeness < 1.0: "⚠ Translated `env.yml`/`environment.yml` to pip. {N} bioconda/R/system packages could NOT be translated and are MISSING from the environment: {list `untranslatable_packages` verbatim}. The reproducibility score is floored at PARTIAL (or FAIL if completeness < 0.5)."
   - `pip_editable`: "Installed in editable mode from `pyproject.toml`/`setup.py`."
   - `none`: "No environment file found in the repo. Reproducibility cannot be assessed without manual intervention. Score MUST be FAIL."
   Then state `discovered_files`, the install `exit_code`, and `success`. If `dep_failures` is non-empty (env.yml leniency mode), list each verbatim. List failures from `diagnostics.dep_failures` too if distinct.

4. ## Data Availability — Report what data files were found in the repository (from diagnostics.data_files_found). Cross-reference with data-loading code references (diagnostics.data_load_code_refs). Flag any files the code tries to load that are not present in the repo. Note any data_download_urls from the protocol.

5. ## Reproducibility Practices — Analyze reproducibility signals from diagnostics: random seeds (diagnostics.random_seeds_set — present or absent, cite specific lines), GPU/CUDA dependencies (diagnostics.gpu_required — cite specific references). State whether the code sets deterministic seeds and whether results would be reproducible across runs. Note if the README has clear setup/run instructions.

6. ## Execution Results — Report the main script command, exit_code, and success status. Quote relevant portions of stdout (first/last lines showing key results, errors, or warnings). If the script produced output files (from diagnostics.generated_files), list them. Note any generated figures (diagnostics.generated_figures).

7. ## Output Verification — Read `expected_outputs_classified` (a dict with keys file_path, directory_path, paper_deliverable, geo_accession, url, unresolved). Render THREE subsections:
   - **On-disk file artifacts**: for each entry in `file_path`, state whether it appears in `expected_outputs_found` (✓ downloaded) or `expected_outputs_missing` (✗ missing). If a `download_errors` entry exists for that path, quote the error.
   - **On-disk directory artifacts**: for each entry in `directory_path`, read `directory_outputs_populated[entry]` (from the fabricated-success detector). ✓ if the directory gained contents during the run, ✗ otherwise.
   - **Claimed deliverables (not on-disk files)**: list each entry in `paper_deliverable` and `geo_accession` verbatim. State explicitly that these are paper figures/datasets, NOT files in the repo — and that the reproducibility score reflects whether the *code* could produce them, not whether their string names matched a path. Do NOT report download_errors for these.
   If `fabricated_success_check.fabricated == true`, prefix this section with a bold "⚠ Fabricated success detected: {reason}" line.

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
                    "fidelity_warning": coding.get("fidelity_warning"),
                    "liquid_step_coverage": coding.get("liquid_step_coverage"),
                    "skipped_step_numbers": coding.get("skipped_step_numbers"),
                    "coverage_method": coding.get("coverage_method"),
                    "attempts_count": len(coding.get("attempts") or []),
                },
                indent=2,
            )
        )

        # A1 — inline each retry attempt's script + stderr so the failure-path
        # report can show the LLM what was tried. Only emit this section when
        # there are 2+ attempts (a single attempt is just the final script,
        # already shown above).
        attempts = coding.get("attempts") or []
        if len(attempts) >= 2:
            chunks.append("\n--- Retry attempts (each attempt's script + stderr) ---\n")
            for entry in attempts:
                n = entry.get("attempt", "?")
                sp = entry.get("script_path", "")
                ep = entry.get("stderr_path", "")
                _, script_text = _read_file_if_exists(sp)
                _, stderr_text = _read_file_if_exists(ep)
                chunks.append(f"\n=== Attempt {n} script ({sp}) ===\n")
                chunks.append(script_text if script_text is not None else "<missing>")
                chunks.append(f"\n=== Attempt {n} stderr ({ep}) ===\n")
                chunks.append(stderr_text if stderr_text is not None else "<missing>")
                chunks.append(
                    f"\n=== Attempt {n} metrics: "
                    f"exit_code={entry.get('exit_code')} "
                    f"success={entry.get('success')} "
                    f"liquid_handling_calls={entry.get('liquid_handling_calls')} "
                    f"coverage={entry.get('liquid_step_coverage')} "
                    f"method={entry.get('coverage_method')} ===\n"
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

    # A1 — failure context block. When this is set the LLM MUST render a
    # "Fail at {phase}" verdict and lean on partial artifacts.
    synthesis_state = state.get("synthesis") or {}
    failed_at_phase = synthesis_state.get("failed_at_phase")
    failure_block = ""
    if failed_at_phase:
        errors = state.get("errors") or []
        errors_text = "\n".join(f"  - {e}" for e in errors) or "  (none recorded)"
        failure_block = (
            "\n=== FAILURE CONTEXT ===\n"
            f"The pipeline did NOT complete. It failed at phase: {failed_at_phase}\n"
            f"Errors recorded:\n{errors_text}\n"
            "Render a report against partial artifacts. The headline verdict line "
            f"MUST read exactly: **Verdict:** Fail at {failed_at_phase}\n"
            "Do not invent successful outcomes for phases that did not run.\n"
            "=== END FAILURE CONTEXT ===\n"
        )

    parts = [
        failure_block,
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
    failed_at_phase = (state.get("synthesis") or {}).get("failed_at_phase")
    # When the pipeline failed before extraction completed (research/extraction
    # phase failures), there is legitimately no protocol on disk. The fail-aware
    # synth path still wants to render a report against whatever partial artifacts
    # exist — so we only treat a missing protocol as a hard error on the success path.
    if not os.path.isfile(protocol_path) and not failed_at_phase:
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

    # Append Field Lineage Summary section for wet-lab runs with iteration data
    if mode == "wet_lab":
        lineage_section = _render_field_lineage_section(task_id)
        if lineage_section:
            report_md = report + "\n" + lineage_section
            try:
                save_text(report_md, out_path)
            except OSError:
                pass  # already saved above; lineage append is best-effort

    return _contract(
        "success",
        [out_path],
        f"Final Markdown report saved to {out_path}",
        0,
        None,
    )


def _render_field_lineage_section(task_id: str) -> str:
    """Return a markdown 'Field Lineage Summary' section. Reads
    workspace/extracted_protocols/protocol_{task_id}.json and
    workspace/state.json. Safe to call even when no iterations ran."""
    from tools.file_tool import load_json
    try:
        proto = load_json(f"workspace/extracted_protocols/protocol_{task_id}.json")
    except Exception:
        return ""
    try:
        state = load_json("workspace/state.json")
    except Exception:
        state = {}

    iters = state.get("iterations") or {}
    if not iters.get("enabled"):
        return ""

    lines: list[str] = []
    lines.append("## Field Lineage Summary")
    lines.append("")
    outcome = (
        "CONVERGED" if iters.get("converged")
        else "DIAGNOSE_REQUIRED" if iters.get("diagnosis_required")
        else "CAP_REACHED" if iters.get("cap_reached")
        else "PENDING"
    )
    lines.append(
        f"- Iteration outcome: **{outcome}** in "
        f"{iters.get('iterations_completed', 0)} iterations"
    )

    counts = {"paper_span": 0, "enricher_fill": 0,
              "oracle_reading": 0, "replanner_revision": 0}
    field_blocks: list[str] = []
    for step in proto.get("sequential_steps", []):
        for field, head in (step.get("field_lineage") or {}).items():
            path = f"step_{step['step_number']}.{field}"
            cur = head
            chain = []
            while cur is not None:
                chain.append(cur)
                counts[cur.get("source_type", "")] = counts.get(cur.get("source_type", ""), 0) + 1
                cur = cur.get("parent")
            chain.reverse()
            if any(c.get("source_type") in ("oracle_reading", "replanner_revision") for c in chain):
                block = [f"### {path}"]
                for c in chain:
                    iter_tag = (
                        f" (iter {c.get('iteration_index')})"
                        if c.get("iteration_index") is not None else ""
                    )
                    line = f"- **{c.get('source_type')}**{iter_tag}: value=`{c.get('value')}`"
                    detail = c.get(c.get("source_type") or "") or {}
                    if c.get("source_type") == "replanner_revision":
                        line += f" — action=`{detail.get('action')}`, rule=`{detail.get('rule_id')}`"
                        if detail.get("citation_failure"):
                            line += " — **citation_failure**"
                    elif c.get("source_type") == "oracle_reading":
                        line += f" — regime=`{detail.get('regime_label')}`, cq=`{detail.get('cq')}`"
                    cites = c.get("citations") or []
                    if cites:
                        line += "\n  - cites: " + ", ".join(f"`{k}`" for k in cites)
                    block.append(line)
                field_blocks.append("\n".join(block))

    lines.append(
        f"- Source-type counts across all fields: "
        f"paper_span={counts['paper_span']}, "
        f"enricher_fill={counts['enricher_fill']}, "
        f"oracle_reading={counts['oracle_reading']}, "
        f"replanner_revision={counts['replanner_revision']}"
    )
    if field_blocks:
        lines.append("")
        lines.extend(field_blocks)
    return "\n".join(lines) + "\n"
