"""Offline Android CLI sample. It never touches a real SDK or contacts Google."""

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CATALOG = [
    ("platform-tools", "36.0.0"),
    ("platform-tools", "37.0.1"),
    ("ndk/29.0.1", "29.0.1"),
    ("ndk/30.0.1", "30.0.1"),
    ("ndk/31.0.1", "31.0.1-rc.2"),
    ("build-tools/36.0.0", "36.0.0"),
    ("platforms/android-36", "3"),
    ("platforms/android-37", "1"),
]


def repository_xml():
    root = ET.Element("sdk-repository")
    for package, revision in CATALOG:
        remote = ET.SubElement(root, "remotePackage", path=package.replace("/", ";"))
        version = ET.SubElement(remote, "revision")
        base, _, preview = revision.partition("-")
        for name, value in zip(["major", "minor", "micro"], base.split(".")):
            ET.SubElement(version, name).text = value
        if preview:
            ET.SubElement(version, "preview").text = preview.split(".")[-1]
        ET.SubElement(remote, "channelRef", ref="channel-3" if preview else "channel-0")
        archive = ET.SubElement(ET.SubElement(remote, "archives"), "archive")
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
    if action != "install":
        sys.exit("Unsupported sample command")
    for specification in arguments[4:]:
        if specification in {"--beta", "--canary"}:
            continue
        package, revision = specification.rsplit("@", 1)
        if (package, revision) not in CATALOG:
            sys.exit("Unknown sample package")
        if os.environ.get("FAKE_ANDROID_FAIL_PACKAGE") == package:
            sys.exit("Simulated SDK download failure")
        component = sdk / package
        component.mkdir(parents=True)
        actual = "999" if os.environ.get("FAKE_ANDROID_WRONG_REVISION") else revision
        (component / "source.properties").write_text(f"Pkg.Revision={actual}\n")
        identity = "wrong-package" if os.environ.get("FAKE_ANDROID_WRONG_IDENTITY") else package
        (component / "package.xml").write_text(
            f'<repository><localPackage path="{identity.replace("/", ";")}"/></repository>'
        )
        if package == "platform-tools":
            executable = component / "adb"
        elif package.startswith("ndk/"):
            executable = component / "ndk-build"
        else:
            continue
        executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{package}@{revision}'\n")
        executable.chmod(0o755)


if __name__ == "__main__":
    main()
