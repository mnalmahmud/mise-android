"""Exercise a real mise binary with an offline Android CLI and repository sample."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MISE = os.environ.get("MISE_BIN") or shutil.which("mise")
ENABLED = os.environ.get("MISE_ANDROID_INTEGRATION") == "1"


@unittest.skipUnless(ENABLED and MISE, "Set MISE_ANDROID_INTEGRATION=1 with mise on PATH")
class MiseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mise android integration ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bin = self.root / "executables with spaces"
        self.bin.mkdir()
        self.config = self.root / "mise.toml"
        sample_path = PLUGIN / "tests/data/fake_android.py"
        android = self.bin / "android"
        android.write_text(f"#!{sys.executable}\n" + sample_path.read_text())
        android.chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
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
        self.mise("plugins", "link", "android", str(PLUGIN))

    def write_config(self, name="sdk/project-a", version="36", ndk="30.0.1"):
        self.config.write_text(
            '[settings]\nexperimental = true\n[tools]\n"core:python"="system"\n'
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
        self.config.write_text('[tools]\n"core:python"="system"\n')
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
                '[settings]\nexperimental=true\n[tools]\n"core:python"="system"\n'
                f'"android:{name}"={{version="36",repository_url="{self.repository.as_uri()}"{packages}}}\n'
            )
            self.mise("install", f"android:{name}")
            sdk = Path(self.environment_values()["ANDROID_HOME"])
            self.assertFalse((sdk / "platform-tools").exists())
            self.assertTrue((sdk / "platforms/android-36").is_dir())

    def test_standalone_packages_keep_independent_roots_and_environment(self):
        self.config.write_text(
            '[settings]\nexperimental=true\n[tools]\n"core:python"="system"\n'
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


if __name__ == "__main__":
    unittest.main()
