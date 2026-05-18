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

try:
    import yaml as _yaml  # pyyaml — required for env.yml translation (Layer 2 A5)
except ImportError:
    _yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_client: OpenAI | None = None
_stage_start: float = 0.0


def _log(msg: str) -> None:
    elapsed = time.monotonic() - _stage_start
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[coder {ts} +{elapsed:.1f}s] {msg}", flush=True)

# Up to 4 simulation attempts: initial + 3 retries
WET_LAB_MAX_SIM_ATTEMPTS = 4

# Below this fraction of declared steps emitting any liquid-handling call,
# even a clean simulation is flagged as a fidelity warning. See B1 in the
# 2026-05-04 post-mortem: Smart-seq3 silently dropped 8 of 12 steps.
LIQUID_COVERAGE_THRESHOLD = 0.5

# Shared sandbox constants — used by both wet and dry lab flows
UV = "/usr/local/py-utils/bin/uv"
VENV = "/home/daytona/venv311"

# ── Layer 2 A5: env-file translation helpers ─────────────────────────────────
# Packages that are bioconda-only, R, or system-level — no PyPI equivalent.
# Built from inspection of five real bio-ML env.yml files (Riboformer, OpenFold,
# DiffDock, ESM, RoseTTAFold). Routed to `untranslatable_packages` so the
# synthesizer can floor the reproducibility score honestly.
_KNOWN_BIOCONDA_ONLY: set[str] = {
    # Bioinformatics CLI tools
    "samtools", "bedtools", "bwa", "star", "salmon", "kallisto", "seqkit",
    "hmmer", "hhsuite", "kalign2", "kalign", "blast", "blast-legacy", "psipred",
    "bcftools", "mafft", "muscle", "fastqc", "trimmomatic", "bowtie2",
    "minimap2", "subread", "stringtie",
    # System / build tools (when listed as conda deps)
    "cuda", "cudatoolkit", "cudnn", "gcc", "gxx", "g++", "git", "aria2", "awscli",
    "make", "cmake", "ninja", "openmpi", "mpi",
    # PyTorch ecosystem pieces that need specific torch+cuda combos
    "pytorch", "pytorch-cuda", "pytorch-cluster", "pytorch-scatter",
    "pytorch-sparse", "pytorch-spline-conv", "pytorch-geometric",
    # Conda-only scientific packages
    "openmm", "pdbfixer",
    # R ecosystem
    "r-base", "r",
    # System libs (rosettafold-style export dumps)
    "blas", "mkl", "mkl-service", "mkl_fft", "mkl_random", "intel-openmp",
    "openssl", "zlib", "zstd", "lz4-c", "libgcc-ng", "libstdcxx-ng",
    "libffi", "libpng", "libtiff", "libwebp-base", "ncurses", "readline",
    "sqlite", "tk", "xz", "freetype", "libuv", "libiconv", "libtasn1",
    "libunistring", "libidn2", "libgfortran-ng", "libgfortran4", "libgomp",
    "bzip2", "ca-certificates", "ffmpeg", "openh264", "nettle", "gnutls",
    "gmp", "lame", "lcms2", "jpeg", "openh264",
}
_BIOCONDA_PATTERNS = (
    re.compile(r"^_"),                 # _libgcc_mutex, _openmp_mutex
    re.compile(r"^bioconductor-"),
    re.compile(r"^ld_impl_"),
    re.compile(r"^libgfortran"),
)
# Names dropped silently (neither installed nor counted as untranslatable):
#   python, pip → handled by venv setup itself.
#   defaults → a channel name that sometimes leaks into dependencies.
#   torch family → handled by the CPU-only torch preinstall.
_CONDA_DROP: set[str] = {
    "python", "pip", "defaults", "setuptools", "wheel",
    "torch", "torchvision", "torchaudio",
}


def _yml_to_pip_requirements(yml_text: str) -> tuple[list[str], list[str]]:
    """Translate a minimal subset of conda env.yml/environment.yml to pip.

    Returns (translatable, untranslatable):
      - translatable: pip-compatible requirement strings ready for `uv pip install`
      - untranslatable: package names dropped because they're bioconda/R/system-only

    Drops `python`, `pip`, `defaults`, `setuptools`, `wheel`, and the torch family
    silently (the venv setup and CPU-torch preinstall handle them separately).

    Handles patterns observed in five real bio-ML env.yml files:
      - Channel prefixes (`bioconda::samtools`, `pytorch::pytorch=2.5`) → strip
        prefix; route bioconda/biocore-prefixed pkgs to `untranslatable`.
      - Build strings (`numpy=1.20.2=py38h2d18471_0`) → drop the third `=` field.
      - Wildcard pins (`protobuf=3.20.*`) → translated to `protobuf==3.20.*`.
      - Multiple `pip:` subsections (DiffDock) → unioned in order.
      - pip flags (`--extra-index-url`, `--find-links`) → passed through verbatim.
      - git+https URLs → passed through verbatim.

    On parse failure or missing pyyaml, returns ([], []).
    """
    if _yaml is None:
        return [], []
    try:
        data = _yaml.safe_load(yml_text)
    except Exception:
        return [], []
    if not isinstance(data, dict):
        return [], []
    deps = data.get("dependencies") or []
    if not isinstance(deps, list):
        return [], []

    translatable: list[str] = []
    untranslatable: list[str] = []

    for entry in deps:
        # pip subsection — may appear multiple times in the dependencies list
        if isinstance(entry, dict):
            pip_list = entry.get("pip") or []
            if isinstance(pip_list, list):
                for item in pip_list:
                    if not isinstance(item, str):
                        continue
                    s = item.strip()
                    if s and not s.startswith("#"):
                        translatable.append(s)
            continue

        if not isinstance(entry, str):
            continue

        s = entry.strip()
        if not s or s.startswith("#"):
            continue

        # Channel prefix: bioconda::samtools=1.17 → channel="bioconda", s="samtools=1.17"
        channel = ""
        if "::" in s:
            channel, s = s.split("::", 1)
            channel = channel.strip().lower()
            s = s.strip()

        # Strip conda build-string field: pkg=ver=build → pkg=ver.
        # Conda's 3-part syntax uses single `=` separators; pip-style `pkg==ver`
        # has an empty middle field and must NOT be stripped this way.
        if "==" not in s and s.count("=") >= 2:
            parts = s.split("=")
            if len(parts) >= 3 and parts[0] and parts[1]:
                s = f"{parts[0]}={parts[1]}"

        name = re.split(r"[=<>!~ ]", s, 1)[0].strip().lower()
        if not name:
            continue
        if name in _CONDA_DROP:
            continue
        if channel in ("bioconda", "biocore"):
            untranslatable.append(name)
            continue
        if name in _KNOWN_BIOCONDA_ONLY:
            untranslatable.append(name)
            continue
        if any(p.match(name) for p in _BIOCONDA_PATTERNS):
            untranslatable.append(name)
            continue

        # If already a pip-style spec (==, >=, <=, !=, ~=) pass through.
        # Otherwise translate conda single `=` to pip `==`.
        if any(op in s for op in ("==", ">=", "<=", "!=", "~=")):
            req = s
        elif "=" in s:
            req = s.replace("=", "==", 1)
        else:
            req = s
        translatable.append(req)

    return translatable, untranslatable


# ── Layer 2: expected_outputs classifier ─────────────────────────────────────
# Test 4 (Riboformer) tried to download "Fig 2b" as a file path. Classifier
# routes only file-shaped entries to the download loop; paper deliverables
# and GEO accessions are surfaced separately in the report.
_GEO_RE = re.compile(r"^GS[EM]\d{3,}$", re.IGNORECASE)
_FIG_RE = re.compile(
    r"^(Fig(?:ure)?|Table|Supplementary|Suppl|Extended Data|Source Data)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_FILE_RE = re.compile(r"^[\w./\- ]+\.[A-Za-z0-9]{1,8}$")


def _classify_expected_output(entry: str) -> str:
    """Returns one of: file_path, directory_path, paper_deliverable,
                       geo_accession, url, unresolved."""
    s = (entry or "").strip()
    if not s:
        return "unresolved"
    if _URL_RE.match(s):
        return "url"
    if _GEO_RE.match(s):
        return "geo_accession"
    if _FIG_RE.match(s):
        return "paper_deliverable"
    if _FILE_RE.match(s):
        return "file_path"
    if s.startswith(("/", "./", "../")) and "." in s.rsplit("/", 1)[-1]:
        return "file_path"
    if "/" in s and not s.endswith((".", "?")):
        # results/, figures/, checkpoints/output
        return "directory_path"
    return "unresolved"


def _check_dry_lab_fabricated_success(
    run_log: dict,
    files_before: set[str],
    files_after: set[str],
) -> dict:
    """Detect 'clean exit but no scientific work happened' on the dry-lab side.

    Ports the wet-lab silent-no-op discipline (LIQUID_RE). Returns a dict
    with `fabricated: bool`, `reason: str | None`, `new_files: list[str]`,
    and `directory_outputs_populated: dict[str, bool]`.

    Failure criteria (all must hold for fabricated=True):
      - main_script exit_code == 0
      - no new files appeared in the repo working tree
      - no file in classified.file_path is present on disk
      - no directory in classified.directory_path gained contents
    """
    main = run_log.get("main_script") or {}
    classified = run_log.get("expected_outputs_classified") or {}
    file_paths = classified.get("file_path") or []
    dir_paths = classified.get("directory_path") or []
    found_files = run_log.get("expected_outputs_found") or []
    generated_files = (run_log.get("diagnostics") or {}).get("generated_files") or []

    new_files = sorted(files_after - files_before)
    directory_outputs_populated: dict[str, bool] = {}
    for d in dir_paths:
        d_norm = d.strip().lstrip("/").rstrip("/") + "/"
        populated = any(f.lstrip("/").startswith(d_norm) for f in new_files)
        directory_outputs_populated[d] = populated

    exit_code = main.get("exit_code")
    if exit_code != 0:
        return {
            "fabricated": False,
            "reason": None,
            "new_files": new_files,
            "directory_outputs_populated": directory_outputs_populated,
        }
    if new_files or generated_files or found_files:
        return {
            "fabricated": False,
            "reason": None,
            "new_files": new_files,
            "directory_outputs_populated": directory_outputs_populated,
        }
    if any(directory_outputs_populated.values()):
        return {
            "fabricated": False,
            "reason": None,
            "new_files": new_files,
            "directory_outputs_populated": directory_outputs_populated,
        }

    return {
        "fabricated": True,
        "reason": (
            "Exit code 0 but zero new files in the working tree, zero expected "
            "file_path artifacts on disk, and zero expected directory_path "
            "entries gained contents."
        ),
        "new_files": new_files,
        "directory_outputs_populated": directory_outputs_populated,
    }

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
- BEFORE emitting the code for each step from sequential_steps, write a marker comment
  EXACTLY in this form on its own line:
      # STEP {step_number}
  Use the literal step_number from the JSON (an integer). Emit the marker even for
  SKIPPED steps. Do not omit, abbreviate, or rename it. A downstream tool counts
  liquid-handling calls per marker region to score per-step coverage; missing markers
  silently degrade the metric to a less accurate fallback.
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
- PRESERVE every existing `# STEP N` marker comment from the original script.
  These are tooling sentinels — never delete, renumber, or reformat them.
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
    attempts: list[dict] | None = None,
    liquid_step_coverage: float | None = None,
    skipped_step_numbers: list[int] | None = None,
    coverage_method: str | None = None,
    fidelity_warning: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "output_files": output_files,
        "message": message,
        "retry_count": retry_count,
        "error_detail": error_detail,
        "attempts": attempts if attempts is not None else [],
        "liquid_step_coverage": liquid_step_coverage,
        "skipped_step_numbers": skipped_step_numbers if skipped_step_numbers is not None else [],
        "coverage_method": coverage_method,
        "fidelity_warning": fidelity_warning,
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


_STEP_MARKER_RE = re.compile(r"^#\s*STEP\s+(\d+)\b", re.MULTILINE)


def _compute_step_coverage(script: str, total_steps: int) -> tuple[float, list[int], str]:
    """Return (coverage_ratio, skipped_step_numbers, method).

    method == "markers" when the script contained `# STEP N` markers and we could
    bucket liquid-handling calls per step.
    method == "heuristic_fallback" when no markers were present and we fell back to
    distinct-call-count / total_steps. The fallback is intentionally tagged so the
    caller can surface "metric is approximate" in the report — see B6 fidelity warnings.
    """
    if total_steps <= 0:
        return 0.0, [], "markers"

    matches = list(_STEP_MARKER_RE.finditer(script))
    if not matches:
        # Heuristic fallback: distinct liquid-handling calls / total steps.
        distinct_calls = _count_liquid_handling_calls(script)
        ratio = min(distinct_calls / total_steps, 1.0)
        # We don't know which step numbers were skipped under the heuristic.
        return ratio, [], "heuristic_fallback"

    # Bucket each liquid-handling call into the step region that contains it.
    # A region is from one marker to the next (or end-of-string for the last).
    regions: list[tuple[int, int, int]] = []
    for i, m in enumerate(matches):
        step_n = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
        regions.append((step_n, start, end))

    active_steps: set[int] = set()
    for step_n, start, end in regions:
        if _LIQUID_HANDLING_RE.search(script, start, end):
            active_steps.add(step_n)

    declared_steps = {step_n for step_n, _, _ in regions}
    skipped = sorted(declared_steps - active_steps)
    ratio = len(active_steps) / total_steps
    return ratio, skipped, "markers"


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
    attempts_log: list[dict] = []
    total_steps = len(raw_protocol.get("sequential_steps") or [])

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

            attempt_n = attempt + 1
            attempt_script_path = f"workspace/generated_code/protocol_{task_id}_attempt{attempt_n}.py"
            attempt_stderr_path = f"workspace/generated_code/protocol_{task_id}_attempt{attempt_n}.stderr"
            save_text(script, attempt_script_path)
            save_text(last_sim_out, attempt_stderr_path)
            attempt_lh_calls = _count_liquid_handling_calls(script)
            attempt_coverage, attempt_skipped_steps, attempt_method = _compute_step_coverage(
                script, total_steps
            )
            attempts_log.append({
                "attempt": attempt_n,
                "script_path": attempt_script_path,
                "stderr_path": attempt_stderr_path,
                "exit_code": sim["exit_code"],
                "success": bool(sim["success"]),
                "liquid_handling_calls": attempt_lh_calls,
                "liquid_step_coverage": attempt_coverage,
                "coverage_method": attempt_method,
            })

            if sim["success"]:
                lh_calls = _count_liquid_handling_calls(script)
                skipped = _count_skipped_markers(script)
                coverage, skipped_step_numbers, coverage_method = _compute_step_coverage(
                    script, total_steps
                )
                low_coverage = coverage < LIQUID_COVERAGE_THRESHOLD
                heuristic_used = coverage_method == "heuristic_fallback"
                fidelity_warning = low_coverage or heuristic_used
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
                        attempts=attempts_log,
                        liquid_step_coverage=coverage,
                        skipped_step_numbers=skipped_step_numbers,
                        coverage_method=coverage_method,
                        fidelity_warning=True,
                    )
                save_text(script, out_path)
                msg = (
                    f"Opentrons protocol simulated successfully after "
                    f"{internal_retries} fix attempt(s). Saved to {out_path} "
                    f"({lh_calls} liquid-handling calls, {skipped} SKIPPED, "
                    f"coverage={coverage:.2f} via {coverage_method})"
                    if internal_retries
                    else f"Opentrons protocol simulated successfully. Saved to {out_path} "
                    f"({lh_calls} liquid-handling calls, {skipped} SKIPPED, "
                    f"coverage={coverage:.2f} via {coverage_method})"
                )
                _log(f"SUCCESS: {msg}")
                return _contract(
                    "success",
                    [out_path],
                    msg,
                    internal_retries,
                    None,
                    attempts=attempts_log,
                    liquid_step_coverage=coverage,
                    skipped_step_numbers=skipped_step_numbers,
                    coverage_method=coverage_method,
                    fidelity_warning=fidelity_warning,
                )

            if attempt >= WET_LAB_MAX_SIM_ATTEMPTS - 1:
                _log(f"FAILED: max retries reached. Last error:\n{last_sim_out[:2000]}")
                return _contract(
                    "error",
                    [],
                    "opentrons_simulate failed after maximum retries",
                    internal_retries,
                    last_sim_out,
                    attempts=attempts_log,
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
                    attempts=attempts_log,
                )

        return _contract(
            "error",
            [],
            "Unexpected exit from simulation loop",
            internal_retries,
            last_sim_out,
            attempts=attempts_log,
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

        # ── Layer 2 A5: env-file discovery dispatcher ────────────────────
        # Replaces the old bash if/elif chain and the NO_REQUIREMENTS_FILE
        # sentinel. Single `find` to enumerate every plausible env file in the
        # repo; Python-side dispatcher picks the install strategy and records
        # a structured `discovery` block so the synthesizer can floor the
        # reproducibility score honestly.
        discover_cmd = (
            "find /home/daytona/repo -maxdepth 2 -type f \\( "
            "-name 'requirements*.txt' -o -name 'pyproject.toml' "
            "-o -name 'setup.py' -o -name 'setup.cfg' -o -name 'Pipfile' "
            "-o -name 'env*.yml' -o -name 'env*.yaml' "
            "-o -name 'environment*.yml' -o -name 'environment*.yaml' "
            "\\) ! -path '*/.git/*' 2>/dev/null"
        )
        discover_run = daytona_tool.run_cmd(sandbox, discover_cmd, timeout=15)
        discovered_full = [
            line.strip()
            for line in (discover_run["stdout"] or "").splitlines()
            if line.strip()
        ]
        discovered_rel = [
            p.replace("/home/daytona/repo/", "", 1) for p in discovered_full
        ]
        _log(f"Env discovery: found {len(discovered_rel)} file(s): {discovered_rel}")

        req_txt_files = [
            p for p in discovered_full
            if os.path.basename(p).startswith("requirements") and p.endswith(".txt")
        ]
        env_yml_files = [
            p for p in discovered_full
            if (os.path.basename(p).startswith(("env", "environment"))
                and p.endswith((".yml", ".yaml")))
        ]
        installable_files = [
            p for p in discovered_full
            if os.path.basename(p) in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile")
        ]

        # ── CPU-only torch handling ──────────────────────────────────────
        # torch 2.x + nvidia-* total ~2GB, blowing the Daytona sandbox disk.
        # Probe every discovered file (not just three hardcoded names).
        torch_in_repo = False
        if discovered_full:
            grep_cmd = (
                f"grep -l -i -E '(^|[^a-zA-Z_])(torch|pytorch)([=<>!~[:space:]]|$)' "
                f"{' '.join(discovered_full)} 2>/dev/null | head -1"
            )
            torch_probe = daytona_tool.run_cmd(sandbox, grep_cmd, timeout=10)
            torch_in_repo = bool((torch_probe["stdout"] or "").strip())
        if torch_in_repo:
            _log("torch/pytorch referenced in env files — stripping + CPU torch preinstall")
            for rf in req_txt_files:
                daytona_tool.run_cmd(
                    sandbox,
                    f"sed -i -E '/^[[:space:]]*(torch([=<>!~[:space:]]|$)|"
                    f"torchvision|torchaudio|nvidia[-_])/d' {rf} 2>/dev/null || true",
                    timeout=10,
                )
            cpu_torch = daytona_tool.run_cmd(
                sandbox,
                f"{UV} pip install --python {VENV} "
                f"--index-url https://download.pytorch.org/whl/cpu torch",
                timeout=600,
            )
            _log(f"cpu torch install exit_code={cpu_torch['exit_code']} success={cpu_torch['success']}")
            if not cpu_torch["success"]:
                _log("WARNING: CPU torch preinstall failed — proceeding anyway")

        # ── Strategy dispatch ────────────────────────────────────────────
        install_stdout_parts: list[str] = []
        install_exit_codes: list[int] = []
        strategies_used: list[str] = []
        untranslatable_packages: list[str] = []
        dep_failures_yml: list[str] = []
        completeness_score: float = 0.0
        install_success_overall: bool = False

        def _run_install(cmd: str, label: str) -> dict:
            _log(f"{label} (timeout=600s)...")
            r = daytona_tool.run_cmd(sandbox, cmd, timeout=600)
            _log(f"{label}: exit_code={r['exit_code']} success={r['success']}")
            install_stdout_parts.append(f"=== {label} ===\n{r['stdout'] or ''}")
            install_exit_codes.append(int(r["exit_code"] or 0))
            return r

        if req_txt_files:
            all_ok = True
            for rf in req_txt_files:
                r = _run_install(
                    f"{UV} pip install --python {VENV} -r {rf}",
                    f"pip install -r {rf}",
                )
                if not r["success"]:
                    all_ok = False
            has_installable_pkg = any(
                os.path.basename(p) in ("pyproject.toml", "setup.py")
                for p in installable_files
            )
            if has_installable_pkg:
                r = _run_install(
                    f"{UV} pip install --python {VENV} -e /home/daytona/repo",
                    "pip install -e .",
                )
                if not r["success"]:
                    all_ok = False
                strategies_used.append("pip_requirements+editable")
            else:
                strategies_used.append("pip_requirements")
            completeness_score = 1.0
            install_success_overall = all_ok
        elif env_yml_files:
            strategies_used.append("env_yml_translated")
            yml_path = env_yml_files[0]
            yml_dl = daytona_tool.run_cmd(sandbox, f"cat {yml_path}", timeout=10)
            yml_text = yml_dl["stdout"] or ""
            translatable, untranslatable = _yml_to_pip_requirements(yml_text)
            untranslatable_packages = untranslatable
            total = len(translatable) + len(untranslatable)
            completeness_score = (len(translatable) / total) if total > 0 else 0.0
            _log(
                f"env.yml {yml_path}: {len(translatable)} pip-translatable, "
                f"{len(untranslatable)} untranslatable, completeness={completeness_score:.2f}"
            )
            if not translatable:
                install_stdout_parts.append(
                    f"=== {yml_path}: 0 pip-translatable, {len(untranslatable)} untranslatable ==="
                )
                install_success_overall = (len(untranslatable) == 0)
            else:
                # Install in a single command so pip can resolve the dep graph.
                # Individual package failures are tolerated for env.yml because
                # version pins are notoriously stale; we'll still record them.
                pkg_args = " ".join(f"'{p}'" for p in translatable)
                r = _run_install(
                    f"{UV} pip install --python {VENV} {pkg_args}",
                    f"pip install (env.yml-translated, {len(translatable)} pkgs)",
                )
                if not r["success"]:
                    # Fall back: install one-at-a-time so a single bad pin doesn't
                    # block the rest. This is the env.yml leniency rationale.
                    _log("Bulk install failed — retrying one-at-a-time for partial success")
                    for pkg in translatable:
                        rr = _run_install(
                            f"{UV} pip install --python {VENV} '{pkg}'",
                            f"pip install {pkg}",
                        )
                        if not rr["success"]:
                            dep_failures_yml.append(pkg)
                # env.yml: success if at least half installed cleanly.
                if dep_failures_yml:
                    install_success_overall = (
                        len(dep_failures_yml) <= len(translatable) // 2
                    )
                else:
                    install_success_overall = r["success"]
        elif installable_files:
            strategies_used.append("pip_editable")
            r = _run_install(
                f"{UV} pip install --python {VENV} -e /home/daytona/repo",
                "pip install -e .",
            )
            completeness_score = 1.0 if r["success"] else 0.5
            install_success_overall = r["success"]
        else:
            strategies_used.append("none")
            completeness_score = 0.0
            install_stdout_parts.append(
                "No environment file discovered (no requirements.txt, env.yml, "
                "pyproject.toml, setup.py, setup.cfg, or Pipfile)."
            )
            install_success_overall = False

        strategy_label = "+".join(strategies_used) if strategies_used else "none"
        combined_stdout = "\n\n".join(install_stdout_parts)
        combined_exit_code = (
            max(install_exit_codes) if install_exit_codes
            else (0 if strategy_label != "none" else 1)
        )

        # Parse dep_failures lines from combined stdout (same heuristic as before)
        dep_failures: list[str] = []
        for line in combined_stdout.splitlines():
            low = line.lower()
            if any(kw in low for kw in (
                "error:", "could not", "no matching distribution", "failed building",
            )):
                dep_failures.append(line.strip())

        # Build partial run_log (saved even on early return)
        run_log: dict[str, Any] = {
            "requirements_install": {
                "discovery": {
                    "discovered_files": discovered_rel,
                    "strategy": strategy_label,
                    "completeness_score": round(completeness_score, 3),
                    "untranslatable_packages": untranslatable_packages,
                },
                "exit_code": combined_exit_code,
                "stdout": combined_stdout,
                "success": install_success_overall,
                "dep_failures": dep_failures_yml,
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

        # Hard-fail only when a pip_requirements install actually failed.
        # For env_yml_translated and pip_editable we proceed to entry-point
        # execution so the synthesizer can report what happened. For none, we
        # still proceed so the report can explain the absence honestly.
        if "pip_requirements" in strategy_label and not install_success_overall:
            output_files.append(log_path)
            save_json(run_log, log_path)
            _log("FAILED: pip install -r requirements.txt failed")
            return _contract(
                "error",
                output_files,
                "pip install -r requirements.txt failed",
                0,
                combined_stdout[-2000:] or f"exit_code={combined_exit_code}",
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

        # ── Snapshot working tree BEFORE execution (fabricated-success input) ─
        ls_before = daytona_tool.run_cmd(
            sandbox,
            "find /home/daytona/repo -maxdepth 4 -type f ! -path '*/.git/*' "
            "2>/dev/null",
            timeout=30,
        )
        files_before: set[str] = set(
            f.strip().replace("/home/daytona/repo/", "", 1)
            for f in (ls_before["stdout"] or "").splitlines()
            if f.strip()
        )
        _log(f"Working tree snapshot (before execution): {len(files_before)} files")

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

        # ── Classify expected outputs (Layer 2) ───────────────────────────
        # Test 4 (Riboformer) tried to download "Fig 2b" as a file path. Only
        # file_path entries are downloadable on-disk artifacts. paper_deliverable,
        # geo_accession, url, unresolved are surfaced in the report verbatim
        # but never attempted as downloads.
        classified: dict[str, list[str]] = {
            "file_path": [], "directory_path": [], "paper_deliverable": [],
            "geo_accession": [], "url": [], "unresolved": [],
        }
        for rel in target.expected_outputs:
            classified[_classify_expected_output(rel)].append((rel or "").strip())
        run_log["expected_outputs_classified"] = classified
        _log(
            "Expected-output classification: "
            + ", ".join(f"{k}={len(v)}" for k, v in classified.items() if v)
        )

        # ── Download expected outputs (file_path only) ────────────────────
        expected_found: list[str] = []
        expected_missing: list[str] = []
        for rel in classified["file_path"]:
            rel_clean = rel.lstrip("/")
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

        # ── Fabricated-success detector (Layer 2) ─────────────────────────
        # Wet-lab analog: silent no-op when simulation passes but zero liquid
        # handling. Dry-lab: clean exit but no on-disk artifacts produced.
        ls_after = daytona_tool.run_cmd(
            sandbox,
            "find /home/daytona/repo -maxdepth 4 -type f ! -path '*/.git/*' "
            "2>/dev/null",
            timeout=30,
        )
        files_after: set[str] = set(
            f.strip().replace("/home/daytona/repo/", "", 1)
            for f in (ls_after["stdout"] or "").splitlines()
            if f.strip()
        )
        fab_check = _check_dry_lab_fabricated_success(
            run_log, files_before, files_after,
        )
        run_log["fabricated_success_check"] = fab_check
        run_log["directory_outputs_populated"] = fab_check["directory_outputs_populated"]
        if fab_check["fabricated"]:
            _log(f"FABRICATED SUCCESS DETECTED: {fab_check['reason']}")
            run_log["main_script"]["success"] = False
            run_log["main_script"]["failure_reason"] = (
                f"Fabricated success: {fab_check['reason']}"
            )

        save_json(run_log, log_path)
        _log(f"Run log saved: {log_path}")

        if fab_check["fabricated"]:
            return _contract(
                "error",
                output_files,
                "Fabricated success: clean exit but no scientific artifacts produced",
                0,
                fab_check["reason"] or "",
            )

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
