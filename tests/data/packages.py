"""Small Android package archives and repository metadata for offline tests."""

import hashlib
import xml.etree.ElementTree as ET
import zipfile

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

LICENSE = "Test SDK license: A & B < C.\n"


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


def archive_path(directory, package, revision):
    return directory / (package.replace("/", "_") + "@" + revision + ".zip")


def create_archives(directory):
    directory.mkdir()
    for package, revision in CATALOG:
        path = archive_path(directory, package, revision)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            properties_revision = (
                revision.replace("-rc.", "-beta") if package.startswith("ndk/") else revision
            )
            archive.writestr("content/source.properties", f"Pkg.Revision={properties_revision}\n")
            archive.writestr("content/NOTICE.txt", LICENSE)
            executable = None
            if package == "platform-tools":
                executable = "adb"
            elif package == "emulator":
                executable = "emulator"
            elif package.startswith("ndk/"):
                executable = "ndk-build"
            if executable:
                entry = zipfile.ZipInfo("content/" + executable)
                entry.external_attr = 0o100755 << 16
                archive.writestr(entry, f"#!/bin/sh\nprintf '%s\\n' '{package}@{revision}'\n")


def repository_xml(directory):
    root = ET.Element("sdk-repository")
    ET.SubElement(root, "license", id="test-license", type="text").text = LICENSE
    for package, revision in CATALOG:
        remote = ET.SubElement(root, "remotePackage", path=package.replace("/", ";"))
        ET.SubElement(remote, "uses-license", ref="test-license")
        ET.SubElement(remote, "display-name").text = package
        add_dependencies(remote, package)
        version = ET.SubElement(remote, "revision")
        base, _, preview = revision.partition("-")
        for name, value in zip(["major", "minor", "micro"], base.split(".")):
            ET.SubElement(version, name).text = value
        if preview:
            ET.SubElement(version, "preview").text = preview.split(".")[-1]
        ET.SubElement(remote, "channelRef", ref="channel-3" if preview else "channel-0")
        archives = ET.SubElement(remote, "archives")
        source = archive_path(directory, package, revision)
        native = package.split("/")[0] in {
            "ndk",
            "platform-tools",
            "build-tools",
            "cmake",
            "emulator",
        }
        for host in ["linux", "macosx"] if native else [None]:
            archive = ET.SubElement(archives, "archive")
            if host:
                ET.SubElement(archive, "host-os").text = host
            complete = ET.SubElement(archive, "complete")
            ET.SubElement(complete, "url").text = source.as_uri()
            ET.SubElement(complete, "size").text = str(source.stat().st_size)
            ET.SubElement(complete, "checksum", type="sha1").text = hashlib.sha1(
                source.read_bytes()
            ).hexdigest()
    return ET.tostring(root, encoding="utf-8")
