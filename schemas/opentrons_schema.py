from pydantic import BaseModel
from typing import Optional, List, Literal


class ProtocolStep(BaseModel):
    step_number: int
    action: Literal["transfer", "distribute", "consolidate", "mix", "incubate", "centrifuge", "aspirate", "dispense"]
    volume_ul: Optional[float] = None
    source_location: Optional[str] = None
    destination_location: Optional[str] = None
    duration_seconds: Optional[int] = None
    speed_rpm: Optional[int] = None
    temperature_celsius: Optional[float] = None
    notes: Optional[str] = None
    # PIE enrichment metadata — None if this step was not enriched
    field_confidence: Optional[dict] = None   # e.g. {"volume_ul": 0.92, "temperature_celsius": 0.85}
    field_sources: Optional[dict] = None      # e.g. {"volume_ul": "https://protocols.io/..."}


class OpentronsProtocol(BaseModel):
    protocol_name: str
    paper_source: str
    labware_setup: List[str]
    pipettes: List[str]
    reagents: List[str]
    sequential_steps: List[ProtocolStep]
    extraction_notes: List[str]
    # PIE enrichment — False/None if enricher was not run
    pie_ran: bool = False
    enrichment_log: Optional[dict] = None
    # enrichment_log shape:
    # {
    #   "gaps_identified": int,
    #   "gaps_filled": int,
    #   "tavily_queries_executed": int,
    #   "fills": [{field, step_number, filled_value, confidence, source_url, rationale}],
    #   "conflicts": [{field, step_number, candidates, resolution, note}],
    #   "still_null": [{field, step_number, reason}]
    # }
