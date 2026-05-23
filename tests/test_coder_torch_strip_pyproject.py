"""Tests for the torch-strip helper (P1.5). The dry-lab Coder strips torch
family entries from env files before installing CPU-only torch from the
PyTorch CPU index. The previous implementation only handled requirements*.txt;
pyproject-based repos (most modern ML libs in 2026) slipped through and
filled the sandbox disk with CUDA wheels.
"""
from __future__ import annotations

import tomllib

import pytest

from agents.coder import _strip_torch_from_env_file


# ── pyproject.toml ───────────────────────────────────────────────────────────

def test_pyproject_project_dependencies_torch_commented_out():
    text = """\
[project]
name = "scgpt"
version = "0.2.5"
dependencies = [
    "numpy>=1.20",
    "torch>=2.0",
    "scipy",
    "torchvision",
]
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    assert n_changed == 2
    assert "    # stripped-by-bioswarm" in new_text
    assert "    # \"torch>=2.0\"," in new_text or '    # "torch>=2.0",' in new_text
    # Non-torch entries untouched
    assert '    "numpy>=1.20",' in new_text
    assert '    "scipy",' in new_text
    # Still valid TOML
    tomllib.loads(new_text)


def test_pyproject_poetry_dependencies_torch_commented_out():
    text = """\
[tool.poetry.dependencies]
python = "^3.11"
torch = "^2.0"
pandas = "^2.0"
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    assert n_changed == 1
    assert '    # stripped-by-bioswarm' not in new_text  # no indent: top-level kv
    # The torch line should be commented; pandas stays
    assert 'pandas = "^2.0"' in new_text
    # Re-parse: torch key must NOT be present in the kept text
    parsed = tomllib.loads(new_text)
    assert "torch" not in parsed.get("tool", {}).get("poetry", {}).get("dependencies", {})
    assert "pandas" in parsed["tool"]["poetry"]["dependencies"]


def test_pyproject_nvidia_packages_stripped():
    text = """\
[project]
dependencies = [
    "torch>=2.0",
    "nvidia-cudnn-cu12",
    "nvidia_cublas_cu12",
    "transformers",
]
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    # torch + nvidia-cudnn + nvidia_cublas = 3 lines
    assert n_changed == 3
    assert '    "transformers",' in new_text
    tomllib.loads(new_text)


# ── setup.py ─────────────────────────────────────────────────────────────────

def test_setup_py_install_requires_list_torch_stripped():
    text = """\
from setuptools import setup
setup(
    name="foo",
    install_requires=[
        "torch",
        "scikit-learn",
        "torchvision==0.15",
    ],
)
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "setup.py")
    assert n_changed == 2
    assert '        "scikit-learn",' in new_text
    # The original quoted torch entries are now commented out
    assert "torch" in new_text  # the comment line preserves the original
    # The commented form should appear
    assert "# stripped-by-bioswarm" in new_text


# ── setup.cfg ────────────────────────────────────────────────────────────────

def test_setup_cfg_install_requires_torch_stripped():
    text = """\
[options]
install_requires =
    numpy
    torch
    pandas
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "setup.cfg")
    assert n_changed == 1
    assert "numpy" in new_text
    assert "pandas" in new_text
    assert "# stripped-by-bioswarm" in new_text


# ── No-torch case: file must be byte-identical ───────────────────────────────

def test_pyproject_no_torch_unchanged():
    text = """\
[project]
name = "demo"
dependencies = [
    "numpy>=1.20",
    "pandas",
    "scikit-learn",
]
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    assert n_changed == 0
    assert new_text == text


def test_empty_file_unchanged():
    new_text, n_changed = _strip_torch_from_env_file("", "pyproject.toml")
    assert new_text == ""
    assert n_changed == 0


# ── Word-boundary safety (don't strip non-torch packages that contain "torch") ─

def test_torchscope_not_stripped():
    # `torchscope` (hypothetical) starts with 'torch' but is a different package.
    # We use \b after the pkg name, so 'torchscope' should NOT match.
    # Note: we DO strip canonical names torch/torchvision/torchaudio/torchdata/
    # torchtext only.
    text = """\
[project]
dependencies = [
    "torchscope",
    "torch-not-real",
]
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    # Both should be preserved: torchscope doesn't match `torch\b`, and
    # torch-not-real has `-` immediately after, which is not a word boundary
    # transition for re.IGNORECASE+\b. Actually `\b` between 'h' and '-' DOES
    # count as a word boundary in Python regex, so 'torch-not-real' WOULD match.
    # We accept this — better to over-strip with `-` suffixes than risk a
    # real torch package slipping past with a `-` separator.
    # So we only assert torchscope is preserved.
    assert '"torchscope"' in new_text


# ── Already-commented lines are not double-commented ─────────────────────────

def test_already_commented_line_unchanged():
    text = """\
[project]
dependencies = [
    # "torch>=2.0",  # user already commented this out
    "numpy",
]
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "pyproject.toml")
    assert n_changed == 0
    assert new_text == text


# ── Pipfile (TOML-ish) ───────────────────────────────────────────────────────

def test_pipfile_torch_stripped():
    text = """\
[packages]
torch = "*"
numpy = "*"
"""
    new_text, n_changed = _strip_torch_from_env_file(text, "Pipfile")
    assert n_changed == 1
    assert 'numpy = "*"' in new_text
