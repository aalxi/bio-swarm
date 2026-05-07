# supervisor.py — PI Agent: orchestrates the pipeline, owns state.json

from datetime import datetime

from schemas.state_schema import WorkspaceState
from tools.file_tool import load_json, save_json
from agents.researcher import researcher_agent
from agents.methodology import methodology_agent
from agents.enricher import enricher_agent
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
        status_callback: Optional callable invoked after each phase. Receives a
            structured dict event ({"type": "phase_start"|"phase_end"|"status", ...})
            or, for backwards-compat, a plain string. The callback decides how to
            handle it. Exceptions in the callback are swallowed.

    Returns:
        {"status": "success"|"error", "task_id": str, "report_file": str|None, "state": dict}
    """
    # --- Initialize state ---
    state = WorkspaceState(
        task_id=task_id, mode=mode, user_input=user_input, status="research"
    )
    _save_state(state)

    # --- 1. Research ---
    _emit_start(status_callback, "research")
    try:
        researcher_result = researcher_agent(user_input, mode, task_id)
    except Exception as e:
        researcher_result = _exception_contract(e)
    _emit_end(status_callback, "research", researcher_result)

    if researcher_result.get("status") != "success":
        return _handle_error(state, "research", researcher_result)

    state.research.done = True
    state.research.files = researcher_result.get("output_files", [])
    state.status = "extraction"
    _save_state(state)

    # --- 2. Methodology / Extraction ---
    _emit_start(status_callback, "extraction")
    try:
        methodology_result = methodology_agent(researcher_result, task_id)
    except Exception as e:
        methodology_result = _exception_contract(e)
    _emit_end(status_callback, "extraction", methodology_result)

    if methodology_result.get("status") != "success":
        return _handle_error(state, "extraction", methodology_result)

    output_files = methodology_result.get("output_files", [])
    if not output_files:
        empty = {
            "status": "error",
            "message": "Methodology agent returned success but no output files",
            "error_detail": "output_files list is empty",
            "retry_count": 0,
            "output_files": [],
        }
        _emit_end(status_callback, "extraction", empty)
        return _handle_error(state, "extraction", empty)

    state.extraction.done = True
    state.extraction.protocol_file = output_files[0]
    state.extraction.schema_valid = True
    state.status = "enrichment" if mode == "wet_lab" else "coding"
    _save_state(state)

    # --- 2b. PIE Enrichment (wet-lab only, non-blocking) ---
    if mode == "wet_lab":
        _emit_start(status_callback, "enrichment")
        try:
            enricher_result = enricher_agent(methodology_result, task_id)
        except Exception as e:
            enricher_result = _exception_contract(e)

        # Pull enrichment_log so we can report gaps_identified accurately
        elog = enricher_result.get("enrichment_log") or {}
        if not elog and enricher_result.get("status") == "success":
            try:
                _proto = load_json(f"workspace/extracted_protocols/protocol_{task_id}.json")
                elog = _proto.get("enrichment_log") or {}
            except Exception:
                pass
        gaps_filled = enricher_result.get("gaps_filled", 0)
        gaps_identified = elog.get("gaps_identified", gaps_filled)

        # Augment the contract with the resolved gap counts before emitting
        enricher_result_for_event = dict(enricher_result)
        enricher_result_for_event["gaps_filled"] = gaps_filled
        enricher_result_for_event["gaps_identified"] = gaps_identified
        enricher_result_for_event["conflicts"] = elog.get("conflicts", [])
        enricher_result_for_event["tavily_queries_executed"] = elog.get(
            "tavily_queries_executed", 0
        )
        _emit_end(status_callback, "enrichment", enricher_result_for_event)

        if enricher_result.get("status") == "success":
            state.enrichment.done = True
            state.enrichment.gaps_identified = gaps_identified
            state.enrichment.gaps_filled = gaps_filled
            enr_files = enricher_result.get("output_files", [])
            if len(enr_files) > 1:
                state.enrichment.enrichment_file = enr_files[1]
        else:
            state.enrichment.skipped = True
            state.errors.append(
                f"[enrichment] {enricher_result.get('message', 'PIE failed')} — pipeline continues"
            )

        state.status = "coding"
        _save_state(state)

    # --- 3. Coder ---
    _emit_start(status_callback, "coding")
    try:
        coder_result = coder_agent(methodology_result, mode, task_id)
    except Exception as e:
        coder_result = _exception_contract(e)
    _emit_end(status_callback, "coding", coder_result)

    # Copy coder-side observability fields into state regardless of outcome —
    # so error paths still surface attempts/coverage in the report.
    state.coding.attempts = coder_result.get("attempts", []) or []
    state.coding.liquid_step_coverage = coder_result.get("liquid_step_coverage")
    state.coding.skipped_step_numbers = coder_result.get("skipped_step_numbers", []) or []
    state.coding.coverage_method = coder_result.get("coverage_method")
    state.coding.fidelity_warning = bool(coder_result.get("fidelity_warning", False))

    if coder_result.get("status") != "success":
        state.coding.error_log = coder_result.get("error_detail")
        state.coding.retry_count = coder_result.get("retry_count", 0)
        return _handle_error(state, "coding", coder_result)

    output_files = coder_result.get("output_files", [])
    if not output_files:
        empty = {
            "status": "error",
            "message": "Coder agent returned success but no output files",
            "error_detail": "output_files list is empty",
            "retry_count": 0,
            "output_files": [],
        }
        return _handle_error(state, "coding", empty)

    state.coding.done = True
    state.coding.script_file = output_files[0]
    state.coding.simulation_passed = True
    state.status = "synthesis"
    _save_state(state)

    # --- 4. Synthesis ---
    _emit_start(status_callback, "synthesis")
    try:
        synth_result = synthesizer_agent(task_id)
    except Exception as e:
        synth_result = _exception_contract(e)
    _emit_end(status_callback, "synthesis", synth_result)

    if synth_result.get("status") != "success":
        return _handle_error(state, "synthesis", synth_result)

    output_files = synth_result.get("output_files", [])
    state.synthesis.done = True
    state.synthesis.report_file = output_files[0] if output_files else None
    state.status = "complete"
    _save_state(state)

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

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _save_state(state: WorkspaceState) -> None:
    save_json(state.model_dump(), STATE_PATH)


def _notify(callback, message_or_event) -> None:
    """Forward a string or dict event to the callback. Errors swallowed."""
    if callback is None:
        return
    try:
        callback(message_or_event)
    except Exception:
        pass


def _emit_start(callback, phase: str) -> None:
    _notify(callback, {"type": "phase_start", "phase": phase, "ts": _ts()})


def _emit_end(callback, phase: str, result: dict) -> None:
    """Emit a phase_end event built from an agent return contract."""
    event = {
        "type": "phase_end",
        "phase": phase,
        "status": result.get("status", "error"),
        "files": result.get("output_files", []),
        "message": result.get("message", ""),
        "retry_count": result.get("retry_count", 0),
        "error_detail": result.get("error_detail"),
        "ts": _ts(),
    }
    # Phase-specific extras (set by the caller for enrichment)
    for k in ("gaps_filled", "gaps_identified", "conflicts", "tavily_queries_executed"):
        if k in result:
            event[k] = result[k]
    _notify(callback, event)


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
