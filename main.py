# main.py — Streamlit entry point

import os
import traceback
import uuid

import streamlit as st
import streamlit.runtime as st_runtime
from dotenv import load_dotenv

if not st_runtime.exists():
    # Running with `python main.py` has no Streamlit runtime — session state and widgets break.
    import sys

    print(
        "BioSwarm must be started with Streamlit, not plain Python:\n\n"
        "  streamlit run main.py\n",
        file=sys.stderr,
    )
    raise SystemExit(1)

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

# --- UI Layout ---
st.title("\U0001f9ec BioSwarm")
mode = st.radio("Mode", ["Wet Lab", "Dry Lab"])
user_input = st.text_area("Paste a paper title, DOI, URL, or abstract")

if st.button("Run BioSwarm") and user_input.strip():
    task_id = str(uuid.uuid4())[:8]
    mode_key = "wet_lab" if mode == "Wet Lab" else "dry_lab"

    # Initialize pipeline state
    state = WorkspaceState(
        task_id=task_id, mode=mode_key, user_input=user_input, status="research"
    )
    save_json(state.model_dump(), STATE_PATH)

    # ---- 1. Researcher Agent ----
    with st.status("\U0001f52c Researcher Agent \u2014 searching...") as s:
        try:
            researcher_result = researcher_agent(user_input, mode_key, task_id)
        except Exception:
            state.errors.append("Researcher agent crashed")
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Research failed", state="error")
            st.error(f"Researcher agent crashed:\n```\n{traceback.format_exc()}```")
            st.stop()
        if researcher_result["status"] == "error":
            state.errors.append(researcher_result["message"])
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Research failed", state="error")
            st.error(researcher_result.get("error_detail", researcher_result["message"]))
            st.stop()
        state.research.done = True
        state.research.files = researcher_result["output_files"]
        state.status = "extraction"
        save_json(state.model_dump(), STATE_PATH)
        s.update(
            label=f"\u2705 Research done \u2014 {len(researcher_result['output_files'])} files saved",
            state="complete",
        )

    # ---- 2. Methodology Agent ----
    with st.status("\U0001f9e0 Methodology Agent \u2014 extracting protocol...") as s:
        try:
            methodology_result = methodology_agent(researcher_result, task_id)
        except Exception:
            state.errors.append("Methodology agent crashed")
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Extraction failed", state="error")
            st.error(f"Methodology agent crashed:\n```\n{traceback.format_exc()}```")
            st.stop()
        if methodology_result["status"] == "error":
            state.errors.append(methodology_result["message"])
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Extraction failed", state="error")
            st.error(methodology_result.get("error_detail", methodology_result["message"]))
            st.stop()
        state.extraction.done = True
        state.extraction.protocol_file = methodology_result["output_files"][0]
        state.extraction.schema_valid = True
        state.status = "coding"
        save_json(state.model_dump(), STATE_PATH)
        s.update(label="\u2705 Protocol extracted and validated", state="complete")

    # ---- 3. Coder Agent ----
    with st.status("\U0001f4bb Coder Agent \u2014 running in Daytona sandbox...") as s:
        try:
            coder_result = coder_agent(methodology_result, mode_key, task_id)
        except Exception:
            state.errors.append("Coder agent crashed")
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Coder failed", state="error")
            st.error(f"Coder agent crashed:\n```\n{traceback.format_exc()}```")
            st.stop()
        if coder_result["status"] == "error":
            state.coding.error_log = coder_result.get("error_detail")
            state.coding.retry_count = coder_result.get("retry_count", 0)
            state.errors.append(coder_result["message"])
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(
                label=f"\u274c Coder failed after {coder_result.get('retry_count', 0)} retries",
                state="error",
            )
            st.error(coder_result.get("error_detail", coder_result["message"]))
            st.stop()
        state.coding.done = True
        state.coding.script_file = coder_result["output_files"][0]
        state.coding.simulation_passed = True
        state.status = "synthesis"
        save_json(state.model_dump(), STATE_PATH)
        s.update(label="\u2705 Script generated and simulation passed", state="complete")

    # ---- 4. Synthesizer Agent ----
    with st.status("\U0001f4dd Synthesizer Agent \u2014 writing report...") as s:
        try:
            synth_result = synthesizer_agent(task_id)
        except Exception:
            state.errors.append("Synthesizer agent crashed")
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Report generation failed", state="error")
            st.error(f"Synthesizer agent crashed:\n```\n{traceback.format_exc()}```")
            st.stop()
        if synth_result["status"] == "error":
            state.errors.append(synth_result["message"])
            state.status = "error"
            save_json(state.model_dump(), STATE_PATH)
            s.update(label="\u274c Report generation failed", state="error")
            st.error(synth_result.get("error_detail", synth_result["message"]))
            st.stop()
        state.synthesis.done = True
        state.synthesis.report_file = synth_result["output_files"][0]
        state.status = "complete"
        save_json(state.model_dump(), STATE_PATH)
        s.update(label="\u2705 Report complete", state="complete")

    # ---- Display results ----
    with st.expander("\U0001f50d Pipeline State (state.json)"):
        st.json(load_json(STATE_PATH))

    report = open(f"workspace/final_reports/report_{task_id}.md").read()
    st.markdown(report)

    # Download button
    if mode == "Wet Lab":
        script = open(f"workspace/generated_code/protocol_{task_id}.py").read()
        st.download_button(
            "\u2b07\ufe0f Download Opentrons Script",
            script,
            f"protocol_{task_id}.py",
            "text/plain",
        )
    else:
        st.download_button(
            "\u2b07\ufe0f Download Reproducibility Report",
            report,
            f"report_{task_id}.md",
            "text/markdown",
        )
