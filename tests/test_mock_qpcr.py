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


import os
from tools.mock_qpcr import _label_regime


def test_label_regime_no_amp_high_template_is_inhibition():
    regime, cites = _label_regime(
        template_ng=200.0, cq=None, ambiguous=False, no_amp=True,
    )
    assert regime == "inhibition_suspected"
    assert "MIQE_essential_inhibition_testing" in cites
    assert "PCR_inhibition_matrix_specific_schrader_2012" in cites


def test_label_regime_no_amp_low_template_is_low_copy():
    regime, cites = _label_regime(
        template_ng=0.5, cq=None, ambiguous=False, no_amp=True,
    )
    assert regime == "low_copy_suspected"
    assert "MIQE_essential_linear_dynamic_range" in cites


def test_label_regime_ambiguous_high_template_is_inhibition():
    regime, cites = _label_regime(
        template_ng=100.0, cq=35.0, ambiguous=True, no_amp=False,
    )
    assert regime == "inhibition_suspected"
    assert "common_practice_cq_gray_zone" in cites


def test_label_regime_ambiguous_low_template_is_low_copy():
    regime, cites = _label_regime(
        template_ng=2.0, cq=35.0, ambiguous=True, no_amp=False,
    )
    assert regime == "low_copy_suspected"


def test_label_regime_clean_returns_no_citations():
    regime, cites = _label_regime(
        template_ng=25.0, cq=27.4, ambiguous=False, no_amp=False,
    )
    assert regime == "clean"
    assert cites == []


from tools.mock_qpcr import simulate_qpcr_well


def test_simulate_well_is_deterministic_under_seed(tmp_workspace):
    r1 = simulate_qpcr_well(25.0, seed=42, raw_record_dir="workspace/iterations/1")
    r2 = simulate_qpcr_well(25.0, seed=42, raw_record_dir="workspace/iterations/1")
    assert r1.cq == r2.cq
    assert r1.regime_label == r2.regime_label


def test_simulate_well_writes_raw_csv(tmp_workspace):
    r = simulate_qpcr_well(25.0, seed=42, raw_record_dir="workspace/iterations/1")
    assert os.path.exists(r.raw_record_path)
    with open(r.raw_record_path) as f:
        content = f.read()
    assert "template_ng" in content
    assert "cq" in content


def test_simulate_well_high_template_inhibition_regime(tmp_workspace):
    r = simulate_qpcr_well(100.0, seed=42, raw_record_dir="workspace/iterations/1")
    assert r.regime_label == "inhibition_suspected"
    assert "PCR_inhibition_matrix_specific_schrader_2012" in r.citations
