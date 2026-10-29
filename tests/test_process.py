"""Check the small Unix installer runner without installing any SDK packages."""

import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "lib/install.sh"


class InstallerProcessTests(unittest.TestCase):
    def run_command(self, *command, timeout=10):
        return subprocess.run(
            ["bash", str(RUNNER), str(timeout), *command],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )

    def test_success_and_failure_codes_are_preserved(self):
        self.assertEqual(self.run_command("sh", "-c", "exit 0").returncode, 0)
        self.assertEqual(self.run_command("sh", "-c", "exit 42").returncode, 42)

    def test_arguments_are_passed_without_shell_expansion(self):
        value = "a path with spaces; $(exit 99) ' and $HOME"
        result = self.run_command("printf", "%s", value)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, value)

    def test_timeout_kills_a_child_that_ignores_sigterm_and_closes_output(self):
        with tempfile.TemporaryDirectory(prefix="android process ") as temporary:
            state = Path(temporary) / "child.pid"
            program = f"""
import fcntl, os, signal, time
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.close(1)
    os.close(2)
    with open({str(state)!r}, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(str(os.getpid()))
        stream.flush()
        time.sleep(60)
    os._exit(0)
time.sleep(60)
"""
            try:
                result = self.run_command(sys.executable, "-c", program, timeout=1)
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertIn("timed out", result.stderr)
                self.assertTrue(state.read_text())
                with state.open() as stream:
                    deadline = time.monotonic() + 2
                    while True:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                self.fail("Installer child survived timeout cleanup")
                            time.sleep(0.01)
            finally:
                if state.exists() and state.read_text():
                    try:
                        os.kill(int(state.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
