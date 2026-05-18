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


import json
import os
import re
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Literal as _Literal

_VerifyResult = _Literal["verified", "content_mismatch", "unreachable"]

# Characters PMC HTML and rendered hyphenation insert that break naive ==
_WS_STRIP = "".join([
    " ",  # NBSP
    "­",  # soft hyphen
    "​",  # zero-width space
])
_SMART_MAP = str.maketrans(
    "–—‘’“”",  # –—''""
    "-" + "-" + "'" + "'" + '"' + '"',
)


def _normalize(s: str) -> str:
    """Casefold + strip noise unicode + collapse runs of whitespace.
    Used on both haystack (HTML body) and needle (quoted_text)."""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_SMART_MAP)
    for ch in _WS_STRIP:
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _fetch(url: str, timeout: float) -> str:
    """Plain GET; returns decoded body. Raises on network or HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": "BioSwarm/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body.decode("utf-8", errors="replace")


def _verify_one(citation: Citation, timeout_s: float) -> _VerifyResult:
    if citation.url is None or citation.quoted_text is None:
        return "verified"  # nothing to assert
    try:
        body = _fetch(citation.url, timeout_s)
    except Exception:
        return "unreachable"
    if _normalize(citation.quoted_text) in _normalize(body):
        return "verified"
    return "content_mismatch"


_CACHE_PATH = "workspace/.citation_cache.json"
_CACHE_TTL_S = 60 * 60 * 24  # 24h


def verify_at_startup(timeout_s: float = 10.0) -> dict[str, _VerifyResult]:
    """Verify every registry entry that has a URL. Persistent cache at
    workspace/.citation_cache.json (24h TTL). Three-state result per L7.
    Mutates each registry entry's `verification_status` in place.

    Failed entries log a warning but do not raise (L16 warn-and-flag)."""
    cache: dict[str, dict] = {}
    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    now = time.time()
    results: dict[str, _VerifyResult] = {}
    for key, citation in REGISTRY.items():
        cached = cache.get(key)
        if cached and (now - cached.get("at", 0)) < _CACHE_TTL_S:
            status = cached["status"]
        else:
            status = _verify_one(citation, timeout_s=timeout_s)
            cache[key] = {"status": status, "at": now}
        citation.verification_status = status
        results[key] = status
        if status != "verified":
            print(f"[citations] {key}: {status} ({citation.url})", flush=True)

    Path(os.path.dirname(_CACHE_PATH) or ".").mkdir(parents=True, exist_ok=True)
    try:
        with open(_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass
    return results
