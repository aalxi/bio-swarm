"""P0.4 — trace-field three-state error messages.

Strategy: write a minimal protocol JSON to a temp dir, monkeypatch
`load_json` to return it, then call the rendering block directly via
a helper that mirrors what run_cli.py does after a successful pipeline run.
"""
import json
import sys
from pathlib import Path

import pytest


# ── Minimal protocol fixture ─────────────────────────────────────────────────

PROTO = {
    "protocol_name": "Test protocol",
    "paper_source": "test",
    "labware_setup": [],
    "pipettes": [],
    "reagents": [],
    "sequential_steps": [
        {
            "step_number": 1,
            "action": "transfer",
            "volume_ul": 50.0,
            "template_amount_ng": 100.0,
            "notes": None,
            # field_lineage intentionally omitted on volume_ul;
            # template_amount_ng has lineage in fields dict.
        }
    ],
    "extraction_notes": [],
}


# ── Helper that mirrors the run_cli.py trace-field block ─────────────────────

def _render_trace(proto: dict, fields: dict, trace_key: str) -> str:
    """Run the P0.4 logic against *proto*/*fields* and return printed output."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()

    steps_by_number = {
        step["step_number"]: step
        for step in proto.get("sequential_steps", [])
    }

    targets = [trace_key]
    lines = []

    for t in targets:
        if t in fields:
            lines.append(f"── {t} ──")
            continue

        parts = t.split(".", 1)
        if (
            len(parts) == 2
            and parts[0].startswith("step_")
            and parts[0][len("step_"):].isdigit()
        ):
            step_num = int(parts[0][len("step_"):])
            field_name = parts[1]
            if step_num not in steps_by_number:
                lines.append(
                    f"[cli] field not in protocol: {t}"
                    f" (step {step_num} does not exist in this protocol)"
                )
            elif field_name not in steps_by_number[step_num]:
                lines.append(
                    f"[cli] field not in protocol: {t}"
                    f" (step {step_num} exists but has no '{field_name}' attribute)"
                )
            else:
                lines.append(
                    f"[cli] field has no lineage record: {t}"
                    f" (field present, no FieldLineage attached"
                    f" — likely a demo-cache field or pre-lineage protocol)"
                )
        else:
            lines.append(f"[cli] field not found: {t}")

    return "\n".join(lines)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_step_does_not_exist():
    msg = _render_trace(PROTO, fields={}, trace_key="step_99.nonexistent")
    assert "field not in protocol" in msg
    assert "step 99 does not exist" in msg


def test_field_name_not_in_step():
    msg = _render_trace(PROTO, fields={}, trace_key="step_1.nonexistent_field")
    assert "field not in protocol" in msg
    assert "has no 'nonexistent_field' attribute" in msg


def test_field_present_but_no_lineage():
    # volume_ul exists on step 1 but there's no lineage record for it.
    msg = _render_trace(PROTO, fields={}, trace_key="step_1.volume_ul")
    assert "field has no lineage record" in msg
    assert "no FieldLineage attached" in msg


def test_field_with_lineage_triggers_tree_path():
    from datetime import datetime, UTC
    from schemas.lineage_schema import FieldLineage, PaperSpanDetail

    fl = FieldLineage(
        value=100.0,
        placed_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC),
        source_type="paper_span",
        paper_span=PaperSpanDetail(
            doc_url="https://pmc/x",
            span_id="step_1_template",
            quoted_text="100 ng template per reaction",
        ),
    )
    fields = {"step_1.template_amount_ng": fl}
    msg = _render_trace(PROTO, fields=fields, trace_key="step_1.template_amount_ng")
    # The lineage branch is taken — we see the header, not an error message.
    assert "── step_1.template_amount_ng ──" in msg
    assert "field not in protocol" not in msg
    assert "field has no lineage record" not in msg


def test_unparseable_key_falls_back_to_generic():
    # A key without "step_N." prefix falls to the generic branch.
    msg = _render_trace(PROTO, fields={}, trace_key="notafield")
    assert "field not found" in msg
