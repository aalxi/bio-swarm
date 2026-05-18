from pydantic import BaseModel
from typing import Optional, List, Literal


class ResearchState(BaseModel):
    done: bool = False
    files: List[str] = []
    sources: List[str] = []


class ExtractionState(BaseModel):
    done: bool = False
    protocol_file: Optional[str] = None
    schema_valid: bool = False


class EnrichmentState(BaseModel):
    done: bool = False
    enrichment_file: Optional[str] = None  # path to enrichment_{task_id}.json
    gaps_identified: int = 0
    gaps_filled: int = 0
    skipped: bool = False  # True if mode != wet_lab or PIE errored non-fatally


class CodingState(BaseModel):
    done: bool = False
    script_file: Optional[str] = None
    simulation_passed: bool = False
    error_log: Optional[str] = None
    retry_count: int = 0
    attempts: List[dict] = []
    liquid_step_coverage: Optional[float] = None
    fidelity_warning: bool = False
    skipped_step_numbers: List[int] = []
    coverage_method: Optional[Literal["markers", "heuristic_fallback"]] = None


class SynthesisState(BaseModel):
    done: bool = False
    report_file: Optional[str] = None
    attempted_on_failure: bool = False
    synthesized_on_failure: bool = False
    failed_at_phase: Optional[str] = None


class IterationOracleRecord(BaseModel):
    iteration_index: int
    code_file: str
    sim_passed: bool
    cq: Optional[float]
    regime_label: Literal[
        "clean", "inhibition_suspected", "low_copy_suspected", "no_amplification"
    ]
    raw_record_path: Optional[str]


class IterationRevision(BaseModel):
    iteration_index: int
    action: Literal[
        "converged", "reduce_template", "increase_template", "diagnose_required"
    ]
    field_changed: Optional[str] = None
    new_value: Optional[float] = None
    rationale: str
    citation_keys: List[str] = []
    citation_failure: bool = False


class IterationsState(BaseModel):
    done: bool = False
    enabled: bool = False
    iterations_completed: int = 0
    converged: bool = False
    cap_reached: bool = False
    diagnosis_required: bool = False
    records: List[IterationOracleRecord] = []
    revisions: List[IterationRevision] = []


class WorkspaceState(BaseModel):
    task_id: str
    mode: Literal["wet_lab", "dry_lab"]
    user_input: str
    status: Literal[
        "research", "extraction", "enrichment", "coding", "iteration",
        "simulation", "synthesis", "complete", "error"
    ]
    research: ResearchState = ResearchState()
    extraction: ExtractionState = ExtractionState()
    enrichment: EnrichmentState = EnrichmentState()
    coding: CodingState = CodingState()
    synthesis: SynthesisState = SynthesisState()
    iterations: IterationsState = IterationsState()
    errors: List[str] = []
