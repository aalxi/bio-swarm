"""Results-reader agent. Pure deterministic interpreter of QPCRReading →
FieldLineage(oracle_reading) record + IterationOracleRecord state entry.

No LLM call. The oracle measures; this reader interprets and types the
result. Side effects: mutates protocol JSON in place (appends a new head
lineage record whose .parent is the previous head)."""
from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any

from schemas.lineage_schema import FieldLineage, OracleReadingDetail
from tools.file_tool import load_json, save_json
from tools.mock_qpcr import QPCRReading


def _split_field_path(field_path: str) -> tuple[int, str]:
    """'step_3.template_amount_ng' -> (3, 'template_amount_ng')."""
    head, field = field_path.split(".", 1)
    assert head.startswith("step_"), f"unexpected field_path: {field_path}"
    return int(head[len("step_"):]), field


def _find_step(proto: dict, step_number: int) -> dict:
    for s in proto.get("sequential_steps", []):
        if s.get("step_number") == step_number:
            return s
    raise KeyError(f"step_{step_number} not in protocol")


def results_reader_agent(
    reading: QPCRReading,
    protocol_path: str,
    iteration_index: int,
    field_path: str,
) -> dict[str, Any]:
    """Append a FieldLineage(oracle_reading) record to the field's chain.
    Returns standard Agent Return Contract dict plus an 'oracle_record' extra.
    """
    try:
        proto = load_json(protocol_path)
        step_number, field_name = _split_field_path(field_path)
        step = _find_step(proto, step_number)
        prev_head_dict = step.get("field_lineage", {}).get(field_name)
        prev_head = (
            FieldLineage.model_validate(prev_head_dict) if prev_head_dict else None
        )

        new_head = FieldLineage(
            value=reading.template_ng,
            placed_at=datetime.now(UTC),
            source_type="oracle_reading",
            oracle_reading=OracleReadingDetail(
                instrument=reading.instrument,
                cq=reading.cq,
                ambiguous=reading.ambiguous,
                no_amplification=reading.no_amplification,
                regime_label=reading.regime_label,
                raw_record_path=reading.raw_record_path,
            ),
            citations=list(reading.citations),
            iteration_index=iteration_index,
            parent=prev_head,
        )
        step.setdefault("field_lineage", {})[field_name] = new_head.model_dump(
            mode="json"
        )
        save_json(proto, protocol_path)

        oracle_record = {
            "iteration_index": iteration_index,
            "code_file": f"workspace/generated_code/protocol_{proto.get('protocol_name', 'x')}.py",
            "sim_passed": True,
            "cq": reading.cq,
            "regime_label": reading.regime_label,
            "raw_record_path": reading.raw_record_path,
        }
        return {
            "status": "success",
            "output_files": [protocol_path],
            "message": f"oracle iter {iteration_index}: cq={reading.cq}, regime={reading.regime_label}",
            "retry_count": 0,
            "error_detail": None,
            "oracle_record": oracle_record,
        }
    except Exception as e:
        return {
            "status": "error",
            "output_files": [],
            "message": f"results_reader failed: {type(e).__name__}",
            "retry_count": 0,
            "error_detail": str(e),
        }
