"""P2.3 + P2.4 — ProtocolStep gains applies_to_wells (per-well parallelism
scope) and out-of-scope action categories (FACS, Bioanalyzer, manual).
The May-04 post-mortem documented Smart-seq3's silent single-well-only
processing and the FACS-modeled-as-transfer category error.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.opentrons_schema import ProtocolStep


def test_default_applies_to_wells_is_plate():
    s = ProtocolStep(step_number=1, action="transfer")
    assert s.applies_to_wells == "plate"
    assert s.custom_wells is None


def test_applies_to_wells_accepts_known_values():
    for v in ("A1_only", "row", "column", "plate", "custom"):
        kwargs = {"step_number": 1, "action": "transfer", "applies_to_wells": v}
        if v == "custom":
            kwargs["custom_wells"] = ["A1"]
        s = ProtocolStep(**kwargs)
        assert s.applies_to_wells == v


def test_applies_to_wells_rejects_unknown_values():
    with pytest.raises(ValidationError):
        ProtocolStep(step_number=1, action="transfer", applies_to_wells="diagonal")


def test_custom_wells_required_when_applies_to_wells_custom():
    with pytest.raises(ValidationError):
        ProtocolStep(step_number=1, action="transfer", applies_to_wells="custom")
    s = ProtocolStep(
        step_number=1, action="transfer",
        applies_to_wells="custom", custom_wells=["A1", "B1", "C1"],
    )
    assert s.custom_wells == ["A1", "B1", "C1"]


def test_custom_wells_forbidden_when_not_custom():
    with pytest.raises(ValidationError):
        ProtocolStep(
            step_number=1, action="transfer", applies_to_wells="plate",
            custom_wells=["A1"],
        )


def test_out_of_scope_actions_accepted():
    for v in ("out_of_scope_setup", "out_of_scope_qc",
              "off_deck_instrument", "manual_only"):
        s = ProtocolStep(step_number=1, action=v)
        assert s.action == v
        # OOS steps default to "plate" scope (same as other steps); coder
        # treats them specially anyway since they emit only protocol.comment().
        assert s.applies_to_wells == "plate"


def test_original_actions_still_accepted():
    for v in ("transfer", "distribute", "consolidate", "mix",
              "incubate", "centrifuge", "aspirate", "dispense"):
        s = ProtocolStep(step_number=1, action=v)
        assert s.action == v


def test_demo_cache_still_loads_after_schema_change():
    """The hand-authored demo cache (with paper_span lineage records,
    pre-existing action='transfer'/'incubate') must continue to validate.
    """
    import json
    from schemas.opentrons_schema import OpentronsProtocol
    proto = json.loads(open("workspace/demo_cache/rt_qpcr_protocol.json").read())
    OpentronsProtocol.model_validate(proto)
