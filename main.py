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
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;700;900&display=swap');

/* ── Global layout scale ── */
:root {
    --accent: #4db87a;
    --accent2: #2a7a5e;
    --accent3: #3a9e6a;
    --bg: #080808;
    --surface: #0e0e0e;
    --border: #1f1f1f;
    --text: #d8d8d8;
    --dim: #3a3a3a;
}

html { font-size: 17px; }

[data-testid="stApp"] {
    background-color: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
}
[data-testid="stMain"] { background-color: var(--bg); }
[data-testid="stVerticalBlock"] > div { background-color: transparent; }

/* Wider, taller content column */
[data-testid="stAppViewBlockContainer"] {
    max-width: 920px !important;
    padding-top: 3.5rem;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

header[data-testid="stHeader"] {
    background-color: var(--bg);
    border-bottom: 1px solid #141414;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* ── Animated title ── */
.bio-title {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 4.2rem;
    font-weight: 900;
    letter-spacing: -0.04em;
    margin-bottom: 0;
    line-height: 0.95;
    background: linear-gradient(
        90deg,
        #3a7a56 0%,
        #4db87a 30%,
        #2a6e50 55%,
        #3a9e6a 80%,
        #3a7a56 100%
    );
    background-size: 300% 100%;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: title-flow 14s linear infinite;
    will-change: background-position;
}
@keyframes title-flow {
    0%   { background-position: 0% 50%; }
    100% { background-position: 300% 50%; }
}

.bio-subtitle {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.72rem;
    color: #2e2e2e;
    margin-top: 8px;
    margin-bottom: 40px;
    letter-spacing: 0.18em;
}

/* ── Mode toggle ── */

/* The column row that holds the two toggle buttons */
[data-testid="stHorizontalBlock"]:has(button[key="btn_wet"]) {
    gap: 0 !important;
    background: #0e0e0e !important;
    border: 1px solid #1f1f1f !important;
    border-radius: 8px !important;
    padding: 4px !important;
    width: fit-content !important;
    margin: 0 auto 28px auto !important;
    position: relative !important;
}

/* Both toggle buttons: transparent, sitting above the pill */
button[key="btn_wet"],
button[key="btn_dry"] {
    background: transparent !important;
    color: #3a3a3a !important;
    border: none !important;
    border-radius: 5px !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    padding: 10px 28px !important;
    min-width: 140px !important;
    box-shadow: none !important;
    position: relative !important;
    z-index: 2 !important;
    transition: color 0.4s ease !important;
}
button[key="btn_wet"]:hover,
button[key="btn_dry"]:hover {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* Active button text color */
button[key="btn_wet"][data-testid="baseButton-primary"],
button[key="btn_dry"][data-testid="baseButton-primary"] {
    color: #4db87a !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* The sliding pill — injected by JS, positioned absolutely inside the row */
#toggle-pill {
    position: absolute;
    top: 4px;
    left: 4px;
    height: calc(100% - 8px);
    background: linear-gradient(135deg, #1a3a28, #0e2a1c);
    border: 1px solid #4db87a44;
    border-radius: 5px;
    box-shadow: 0 0 12px #4db87a22, inset 0 1px 0 #4db87a18;
    pointer-events: none;
    z-index: 1;
    transition: transform 0.55s cubic-bezier(0.34, 1.56, 0.64, 1),
                width 0.55s cubic-bezier(0.34, 1.56, 0.64, 1);
    will-change: transform;
}

/* ── Text area ── */
[data-testid="stTextArea"] textarea {
    background-color: #0e0e0e !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    font-family: 'JetBrains Mono', 'Courier New', monospace !important;
    font-size: 0.82rem !important;
    caret-color: var(--accent);
    resize: vertical;
    padding: 14px 16px !important;
    line-height: 1.6 !important;
}
[data-testid="stTextArea"] textarea:focus {
    border-color: #4db87a55 !important;
    box-shadow: 0 0 0 2px #4db87a18 !important;
}
[data-testid="stTextArea"] textarea::placeholder { color: #2a2a2a !important; }
[data-testid="stTextArea"] label { display: none !important; }

/* ── Run button ── */
[data-testid="stButton"][id="run-btn-wrap"] > button,
button[data-testid="baseButton-secondary"][key="run_btn"],
div:has(> button[key="run_btn"]) button {
    background: linear-gradient(135deg, #1a3a28, #0e2a1c) !important;
    color: #4db87a !important;
    border: 1px solid #4db87a55 !important;
    border-radius: 6px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em !important;
    padding: 14px 0 !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease !important;
}
div:has(> button[key="run_btn"]) button:hover {
    box-shadow: 0 0 20px #4db87a33 !important;
    border-color: #4db87a99 !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
}
[data-testid="stExpander"] summary {
    color: #444 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
}

/* Hide native st.status() */
[data-testid="stStatusWidget"] { display: none !important; }

/* ── Download button ── */
[data-testid="stDownloadButton"] > button {
    background-color: transparent !important;
    color: var(--accent) !important;
    border: 1px solid #4db87a44 !important;
    border-radius: 5px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    font-weight: 400 !important;
    padding: 10px 24px !important;
    letter-spacing: 0.06em;
    transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
    width: auto !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #4db87a18 !important;
    box-shadow: 0 0 16px #4db87a22 !important;
}

/* ── Terminal panels ── */
.terminal-panel {
    background-color: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    padding: 20px 24px;
    margin: 10px 0;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.78rem;
    line-height: 1.8;
    overflow-x: auto;
    transition: transform 0.35s cubic-bezier(0.23, 1, 0.32, 1),
                box-shadow 0.35s cubic-bezier(0.23, 1, 0.32, 1);
}
.terminal-panel:hover {
    box-shadow: 0 4px 32px #4db87a0d;
}
.terminal-panel.running { border-left-color: #ffaa00; }
.terminal-panel.error   { border-left-color: #ff4444; }

.terminal-header {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.65rem;
    font-weight: 700;
    color: #3a3a3a;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    margin-bottom: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid #181818;
}
.terminal-line {
    color: #666;
    margin: 2px 0;
    white-space: pre-wrap;
    word-break: break-word;
}
.terminal-line.success { color: #4db87a; }
.terminal-line.error   { color: #ff5555; }
.terminal-line.warn    { color: #ffaa00; }
.terminal-line.dim     { color: #2c2c2c; }

.terminal-cursor {
    display: inline-block;
    width: 9px;
    height: 14px;
    background-color: #ffaa00;
    margin-left: 3px;
    vertical-align: middle;
    animation: cur-blink 1s step-end infinite;
}
@keyframes cur-blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
}

/* ── Handoff ── */
.handoff-msg {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.7rem;
    color: #1e4a2c;
    text-align: center;
    padding: 8px 0 6px 0;
    letter-spacing: 0.06em;
}

/* ── Pipeline complete ── */
.pipeline-complete {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    background: linear-gradient(90deg, #3a7a56, #4db87a, #2a6e50, #3a7a56);
    background-size: 300% 100%;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: title-flow 10s linear infinite;
    text-align: center;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    padding: 24px 0 12px 0;
    border-top: 1px solid #181818;
    margin-top: 24px;
}
.report-section-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    color: #2a2a2a;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    margin-top: 20px;
    margin-bottom: 8px;
}

/* ── Cursor magnetic field: magnetic-el class ── */
.magnetic-el {
    will-change: transform;
    transition: transform 0.6s cubic-bezier(0.23, 1, 0.32, 1);
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
    panel_cls = f"terminal-panel magnetic-el {state}"
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

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="bio-title magnetic-el">BIOSWARM</div>'
    '<div class="bio-subtitle">// MULTI-AGENT AI SYSTEM FOR BIOLOGICAL REPRODUCIBILITY</div>',
    unsafe_allow_html=True,
)

# ── Mode toggle ───────────────────────────────────────────────────────────────
# Two real Streamlit buttons. CSS targets them by key to style as a pill track.
# type="primary" = active (green pill), type="secondary" = inactive (dim).
_tc1, _tc2 = st.columns(2)
with _tc1:
    _wet_type = "primary" if st.session_state["mode"] == "Wet Lab" else "secondary"
    if st.button("🧪  Wet Lab", key="btn_wet", type=_wet_type, use_container_width=True):
        st.session_state["mode"] = "Wet Lab"
        st.rerun()
with _tc2:
    _dry_type = "primary" if st.session_state["mode"] == "Dry Lab" else "secondary"
    if st.button("💻  Dry Lab", key="btn_dry", type=_dry_type, use_container_width=True):
        st.session_state["mode"] = "Dry Lab"
        st.rerun()

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
    run_clicked = st.button("[ RUN BIOSWARM ]", use_container_width=True, key="run_btn")

# ── JavaScript: slider pill + cursor magnetic field ──────────────────────────
st.markdown("""
<script>
(function () {

  /* ── 1. Sliding pill ───────────────────────────────────────────────────
     Strategy:
     - Find the toggle row (stHorizontalBlock containing btn_wet / btn_dry)
     - Inject a #toggle-pill div as a child of that row
     - Measure whichever button is data-testid="baseButton-primary" and
       position the pill under it (no translateX needed — we just set left)
     - On button click: move pill immediately (before Streamlit rerenders),
       giving the full spring animation before the page updates
  ── */

  function findToggleRow() {
    var btns = document.querySelectorAll('button[key="btn_wet"], button[key="btn_dry"]');
    if (btns.length < 2) return null;
    // Walk up to the stHorizontalBlock
    var el = btns[0].parentElement;
    while (el && el.getAttribute('data-testid') !== 'stHorizontalBlock') {
      el = el.parentElement;
    }
    return el;
  }

  function injectPill(row) {
    if (document.getElementById('toggle-pill')) return; // already injected
    var pill = document.createElement('div');
    pill.id = 'toggle-pill';
    row.appendChild(pill);
    return pill;
  }

  function positionPill(pill, targetBtn, animate) {
    var row    = findToggleRow();
    if (!row || !targetBtn) return;
    var rowRect = row.getBoundingClientRect();
    var btnRect = targetBtn.getBoundingClientRect();
    var newLeft = btnRect.left - rowRect.left;   // relative to row
    var newW    = btnRect.width;

    if (!animate) {
      // Instant placement on first load — disable transition temporarily
      pill.style.transition = 'none';
      pill.style.left  = newLeft + 'px';
      pill.style.width = newW + 'px';
      // Re-enable transition after paint
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          pill.style.transition = '';
        });
      });
    } else {
      pill.style.left  = newLeft + 'px';
      pill.style.width = newW + 'px';
    }
  }

  function getActiveBtn() {
    return document.querySelector(
      'button[key="btn_wet"][data-testid="baseButton-primary"], ' +
      'button[key="btn_dry"][data-testid="baseButton-primary"]'
    );
  }

  function setupToggle() {
    var row = findToggleRow();
    if (!row) return false;

    var pill = injectPill(row);
    if (!pill) pill = document.getElementById('toggle-pill');

    // Position pill on current active button instantly (no animation on load)
    var active = getActiveBtn();
    if (active) positionPill(pill, active, false);

    // Wire click handlers on both buttons
    ['btn_wet', 'btn_dry'].forEach(function (key) {
      var btn = document.querySelector('button[key="' + key + '"]');
      if (!btn || btn._pillWired) return;
      btn._pillWired = true;
      btn.addEventListener('click', function () {
        // Animate pill to this button immediately — before Streamlit rerenders
        positionPill(pill, btn, true);
        // Also update text color eagerly
        document.querySelectorAll('button[key="btn_wet"], button[key="btn_dry"]')
          .forEach(function (b) { b.style.color = '#3a3a3a'; });
        btn.style.color = '#4db87a';
      });
    });

    return true;
  }

  // Try immediately, then observe DOM until the toggle row appears
  if (!setupToggle()) {
    var obs = new MutationObserver(function () {
      if (setupToggle()) obs.disconnect();
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  // After each Streamlit rerender the buttons are replaced — rewire
  var rerunObs = new MutationObserver(function () {
    var row = findToggleRow();
    if (!row) return;
    // Check if pill is still in the row
    if (!document.getElementById('toggle-pill')) {
      setupToggle();
      return;
    }
    // Rewire any unwired buttons (Streamlit replaces DOM nodes on rerun)
    ['btn_wet', 'btn_dry'].forEach(function (key) {
      var btn = document.querySelector('button[key="' + key + '"]');
      if (btn && !btn._pillWired) setupToggle();
    });
    // Snap pill to active button after rerender (no animation — it already played)
    var active = getActiveBtn();
    var pill = document.getElementById('toggle-pill');
    if (active && pill) positionPill(pill, active, false);
  });
  rerunObs.observe(document.body, { childList: true, subtree: true });

  /* ── 2. Cursor magnetic field ──────────────────────────────────────── */
  var mouseX = 0, mouseY = 0;
  var rafId = null;

  document.addEventListener('mousemove', function (e) {
    mouseX = e.clientX;
    mouseY = e.clientY;
    if (!rafId) rafId = requestAnimationFrame(tick);
  });

  function tick() {
    rafId = null;
    document.querySelectorAll('.magnetic-el').forEach(function (el) {
      var rect = el.getBoundingClientRect();
      var cx = rect.left + rect.width  / 2;
      var cy = rect.top  + rect.height / 2;
      var dx = mouseX - cx;
      var dy = mouseY - cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var radius = Math.max(rect.width, rect.height) * 1.6 + 180;
      if (dist < radius) {
        var s = 1 - dist / radius;
        s = s * s * (3 - 2 * s);   // smoothstep
        var pull = s * 8;
        el.style.transform = 'translate(' +
          ((dx / dist) * pull).toFixed(2) + 'px,' +
          ((dy / dist) * pull).toFixed(2) + 'px)';
      } else {
        el.style.transform = 'translate(0px,0px)';
      }
    });
  }

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
