"""Mock qPCR oracle. Models a continuous Cq(template_ng) function with a
log-linear standard-curve slope in the clean regime and a superlinear
inhibition penalty above 50 ng (demo scenario per Schrader 2012,
matrix-specific inhibition; values are demo parameters, not paper-derived).
"""
from __future__ import annotations

import csv
import math
import os
import random
from typing import Literal, Optional

from pydantic import BaseModel


class QPCRReading(BaseModel):
    template_ng: float
    cq: Optional[float]
    ambiguous: bool
    no_amplification: bool
    regime_label: Literal[
        "clean", "inhibition_suspected", "low_copy_suspected", "no_amplification"
    ]
    raw_record_path: str
    instrument: Literal["mock_qpcr_v1"] = "mock_qpcr_v1"
    citations: list[str] = []


def _cq_mean(template_ng: float) -> Optional[float]:
    """Continuous Cq(template) model. Returns None below detection."""
    if template_ng <= 0.0:
        return None
    if template_ng < 0.5:
        return None
    log_linear = 32.0 - 3.32 * math.log10(template_ng)
    inhibition = 0.0
    if template_ng > 50.0:
        inhibition = 0.07 * (template_ng - 50.0) ** 1.4
    return log_linear + inhibition


def _label_regime(
    template_ng: float, cq: Optional[float], ambiguous: bool, no_amp: bool,
) -> tuple[str, list[str]]:
    if no_amp and template_ng > 50:
        return "inhibition_suspected", [
            "MIQE_essential_inhibition_testing",
            "PCR_inhibition_matrix_specific_schrader_2012",
        ]
    if no_amp and template_ng < 1:
        return "low_copy_suspected", ["MIQE_essential_linear_dynamic_range"]
    if no_amp:
        return "no_amplification", []
    if ambiguous and template_ng > 50:
        return "inhibition_suspected", [
            "MIQE_essential_inhibition_testing",
            "PCR_inhibition_matrix_specific_schrader_2012",
            "common_practice_cq_gray_zone",
        ]
    if ambiguous and template_ng < 5:
        return "low_copy_suspected", [
            "MIQE_essential_linear_dynamic_range",
            "common_practice_cq_gray_zone",
        ]
    if ambiguous:
        return "inhibition_suspected", [
            "PCR_inhibition_matrix_specific_schrader_2012",
            "common_practice_cq_gray_zone",
        ]
    return "clean", []


def _write_csv(raw_record_dir: str, template_ng: float,
               cq: Optional[float], regime: str) -> str:
    os.makedirs(raw_record_dir, exist_ok=True)
    path = os.path.join(raw_record_dir, f"qpcr_raw_{int(template_ng*100)}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["template_ng", "cq", "regime_label"])
        w.writerow([template_ng, "" if cq is None else cq, regime])
    return path


def simulate_qpcr_well(template_ng: float, *, seed: int,
                       raw_record_dir: str) -> QPCRReading:
    rng = random.Random(seed)
    mean = _cq_mean(template_ng)
    if mean is None:
        cq: Optional[float] = None
        no_amp = True
    else:
        noisy = mean + rng.gauss(0.0, 0.4)
        if noisy > 40.0:
            cq, no_amp = None, True
        else:
            cq, no_amp = round(noisy, 2), False

    ambiguous = (cq is not None) and (33.0 <= cq <= 37.0)
    regime, citations = _label_regime(template_ng, cq, ambiguous, no_amp)
    raw_path = _write_csv(raw_record_dir, template_ng, cq, regime)
    return QPCRReading(
        template_ng=template_ng, cq=cq, ambiguous=ambiguous,
        no_amplification=no_amp, regime_label=regime,
        raw_record_path=raw_path, citations=citations,
    )
