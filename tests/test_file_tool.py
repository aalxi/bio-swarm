"""file_tool.py — used everywhere; zero coverage before this file.

Tests focus on behavior that would actually break callers:
  - parent directories auto-created (callers rely on this)
  - round-trip preserves data (json types, unicode)
  - error surface (FileNotFoundError, json.JSONDecodeError) is raised as-is
"""
import json

import pytest

from tools.file_tool import load_json, load_text, save_json, save_text


def test_save_json_creates_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "out.json"
    save_json({"x": 1}, str(nested))
    assert nested.exists()
    assert json.loads(nested.read_text()) == {"x": 1}


def test_save_text_creates_parent_directories(tmp_path):
    nested = tmp_path / "deep" / "nested" / "file.txt"
    save_text("hello", str(nested))
    assert nested.read_text() == "hello"


def test_save_json_returns_the_path(tmp_path):
    path = str(tmp_path / "x.json")
    assert save_json({}, path) == path


def test_save_json_overwrites_existing_file(tmp_path):
    path = str(tmp_path / "x.json")
    save_json({"v": 1}, path)
    save_json({"v": 2}, path)
    assert load_json(path) == {"v": 2}


def test_save_json_preserves_unicode_and_nested_types(tmp_path):
    path = str(tmp_path / "u.json")
    data = {"emoji_text": "µL ° °C", "nested": {"list": [1, 2.5, None, True]}}
    save_json(data, path)
    assert load_json(path) == data


def test_load_json_raises_filenotfound_for_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json(str(tmp_path / "does_not_exist.json"))


def test_load_json_raises_decode_error_for_malformed_content(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        load_json(str(path))


def test_save_text_overwrites_not_appends(tmp_path):
    path = str(tmp_path / "t.txt")
    save_text("first", path)
    save_text("second", path)
    assert load_text(path) == "second"
