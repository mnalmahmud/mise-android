"""Exercise a real mise binary with local Android package lists and ZIP archives."""

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import tempfile
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
        sample_path = self.plugin / "tests/data/packages.py"
        spec = importlib.util.spec_from_file_location("sample_packages", sample_path)
        self.sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sample)
        self.archives = self.root / "package archives"
        self.sample.create_archives(self.archives)
        self.repository = self.root / "repository.xml"
        self.refresh_metadata()
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
        return list((self.root / "cache").rglob("package.zip"))

    def refresh_metadata(self):
        self.repository.write_bytes(self.sample.repository_xml(self.archives))

    def archive(self, package, revision):
        return self.sample.archive_path(self.archives, package, revision)

    def replace_archive(self, package, revision, files):
        import zipfile

        path = self.archive(package, revision)
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        self.refresh_metadata()

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

    def test_components_install_into_one_sdk_and_export_selected_ndk(self):
        self.mise("install")
        values = self.environment_values()
        self.assertEqual(Path(values["ANDROID_HOME"]), self.sdk)
        self.assertEqual(Path(values["ANDROID_NDK_HOME"]), self.sdk / "ndk/30.0.1")
        self.assertTrue((self.sdk / "platforms/android-36/source.properties").exists())
        self.assertIn("platform-tools@37.0.1", self.mise("exec", "--", "adb", "version").stdout)

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
        self.repository.unlink()
        self.mise("cache", "clear")
        self.assertEqual(self.calls(), [])
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

    def test_preview_revision_is_installed_without_cli_version_translation(self):
        self.write_config({"ndk": {"version": "31.0.1-rc.2", "channel": "canary"}})
        self.mise("install")
        self.assertEqual(
            Path(self.environment_values()["ANDROID_NDK_HOME"]), self.sdk / "ndk/31.0.1"
        )
        self.assertIn("31.0.1-beta2", (self.sdk / "ndk/31.0.1/source.properties").read_text())

    def test_linux_arm64_ndk_fails_before_installer_but_platform_works(self):
        for hook in ["backend_list_versions.lua", "backend_install.lua"]:
            path = self.plugin / "hooks" / hook
            path.write_text(
                path.read_text().replace(
                    '\treturn require("android")',
                    '\tlocal catalog=require("catalog")\n'
                    "\tcatalog.versions=function(tool,options)\n"
                    "\t\tlocal url=catalog.repository_url(tool,options)\n"
                    '\t\treturn catalog.parse(require("common").fetch(url),tool,options.channel,"linux","aarch64",url,options)\n'
                    "\tend\n"
                    '\treturn require("android")',
                )
            )
        self.write_config({"ndk": "30.0.1"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.assertEqual(Path(self.environment_values()["ANDROID_HOME"]), self.sdk)

    def test_archive_cache_is_verified_reused_and_repaired(self):
        self.write_config({"sdk": "36"})
        self.mise("install")
        cached = self.calls()[0]
        correct = cached.read_bytes()
        self.mise("install", "--force", "android:sdk")
        self.assertEqual(cached.read_bytes(), correct)
        cached.write_bytes(b"corrupt")
        self.mise("install", "--force", "android:sdk")
        self.assertEqual(cached.read_bytes(), correct)

    def test_bad_checksum_is_rejected_before_sdk_changes(self):
        self.write_config({"sdk": "36"})
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self.repository.read_bytes())
        for node in root.findall("remotePackage"):
            if node.attrib["path"] == "platforms;android-36":
                node.find("archives/archive/complete/checksum").text = "0" * 40
        self.repository.write_bytes(ET.tostring(root))
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum or size mismatch", result.stderr)
        self.assertFalse((self.sdk / "platforms/android-36").exists())
        self.assertFalse(list((self.root / "data/installs").rglob(".mise-android-package.json")))

    def test_failed_upgrade_preserves_old_shared_version(self):
        self.write_config({"emulator": "35.0.0"})
        self.mise("install")
        self.replace_archive(
            "emulator", "37.0.0", {"content/source.properties": "Pkg.Revision=999\n"}
        )
        self.write_config({"emulator": "37.0.0"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected emulator@37.0.0", result.stderr)
        self.assertEqual(
            (self.sdk / "emulator/source.properties").read_text(), "Pkg.Revision=35.0.0\n"
        )
        self.assertFalse(list((self.root / "data/android").glob(".mise-android.*")))

    def test_publish_failure_restores_old_package(self):
        self.write_config({"emulator": "35.0.0"})
        self.mise("install")
        hook = self.plugin / "hooks/backend_install.lua"
        hook.write_text(
            "function PLUGIN:BackendInstall(ctx)\nlocal rename=os.rename\nos.rename=function(source,target)\n"
            'if source:match("/content$") and target:match("/sdk/emulator$") then return nil,"simulated publish failure" end\n'
            'return rename(source,target)\nend\nreturn require("android").install(ctx) end\n'
        )
        self.write_config({"emulator": "37.0.0"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simulated publish failure", result.stderr)
        self.assertEqual(
            (self.sdk / "emulator/source.properties").read_text(), "Pkg.Revision=35.0.0\n"
        )

    def test_missing_source_properties_fails_before_publication(self):
        self.replace_archive("platforms/android-36", "3", {"content/README": "empty package"})
        self.write_config({"sdk": "36"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing Android source.properties", result.stderr)
        self.assertFalse((self.sdk / "platforms/android-36").exists())

    def test_embedded_package_identity_is_checked_before_writing_metadata(self):
        self.replace_archive(
            "platforms/android-36",
            "3",
            {
                "content/source.properties": "Pkg.Revision=3\n",
                "content/package.xml": '<repository><localPackage path="wrong-package"/></repository>',
            },
        )
        self.write_config({"sdk": "36"})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wrong name", result.stderr)
        self.assertFalse((self.sdk / "platforms/android-36").exists())

    def test_package_metadata_and_license_records_are_written(self):
        import xml.etree.ElementTree as ET

        self.write_config({"system-image": "36"})
        self.mise("install")
        path = next((self.sdk / "system-images").rglob("package.xml"))
        root = ET.parse(path).getroot()
        self.assertEqual(
            root.tag, "{http://schemas.android.com/repository/android/common/02}repository"
        )
        package = root.find("localPackage")
        self.assertTrue(package.attrib["path"].startswith("system-images;android-36;google_apis;"))
        self.assertEqual(package.find("dependencies/dependency").attrib["path"], "emulator")
        expected = hashlib.sha1(self.sample.LICENSE.encode()).hexdigest()
        self.assertIn(expected, (self.sdk / "licenses/test-license").read_text().splitlines())

    def test_stale_installation_lock_is_recovered(self):
        lock = self.root / "data/android/install.lock"
        lock.mkdir(parents=True)
        (lock / "999999999-old-process").write_text("old start time")
        self.write_config({"sdk": {"version": "36", "timeout": 5}})
        self.mise("install")
        self.assertFalse(lock.exists())
        self.assertTrue((self.sdk / "platforms/android-36").is_dir())

    def test_live_installation_lock_is_preserved_on_timeout(self):
        lock = self.root / "data/android/install.lock"
        lock.mkdir(parents=True)
        pid = str(os.getpid())
        started = subprocess.check_output(
            ["env", "LC_ALL=C", "ps", "-p", pid, "-o", "lstart="], text=True
        ).strip()
        owner = lock / (pid + "-active-test")
        owner.write_text(started)
        self.write_config({"sdk": {"version": "36", "timeout": 1}})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting", result.stderr)
        self.assertTrue(owner.exists())
        self.assertEqual(self.calls(), [])

    def test_flat_archive_layout_is_supported(self):
        self.replace_archive("platforms/android-36", "3", {"source.properties": "Pkg.Revision=3\n"})
        self.write_config({"sdk": "36"})
        self.mise("install")
        self.assertTrue((self.sdk / "platforms/android-36/package.xml").is_file())

    def test_android_java_python_and_bash_are_not_used(self):
        marker = self.root / "unexpected-command"
        for name in ["android", "java", "python", "python3", "bash", "tar"]:
            path = self.bin / name
            path.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
            path.chmod(0o755)
        self.write_config({"sdk": "36", "system-image": "36", "ndk": "30.0.1"})
        self.mise("install")
        self.environment_values()
        self.assertFalse(marker.exists())

    def test_ndk_symbolic_links_and_executable_permissions_are_preserved(self):
        import zipfile

        with zipfile.ZipFile(self.archive("ndk/30.0.1", "30.0.1"), "a") as archive:
            binary = zipfile.ZipInfo("content/bin/clang-real")
            binary.external_attr = 0o100755 << 16
            archive.writestr(binary, "binary")
            link = zipfile.ZipInfo("content/bin/clang")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "clang-real")
        self.refresh_metadata()
        self.write_config({"ndk": "30.0.1"})
        self.mise("install")
        link = self.sdk / "ndk/30.0.1/bin/clang"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), Path("clang-real"))
        self.assertTrue(link.stat().st_mode & 0o111)

    def test_lua_modules_in_mises_interpreter(self):
        self.environment["MISE_ANDROID_TEST_ROOT"] = str(self.plugin)
        (self.plugin / "hooks/backend_list_versions.lua").write_text(
            'function PLUGIN:BackendListVersions(ctx)\ndofile(os.getenv("MISE_ANDROID_TEST_ROOT").."/tests/unit.lua")\nreturn {versions={"1"}} end\n'
        )
        self.assertEqual(self.mise("ls-remote", "android:test").stdout.strip(), "1")

    def test_download_timeout_releases_lock_and_preserves_sdk(self):
        import xml.etree.ElementTree as ET

        self.write_config({"sdk": "36"})
        self.mise("install")
        root = ET.fromstring(self.repository.read_bytes())
        for node in root.findall("remotePackage"):
            if node.attrib["path"] == "platform-tools":
                for url in node.findall("archives/archive/complete/url"):
                    url.text = "https://example.invalid/slow.zip"
        self.repository.write_bytes(ET.tostring(root))
        curl = self.bin / "curl"
        curl.write_text("#!/bin/sh\nexec sleep 60\n")
        curl.chmod(0o755)
        self.write_config({"platform-tools": {"version": "37.0.1", "timeout": 1}})
        result = self.mise("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timed out", result.stderr.lower())
        self.assertFalse((self.root / "data/android/install.lock").exists())
        self.assertTrue((self.sdk / "platforms/android-36").is_dir())


if __name__ == "__main__":
    unittest.main()
