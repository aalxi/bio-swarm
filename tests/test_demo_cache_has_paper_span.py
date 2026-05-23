import json
from pathlib import Path
from schemas.lineage_schema import FieldLineage
from schemas.opentrons_schema import OpentronsProtocol

TYPED_FIELDS = {
    "volume_ul", "template_amount_ng", "temperature_celsius",
    "duration_seconds", "speed_rpm", "source_location",
    "destination_location",
}

def test_demo_cache_has_paper_span_for_every_typed_field():
    proto = json.loads(Path("workspace/demo_cache/rt_qpcr_protocol.json").read_text())
    OpentronsProtocol.model_validate(proto)  # still schema-valid
    for step in proto["sequential_steps"]:
        for field in TYPED_FIELDS:
            value = step.get(field)
            if value is None:
                continue
            fl_raw = (step.get("field_lineage") or {}).get(field)
            assert fl_raw is not None, (
                f"step {step['step_number']}.{field} = {value!r} has no lineage record"
            )
            fl = FieldLineage.model_validate(fl_raw)
            assert fl.source_type == "paper_span", (
                f"step {step['step_number']}.{field} lineage source_type was "
                f"{fl.source_type!r}, expected paper_span"
            )
            # citation invariant: any citation must resolve in the registry
            from tools.citation_registry import REGISTRY
            for k in fl.citations:
                assert k in REGISTRY, f"unregistered citation key {k!r}"
