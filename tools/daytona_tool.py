import os
from daytona import Daytona, DaytonaConfig, CreateSandboxFromImageParams, Image


def _get_client() -> Daytona:
    """Returns configured Daytona client. Reads env vars automatically if not passed."""
    config = DaytonaConfig(
        api_key=os.getenv("DAYTONA_API_KEY"),
        api_url=os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api"),
        target=os.getenv("DAYTONA_TARGET", "us"),
    )
    return Daytona(config)


def create_sandbox(language: str = "python"):
    """Create a new sandbox. Returns the sandbox object. Caller must delete it."""
    daytona = _get_client()
    image = Image.debian_slim("3.11")
    sandbox = daytona.create(CreateSandboxFromImageParams(image=image, language=language))
    return daytona, sandbox


def run_cmd(sandbox, command: str, cwd: str = "/home/daytona", timeout: int = 120) -> dict:
    """
    Run a shell command (pip install, git clone, opentrons_simulate, etc.).
    Returns {"exit_code": int, "stdout": str, "success": bool}
    """
    response = sandbox.process.exec(command, cwd=cwd, timeout=timeout)
    return {
        "exit_code": response.exit_code,
        "stdout": response.result,
        "success": response.exit_code == 0,
    }


def run_code(sandbox, code: str, timeout: int = 60) -> dict:
    """
    Run a Python code string directly in the sandbox interpreter.
    Returns {"exit_code": int, "stdout": str, "success": bool}
    """
    response = sandbox.process.code_run(code, timeout=timeout)
    return {
        "exit_code": response.exit_code,
        "stdout": response.result,
        "success": response.exit_code == 0,
    }


def upload_file(sandbox, content: bytes | str, remote_path: str):
    """Upload a file into the sandbox filesystem."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    sandbox.fs.upload_file(content, remote_path)


def download_file(sandbox, remote_path: str) -> bytes:
    """Download a file from the sandbox filesystem."""
    return sandbox.fs.download_file(remote_path)


def clone_repo(sandbox, url: str, dest_path: str = "/home/daytona/repo"):
    """Clone a git repository into the sandbox."""
    sandbox.git.clone(url, dest_path)


def cleanup(daytona, sandbox):
    """Always call this after a sandbox is done — avoids leaving billable sandboxes running."""
    try:
        daytona.remove(sandbox)
    except Exception:
        pass
