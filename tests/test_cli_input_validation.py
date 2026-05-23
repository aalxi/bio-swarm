"""P0.3 — CLI rejects empty/short --input and exits with code 2."""
import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "run_cli.py", *args],
        capture_output=True, text=True,
        cwd=None,  # run_cli.py sets its own cwd
    )


def test_empty_input_exits_2():
    result = _run("--mode", "wet_lab", "--input", "")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr!r}"
    )


def test_empty_input_stderr_message():
    result = _run("--mode", "wet_lab", "--input", "")
    assert "[cli] error:" in result.stderr
    assert "--input" in result.stderr


def test_short_input_exits_2():
    result = _run("--mode", "wet_lab", "--input", "pcr")
    assert result.returncode == 2


def test_short_input_stderr_contains_got():
    result = _run("--mode", "wet_lab", "--input", "pcr")
    assert "got:" in result.stderr


def test_seven_char_input_exits_2():
    # 7 non-whitespace chars — one short of the threshold
    result = _run("--mode", "wet_lab", "--input", "1234567")
    assert result.returncode == 2


def test_eight_char_input_does_not_reject_at_entry():
    # 8+ chars — validation passes (pipeline will still error without API keys,
    # so we only check the exit code is NOT 2).
    result = _run("--mode", "wet_lab", "--input", "12345678")
    assert result.returncode != 2


def test_demo_paper_bypasses_validation():
    # With --demo-paper set, short input like "demo" must NOT exit 2 at
    # validation time (it may fail later when the cache is missing, but the
    # input-validation guard must not fire).
    result = _run("--mode", "wet_lab", "--input", "demo", "--demo-paper", "rt-qpcr")
    # May exit 0 (cache present) or 1 (cache missing / network), never 2.
    assert result.returncode != 2
