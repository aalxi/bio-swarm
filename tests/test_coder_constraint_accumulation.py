"""P2.1 — constraint-accumulating retry loop. The wet-lab Coder's fix
prompt now carries an accumulated list of natural-language rules the
LLM has learned across prior attempts. The May-04 post-mortem showed
each retry introducing a fresh bug class because the LLM had no memory
of what the *previous* attempt got wrong.
"""
from __future__ import annotations

import pytest

from agents import coder


def test_fix_prompt_accepts_learned_constraints():
    """When called with non-empty learned_constraints, the fix prompt
    must list them under a 'LEARNED CONSTRAINTS' header."""
    prompt = coder._build_fix_user_payload(
        original_script="def run(p): pass",
        sim_stdout="ValueError: ...",
        learned_constraints=[
            "Always call .open_lid() before pipetting into a Thermocycler-mounted plate",
            "Use 'thermocycler module gen2' (spaces) not 'thermocycler_module_gen2'",
        ],
    )
    assert "LEARNED CONSTRAINTS" in prompt
    assert "open_lid()" in prompt
    assert "thermocycler module gen2" in prompt


def test_fix_prompt_with_no_constraints():
    prompt = coder._build_fix_user_payload(
        original_script="def run(p): pass",
        sim_stdout="ValueError: ...",
        learned_constraints=[],
    )
    assert "LEARNED CONSTRAINTS" not in prompt


def test_fix_response_returns_script_and_constraint(monkeypatch):
    """The fix LLM call must accept (and parse) a 'new_constraint' key."""
    canned = {
        "script": "from opentrons import protocol_api\n\ndef run(p): pass\n",
        "labware_substitutions": [],
        "new_constraint": "Always call .open_lid() before moving into Thermocycler labware.",
    }
    monkeypatch.setattr(coder, "_llm_json", lambda system, user: canned)
    script, subs, constraint = coder._fix_opentrons_script_v2(
        original_script="x", sim_stdout="y", learned_constraints=[],
    )
    assert script.startswith("from opentrons")
    assert subs == []
    assert constraint == "Always call .open_lid() before moving into Thermocycler labware."


def test_fix_response_handles_missing_new_constraint(monkeypatch):
    """Back-compat: if the LLM forgets to emit new_constraint, treat as empty."""
    canned = {
        "script": "from opentrons import protocol_api\n\ndef run(p): pass\n",
        "labware_substitutions": [],
        # no new_constraint key
    }
    monkeypatch.setattr(coder, "_llm_json", lambda system, user: canned)
    script, subs, constraint = coder._fix_opentrons_script_v2(
        original_script="x", sim_stdout="y", learned_constraints=[],
    )
    assert constraint == ""


def test_fix_prompt_orders_constraints_oldest_first():
    """The displayed order should be the order learned (chronological),
    so the LLM sees the longest-standing constraints first."""
    constraints = ["first lesson", "second lesson", "third lesson"]
    prompt = coder._build_fix_user_payload(
        original_script="x", sim_stdout="y", learned_constraints=constraints,
    )
    p1 = prompt.find("first lesson")
    p2 = prompt.find("second lesson")
    p3 = prompt.find("third lesson")
    assert 0 < p1 < p2 < p3


def test_fix_system_prompt_mentions_new_constraint():
    """The system prompt must instruct the LLM to emit new_constraint."""
    assert "new_constraint" in coder.WET_LAB_FIX_SYSTEM_PROMPT
