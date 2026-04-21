# BioSwarm — Agent Architecture & Project Intelligence

> **Read this file on every startup before touching any code.**

---

## What This Project Is

BioSwarm is a multi-agent AI system that bridges published biology research and physical/computational execution. It operates in two modes:

- **Wet Lab Mode**: Takes a biology paper or protocol description → extracts physical methodology → enriches null critical fields from the paper's notes and open-access sources (PIE) → converts it into a validated, simulation-tested Opentrons Python script ready to run on a liquid-handling robot.
- **Dry Lab Mode**: Takes a computational biology paper → finds its linked code repository → spins up the exact environment → attempts to reproduce the paper's results → returns a Reproducibility Score.

**Core thesis**: A single LLM cannot reliably do science. BioSwarm separates reasoning, retrieval, enrichment, execution, and synthesis into specialized agents that hand off structured data — never raw text — through a shared workspace.

---

## Environment Setup

**Python version**: 3.11+ required (Daytona SDK minimum).

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in all four keys in .env

# 3a. Run the Streamlit UI
streamlit run main.py

# 3b. Or run headlessly from the CLI
python run_cli.py --mode wet_lab --input "Paper title or DOI"
python run_cli.py --mode dry_lab --input "Paper title or DOI"
```

**`.env` file** (copy from `.env.example`, never commit `.env`):
```
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
DAYTONA_API_KEY=...
DAYTONA_API_URL=https://app.daytona.io/api
DAYTONA_TARGET=us
```

**`requirements.txt`**:
```
openai>=1.30.0
tavily-python>=0.5.0
daytona>=0.1.0
pydantic>=2.0.0
streamlit>=1.35.0
python-dotenv>=1.0.0
tiktoken>=0.7.0
```

---

## Project File Structure

```
bio_swarm/
├── claude.md                  # This file — read on every startup
├── .env                       # API keys — never commit this
├── .env.example               # Template — commit this
├── requirements.txt
├── main.py                    # Streamlit UI entry point — creates /workspace/ on startup
├── run_cli.py                 # Headless CLI entry point — calls supervisor.run_pipeline()
├── agents/
│   ├── supervisor.py          # Pure-Python orchestrator (NOT an LLM) — owns state.json
│   ├── researcher.py          # Tavily Agent — web search & scraping
│   ├── methodology.py         # Extractor Agent — raw research → validated Pydantic JSON
│   ├── enricher.py            # PIE Agent — wet-lab only, fills null critical fields
│   ├── coder.py               # Daytona Agent — JSON → executable code, simulates/runs
│   └── synthesizer.py         # Reporter Agent — produces final markdown report
├── schemas/
│   ├── opentrons_schema.py    # Pydantic model for wet lab protocol (+ PIE fields)
│   ├── dry_lab_schema.py      # Pydantic model for reproducibility pipeline
│   └── state_schema.py        # Pydantic model for shared workspace state (+ enrichment)
├── tools/
│   ├── tavily_tool.py         # search_web, extract_url, extract_urls_bulk, crawl_site
│   ├── daytona_tool.py        # create_sandbox, run_code, run_cmd, upload/download, cleanup
│   ├── file_tool.py           # save/load JSON and text from /workspace/
│   └── token_tracker.py       # track_call, print_summary — tiktoken-based ledger
├── workflows/
│   ├── wet_lab_workflow.md    # Step-by-step agent routing for wet lab
│   └── dry_lab_workflow.md    # Step-by-step agent routing for dry lab
└── workspace/                 # Shared agent memory — auto-created by main.py / run_cli.py
    ├── state.json             # Live task state — Supervisor is the ONLY writer
    ├── raw_research/          # Researcher Agent outputs
    │   ├── {task_id}_search_{i}.json
    │   ├── {task_id}_search_github.json   # dry-lab github fallback, if triggered
    │   ├── {task_id}_extracted_{i}.json
    │   └── {task_id}_combined.json        # summary + all_sources (read by PIE)
    ├── extracted_protocols/   # Methodology + Enricher outputs
    │   ├── protocol_{task_id}.json        # overwritten in place by PIE
    │   └── enrichment_{task_id}.json      # PIE audit log
    ├── generated_code/        # Coder Agent outputs
    │   ├── protocol_{task_id}.py          # wet-lab: Opentrons script
    │   └── dry_lab_{task_id}_run.json     # dry-lab: run artifacts + diagnostics
    └── final_reports/         # Synthesizer Agent outputs
        └── report_{task_id}.md
```

**Workspace creation** — both `main.py` and `run_cli.py` run this on startup before any agent is called:
```python
import os
WORKSPACE_DIRS = [
    "workspace", "workspace/raw_research",
    "workspace/extracted_protocols", "workspace/generated_code",
    "workspace/final_reports"
]
for d in WORKSPACE_DIRS:
    os.makedirs(d, exist_ok=True)
```

---

## LLM Configuration

**Model**: `gpt-5.4-mini` (string: `"gpt-5.4-mini"`)
**Every LLM-using agent** (Researcher, Methodology, Enricher, Coder, Synthesizer) uses `response_format={"type": "json_object"}`. The Supervisor does not call the LLM at all.

```python
from openai import OpenAI
from tools.token_tracker import track_call

client = OpenAI()  # reads OPENAI_API_KEY from env

response = client.chat.completions.create(
    model="gpt-5.4-mini",
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": "...your system prompt..."},
        {"role": "user", "content": "..."}
    ]
)
track_call("agent_name", response)   # MANDATORY — records tokens in the ledger
import json
data = json.loads(response.choices[0].message.content)
```

**Every LLM call must be followed by `track_call(agent_name, response)`** — this is how the token summary at the end of a run is built.

---

## Tool Implementation Reference

### `tools/tavily_tool.py`

**Package**: `tavily-python` | **Import**: `from tavily import TavilyClient`

```python
from tavily import TavilyClient

client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "advanced",
    include_raw_content: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """
    Returns list of dicts with keys: url, title, content, score, raw_content.
    include_domains / exclude_domains let PIE pin searches to open-access sources
    (pmc.ncbi.nlm.nih.gov, biorxiv.org, protocols.io) and suppress paywalls.
    """

def extract_url(url: str) -> str:
    """Fetches and returns the full cleaned text of a single URL."""

def extract_urls_bulk(
    urls: list[str],
    extract_depth: str = "advanced",
    query: str | None = None,
) -> list[dict]:
    """Extract up to 20 URLs in one call. Returns list of {url, raw_content, ...}."""

def crawl_site(
    url: str,
    instructions: str | None = None,
    max_depth: int = 2,
    limit: int = 20,
) -> list[dict]:
    """BFS crawl a documentation/GitHub site for a specific kind of content."""
```

**Error handling for Tavily**:
```python
from tavily import MissingAPIKeyError, InvalidAPIKeyError, UsageLimitExceededError

try:
    results = search_web(query)
except MissingAPIKeyError:
    raise RuntimeError("TAVILY_API_KEY not set in environment")
except InvalidAPIKeyError:
    raise RuntimeError("TAVILY_API_KEY is invalid")
except UsageLimitExceededError:
    raise RuntimeError("Tavily usage limit exceeded — check account credits")
except Exception as e:
    raise RuntimeError(f"Tavily search failed: {e}")
```

---

### `tools/daytona_tool.py`

**Package**: `daytona` (NOT `daytona-sdk`) | **Install**: `pip install daytona`
**Import**: `from daytona import Daytona, DaytonaConfig, CreateSandboxParams`

```python
def create_sandbox(language: str = "python"):
    """Create a new sandbox. Returns (daytona, sandbox). Caller must call cleanup()."""

def run_cmd(sandbox, command: str, cwd: str = "/home/daytona", timeout: int = 120) -> dict:
    """Run a shell command. Returns {"exit_code": int, "stdout": str, "success": bool}."""

def run_code(sandbox, code: str, timeout: int = 60) -> dict:
    """Run a Python string in the sandbox interpreter."""

def upload_file(sandbox, content: bytes | str, remote_path: str): ...
def download_file(sandbox, remote_path: str) -> bytes: ...
def clone_repo(sandbox, url: str, dest_path: str = "/home/daytona/repo"): ...
def cleanup(daytona, sandbox): ...   # idempotent; safe in `finally:`
```

**Coder sandbox convention** — the Coder Agent uses `uv` and a Python 3.11 virtualenv for speed and reproducibility:

```python
UV   = "/usr/local/py-utils/bin/uv"
VENV = "/home/daytona/venv311"

daytona, sandbox = create_sandbox(language="python")
try:
    run_cmd(sandbox, f"{UV} venv {VENV} --python 3.11", timeout=180)
    run_cmd(sandbox, f"{UV} pip install --python {VENV}/bin/python opentrons", timeout=300)
    upload_file(sandbox, script_content, "/home/daytona/protocol.py")
    result = run_cmd(
        sandbox,
        f"{VENV}/bin/opentrons_simulate /home/daytona/protocol.py",
        timeout=120,
    )
finally:
    cleanup(daytona, sandbox)
```

Dry-lab runs follow the same `uv`-venv pattern but additionally strip `nvidia-*` / `triton` / `torch==*+cuXX` entries from `requirements.txt` and preinstall CPU-only `torch` to fit within sandbox disk limits.

---

### `tools/file_tool.py`

```python
def save_json(data: dict, path: str) -> str: ...
def load_json(path: str) -> dict: ...
def save_text(content: str, path: str) -> str: ...
def load_text(path: str) -> str: ...
```

All four create parent directories as needed.

---

### `tools/token_tracker.py`

Module-level ledger that every LLM-using agent is required to feed.

```python
from tools.token_tracker import track_call, print_summary, estimate_tokens, reset

# Inside an agent, after each OpenAI call:
track_call("researcher", response)     # uses response.usage if present; falls back to tiktoken

# Supervisor calls this at the end of a successful or failed run:
print_summary()   # per-agent prompt/completion/total token counts + grand total
```

`estimate_tokens(text, model="gpt-5.4-mini")` is available for pre-call token estimation when pruning large prompts.

---

## Agent Return Contract

Every agent function **must** return this exact dict to the Supervisor:

```python
{
    "status": "success" | "error",
    "output_files": ["workspace/raw_research/task_abc.json"],
    "message": "Human-readable summary of what happened",
    "retry_count": 0,
    "error_detail": None | "full stderr or exception traceback as string"
}
```

**Enricher** (`enricher_agent`) extends this with one extra key — `gaps_filled: int` — which the Supervisor records in `state.enrichment.gaps_filled`.

The Supervisor reads this dict and writes the relevant fields into `state.json`. Worker agents never touch `state.json` directly.

---

## The Shared Workspace (State Management)

**This is the most important architectural decision in the system.**

Agents never pass large text blobs through function arguments or LLM prompts. Every artifact is saved to `/workspace/` and referenced by filename in `state.json`. This prevents context window bloat, preserves signal-to-noise ratio, and makes the pipeline debuggable.

**One exception, by design:** the Enricher mutates `protocol_{task_id}.json` in place (with a pre-mutation deep copy held in memory). If Pydantic re-validation after enrichment fails, the Enricher writes the backup back to disk and returns an error contract. This is the only upstream-artifact mutation in the system; the tradeoff is that Coder and Synthesizer only ever see one protocol file regardless of whether PIE ran.

### `state.json` schema (always current)
```json
{
  "task_id": "uuid",
  "mode": "wet_lab | dry_lab",
  "user_input": "original user request",
  "status": "research | extraction | enrichment | coding | simulation | synthesis | complete | error",
  "research":   {"done": false, "files": [], "sources": []},
  "extraction": {"done": false, "protocol_file": null, "schema_valid": false},
  "enrichment": {"done": false, "enrichment_file": null,
                 "gaps_identified": 0, "gaps_filled": 0, "skipped": false},
  "coding":     {"done": false, "script_file": null, "simulation_passed": false,
                 "error_log": null, "retry_count": 0},
  "synthesis":  {"done": false, "report_file": null},
  "errors": []
}
```

The **Supervisor Agent is the only writer to `state.json`.** Worker agents return their outputs via the Agent Return Contract dict, and the Supervisor updates state accordingly.

---

## Agent Roster

### 1. Supervisor (Pure-Python Orchestrator)
**File**: `agents/supervisor.py`
**Role**: Calls each agent in sequence, owns `state.json`, translates exceptions into error contracts, prints the token summary.

**There is no LLM in the Supervisor and no system prompt.** It is a straightforward Python function:

```python
def run_pipeline(
    user_input: str,
    mode: str,                         # "wet_lab" | "dry_lab"
    task_id: str,
    status_callback=None,              # optional: callable(str) for per-phase updates
) -> dict:
    """Returns {"status", "task_id", "report_file", "state"}."""
```

**Sequence**:
1. Research (always)
2. Extraction (always)
3. **Enrichment (wet-lab only, non-blocking)** — if PIE errors, the supervisor logs `state.enrichment.skipped = True`, appends a warning to `state.errors`, and proceeds to Coder with the sparse protocol.
4. Coding (always)
5. Synthesis (always)

**Error handling**: on any non-success contract from a blocking step, the Supervisor marks `state.status = "error"`, appends `[phase] {message}: {error_detail}` to `state.errors`, prints the token summary, and returns the error dict. No clarifying questions, no user interaction — both entry points (`main.py` and `run_cli.py`) handle UX.

**`main.py` duplicates this orchestration inline** so it can render per-agent terminal panels in Streamlit; `run_cli.py` calls `run_pipeline` directly. Keep the two in sync when adding new phases.

---

### 2. Researcher (Tavily)
**File**: `agents/researcher.py`
**Tools**: `tavily_tool.search_web`, `tavily_tool.extract_url`

**Pipeline**:
1. LLM plans 2–3 targeted search queries based on mode.
2. Runs each query via Tavily; on empty results, retries once with a broader query (`{user_input} biology protocol methodology`).
3. **Dry-lab github fallback**: if no `github.com` URL appears in results, runs one additional `{user_input} site:github.com` query.
4. LLM picks the top ~2 URLs worth full extraction; runs `extract_url` on each.
5. Saves per-query files, per-extraction files, and a combined summary file to `workspace/raw_research/`.

**Output files**:
- `{task_id}_search_{i}.json` — one per planned query
- `{task_id}_search_github.json` — only if dry-lab fallback triggered
- `{task_id}_extracted_{i}.json` — one per picked URL
- `{task_id}_combined.json` — aggregated summary + `all_sources` list (read by PIE and Synthesizer)

**Critical rules**:
- Never summarize results before saving. Save the raw Tavily output; let Methodology interpret.
- Always preserve source URLs alongside content.
- If a Tavily call raises `RuntimeError`, return an error contract immediately — don't silently continue.

---

### 3. Methodology (Extractor)
**File**: `agents/methodology.py`
**Input**: `researcher_result` dict (uses its `output_files` list)
**Output**: `workspace/extracted_protocols/protocol_{task_id}.json`

**Pipeline**:
1. Load every file from the researcher's `output_files`; concatenate the useful text content; truncate to ~30k chars.
2. LLM call → JSON matching the target schema.
3. Validate with Pydantic. On failure, **retry once** with the validation error fed back as an assistant/user message pair.
4. **Dry-lab post-hoc github resolver** (`_find_missing_github_url`): if `github_url` is null, extract candidate package names from the paper title (capitalized words/acronyms) and run up to 3 targeted `{pkg} github repository` searches.
5. Save the validated JSON.

**Critical rules**:
- Never hallucinate values. If a field isn't present in the sources, set it to `null` and append a note to `extraction_notes[]`.
- Wet-lab extraction targets `OpentronsProtocol`; dry-lab targets `ReproducibilityTarget`.

---

### 4. Enricher (PIE — Protocol Intelligence Enrichment)
**File**: `agents/enricher.py`
**Mode**: **Wet-lab only.** Non-blocking — failures are treated as warnings by the Supervisor.

PIE inserts between Methodology and Coder. It reads the sparse extracted protocol, identifies null critical fields, and fills them with provenance and confidence metadata.

**Critical fields** (in fill-priority order):
`volume_ul`, `pipettes`, `labware_setup`, `temperature_celsius`, `duration_seconds`, `speed_rpm`, `source_location`, `destination_location`

**Constants** (see source for authoritative values):
```python
MAX_QUERIES              = 20    # per-run Tavily query cap
CONFIDENCE_THRESHOLD     = 0.60  # minimum confidence to apply a fill
NOTES_DERIVED_CONFIDENCE = 0.88  # confidence for values mined from protocol notes
OPEN_ACCESS_DOMAINS      = ["pmc.ncbi.nlm.nih.gov", "biorxiv.org", "protocols.io", ...]
PAYWALL_DOMAINS          = ["nature.com", "science.org", "cell.com", ...]
```

**Three phases**:
1. **Phase 0 — Notes Mining**: LLM reads `extraction_notes[]` and per-step `notes` strings to find values already stated in the paper but not placed in structured fields. High-confidence (0.88) fills, no Tavily calls.
2. **Phase 1 — Gap Analysis**: LLM identifies remaining null critical fields and generates a short (4–8 word) `search_hint` for each.
3. **Phase 2 — Targeted Search + Fill**: For each remaining gap (capped at `MAX_QUERIES // 2`), runs up to 2 Tavily queries pinned to `OPEN_ACCESS_DOMAINS` with `include_raw_content=True`. Bulk-extracts PMC/biorxiv URLs via `extract_urls_bulk`. LLM extracts a typed value + confidence + source URL. Fills applied only if `confidence >= CONFIDENCE_THRESHOLD`.

**Conflict handling**: if two sources produce different values for the same field, both candidates are logged, the fill is reverted to the backup, and the conflict is recorded in the enrichment log — the field is left null for the Coder to skip.

**Output**:
- Overwrites `workspace/extracted_protocols/protocol_{task_id}.json` in place (with `pie_ran: true` and a full `enrichment_log` dict).
- Writes `workspace/extracted_protocols/enrichment_{task_id}.json` as an audit trail (fills, conflicts, still_null, query counts).

**Safety valve**: if the enriched protocol fails Pydantic re-validation, the pre-mutation backup is written back to disk and the contract is an error. The Supervisor will then continue with the unenriched protocol.

**Per-step provenance**: fills write `field_confidence[field] -> float` and `field_sources[field] -> url` on the step. The Synthesizer uses these to render "Confidence notes" in the final report.

---

### 5. Coder (Daytona)
**File**: `agents/coder.py`
**Tools**: `daytona_tool.py`

#### Wet Lab Behavior
1. Load `protocol_{task_id}.json` (post-PIE if applicable).
2. LLM generates an Opentrons Python script (must use every populated field; skips nulls with `# SKIPPED: {note}` comments).
3. Provision sandbox: `uv venv {VENV} --python 3.11`, then `uv pip install opentrons`.
4. Upload script, run `{VENV}/bin/opentrons_simulate …`.
5. Inspect both `success` and **silent no-op detection**: count liquid-handling calls using
   ```python
   LIQUID_RE = re.compile(r"\.(transfer|distribute|consolidate|aspirate|dispense|mix|blow_out|pick_up_tip|drop_tip)\s*\(")
   ```
   A protocol whose simulation exits cleanly but emits zero liquid-handling calls is treated as a failure (fabricated success mode).
6. On failure, parse stdout for the specific error, regenerate the affected section, retry up to `WET_LAB_MAX_SIM_ATTEMPTS = 4` total attempts.
7. Save final script to `workspace/generated_code/protocol_{task_id}.py`. Cleanup sandbox in `finally`.

#### Dry Lab Behavior
1. Load `ReproducibilityTarget` JSON.
2. Create sandbox + `uv` venv.
3. `clone_repo(sandbox, github_url)` if present.
4. **CPU-only torch strategy**: strip `nvidia-*`, `triton`, and `+cu*` suffixes from `requirements.txt` before install; preinstall CPU-only `torch` to avoid disk-space failures.
5. **Entry-point discovery**: `find` with `maxdepth 4` for `main.py`, `run.py`, `run.sh`, `Makefile`, notebooks. Convert `.ipynb` entry points via `nbconvert`.
6. **Diagnostics pass**: probe for fixed seeds, GPU-only imports, README instructions, expected data files — surfaced in the dry-run log.
7. Execute the entry point; capture stdout/stderr and scan the working tree for newly-generated output files.
8. Save everything to `workspace/generated_code/dry_lab_{task_id}_run.json` (includes exit code, stdout, stderr, diagnostics, generated-file list). Cleanup sandbox.

**Critical rules**:
- Always wrap sandbox lifecycle in `try/finally` with `cleanup(daytona, sandbox)` in the `finally` block. No leaked sandboxes.
- Self-correction loop is mandatory — never return a first-attempt wet-lab failure without retrying.
- Never install packages not in the paper's requirements file (dry lab) or not needed for the protocol (wet lab).
- A clean simulation that performed no liquid handling is **not** a success — fail it explicitly.

---

### 6. Synthesizer (Reporter)
**File**: `agents/synthesizer.py`
**Input**: `task_id` only — reads `state.json` to locate all artifacts.
**Output**: `workspace/final_reports/report_{task_id}.md`

The Synthesizer uses the LLM in JSON mode to fill structured templates. Section order is a hard contract — don't reorder without updating both `main.py` and any demo scripts that parse the output.

#### Wet-Lab Report — 5 sections, in this order
1. **Protocol summary** — what the paper describes (name, paper source, reagents, labware, step count).
2. **Generated Opentrons script** — full code block from `workspace/generated_code/protocol_{task_id}.py`.
3. **Simulation result** — Pass/Fail, simulator stdout excerpt, warnings.
4. **Confidence notes from extraction** — any `null` fields from `extraction_notes`, **plus** a PIE summary block if `protocol.pie_ran` is true: gaps identified, gaps filled, note-vs-Tavily split, conflicts, fields still null, per-step `field_sources` citations.
5. **Source citations** — URLs from `raw_research/{task_id}_combined.json` and PIE `fills[].source_url`.

#### Dry-Lab Report — 9 sections, in this order
1. **Paper & Repository Summary**
2. **Reproducibility Score** — `PASS` / `PARTIAL` / `FAIL` using the rubric below
3. **Dependency Analysis** — what installed, what didn't, CPU-only patches applied
4. **Data Availability** — were datasets reachable? any missing `data_download_urls`?
5. **Reproducibility Practices** — fixed seeds? pinned versions? container/env file? README quality?
6. **Execution Results** — exit code, entry point used, stdout/stderr excerpts
7. **Output Verification** — did generated files match `expected_outputs` from the schema?
8. **Recommendations** — concrete fixes needed to reach PASS
9. **Source Citations**

**Rubric**:
- **PASS**: dependencies installed cleanly, entry point exited 0, outputs match `expected_outputs`.
- **PARTIAL**: code ran to completion but outputs missing/mismatched, or ran only after non-trivial patches.
- **FAIL**: dependency install failed, entry point errored, or no entry point discoverable.

---

## Schemas

### `schemas/opentrons_schema.py`
```python
from pydantic import BaseModel
from typing import Optional, List, Literal

class ProtocolStep(BaseModel):
    step_number: int
    action: Literal["transfer", "distribute", "consolidate", "mix",
                    "incubate", "centrifuge", "aspirate", "dispense"]
    volume_ul: Optional[float] = None
    source_location: Optional[str] = None
    destination_location: Optional[str] = None
    duration_seconds: Optional[int] = None
    speed_rpm: Optional[int] = None
    temperature_celsius: Optional[float] = None
    notes: Optional[str] = None
    # PIE provenance — populated only for fields filled by the Enricher
    field_confidence: Optional[dict] = None    # {"volume_ul": 0.88, ...}
    field_sources: Optional[dict] = None       # {"volume_ul": "https://pmc..."}

class OpentronsProtocol(BaseModel):
    protocol_name: str
    paper_source: str
    labware_setup: List[str]
    pipettes: List[str]
    reagents: List[str]
    sequential_steps: List[ProtocolStep]
    extraction_notes: List[str]
    # PIE bookkeeping
    pie_ran: bool = False
    enrichment_log: Optional[dict] = None
```

### `schemas/dry_lab_schema.py`
```python
class ReproducibilityTarget(BaseModel):
    paper_title: str
    paper_source: str
    github_url: Optional[str] = None
    requirements_file: Optional[str] = None
    data_download_urls: List[str] = []
    main_script: Optional[str] = None
    expected_outputs: List[str] = []
    extraction_notes: List[str] = []
```

### `schemas/state_schema.py`
```python
class ResearchState(BaseModel):
    done: bool = False
    files: List[str] = []
    sources: List[str] = []

class ExtractionState(BaseModel):
    done: bool = False
    protocol_file: Optional[str] = None
    schema_valid: bool = False

class EnrichmentState(BaseModel):
    done: bool = False
    enrichment_file: Optional[str] = None
    gaps_identified: int = 0
    gaps_filled: int = 0
    skipped: bool = False

class CodingState(BaseModel):
    done: bool = False
    script_file: Optional[str] = None
    simulation_passed: bool = False
    error_log: Optional[str] = None
    retry_count: int = 0

class SynthesisState(BaseModel):
    done: bool = False
    report_file: Optional[str] = None

class WorkspaceState(BaseModel):
    task_id: str
    mode: Literal["wet_lab", "dry_lab"]
    user_input: str
    status: Literal["research", "extraction", "enrichment", "coding",
                    "simulation", "synthesis", "complete", "error"]
    research:   ResearchState   = ResearchState()
    extraction: ExtractionState = ExtractionState()
    enrichment: EnrichmentState = EnrichmentState()
    coding:     CodingState     = CodingState()
    synthesis:  SynthesisState  = SynthesisState()
    errors: List[str] = []
```

---

## Entry Points

### Streamlit UI (`main.py`)
- Renders per-agent terminal panels as each phase runs.
- **Duplicates the orchestration inline** (does not call `run_pipeline`) so it can update panel state between agents.
- Imports all five worker agents directly; shares the same `state.json` discipline as the headless runner.

### Headless CLI (`run_cli.py`)
- `python run_cli.py --mode {wet_lab|dry_lab} --input "…"`
- Calls `supervisor.run_pipeline(...)` with a `status_callback` that prints each phase transition.
- Exits 0 on success, 1 on any error.
- `chdir`s to the project root first so all `workspace/…` relative paths resolve correctly.

**When adding a new phase, update both entry points.**

---

## Error Handling Patterns

| Scenario | Handler |
|---|---|
| Tavily returns empty results | Retry once with broader query; still empty → error contract with queries logged |
| No `github.com` URL after dry-lab research | One extra `site:github.com` fallback query in Researcher |
| Methodology produces invalid JSON | Pydantic validates; retry once with error fed back; then error contract |
| Methodology returns null `github_url` (dry lab) | Post-hoc resolver tries 3 package-name searches before saving |
| PIE Pydantic re-validation fails | Revert to pre-mutation backup; error contract; supervisor marks skipped, continues |
| PIE any other exception | Non-blocking — supervisor logs warning, continues to Coder with sparse protocol |
| Wet-lab simulator clean but no liquid handling | **Fail explicitly** — silent no-op, regenerate and retry |
| Daytona `SyntaxError` / `ImportError` in simulation | Parse stdout, patch, retry; up to `WET_LAB_MAX_SIM_ATTEMPTS = 4` |
| Wet-lab simulation fails 4 times | Cleanup sandbox; Coder returns error contract; Supervisor escalates |
| Dry-lab deps include CUDA torch | Strip `nvidia-*` / `+cu*`, preinstall CPU-only `torch` |
| Dry-lab entry point missing | Discovery via `find -maxdepth 4`; notebooks converted via `nbconvert` |
| Sandbox leak | `try/finally` with `cleanup()` — always. Never rely on the happy path. |
| Any unexpected exception in a worker | Supervisor wraps it into an error contract via `_exception_contract()` |

---

## Rules for All Agents

1. **Never hallucinate scientific values.** If a value is not in the source material, it is `null` (or in PIE's case, only filled if `confidence >= CONFIDENCE_THRESHOLD`).
2. **Never pass raw paper text between agents.** Save to file, pass the filename.
3. **Always validate output schema with Pydantic before returning to Supervisor.** (PIE re-validates after mutation; on failure, revert.)
4. **Always call `track_call(agent_name, response)` after every LLM call.**
5. **Always log errors with the full stdout/stderr trace, not just "it failed."**
6. **Retry before escalating.** Every agent has an internal retry budget appropriate to its cost (Methodology: 1, Coder wet-lab: 4, PIE: capped at `MAX_QUERIES`).
7. **Cite sources.** Every factual claim in the final report traces back to a Tavily URL or a PIE `field_sources[field]`.
8. **Always return the Agent Return Contract dict.** The Supervisor depends on the structure.
9. **Always clean up Daytona sandboxes.** Use `try/finally`. No leaked sandboxes.
10. **Treat a clean-but-empty wet-lab simulation as a failure.** Use the liquid-handling regex check.

---

## Hackathon Demo Script

Walk judges through this sequence:
1. Paste a real biopaper link into the Streamlit UI.
2. Show Tavily scraping in real time (per-agent terminal panel).
3. Show the extracted JSON protocol appearing in `workspace/extracted_protocols/`.
4. Show PIE's notes-mining and Tavily gap-filling, with the `enrichment_{task_id}.json` audit trail.
5. Show the Daytona sandbox spinning up with `uv` + Python 3.11 venv.
6. Show `opentrons_simulate` running, passing, and the liquid-handling-call count sanity check.
7. Show the final Opentrons `.py` script — highlight that it came from a PDF, not a human, with per-field source URLs traceable via `field_sources`.
8. Switch to Dry Lab tab — show a reproducibility score on a known-broken paper, with the CPU-only torch patch and entry-point discovery surfaced in the report.
