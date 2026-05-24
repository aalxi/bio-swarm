"""P2.5 — Methodology DRY_LAB_SYSTEM_PROMPT must instruct the LLM to
emit typed {label, category} entries for expected_outputs."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

from agents import methodology


def test_dry_lab_prompt_describes_typed_outputs():
    p = methodology.DRY_LAB_SYSTEM_PROMPT
    assert "expected_outputs" in p
    assert "category" in p
    # Mentions at least the headline categories
    assert "paper_deliverable" in p
    assert "file_path" in p


def test_dry_lab_prompt_forbids_legacy_string_form():
    """The prompt should make clear each entry must be an object."""
    p = methodology.DRY_LAB_SYSTEM_PROMPT.lower()
    # Some explicit instruction; accept multiple phrasings.
    assert ("object" in p or "dict" in p) and "category" in p


def test_dry_lab_round_trip_with_typed_outputs(monkeypatch, tmp_path):
    """Methodology accepts the LLM emitting typed {label, category}
    objects and saves a protocol where expected_outputs is preserved as
    a list of ExpectedOutput objects."""
    canned = {
        "paper_title": "scGPT",
        "paper_source": "https://doi.org/x",
        "github_url": "https://github.com/foo/bar",
        "requirements_file": None,
        "data_download_urls": [],
        "main_script": None,
        "expected_outputs": [
            {"label": "results/figure_4.png", "category": "file_path"},
            {"label": "Figure 4: gene expression", "category": "paper_deliverable"},
        ],
        "extraction_notes": [],
    }
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(canned)
    mock_resp.usage = MagicMock(
        prompt_tokens=10, completion_tokens=10, total_tokens=20,
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    monkeypatch.setattr(methodology, "_get_openai_client", lambda: mock_client)

    src = tmp_path / "src.json"
    # Combined file convention: mode='dry_lab' tells methodology which prompt to use.
    src.write_text(json.dumps({
        "mode": "dry_lab",
        "raw_content": "scGPT paper text mentioning results/figure_4.png and Figure 4",
        "source_url": "test://scgpt",
    }))
    researcher_result = {"status": "success", "output_files": [str(src)]}

    os.makedirs("workspace/extracted_protocols", exist_ok=True)
    result = methodology.methodology_agent(researcher_result, "test_c2_dry")
    assert result["status"] == "success", result
    proto = json.loads(open(result["output_files"][0]).read())
    eo = proto["expected_outputs"]
    assert eo[0]["label"] == "results/figure_4.png"
    assert eo[0]["category"] == "file_path"
    assert eo[1]["category"] == "paper_deliverable"
