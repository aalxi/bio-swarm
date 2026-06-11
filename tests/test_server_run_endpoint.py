"""server.py POST /run — the task-submission endpoint had no coverage.

The endpoint validates input synchronously, optionally stages a demo cache,
then launches the pipeline on a background thread and returns {task_id}. We
test the synchronous validation + staging logic (deterministic) and the
success-path wiring. The pipeline itself is monkeypatched so no real agents,
LLMs, or network calls run.

Note: importing server.py chdir's to the repo root (module side effect), so
filesystem-relative paths in these tests resolve against the real repo, not a
tmp dir. The validation branches under test don't depend on that.
"""
import pytest


@pytest.fixture()
def client(tmp_workspace):
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


@pytest.fixture()
def stub_pipeline(monkeypatch):
    """Replace the real pipeline entry points with instant no-ops so the
    background runner thread can't reach OpenAI/Tavily/Daytona."""
    import server

    calls = {"run": [], "demo": []}

    def fake_run(**kwargs):
        calls["run"].append(kwargs)
        return {"status": "success", "task_id": kwargs.get("task_id"),
                "report_file": None, "state": {}}

    def fake_demo(**kwargs):
        calls["demo"].append(kwargs)
        return {"status": "success", "task_id": kwargs.get("task_id"),
                "report_file": None, "state": {}}

    monkeypatch.setattr(server, "run_pipeline", fake_run)
    monkeypatch.setattr(server, "run_pipeline_from_demo", fake_demo)
    return calls


# ── Validation branches (return before any thread starts) ────────────────────


def test_run_rejects_short_input(client, stub_pipeline):
    r = client.post("/run", json={"input": "qpcr", "mode": "wet_lab"})
    assert r.status_code == 400
    assert "non-trivial" in r.json()["error"]


def test_run_rejects_missing_input(client, stub_pipeline):
    r = client.post("/run", json={"mode": "wet_lab"})
    assert r.status_code == 400


def test_run_rejects_invalid_mode(client, stub_pipeline):
    r = client.post(
        "/run", json={"input": "a sufficiently long paper title", "mode": "banana"}
    )
    assert r.status_code == 400
    assert "mode" in r.json()["error"]


def test_run_rejects_missing_mode(client, stub_pipeline):
    r = client.post("/run", json={"input": "a sufficiently long paper title"})
    assert r.status_code == 400


# ── Success path wiring (synchronous response only; thread runs in bg) ────────


def test_run_valid_request_returns_task_id(client, stub_pipeline):
    r = client.post(
        "/run",
        json={"input": "RT-qPCR inhibition detection in wastewater", "mode": "wet_lab"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "task_id" in body
    assert len(body["task_id"]) == 8  # uuid4 hex truncated to 8


def test_run_registers_task_in_event_registry(client, stub_pipeline):
    import server

    r = client.post(
        "/run", json={"input": "a long enough paper title here", "mode": "dry_lab"}
    )
    task_id = r.json()["task_id"]
    # The endpoint registers an event queue synchronously before returning.
    assert task_id in server.TASKS


def test_run_demo_paper_bypasses_length_check_then_validates_cache(client, stub_pipeline):
    """demo_paper lets short input through the length gate, but staging still
    requires the cache to exist. The 400 must be the cache-not-found one
    (HTTPException detail), proving BOTH the length bypass and the cache guard
    in a single path. A length-rejection would instead carry {"error": ...}."""
    r = client.post(
        "/run",
        json={"input": "x", "mode": "wet_lab", "demo_paper": "definitely_absent_demo"},
    )
    assert r.status_code == 400
    assert "Demo cache not found" in r.text
    assert "non-trivial" not in r.text  # NOT the length rejection
