# BioSwarm — Agent Architecture & Project Intelligence

> **Read this file on every startup before touching any code.**

---

## What This Project Is

BioSwarm is a multi-agent AI system that bridges published biology research and physical/computational execution. It operates in two modes:

- **Wet Lab Mode**: Takes a biology paper or protocol description → extracts physical methodology → converts it into a validated, simulation-tested Opentrons Python script ready to run on a liquid-handling robot.
- **Dry Lab Mode**: Takes a computational biology paper → finds its linked code repository → spins up the exact environment → attempts to reproduce the paper's results → returns a Reproducibility Score.

**Core thesis**: A single LLM cannot reliably do science. BioSwarm separates reasoning, retrieval, execution, and synthesis into specialized agents that hand off structured data — never raw text — through a shared workspace.

---

## Environment Setup

**Python version**: 3.11+ required (Daytona SDK minimum).

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in all four keys in .env

# 3. Run the app
streamlit run main.py
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
```

---

## Project File Structure

```
bio_swarm/
├── claude.md                  # This file — read on every startup
├── .env                       # API keys — never commit this
├── .env.example               # Template — commit this
├── requirements.txt
├── main.py                    # Streamlit entry point — creates /workspace/ on startup
├── agents/
│   ├── supervisor.py          # PI Agent — routes tasks, owns state.json
│   ├── researcher.py          # Tavily Agent — web search & scraping
│   ├── methodology.py         # Extractor Agent — PDF/text → JSON schema
│   ├── coder.py               # Daytona Agent — JSON → executable code
│   └── synthesizer.py         # Reporter Agent — produces final output
├── schemas/
│   ├── opentrons_schema.py    # Pydantic model for wet lab protocol
│   ├── dry_lab_schema.py      # Pydantic model for reproducibility pipeline
│   └── state_schema.py        # Pydantic model for shared workspace state
├── tools/
│   ├── tavily_tool.py         # Wrapper: search_web() and extract_url()
│   ├── daytona_tool.py        # Wrapper: create_sandbox(), run_code(), run_cmd(), cleanup()
│   └── file_tool.py           # Wrapper: save/load JSON and text from /workspace/
├── workflows/
│   ├── wet_lab_workflow.md    # Step-by-step agent routing for wet lab
│   └── dry_lab_workflow.md    # Step-by-step agent routing for dry lab
└── workspace/                 # Shared agent memory — auto-created by main.py at startup
    ├── state.json             # Live task state — Supervisor is the ONLY writer
    ├── raw_research/          # Researcher Agent outputs land here
    ├── extracted_protocols/   # Methodology Agent outputs land here
    ├── generated_code/        # Coder Agent outputs land here
    └── final_reports/         # Synthesizer Agent outputs land here
```

**Workspace creation** — `main.py` runs this on startup before any agent is called:
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

**Model**: `gpt-5.4` (string: `"gpt-5.4"`)
**All agents** use `response_format={"type": "json_object"}` — every agent prompt must instruct the model to return only JSON.

```python
from openai import OpenAI
client = OpenAI()  # reads OPENAI_API_KEY from env

response = client.chat.completions.create(
    model="gpt-5.4",
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": "...your system prompt..."},
        {"role": "user", "content": "..."}
    ]
)
result = response.choices[0].message.content  # always a JSON string
import json
data = json.loads(result)
```

---

## Tool Implementation Reference

### `tools/tavily_tool.py`

**Package**: `tavily-python` | **Import**: `from tavily import TavilyClient`

```python
import os
from tavily import TavilyClient, MissingAPIKeyError, InvalidAPIKeyError

client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def search_web(query: str, max_results: int = 5, search_depth: str = "advanced") -> list[dict]:
    """
    Returns list of dicts, each with keys: url, title, content, score, raw_content (if requested).
    search_depth: "basic" (faster, cheaper) or "advanced" (deeper, more relevant — use this).
    """
    response = client.search(
        query=query,
        max_results=max_results,
        search_depth=search_depth,        # "basic" | "advanced"
        include_raw_content=True,         # returns full page text in raw_content field
        include_answer=False,
    )
    return response["results"]            # list of {url, title, content, score, raw_content}

def extract_url(url: str) -> str:
    """
    Fetches and returns the full cleaned text of a specific URL.
    Use this when search gives a URL and you need the complete page content.
    """
    response = client.extract(url)
    # response["results"] is a list; take the first item's raw_content
    return response["results"][0].get("raw_content", "")
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
import os
from daytona import Daytona, DaytonaConfig, CreateSandboxParams

def _get_client() -> Daytona:
    """Returns configured Daytona client. Reads env vars automatically if not passed."""
    config = DaytonaConfig(
        api_key=os.getenv("DAYTONA_API_KEY"),
        api_url=os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api"),
        target=os.getenv("DAYTONA_TARGET", "us"),
    )
    return Daytona(config)

def create_sandbox(language: str = "python"):
    """Create a new sandbox. Returns the sandbox object. Caller must delete it."""
    daytona = _get_client()
    sandbox = daytona.create(CreateSandboxParams(language=language))
    return daytona, sandbox          # return both so caller can call daytona.remove(sandbox)

def run_cmd(sandbox, command: str, cwd: str = "/home/daytona", timeout: int = 120) -> dict:
    """
    Run a shell command (pip install, git clone, opentrons_simulate, etc.).
    Returns {"exit_code": int, "stdout": str, "success": bool}
    """
    response = sandbox.process.exec(command, cwd=cwd, timeout=timeout)
    return {
        "exit_code": response.exit_code,
        "stdout": response.result,
        "success": response.exit_code == 0,
    }

def run_code(sandbox, code: str, timeout: int = 60) -> dict:
    """
    Run a Python code string directly in the sandbox interpreter.
    Returns {"exit_code": int, "stdout": str, "success": bool}
    """
    response = sandbox.process.code_run(code, timeout=timeout)
    return {
        "exit_code": response.exit_code,
        "stdout": response.result,
        "success": response.exit_code == 0,
    }

def upload_file(sandbox, content: bytes | str, remote_path: str):
    """Upload a file into the sandbox filesystem."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    sandbox.fs.upload_file(content, remote_path)

def download_file(sandbox, remote_path: str) -> bytes:
    """Download a file from the sandbox filesystem."""
    return sandbox.fs.download_file(remote_path)

def clone_repo(sandbox, url: str, dest_path: str = "/home/daytona/repo"):
    """Clone a git repository into the sandbox."""
    sandbox.git.clone(url, dest_path)

def cleanup(daytona, sandbox):
    """Always call this after a sandbox is done — avoids leaving billable sandboxes running."""
    try:
        daytona.remove(sandbox)
    except Exception:
        pass  # best-effort cleanup
```

**Daytona usage pattern in Coder Agent** (always use try/finally for cleanup):
```python
daytona, sandbox = create_sandbox(language="python")
try:
    run_cmd(sandbox, "pip install opentrons", timeout=180)
    upload_file(sandbox, script_content, "/home/daytona/protocol.py")
    result = run_cmd(sandbox, "opentrons_simulate /home/daytona/protocol.py", timeout=120)
    # result["success"] and result["stdout"] / result["exit_code"]
finally:
    cleanup(daytona, sandbox)
```

---

### `tools/file_tool.py`

```python
import json, os

def save_json(data: dict, path: str) -> str:
    """Saves dict to path. Creates parent dirs. Returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path

def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)

def save_text(content: str, path: str) -> str:
    """Saves raw text to path. Returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path

def load_text(path: str) -> str:
    with open(path, "r") as f:
        return f.read()
```

---

## Agent Return Contract

Every agent function **must** return this exact dict to the Supervisor:

```python
{
    "status": "success" | "error",
    "output_files": ["workspace/raw_research/task_abc.json"],  # list of files written
    "message": "Human-readable summary of what happened",
    "retry_count": 0,    # how many retries this agent performed internally
    "error_detail": None | "full stderr or exception traceback as string"
}
```

The Supervisor reads this dict and writes the relevant fields into `state.json`. Worker agents never touch `state.json` directly.

---

## The Shared Workspace (State Management)

**This is the most important architectural decision in the system.**

Agents NEVER pass large text blobs to each other through function arguments or LLM prompts. Every artifact is saved to `/workspace/` and referenced by filename in `state.json`. This prevents context window bloat, preserves signal-to-noise ratio, and makes the pipeline debuggable.

### `state.json` schema (always current)
```json
{
  "task_id": "uuid",
  "mode": "wet_lab | dry_lab",
  "user_input": "original user request",
  "status": "research | extraction | coding | simulation | synthesis | complete | error",
  "research": {
    "done": false,
    "files": [],
    "sources": []
  },
  "extraction": {
    "done": false,
    "protocol_file": null,
    "schema_valid": false
  },
  "coding": {
    "done": false,
    "script_file": null,
    "simulation_passed": false,
    "error_log": null,
    "retry_count": 0
  },
  "synthesis": {
    "done": false,
    "report_file": null
  },
  "errors": []
}
```

The **Supervisor Agent is the only agent that writes to `state.json`**. All other agents return their outputs via the Agent Return Contract dict above, and the Supervisor updates state accordingly. This prevents race conditions and keeps a single source of truth.

---

## Agent Roster

### 1. Supervisor Agent (Principal Investigator)
**File**: `agents/supervisor.py`
**Role**: Orchestrates the entire pipeline. Interacts with the user. Does NO actual work itself.

**Responsibilities**:
- Ask the user 2–3 clarifying questions before starting (mode, paper input, goal)
- Break the task into subtasks and route to appropriate worker agents in sequence
- Read `state.json` before delegating to avoid redundant work
- Write `state.json` after every agent returns
- Detect errors in agent return dicts and trigger retry or escalation
- Never pass more than a filename + instruction to any worker agent

**System Prompt**:
> You are the Principal Investigator of BioSwarm. You manage a team of specialized agents. You never do research, coding, or writing yourself. Your job is to understand the user's goal, decompose it into subtasks, delegate to agents in the correct order, and assemble the final result. Always read state.json before delegating to avoid redundant work. When an agent returns status="error", increment retry_count and re-delegate with the full error_detail included in the new instruction. After 3 failures on the same step, escalate to the user with a plain-language summary of the failure.
> 
> Always return valid JSON.

---

### 2. Researcher Agent (Tavily)
**File**: `agents/researcher.py`
**Tools**: `tavily_tool.search_web()` and `tavily_tool.extract_url()`

**Wet Lab inputs**: Paper title, DOI, or description of protocol
**Dry Lab inputs**: Paper title + "GitHub repository" + "supplemental data"

**Output**: Saves raw search results and scraped content as `.json` files in `workspace/raw_research/`. Returns filenames in the Agent Return Contract dict.

**Critical rules**:
- Never summarize results before saving — save raw output, let Methodology Agent interpret
- Always save source URLs alongside content for citations in the final report
- For Dry Lab: must find (1) GitHub repo URL, (2) requirements.txt or environment.yml contents, (3) any data download links
- If `search_web` returns zero results, retry once with a broader query, then return `status="error"` with the queries attempted in `error_detail`
- Call `extract_url()` on the most relevant URL when you need the full page (not just the snippet)

---

### 3. Methodology Agent (Extractor)
**File**: `agents/methodology.py`
**Role**: Reads raw research files and extracts structured protocol data.

**Input**: Filename(s) from `workspace/raw_research/` (passed as strings by Supervisor)
**Output**: A validated Pydantic JSON object saved to `workspace/extracted_protocols/protocol_{task_id}.json`

**Critical rules**:
- Output MUST pass Pydantic schema validation before being saved. If validation fails, fix and retry — do not pass invalid data downstream.
- For Wet Lab: extract to `OpentronsProtocol` schema
- For Dry Lab: extract to `ReproducibilityTarget` schema
- If a field is ambiguous or missing from the paper, set it to `null` and add a note to `extraction_notes[]` — do NOT hallucinate values
- The LLM must be instructed in its system prompt to return only JSON matching the schema exactly

---

### 4. Coder Agent (Daytona)
**File**: `agents/coder.py`
**Tools**: `daytona_tool.py` (see Tool Implementation Reference above)

**Wet Lab behavior**:
1. Read `protocol_{task_id}.json` via `file_tool.load_json()`
2. Call GPT-5.4 with the protocol JSON → generates Opentrons Python script
3. Create a Daytona sandbox, install `opentrons` via `run_cmd(sandbox, "pip install opentrons")`
4. Upload the script via `upload_file(sandbox, script, "/home/daytona/protocol.py")`
5. Run `result = run_cmd(sandbox, "opentrons_simulate /home/daytona/protocol.py")`
6. Check `result["success"]`:
   - If `True` → save script to `workspace/generated_code/protocol_{task_id}.py`, cleanup sandbox
   - If `False` → parse `result["stdout"]` for the specific error, regenerate the affected section, retry (max 3)
7. After 3 failures → cleanup sandbox, return `status="error"` with full stdout as `error_detail`

**Dry Lab behavior**:
1. Read `ReproducibilityTarget` JSON from `workspace/extracted_protocols/`
2. Create a Daytona sandbox
3. `clone_repo(sandbox, github_url)` if available
4. Install deps: `run_cmd(sandbox, "pip install -r /home/daytona/repo/requirements.txt")`
5. Run the main script: `run_cmd(sandbox, f"python /home/daytona/repo/{main_script}")`
6. Capture all stdout/stderr
7. Download any generated output files via `download_file(sandbox, path)`
8. Save all artifacts to `workspace/generated_code/`
9. Cleanup sandbox

**Critical rules**:
- Always wrap sandbox lifecycle in `try/finally` with `cleanup(daytona, sandbox)` in the `finally` block
- Self-correction loop is mandatory — never return a first-attempt failure without retrying
- Log every retry: what error occurred, what fix was applied
- Never install packages not in the paper's requirements file

---

### 5. Synthesizer Agent (Reporter)
**File**: `agents/synthesizer.py`
**Role**: Reads all workspace artifacts and writes the final human-readable report.

**Input**: Reads `state.json` to find all output filenames, then reads those files via `file_tool`
**Output**: Markdown report saved to `workspace/final_reports/report_{task_id}.md`

**Wet Lab report includes**:
- Protocol summary (what the paper describes)
- The generated Opentrons Python script (code block)
- Simulation result (Pass/Fail + any warnings)
- Confidence notes from extraction (any null fields)
- Source citations with URLs

**Dry Lab report includes**:
- Paper summary
- Reproducibility Score: `PASS` / `PARTIAL` / `FAIL`
- Environment setup result (did dependencies install?)
- Execution result (did the code run without errors?)
- Output comparison (did figures/results match the paper's claims?)
- Specific failure points if FAIL (missing data, bad dependency, hidden preprocessing steps, etc.)
- Source citations with URLs

---

## Schemas

### `schemas/opentrons_schema.py`
```python
from pydantic import BaseModel
from typing import Optional, List, Literal

class ProtocolStep(BaseModel):
    step_number: int
    action: Literal["transfer", "distribute", "consolidate", "mix", "incubate", "centrifuge", "aspirate", "dispense"]
    volume_ul: Optional[float] = None
    source_location: Optional[str] = None       # e.g. "A1", "Sample_Tube_1"
    destination_location: Optional[str] = None
    duration_seconds: Optional[int] = None      # for incubate/centrifuge
    speed_rpm: Optional[int] = None             # for centrifuge
    temperature_celsius: Optional[float] = None # for incubate
    notes: Optional[str] = None                 # ambiguities from the paper

class OpentronsProtocol(BaseModel):
    protocol_name: str
    paper_source: str                           # title or DOI
    labware_setup: List[str]                    # Opentrons API labware names
    pipettes: List[str]                         # e.g. "p300_single_gen2"
    reagents: List[str]
    sequential_steps: List[ProtocolStep]
    extraction_notes: List[str]                 # fields that were null or ambiguous
```

### `schemas/dry_lab_schema.py`
```python
from pydantic import BaseModel
from typing import Optional, List

class ReproducibilityTarget(BaseModel):
    paper_title: str
    paper_source: str
    github_url: Optional[str] = None
    requirements_file: Optional[str] = None     # full contents of requirements.txt
    data_download_urls: List[str] = []
    main_script: Optional[str] = None           # entry point filename
    expected_outputs: List[str] = []            # figures/tables the paper claims to produce
    extraction_notes: List[str] = []
```

### `schemas/state_schema.py`
```python
from pydantic import BaseModel
from typing import Optional, List, Literal

class ResearchState(BaseModel):
    done: bool = False
    files: List[str] = []
    sources: List[str] = []

class ExtractionState(BaseModel):
    done: bool = False
    protocol_file: Optional[str] = None
    schema_valid: bool = False

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
    status: Literal["research", "extraction", "coding", "simulation", "synthesis", "complete", "error"]
    research: ResearchState = ResearchState()
    extraction: ExtractionState = ExtractionState()
    coding: CodingState = CodingState()
    synthesis: SynthesisState = SynthesisState()
    errors: List[str] = []
```

---

## Streamlit UI (`main.py`)

**Threading model**: All agents are called **synchronously** inside `st.status()` context managers. Do not use threads or async. The UI blocks while an agent runs, which is correct — each `st.status()` block opens, the agent runs, then the block closes with a checkmark or error.

**Structure**:
```python
import streamlit as st
import uuid, os, json
from tools.file_tool import save_json, load_json

# --- Startup ---
WORKSPACE_DIRS = ["workspace", "workspace/raw_research", "workspace/extracted_protocols",
                  "workspace/generated_code", "workspace/final_reports"]
for d in WORKSPACE_DIRS:
    os.makedirs(d, exist_ok=True)

# --- UI Layout ---
st.title("🧬 BioSwarm")
mode = st.radio("Mode", ["Wet Lab", "Dry Lab"])
user_input = st.text_area("Paste a paper title, DOI, URL, or abstract")

if st.button("Run BioSwarm") and user_input:
    task_id = str(uuid.uuid4())[:8]

    with st.status("🔬 Researcher Agent — searching...") as s:
        result = researcher_agent(user_input, mode, task_id)
        s.update(label=f"✅ Research done — {len(result['output_files'])} files saved", state="complete")

    with st.status("🧠 Methodology Agent — extracting protocol...") as s:
        result = methodology_agent(result, task_id)
        s.update(label="✅ Protocol extracted and validated", state="complete")

    with st.status("💻 Coder Agent — running in Daytona sandbox...") as s:
        result = coder_agent(result, mode, task_id)
        if result["status"] == "error":
            s.update(label=f"❌ Coder failed after {result['retry_count']} retries", state="error")
            st.error(result["error_detail"])
            st.stop()
        s.update(label="✅ Script generated and simulation passed", state="complete")

    with st.status("📝 Synthesizer Agent — writing report...") as s:
        result = synthesizer_agent(task_id)
        s.update(label="✅ Report complete", state="complete")

    # Show state.json for transparency
    with st.expander("🔍 Pipeline State (state.json)"):
        st.json(load_json(f"workspace/state.json"))

    # Show final report
    report = open(f"workspace/final_reports/report_{task_id}.md").read()
    st.markdown(report)

    # Download button
    if mode == "Wet Lab":
        script = open(f"workspace/generated_code/protocol_{task_id}.py").read()
        st.download_button("⬇️ Download Opentrons Script", script, f"protocol_{task_id}.py", "text/plain")
    else:
        st.download_button("⬇️ Download Reproducibility Report", report, f"report_{task_id}.md", "text/markdown")
```

---

## Error Handling Patterns

| Scenario | Handler |
|---|---|
| Tavily returns empty results | Retry with broader query; if still empty return `status="error"` with queries logged |
| Methodology Agent produces invalid JSON | Pydantic validates; agent self-corrects and retries once before escalating |
| Daytona `SyntaxError` in simulation | Parse stdout, patch specific line, re-upload, retry (max 3) |
| Daytona `ImportError` in simulation | Add missing library to pip install command, rebuild, retry |
| Daytona fails 3 times | Cleanup sandbox; Supervisor escalates to user with full stderr in `st.error()` |
| Missing paper data (null fields) | Add to `extraction_notes[]`; Coder skips that step with a `# SKIPPED: {note}` comment |
| GitHub repo not found | Retry with `{author} {title} code github` query; flag in report if still missing |
| Sandbox not cleaned up | Always use `try/finally` — `cleanup()` is always called even on failure |

---

## Rules for All Agents

1. **Never hallucinate scientific values.** If a value is not in the source material, it is `null`.
2. **Never pass raw paper text between agents.** Save to file, pass the filename.
3. **Always validate output schema with Pydantic before returning to Supervisor.**
4. **Always log errors with the full stdout/stderr trace, not just "it failed."**
5. **Retry before escalating.** Every agent has internal `max_retries=3`.
6. **Cite sources.** Every factual claim in the final report traces back to a Tavily result URL.
7. **Always return the Agent Return Contract dict.** Supervisor depends on consistent structure.
8. **Always clean up Daytona sandboxes.** Use `try/finally`. No leaked sandboxes.

---

## Hackathon Demo Script

Walk judges through this sequence:
1. Paste a real biopaper link into the UI
2. Show Tavily scraping in real time (`st.status`)
3. Show the extracted JSON protocol appearing in the workspace
4. Show the Daytona sandbox spinning up
5. Show `opentrons_simulate` running and passing
6. Show the final Opentrons `.py` script — highlight that it came from a PDF, not a human
7. Switch to Dry Lab tab — show a reproducibility score on a known-broken paper