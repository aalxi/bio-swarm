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
from agents.enricher import enricher_agent
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500&family=JetBrains+Mono:wght@400&display=swap');

/* ──────────────────────────────────────────────────────────────────────────
   Warp-inspired warm dark palette.
   No bold accents, no animated gradients, no glow effects.
   Depth comes from semi-transparent borders and warm parchment text.
   ────────────────────────────────────────────────────────────────────────── */
:root {
    /* Backgrounds — warm earthy near-black, never pure #000 */
    --bg:           #0e0d0c;
    --surface:      #161513;
    --surface-2:    rgba(255, 255, 255, 0.04);

    /* Text — warm parchment family, never pure white */
    --text:         #faf9f6;   /* Warm Parchment — primary text */
    --text-body:    #afaeac;   /* Ash Gray — body / readable secondary */
    --text-muted:   #868584;   /* Stone Gray — labels, subdued */
    --text-dim:     #5a5856;   /* Deeper muted — timestamps, paths */

    /* Borders & buttons — Earth Gray family */
    --border:       rgba(227, 227, 227, 0.12);
    --border-soft:  rgba(227, 227, 227, 0.06);
    --btn-bg:       #353534;   /* Earth Gray pill */
    --btn-text:     #afaeac;

    /* Status — warm muted, NOT bright primaries */
    --status-running: #c9a66b;   /* warm amber, dim */
    --status-error:   #b86a5e;   /* warm terracotta */
}

html { font-size: 17px; }

[data-testid="stApp"] {
    background-color: var(--bg);
    color: var(--text-body);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-weight: 400;
    -webkit-font-smoothing: antialiased;
}
[data-testid="stMain"] { background-color: var(--bg); }
[data-testid="stVerticalBlock"] > div { background-color: transparent; }

/* Editorial container — generous padding for contemplative pacing */
[data-testid="stAppViewBlockContainer"] {
    max-width: 920px !important;
    padding-top: 5rem;
    padding-bottom: 6rem;
    padding-left: 2.5rem !important;
    padding-right: 2.5rem !important;
}

header[data-testid="stHeader"] {
    background-color: var(--bg);
    border-bottom: none;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* ── Title — Matter-style display: large, weight 400, tight negative tracking ── */
.bio-title {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 4.5rem;
    font-weight: 400;          /* Warp uses Regular even for hero */
    letter-spacing: -0.045em;  /* equiv. to -2.4px at 80px */
    line-height: 1.0;
    color: var(--text);        /* warm parchment, not gradient */
    margin-bottom: 0;
}

.bio-subtitle {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.72rem;
    font-weight: 400;
    color: var(--text-muted);
    margin-top: 14px;
    margin-bottom: 56px;
    letter-spacing: 0.18em;    /* uppercase editorial label */
    text-transform: uppercase;
}

/* ── Mode toggle — restrained pill, no glow ── */
.toggle-wrap {
    display: flex;
    align-items: center;
    gap: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 50px;       /* full pill */
    padding: 5px;
    width: fit-content;
    position: relative;
    margin: 0 auto 36px auto;
    user-select: none;
}
.toggle-track {
    position: absolute;
    top: 5px;
    left: 5px;
    width: calc(50% - 5px);
    height: calc(100% - 10px);
    background: var(--btn-bg);
    border-radius: 50px;
    transition: transform 0.45s cubic-bezier(0.4, 0, 0.2, 1);
    pointer-events: none;
}
.toggle-track.right { transform: translateX(100%); }

.toggle-btn {
    position: relative;
    z-index: 1;
    padding: 10px 32px;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.82rem;
    font-weight: 500;          /* Matter Medium for button text */
    letter-spacing: 0;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 50px;
    min-width: 130px;
    text-align: center;
    transition: color 0.3s ease;
    border: none;
    background: transparent;
    outline: none;
}
.toggle-btn.active { color: var(--text); }

/* ── Text area — warm dark surface, parchment text ── */
[data-testid="stTextArea"] textarea {
    background-color: var(--surface) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.95rem !important;
    font-weight: 400 !important;
    letter-spacing: -0.005em !important;
    caret-color: var(--text);
    resize: vertical;
    padding: 18px 20px !important;
    line-height: 1.5 !important;
    transition: border-color 0.2s ease;
}
[data-testid="stTextArea"] textarea:focus {
    border-color: rgba(227, 227, 227, 0.28) !important;
    box-shadow: none !important;
}
[data-testid="stTextArea"] textarea::placeholder {
    color: var(--text-dim) !important;
}
[data-testid="stTextArea"] label { display: none !important; }

/* ── Run button — Earth Gray pill, restrained CTA ── */
div:has(> button[key="run_btn"]) button {
    background: var(--btn-bg) !important;
    color: var(--btn-text) !important;
    border: 1px solid var(--border-soft) !important;
    border-radius: 50px !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    padding: 14px 0 !important;
    transition: background 0.2s ease;
    box-shadow: none !important;
}
div:has(> button[key="run_btn"]) button:hover {
    background: #404040 !important;
    border-color: var(--border) !important;
    box-shadow: none !important;
}

/* ── Expander — restrained, warm border ── */
[data-testid="stExpander"] {
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}
[data-testid="stExpander"] summary {
    color: var(--text-muted) !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 400 !important;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    padding: 14px 18px !important;
}

/* Hide native status widget */
[data-testid="stStatusWidget"] { display: none !important; }

/* ── Download button — pill, restrained ── */
[data-testid="stDownloadButton"] > button {
    background-color: var(--btn-bg) !important;
    color: var(--btn-text) !important;
    border: 1px solid var(--border-soft) !important;
    border-radius: 50px !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    padding: 12px 28px !important;
    transition: background 0.2s ease;
    width: auto !important;
    box-shadow: none !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #404040 !important;
    box-shadow: none !important;
}

/* ──────────────────────────────────────────────────────────────────────────
   Terminal panels — kept monospace (they're agent telemetry logs), but
   reframed in the warm palette. No bright green, no orange cursors.
   ────────────────────────────────────────────────────────────────────────── */
.terminal-panel {
    background-color: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 26px;
    margin: 12px 0;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.78rem;
    font-weight: 400;
    line-height: 1.75;
    overflow-x: auto;
}
.terminal-panel.running { border-color: rgba(201, 166, 107, 0.35); }
.terminal-panel.error   { border-color: rgba(184, 106, 94, 0.35); }

.terminal-header {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.65rem;
    font-weight: 400;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.24em;    /* wide editorial tracking */
    margin-bottom: 14px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border-soft);
}
.terminal-line {
    color: var(--text-body);
    margin: 2px 0;
    white-space: pre-wrap;
    word-break: break-word;
}
.terminal-line.success { color: var(--text); }              /* parchment for success */
.terminal-line.error   { color: var(--status-error); }
.terminal-line.warn    { color: var(--status-running); }
.terminal-line.dim     { color: var(--text-dim); }

.terminal-cursor {
    display: inline-block;
    width: 7px;
    height: 12px;
    background-color: var(--text-muted);
    margin-left: 4px;
    vertical-align: middle;
    animation: cur-blink 1.2s step-end infinite;
}
@keyframes cur-blink {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 0; }
}

/* ── Handoff — uppercase editorial micro-label ── */
.handoff-msg {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.65rem;
    font-weight: 400;
    color: var(--text-dim);
    text-align: center;
    padding: 14px 0 10px 0;
    letter-spacing: 0.24em;
    text-transform: uppercase;
}

/* ── Pipeline complete — flat parchment, no animated gradient ── */
.pipeline-complete {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--text);
    text-align: center;
    letter-spacing: 0.32em;
    text-transform: uppercase;
    padding: 36px 0 16px 0;
    border-top: 1px solid var(--border-soft);
    margin-top: 32px;
}
.report-section-label {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.65rem;
    font-weight: 400;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.24em;
    margin-top: 28px;
    margin-bottom: 16px;
}

/* ── Markdown report — warm parchment headings, ash gray body ── */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    font-weight: 400;
    letter-spacing: -0.015em;
}
.stMarkdown h1 { font-size: 2.4rem; line-height: 1.15; }
.stMarkdown h2 { font-size: 1.75rem; line-height: 1.2; }
.stMarkdown h3 { font-size: 1.3rem; line-height: 1.25; }
.stMarkdown p, .stMarkdown li {
    color: var(--text-body);
    font-size: 1.05rem;
    line-height: 1.55;
}
.stMarkdown a { color: var(--text); text-decoration: underline; }
.stMarkdown code {
    font-family: 'JetBrains Mono', monospace;
    background: var(--surface-2);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.88em;
    color: var(--text);
}
.stMarkdown pre {
    background: var(--surface) !important;
    border: 1px solid var(--border-soft);
    border-radius: 8px;
    padding: 16px !important;
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
        f"Passing {n_files} file(s) &nbsp;&middot;&nbsp; {_esc(to_agent)}"
        f"</div>"
    )


# ── UI ───────────────────────────────────────────────────────────────────────

st.markdown(CSS_BLOCK, unsafe_allow_html=True)

# Session state defaults
if "mode" not in st.session_state:
    st.session_state["mode"] = "Wet Lab"

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="bio-title">BioSwarm</div>'
    '<div class="bio-subtitle">Multi-agent AI for biological reproducibility</div>',
    unsafe_allow_html=True,
)

# ── Custom physics toggle ─────────────────────────────────────────────────────
_wet_active = "active" if st.session_state["mode"] == "Wet Lab" else ""
_dry_active  = "active" if st.session_state["mode"] == "Dry Lab"  else ""
_track_right = "right"  if st.session_state["mode"] == "Dry Lab"  else ""

st.markdown(
    f"""
    <div class="toggle-wrap" id="bio-toggle">
      <div class="toggle-track {_track_right}" id="toggle-track"></div>
      <button class="toggle-btn {_wet_active}" id="tbtn-wet" onclick="toggleMode('Wet Lab')">Wet Lab</button>
      <button class="toggle-btn {_dry_active}"  id="tbtn-dry"  onclick="toggleMode('Dry Lab')">Dry Lab</button>
    </div>
    """,
    unsafe_allow_html=True,
)

# Zero-height container — Streamlit buttons needed so JS can click them for rerun.
# Collapsed to 0px via inline style; columns prevent them affecting layout.
st.markdown('<div style="height:0;overflow:hidden;position:absolute;pointer-events:none;opacity:0">', unsafe_allow_html=True)
_hc1, _hc2 = st.columns(2)
with _hc1:
    if st.button("Wet Lab", key="btn_wet"):
        st.session_state["mode"] = "Wet Lab"
        st.rerun()
with _hc2:
    if st.button("Dry Lab", key="btn_dry"):
        st.session_state["mode"] = "Dry Lab"
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

mode = st.session_state["mode"]

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# Input
user_input = st.text_area(
    "Input",
    placeholder="Paste a paper title, DOI, URL, or protocol description...",
    height=130,
    label_visibility="collapsed",
)

# Centered run button
_rl, _rc, _rr = st.columns([2, 3, 2])
with _rc:
    run_clicked = st.button("Run BioSwarm", use_container_width=True, key="run_btn")

# ── JavaScript: mode toggle ───────────────────────────────────────────────────
st.markdown("""
<script>
(function () {
  /* Mode toggle — clicks a hidden Streamlit button to trigger a Python rerun. */
  window.toggleMode = function (mode) {
    var track  = document.getElementById('toggle-track');
    var btnWet = document.getElementById('tbtn-wet');
    var btnDry = document.getElementById('tbtn-dry');
    if (!track) return;

    if (mode === 'Wet Lab') {
      track.classList.remove('right');
      btnWet.classList.add('active');
      btnDry.classList.remove('active');
    } else {
      track.classList.add('right');
      btnDry.classList.add('active');
      btnWet.classList.remove('active');
    }

    var label = (mode === 'Wet Lab') ? 'Wet Lab' : 'Dry Lab';
    var allBtns = document.querySelectorAll('button[kind="secondary"]');
    for (var i = 0; i < allBtns.length; i++) {
      if (allBtns[i].innerText.trim() === label) {
        allBtns[i].click();
        break;
      }
    }
  };
})();
</script>
""", unsafe_allow_html=True)

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
                ("",    f"> [{ts}]  planning Tavily web search queries via GPT-5.4 mini..."),
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
                    ("",      f"> [{ts}]  running LLM extraction (GPT-5.4 mini)..."),
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
        ("",        f"> [{ts}]  calling GPT-5.4 mini for structured extraction..."),
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
    state.status = "enrichment" if mode_key == "wet_lab" else "coding"
    save_json(state.model_dump(), STATE_PATH)

    # ── 2b. PIE Agent (wet-lab only, non-blocking) ─────────────────────────

    if mode_key == "wet_lab":
        st.markdown(
            _handoff_msg(len(methodology_result["output_files"]), "PIE AGENT"),
            unsafe_allow_html=True,
        )

        ts = _now()
        ph_enricher = st.empty()
        ph_enricher.markdown(
            _terminal_panel(
                "PIE AGENT",
                [
                    ("dim", f"> [{ts}]  reading protocol_{task_id}.json from methodology agent"),
                    ("dim", f"> [{ts}]  running gap analysis..."),
                ],
            ),
            unsafe_allow_html=True,
        )

        try:
            enricher_result = enricher_agent(methodology_result, task_id)
        except Exception:
            tb = traceback.format_exc()
            ts = _now()
            enricher_result = {
                "status": "error",
                "message": "Unhandled exception in PIE agent",
                "output_files": [],
                "retry_count": 0,
                "error_detail": tb,
                "gaps_filled": 0,
            }

        ts = _now()
        if enricher_result["status"] == "success":
            gaps_identified = 0
            gaps_filled = enricher_result.get("gaps_filled", 0)
            elog = enricher_result.get("enrichment_log") or {}
            if not elog:
                # Read from the protocol file if enrichment_log wasn't forwarded
                try:
                    _proto = load_json(f"workspace/extracted_protocols/protocol_{task_id}.json")
                    elog = _proto.get("enrichment_log") or {}
                except Exception:
                    pass
            gaps_identified = elog.get("gaps_identified", gaps_filled)
            conflicts = elog.get("conflicts", [])

            pie_lines = [
                ("dim",     f"> [{ts}]  reading protocol_{task_id}.json from methodology agent"),
                ("",        f"> [{ts}]  gap analysis: {gaps_identified} critical null fields found"),
                ("",        f"> [{ts}]  executing {elog.get('tavily_queries_executed', 0)} targeted Tavily searches..."),
            ]
            if conflicts:
                pie_lines.append(("warn", f"> [{ts}]  {len(conflicts)} conflicting value(s) found — not applied"))
            pie_lines += [
                ("success", f"> [{ts}]  {gaps_filled}/{gaps_identified} fields enriched (confidence ≥ 0.7)"),
                ("success", f"> [{ts}]  enriched protocol saved → protocol_{task_id}.json"),
                ("dim",     f"> [{ts}]  audit log → enrichment_{task_id}.json"),
                ("success", f"> [{ts}]  status: SUCCESS"),
            ]
            ph_enricher.markdown(
                _terminal_panel("PIE AGENT", pie_lines, "success"),
                unsafe_allow_html=True,
            )
            state.enrichment.done = True
            state.enrichment.gaps_identified = gaps_identified
            state.enrichment.gaps_filled = gaps_filled
            if len(enricher_result["output_files"]) > 1:
                state.enrichment.enrichment_file = enricher_result["output_files"][1]
        else:
            pie_lines = [
                ("warn", f"> [{ts}]  PIE encountered an error — continuing with sparse protocol"),
                ("dim",  f"> [{ts}]  {enricher_result.get('message', 'Unknown error')}"),
                ("warn", f"> [{ts}]  status: SKIPPED (pipeline continues)"),
            ]
            ph_enricher.markdown(
                _terminal_panel("PIE AGENT", pie_lines, "running"),
                unsafe_allow_html=True,
            )
            state.enrichment.skipped = True
            state.errors.append(
                f"[enrichment] {enricher_result.get('message', 'PIE failed')} — pipeline continues"
            )

        state.status = "coding"
        save_json(state.model_dump(), STATE_PATH)

    st.markdown(
        _handoff_msg(len(methodology_result["output_files"]), "CODER AGENT"),
        unsafe_allow_html=True,
    )

    # ── 3. Coder Agent ─────────────────────────────────────────────────────

    ts = _now()
    ph_coder = st.empty()
    if mode_key == "wet_lab":
        _coder_running_lines = [
            ("dim", f"> [{ts}]  protocol file: protocol_{task_id}.json"),
            ("dim", f"> [{ts}]  initializing coder agent..."),
            ("",    f"> [{ts}]  generating Opentrons script via GPT-5.4 mini..."),
            ("",    f"> [{ts}]  spawning Daytona sandbox..."),
        ]
    else:
        _coder_running_lines = [
            ("dim", f"> [{ts}]  protocol file: protocol_{task_id}.json"),
            ("dim", f"> [{ts}]  initializing coder agent..."),
            ("",    f"> [{ts}]  cloning GitHub repo into sandbox..."),
            ("",    f"> [{ts}]  installing dependencies..."),
        ]
    ph_coder.markdown(
        _terminal_panel("CODER AGENT", _coder_running_lines, "running"),
        unsafe_allow_html=True,
    )

    try:
        coder_result = coder_agent(methodology_result, mode_key, task_id)
    except Exception:
        tb = traceback.format_exc()
        ts = _now()
        _crash_context = "spawning Daytona sandbox..." if mode_key == "wet_lab" else "running in sandbox..."
        ph_coder.markdown(
            _terminal_panel(
                "CODER AGENT",
                [
                    ("dim",   f"> [{ts}]  {_crash_context}"),
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
        if mode_key == "wet_lab":
            _coder_err_lines = [
                ("",      f"> [{ts}]  sandbox created, uploading protocol.py..."),
                ("",      f"> [{ts}]  running opentrons_simulate..."),
                ("warn",  f"> [{ts}]  simulation failed — attempted {retry} LLM fix(es)"),
                ("error", f"> [{ts}]  ERROR: {coder_result.get('message', 'Unknown error')}"),
                ("dim",   f"> [{ts}]  sandbox cleaned up"),
                ("error", f"> [{ts}]  status: FAILED after {retry} retries"),
            ]
        else:
            _coder_err_lines = [
                ("",      f"> [{ts}]  repo cloned, installing dependencies..."),
                ("",      f"> [{ts}]  running entry point..."),
                ("warn",  f"> [{ts}]  execution failed"),
                ("error", f"> [{ts}]  ERROR: {coder_result.get('message', 'Unknown error')}"),
                ("dim",   f"> [{ts}]  sandbox cleaned up"),
                ("error", f"> [{ts}]  status: FAILED"),
            ]
        ph_coder.markdown(
            _terminal_panel("CODER AGENT", _coder_err_lines, "error"),
            unsafe_allow_html=True,
        )
        st.stop()

    coder_retry = coder_result.get("retry_count", 0)
    script_file = coder_result["output_files"][0] if coder_result["output_files"] else "N/A"
    if mode_key == "wet_lab":
        coder_lines = [
            ("dim",     f"> [{ts}]  protocol_{task_id}.json loaded and validated"),
            ("",        f"> [{ts}]  GPT-5.4 mini script generation complete"),
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
    else:
        coder_lines = [
            ("dim",     f"> [{ts}]  protocol_{task_id}.json loaded and validated"),
            ("",        f"> [{ts}]  GitHub repo cloned into sandbox"),
            ("",        f"> [{ts}]  dependencies installed"),
            ("",        f"> [{ts}]  entry point executed"),
        ]
        if coder_retry > 0:
            coder_lines.append(("warn", f"> [{ts}]  execution required {coder_retry} retry attempt(s)"))
        else:
            coder_lines.append(("dim", f"> [{ts}]  entry point passed on first attempt"))
        coder_lines += [
            ("success", f"> [{ts}]  execution: PASSED"),
            ("success", f"> [{ts}]  artifacts saved to {script_file}"),
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
                ("",        f"> [{ts}]  calling GPT-5.4 mini to generate final Markdown report..."),
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
        '<div class="pipeline-complete">Pipeline complete</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Pipeline state · state.json"):
        st.json(load_json(STATE_PATH))

    st.markdown(
        '<div class="report-section-label">Final report</div>',
        unsafe_allow_html=True,
    )
    report = open(f"workspace/final_reports/report_{task_id}.md").read()
    st.markdown(report)

    if mode == "Wet Lab":
        script = open(f"workspace/generated_code/protocol_{task_id}.py").read()
        st.download_button(
            "Download Opentrons script",
            script,
            f"protocol_{task_id}.py",
            "text/plain",
        )
    else:
        st.download_button(
            "Download reproducibility report",
            report,
            f"report_{task_id}.md",
            "text/markdown",
        )
