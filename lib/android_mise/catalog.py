"""Version discovery from Google's structured SDK repository XML."""

import platform
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from . import network
from .model import (
    FAMILIES,
    BackendError,
    Package,
    Request,
    is_sdk,
    package_path,
    revision,
    version_key,
)

DEFAULT_REPOSITORY = "https://dl.google.com/android/repository/repository2-3.xml"


def local_name(node):
    return node.tag.rsplit("}", 1)[-1]


def children(node, name):
    return [child for child in node if local_name(child) == name]


def child(node, name):
    return next((child for child in node if local_name(child) == name), None)


def text(node, name, default=""):
    element = child(node, name)
    return element.text.strip() if element is not None and element.text else default


def repository_url(request):
    if request.options.repository_url:
        return request.options.repository_url
    if request.tool.startswith("system-images/"):
        parts = request.tool.split("/")
        if len(parts) != 4:
            raise BackendError("System images require system-images/API/TAG/ABI")
        return f"https://dl.google.com/android/repository/sys-img/{parts[2]}/sys-img2-3.xml"
    return DEFAULT_REPOSITORY


def host_archive(archives, system, machine):
    host_os = {"linux": "linux", "darwin": "macosx"}.get(system)
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(
        machine.lower()
    )
    if archives is None or host_os is None or arch is None:
        return None
    for archive in children(archives, "archive"):
        target_os = text(archive, "host-os")
        target_arch = text(archive, "host-arch")
        if target_os and target_os != host_os:
            continue
        if target_arch and target_arch != arch:
            continue
        if text(archive, "host-bits") not in {"", "64"}:
            continue
        complete = child(archive, "complete")
        if complete is not None and text(complete, "url"):
            return complete
    return None


def parse_repository(
    data, tool, channel="stable", *, url=DEFAULT_REPOSITORY, system=None, machine=None
):
    package_path(tool)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise BackendError(f"Invalid Android repository XML: {error}") from error
    if local_name(root) not in {"sdk-repository", "sdk-sys-img"}:
        raise BackendError("Unexpected Android repository XML root")
    versions = {}
    maximum_channel = {"stable": 0, "beta": 1, "canary": 3}[channel]
    for node in children(root, "remotePackage"):
        path = node.get("path", "").replace(";", "/")
        if is_sdk(tool):
            if not path.startswith("platforms/android-"):
                continue
            api = path.removeprefix("platforms/android-")
            if not api or not all(part.isdigit() for part in api.split(".")):
                continue
            selected = revision(api)
        elif tool in FAMILIES:
            if not path.startswith(tool + "/") or "/" in path[len(tool) + 1 :]:
                continue
            leaf = path[len(tool) + 1 :]
            if leaf == "latest":
                continue
            selected = revision(leaf)
        elif path == tool:
            selected = None
        else:
            continue
        package_path(path)
        channel_ref = child(node, "channelRef")
        channel_id = channel_ref.get("ref", "channel-0") if channel_ref is not None else "channel-0"
        if not channel_id.startswith("channel-") or not channel_id[8:].isdigit():
            raise BackendError(f"Invalid channel metadata for {path}")
        if int(channel_id[8:]) > maximum_channel:
            continue
        version_node = child(node, "revision")
        if version_node is None or not text(version_node, "major").isdigit():
            raise BackendError(f"Missing package revision for {path}")
        parts = [text(version_node, "major")]
        for name in ["minor", "micro"]:
            if child(version_node, name) is not None:
                value = text(version_node, name)
                if not value.isdigit():
                    raise BackendError(f"Invalid package revision for {path}")
                parts.append(value)
        actual = ".".join(parts)
        preview = text(version_node, "preview")
        if preview:
            if not preview.isdigit():
                raise BackendError(f"Invalid preview revision for {path}")
            actual += "-rc." + preview
        actual = revision(actual)
        if channel == "stable" and "-" in actual:
            continue
        selected = selected or actual
        if "-" in actual and "-" not in selected:
            selected += "-" + actual.split("-", 1)[1]
        archive = host_archive(
            child(node, "archives"), system or sys.platform, machine or platform.machine()
        )
        if archive is None:
            continue
        checksum = child(archive, "checksum")
        package = Package(
            path,
            actual,
            selected,
            urljoin(url, text(archive, "url")),
            checksum.get("type", "sha1") if checksum is not None else "",
            checksum.text.strip() if checksum is not None and checksum.text else "",
        )
        if selected in versions and versions[selected] != package:
            previous = versions[selected]
            if is_sdk(tool) and previous.path == package.path and previous.revision != actual:
                if version_key(previous.revision) > version_key(actual):
                    continue
            else:
                raise BackendError(f"Ambiguous repository revisions for {tool}@{selected}")
        versions[selected] = package
    if not versions:
        raise BackendError(f"No {channel} versions of {tool} are available for this host")
    return versions


def catalog(request: Request):
    url = repository_url(request)
    return parse_repository(
        network.cached_read(url), request.tool, request.options.channel, url=url
    )
