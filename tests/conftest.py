"""Shared pytest fixtures for BioSwarm tests."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, UTC
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_workspace(tmp_path, monkeypatch):
    """Run the test in a temporary CWD with workspace/ subdirs created."""
    for d in [
        "workspace",
        "workspace/raw_research",
        "workspace/extracted_protocols",
        "workspace/generated_code",
        "workspace/final_reports",
        "workspace/iterations",
        "workspace/lineage",
        "workspace/demo_cache",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def frozen_now(monkeypatch):
    """Freeze datetime.now(UTC) to a fixed instant for deterministic ids."""
    fixed = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    import schemas.lineage_schema as ls
    monkeypatch.setattr(ls, "datetime", _FrozenDT, raising=False)
    return fixed
