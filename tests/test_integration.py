"""Exercise a real mise binary with an offline Android CLI and repository sample."""

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MISE = os.environ.get("MISE_BIN") or shutil.which("mise")


@unittest.skipUnless(MISE, "Install mise or set MISE_BIN to run the plugin tests")
class MiseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mise android's $test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bin = self.root / "executables with spaces"
        self.bin.mkdir()
        self.config = self.root / "mise.toml"
        self.plugin = self.root / "plugin"
        shutil.copytree(
            PLUGIN,
            self.plugin,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", ".ruff_cache", "__pycache__", ".agents", ".aws", ".codex"
            ),
        )
        sample_path = self.plugin / "tests/data/fake_android.py"
        android = self.bin / "android"
        android.write_text(f"#!{sys.executable}\n" + sample_path.read_text())
        android.chmod(0o755)
        spec = importlib.util.spec_from_file_location("sample_android", sample_path)
        sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sample)
        self.repository = self.root / "repository.xml"
        self.repository.write_bytes(sample.repository_xml())
        self.environment = {
            "HOME": str(self.root / "home"),
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_CACHE_HOME": str(self.root / "xdg-cache"),
            "XDG_DATA_HOME": str(self.root / "xdg-data"),
            "XDG_STATE_HOME": str(self.root / "xdg-state"),
            "MISE_GLOBAL_CONFIG_FILE": str(self.config),
            "MISE_DATA_DIR": str(self.root / "data"),
            "MISE_CACHE_DIR": str(self.root / "cache"),
            "MISE_STATE_DIR": str(self.root / "state"),
            "MISE_TRUSTED_CONFIG_PATHS": str(self.root),
            "MISE_YES": "1",
            "MISE_BIN": str(Path(MISE).resolve()),
            "FAKE_ANDROID_LOG": str(self.root / "calls.jsonl"),
        }
        Path(self.environment["HOME"]).mkdir()
        self.write_config()
        self.mise("plugins", "link", "android", str(self.plugin))

    def write_config(self, tools=None):
        tools = (
            tools
            if tools is not None
            else {"sdk": "36", "platform-tools": "latest", "ndk": "30.0.1"}
        )
        lines = ["[settings]", "experimental=true", "[tools]"]
        for tool, value in tools.items():
            values = value if isinstance(value, list) else [value]
            entries = []
            for entry in values:
                options = {"version": entry} if isinstance(entry, str) else dict(entry)
                options["repository_url"] = self.repository.as_uri()
                fields = ",".join(f"{key}={json.dumps(item)}" for key, item in options.items())
                entries.append("{" + fields + "}")
            value = "[" + ",".join(entries) + "]" if isinstance(value, list) else entries[0]
            lines.append(f'"android:{tool}"={value}')
        self.config.write_text("\n".join(lines) + "\n")

    @property
    def sdk(self):
        return self.root / "data/android/sdk"

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def mise(self, *arguments, check=True):
        result = subprocess.run(
            [MISE, *arguments],
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if check and result.returncode:
            self.fail(f"mise {' '.join(arguments)} failed:\n{result.stdout}\n{result.stderr}")
        return result

    def environment_values(self):
        return json.loads(self.mise("env", "--json").stdout)

    def fake_cli_downloads(self):
        source = self.root / "downloadable android"
        source.write_bytes((self.bin / "android").read_bytes())
        (self.bin / "android").unlink()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        curl = self.bin / "curl"
        curl.write_text(
            f"#!{sys.executable}\n"
            "import json,os,sys\nfrom pathlib import Path\n"
            "url=sys.argv[-1]\n"
            "assert url.startswith('https://dl.google.com/android/cli/latest/'), url\n"
            f"source=Path({str(source)!r})\n"
            "if url.endswith('/android.sha256'):\n"
            f"    content=(os.environ.get('FAKE_CLI_DIGEST') or {digest!r}).encode()\n"
            "else:\n"
            "    assert url.endswith('/android'), url\n"
            "    content=source.read_bytes()\n"
            "Path(sys.argv[sys.argv.index('--output')+1]).write_bytes(content)\n"
            f"with open({str(self.root / 'downloads.jsonl')!r},'a') as log:\n"
            "    log.write(json.dumps(url)+'\\n')\n"
        )
        curl.chmod(0o755)

    def test_components_install_into_one_sdk_and_export_selected_ndk(self):
        self.mise("install")
        values = self.environment_values()
        self.assertEqual(Path(values["ANDROID_HOME"]), self.sdk)
        self.assertEqual(Path(values["ANDROID_NDK_HOME"]), self.sdk / "ndk/30.0.1")
        self.assertTrue((self.sdk / "platforms/android-36/source.properties").exists())
        self.assertIn("platform-tools@37.0.1", self.mise("exec", "--", "adb", "version").stdout)
        self.assertEqual({Path(call[1]) for call in self.calls()}, {self.sdk})

    def test_multiple_platforms_and_ndks_coexist(self):
        self.write_config({"sdk": ["36", "37"], "ndk": ["29.0.1", "30.0.1"]})
        self.mise("install")
        for path in ["platforms/android-36", "platforms/android-37", "ndk/29.0.1", "ndk/30.0.1"]:
            self.assertTrue((self.sdk / path).is_dir())
        self.write_config({"sdk": "36", "ndk": "29.0.1"})
        self.assertEqual(
            Path(self.environment_values()["ANDROID_NDK_HOME"]), self.sdk / "ndk/29.0.1"
        )
        self.mise("uninstall", "android:sdk@37")
        self.assertFalse((self.sdk / "platforms/android-37").exists())
        self.assertTrue((self.sdk / "platforms/android-36").is_dir())
        self.assertTrue((self.sdk / "ndk/30.0.1").is_dir())

    def test_sdk_default_installs_only_platform(self):
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.assertTrue((self.sdk / "platforms/android-36").is_dir())
        self.assertFalse((self.sdk / "platform-tools").exists())
        self.assertFalse((self.sdk / "emulator").exists())

    def test_image_adds_required_emulator_in_same_sdk(self):
        self.write_config({"system-image": "36"})
        self.assertEqual(
            self.mise("ls-remote", "android:system-image").stdout.splitlines(), ["36", "37"]
        )
        self.mise("install")
        arch = "arm64-v8a" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        image = self.sdk / f"system-images/android-36/google_apis/{arch}"
        self.assertEqual((image / "source.properties").read_text(), "Pkg.Revision=5\n")
        values = self.environment_values()
        self.assertEqual(Path(values["ANDROID_HOME"]), self.sdk)
        self.assertIn("emulator@37.0.0", self.mise("exec", "--", "emulator").stdout)
        self.mise("uninstall", "android:system-image@36")
        self.assertFalse(image.exists())
        self.assertTrue((self.sdk / "emulator").is_dir())

    def test_conflicting_emulator_pin_fails_before_any_installer_starts(self):
        self.write_config({"sdk": "36", "emulator": "35.0.0", "system-image": "36"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires emulator >= 35.4.9", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_two_versions_of_a_shared_package_fail_before_installation(self):
        for tool, versions in [
            ("emulator", ["35.0.0", "37.0.0"]),
            ("platform-tools", ["36.0.0", "37.0.1"]),
        ]:
            self.write_config({tool: versions})
            result = self.mise("install", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot contain two versions", result.stderr)
            self.assertEqual(self.calls(), [])

    def test_removed_emulator_invalidates_cached_image_activation(self):
        self.write_config({"system-image": "36"})
        self.mise("install")
        self.environment_values()
        self.write_config({"emulator": "37.0.0"})
        self.mise("install")
        self.mise("uninstall", "android:emulator@37.0.0")
        self.write_config({"system-image": "36"})
        result = self.mise("env", check=False)
        self.assertIn("Expected emulator@35.4.9, found missing", result.stderr)

    def test_compatible_emulator_pin_and_image_install_in_either_order(self):
        self.write_config({"emulator": "35.4.9", "system-image": "36"})
        self.mise("install", "android:system-image")
        self.mise("install", "android:emulator")
        self.assertEqual(
            (self.sdk / "emulator/source.properties").read_text(), "Pkg.Revision=35.4.9\n"
        )
        self.assertIn("emulator@35.4.9", self.mise("exec", "--", "emulator").stdout)
        self.mise("install", "--force", "android:system-image")
        self.environment_values()
        self.assertEqual(
            (self.sdk / "emulator/source.properties").read_text(), "Pkg.Revision=35.4.9\n"
        )

    def test_shared_version_changes_are_detected_after_cached_activation(self):
        self.write_config({"emulator": "35.0.0"})
        self.mise("install")
        self.environment_values()
        self.write_config({"system-image": "36"})
        self.mise("install")
        self.write_config({"emulator": "35.0.0"})
        result = self.mise("env", "--json", check=False)
        self.assertIn("Expected emulator@35.0.0, found 37.0.0", result.stderr)
        self.mise("uninstall", "android:system-image@36")
        self.mise("install", "--force", "android:emulator")
        self.assertIn("emulator@35.0.0", self.mise("exec", "--", "emulator").stdout)

    def test_installed_image_blocks_incompatible_emulator_pin_in_another_project(self):
        self.write_config({"system-image": "36"})
        self.mise("install")
        before = len(self.calls())
        self.write_config({"emulator": "35.0.0"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires emulator >= 35.4.9", result.stderr)
        self.assertEqual(len(self.calls()), before)
        self.assertEqual(
            (self.sdk / "emulator/source.properties").read_text(), "Pkg.Revision=37.0.0\n"
        )

    def test_uninstalling_old_receipt_preserves_new_shared_version(self):
        self.write_config({"platform-tools": "36.0.0"})
        self.mise("install")
        self.write_config({"platform-tools": "37.0.1"})
        self.mise("install")
        self.mise("uninstall", "android:platform-tools@36.0.0")
        self.assertIn("platform-tools@37.0.1", self.mise("exec", "--", "adb", "version").stdout)
        self.mise("uninstall", "android:platform-tools@37.0.1")
        self.assertFalse((self.sdk / "platform-tools").exists())

    def test_activation_is_read_only_and_offline(self):
        self.write_config({"sdk": "36", "system-image": "36"})
        self.mise("install")
        self.environment_values()
        before = {p: p.stat().st_mtime_ns for p in self.sdk.rglob("*")}
        (self.bin / "android").unlink()
        self.repository.unlink()
        self.mise("cache", "clear", "android")
        self.assertEqual(Path(self.environment_values()["ANDROID_HOME"]), self.sdk)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.sdk.rglob("*")})

    def test_removed_named_sdks_raw_paths_and_bundle_options_fail(self):
        self.write_config({})
        for name in [
            "sdk/project",
            "platforms/android-36",
            "system-images/android-36/google_apis/x86_64",
        ]:
            result = self.mise("ls-remote", f"android:{name}", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Use android:", result.stderr)
        self.write_config({"sdk": {"version": "36", "packages": "ndk"}})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown Android setting: packages", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_image_overrides_and_changed_settings(self):
        self.write_config(
            {
                "system-image": {
                    "version": "36",
                    "variant": "google_apis_playstore",
                    "arch": "x86_64",
                }
            }
        )
        self.mise("install")
        self.assertTrue(
            (self.sdk / "system-images/android-36/google_apis_playstore/x86_64").is_dir()
        )
        self.write_config({"system-image": {"version": "36", "arch": "x86_64"}})
        self.assertIn("Android settings changed", self.mise("env", check=False).stderr)
        self.mise("install", "--force", "android:system-image")
        self.assertTrue((self.sdk / "system-images/android-36/google_apis/x86_64").is_dir())
        self.assertFalse(
            (self.sdk / "system-images/android-36/google_apis_playstore/x86_64").is_dir()
        )

    def test_unavailable_image_choices_do_not_start_installer(self):
        for settings in [
            {"variant": "unavailable"},
            {"arch": "x86"},
            {"version": "99", "arch": "x86_64"},
            {"revision": "3"},
        ]:
            self.write_config({"system-image": {"version": "36", **settings}})
            result = self.mise("install", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls(), [])

    def test_preview_revision_uses_numeric_cli_argument(self):
        self.write_config({"ndk": {"version": "31.0.1-rc.2", "channel": "canary"}})
        self.mise("install")
        self.assertIn("ndk/31.0.1@31.0.1.2", self.calls()[0])
        self.assertIn("--canary", self.calls()[0])
        self.assertEqual(
            Path(self.environment_values()["ANDROID_NDK_HOME"]), self.sdk / "ndk/31.0.1"
        )

    def test_linux_arm64_ndk_fails_before_installer_but_platform_works(self):
        for hook in ["backend_list_versions.lua", "backend_install.lua"]:
            path = self.plugin / "hooks" / hook
            path.write_text(
                path.read_text().replace(
                    '\treturn require("android")',
                    '\tRUNTIME={osType="linux",archType="aarch64",cacheDirPath=RUNTIME.cacheDirPath}\n\treturn require("android")',
                )
            )
        self.write_config({"ndk": "30.0.1"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.assertEqual(Path(self.environment_values()["ANDROID_HOME"]), self.sdk)

    def test_cli_download_is_checked_reused_and_repaired(self):
        self.fake_cli_downloads()
        self.write_config({"sdk": "36"})
        self.mise("install")
        calls = self.root / "downloads.jsonl"
        self.assertEqual(len(calls.read_text().splitlines()), 2)
        self.write_config({"sdk": "37"})
        self.mise("install")
        self.assertEqual(len(calls.read_text().splitlines()), 3)
        executable = next(p for p in (self.root / "cache").rglob("android") if p.is_file())
        executable.write_bytes(b"corrupt")
        self.write_config({"platform-tools": "37.0.1"})
        self.mise("install")
        self.assertEqual(len(calls.read_text().splitlines()), 5)
        self.assertNotEqual(executable.read_bytes(), b"corrupt")

    def test_bad_cli_checksum_does_not_install_download(self):
        self.fake_cli_downloads()
        self.environment["FAKE_CLI_DIGEST"] = "0" * 64
        self.write_config({"sdk": "36"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(any(p.is_file() for p in (self.root / "cache").rglob("android")))

    def test_wrong_installed_version_or_identity_is_not_recorded(self):
        for variable, message in [
            ("FAKE_ANDROID_WRONG_REVISION", "Expected"),
            ("FAKE_ANDROID_WRONG_IDENTITY", "wrong name"),
        ]:
            self.write_config({"sdk": "36"})
            self.environment[variable] = "1"
            result = self.mise("install", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertFalse(
                list((self.root / "data/installs").rglob(".mise-android-package.json"))
            )
            del self.environment[variable]

    def test_failure_preserves_other_installed_components(self):
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.write_config({"sdk": "36", "ndk": "30.0.1"})
        self.environment["FAKE_ANDROID_FAIL_PACKAGE"] = "ndk/30.0.1"
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.sdk / "platforms/android-36").is_dir())

    def test_python_and_bash_are_not_needed_by_plugin(self):
        marker = self.root / "unexpected-command"
        for name in ["python", "python3", "bash"]:
            path = self.bin / name
            path.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
            path.chmod(0o755)
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.environment_values()
        self.assertFalse(marker.exists())

    def test_lua_modules_in_mises_interpreter(self):
        self.environment["MISE_ANDROID_TEST_ROOT"] = str(self.plugin)
        (self.plugin / "hooks/backend_list_versions.lua").write_text(
            'function PLUGIN:BackendListVersions(ctx)\ndofile(os.getenv("MISE_ANDROID_TEST_ROOT").."/tests/unit.lua")\nreturn {versions={"1"}} end\n'
        )
        self.assertEqual(self.mise("ls-remote", "android:test").stdout.strip(), "1")

    def test_timeout_stops_installer_after_launcher_exec(self):
        launcher_pid, installer_pid = self.root / "launcher.pid", self.root / "installer.pid"
        worker = (
            "import os,time\n"
            + f"open({str(installer_pid)!r},'w').write(str(os.getpid()))\ntime.sleep(60)\n"
        )
        (self.bin / "android").write_text(
            f"#!{sys.executable}\nimport os,sys\n"
            + f"open({str(launcher_pid)!r},'w').write(str(os.getpid()))\n"
            + f"os.execv(sys.executable,[sys.executable,'-c',{worker!r}])\n"
        )
        self.write_config({"sdk": {"version": "36", "timeout": 1}})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timed out", result.stderr.lower())
        pid = int(installer_pid.read_text())
        self.assertEqual(pid, int(launcher_pid.read_text()))
        deadline = time.monotonic() + 2
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if time.monotonic() >= deadline:
                self.fail("Installer survived timeout")
            time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
