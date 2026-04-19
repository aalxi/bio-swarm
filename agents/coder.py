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

from tools.token_tracker import track_call
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
- Use Opentrons API v2 with this exact structure (no decorators):
    from opentrons import protocol_api
    metadata = {"apiLevel": "2.13"}
    def run(protocol: protocol_api.ProtocolContext):
        ...
- Do NOT use @requires_version or any other decorator on run().
- Load all labware and pipettes implied by the protocol JSON (labware_setup, pipettes).
- Use ONLY standard Opentrons labware API names. Common valid names:
    opentrons_96_tiprack_300ul, opentrons_96_tiprack_20ul,
    opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap,
    opentrons_96_wellplate_200ul_pcr_full_skirt,
    nest_96_wellplate_200ul_flat, nest_12_reservoir_15ml,
    corning_384_wellplate_112ul_flat, opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical,
    agilent_1_reservoir_290ml, usascientific_96_wellplate_2.4ml_deep
  If the protocol JSON contains a non-standard labware name, substitute the closest
  standard Opentrons labware. Add a comment noting the substitution.
- Use ONLY standard pipette names: p20_single_gen2, p300_single_gen2, p1000_single_gen2,
  p20_multi_gen2, p300_multi_gen2.
- Implement every sequential step: transfers, distribute, consolidate, mix, etc.
- For incubate, centrifuge, or other steps that cannot be fully expressed in simulation,
  add protocol.comment() and protocol.delay() calls where appropriate.
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
- Use the standard API v2 structure: metadata = {"apiLevel": "2.13"}, def run(protocol): ...
- Do NOT use decorators on run(). Do NOT use @requires_version.
- If the error is "Unable to find a labware definition", replace the invalid labware name
  with a standard Opentrons labware. Common valid names:
    opentrons_96_tiprack_300ul, opentrons_96_tiprack_20ul,
    opentrons_96_wellplate_200ul_pcr_full_skirt, nest_96_wellplate_200ul_flat,
    corning_384_wellplate_112ul_flat, nest_12_reservoir_15ml,
    opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap
- If the error is an AttributeError on protocol_api, fix the import/API usage.
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
    track_call("coder", response)
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty LLM response")
    return json.loads(raw)


def _extract_script(data: dict[str, Any]) -> str:
    script = data.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError('LLM JSON must contain non-empty string "script"')
    return script


# Opentrons pipette/protocol method calls that constitute actual liquid handling.
# A generated script with ZERO of these is a silent no-op — simulation passes trivially.
_LIQUID_HANDLING_RE = re.compile(
    r"\.(transfer|distribute|consolidate|aspirate|dispense|mix|blow_out|pick_up_tip|drop_tip)\s*\("
)


def _count_liquid_handling_calls(script: str) -> int:
    return len(_LIQUID_HANDLING_RE.findall(script))


def _count_skipped_markers(script: str) -> int:
    return len(re.findall(r"#\s*SKIPPED\s*:", script))


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
                lh_calls = _count_liquid_handling_calls(script)
                skipped = _count_skipped_markers(script)
                if lh_calls == 0:
                    save_text(script, out_path)
                    _log(
                        f"FAILED: simulation passed but script has no liquid-handling calls "
                        f"(SKIPPED markers={skipped}). Treating as silent no-op."
                    )
                    return _contract(
                        "error",
                        [out_path],
                        "Generated protocol has no liquid-handling steps — "
                        "all steps were skipped due to missing volumes/targets",
                        internal_retries,
                        f"liquid_handling_calls=0, skipped_markers={skipped}. "
                        f"Simulation stdout:\n{last_sim_out[:1500]}",
                    )
                save_text(script, out_path)
                msg = (
                    f"Opentrons protocol simulated successfully after "
                    f"{internal_retries} fix attempt(s). Saved to {out_path} "
                    f"({lh_calls} liquid-handling calls, {skipped} SKIPPED)"
                    if internal_retries
                    else f"Opentrons protocol simulated successfully. Saved to {out_path} "
                    f"({lh_calls} liquid-handling calls, {skipped} SKIPPED)"
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

    main_script: str | None = target.main_script

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

        # ── Verify extracted main_script exists; fall back to discovery ──
        # Methodology agent occasionally hallucinates entry-point filenames
        # (e.g. "oneliner.repurpose"). Always verify before trusting.
        if main_script:
            main_check = daytona_tool.run_cmd(
                sandbox,
                f"test -f \"/home/daytona/repo/{main_script.strip().lstrip('/')}\" && echo YES || echo NO",
                timeout=5,
            )
            if "YES" not in (main_check["stdout"] or ""):
                _log(
                    f"main_script '{main_script}' does not exist in repo — "
                    "falling back to discovery"
                )
                main_script = None

        # ── Discover main_script if not provided ──────────────────────────
        if not main_script:
            _log("main_script not provided — scanning repo for entry point...")
            # Search up to depth 4 — tutorial notebooks often live under
            # docs/tutorials/ or examples/ in library-style repos.
            py_find = daytona_tool.run_cmd(
                sandbox,
                "find /home/daytona/repo -maxdepth 4 -type f "
                "\\( -name 'main.py' -o -name 'run.py' -o -name 'train.py' "
                "-o -name 'app.py' -o -name 'run_experiments.py' -o -name 'demo.py' "
                "-o -name 'example.py' -o -name 'reproduce.py' \\) "
                "! -path '*/.git/*' ! -path '*/tests/*' ! -path '*/test/*' "
                "2>/dev/null | head -10",
                timeout=15,
            )
            py_candidates = [
                f.strip() for f in (py_find["stdout"] or "").splitlines() if f.strip()
            ]
            _log(f"Python script candidates: {py_candidates}")

            nb_find = daytona_tool.run_cmd(
                sandbox,
                "find /home/daytona/repo -maxdepth 4 -type f -name '*.ipynb' "
                "! -path '*/.ipynb_checkpoints/*' ! -path '*/.git/*' "
                "! -path '*/node_modules/*' "
                "2>/dev/null | head -30",
                timeout=15,
            )
            nb_candidates = [
                f.strip() for f in (nb_find["stdout"] or "").splitlines() if f.strip()
            ]
            # Prioritize notebooks under tutorial/example/demo/notebook directories
            _preferred_dirs = ("tutorial", "example", "demo", "notebook", "quickstart", "getting_started")
            nb_candidates.sort(
                key=lambda p: (
                    0 if any(d in p.lower() for d in _preferred_dirs) else 1,
                    p.count("/"),
                )
            )
            _log(f"Notebook candidates: {nb_candidates}")

            readme_run_cmd = daytona_tool.run_cmd(
                sandbox,
                "grep -i -E '(python |python3 |jupyter |nbconvert|^\\s*run)' "
                "/home/daytona/repo/README.md 2>/dev/null | head -5",
                timeout=10,
            )
            readme_hints = (readme_run_cmd["stdout"] or "").strip()
            if readme_hints:
                _log(f"README run hints: {readme_hints[:300]}")

            # Prefer .py scripts by priority
            py_priority = ["main.py", "run.py", "train.py", "app.py", "run_experiments.py"]
            chosen = None
            for name in py_priority:
                for c in py_candidates:
                    if c.endswith(f"/{name}"):
                        chosen = c
                        break
                if chosen:
                    break
            if not chosen and py_candidates:
                chosen = py_candidates[0]

            # Fall back to notebooks if no .py found
            if not chosen and nb_candidates:
                nb_preferred = ["run", "main", "demo", "reproduce", "example", "usage", "tutorial", "getting_started"]
                for keyword in nb_preferred:
                    for c in nb_candidates:
                        if keyword in os.path.basename(c).lower():
                            chosen = c
                            break
                    if chosen:
                        break
                if not chosen:
                    chosen = nb_candidates[0]

            if chosen:
                main_script = chosen.replace("/home/daytona/repo/", "").lstrip("/")
                _log(f"Discovered entry point: {main_script}")
            else:
                _log("FAILED: no entry point found in cloned repo")
                return _contract(
                    "error",
                    [],
                    "No main_script provided and none discovered in repo",
                    0,
                    f"Searched for .py scripts and .ipynb notebooks in cloned repo. "
                    f"README hints: {readme_hints[:200]}",
                )

        main_rel = main_script.strip().lstrip("/")
        remote_main = f"/home/daytona/repo/{main_rel}"
        is_notebook = main_rel.endswith(".ipynb")

        # ── uv + Python 3.11 venv setup ──────────────────────────────────
        _log("Installing Python 3.11 via uv (timeout=120s)...")
        uv_py = daytona_tool.run_cmd(sandbox, f"{UV} python install 3.11", timeout=120)
        _log(f"uv python install exit_code={uv_py['exit_code']} success={uv_py['success']}")
        _log(f"uv python install stdout:\n{(uv_py['stdout'] or '')[-500:]}")

        _log("Creating Python 3.11 venv...")
        uv_venv = daytona_tool.run_cmd(sandbox, f"{UV} venv --python 3.11 {VENV}", timeout=60)
        _log(f"uv venv exit_code={uv_venv['exit_code']} success={uv_venv['success']}")

        # ── Upload inline requirements only if repo has none ─────────────
        # The LLM-reconstructed requirements_file is often malformed
        # (indented lines, partial quotes, fragments). Trust the repo's
        # own requirements.txt whenever it exists.
        if target.requirements_file and target.requirements_file.strip():
            existing = daytona_tool.run_cmd(
                sandbox,
                "test -f /home/daytona/repo/requirements.txt && echo YES || echo NO",
                timeout=5,
            )
            if (existing["stdout"] or "").strip() == "NO":
                _log("Uploading inline requirements.txt (repo has none)...")
                daytona_tool.upload_file(
                    sandbox,
                    target.requirements_file,
                    "/home/daytona/repo/requirements.txt",
                )
            else:
                _log("Repo already has requirements.txt — ignoring LLM-extracted requirements_file")

        # ── CPU-only torch handling ──────────────────────────────────────
        # torch 2.x + its transitive nvidia-* deps total ~2GB, blowing the
        # Daytona sandbox disk. Strategy: strip torch and nvidia-* lines
        # from requirements.txt, install torch from the CPU-only index,
        # then install the remaining requirements. The CPU torch build
        # satisfies downstream imports without pulling CUDA libs.
        torch_probe = daytona_tool.run_cmd(
            sandbox,
            "grep -l -i -E '^\\s*torch([=<>!~ ]|$)' "
            "/home/daytona/repo/requirements.txt "
            "/home/daytona/repo/pyproject.toml "
            "/home/daytona/repo/setup.py 2>/dev/null | head -1",
            timeout=10,
        )
        if (torch_probe["stdout"] or "").strip():
            _log("torch detected in requirements — stripping torch/nvidia-* lines...")
            daytona_tool.run_cmd(
                sandbox,
                "sed -i -E '/^[[:space:]]*(torch([=<>!~[:space:]]|$)|"
                "torchvision|torchaudio|nvidia[-_])/d' "
                "/home/daytona/repo/requirements.txt 2>/dev/null || true",
                timeout=10,
            )
            _log("Pre-installing CPU-only torch (timeout=600s)...")
            cpu_torch = daytona_tool.run_cmd(
                sandbox,
                f"{UV} pip install --python {VENV} "
                f"--index-url https://download.pytorch.org/whl/cpu torch",
                timeout=600,
            )
            _log(f"cpu torch install exit_code={cpu_torch['exit_code']} success={cpu_torch['success']}")
            _log(f"cpu torch stdout tail:\n{(cpu_torch['stdout'] or '')[-1200:]}")
            if not cpu_torch["success"]:
                _log("WARNING: CPU torch preinstall failed — main install may still try CUDA build")

        # ── Install dependencies via venv pip ─────────────────────────────
        _log("Installing requirements via venv pip (timeout=600s)...")
        req_check = daytona_tool.run_cmd(
            sandbox,
            (
                f"bash -c '"
                f"if [ -f /home/daytona/repo/requirements.txt ]; then "
                f"  {UV} pip install --python {VENV} -r /home/daytona/repo/requirements.txt; "
                f"elif [ -f /home/daytona/repo/pyproject.toml ] || [ -f /home/daytona/repo/setup.py ]; then "
                f"  {UV} pip install --python {VENV} /home/daytona/repo; "
                f"else "
                f"  echo NO_REQUIREMENTS_FILE; "
                f"fi'"
            ),
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

        # ── Install notebook tooling + extra deps if needed ─────────────
        if is_notebook:
            _log("Notebook detected — installing nbconvert + ipykernel...")
            nb_pip = daytona_tool.run_cmd(
                sandbox,
                f"{UV} pip install --python {VENV} nbconvert ipykernel",
                timeout=180,
            )
            _log(f"nbconvert install exit_code={nb_pip['exit_code']} success={nb_pip['success']}")
            if not nb_pip["success"]:
                return _contract(
                    "error",
                    [],
                    "pip install nbconvert/ipykernel failed in sandbox",
                    0,
                    nb_pip["stdout"] or f"exit_code={nb_pip['exit_code']}",
                )

            # Scan notebook imports and install any missing packages
            _log("Scanning notebook for import dependencies...")
            scan_cmd = daytona_tool.run_cmd(
                sandbox,
                f"{VENV}/bin/python -c \""
                "import json, re; "
                f"nb = json.load(open('{remote_main}')); "
                "imports = set(); "
                "[imports.update(re.findall(r'^(?:import|from)\\s+(\\w+)', "
                "'\\n'.join(c.get('source',['']) if isinstance(c.get('source'),list) else [c.get('source','')]), re.MULTILINE)) "
                "for c in nb.get('cells',[]) if c.get('cell_type')=='code']; "
                "print('\\n'.join(sorted(imports)))"
                "\"",
                timeout=15,
            )
            raw_imports = [
                m.strip() for m in (scan_cmd["stdout"] or "").splitlines() if m.strip()
            ]
            _log(f"Notebook imports detected: {raw_imports}")
            # Map common import names to pip package names
            _IMPORT_TO_PKG = {
                "sklearn": "scikit-learn",
                "cv2": "opencv-python",
                "PIL": "Pillow",
                "skimage": "scikit-image",
                "yaml": "pyyaml",
                "bs4": "beautifulsoup4",
                "Bio": "biopython",
                "umap": "umap-learn",
                "lxml": "lxml",
                "wx": "wxPython",
                "gi": "PyGObject",
                "attr": "attrs",
            }
            # Skip stdlib, Jupyter internals, and subpackages of other packages
            _SKIP = {
                "os", "sys", "re", "json", "math", "time", "datetime", "collections",
                "itertools", "functools", "pathlib", "io", "copy", "csv", "typing",
                "warnings", "abc", "logging", "subprocess", "random", "string",
                "struct", "operator", "contextlib", "hashlib", "base64", "textwrap",
                "shutil", "glob", "tempfile", "unittest", "argparse", "ast",
                "pprint", "zipfile", "tarfile", "gzip", "pickle", "sqlite3",
                "threading", "multiprocessing", "concurrent", "signal", "socket",
                "http", "urllib", "ftplib", "email", "html", "xml",
                "IPython", "ipykernel", "nbconvert", "nbformat",
                # Subpackages bundled with their parent (not standalone PyPI packages)
                "mpl_toolkits", "pkg_resources", "distutils", "setuptools",
                "encodings", "importlib", "ctypes", "builtins",
            }
            # Filter to imports not in stdlib/skip
            candidate_imports = [m for m in raw_imports if m not in _SKIP]

            # Check which are already importable in the venv
            if candidate_imports:
                import_checks = " and ".join(
                    f"__import__('{m}')" for m in candidate_imports
                )
                # Write a small Python script to the sandbox for reliable multi-line execution
                check_code = "import importlib, sys\\n"
                for m in candidate_imports:
                    check_code += (
                        f"try:\\n"
                        f"    importlib.import_module('{m}')\\n"
                        f"    print('OK:{m}')\\n"
                        f"except ImportError:\\n"
                        f"    print('MISS:{m}')\\n"
                    )
                daytona_tool.upload_file(
                    sandbox, check_code.replace("\\n", "\n"), "/tmp/_check_imports.py"
                )
                chk = daytona_tool.run_cmd(
                    sandbox,
                    f"{VENV}/bin/python /tmp/_check_imports.py",
                    timeout=15,
                )
                missing_imports = [
                    line.split(":", 1)[1]
                    for line in (chk["stdout"] or "").splitlines()
                    if line.startswith("MISS:")
                ]
                already = [
                    line.split(":", 1)[1]
                    for line in (chk["stdout"] or "").splitlines()
                    if line.startswith("OK:")
                ]
                _log(f"Already importable: {already}")
                _log(f"Missing imports: {missing_imports}")
            else:
                missing_imports = []

            pkgs_to_install = sorted(set(
                _IMPORT_TO_PKG.get(m, m) for m in missing_imports
            ))

            if pkgs_to_install:
                pkg_str = " ".join(pkgs_to_install)
                _log(f"Installing notebook extra deps: {pkg_str}")
                extras_pip = daytona_tool.run_cmd(
                    sandbox,
                    f"{UV} pip install --python {VENV} {pkg_str}",
                    timeout=300,
                )
                _log(f"extras install exit_code={extras_pip['exit_code']} success={extras_pip['success']}")
                if not extras_pip["success"]:
                    _log(f"Some extras failed (non-fatal): {(extras_pip['stdout'] or '')[-500:]}")
            else:
                _log("No extra notebook dependencies needed")

        # ── Execute entry point ───────────────────────────────────────────
        if is_notebook:
            _log(f"Running notebook: {remote_main} via nbconvert (timeout=600s)...")
            run_cmd_str = (
                f"bash -c '{VENV}/bin/jupyter nbconvert --to notebook --execute "
                f"--ExecutePreprocessor.timeout=600 \"{remote_main}\" 2>&1'"
            )
        else:
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
            "entry_point": main_rel,
            "is_notebook": is_notebook,
            "discovered": target.main_script is None,
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
