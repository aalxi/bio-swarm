"""Replanner LLM narration + citation-failure fallback (L21)."""
import json
import pytest

from agents.replanner import _llm_call_with_retry


class FakeChoice:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class FakeResp:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]
        self.usage = type("U", (), {
            "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
        })


def test_first_attempt_passes_with_real_keys(monkeypatch):
    payload = json.dumps({
        "rationale": "optimal range per MIQE",
        "citation_keys": ["MIQE_essential_reaction_volume_and_template"],
    })

    def fake_create(**kw): return FakeResp(payload)
    import agents.replanner as rp
    monkeypatch.setattr(rp, "_chat_completion", fake_create)

    rationale, keys, failure = _llm_call_with_retry(
        prompt="x", action="converged",
        rule_id="rule.converged.clean_optimal_range",
    )
    assert "optimal" in rationale
    assert keys == ["MIQE_essential_reaction_volume_and_template"]
    assert failure is False


def test_first_attempt_hallucinated_key_retried_succeeds(monkeypatch):
    """First call returns a fake key; second call returns a real one."""
    responses = [
        json.dumps({"rationale": "x", "citation_keys": ["Bustle_2009"]}),
        json.dumps({
            "rationale": "x",
            "citation_keys": ["MIQE_essential_reaction_volume_and_template"],
        }),
    ]
    import agents.replanner as rp

    def fake_create(**kw): return FakeResp(responses.pop(0))
    monkeypatch.setattr(rp, "_chat_completion", fake_create)

    _, keys, failure = _llm_call_with_retry(
        prompt="x", action="converged", rule_id="rule.converged.clean_optimal_range",
    )
    assert keys == ["MIQE_essential_reaction_volume_and_template"]
    assert failure is False


def test_two_consecutive_failures_emit_deterministic_string(monkeypatch):
    """L21: rationale text is REPLACED entirely; no preserved LLM prose."""
    responses = [
        json.dumps({"rationale": "per Schrader 2012", "citation_keys": ["fake_a"]}),
        json.dumps({"rationale": "per Bustin 2009", "citation_keys": ["fake_b"]}),
    ]
    import agents.replanner as rp

    def fake_create(**kw): return FakeResp(responses.pop(0))
    monkeypatch.setattr(rp, "_chat_completion", fake_create)

    rationale, keys, failure = _llm_call_with_retry(
        prompt="x", action="reduce_template",
        rule_id="rule.ambiguous.high_template.reduce",
    )
    assert keys == []
    assert failure is True
    assert "Citation validation failed" in rationale
    assert "rule.ambiguous.high_template.reduce" in rationale
    assert "Schrader" not in rationale
    assert "Bustin" not in rationale
