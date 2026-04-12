# supervisor.py — PI Agent: orchestrates the pipeline, owns state.json

from schemas.state_schema import WorkspaceState
from tools.file_tool import save_json
from agents.researcher import researcher_agent
from agents.methodology import methodology_agent
from agents.coder import coder_agent
from agents.synthesizer import synthesizer_agent
from tools.token_tracker import print_summary as print_token_summary


STATE_PATH = "workspace/state.json"


def run_pipeline(user_input: str, mode: str, task_id: str, status_callback=None) -> dict:
    """Run the full BioSwarm pipeline: research → extraction → coding → synthesis.

    Pure Python orchestrator — no LLM calls. Calls each agent in sequence,
    updates workspace/state.json after every step, and returns the final result.

    Args:
        user_input: Paper title, DOI, URL, or abstract from the user.
        mode: "wet_lab" or "dry_lab".
        task_id: Short unique identifier for this run.
        status_callback: Optional callable(str) invoked after each phase with a status message.

    Returns:
        {"status": "success"|"error", "task_id": str, "report_file": str|None, "state": dict}
    """
    # --- Initialize state ---
    state = WorkspaceState(
        task_id=task_id, mode=mode, user_input=user_input, status="research"
    )
    _save_state(state)

    # --- 1. Research ---
    try:
        researcher_result = researcher_agent(user_input, mode, task_id)
    except Exception as e:
        researcher_result = _exception_contract(e)

    if researcher_result.get("status") != "success":
        return _handle_error(state, "research", researcher_result)

    state.research.done = True
    state.research.files = researcher_result.get("output_files", [])
    state.status = "extraction"
    _save_state(state)
    _notify(status_callback, f"Research complete — {len(state.research.files)} files saved")

    # --- 2. Methodology / Extraction ---
    try:
        methodology_result = methodology_agent(researcher_result, task_id)
    except Exception as e:
        methodology_result = _exception_contract(e)

    if methodology_result.get("status") != "success":
        return _handle_error(state, "extraction", methodology_result)

    output_files = methodology_result.get("output_files", [])
    if not output_files:
        return _handle_error(state, "extraction", {
            "status": "error",
            "message": "Methodology agent returned success but no output files",
            "error_detail": "output_files list is empty",
            "retry_count": 0,
            "output_files": [],
        })

    state.extraction.done = True
    state.extraction.protocol_file = output_files[0]
    state.extraction.schema_valid = True
    state.status = "coding"
    _save_state(state)
    _notify(status_callback, "Protocol extracted and validated")

    # --- 3. Coder ---
    try:
        coder_result = coder_agent(methodology_result, mode, task_id)
    except Exception as e:
        coder_result = _exception_contract(e)

    if coder_result.get("status") != "success":
        state.coding.error_log = coder_result.get("error_detail")
        state.coding.retry_count = coder_result.get("retry_count", 0)
        return _handle_error(state, "coding", coder_result)

    output_files = coder_result.get("output_files", [])
    if not output_files:
        return _handle_error(state, "coding", {
            "status": "error",
            "message": "Coder agent returned success but no output files",
            "error_detail": "output_files list is empty",
            "retry_count": 0,
            "output_files": [],
        })

    state.coding.done = True
    state.coding.script_file = output_files[0]
    state.coding.simulation_passed = True
    state.status = "synthesis"
    _save_state(state)
    _notify(status_callback, "Script generated and simulation passed")

    # --- 4. Synthesis ---
    try:
        synth_result = synthesizer_agent(task_id)
    except Exception as e:
        synth_result = _exception_contract(e)

    if synth_result.get("status") != "success":
        return _handle_error(state, "synthesis", synth_result)

    output_files = synth_result.get("output_files", [])
    state.synthesis.done = True
    state.synthesis.report_file = output_files[0] if output_files else None
    state.status = "complete"
    _save_state(state)
    _notify(status_callback, "Report complete")

    print_token_summary()
    return {
        "status": "success",
        "task_id": task_id,
        "report_file": state.synthesis.report_file,
        "state": state.model_dump(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_state(state: WorkspaceState) -> None:
    save_json(state.model_dump(), STATE_PATH)


def _notify(callback, message: str) -> None:
    if callback is not None:
        try:
            callback(message)
        except Exception:
            pass


def _exception_contract(exc: Exception) -> dict:
    """Build an Agent Return Contract dict from an unexpected exception."""
    return {
        "status": "error",
        "output_files": [],
        "message": f"Unexpected exception: {type(exc).__name__}",
        "retry_count": 0,
        "error_detail": str(exc),
    }


def _handle_error(state: WorkspaceState, phase: str, result: dict) -> dict:
    """Record an agent error in state and return the pipeline error dict."""
    msg = result.get("message", "Unknown error")
    detail = result.get("error_detail", "")
    state.errors.append(f"[{phase}] {msg}: {detail}" if detail else f"[{phase}] {msg}")
    state.status = "error"
    _save_state(state)
    print_token_summary()
    return {
        "status": "error",
        "task_id": state.task_id,
        "report_file": None,
        "state": state.model_dump(),
    }
