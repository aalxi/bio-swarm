#!/usr/bin/env python3
"""server.py — FastAPI entry point for BioSwarm.

Wraps `agents.supervisor.run_pipeline` in a thin web layer:
    POST /run                  → start a task, returns {task_id}
    GET  /events/{task_id}     → Server-Sent Events stream of phase events
    GET  /state/{task_id}      → current workspace/state.json (404 if not current)
    GET  /report/{task_id}     → server-rendered report HTML (202 if pending)
    GET  /download/{task_id}   → script .py or report .md (202 if pending)
    GET  /                     → web/index.html
    GET  /static/*             → web/{css,js,fonts,...}
"""

import asyncio
import json
import os
import queue
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

# Make workspace/* relative paths resolve regardless of CWD
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# Workspace bootstrap (mirrors run_cli.py)
for _d in [
    "workspace",
    "workspace/raw_research",
    "workspace/extracted_protocols",
    "workspace/generated_code",
    "workspace/final_reports",
]:
    os.makedirs(_d, exist_ok=True)

import markdown as md
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from agents.supervisor import run_pipeline, run_pipeline_from_demo, _demo_slug
from tools.file_tool import load_json


app = FastAPI(title="BioSwarm")


# Best-effort citation-registry verification at boot (L16 warn-and-flag).
try:
    from tools.citation_registry import verify_at_startup as _verify_citations
    _verify_citations(timeout_s=10.0)
except Exception as _verify_err:
    print(f"[server] citation verify_at_startup failed: {_verify_err}", flush=True)

# In-memory task registries. Single-tenant by design — see plan/CLAUDE.md.
TASKS: dict[str, queue.Queue] = {}   # task_id -> event queue
RESULTS: dict[str, dict] = {}        # task_id -> final pipeline result


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── Pipeline endpoints ──────────────────────────────────────────────────────

@app.post("/run")
async def start_run(payload: dict):
    user_input = (payload.get("input") or "").strip()
    mode = payload.get("mode")
    enable_iteration: bool = bool(payload.get("enable_iteration", False))
    demo_paper = (payload.get("demo_paper") or "").strip() or None
    if not user_input:
        raise HTTPException(400, "Missing 'input'")
    if mode not in ("wet_lab", "dry_lab"):
        raise HTTPException(400, "'mode' must be 'wet_lab' or 'dry_lab'")

    task_id = str(uuid.uuid4())[:8]
    protocol_path: str | None = None

    # Stage a demo cache as the extracted protocol if requested. Done BEFORE
    # registering TASKS[task_id] so a missing cache cleanly 400s without
    # leaving an orphan event queue that /events would block on forever.
    if demo_paper:
        slug = _demo_slug(demo_paper)
        src = Path(f"workspace/demo_cache/{slug}_protocol.json")
        if not src.exists():
            raise HTTPException(400, f"Demo cache not found for '{demo_paper}'")
        dst = Path(f"workspace/extracted_protocols/protocol_{task_id}.json")
        shutil.copy(src, dst)
        protocol_path = str(dst)

    q: queue.Queue = queue.Queue()
    TASKS[task_id] = q

    def callback(event):
        # Supervisor sends dicts; tolerate strings just in case.
        if isinstance(event, dict):
            q.put(event)
        else:
            q.put({"type": "status", "message": str(event), "ts": _ts()})

    def runner():
        try:
            if demo_paper:
                result = run_pipeline_from_demo(
                    user_input=user_input,
                    mode=mode,
                    task_id=task_id,
                    protocol_path=protocol_path,
                    enable_iteration=enable_iteration,
                    status_callback=callback,
                )
            else:
                result = run_pipeline(
                    user_input=user_input,
                    mode=mode,
                    task_id=task_id,
                    status_callback=callback,
                    enable_iteration=enable_iteration,
                )
        except Exception as e:
            tb = traceback.format_exc()
            # Synthetic phase_end so no panel is left "running" forever.
            q.put({
                "type": "phase_end",
                "phase": "unknown",
                "status": "error",
                "files": [],
                "message": f"Server-side runner crashed: {type(e).__name__}",
                "retry_count": 0,
                "error_detail": tb,
                "ts": _ts(),
            })
            result = {
                "status": "error",
                "task_id": task_id,
                "report_file": None,
                "error_detail": tb,
            }
        RESULTS[task_id] = result
        q.put({"type": "done", "result": result, "ts": _ts()})

    threading.Thread(target=runner, daemon=True, name=f"bioswarm-{task_id}").start()
    return {"task_id": task_id}


@app.get("/events/{task_id}")
async def stream_events(task_id: str, request: Request):
    if task_id not in TASKS:
        raise HTTPException(404, "Unknown task")
    q = TASKS[task_id]

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.to_thread(q.get, True, 1.0)
            except queue.Empty:
                # Keep-alive — prevents proxies from closing the long stream.
                yield {"event": "ping", "data": ""}
                continue
            yield {
                "event": event.get("type", "message"),
                "data": json.dumps(event),
            }
            if event.get("type") == "done":
                break

    return EventSourceResponse(event_generator())


# ── Result endpoints ────────────────────────────────────────────────────────

@app.get("/state/{task_id}")
async def get_state(task_id: str):
    """Return current workspace/state.json. 404 if it's no longer this task's."""
    try:
        state = load_json("workspace/state.json")
    except Exception:
        raise HTTPException(404, "No state file")
    if state.get("task_id") != task_id:
        raise HTTPException(404, "State for this task is no longer current")
    return state


@app.get("/report/{task_id}")
async def get_report(task_id: str):
    """Server-render the markdown report to HTML."""
    if task_id not in RESULTS and task_id not in TASKS:
        raise HTTPException(404, "Unknown task")
    if task_id not in RESULTS:
        return Response(status_code=202)  # still running
    if RESULTS[task_id].get("status") != "success":
        raise HTTPException(409, "Task did not complete successfully")

    path = f"workspace/final_reports/report_{task_id}.md"
    if not os.path.exists(path):
        raise HTTPException(404, "Report file missing")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    html = md.markdown(raw, extensions=["fenced_code", "tables"])
    return JSONResponse({"html": html})


@app.get("/download/{task_id}")
async def download(task_id: str, kind: str = "script"):
    """Download the generated script (kind=script) or markdown report (kind=report)."""
    if task_id not in RESULTS and task_id not in TASKS:
        raise HTTPException(404, "Unknown task")
    if task_id not in RESULTS:
        return Response(status_code=202)

    if kind == "script":
        path = f"workspace/generated_code/protocol_{task_id}.py"
        media = "text/x-python"
        filename = f"protocol_{task_id}.py"
    elif kind == "report":
        path = f"workspace/final_reports/report_{task_id}.md"
        media = "text/markdown"
        filename = f"report_{task_id}.md"
    else:
        raise HTTPException(400, "kind must be 'script' or 'report'")

    if not os.path.exists(path):
        raise HTTPException(404, "File not available")
    return FileResponse(path, media_type=media, filename=filename)


# ── Lineage endpoint ────────────────────────────────────────────────────────

@app.get("/lineage/{task_id}")
def get_lineage(task_id: str):
    """Return field-level lineage for all steps in a protocol, plus the citation registry."""
    from pathlib import Path as _Path

    path = _Path(f"workspace/extracted_protocols/protocol_{task_id}.json")
    if not path.exists():
        raise HTTPException(404, f"protocol not found for task_id={task_id}")
    proto = json.loads(path.read_text())
    fields: dict[str, dict] = {}
    for step in proto.get("sequential_steps", []):
        for field, fl_json in (step.get("field_lineage") or {}).items():
            fields[f"step_{step['step_number']}.{field}"] = fl_json

    from tools.citation_registry import REGISTRY
    registry = {k: c.model_dump() for k, c in REGISTRY.items()}
    return {"fields": fields, "registry": registry}


# ── Static + index (registered last so they don't shadow API routes) ────────

app.mount("/static", StaticFiles(directory="web"), name="static")


@app.get("/")
async def index():
    return FileResponse("web/index.html")


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
