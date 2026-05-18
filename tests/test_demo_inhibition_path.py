"""Demo seed + starting template MUST produce inhibition_suspected regime
with non-empty citations including PCR_inhibition_matrix_specific_schrader_2012.
Guards against silent regression where seed/value drift drops the demo
into no_amplification and the MIQE/Schrader citation chain doesn't fire."""
import pytest

from agents.supervisor import _seed_for
from tools.mock_qpcr import simulate_qpcr_well


DEMO_TASK_ID = "demo_rt_qpcr"
DEMO_STARTING_TEMPLATE_NG = 100.0


def test_demo_iter_1_is_inhibition_with_schrader_citation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reading = simulate_qpcr_well(
        DEMO_STARTING_TEMPLATE_NG,
        seed=_seed_for(DEMO_TASK_ID, 1),
        raw_record_dir=str(tmp_path / "iter1"),
    )
    assert reading.regime_label == "inhibition_suspected", (
        f"demo iter-1 regime drifted: got {reading.regime_label!r}; "
        f"citations were {reading.citations!r}"
    )
    assert "PCR_inhibition_matrix_specific_schrader_2012" in reading.citations, (
        f"demo iter-1 missing Schrader citation; got {reading.citations!r}"
    )
