import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from android_mise import bootstrap
from android_mise.model import BackendError

INDEX = b"Package: android-cli\nVersion: 1.1.123\nArchitecture: amd64\n"
BINARY = b"#!/bin/sh\nprintf 'test Android CLI\\n'\n"
DIGEST = hashlib.sha256(BINARY).hexdigest().encode()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="android bootstrap ")
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / "cache"

    def response(self, url, *_):
        if url == bootstrap.VERSION_INDEX:
            return INDEX
        return DIGEST if url.endswith(".sha256") else BINARY

    def test_existing_binary_is_used_without_network_or_private_cache(self):
        executable = Path(self.temporary.name) / "android"
        executable.write_bytes(BINARY)
        executable.chmod(0o755)
        with (
            patch.dict(os.environ, {"PATH": self.temporary.name}),
            patch.object(bootstrap.network, "read") as read,
        ):
            self.assertEqual(bootstrap.resolve(), executable)
            read.assert_not_called()

    def test_unresolved_mise_shims_are_not_invoked_recursively(self):
        shim = Path(self.temporary.name) / "mise/shims/android"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(BINARY)
        shim.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(shim.parent)}):
            self.assertIsNone(bootstrap.existing_cli())

    def test_mise_symlink_shims_in_custom_directories_are_skipped(self):
        target = Path(self.temporary.name) / "mise"
        target.write_bytes(BINARY)
        target.chmod(0o755)
        directory = Path(self.temporary.name) / "custom shims"
        directory.mkdir()
        (directory / "android").symlink_to(target)
        with patch.dict(os.environ, {"PATH": str(directory)}):
            self.assertIsNone(bootstrap.existing_cli())

    def test_download_verified_cached_and_repaired_if_corrupt(self):
        with (
            patch.object(bootstrap, "existing_cli", return_value=None),
            patch.object(bootstrap, "platform_name", return_value="linux_x86_64"),
            patch.object(bootstrap.network, "cache_root", return_value=self.cache),
            patch.object(bootstrap.network, "read", side_effect=self.response) as read,
        ):
            executable = bootstrap.resolve()
            self.assertEqual(executable.read_bytes(), BINARY)
            self.assertTrue(os.access(executable, os.X_OK))
            self.assertEqual(read.call_count, 3)
            self.assertEqual(bootstrap.resolve(), executable)
            self.assertEqual(read.call_count, 3)
            executable.write_bytes(b"corrupt")
            self.assertEqual(bootstrap.resolve().read_bytes(), BINARY)
            self.assertEqual(read.call_count, 5)
            executable.with_name("sha256").write_bytes(b"\xff")
            self.assertEqual(bootstrap.resolve().read_bytes(), BINARY)
            self.assertEqual(read.call_count, 7)

    def test_bad_checksum_never_installs_executable(self):
        def response(url, *_):
            return b"0" * 64 if url.endswith(".sha256") else self.response(url)

        with (
            patch.object(bootstrap, "existing_cli", return_value=None),
            patch.object(bootstrap, "platform_name", return_value="linux_x86_64"),
            patch.object(bootstrap.network, "cache_root", return_value=self.cache),
            patch.object(bootstrap.network, "read", side_effect=response),
        ):
            with self.assertRaisesRegex(BackendError, "checksum mismatch"):
                bootstrap.resolve()
        self.assertEqual(list(self.cache.rglob("android")), [])

    def test_checksum_and_version_formats_are_validated(self):
        self.assertEqual(bootstrap.parse_checksum(DIGEST), DIGEST.decode())
        self.assertEqual(bootstrap.parse_checksum(DIGEST + b"  android\n"), DIGEST.decode())
        self.assertEqual(bootstrap.parse_latest(INDEX), "1.1.123")
        for value in [b"", b"abc", b"\xff", DIGEST + b" trailing nonsense"]:
            with self.subTest(value=value), self.assertRaises(BackendError):
                bootstrap.parse_checksum(value)
        with self.assertRaises(BackendError):
            bootstrap.parse_latest(b"Package: unrelated\nVersion: 1\n")
        with self.assertRaises(BackendError):
            bootstrap.parse_latest(b"\xff")

    def test_supported_google_targets(self):
        self.assertEqual(bootstrap.platform_name("darwin", "aarch64"), "darwin_arm64")
        self.assertEqual(bootstrap.platform_name("linux", "amd64"), "linux_x86_64")
        with self.assertRaisesRegex(BackendError, "no supported"):
            bootstrap.platform_name("linux", "aarch64")


if __name__ == "__main__":
    unittest.main()
