"""daytona_tool.py — zero coverage before this file.

The tool is a thin wrapper around the Daytona SDK. We don't test SDK behavior,
but we DO test the contract translation that callers (coder agent) depend on:
  - run_cmd / run_code return the {exit_code, stdout, success} dict shape
  - success is True iff exit_code == 0 (subtle: True for 0, False for any nonzero)
  - upload_file converts str → bytes
  - cleanup is exception-safe (Daytona delete failures must not break the pipeline)
"""
from tools import daytona_tool


class FakeExecResponse:
    def __init__(self, exit_code, result):
        self.exit_code = exit_code
        self.result = result


class FakeProcess:
    def __init__(self, exec_response=None, code_response=None):
        self._exec_response = exec_response
        self._code_response = code_response
        self.exec_calls = []
        self.code_calls = []

    def exec(self, command, cwd=None, timeout=None):
        self.exec_calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return self._exec_response

    def code_run(self, code, timeout=None):
        self.code_calls.append({"code": code, "timeout": timeout})
        return self._code_response


class FakeFS:
    def __init__(self):
        self.uploads = []
        self.download_payload = b"file bytes"

    def upload_file(self, content, remote_path):
        self.uploads.append({"content": content, "path": remote_path})

    def download_file(self, remote_path):
        return self.download_payload


class FakeGit:
    def __init__(self):
        self.clones = []

    def clone(self, url, dest_path):
        self.clones.append({"url": url, "dest": dest_path})


class FakeSandbox:
    def __init__(self, exec_response=None, code_response=None):
        self.process = FakeProcess(exec_response, code_response)
        self.fs = FakeFS()
        self.git = FakeGit()


# ── run_cmd ──────────────────────────────────────────────────────────────────


def test_run_cmd_returns_contract_dict_on_success():
    sandbox = FakeSandbox(exec_response=FakeExecResponse(0, "ok\n"))
    result = daytona_tool.run_cmd(sandbox, "ls")
    assert result == {"exit_code": 0, "stdout": "ok\n", "success": True}


def test_run_cmd_success_is_false_for_any_nonzero_exit():
    sandbox = FakeSandbox(exec_response=FakeExecResponse(1, "err"))
    assert daytona_tool.run_cmd(sandbox, "false")["success"] is False


def test_run_cmd_passes_cwd_and_timeout():
    sandbox = FakeSandbox(exec_response=FakeExecResponse(0, ""))
    daytona_tool.run_cmd(sandbox, "ls", cwd="/tmp", timeout=42)
    call = sandbox.process.exec_calls[0]
    assert call["cwd"] == "/tmp"
    assert call["timeout"] == 42


def test_run_cmd_defaults_match_documented_values():
    """Coder agent depends on the default /home/daytona cwd."""
    sandbox = FakeSandbox(exec_response=FakeExecResponse(0, ""))
    daytona_tool.run_cmd(sandbox, "ls")
    call = sandbox.process.exec_calls[0]
    assert call["cwd"] == "/home/daytona"
    assert call["timeout"] == 120


# ── run_code ─────────────────────────────────────────────────────────────────


def test_run_code_returns_contract_dict():
    sandbox = FakeSandbox(code_response=FakeExecResponse(0, "hello\n"))
    result = daytona_tool.run_code(sandbox, "print('hello')")
    assert result == {"exit_code": 0, "stdout": "hello\n", "success": True}


def test_run_code_success_flag_tracks_exit_code():
    sandbox = FakeSandbox(code_response=FakeExecResponse(2, "traceback"))
    assert daytona_tool.run_code(sandbox, "raise SystemExit(2)")["success"] is False


# ── upload_file ──────────────────────────────────────────────────────────────


def test_upload_file_encodes_str_to_bytes():
    """Caller may pass either str or bytes; SDK requires bytes."""
    sandbox = FakeSandbox()
    daytona_tool.upload_file(sandbox, "hello", "/tmp/x")
    assert sandbox.fs.uploads[0]["content"] == b"hello"


def test_upload_file_preserves_bytes_input():
    sandbox = FakeSandbox()
    daytona_tool.upload_file(sandbox, b"\x00\xff", "/tmp/x")
    assert sandbox.fs.uploads[0]["content"] == b"\x00\xff"


def test_upload_file_preserves_unicode():
    sandbox = FakeSandbox()
    daytona_tool.upload_file(sandbox, "µL 42°C", "/tmp/x")
    assert sandbox.fs.uploads[0]["content"] == "µL 42°C".encode("utf-8")


# ── download_file / clone_repo ───────────────────────────────────────────────


def test_download_file_returns_sdk_bytes_payload():
    sandbox = FakeSandbox()
    sandbox.fs.download_payload = b"abc"
    assert daytona_tool.download_file(sandbox, "/x") == b"abc"


def test_clone_repo_passes_url_and_dest_to_sdk():
    sandbox = FakeSandbox()
    daytona_tool.clone_repo(sandbox, "https://github.com/x/y", "/home/repo")
    assert sandbox.git.clones[0] == {
        "url": "https://github.com/x/y", "dest": "/home/repo",
    }


# ── cleanup ──────────────────────────────────────────────────────────────────


def test_cleanup_calls_delete():
    deleted = []

    class FakeDaytona:
        def delete(self, sb):
            deleted.append(sb)

    sandbox = FakeSandbox()
    daytona_tool.cleanup(FakeDaytona(), sandbox)
    assert deleted == [sandbox]


def test_cleanup_swallows_delete_errors():
    """If the sandbox is already gone or Daytona is unreachable, cleanup MUST
    NOT raise — the coder agent calls it from finally blocks."""

    class ExplodingDaytona:
        def delete(self, sb):
            raise ConnectionError("daytona is down")

    daytona_tool.cleanup(ExplodingDaytona(), FakeSandbox())  # must not raise
