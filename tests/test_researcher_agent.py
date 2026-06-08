"""researcher_agent — zero coverage before this file.

The researcher orchestrates: query planning (LLM) → Tavily search → URL picking
(LLM) → Tavily extract → file persistence. Integration tests cover the happy
path; these tests cover the error contracts and structural invariants that
the Supervisor depends on:

  - The return dict always matches the Agent Return Contract
    (status / output_files / message / retry_count / error_detail).
  - LLM planning failure → status="error", message identifies the planning step.
  - Tavily failure → status="error" with retry_count reflecting attempts.
  - Empty search results trigger a broader-query retry; total miss → error.
  - dry_lab mode triggers the extra site:github.com query.
  - URL extraction failures are NON-fatal (search results are still usable).
"""
import json
from types import SimpleNamespace

import pytest

from agents import researcher


# ── Test doubles ─────────────────────────────────────────────────────────────


def _llm_response(payload: dict):
    """Build a fake OpenAI ChatCompletion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload))
        )],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


class FakeOpenAI:
    """Returns canned LLM responses in sequence. Last response is sticky."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        if len(self._queue) > 1:
            return self._queue.pop(0)
        return self._queue[0]


@pytest.fixture
def patch_openai(monkeypatch):
    """Patch researcher's _get_openai_client to return a configurable fake."""
    def install(responses):
        fake = FakeOpenAI(responses)
        monkeypatch.setattr(researcher, "_get_openai_client", lambda: fake)
        return fake
    return install


@pytest.fixture
def patch_tavily(monkeypatch):
    """Patch tavily functions referenced by researcher module."""
    def install(search_fn=None, extract_fn=None):
        if search_fn is not None:
            monkeypatch.setattr(researcher, "search_web", search_fn)
        if extract_fn is not None:
            monkeypatch.setattr(researcher, "extract_url", extract_fn)
    return install


# ── Tests ────────────────────────────────────────────────────────────────────


def test_researcher_returns_error_contract_when_query_planning_fails(
    tmp_workspace, patch_openai, patch_tavily,
):
    """If GPT can't be reached at all, we MUST return a structured error so the
    supervisor can record it rather than crash the pipeline."""
    class ExplodingClient:
        chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (_ for _ in ()).throw(ConnectionError("openai down"))
        ))

    import agents.researcher as r
    r._client = None  # reset cache
    import unittest.mock as mock
    with mock.patch.object(r, "_get_openai_client", return_value=ExplodingClient()):
        result = researcher.researcher_agent("query", "wet_lab", "task_X")

    assert result["status"] == "error"
    assert "plan" in result["message"].lower()
    assert "openai down" in result["error_detail"]
    assert result["output_files"] == []


def test_researcher_returns_error_contract_when_tavily_fails(
    tmp_workspace, patch_openai, patch_tavily,
):
    patch_openai([_llm_response({"queries": ["q1"]})])

    def boom(*args, **kwargs):
        raise RuntimeError("Tavily down")

    patch_tavily(search_fn=boom)
    result = researcher.researcher_agent("query", "wet_lab", "task_X")
    assert result["status"] == "error"
    assert "Tavily" in result["message"] or "tavily" in result["message"].lower()
    assert "Tavily down" in result["error_detail"]


def test_researcher_retries_with_broader_query_when_first_search_empty(
    tmp_workspace, patch_openai, patch_tavily,
):
    """An initial empty Tavily result triggers ONE broader-query retry."""
    patch_openai([
        _llm_response({"queries": ["narrow"]}),
        _llm_response({"urls": []}),  # _pick_extraction_urls returns no URLs
    ])

    call_log = []
    results_queue = [
        [],  # first query: empty
        [{"url": "http://hit", "title": "T", "content": "C", "score": 0.9}],
    ]

    def staged_search(q, **kw):
        call_log.append(q)
        return results_queue.pop(0) if results_queue else []

    patch_tavily(search_fn=staged_search)
    result = researcher.researcher_agent("very obscure query", "wet_lab", "task_R")

    assert result["status"] == "success"
    assert len(call_log) == 2  # initial + broader retry
    assert "biology protocol methodology" in call_log[1]


def test_researcher_returns_error_when_both_initial_and_broader_search_empty(
    tmp_workspace, patch_openai, patch_tavily,
):
    patch_openai([_llm_response({"queries": ["q"]})])
    patch_tavily(search_fn=lambda q, **kw: [])
    result = researcher.researcher_agent("q", "wet_lab", "task_Z")
    assert result["status"] == "error"
    assert result["retry_count"] == 1
    assert "No results" in result["message"]


def test_researcher_dry_lab_mode_runs_extra_github_query(
    tmp_workspace, patch_openai, patch_tavily,
):
    """dry_lab mode adds a site:github.com query after the planned queries."""
    patch_openai([
        _llm_response({"queries": ["paper q"]}),
        _llm_response({"urls": []}),
    ])

    queries_seen = []

    def search(q, **kw):
        queries_seen.append(q)
        return [{"url": f"http://{len(queries_seen)}", "title": "x",
                 "content": "y", "score": 0.5}]

    patch_tavily(search_fn=search)
    researcher.researcher_agent("my paper", "dry_lab", "task_D")

    assert any("site:github.com" in q for q in queries_seen)


def test_researcher_wet_lab_mode_does_not_run_github_query(
    tmp_workspace, patch_openai, patch_tavily,
):
    patch_openai([
        _llm_response({"queries": ["q"]}),
        _llm_response({"urls": []}),
    ])
    queries_seen = []

    def search(q, **kw):
        queries_seen.append(q)
        return [{"url": "http://x", "title": "t", "content": "c", "score": 1.0}]

    patch_tavily(search_fn=search)
    researcher.researcher_agent("paper", "wet_lab", "task_W")
    assert not any("site:github.com" in q for q in queries_seen)


def test_researcher_extraction_failure_is_non_fatal(
    tmp_workspace, patch_openai, patch_tavily,
):
    """If extract_url fails, the agent still returns success with search files."""
    patch_openai([
        _llm_response({"queries": ["q"]}),
        _llm_response({"urls": [{"url": "http://a", "reason": "best"}]}),
    ])

    def boom_extract(url):
        raise RuntimeError("extract failed")

    patch_tavily(
        search_fn=lambda q, **kw: [
            {"url": "http://a", "title": "T", "content": "C", "score": 0.9}
        ],
        extract_fn=boom_extract,
    )
    result = researcher.researcher_agent("q", "wet_lab", "task_E")
    assert result["status"] == "success"


def test_researcher_falls_back_to_user_input_when_planner_returns_no_queries(
    tmp_workspace, patch_openai, patch_tavily,
):
    """If the LLM produces an empty query list, we use the raw user_input."""
    patch_openai([
        _llm_response({"queries": []}),  # planner returns nothing
        _llm_response({"urls": []}),
    ])
    seen = []

    def search(q, **kw):
        seen.append(q)
        return [{"url": "http://x", "title": "T", "content": "C", "score": 1}]

    patch_tavily(search_fn=search)
    researcher.researcher_agent("raw user query", "wet_lab", "task_F")
    assert seen[0] == "raw user query"


def test_researcher_writes_combined_summary_with_unique_sources(
    tmp_workspace, patch_openai, patch_tavily,
):
    """The combined file is the supervisor's hand-off — its shape is part of
    the inter-agent contract."""
    from tools.file_tool import load_json

    patch_openai([
        _llm_response({"queries": ["q1", "q2"]}),
        _llm_response({"urls": []}),
    ])

    def search(q, **kw):
        # Same URL across queries → must dedupe in combined file
        return [{"url": "http://same", "title": "T", "content": "C", "score": 1}]

    patch_tavily(search_fn=search)
    result = researcher.researcher_agent("input", "wet_lab", "task_C")
    assert result["status"] == "success"

    combined_path = next(f for f in result["output_files"] if "combined" in f)
    combined = load_json(combined_path)
    assert combined["task_id"] == "task_C"
    assert combined["mode"] == "wet_lab"
    assert combined["all_sources"] == ["http://same"]  # deduped


def test_researcher_success_contract_keys_match_specification(
    tmp_workspace, patch_openai, patch_tavily,
):
    """Supervisor reads these exact keys from every agent return."""
    patch_openai([
        _llm_response({"queries": ["q"]}),
        _llm_response({"urls": []}),
    ])
    patch_tavily(search_fn=lambda q, **kw: [
        {"url": "http://x", "title": "t", "content": "c", "score": 1}
    ])
    result = researcher.researcher_agent("q", "wet_lab", "task_K")
    assert set(result.keys()) >= {
        "status", "output_files", "message", "retry_count", "error_detail",
    }
