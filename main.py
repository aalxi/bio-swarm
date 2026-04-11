# main.py — Streamlit entry point

import os
import traceback
import uuid
from datetime import datetime

import streamlit as st
import streamlit.runtime as st_runtime
from dotenv import load_dotenv

if not st_runtime.exists():
    import sys

    print(
        "BioSwarm must be started with Streamlit, not plain Python:\n\n"
        "  streamlit run main.py\n",
        file=sys.stderr,
    )
    raise SystemExit(1)

st.set_page_config(
    page_title="BioSwarm",
    page_icon="⬡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

load_dotenv()

from agents.researcher import researcher_agent
from agents.methodology import methodology_agent
from agents.coder import coder_agent
from agents.synthesizer import synthesizer_agent
from schemas.state_schema import WorkspaceState
from tools.file_tool import save_json, load_json

# --- Startup: create workspace directories ---
WORKSPACE_DIRS = [
    "workspace",
    "workspace/raw_research",
    "workspace/extracted_protocols",
    "workspace/generated_code",
    "workspace/final_reports",
]
for d in WORKSPACE_DIRS:
    os.makedirs(d, exist_ok=True)

STATE_PATH = "workspace/state.json"

# ── CSS ──────────────────────────────────────────────────────────────────────

CSS_BLOCK = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;700&display=swap');

/* Global dark theme */
[data-testid="stApp"] {
    background-color: #0a0a0a;
    color: #e0e0e0;
    font-family: 'Inter', system-ui, sans-serif;
}
[data-testid="stMain"] {
    background-color: #0a0a0a;
}
[data-testid="stVerticalBlock"] > div {
    background-color: transparent;
}
[data-testid="stAppViewBlockContainer"] {
    padding-top: 2rem;
}
header[data-testid="stHeader"] {
    background-color: #0a0a0a;
    border-bottom: 1px solid #1a1a1a;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* Text area */
[data-testid="stTextArea"] textarea {
    background-color: #111111 !important;
    color: #e0e0e0 !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 4px !important;
    font-family: 'JetBrains Mono', 'Courier New', monospace !important;
    font-size: 13px !important;
    caret-color: #00ff88;
    resize: vertical;
}
[data-testid="stTextArea"] textarea:focus {
    border-color: #00ff88 !important;
    box-shadow: 0 0 0 1px rgba(0, 255, 136, 0.25) !important;
}
[data-testid="stTextArea"] label {
    color: #555555 !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
[data-testid="stTextArea"] textarea::placeholder {
    color: #333333 !important;
}

/* Expander */
[data-testid="stExpander"] {
    background-color: #0d0d0d !important;
    border: 1px solid #1e1e1e !important;
    border-radius: 4px !important;
}
[data-testid="stExpander"] summary {
    color: #555555 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 11px !important;
}

/* Hide st.status() widgets — we replace with custom terminal panels */
[data-testid="stStatusWidget"] { display: none !important; }

/* Download button */
[data-testid="stDownloadButton"] > button {
    background-color: transparent !important;
    color: #00ff88 !important;
    border: 1px solid #00ff88 !important;
    border-radius: 3px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    padding: 8px 20px !important;
    letter-spacing: 0.05em;
    transition: background-color 0.15s ease, color 0.15s ease;
    width: auto !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #00ff88 !important;
    color: #0a0a0a !important;
}

/* Page title */
.bio-title {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 2.4rem;
    font-weight: 700;
    color: #00ff88;
    letter-spacing: -0.03em;
    margin-bottom: 0;
    line-height: 1;
}
.bio-subtitle {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.7rem;
    color: #333333;
    margin-top: 6px;
    margin-bottom: 32px;
    letter-spacing: 0.14em;
}

/* Mode toggle label */
.mode-toggle-label {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 11px;
    color: #444444;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 6px;
}

/* Terminal panels */
.terminal-panel {
    background-color: #0d0d0d;
    border: 1px solid #1e1e1e;
    border-left: 3px solid #00ff88;
    border-radius: 4px;
    padding: 16px 20px;
    margin: 8px 0;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.75;
    overflow-x: auto;
}
.terminal-panel.running {
    border-left-color: #ffaa00;
}
.terminal-panel.error {
    border-left-color: #ff4444;
}
.terminal-header {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 10px;
    font-weight: 700;
    color: #444444;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid #1a1a1a;
}
.terminal-line {
    color: #999999;
    margin: 1px 0;
    white-space: pre-wrap;
    word-break: break-word;
}
.terminal-line.success { color: #00ff88; }
.terminal-line.error   { color: #ff5555; }
.terminal-line.warn    { color: #ffaa00; }
.terminal-line.dim     { color: #383838; }
.terminal-cursor {
    display: inline-block;
    width: 8px;
    height: 13px;
    background-color: #ffaa00;
    margin-left: 2px;
    vertical-align: middle;
    animation: cur-blink 1s step-end infinite;
}
@keyframes cur-blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
}

/* Handoff message */
.handoff-msg {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 11px;
    color: #2a5e3a;
    text-align: center;
    padding: 6px 0 4px 0;
    letter-spacing: 0.04em;
}

/* Pipeline complete banner */
.pipeline-complete {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.9rem;
    font-weight: 700;
    color: #00ff88;
    text-align: center;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    padding: 20px 0 10px 0;
    border-top: 1px solid #1a1a1a;
    margin-top: 20px;
}
.report-section-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: #333333;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin-top: 18px;
    margin-bottom: 6px;
}
</style>
"""

# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _esc(text: str) -> str:
    """Minimal HTML escaping for terminal panel content."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _terminal_panel(
    agent_name: str,
    lines: list,
    state: str = "success",
) -> str:
    """
    Build a terminal panel HTML string.
    lines: list of (css_class, text) tuples.
    state: 'success' | 'error' | 'running'
    """
    panel_cls = f"terminal-panel {state}"
    rows = ""
    for css_cls, text in lines:
        cls = f"terminal-line {css_cls}".strip()
        rows += f'<div class="{cls}">{_esc(text)}</div>\n'
    cursor = '<span class="terminal-cursor"></span>' if state == "running" else ""
    return (
        f'<div class="{panel_cls}">'
        f'<div class="terminal-header">{_esc(agent_name)}</div>'
        f"{rows}{cursor}"
        f"</div>"
    )


def _handoff_msg(n_files: int, to_agent: str) -> str:
    return (
        f'<div class="handoff-msg">'
        f"&gt;&gt; passing {n_files} file(s) ──&gt; {_esc(to_agent)}"
        f"</div>"
    )


# ── UI ───────────────────────────────────────────────────────────────────────

st.markdown(CSS_BLOCK, unsafe_allow_html=True)

# Session state defaults
if "mode" not in st.session_state:
    st.session_state["mode"] = "Wet Lab"

# Header
st.markdown(
    '<div class="bio-title">BIOSWARM</div>'
    '<div class="bio-subtitle">// MULTI-AGENT AI SYSTEM FOR BIOLOGICAL REPRODUCIBILITY</div>',
    unsafe_allow_html=True,
)

# Mode toggle
st.markdown('<div class="mode-toggle-label">Pipeline Mode</div>', unsafe_allow_html=True)
_sp1, _col_wet, _col_dry, _sp2 = st.columns([1, 2, 2, 1])
with _col_wet:
    wet_type = "primary" if st.session_state["mode"] == "Wet Lab" else "secondary"
    if st.button("🧪  Wet Lab", key="btn_wet", use_container_width=True, type=wet_type):
        st.session_state["mode"] = "Wet Lab"
        st.rerun()
with _col_dry:
    dry_type = "primary" if st.session_state["mode"] == "Dry Lab" else "secondary"
    if st.button("💻  Dry Lab", key="btn_dry", use_container_width=True, type=dry_type):
        st.session_state["mode"] = "Dry Lab"
        st.rerun()

mode = st.session_state["mode"]

st.markdown("<br>", unsafe_allow_html=True)

# Input
user_input = st.text_area(
    "Input",
    placeholder="Paste a paper title, DOI, URL, or protocol description...",
    height=110,
    label_visibility="collapsed",
)

# Centered run button
_rl, _rc, _rr = st.columns([2, 3, 2])
with _rc:
    run_clicked = st.button("[ RUN BIOSWARM ]", use_container_width=True, key="run_btn")

# ── Pipeline ─────────────────────────────────────────────────────────────────

if run_clicked and user_input.strip():
    task_id = str(uuid.uuid4())[:8]
    mode_key = "wet_lab" if mode == "Wet Lab" else "dry_lab"

    # Initialize pipeline state
    state = WorkspaceState(
        task_id=task_id, mode=mode_key, user_input=user_input, status="research"
    )
    save_json(state.model_dump(), STATE_PATH)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 1. Researcher Agent ────────────────────────────────────────────────

    ts = _now()
    ph_researcher = st.empty()
    ph_researcher.markdown(
        _terminal_panel(
            "RESEARCHER AGENT",
            [
                ("dim", f"> [{ts}]  task: {task_id}  |  mode: {mode_key}"),
                ("dim", f"> [{ts}]  initializing researcher agent..."),
                ("",    f"> [{ts}]  planning Tavily web search queries via GPT-5.4..."),
            ],
            "running",
        ),
        unsafe_allow_html=True,
    )

    try:
        researcher_result = researcher_agent(user_input, mode_key, task_id)
    except Exception:
        tb = traceback.format_exc()
        ts = _now()
        ph_researcher.markdown(
            _terminal_panel(
                "RESEARCHER AGENT",
                [
                    ("dim",   f"> [{ts}]  initializing researcher agent..."),
                    ("error", f"> [{ts}]  UNHANDLED EXCEPTION:"),
                    ("error", f"> [{ts}]  {tb[:1500]}"),
                    ("error", f"> [{ts}]  status: CRASHED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append("Researcher agent crashed")
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    ts = _now()
    if researcher_result["status"] == "error":
        ph_researcher.markdown(
            _terminal_panel(
                "RESEARCHER AGENT",
                [
                    ("dim",   f"> [{ts}]  executing Tavily web searches..."),
                    ("error", f"> [{ts}]  ERROR: {researcher_result.get('message', 'Unknown error')}"),
                    ("dim",   f"> [{ts}]  retries: {researcher_result.get('retry_count', 0)}"),
                    ("error", f"> [{ts}]  status: FAILED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append(researcher_result["message"])
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    n_research_files = len(researcher_result["output_files"])
    ph_researcher.markdown(
        _terminal_panel(
            "RESEARCHER AGENT",
            [
                ("dim",     f"> [{ts}]  task: {task_id}  |  mode: {mode_key}"),
                ("",        f"> [{ts}]  web search queries executed via Tavily"),
                ("",        f"> [{ts}]  {researcher_result.get('message', 'Research complete')}"),
                ("success", f"> [{ts}]  {n_research_files} file(s) saved to workspace/raw_research/"),
                ("dim",     f"> [{ts}]  retries: {researcher_result.get('retry_count', 0)}"),
                ("success", f"> [{ts}]  status: SUCCESS"),
            ],
            "success",
        ),
        unsafe_allow_html=True,
    )
    state.research.done = True
    state.research.files = researcher_result["output_files"]
    state.status = "extraction"
    save_json(state.model_dump(), STATE_PATH)

    st.markdown(
        _handoff_msg(n_research_files, "METHODOLOGY AGENT"),
        unsafe_allow_html=True,
    )

    # ── 2. Methodology Agent ───────────────────────────────────────────────

    ts = _now()
    ph_methodology = st.empty()
    ph_methodology.markdown(
        _terminal_panel(
            "METHODOLOGY AGENT",
            [
                ("dim", f"> [{ts}]  receiving {n_research_files} research file(s) from researcher"),
                ("dim", f"> [{ts}]  initializing methodology agent..."),
                ("",    f"> [{ts}]  chunking and preparing research content..."),
            ],
            "running",
        ),
        unsafe_allow_html=True,
    )

    try:
        methodology_result = methodology_agent(researcher_result, task_id)
    except Exception:
        tb = traceback.format_exc()
        ts = _now()
        ph_methodology.markdown(
            _terminal_panel(
                "METHODOLOGY AGENT",
                [
                    ("dim",   f"> [{ts}]  chunking research content..."),
                    ("error", f"> [{ts}]  UNHANDLED EXCEPTION:"),
                    ("error", f"> [{ts}]  {tb[:1500]}"),
                    ("error", f"> [{ts}]  status: CRASHED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append("Methodology agent crashed")
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    ts = _now()
    if methodology_result["status"] == "error":
        retry = methodology_result.get("retry_count", 0)
        ph_methodology.markdown(
            _terminal_panel(
                "METHODOLOGY AGENT",
                [
                    ("",      f"> [{ts}]  running LLM extraction (GPT-5.4)..."),
                    ("warn",  f"> [{ts}]  schema fix retry: {retry} attempt(s)") if retry > 0 else
                    ("dim",   f"> [{ts}]  no retry performed"),
                    ("error", f"> [{ts}]  ERROR: {methodology_result.get('message', 'Unknown error')}"),
                    ("error", f"> [{ts}]  status: FAILED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append(methodology_result["message"])
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    protocol_file = methodology_result["output_files"][0] if methodology_result["output_files"] else "N/A"
    meth_retry = methodology_result.get("retry_count", 0)
    meth_lines = [
        ("dim",     f"> [{ts}]  receiving {n_research_files} research file(s)"),
        ("",        f"> [{ts}]  calling GPT-5.4 for structured extraction..."),
        ("",        f"> [{ts}]  validating output against Pydantic schema..."),
    ]
    if meth_retry > 0:
        meth_lines.append(("warn", f"> [{ts}]  schema validation retry: {meth_retry} attempt(s)"))
    meth_lines += [
        ("success", f"> [{ts}]  schema validation: PASSED"),
        ("success", f"> [{ts}]  protocol saved to {protocol_file}"),
        ("success", f"> [{ts}]  status: SUCCESS"),
    ]
    ph_methodology.markdown(
        _terminal_panel("METHODOLOGY AGENT", meth_lines, "success"),
        unsafe_allow_html=True,
    )
    state.extraction.done = True
    state.extraction.protocol_file = methodology_result["output_files"][0]
    state.extraction.schema_valid = True
    state.status = "coding"
    save_json(state.model_dump(), STATE_PATH)

    st.markdown(
        _handoff_msg(len(methodology_result["output_files"]), "CODER AGENT"),
        unsafe_allow_html=True,
    )

    # ── 3. Coder Agent ─────────────────────────────────────────────────────

    ts = _now()
    ph_coder = st.empty()
    ph_coder.markdown(
        _terminal_panel(
            "CODER AGENT",
            [
                ("dim", f"> [{ts}]  protocol file: protocol_{task_id}.json"),
                ("dim", f"> [{ts}]  initializing coder agent..."),
                ("",    f"> [{ts}]  generating Opentrons script via GPT-5.4..."),
                ("",    f"> [{ts}]  spawning Daytona sandbox..."),
            ],
            "running",
        ),
        unsafe_allow_html=True,
    )

    try:
        coder_result = coder_agent(methodology_result, mode_key, task_id)
    except Exception:
        tb = traceback.format_exc()
        ts = _now()
        ph_coder.markdown(
            _terminal_panel(
                "CODER AGENT",
                [
                    ("dim",   f"> [{ts}]  spawning Daytona sandbox..."),
                    ("error", f"> [{ts}]  UNHANDLED EXCEPTION:"),
                    ("error", f"> [{ts}]  {tb[:1500]}"),
                    ("error", f"> [{ts}]  status: CRASHED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append("Coder agent crashed")
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    ts = _now()
    if coder_result["status"] == "error":
        retry = coder_result.get("retry_count", 0)
        state.coding.error_log = coder_result.get("error_detail")
        state.coding.retry_count = retry
        state.errors.append(coder_result["message"])
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        ph_coder.markdown(
            _terminal_panel(
                "CODER AGENT",
                [
                    ("",      f"> [{ts}]  sandbox created, uploading protocol.py..."),
                    ("",      f"> [{ts}]  running opentrons_simulate..."),
                    ("warn",  f"> [{ts}]  simulation failed — attempted {retry} LLM fix(es)"),
                    ("error", f"> [{ts}]  ERROR: {coder_result.get('message', 'Unknown error')}"),
                    ("dim",   f"> [{ts}]  sandbox cleaned up"),
                    ("error", f"> [{ts}]  status: FAILED after {retry} retries"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        st.stop()

    coder_retry = coder_result.get("retry_count", 0)
    script_file = coder_result["output_files"][0] if coder_result["output_files"] else "N/A"
    coder_lines = [
        ("dim",     f"> [{ts}]  protocol_{task_id}.json loaded and validated"),
        ("",        f"> [{ts}]  GPT-5.4 script generation complete"),
        ("",        f"> [{ts}]  Daytona sandbox created, installing opentrons..."),
        ("",        f"> [{ts}]  uploading protocol.py, running opentrons_simulate..."),
    ]
    if coder_retry > 0:
        coder_lines.append(("warn", f"> [{ts}]  simulation fix applied: {coder_retry} retry attempt(s)"))
    else:
        coder_lines.append(("dim", f"> [{ts}]  opentrons_simulate passed on first attempt"))
    coder_lines += [
        ("success", f"> [{ts}]  simulation: PASSED"),
        ("success", f"> [{ts}]  script saved to {script_file}"),
        ("dim",     f"> [{ts}]  sandbox cleaned up"),
        ("success", f"> [{ts}]  status: SUCCESS"),
    ]
    ph_coder.markdown(
        _terminal_panel("CODER AGENT", coder_lines, "success"),
        unsafe_allow_html=True,
    )
    state.coding.done = True
    state.coding.script_file = coder_result["output_files"][0]
    state.coding.simulation_passed = True
    state.status = "synthesis"
    save_json(state.model_dump(), STATE_PATH)

    st.markdown(
        _handoff_msg(len(coder_result["output_files"]), "SYNTHESIZER AGENT"),
        unsafe_allow_html=True,
    )

    # ── 4. Synthesizer Agent ───────────────────────────────────────────────

    ts = _now()
    ph_synth = st.empty()
    ph_synth.markdown(
        _terminal_panel(
            "SYNTHESIZER AGENT",
            [
                ("dim", f"> [{ts}]  task {task_id} complete — compiling artifacts"),
                ("dim", f"> [{ts}]  initializing synthesizer agent..."),
                ("",    f"> [{ts}]  reading workspace artifacts and state.json..."),
            ],
            "running",
        ),
        unsafe_allow_html=True,
    )

    try:
        synth_result = synthesizer_agent(task_id)
    except Exception:
        tb = traceback.format_exc()
        ts = _now()
        ph_synth.markdown(
            _terminal_panel(
                "SYNTHESIZER AGENT",
                [
                    ("dim",   f"> [{ts}]  reading workspace artifacts..."),
                    ("error", f"> [{ts}]  UNHANDLED EXCEPTION:"),
                    ("error", f"> [{ts}]  {tb[:1500]}"),
                    ("error", f"> [{ts}]  status: CRASHED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append("Synthesizer agent crashed")
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    ts = _now()
    if synth_result["status"] == "error":
        ph_synth.markdown(
            _terminal_panel(
                "SYNTHESIZER AGENT",
                [
                    ("",      f"> [{ts}]  loading workspace files..."),
                    ("error", f"> [{ts}]  ERROR: {synth_result.get('message', 'Unknown error')}"),
                    ("error", f"> [{ts}]  status: FAILED"),
                ],
                "error",
            ),
            unsafe_allow_html=True,
        )
        state.errors.append(synth_result["message"])
        state.status = "error"
        save_json(state.model_dump(), STATE_PATH)
        st.stop()

    report_file = synth_result["output_files"][0] if synth_result["output_files"] else "N/A"
    ph_synth.markdown(
        _terminal_panel(
            "SYNTHESIZER AGENT",
            [
                ("dim",     f"> [{ts}]  loading state.json, protocol JSON, code artifacts"),
                ("",        f"> [{ts}]  calling GPT-5.4 to generate final Markdown report..."),
                ("success", f"> [{ts}]  report written to {report_file}"),
                ("success", f"> [{ts}]  status: SUCCESS"),
            ],
            "success",
        ),
        unsafe_allow_html=True,
    )
    state.synthesis.done = True
    state.synthesis.report_file = synth_result["output_files"][0]
    state.status = "complete"
    save_json(state.model_dump(), STATE_PATH)

    # ── Results ────────────────────────────────────────────────────────────

    st.markdown(
        '<div class="pipeline-complete">// PIPELINE COMPLETE //</div>',
        unsafe_allow_html=True,
    )

    with st.expander("// PIPELINE STATE (state.json)"):
        st.json(load_json(STATE_PATH))

    st.markdown(
        '<div class="report-section-label">// FINAL REPORT</div>',
        unsafe_allow_html=True,
    )
    report = open(f"workspace/final_reports/report_{task_id}.md").read()
    st.markdown(report)

    if mode == "Wet Lab":
        script = open(f"workspace/generated_code/protocol_{task_id}.py").read()
        st.download_button(
            "[ DOWNLOAD OPENTRONS SCRIPT .py ]",
            script,
            f"protocol_{task_id}.py",
            "text/plain",
        )
    else:
        st.download_button(
            "[ DOWNLOAD REPRODUCIBILITY REPORT .md ]",
            report,
            f"report_{task_id}.md",
            "text/markdown",
        )
