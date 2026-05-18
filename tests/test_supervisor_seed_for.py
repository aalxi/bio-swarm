"""Stable seed across processes (reviewer issue #8). Python's hash() is
salted per-process; md5 is not."""
from agents.supervisor import _seed_for


def test_seed_for_is_deterministic_for_same_input():
    s1 = _seed_for("task_abc", 1)
    s2 = _seed_for("task_abc", 1)
    assert s1 == s2


def test_seed_for_differs_per_iteration():
    assert _seed_for("task_abc", 1) != _seed_for("task_abc", 2)


def test_seed_for_differs_per_task_id():
    assert _seed_for("task_abc", 1) != _seed_for("task_def", 1)


def test_seed_for_fits_in_32_bits():
    s = _seed_for("task_abc", 1)
    assert 0 <= s < (1 << 32)
