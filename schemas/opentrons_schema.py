from typing import Optional, List, Literal
from pydantic import BaseModel, model_validator

from schemas.lineage_schema import FieldLineage


class ProtocolStep(BaseModel):
    step_number: int
    action: Literal[
        # Standard liquid-handling actions (Coder emits real ops for these)
        "transfer", "distribute", "consolidate", "mix",
        "incubate", "centrifuge", "aspirate", "dispense",
        # P2.4 — out-of-scope categories. Coder emits ONLY protocol.comment()
        # for these; coverage detector excludes them from the denominator so
        # an honest protocol with 4 in-scope LH steps + 3 off-deck steps shows
        # 100% coverage, not 4/7.
        "out_of_scope_setup",       # cell prep, sample staging, off-deck handoff
        "out_of_scope_qc",          # Bioanalyzer, Qubit, Tapestation, Nanodrop, gel
        "off_deck_instrument",      # FACS sorter, plate reader, separate thermocycler
        "manual_only",              # hammering tubes, manual UV exposure, bench chemistry
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

    # P2.3 — does this step apply to one well, a row, a column, the whole
    # plate, or a custom list? Default "plate" because most steps in a real
    # protocol parallelize across all wells. Coder emits `for well in
    # plate.wells():` accordingly. Smart-seq3-class protocols used to
    # silently process only A1 because this concept didn't exist.
    applies_to_wells: Literal[
        "A1_only", "row", "column", "plate", "custom"
    ] = "plate"
    custom_wells: Optional[List[str]] = None

    @model_validator(mode="after")
    def _custom_wells_consistency(self) -> "ProtocolStep":
        if self.applies_to_wells == "custom" and not self.custom_wells:
            raise ValueError(
                "applies_to_wells='custom' requires a non-empty custom_wells list"
            )
        if self.applies_to_wells != "custom" and self.custom_wells is not None:
            raise ValueError(
                f"applies_to_wells={self.applies_to_wells!r} must not set custom_wells "
                "(use applies_to_wells='custom' if you need an explicit list)"
            )
        return self


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
