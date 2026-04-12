"""Coder Agent — Daytona: structured protocol → executable code and sandbox runs.

Wet lab: Opentrons Python generation, simulation with self-correction.
Dry lab: clone repo, install deps, run main script, collect artifacts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

from openai import OpenAI

from schemas.dry_lab_schema import ReproducibilityTarget
from schemas.opentrons_schema import OpentronsProtocol
from tools import daytona_tool
from tools.file_tool import load_json, save_json, save_text

logger = logging.getLogger(__name__)

_client: OpenAI | None = None
_stage_start: float = 0.0


def _log(msg: str) -> None:
    elapsed = time.monotonic() - _stage_start
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[coder {ts} +{elapsed:.1f}s] {msg}", flush=True)

# Up to 4 simulation attempts: initial + 3 retries
WET_LAB_MAX_SIM_ATTEMPTS = 4

# Shared sandbox constants — used by both wet and dry lab flows
UV = "/usr/local/py-utils/bin/uv"
VENV = "/home/daytona/venv311"

WET_LAB_CODEGEN_SYSTEM_PROMPT = """\
You are an Opentrons OT-2 protocol author. You receive a JSON protocol definition
and must output a complete, runnable Opentrons Python protocol using API v2.

You MUST respond with ONLY valid JSON containing exactly one key:
{
  "script": "<full Python source as a single string, with \\n for newlines>"
}

Code requirements:
- Use Opentrons API v2. Include metadata: metadata = {"apiLevel": "2.13"} and
  run(protocol_context) with @protocol_api.protocol_api.api_protocol_decorators.requires_version(2, 13)
  or the standard load API pattern with api_level="2.13" as appropriate for API v2.13.
- Import from opentrons import protocol_api, types as needed.
- Load all labware and pipettes implied by the protocol JSON (labware_setup, pipettes).
- Implement every sequential step: transfers, distribute, consolidate, mix, etc.
- For incubate, centrifuge, or other steps that cannot be fully expressed in simulation,
  still structure the deck and add comments.
- Whenever a field in the source JSON is null or missing for a step, do not guess values.
  Instead add a comment line exactly in this form for that step or field:
  # SKIPPED: <short note explaining what was null or ambiguous>
- Include proper labware loading, pipette setup, and all transfer steps that have enough data.
- The script must be self-contained and pass opentrons_simulate when dependencies are installed.
"""

WET_LAB_FIX_SYSTEM_PROMPT = """\
You are fixing an Opentrons OT-2 Python protocol that failed opentrons_simulate.

Return ONLY valid JSON with exactly one key:
{ "script": "<complete fixed Python source as a single string>" }

Requirements:
- Preserve apiLevel 2.13 and API v2 usage.
- Keep # SKIPPED: comments for any still-null protocol fields.
- Address the simulation error shown; return the full corrected script, not a diff.
"""


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


def _llm_json(system: str, user: str) -> dict[str, Any]:
    response = _get_openai_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty LLM response")
    return json.loads(raw)


def _extract_script(data: dict[str, Any]) -> str:
    script = data.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError('LLM JSON must contain non-empty string "script"')
    return script


def _generate_opentrons_script(protocol: dict[str, Any]) -> str:
    user = json.dumps(protocol, indent=2)
    data = _llm_json(WET_LAB_CODEGEN_SYSTEM_PROMPT, user)
    return _extract_script(data)


def _fix_opentrons_script(original_script: str, sim_stdout: str) -> str:
    user = (
        "Simulation failed. Below is the error output from opentrons_simulate, "
        "then the full original script. Fix the script.\n\n"
        f"--- STDERR/STDOUT ---\n{sim_stdout}\n\n"
        f"--- ORIGINAL SCRIPT ---\n{original_script}"
    )
    data = _llm_json(WET_LAB_FIX_SYSTEM_PROMPT, user)
    return _extract_script(data)


def _wet_lab_flow(task_id: str) -> dict[str, Any]:
    protocol_path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    try:
        raw_protocol = load_json(protocol_path)
    except FileNotFoundError:
        return _contract(
            "error",
            [],
            f"Protocol file not found: {protocol_path}",
            0,
            f"Missing file: {protocol_path}",
        )
    except json.JSONDecodeError as e:
        return _contract(
            "error",
            [],
            "Protocol JSON is invalid",
            0,
            str(e),
        )

    try:
        OpentronsProtocol.model_validate(raw_protocol)
    except Exception as e:
        return _contract(
            "error",
            [],
            "Protocol JSON failed schema validation",
            0,
            str(e),
        )

    try:
        script = _generate_opentrons_script(raw_protocol)
    except Exception as e:
        return _contract(
            "error",
            [],
            "Failed to generate Opentrons script via LLM",
            0,
            str(e),
        )

    out_path = f"workspace/generated_code/protocol_{task_id}.py"
    internal_retries = 0
    last_sim_out = ""

    global _stage_start
    _stage_start = time.monotonic()

    _log("Creating Daytona sandbox...")
    daytona, sandbox = daytona_tool.create_sandbox(language="python")
    _log(f"Sandbox created: {getattr(sandbox, 'id', sandbox)}")
    try:
        _log("Installing Python 3.11 via uv (timeout=120s)...")
        uv_py = daytona_tool.run_cmd(sandbox, f"{UV} python install 3.11", timeout=120)
        _log(f"uv python install exit_code={uv_py['exit_code']} success={uv_py['success']}")
        _log(f"uv python install stdout:\n{(uv_py['stdout'] or '')[-500:]}")

        _log("Creating Python 3.11 venv...")
        uv_venv = daytona_tool.run_cmd(sandbox, f"{UV} venv --python 3.11 {VENV}", timeout=60)
        _log(f"uv venv exit_code={uv_venv['exit_code']} success={uv_venv['success']}")

        _log("Running: uv pip install opentrons into venv (timeout=180s)...")
        pip = daytona_tool.run_cmd(
            sandbox, f"{UV} pip install --python {VENV} opentrons", timeout=180
        )
        _log(f"pip install exit_code={pip['exit_code']} success={pip['success']}")
        _log(f"pip stdout tail:\n{(pip['stdout'] or '')[-1000:]}")
        if not pip["success"]:
            return _contract(
                "error",
                [],
                "pip install opentrons failed in sandbox",
                internal_retries,
                pip["stdout"] or f"exit_code={pip['exit_code']}",
            )

        for attempt in range(WET_LAB_MAX_SIM_ATTEMPTS):
            _log(f"Uploading protocol.py to sandbox (attempt {attempt + 1}/{WET_LAB_MAX_SIM_ATTEMPTS})...")
            daytona_tool.upload_file(sandbox, script, "/home/daytona/protocol.py")
            _log(f"Running: {VENV}/bin/opentrons_simulate (timeout=120s)...")
            sim = daytona_tool.run_cmd(
                sandbox,
                f"{VENV}/bin/opentrons_simulate /home/daytona/protocol.py",
                timeout=120,
            )
            last_sim_out = sim["stdout"] or ""
            _log(f"opentrons_simulate exit_code={sim['exit_code']} success={sim['success']}")
            _log(f"simulate stdout:\n{last_sim_out[:2000]}")

            if sim["success"]:
                save_text(script, out_path)
                msg = (
                    f"Opentrons protocol simulated successfully after "
                    f"{internal_retries} fix attempt(s). Saved to {out_path}"
                    if internal_retries
                    else f"Opentrons protocol simulated successfully. Saved to {out_path}"
                )
                _log(f"SUCCESS: {msg}")
                return _contract(
                    "success",
                    [out_path],
                    msg,
                    internal_retries,
                    None,
                )

            if attempt >= WET_LAB_MAX_SIM_ATTEMPTS - 1:
                _log(f"FAILED: max retries reached. Last error:\n{last_sim_out[:2000]}")
                return _contract(
                    "error",
                    [],
                    "opentrons_simulate failed after maximum retries",
                    internal_retries,
                    last_sim_out,
                )

            internal_retries += 1
            logger.info(
                "Wet lab simulation retry %s/%s: exit=%s head_error=%s",
                internal_retries,
                WET_LAB_MAX_SIM_ATTEMPTS - 1,
                sim["exit_code"],
                last_sim_out[:500],
            )
            _log(f"Requesting LLM fix (retry {internal_retries}/{WET_LAB_MAX_SIM_ATTEMPTS - 1})...")
            try:
                script = _fix_opentrons_script(script, last_sim_out)
                logger.info(
                    "Wet lab fix attempt %s: requested revised full script from LLM",
                    internal_retries,
                )
                _log("LLM fix received, re-uploading...")
            except Exception as e:
                _log(f"LLM fix failed: {e}")
                return _contract(
                    "error",
                    [],
                    f"LLM fix failed on retry {internal_retries}",
                    internal_retries,
                    str(e),
                )

        return _contract(
            "error",
            [],
            "Unexpected exit from simulation loop",
            internal_retries,
            last_sim_out,
        )
    finally:
        daytona_tool.cleanup(daytona, sandbox)


def _dry_lab_flow(task_id: str) -> dict[str, Any]:
    protocol_path = f"workspace/extracted_protocols/protocol_{task_id}.json"
    try:
        raw = load_json(protocol_path)
    except FileNotFoundError:
        return _contract(
            "error",
            [],
            f"Protocol file not found: {protocol_path}",
            0,
            f"Missing file: {protocol_path}",
        )

    try:
        target = ReproducibilityTarget.model_validate(raw)
    except Exception as e:
        return _contract(
            "error",
            [],
            "ReproducibilityTarget validation failed",
            0,
            str(e),
        )

    if not target.github_url:
        return _contract(
            "error",
            [],
            "No github_url in reproducibility target",
            0,
            "github_url is null or missing",
        )

    if not target.main_script:
        return _contract(
            "error",
            [],
            "No main_script in reproducibility target",
            0,
            "main_script is null or missing",
        )

    main_rel = target.main_script.strip().lstrip("/")
    remote_main = f"/home/daytona/repo/{main_rel}"

    global _stage_start
    _stage_start = time.monotonic()

    output_files: list[str] = []
    log_path = f"workspace/generated_code/dry_lab_{task_id}_run.json"

    _log("Creating Daytona sandbox for dry lab...")
    daytona, sandbox = daytona_tool.create_sandbox(language="python")
    _log(f"Sandbox created: {getattr(sandbox, 'id', sandbox)}")
    try:
        # ── Clone repo ────────────────────────────────────────────────────
        _log(f"Cloning {target.github_url} into sandbox...")
        try:
            daytona_tool.clone_repo(sandbox, target.github_url, "/home/daytona/repo")
        except Exception as e:
            return _contract(
                "error",
                [],
                "git clone failed in sandbox",
                0,
                str(e),
            )
        _log("Repo cloned successfully.")

        # ── uv + Python 3.11 venv setup ──────────────────────────────────
        _log("Installing Python 3.11 via uv (timeout=120s)...")
        uv_py = daytona_tool.run_cmd(sandbox, f"{UV} python install 3.11", timeout=120)
        _log(f"uv python install exit_code={uv_py['exit_code']} success={uv_py['success']}")
        _log(f"uv python install stdout:\n{(uv_py['stdout'] or '')[-500:]}")

        _log("Creating Python 3.11 venv...")
        uv_venv = daytona_tool.run_cmd(sandbox, f"{UV} venv --python 3.11 {VENV}", timeout=60)
        _log(f"uv venv exit_code={uv_venv['exit_code']} success={uv_venv['success']}")

        # ── Upload inline requirements if provided ────────────────────────
        if target.requirements_file and target.requirements_file.strip():
            _log("Uploading inline requirements.txt...")
            daytona_tool.upload_file(
                sandbox,
                target.requirements_file,
                "/home/daytona/repo/requirements.txt",
            )

        # ── Install dependencies via venv pip ─────────────────────────────
        _log("Installing requirements via venv pip (timeout=600s)...")
        req_check = daytona_tool.run_cmd(
            sandbox,
            f"bash -c 'if [ -f /home/daytona/repo/requirements.txt ]; then {VENV}/bin/pip install -r /home/daytona/repo/requirements.txt; else echo NO_REQUIREMENTS_FILE; fi'",
            timeout=600,
        )
        _log(f"pip install exit_code={req_check['exit_code']} success={req_check['success']}")
        _log(f"pip stdout tail:\n{(req_check['stdout'] or '')[-1000:]}")

        # Parse dependency failures from pip output
        pip_out = req_check["stdout"] or ""
        dep_failures: list[str] = []
        for line in pip_out.splitlines():
            low = line.lower()
            if any(kw in low for kw in ("error:", "could not", "no matching distribution", "failed building")):
                dep_failures.append(line.strip())
        if dep_failures:
            _log(f"Dependency failures detected: {dep_failures}")

        # Build partial run_log (saved even on early return)
        run_log: dict[str, Any] = {
            "requirements_install": {
                "exit_code": req_check["exit_code"],
                "stdout": req_check["stdout"],
                "success": req_check["success"],
            },
            "diagnostics": {
                "dep_failures": dep_failures,
                "data_files_found": [],
                "data_load_code_refs": "",
                "reproducibility_signals": "",
                "readme_head": "",
                "generated_files": [],
            },
        }

        if not req_check["success"] and "NO_REQUIREMENTS_FILE" not in pip_out:
            output_files.append(log_path)
            save_json(run_log, log_path)
            _log("FAILED: pip install -r requirements.txt failed")
            return _contract(
                "error",
                output_files,
                "pip install -r requirements.txt failed",
                0,
                req_check["stdout"] or f"exit_code={req_check['exit_code']}",
            )

        # ── Diagnostic: data file check ───────────────────────────────────
        _log("Running diagnostic: data file check...")
        data_files_cmd = daytona_tool.run_cmd(
            sandbox,
            "find /home/daytona/repo -maxdepth 3 -type f "
            "\\( -name '*.csv' -o -name '*.tsv' -o -name '*.h5' -o -name '*.hdf5' "
            "-o -name '*.npz' -o -name '*.npy' -o -name '*.parquet' "
            "-o -name '*.pkl' -o -name '*.pickle' -o -name '*.json' "
            "-o -name '*.fasta' -o -name '*.fastq' -o -name '*.bam' -o -name '*.vcf' "
            "\\) 2>/dev/null | head -20",
            timeout=30,
        )
        data_files_found = [f.strip() for f in (data_files_cmd["stdout"] or "").splitlines() if f.strip()]
        _log(f"Data files found in repo: {len(data_files_found)}")

        data_load_cmd = daytona_tool.run_cmd(
            sandbox,
            "grep -rn --include='*.py' -E "
            "'(open\\(|pd\\.read|np\\.load|torch\\.load|pickle\\.load|h5py|load_csv|read_csv|read_table)' "
            "/home/daytona/repo/ 2>/dev/null | head -20",
            timeout=30,
        )
        data_load_refs = (data_load_cmd["stdout"] or "").strip()
        _log(f"Data-loading code references: {len(data_load_refs.splitlines())} lines")

        # ── Diagnostic: reproducibility signals ───────────────────────────
        _log("Running diagnostic: reproducibility signals...")
        seed_cmd = daytona_tool.run_cmd(
            sandbox,
            "grep -rn --include='*.py' -E "
            "'(random\\.seed|np\\.random\\.seed|torch\\.manual_seed|tf\\.random\\.set_seed|PYTHONHASHSEED|seed=)' "
            "/home/daytona/repo/ 2>/dev/null | head -10",
            timeout=30,
        )
        seed_refs = (seed_cmd["stdout"] or "").strip()

        gpu_cmd = daytona_tool.run_cmd(
            sandbox,
            "grep -rn --include='*.py' -E '(cuda|gpu|CUDA|torch\\.device)' "
            "/home/daytona/repo/ 2>/dev/null | head -10",
            timeout=30,
        )
        gpu_refs = (gpu_cmd["stdout"] or "").strip()

        repro_signals = ""
        if seed_refs:
            repro_signals += f"SEED REFERENCES:\n{seed_refs}\n"
        if gpu_refs:
            repro_signals += f"GPU REFERENCES:\n{gpu_refs}\n"
        _log(f"Reproducibility signals: seeds={bool(seed_refs)}, gpu={bool(gpu_refs)}")

        # ── Diagnostic: README check ──────────────────────────────────────
        _log("Running diagnostic: README check...")
        readme_cmd = daytona_tool.run_cmd(
            sandbox,
            "bash -c 'cat /home/daytona/repo/README.md 2>/dev/null "
            "|| cat /home/daytona/repo/README.rst 2>/dev/null "
            "|| cat /home/daytona/repo/README 2>/dev/null "
            "|| echo NO_README_FOUND' | head -100",
            timeout=15,
        )
        readme_head = (readme_cmd["stdout"] or "").strip()
        _log(f"README preview: {len(readme_head)} chars")

        # ── Execute main script via venv python ───────────────────────────
        _log(f"Running main script: {remote_main} (timeout=600s)...")
        run_cmd_str = f"bash -c '{VENV}/bin/python \"{remote_main}\" 2>&1'"
        main_run = daytona_tool.run_cmd(sandbox, run_cmd_str, timeout=600)
        _log(f"Main script exit_code={main_run['exit_code']} success={main_run['success']}")
        _log(f"Main script stdout tail:\n{(main_run['stdout'] or '')[-2000:]}")

        # ── Find generated/new files after execution ──────────────────────
        _log("Scanning for generated/new files...")
        gen_files_cmd = daytona_tool.run_cmd(
            sandbox,
            "find /home/daytona/repo -maxdepth 3 -newer /home/daytona/repo/.git/HEAD -type f "
            "2>/dev/null | head -30",
            timeout=30,
        )
        generated_files = [f.strip() for f in (gen_files_cmd["stdout"] or "").splitlines() if f.strip()]

        gen_figures_cmd = daytona_tool.run_cmd(
            sandbox,
            "find /home/daytona/repo -maxdepth 3 -newer /home/daytona/repo/.git/HEAD -type f "
            "\\( -name '*.png' -o -name '*.pdf' -o -name '*.jpg' -o -name '*.svg' \\) "
            "2>/dev/null | head -20",
            timeout=30,
        )
        generated_figures = [f.strip() for f in (gen_figures_cmd["stdout"] or "").splitlines() if f.strip()]
        _log(f"Generated files: {len(generated_files)} total, {len(generated_figures)} figures")

        # ── Build enriched run_log ────────────────────────────────────────
        run_log["diagnostics"] = {
            "dep_failures": dep_failures,
            "data_files_found": data_files_found,
            "data_load_code_refs": data_load_refs,
            "reproducibility_signals": repro_signals,
            "random_seeds_set": bool(seed_refs),
            "gpu_required": bool(gpu_refs),
            "readme_head": readme_head,
            "generated_files": generated_files,
            "generated_figures": generated_figures,
        }
        run_log["main_script"] = {
            "command": run_cmd_str,
            "exit_code": main_run["exit_code"],
            "stdout": main_run["stdout"],
            "success": main_run["success"],
        }

        output_files.append(log_path)

        # ── Download expected outputs ─────────────────────────────────────
        expected_found: list[str] = []
        expected_missing: list[str] = []
        for rel in target.expected_outputs:
            rel_clean = rel.strip().lstrip("/")
            if not rel_clean:
                continue
            remote_path = f"/home/daytona/repo/{rel_clean}"
            _log(f"Downloading expected output: {remote_path}")
            try:
                data = daytona_tool.download_file(sandbox, remote_path)
                safe_name = re.sub(r"[^\w.\-]+", "_", os.path.basename(rel_clean))
                local_path = f"workspace/generated_code/{task_id}_{safe_name}"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                if isinstance(data, bytes):
                    with open(local_path, "wb") as f:
                        f.write(data)
                else:
                    save_text(str(data), local_path)
                output_files.append(local_path)
                expected_found.append(rel_clean)
                _log(f"Downloaded: {local_path}")
            except Exception as ex:
                _log(f"Download failed for {remote_path}: {ex}")
                expected_missing.append(rel_clean)
                run_log.setdefault("download_errors", []).append(
                    {"path": remote_path, "error": str(ex)}
                )

        run_log["expected_outputs"] = list(target.expected_outputs)
        run_log["expected_outputs_found"] = expected_found
        run_log["expected_outputs_missing"] = expected_missing

        save_json(run_log, log_path)
        _log(f"Run log saved: {log_path}")

        if not main_run["success"]:
            _log("DRY LAB FAILED: main script exited non-zero")
            return _contract(
                "error",
                output_files,
                "Main script exited with non-zero status",
                0,
                main_run["stdout"] or f"exit_code={main_run['exit_code']}",
            )

        _log(f"DRY LAB SUCCESS: {len(output_files)} artifacts saved")
        return _contract(
            "success",
            output_files,
            f"Dry lab run completed; artifacts saved under workspace/generated_code/ ({len(output_files)} files)",
            0,
            None,
        )
    finally:
        daytona_tool.cleanup(daytona, sandbox)


def coder_agent(methodology_result: dict, mode: str, task_id: str) -> dict[str, Any]:
    """Coder Agent entry point — generates/runs code per mode, returns Agent Return Contract dict."""
    if methodology_result.get("status") != "success":
        return _contract(
            "error",
            methodology_result.get("output_files") or [],
            "Methodology step did not succeed — skipping coding",
            0,
            methodology_result.get("error_detail") or "methodology_result.status != success",
        )

    if mode == "wet_lab":
        return _wet_lab_flow(task_id)
    if mode == "dry_lab":
        return _dry_lab_flow(task_id)

    return _contract(
        "error",
        [],
        f"Unknown mode: {mode}",
        0,
        "mode must be wet_lab or dry_lab",
    )
