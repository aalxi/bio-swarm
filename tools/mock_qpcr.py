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
