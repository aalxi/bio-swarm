"""Tests that methodology_agent appends a rejection note when the LLM returns
placeholder URLs in data_download_urls.

The monkeypatch pattern follows other tests in this suite: we patch
_get_openai_client inside agents.methodology to return a fake client whose
chat.completions.create() call returns a canned JSON response with placeholder
URLs baked in.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_fake_client(llm_json: dict):
    """Return a mock OpenAI client that yields *llm_json* as the first completion."""
    fake_message = MagicMock()
    fake_message.content = json.dumps(llm_json)

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    # usage stub so track_call doesn't blow up
    fake_response.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    return fake_client


_DRY_LAB_RESPONSE_WITH_PLACEHOLDERS = {
    "paper_title": "scGPT: toward building a foundation model",
    "paper_source": "https://doi.org/10.1038/s41592-024-02201-0",
    "github_url": "https://github.com/bowang-lab/scGPT",
    "requirements_file": None,
    "data_download_urls": [
        "https://doi.org/10.6084/m9.figshare.??",
        "https://zenodo.org/record/??",
        "https://zenodo.org/record/12345",   # this one is real
    ],
    "main_script": None,
    "expected_outputs": ["Figure 4"],
    "extraction_notes": ["No requirements.txt found."],
}


def _seed_research_file(tmp_workspace) -> dict:
    """Write a minimal combined research file and return a researcher_result dict."""
    data = {
        "mode": "dry_lab",
        "summary": "test",
        "all_sources": ["https://example.com"],
        "results": [
            {
                "url": "https://example.com",
                "title": "Test",
                "content": "scGPT paper content",
                "raw_content": "scGPT paper content",
                "score": 0.9,
            }
        ],
    }
    path = "workspace/raw_research/task_test_combined.json"
    Path(path).write_text(json.dumps(data))
    return {
        "status": "success",
        "output_files": [path],
        "message": "ok",
        "retry_count": 0,
        "error_detail": None,
    }


def test_methodology_records_placeholder_url_rejection_in_notes(
    tmp_workspace, monkeypatch
):
    """When the LLM returns placeholder URLs, extraction_notes must contain a
    rejection notice mentioning the bad URL(s)."""
    import agents.methodology as meth

    fake_client = _make_fake_client(_DRY_LAB_RESPONSE_WITH_PLACEHOLDERS)
    monkeypatch.setattr(meth, "_get_openai_client", lambda: fake_client)
    # Also stub the Tavily search used by _find_missing_github_url (github_url IS
    # already populated in this response, so the fallback won't trigger — but patch
    # anyway to avoid accidental network calls in CI).
    monkeypatch.setattr(meth, "search_web", lambda *a, **kw: [])

    researcher_result = _seed_research_file(tmp_workspace)
    result = meth.methodology_agent(researcher_result, task_id="test")

    assert result["status"] == "success", result.get("error_detail")

    # Load the saved protocol and inspect extraction_notes
    saved = json.loads(
        Path(result["output_files"][0]).read_text()
    )
    notes = saved.get("extraction_notes", [])

    # At least one note must mention the rejected URLs
    rejection_notes = [n for n in notes if "rejected" in n.lower() and "??" in n]
    assert rejection_notes, (
        f"Expected a rejection note containing '??' in extraction_notes, got:\n{notes}"
    )

    # The real URL should survive in data_download_urls
    assert "https://zenodo.org/record/12345" in saved["data_download_urls"]

    # The placeholder URLs must NOT be in data_download_urls
    for bad in ["https://doi.org/10.6084/m9.figshare.??", "https://zenodo.org/record/??"]:
        assert bad not in saved["data_download_urls"], (
            f"Placeholder URL {bad!r} should have been filtered out"
        )


def test_methodology_no_rejection_note_when_all_urls_valid(
    tmp_workspace, monkeypatch
):
    """When the LLM returns no placeholder URLs, no rejection note is added."""
    import agents.methodology as meth

    good_response = dict(_DRY_LAB_RESPONSE_WITH_PLACEHOLDERS)
    good_response["data_download_urls"] = ["https://zenodo.org/record/12345"]

    fake_client = _make_fake_client(good_response)
    monkeypatch.setattr(meth, "_get_openai_client", lambda: fake_client)
    monkeypatch.setattr(meth, "search_web", lambda *a, **kw: [])

    researcher_result = _seed_research_file(tmp_workspace)
    result = meth.methodology_agent(researcher_result, task_id="test_clean")

    assert result["status"] == "success", result.get("error_detail")

    saved = json.loads(Path(result["output_files"][0]).read_text())
    rejection_notes = [
        n for n in saved.get("extraction_notes", [])
        if "rejected" in n.lower() and "placeholder" in n.lower()
    ]
    assert not rejection_notes, (
        f"Unexpected rejection note when all URLs were valid: {rejection_notes}"
    )
    assert saved["data_download_urls"] == ["https://zenodo.org/record/12345"]
