"""Run Google's installer with argument arrays and bounded execution time."""

import os
import signal
import subprocess
from pathlib import Path

from . import bootstrap
from .model import BackendError, Request


def _terminate(process):
    """Stop the installer and its children before mise can clean the SDK directory."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The leader can exit while a child ignores SIGTERM and closes its pipes.
        # communicate() returning does not prove that the process group is gone.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate()


def _capture(command, timeout):
    with subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "LC_ALL": "C", "LANG": "C", "NO_COLOR": "1"},
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            _terminate(process)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run(request: Request, sdk: Path, *arguments: str) -> str:
    executable = bootstrap.resolve(request.options.timeout)
    command = [str(executable), "--sdk", str(sdk), "sdk", *arguments]
    if request.options.channel != "stable":
        command.append("--" + request.options.channel)
    try:
        result = _capture(command, request.options.timeout)
    except FileNotFoundError as error:
        raise BackendError(
            f"Cannot execute Android CLI at {executable}; check its permissions and host compatibility."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise BackendError(
            f"Android CLI timed out after {request.options.timeout}s during {arguments[0]}"
        ) from error
    if result.returncode:
        details = "\n".join(part.strip() for part in [result.stderr, result.stdout] if part.strip())
        raise BackendError(f"Android CLI {arguments[0]} exited {result.returncode}:\n{details}")
    return result.stdout
