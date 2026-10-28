"""Offline package, SDK, process, and metadata tests."""

import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from android_mise import android_cli, backend, bootstrap, catalog, storage
from android_mise.model import (
    BackendError,
    Options,
    Package,
    Request,
    package_path,
    revision,
    version_key,
)

SAMPLES = Path(__file__).parent / "data"


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.xml = (SAMPLES / "repository.xml").read_bytes()

    def test_platform_tools_source_and_checksum(self):
        package = catalog.parse_repository(self.xml, "platform-tools")["37.0.1"]
        self.assertEqual(package.path, "platform-tools")
        self.assertTrue(package.download_url.endswith(".zip"))
        self.assertEqual(package.checksum_type, "sha1")

    def test_ndk_channels_and_preview_versions(self):
        stable = catalog.parse_repository(self.xml, "ndk")
        self.assertIn("30.0.16248370", stable)
        self.assertFalse(any("-" in version for version in stable))
        self.assertIn("30.0.14904198-rc.1", catalog.parse_repository(self.xml, "ndk", "canary"))

    def test_sdk_versions_are_api_levels(self):
        entries = catalog.parse_repository(self.xml, "sdk/project-a")
        self.assertEqual(entries["36"].path, "platforms/android-36")
        self.assertEqual(entries["36"].revision, "2")

    def test_sdk_selects_latest_platform_revision_for_same_api(self):
        entries = catalog.parse_repository(self.xml, "sdk/project-a")
        revisions = catalog.parse_repository(self.xml, "platforms/android-34")
        self.assertEqual(entries["34"].revision, max(revisions, key=version_key))

    def test_exact_platform_versions_are_package_revisions(self):
        self.assertIn("2", catalog.parse_repository(self.xml, "platforms/android-36"))

    def test_latest_directory_alias_is_excluded(self):
        entries = catalog.parse_repository(self.xml, "cmdline-tools")
        self.assertTrue(entries)
        self.assertNotIn("latest", entries)

    def test_host_archive_selection(self):
        entries = catalog.parse_repository(
            self.xml, "cmdline-tools", system="darwin", machine="arm64"
        )
        self.assertTrue(all("arm64" in package.download_url for package in entries.values()))
        with self.assertRaises(BackendError):
            catalog.parse_repository(self.xml, "cmdline-tools", system="unknown", machine="unknown")

    def test_universal_archives_do_not_enable_unsupported_hosts(self):
        for system, machine in [("win32", "x86_64"), ("linux", "unknown")]:
            with self.subTest(system=system, machine=machine), self.assertRaises(BackendError):
                catalog.parse_repository(self.xml, "sdk", system=system, machine=machine)

    def test_system_image_identifiers_need_exactly_four_segments(self):
        for tool in ["system-images/android-36/google_apis", "system-images/a/b/c/d"]:
            with self.subTest(tool=tool), self.assertRaisesRegex(BackendError, "TAG/ABI"):
                catalog.repository_url(Request.parse({"tool": tool}))

    def test_invalid_metadata_and_missing_packages(self):
        for data in [b"not XML", b"<wrong/>", b"<sdk-repository/>"]:
            with self.subTest(data=data), self.assertRaises(BackendError):
                catalog.parse_repository(data, "platform-tools")


class ModelTests(unittest.TestCase):
    def test_component_versions_are_normalized_without_mutating_input(self):
        raw = {"packages": {"ndk": "030.0.01 rc2"}}
        options = Options.parse(raw)
        self.assertEqual(options.packages, {"ndk": "30.0.1-rc.2"})
        self.assertEqual(raw["packages"]["ndk"], "030.0.01 rc2")

    def test_repository_urls_are_validated_as_options(self):
        for value in [
            "",
            "http://example.invalid/repo",
            "https://[",
            "https:///repo",
            "https://example.invalid:bad/repo",
            "file:relative.xml",
            "file://remote.invalid/repo",
            "https://example.invalid/white space",
            1,
        ]:
            with self.subTest(value=value), self.assertRaisesRegex(BackendError, "repository_url"):
                Options.parse({"repository_url": value})
        for value in ["https://example.invalid/repo.xml", "file:///tmp/repo.xml"]:
            self.assertEqual(Options.parse({"repository_url": value}).repository_url, value)

    def test_mise_scalar_timeout_options(self):
        self.assertEqual(Options.parse({"timeout": "60"}).timeout, 60)

    def test_invalid_package_paths(self):
        for value in ["../ndk", "/ndk", "ndk/../x", "ndk;echo", "$(id)", "ndk//x", "-x", None]:
            with self.subTest(value=value), self.assertRaises(BackendError):
                package_path(value)

    def test_normalized_revision_order(self):
        self.assertEqual(revision("30.0.01 rc2"), "30.0.1-rc.2")
        values = ["30.0.1", "30.0.1-beta.1", "30.0.1-rc.1", "30.0.1-alpha.9", "29.9"]
        self.assertEqual(
            sorted(values, key=version_key),
            ["29.9", "30.0.1-alpha.9", "30.0.1-beta.1", "30.0.1-rc.1", "30.0.1"],
        )
        self.assertEqual(version_key("1.0"), version_key("1.0.0"))

    def test_invalid_options(self):
        for options in [
            {"unknown": True},
            {"channel": []},
            {"channel": "dev"},
            {"timeout": True},
            {"timeout": 0},
            {"timeout": "86401"},
            {"timeout": "0"},
            {"timeout": "1.5"},
            {"timeout": "true"},
            {"packages": []},
            {"packages": {"ndk": 30}},
            {"packages": {"sdk": "36"}},
        ]:
            with self.subTest(options=options), self.assertRaises(BackendError):
                Options.parse(options)

    def test_packages_only_apply_to_sdks(self):
        with self.assertRaisesRegex(BackendError, "only available"):
            Request.parse({"tool": "ndk", "options": {"packages": {"platform-tools": "latest"}}})


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mise android test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def request(self, tool="platform-tools", version="37.0.1", **options):
        return Request.parse(
            {
                "tool": tool,
                "version": version,
                "install_path": str(self.root / "install"),
                "options": options,
            }
        )

    def packages(self, request):
        values = {
            "sdk/project-a": [Package("platforms/android-36", "2", "36")],
            "platform-tools": [Package("platform-tools", "37.0.1", "37.0.1")],
            "ndk": [
                Package("ndk/29.0.1", "29.0.1", "29.0.1"),
                Package("ndk/30.0.1", "30.0.1", "30.0.1"),
            ],
            "ndk/29.0.1": [Package("ndk/29.0.1", "29.0.1", "29.0.1")],
            "ndk/30.0.1": [Package("ndk/30.0.1", "30.0.1", "30.0.1")],
            "platforms/android-36": [Package("platforms/android-36", "1", "1")],
        }
        return {entry.version: entry for entry in values[request.tool]}

    def install_package(self, request, sdk, _action, *specifications):
        for specification in specifications:
            package, version = specification.rsplit("@", 1)
            component = sdk / package
            component.mkdir(parents=True)
            (component / "source.properties").write_text("Pkg.Revision=" + version + "\n")

    def test_single_package_does_not_claim_android_home(self):
        request = self.request()
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package),
        ):
            backend.install(request)
        values = {item["key"]: item["value"] for item in backend.environment(request)["env_vars"]}
        self.assertNotIn("ANDROID_HOME", values)
        self.assertTrue(values["PATH"].endswith("sdk/platform-tools"))

    def test_complete_sdk_has_consistent_environment_and_read_only_activation(self):
        request = self.request(
            "sdk/project-a", "36", packages={"platform-tools": "latest", "ndk": "30.0.1"}
        )
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package),
        ):
            backend.install(request)
        before = {path: path.stat().st_mtime_ns for path in self.root.rglob("*")}
        values = {item["key"]: item["value"] for item in backend.environment(request)["env_vars"]}
        sdk = request.install_path / "sdk"
        self.assertEqual(Path(values["ANDROID_HOME"]), sdk)
        self.assertEqual(Path(values["ANDROID_NDK_HOME"]), sdk / "ndk/30.0.1")
        self.assertTrue((sdk / "platforms/android-36/source.properties").is_file())
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in self.root.rglob("*")})

    def test_default_sdk_only_includes_requested_platform(self):
        request = self.request("sdk/project-a", "36")
        with patch.object(catalog, "catalog", side_effect=self.packages):
            self.assertEqual(
                [package.path for package in backend.plan(request)],
                ["platforms/android-36"],
            )

    def test_sdk_deduplicates_package_aliases_in_one_installer_call(self):
        request = self.request(
            "sdk/project-a", "36", packages={"ndk": "30.0.1", "ndk/30.0.1": "30.0.1"}
        )
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package) as installer,
        ):
            backend.install(request)
        installer.assert_called_once_with(
            request,
            request.install_path / "sdk",
            "install",
            "platforms/android-36@2",
            "ndk/30.0.1@30.0.1",
        )

    def test_conflicting_platform_revisions_fail_before_creating_sdk(self):
        request = self.request("sdk/project-a", "36", packages={"platforms/android-36": "1"})
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run") as installer,
        ):
            with self.assertRaisesRegex(BackendError, "two revisions"):
                backend.install(request)
        installer.assert_not_called()
        self.assertFalse(request.install_path.exists())

    def test_multiple_ndks_export_the_highest_revision(self):
        request = self.request(
            "sdk/project-a", "36", packages={"ndk": "30.0.1", "ndk/29.0.1": "29.0.1"}
        )
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package),
        ):
            backend.install(request)
        values = {item["key"]: item["value"] for item in backend.environment(request)["env_vars"]}
        self.assertTrue(values["ANDROID_NDK_HOME"].endswith("ndk/30.0.1"))

    def test_missing_version_fails_before_install(self):
        request = self.request(version="99.0.0")
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run") as installer,
        ):
            with self.assertRaisesRegex(BackendError, "does not offer"):
                backend.install(request)
            installer.assert_not_called()

    def test_failed_download_does_not_commit_a_manifest(self):
        request = self.request()
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=BackendError("download failed")),
        ):
            with self.assertRaisesRegex(BackendError, "download failed"):
                backend.install(request)
        self.assertFalse((request.install_path / storage.MANIFEST).exists())

    def test_all_components_are_verified_after_the_installer_finishes(self):
        request = self.request("sdk/project-a", "36", packages={"ndk": "30.0.1"})

        def install_and_change_platform(*arguments):
            self.install_package(*arguments)
            if arguments[-1].startswith("ndk/"):
                (request.install_path / "sdk/platforms/android-36/source.properties").write_text(
                    "Pkg.Revision=99\n"
                )

        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=install_and_change_platform),
        ):
            with self.assertRaisesRegex(BackendError, "Expected platforms/android-36@2"):
                backend.install(request)
        self.assertFalse((request.install_path / storage.MANIFEST).exists())

    def test_changed_sdk_configuration_requires_reinstall(self):
        request = self.request("sdk/project-a", "36", packages={})
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package),
        ):
            backend.install(request)
        changed = self.request("sdk/project-a", "36", packages={"ndk": "30.0.1"})
        with self.assertRaisesRegex(BackendError, "packages changed"):
            backend.environment(changed)
        changed = self.request("sdk/project-a", "36", channel="canary")
        with self.assertRaisesRegex(BackendError, "channel changed"):
            backend.environment(changed)

    def test_malformed_manifest_package_options_are_rejected(self):
        request = self.request()
        with (
            patch.object(catalog, "catalog", side_effect=self.packages),
            patch.object(android_cli, "run", side_effect=self.install_package),
        ):
            backend.install(request)
        path = request.install_path / storage.MANIFEST
        manifest = storage.read_json(path)
        manifest["packages"] = []
        storage.atomic_json(path, manifest)
        with self.assertRaisesRegex(BackendError, "Invalid packages"):
            backend.environment(request)

    def test_component_identity_is_verified(self):
        path = self.root / "component"
        path.mkdir()
        (path / "source.properties").write_text("Pkg.Revision=37.0.1\n")
        (path / "package.xml").write_text(
            '<repository><localPackage path="emulator"/></repository>'
        )
        with self.assertRaisesRegex(BackendError, "expected platform-tools"):
            storage.verify_component(path, "platform-tools", "37.0.1")

    def test_atomic_write_preserves_previous_manifest_on_failure(self):
        path = self.root / "state.json"
        storage.atomic_json(path, {"old": True})
        with patch("os.fsync", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            storage.atomic_json(path, {"new": True})
        self.assertEqual(storage.read_json(path), {"old": True})
        self.assertEqual(list(self.root.glob("state.json.*")), [])

    def test_cli_arguments_are_not_shell_interpolated(self):
        with (
            patch.object(bootstrap, "resolve", return_value=Path("/path with spaces/android")),
            patch.object(
                android_cli, "_capture", return_value=subprocess.CompletedProcess([], 0, "ok", "")
            ) as capture,
        ):
            android_cli.run(
                self.request(channel="canary"), self.root, "install", "ndk/30.0.1@30.0.1"
            )
        arguments = capture.call_args.args[0]
        self.assertEqual(arguments[0], "/path with spaces/android")
        self.assertEqual(arguments[-1], "--canary")

    def test_timeout_terminates_installer(self):
        executable = self.root / "slow android"
        pid_file = self.root / "installer.pid"
        executable.write_text(
            f"#!{sys.executable}\nimport os,time\nopen({str(pid_file)!r},'w').write(str(os.getpid()))\ntime.sleep(60)\n"
        )
        executable.chmod(0o755)
        with (
            patch.object(bootstrap, "resolve", return_value=executable),
            self.assertRaisesRegex(BackendError, "timed out"),
        ):
            android_cli.run(self.request(timeout=1), self.root, "install", "platform-tools@37.0.1")
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

    def test_cleanup_kills_children_even_when_the_leader_exits_on_sigterm(self):
        executable = self.root / "forking android"
        child_state = self.root / "child.pid"
        executable.write_text(
            f"""#!{sys.executable}
import fcntl, os, signal, time
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.close(1)
    os.close(2)
    with open({str(child_state)!r}, 'w') as state:
        fcntl.flock(state, fcntl.LOCK_EX)
        state.write(str(os.getpid()))
        state.flush()
        time.sleep(60)
    os._exit(0)
time.sleep(60)
"""
        )
        executable.chmod(0o755)

        def cleanup():
            if child_state.exists() and child_state.read_text():
                try:
                    os.kill(int(child_state.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

        self.addCleanup(cleanup)
        with (
            patch.object(bootstrap, "resolve", return_value=executable),
            self.assertRaisesRegex(BackendError, "timed out"),
        ):
            android_cli.run(self.request(timeout=1), self.root, "install", "platform-tools@37.0.1")
        # A lock is released on exit even if an orphan is still waiting to be reaped.
        self.assertTrue(child_state.read_text())
        with child_state.open() as state:
            deadline = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        self.fail("Installer child survived timeout cleanup")
                    time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
