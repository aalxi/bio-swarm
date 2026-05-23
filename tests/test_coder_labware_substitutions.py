"""P1.7 — labware_substitutions round-trips through the coder contract and into state."""
from agents.coder import _extract_substitutions, _contract


def test_extract_substitutions_basic():
    """Deep-well labware substituted for a shallow flat plate → volume-significant."""
    data = {
        "script": "...",
        "labware_substitutions": [
            {
                "original": "nest_96_wellplate_2ml_deep",
                "substituted": "nest_96_wellplate_200ul_flat",
                "reason": "deep-well not available, using flat plate",
            }
        ],
    }
    subs = _extract_substitutions(data)
    assert len(subs) == 1
    s = subs[0]
    assert s["original"] == "nest_96_wellplate_2ml_deep"
    assert s["substituted"] == "nest_96_wellplate_200ul_flat"
    assert s["reason"] == "deep-well not available, using flat plate"
    # Original has "_deep" / "2ml"; substituted has neither → volume-significant
    assert s["volume_significant"] is True


def test_extract_substitutions_tautological_filtered():
    """Same name on both sides → silently dropped."""
    data = {
        "script": "...",
        "labware_substitutions": [
            {
                "original": "opentrons_24_tuberack_nest_1.5ml_snapcap",
                "substituted": "opentrons_24_tuberack_nest_1.5ml_snapcap",
                "reason": "no change needed",
            }
        ],
    }
    subs = _extract_substitutions(data)
    assert subs == [], "Tautological substitution (same name both sides) must be filtered out"


def test_extract_substitutions_empty():
    data = {"script": "...", "labware_substitutions": []}
    subs = _extract_substitutions(data)
    assert subs == []


def test_extract_substitutions_missing_key():
    """LLM returned only 'script' key — no crash, return empty list."""
    data = {"script": "..."}
    subs = _extract_substitutions(data)
    assert subs == []


def test_extract_substitutions_volume_not_significant():
    """Substitution between two 200 µL flat plates → not volume-significant."""
    data = {
        "script": "...",
        "labware_substitutions": [
            {
                "original": "nest_96_wellplate_200ul_flat",
                "substituted": "corning_96_wellplate_360ul_flat",
                "reason": "Corning available in lab",
            }
        ],
    }
    subs = _extract_substitutions(data)
    assert len(subs) == 1
    # Neither name contains _deep / 2ml / 2.4ml tokens
    assert subs[0]["volume_significant"] is False


def test_contract_carries_labware_substitutions():
    subs = [{"original": "a", "substituted": "b", "reason": "x", "volume_significant": False}]
    result = _contract(
        "success", ["out.py"], "ok", 0, None,
        labware_substitutions=subs,
    )
    assert result["labware_substitutions"] == subs


def test_contract_default_empty_substitutions():
    result = _contract("error", [], "fail", 0, "bad")
    assert result["labware_substitutions"] == []
