"""Citation registry — single source of truth for every citation key used in
FieldLineage records. Every `FieldLineage.citations[]` entry must be a key
that resolves here. Raw URLs are not permitted in lineage records.

Verification (`verify_at_startup`) is three-state: verified / content_mismatch
/ unreachable. Network failures must not crash startup (L16 warn-and-flag).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    key: str
    citation_type: Literal["paper", "guideline_checklist_item", "common_practice"]
    full_text: str
    url: Optional[str] = None
    doi: Optional[str] = None
    quoted_text: Optional[str] = None
    verification_status: Literal[
        "verified", "content_mismatch", "unreachable", "unchecked"
    ] = "unchecked"


# ── Seed entries (v1) ────────────────────────────────────────────────────────
REGISTRY: dict[str, Citation] = {
    "MIQE_2009": Citation(
        key="MIQE_2009",
        citation_type="paper",
        full_text=(
            "Bustin SA et al. (2009). The MIQE guidelines: minimum information "
            "for publication of quantitative real-time PCR experiments. "
            "Clinical Chemistry 55(4):611–622."
        ),
        url="https://doi.org/10.1373/clinchem.2008.112797",
        doi="10.1373/clinchem.2008.112797",
        quoted_text=None,
    ),
    "MIQE_essential_inhibition_testing": Citation(
        key="MIQE_essential_inhibition_testing",
        citation_type="guideline_checklist_item",
        full_text="MIQE essential item: Inhibition testing (Cq dilutions, spike or other).",
        url="https://rdml.org/miqe.html",
        quoted_text="Inhibition testing (Cq dilutions, spike or other)",
    ),
    "MIQE_essential_linear_dynamic_range": Citation(
        key="MIQE_essential_linear_dynamic_range",
        citation_type="guideline_checklist_item",
        full_text="MIQE essential item: Linear dynamic range.",
        url="https://rdml.org/miqe.html",
        quoted_text="Linear dynamic range",
    ),
    "MIQE_essential_reaction_volume_and_template": Citation(
        key="MIQE_essential_reaction_volume_and_template",
        citation_type="guideline_checklist_item",
        full_text="MIQE essential item: Reaction volume and amount of cDNA/DNA.",
        url="https://rdml.org/miqe.html",
        quoted_text="Reaction volume and amount of cDNA/DNA",
    ),
    "common_practice_cq_gray_zone": Citation(
        key="common_practice_cq_gray_zone",
        citation_type="common_practice",
        full_text=(
            "Common laboratory practice (not MIQE): Cq values between ~33 and ~37 "
            "are often treated as a gray zone where amplification is detectable "
            "but inhibitor presence, low template copy number, or primer issues "
            "should be considered before reporting."
        ),
        url=None,
        quoted_text=None,
    ),
    "PCR_inhibition_matrix_specific_schrader_2012": Citation(
        key="PCR_inhibition_matrix_specific_schrader_2012",
        citation_type="paper",
        full_text=(
            "Schrader C et al. (2012). PCR inhibitors — occurrence, properties "
            "and removal. Journal of Applied Microbiology 113(5):1014–1026."
        ),
        url="https://pubmed.ncbi.nlm.nih.gov/22747964/",
        doi="10.1111/j.1365-2672.2012.05384.x",
        quoted_text=(
            "Some of them are predominantly found in specific types of samples "
            "thus necessitating matrix-specific protocols"
        ),
    ),
}
