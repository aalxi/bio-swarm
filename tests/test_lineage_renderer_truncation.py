"""P0.6 — word-boundary rationale truncation."""
import pytest

from tools.lineage_renderer import _truncate_rationale


def test_short_text_unchanged():
    text = "Short rationale."
    assert _truncate_rationale(text) == text


def test_exactly_160_chars_unchanged():
    text = "x" * 160
    assert _truncate_rationale(text) == text


def test_truncation_falls_on_word_boundary():
    # Build a string where a mid-word hard cut would give 'w' at position 160
    # but a word-boundary cut gives the last space before 160.
    # "hello " * 30 = 180 chars; last space before 160 is at position 156 (26*6=156).
    text = "hello " * 30  # 180 chars
    result = _truncate_rationale(text)
    assert result.endswith("…")
    # Strip the ellipsis and confirm no partial word.
    trimmed = result[:-1]  # remove "…"
    assert trimmed == trimmed.rstrip()  # no trailing partial word chars mid-space
    assert len(trimmed) <= 160


def test_ellipsis_appended_on_truncation():
    text = "word " * 40  # 200 chars
    result = _truncate_rationale(text)
    assert "…" in result


def test_no_ellipsis_when_no_truncation():
    text = "Short enough."
    result = _truncate_rationale(text)
    assert "…" not in result


def test_161_chars_truncated():
    text = "a" * 161
    result = _truncate_rationale(text)
    # No spaces → hard cut at 160 + ellipsis
    assert result == "a" * 160 + "…"


def test_word_boundary_correct_position():
    # "The quick brown fox " * 9 = 180 chars
    # Spaces at positions 3, 9, 15, 20, … Let's use a known string.
    text = ("The selected action is to reduce the template input because the "
            "current condition shows no amplification at a high template load "
            "(100 ng), which is consistent with inhibition or saturation effects "
            "and would benefit from further investigation.")
    result = _truncate_rationale(text)
    if len(text) > 160:
        assert result.endswith("…")
        trimmed = result[:-1]
        # The character just before the ellipsis must not be mid-word.
        # i.e. the character at trimmed[-1] is a space or end of word is a space.
        # More precisely: the full text at position len(trimmed) must be a space.
        assert text[len(trimmed)] == " ", (
            f"Truncation did not fall on space boundary; "
            f"char at cut position: {text[len(trimmed)]!r}"
        )
    else:
        assert "…" not in result
