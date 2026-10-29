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
            "FAKE_ANDROID_LOG": str(self.root / "calls.jsonl"),
        }
        Path(self.environment["HOME"]).mkdir()
        self.write_config()
        self.mise("plugins", "link", "android", str(self.plugin))

    def write_config(self, name="sdk/project-a", version="36", ndk="30.0.1"):
        self.config.write_text(
            "[settings]\nexperimental = true\n[tools]\n"
            f'[tools."android:{name}"]\nversion="{version}"\n'
            f'repository_url="{self.repository.as_uri()}"\n'
            f'packages={{"platform-tools"="latest",ndk="{ndk}"}}\n'
        )

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

    def test_cli_download_is_checked_reused_and_repaired(self):
        self.fake_cli_downloads()
        self.mise("install", "android:sdk/project-a")
        self.assertTrue(Path(self.environment_values()["ANDROID_HOME"]).is_dir())
        calls = self.root / "downloads.jsonl"
        self.assertEqual(len(calls.read_text().splitlines()), 2)
        self.write_config(name="sdk/second")
        self.mise("install", "android:sdk/second")
        self.assertEqual(len(calls.read_text().splitlines()), 3)
        executable = next(path for path in (self.root / "cache").rglob("android") if path.is_file())
        executable.write_bytes(b"corrupt")
        self.write_config(name="sdk/third")
        self.mise("install", "android:sdk/third")
        self.assertEqual(len(calls.read_text().splitlines()), 5)
        self.assertNotEqual(executable.read_bytes(), b"corrupt")

    def test_bad_cli_checksum_does_not_install_download(self):
        self.fake_cli_downloads()
        self.environment["FAKE_CLI_DIGEST"] = "0" * 64
        result = self.mise("install", "android:sdk/project-a", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(any(path.is_file() for path in (self.root / "cache").rglob("android")))

    def test_sdk_selection_and_cached_environment_are_consistent(self):
        self.assertEqual(
            self.mise("ls-remote", "android:sdk/project-a").stdout.splitlines(), ["36", "37"]
        )
        self.mise("install", "android:sdk/project-a")
        first = self.environment_values()
        home = Path(first["ANDROID_HOME"])
        self.assertTrue((home / "platforms/android-36/source.properties").exists())
        self.assertIn("platform-tools@37.0.1", self.mise("exec", "--", "adb", "version").stdout)
        self.assertTrue(Path(first["ANDROID_NDK_HOME"]).is_relative_to(home))
        self.write_config(version="37", ndk="29.0.1")
        self.mise("install", "android:sdk/project-a")
        second = self.environment_values()
        self.assertNotEqual(first["ANDROID_HOME"], second["ANDROID_HOME"])
        self.assertTrue((Path(second["ANDROID_HOME"]) / "platforms/android-37").is_dir())
        self.write_config()
        for _ in range(2):
            restored = self.environment_values()
            self.assertEqual(restored["ANDROID_HOME"], first["ANDROID_HOME"])
            self.assertEqual(restored["ANDROID_NDK_HOME"], first["ANDROID_NDK_HOME"])
        self.mise("uninstall", "android:sdk/project-a@37")
        self.assertTrue(home.exists())
        self.assertFalse(Path(second["ANDROID_HOME"]).exists())
        self.config.write_text("[tools]\n")
        self.mise("uninstall", "android:sdk/project-a@36")
        self.assertFalse(home.exists())

    def test_named_sdks_isolate_same_api_with_different_packages(self):
        self.mise("install", "android:sdk/project-a")
        first = self.environment_values()
        self.write_config(name="sdk/project-b", ndk="29.0.1")
        self.mise("install", "android:sdk/project-b")
        second = self.environment_values()
        self.assertNotEqual(first["ANDROID_HOME"], second["ANDROID_HOME"])
        self.assertTrue(first["ANDROID_NDK_HOME"].endswith("ndk/30.0.1"))
        self.assertTrue(second["ANDROID_NDK_HOME"].endswith("ndk/29.0.1"))

    def test_failed_sdk_install_does_not_change_an_existing_sdk(self):
        self.mise("install", "android:sdk/project-a")
        first = self.environment_values()
        self.write_config(version="37")
        self.environment["FAKE_ANDROID_FAIL_PACKAGE"] = "ndk/30.0.1"
        result = self.mise("install", "android:sdk/project-a", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((Path(first["ANDROID_HOME"]) / "platform-tools/adb").exists())
        self.assertFalse(list((self.root / "data/installs").glob("*/37/sdk")))

    def test_default_and_empty_package_sets(self):
        for name, packages in [("sdk/default", ""), ("sdk/platform-only", ",packages={}")]:
            self.config.write_text(
                "[settings]\nexperimental=true\n[tools]\n"
                f'"android:{name}"={{version="36",repository_url="{self.repository.as_uri()}"{packages}}}\n'
            )
            self.mise("install", f"android:{name}")
            sdk = Path(self.environment_values()["ANDROID_HOME"])
            self.assertFalse((sdk / "platform-tools").exists())
            self.assertTrue((sdk / "platforms/android-36").is_dir())

    def test_standalone_packages_keep_independent_roots_and_environment(self):
        self.config.write_text(
            "[settings]\nexperimental=true\n[tools]\n"
            f'"android:platform-tools"={{version="37.0.1",repository_url="{self.repository.as_uri()}"}}\n'
            f'"android:ndk"={{version="30.0.1",repository_url="{self.repository.as_uri()}"}}\n'
        )
        self.mise("install")
        values = self.environment_values()
        self.assertNotIn("ANDROID_HOME", values)
        ndk = Path(values["ANDROID_NDK_HOME"])
        self.assertTrue((ndk / "ndk-build").is_file())
        self.assertIn("platform-tools@37.0.1", self.mise("exec", "--", "adb", "version").stdout)
        paths = values["PATH"].split(os.pathsep)
        platform_tools = next(Path(path) for path in paths if Path(path).name == "platform-tools")
        self.assertNotEqual(platform_tools.parent, ndk.parent.parent)
        self.mise("uninstall", "android:platform-tools@37.0.1")
        self.assertFalse(platform_tools.exists())
        self.assertTrue(ndk.is_dir())

    def write_image_config(self, **options):
        settings = {"version": "36", "repository_url": self.repository.as_uri(), **options}
        fields = ",".join(f"{key}={json.dumps(value)}" for key, value in settings.items())
        self.config.write_text(
            '[settings]\nexperimental=true\n[tools]\n"android:system-image"={' + fields + "}\n"
        )

    def test_system_image_selects_api_latest_revision_and_host_cpu(self):
        self.write_image_config()
        self.assertEqual(
            self.mise("ls-remote", "android:system-image").stdout.splitlines(), ["36", "37"]
        )
        self.mise("install", "android:system-image")
        installed = Path(self.mise("where", "android:system-image").stdout.strip())
        arch = "arm64-v8a" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        package = f"system-images/android-36/google_apis/{arch}"
        record = json.loads((installed / ".mise-android-package.json").read_text())
        self.assertEqual(record["components"][0]["package"], package)
        self.assertEqual(record["components"][0]["revision"], "5")
        self.assertEqual(record["arch"], arch)
        self.assertTrue((installed / "sdk" / package).is_dir())
        values = self.environment_values()
        self.assertNotIn("ANDROID_HOME", values)
        self.assertNotIn("ANDROID_NDK_HOME", values)
        self.assertNotIn(str(installed / "sdk" / package), values["PATH"].split(os.pathsep))
        before = {path: path.stat().st_mtime_ns for path in installed.rglob("*")}
        (self.bin / "android").unlink()
        self.repository.unlink()
        self.mise("cache", "clear", "android")
        self.environment_values()
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in installed.rglob("*")})

    def test_image_overrides_require_reinstallation_when_changed(self):
        self.write_image_config(variant="google_apis_playstore", arch="x86_64")
        self.mise("install", "android:system-image")
        installed = Path(self.mise("where", "android:system-image").stdout.strip())
        self.assertTrue(
            (installed / "sdk/system-images/android-36/google_apis_playstore/x86_64").is_dir()
        )
        self.write_image_config(variant="google_apis", arch="x86_64")
        self.assertIn("System image settings changed", self.mise("env", check=False).stderr)
        self.mise("install", "--force", "android:system-image")
        self.assertTrue((installed / "sdk/system-images/android-36/google_apis/x86_64").is_dir())
        self.write_image_config(variant="google_apis", arch="arm64-v8a")
        self.assertIn("System image settings changed", self.mise("env", check=False).stderr)

    def test_removed_tool_names_and_revision_setting_are_rejected(self):
        for name in ["platforms/android-36", "system-images/android-36/google_apis/x86_64"]:
            self.config.write_text("[settings]\nexperimental=true\n")
            result = self.mise("ls-remote", f"android:{name}", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Use android:", result.stderr)
        self.write_image_config(revision="3")
        result = self.mise("install", "android:system-image", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown Android setting: revision", result.stderr)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_unavailable_image_choices_do_not_start_installer(self):
        for settings in [
            {"variant": "unavailable"},
            {"arch": "x86"},
            {"version": "99", "arch": "x86_64"},
        ]:
            self.write_image_config(**settings)
            self.mise("cache", "clear", "android")
            result = self.mise("install", "android:system-image", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "calls.jsonl").exists())

    def test_sdk_can_pin_a_preview_component_from_canary(self):
        self.write_config(ndk="31.0.1-rc.2")
        with self.config.open("a") as stream:
            stream.write('channel="canary"\n')
        self.mise("install", "android:sdk/project-a")
        ndk = Path(self.environment_values()["ANDROID_NDK_HOME"])
        self.assertTrue(str(ndk).endswith("ndk/31.0.1"))
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertIn("ndk/31.0.1@31.0.1-rc.2", calls[0])
        self.assertIn("--canary", calls[0])

    def test_explicit_timeout_survives_mise_option_serialization(self):
        with self.config.open("a") as stream:
            stream.write("timeout=60\n")
        self.mise("install", "android:sdk/project-a")
        self.assertTrue(Path(self.environment_values()["ANDROID_HOME"]).is_dir())

    def test_lua_modules_in_mises_actual_interpreter(self):
        self.environment["MISE_ANDROID_TEST_ROOT"] = str(self.plugin)
        (self.plugin / "hooks/backend_list_versions.lua").write_text(
            "function PLUGIN:BackendListVersions(ctx)\n"
            'dofile(os.getenv("MISE_ANDROID_TEST_ROOT") .. "/tests/unit.lua")\n'
            'return {versions={"1"}}\nend\n'
        )
        result = self.mise("ls-remote", "android:test")
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("Lua checks", result.stderr)

    def test_python_and_bash_are_not_needed_by_the_plugin(self):
        marker = self.root / "python-was-called"
        for name in ["python", "python3", "bash"]:
            executable = self.bin / name
            executable.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
            executable.chmod(0o755)
        self.mise("install", "android:sdk/project-a")
        self.assertTrue(Path(self.environment_values()["ANDROID_HOME"]).is_dir())
        self.assertFalse(marker.exists())

    def test_activation_only_reads_the_installed_sdk(self):
        self.mise("install", "android:sdk/project-a")
        home = Path(self.environment_values()["ANDROID_HOME"])
        installed = home.parent
        before = {path: path.stat().st_mtime_ns for path in installed.rglob("*")}
        (self.bin / "android").unlink()
        self.repository.unlink()
        self.mise("cache", "clear", "android")
        self.assertEqual(Path(self.environment_values()["ANDROID_HOME"]), home)
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in installed.rglob("*")})

    def test_changed_packages_and_channel_require_reinstallation(self):
        self.mise("install", "android:sdk/project-a")
        self.write_config(ndk="29.0.1")
        result = self.mise("env", "--json", check=False)
        self.assertIn("SDK packages changed", result.stderr)
        self.write_config()
        with self.config.open("a") as stream:
            stream.write('channel="canary"\n')
        result = self.mise("env", "--json", check=False)
        self.assertIn("Release channel changed", result.stderr)

    def test_wrong_installed_version_is_not_marked_successful(self):
        self.environment["FAKE_ANDROID_WRONG_REVISION"] = "1"
        result = self.mise("install", "android:sdk/project-a", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected", result.stderr)
        self.assertFalse(list((self.root / "data/installs").rglob(".mise-android-package.json")))

    def test_wrong_package_identity_is_rejected(self):
        self.environment["FAKE_ANDROID_WRONG_IDENTITY"] = "1"
        result = self.mise("install", "android:sdk/project-a", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wrong name", result.stderr)

    def test_plan_failure_does_not_start_installer(self):
        self.write_config(ndk="99.0.1")
        result = self.mise("install", "android:sdk/project-a", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_timeout_stops_the_installer_after_launcher_exec(self):
        launcher_pid = self.root / "launcher.pid"
        installer_pid = self.root / "installer.pid"
        worker = (
            "import os,time\n"
            f"open({str(installer_pid)!r},'w').write(str(os.getpid()))\n"
            "time.sleep(60)\n"
        )
        (self.bin / "android").write_text(
            f"#!{sys.executable}\nimport os,sys\n"
            f"open({str(launcher_pid)!r},'w').write(str(os.getpid()))\n"
            f"os.execv(sys.executable,[sys.executable,'-c',{worker!r}])\n"
        )
        with self.config.open("a") as stream:
            stream.write("timeout=1\n")
        result = self.mise("install", "android:sdk/project-a", check=False)
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
                self.fail("Installer command survived mise's timeout")
            time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
