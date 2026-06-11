"""synthesizer.py artifact-collection helpers — previously only the lineage
renderer was covered. These functions assemble the LLM payload from on-disk
state; if they silently drop or mislabel artifacts, the final report degrades
without any error. No LLM is called here.
"""
import json

from agents.synthesizer import _collect_research_bundle, _read_file_if_exists
from tools.file_tool import save_json, save_text


# ── _read_file_if_exists ─────────────────────────────────────────────────────


def test_read_returns_none_for_missing_path(tmp_workspace):
    label, content = _read_file_if_exists("workspace/raw_research/nope.json")
    assert content is None
    assert label == "workspace/raw_research/nope.json"


def test_read_returns_none_for_empty_path(tmp_workspace):
    label, content = _read_file_if_exists("")
    assert content is None


def test_read_json_is_pretty_printed(tmp_workspace):
    path = "workspace/raw_research/x.json"
    save_json({"b": 2, "a": 1}, path)
    label, content = _read_file_if_exists(path)
    # Pretty-printed (indent=2) so the LLM sees readable structure.
    assert "\n" in content
    assert json.loads(content) == {"b": 2, "a": 1}


def test_read_json_preserves_unicode(tmp_workspace):
    path = "workspace/raw_research/u.json"
    save_json({"note": "70 µL at 42°C"}, path)
    _, content = _read_file_if_exists(path)
    assert "µL" in content and "42°C" in content  # ensure_ascii=False


def test_read_text_returns_raw_content(tmp_workspace):
    path = "workspace/raw_research/notes.txt"
    save_text("plain text body", path)
    _, content = _read_file_if_exists(path)
    assert content == "plain text body"


def test_read_directory_path_returns_none(tmp_workspace):
    """isfile() guard: a directory is not a readable artifact."""
    _, content = _read_file_if_exists("workspace/raw_research")
    assert content is None


# ── _collect_research_bundle ─────────────────────────────────────────────────


def test_bundle_includes_combined_file_even_when_not_in_state(tmp_workspace):
    """The combined research file is always appended, so synthesis sees the
    research summary even if state didn't list it."""
    save_json({"sources": ["http://x"]}, "workspace/raw_research/T1_combined.json")
    bundle = _collect_research_bundle({"research": {"files": []}}, "T1")
    assert "T1_combined.json" in bundle
    assert "http://x" in bundle


def test_bundle_marks_missing_files_without_crashing(tmp_workspace):
    """A path listed in state but absent on disk must be flagged, not fatal."""
    bundle = _collect_research_bundle(
        {"research": {"files": ["workspace/raw_research/gone.json"]}}, "T2"
    )
    assert "gone.json" in bundle
    assert "<missing or not found>" in bundle


def test_bundle_deduplicates_repeated_paths(tmp_workspace):
    """Same path listed twice (and once more as the combined file) must be
    inlined only once."""
    p = "workspace/raw_research/T3_combined.json"
    save_json({"k": "v"}, p)
    bundle = _collect_research_bundle({"research": {"files": [p, p]}}, "T3")
    assert bundle.count(f"--- {p} ---") == 1


def test_bundle_tolerates_missing_research_key(tmp_workspace):
    """state with no 'research' entry must not raise (None-safe)."""
    bundle = _collect_research_bundle({}, "T4")
    assert isinstance(bundle, str)  # combined-file chunk only
