"""token_tracker.py — zero coverage before this file.

Tests cover:
  - track_call() correctly extracts usage from OpenAI-shaped responses
  - track_call() is a safe no-op when usage is missing (older models, errors)
  - print_summary() handles empty + multi-agent ledger without crashing
  - reset() actually clears the module-level ledger between runs
  - estimate_tokens() returns sensible counts and falls back for unknown models
"""
from types import SimpleNamespace

import pytest

from tools import token_tracker


@pytest.fixture(autouse=True)
def _clean_ledger():
    """Module-level _ledger leaks across tests without this."""
    token_tracker.reset()
    yield
    token_tracker.reset()


def _fake_response(prompt: int, completion: int, total: int):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
    )


def test_track_call_records_one_entry_per_call():
    token_tracker.track_call("agent_a", _fake_response(10, 5, 15))
    token_tracker.track_call("agent_a", _fake_response(20, 8, 28))
    assert len(token_tracker._ledger["agent_a"]) == 2


def test_track_call_separates_agents():
    token_tracker.track_call("researcher", _fake_response(100, 50, 150))
    token_tracker.track_call("coder", _fake_response(200, 75, 275))
    assert set(token_tracker._ledger.keys()) == {"researcher", "coder"}


def test_track_call_is_noop_when_response_has_no_usage():
    """OpenAI streaming responses and error responses can lack usage; agents
    log every call, so a None-safe path is required."""
    response_without_usage = SimpleNamespace(usage=None)
    token_tracker.track_call("agent", response_without_usage)
    assert "agent" not in token_tracker._ledger


def test_track_call_coerces_none_usage_fields_to_zero():
    """Anthropic compat layers sometimes return None for unused fields."""
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=None, total_tokens=10,
        )
    )
    token_tracker.track_call("agent", response)
    assert token_tracker._ledger["agent"][0]["completion_tokens"] == 0


def test_reset_clears_all_agents():
    token_tracker.track_call("a", _fake_response(1, 1, 2))
    token_tracker.track_call("b", _fake_response(1, 1, 2))
    token_tracker.reset()
    assert token_tracker._ledger == {}


def test_print_summary_empty_ledger_does_not_crash(capsys):
    token_tracker.print_summary()
    out = capsys.readouterr().out
    assert "No OpenAI calls recorded" in out


def test_print_summary_aggregates_per_agent_and_grand_total(capsys):
    token_tracker.track_call("researcher", _fake_response(100, 50, 150))
    token_tracker.track_call("researcher", _fake_response(200, 100, 300))
    token_tracker.track_call("coder", _fake_response(500, 250, 750))
    token_tracker.print_summary()
    out = capsys.readouterr().out
    assert "researcher" in out and "coder" in out
    # Grand total = 150 + 300 + 750 = 1,200
    assert "1,200" in out


def test_estimate_tokens_returns_positive_count_for_nonempty_text():
    assert token_tracker.estimate_tokens("hello world") > 0


def test_estimate_tokens_returns_zero_for_empty_string():
    assert token_tracker.estimate_tokens("") == 0


def test_estimate_tokens_falls_back_for_unrecognized_model():
    """estimate_tokens MUST NOT raise on unknown model names — agents pass
    arbitrary model strings (gpt-5.4-mini etc.) that tiktoken may not know."""
    count = token_tracker.estimate_tokens("hello", model="some-future-model-9000")
    assert count > 0
