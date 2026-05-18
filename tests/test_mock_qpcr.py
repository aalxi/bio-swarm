"""Mock qPCR oracle: continuous Cq curve, regime labeling, determinism."""
import math
import pytest

from tools.mock_qpcr import _cq_mean


def test_cq_mean_zero_template_returns_none():
    assert _cq_mean(0.0) is None
    assert _cq_mean(-1.0) is None


def test_cq_mean_below_detection_edge_returns_none():
    assert _cq_mean(0.4) is None


def test_cq_mean_log_linear_in_clean_regime():
    """slope -3.32 per decade in the clean regime (≤50 ng)."""
    cq_1 = _cq_mean(1.0)
    cq_10 = _cq_mean(10.0)
    cq_50 = _cq_mean(50.0)
    assert cq_1 is not None and cq_10 is not None and cq_50 is not None
    assert abs((cq_1 - cq_10) - 3.32) < 0.05
    assert cq_50 < cq_10 < cq_1


def test_cq_mean_inhibition_kicks_in_above_50_ng():
    """Above 50 ng the inhibition penalty pushes Cq UP (worse amplification)."""
    cq_50 = _cq_mean(50.0)
    cq_100 = _cq_mean(100.0)
    assert cq_100 > cq_50
    # Continuity at boundary: at exactly 50 ng penalty = 0
    cq_50_plus = _cq_mean(50.0001)
    assert abs(cq_50_plus - cq_50) < 0.05
