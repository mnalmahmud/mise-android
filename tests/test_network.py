"""Offline URL, download-bound, and cache-policy checks."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request as URLRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from android_mise import network
from android_mise.model import BackendError


class NetworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="android metadata ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_redirects_require_https_before_following_them(self):
        handler = network.HTTPSRedirectHandler()
        request = URLRequest("https://example.invalid/repository.xml")
        for url in ["http://example.invalid/repository.xml", "file:///tmp/repository.xml"]:
            with self.subTest(url=url), self.assertRaisesRegex(BackendError, "insecure URL"):
                handler.redirect_request(request, None, 302, "Found", {}, url)
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://mirror.invalid/repository.xml"
        )
        self.assertEqual(redirected.full_url, "https://mirror.invalid/repository.xml")

    def test_local_metadata_is_bounded_and_never_cached(self):
        path = self.root / "repository with spaces.xml"
        path.write_bytes(b"first")
        with patch.object(network, "cache_root") as root:
            self.assertEqual(network.cached_read(path.as_uri()), b"first")
            path.write_bytes(b"second")
            self.assertEqual(network.cached_read(path.as_uri()), b"second")
            root.assert_not_called()
        with self.assertRaisesRegex(BackendError, "exceeds"):
            network.read(path.as_uri(), maximum=3)

    def test_https_cache_reuses_metadata_until_it_expires(self):
        url = "https://example.invalid/repository.xml"
        with (
            patch.object(network, "cache_root", return_value=self.root),
            patch.object(network, "read", side_effect=[b"first", b"second"]) as read,
        ):
            self.assertEqual(network.cached_read(url), b"first")
            self.assertEqual(network.cached_read(url), b"first")
            self.assertEqual(read.call_count, 1)
            path = next((self.root / "metadata").iterdir())
            expired = time.time() - network.CACHE_SECONDS - 1
            os.utime(path, (expired, expired))
            self.assertEqual(network.cached_read(url), b"second")
            self.assertEqual(read.call_count, 2)

    def test_oversized_and_future_dated_cache_entries_are_refetched(self):
        url = "https://example.invalid/repository.xml"
        with (
            patch.object(network, "cache_root", return_value=self.root),
            patch.object(network, "METADATA_LIMIT", 4),
            patch.object(network, "read", return_value=b"good") as read,
        ):
            network.cached_read(url)
            path = next((self.root / "metadata").iterdir())
            path.write_bytes(b"oversized")
            self.assertEqual(network.cached_read(url), b"good")
            future = time.time() + 600
            os.utime(path, (future, future))
            self.assertEqual(network.cached_read(url), b"good")
            self.assertEqual(read.call_count, 3)

    def test_invalid_url_is_rejected_before_cache_access(self):
        with patch.object(network, "cache_root") as root:
            with self.assertRaises(BackendError):
                network.cached_read("https://[")
            root.assert_not_called()

    def test_cache_location_requires_an_absolute_xdg_path(self):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root)}):
            self.assertEqual(network.cache_root(), self.root / "mise-android")
        with (
            patch.dict(os.environ, {"XDG_CACHE_HOME": "relative"}),
            patch.object(network.sys, "platform", "linux"),
            patch.object(Path, "home", return_value=self.root),
        ):
            self.assertEqual(network.cache_root(), self.root / ".cache/mise-android")
        with (
            patch.dict(os.environ, {"XDG_CACHE_HOME": ""}),
            patch.object(network.sys, "platform", "darwin"),
            patch.object(Path, "home", return_value=self.root),
        ):
            self.assertEqual(network.cache_root(), self.root / "Library/Caches/mise-android")


if __name__ == "__main__":
    unittest.main()
