"""P2.5 — Typed ExpectedOutput model. expected_outputs in
ReproducibilityTarget is no longer free-text List[str] — each entry
carries a category so the Coder doesn't try to download "Figure 4: scGPT
gene expression prediction" as a file path.
"""
from __future__ import annotations

import json
import os

import pytest
from pydantic import ValidationError

from schemas.dry_lab_schema import (
    ReproducibilityTarget, ExpectedOutput, classify_expected_output,
)


def test_expected_output_categories():
    for cat in ("file_path", "directory_path", "paper_deliverable",
                "geo_accession", "url", "unresolved"):
        e = ExpectedOutput(label="x", category=cat)
        assert e.category == cat


def test_expected_output_rejects_unknown_category():
    with pytest.raises(ValidationError):
        ExpectedOutput(label="x", category="random")


def test_classify_expected_output():
    assert classify_expected_output("results/figure_4.png") == "file_path"
    assert classify_expected_output("Figure 4: gene expression") == "paper_deliverable"
    assert classify_expected_output("GSE154763") == "geo_accession"
    assert classify_expected_output("https://zenodo.org/record/12345") == "url"
    assert classify_expected_output("checkpoints/") == "directory_path"
    assert classify_expected_output("A foundation model for single-cell biology") == "paper_deliverable"
    assert classify_expected_output("") == "unresolved"


def test_target_accepts_typed_expected_outputs():
    t = ReproducibilityTarget(
        paper_title="x",
        paper_source="https://example.com",
        expected_outputs=[
            ExpectedOutput(label="results/figure_4.png", category="file_path"),
            ExpectedOutput(label="Figure 4", category="paper_deliverable"),
        ],
    )
    assert len(t.expected_outputs) == 2
    assert t.expected_outputs[0].category == "file_path"
    assert t.expected_outputs[1].category == "paper_deliverable"


def test_target_accepts_legacy_strings_with_auto_classification():
    """Back-compat: existing on-disk protocols with List[str] must still
    load. Each string is auto-classified via classify_expected_output."""
    t = ReproducibilityTarget.model_validate({
        "paper_title": "x",
        "paper_source": "https://example.com",
        "expected_outputs": [
            "results/figure_4.png",
            "Figure 4",
            "GSE154763",
        ],
    })
    cats = [e.category for e in t.expected_outputs]
    assert cats == ["file_path", "paper_deliverable", "geo_accession"]


def test_target_loads_old_protocol_805f95c3():
    """The actual on-disk scGPT failure protocol must continue to load
    after the typing change. This is the regression sentinel.

    The artifact lives under the gitignored workspace/ dir, so it is absent
    in clean checkouts/CI — skip rather than fail there. The auto-classify
    behavior it guards is also covered inline by the two tests above.
    """
    proto_path = "workspace/extracted_protocols/protocol_805f95c3.json"
    if not os.path.exists(proto_path):
        pytest.skip(f"sentinel artifact not present: {proto_path}")
    proto = json.load(open(proto_path))
    t = ReproducibilityTarget.model_validate(proto)
    assert len(t.expected_outputs) == len(proto["expected_outputs"])
    # The scGPT protocol has multiple free-text paper-deliverable entries
    # like "A foundation model for single-cell multi-omics (scGPT)" and
    # "Figure 4: scGPT gene expression prediction" — they MUST be
    # auto-categorized as paper_deliverable, not file_path.
    assert any(e.category == "paper_deliverable" for e in t.expected_outputs)


def test_heterogeneous_input_mixed_strings_and_dicts():
    """The validator must accept a list mixing both shapes."""
    t = ReproducibilityTarget.model_validate({
        "paper_title": "x",
        "paper_source": "https://example.com",
        "expected_outputs": [
            "results/figure_4.png",
            {"label": "Figure 4", "category": "paper_deliverable"},
            {"label": "checkpoints/model.pt"},  # missing category → auto-classify
        ],
    })
    assert t.expected_outputs[0].category == "file_path"
    assert t.expected_outputs[1].category == "paper_deliverable"
    assert t.expected_outputs[2].category == "file_path"
