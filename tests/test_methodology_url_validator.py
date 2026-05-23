"""Tests for _filter_placeholder_urls and the ReproducibilityTarget validators."""

import pytest
from schemas.dry_lab_schema import ReproducibilityTarget, _filter_placeholder_urls


# ---------------------------------------------------------------------------
# _filter_placeholder_urls
# ---------------------------------------------------------------------------

def test_filter_rejects_question_mark_placeholder():
    kept, rejected = _filter_placeholder_urls([
        "https://doi.org/10.6084/m9.figshare.??",
        "https://github.com/foo/bar",
    ])
    assert kept == ["https://github.com/foo/bar"]
    assert rejected == ["https://doi.org/10.6084/m9.figshare.??"]


def test_filter_rejects_bare_service_names():
    kept, rejected = _filter_placeholder_urls([
        "Google Drive",
        "Zenodo",
        "https://zenodo.org/record/12345",
    ])
    assert kept == ["https://zenodo.org/record/12345"]
    assert set(rejected) == {"Google Drive", "Zenodo"}


def test_filter_rejects_angle_bracket_placeholder():
    kept, rejected = _filter_placeholder_urls([
        "https://zenodo.org/record/<placeholder>",
    ])
    assert kept == []
    assert rejected == ["https://zenodo.org/record/<placeholder>"]


def test_filter_empty_list():
    kept, rejected = _filter_placeholder_urls([])
    assert kept == []
    assert rejected == []


def test_filter_rejects_todo_marker():
    kept, rejected = _filter_placeholder_urls([
        "https://example.com/data/<TODO>",
        "https://example.com/real/path",
    ])
    assert kept == ["https://example.com/real/path"]
    assert rejected == ["https://example.com/data/<TODO>"]


def test_filter_rejects_ellipsis_continuation():
    kept, rejected = _filter_placeholder_urls([
        "https://example.com/data/...",
        "https://example.com/real/path",
    ])
    assert kept == ["https://example.com/real/path"]
    assert rejected == ["https://example.com/data/..."]


def test_filter_rejects_no_scheme():
    kept, rejected = _filter_placeholder_urls([
        "not-a-url",
        "https://example.com/real/path",
    ])
    assert kept == ["https://example.com/real/path"]
    assert "not-a-url" in rejected


# ---------------------------------------------------------------------------
# ReproducibilityTarget schema validator
# ---------------------------------------------------------------------------

def test_schema_validator_drops_placeholder_urls():
    target = ReproducibilityTarget(
        paper_title="Test Paper",
        paper_source="https://doi.org/10.1234/test",
        data_download_urls=[
            "https://doi.org/10.6084/m9.figshare.??",
            "https://zenodo.org/record/??",
            "https://zenodo.org/record/12345",
        ],
    )
    assert target.data_download_urls == ["https://zenodo.org/record/12345"]


def test_schema_validator_keeps_valid_urls():
    urls = [
        "https://zenodo.org/record/12345",
        "https://github.com/user/repo/releases/download/v1/data.zip",
        "https://figshare.com/articles/dataset/My_Dataset/123456",
    ]
    target = ReproducibilityTarget(
        paper_title="T",
        paper_source="https://doi.org/10.1234/x",
        data_download_urls=urls,
    )
    assert target.data_download_urls == urls


def test_schema_validator_github_url_placeholder_becomes_none():
    target = ReproducibilityTarget(
        paper_title="T",
        paper_source="https://doi.org/10.1234/x",
        github_url="https://github.com/??/??",
    )
    assert target.github_url is None


def test_schema_validator_github_url_valid_is_kept():
    target = ReproducibilityTarget(
        paper_title="T",
        paper_source="https://doi.org/10.1234/x",
        github_url="https://github.com/bowang-lab/scGPT",
    )
    assert target.github_url == "https://github.com/bowang-lab/scGPT"


def test_schema_validator_github_url_none_stays_none():
    target = ReproducibilityTarget(
        paper_title="T",
        paper_source="https://doi.org/10.1234/x",
        github_url=None,
    )
    assert target.github_url is None


def test_on_disk_protocol_805f95c3_drops_placeholders():
    """The known-bad on-disk protocol should round-trip cleanly with ?? URLs removed."""
    import json, pathlib
    path = pathlib.Path("workspace/extracted_protocols/protocol_805f95c3.json")
    if not path.exists():
        pytest.skip("On-disk protocol not present in this environment")
    with open(path) as f:
        raw = json.load(f)
    target = ReproducibilityTarget.model_validate(raw)
    for url in target.data_download_urls:
        assert "??" not in url, f"Placeholder URL survived validation: {url}"
