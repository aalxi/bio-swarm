"""P2.5 — Coder consumes typed expected_outputs via _partition_expected_outputs,
no longer re-classifying free-text labels at consume time."""
from __future__ import annotations

from agents import coder
from schemas.dry_lab_schema import ExpectedOutput


def test_partition_typed_expected_outputs_objects():
    """Accepts a list of ExpectedOutput pydantic objects."""
    entries = [
        ExpectedOutput(label="results/figure_4.png", category="file_path"),
        ExpectedOutput(label="Figure 4", category="paper_deliverable"),
        ExpectedOutput(label="https://zenodo.org/record/x", category="url"),
        ExpectedOutput(label="GSE154763", category="geo_accession"),
    ]
    downloadable, paper_only = coder._partition_expected_outputs(entries)
    labels_d = {e["label"] for e in downloadable}
    labels_p = {e["label"] for e in paper_only}
    assert "results/figure_4.png" in labels_d
    assert "https://zenodo.org/record/x" in labels_d
    assert "Figure 4" in labels_p
    assert "GSE154763" in labels_p


def test_partition_typed_expected_outputs_dicts():
    """Accepts plain dicts (e.g. straight from JSON)."""
    entries = [
        {"label": "checkpoints/model.pt", "category": "file_path"},
        {"label": "results/", "category": "directory_path"},
        {"label": "unresolved string", "category": "unresolved"},
    ]
    downloadable, paper_only = coder._partition_expected_outputs(entries)
    labels_d = {e["label"] for e in downloadable}
    labels_p = {e["label"] for e in paper_only}
    # directory_path is downloadable (the repo may have populated the dir)
    assert "checkpoints/model.pt" in labels_d
    assert "results/" in labels_d
    assert "unresolved string" in labels_p


def test_partition_empty_input():
    downloadable, paper_only = coder._partition_expected_outputs([])
    assert downloadable == []
    assert paper_only == []


def test_partition_treats_pre_typed_strings_as_unresolved():
    """Defensive: if a raw string sneaks through (shouldn't, but might
    from a pre-validator on-disk protocol), it gets bucketed safely."""
    entries = ["something that should be typed"]
    downloadable, paper_only = coder._partition_expected_outputs(entries)
    assert downloadable == []
    # Bucketed as paper_only with category=unresolved
    assert len(paper_only) == 1
    assert paper_only[0]["category"] == "unresolved"


def test_old_classify_helper_removed_from_coder():
    """The old _classify_expected_output heuristic in coder.py is dead
    code now that the schema carries the type. Make sure we removed it
    so future contributors don't accidentally use the wrong helper."""
    assert not hasattr(coder, "_classify_expected_output"), (
        "coder._classify_expected_output should be deleted — the canonical "
        "classifier now lives in schemas.dry_lab_schema.classify_expected_output"
    )
