from typing import Optional, List, Literal
from pydantic import BaseModel

from schemas.lineage_schema import FieldLineage


class ProtocolStep(BaseModel):
    step_number: int
    action: Literal[
        "transfer", "distribute", "consolidate", "mix",
        "incubate", "centrifuge", "aspirate", "dispense",
    ]
    volume_ul: Optional[float] = None
    template_amount_ng: Optional[float] = None
    source_location: Optional[str] = None
    destination_location: Optional[str] = None
    duration_seconds: Optional[int] = None
    speed_rpm: Optional[int] = None
    temperature_celsius: Optional[float] = None
    notes: Optional[str] = None
    # REPLACED: field_confidence + field_sources -> field_lineage
    field_lineage: dict[str, FieldLineage] = {}


class OpentronsProtocol(BaseModel):
    protocol_name: str
    paper_source: str
    labware_setup: List[str]
    pipettes: List[str]
    reagents: List[str]
    sequential_steps: List[ProtocolStep]
    extraction_notes: List[str]
    pie_ran: bool = False
    enrichment_log: Optional[dict] = None
