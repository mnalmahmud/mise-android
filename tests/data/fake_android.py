"""Offline Android CLI sample. It never touches a real SDK or contacts Google."""

import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CATALOG = [
    ("platform-tools", "36.0.0"),
    ("platform-tools", "37.0.1"),
    ("emulator", "35.0.0"),
    ("emulator", "35.4.9"),
    ("emulator", "37.0.0"),
    ("ndk/29.0.1", "29.0.1"),
    ("ndk/30.0.1", "30.0.1"),
    ("ndk/31.0.1", "31.0.1-rc.2"),
    ("build-tools/36.0.0", "36.0.0"),
    ("platforms/android-36", "3"),
    ("platforms/android-37", "1"),
    ("system-images/android-36/google_apis/x86_64", "3"),
    ("system-images/android-36/google_apis/x86_64", "5"),
    ("system-images/android-36/google_apis/arm64-v8a", "5"),
    ("system-images/android-37/google_apis/x86_64", "1"),
    ("system-images/android-37/google_apis/arm64-v8a", "1"),
    ("system-images/android-36/google_apis_playstore/x86_64", "2"),
]


def dependencies(package):
    return [("emulator", "35.4.9")] if package.startswith("system-images/") else []


def add_dependencies(node, package):
    for name, revision in dependencies(package):
        parent = node.find("dependencies")
        if parent is None:
            parent = ET.SubElement(node, "dependencies")
        dependency = ET.SubElement(parent, "dependency", path=name)
        minimum = ET.SubElement(dependency, "min-revision")
        for key, part in zip(["major", "minor", "micro"], revision.split(".")):
            ET.SubElement(minimum, key).text = part


def repository_xml():
    root = ET.Element("sdk-repository")
    for package, revision in CATALOG:
        remote = ET.SubElement(root, "remotePackage", path=package.replace("/", ";"))
        add_dependencies(remote, package)
        version = ET.SubElement(remote, "revision")
        base, _, preview = revision.partition("-")
        for name, value in zip(["major", "minor", "micro"], base.split(".")):
            ET.SubElement(version, name).text = value
        if preview:
            ET.SubElement(version, "preview").text = preview.split(".")[-1]
        ET.SubElement(remote, "channelRef", ref="channel-3" if preview else "channel-0")
        archives = ET.SubElement(remote, "archives")
        for host in ["linux", "macosx"] if package.startswith("ndk/") else [None]:
            archive = ET.SubElement(archives, "archive")
            if host:
                ET.SubElement(archive, "host-os").text = host
            complete = ET.SubElement(archive, "complete")
            ET.SubElement(complete, "url").text = "https://example.invalid/package.zip"
    return ET.tostring(root, encoding="utf-8")


def main():
    arguments = sys.argv[1:]
    if len(arguments) < 4 or arguments[0] != "--sdk" or arguments[2] != "sdk":
        sys.exit("Expected --sdk ROOT sdk COMMAND")
    sdk = Path(arguments[1])
    action = arguments[3]
    if os.environ.get("FAKE_ANDROID_LOG"):
        with open(os.environ["FAKE_ANDROID_LOG"], "a", encoding="utf-8") as stream:
            stream.write(json.dumps(arguments) + "\n")
    if action == "remove":
        for package in arguments[4:]:
            if package not in {name for name, _ in CATALOG}:
                sys.exit("Unknown sample package")
            shutil.rmtree(sdk / package, ignore_errors=True)
        return
    if action != "install":
        sys.exit("Unsupported sample command")

    def install(package, revision):
        for name, minimum in dependencies(package):
            properties = sdk / name / "source.properties"
            existing = (
                properties.read_text().split("=", 1)[1].strip() if properties.exists() else None
            )
            if existing is None or tuple(map(int, existing.split("."))) < tuple(
                map(int, minimum.split("."))
            ):
                version = max(
                    (v for p, v in CATALOG if p == name),
                    key=lambda v: tuple(map(int, v.split("."))),
                )
                install(name, version)
        if os.environ.get("FAKE_ANDROID_FAIL_PACKAGE") == package:
            sys.exit("Simulated SDK download failure")
        component = sdk / package
        component.mkdir(parents=True, exist_ok=True)
        actual = "999" if os.environ.get("FAKE_ANDROID_WRONG_REVISION") else revision
        (component / "source.properties").write_text(f"Pkg.Revision={actual}\n")
        identity = "wrong-package" if os.environ.get("FAKE_ANDROID_WRONG_IDENTITY") else package
        node = ET.Element("localPackage", path=identity.replace("/", ";"))
        add_dependencies(node, package)
        (component / "package.xml").write_bytes(ET.tostring(node))
        executable = None
        if package == "platform-tools":
            executable = component / "adb"
        elif package == "emulator":
            executable = component / "emulator"
        elif package.startswith("ndk/"):
            executable = component / "ndk-build"
        if executable:
            executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{package}@{revision}'\n")
            executable.chmod(0o755)

    for specification in arguments[4:]:
        if specification in {"--beta", "--canary", "--force"}:
            continue
        package, revision = specification.rsplit("@", 1)
        parts = revision.split(".")
        if not 1 <= len(parts) <= 4 or any(not p.isascii() or not p.isdecimal() for p in parts):
            sys.exit("Expected a numeric Android CLI revision")
        if len(parts) == 4:
            revision = ".".join(parts[:3]) + "-rc." + parts[3]
        if (package, revision) not in CATALOG:
            sys.exit("Unknown sample package")
        install(package, revision)


if __name__ == "__main__":
    main()
