"""Installation manifests and verification of Android package metadata."""

import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .model import BackendError, Options, package_path, revision

MANIFEST = ".mise-android-package.json"


def atomic_write(path: Path, content: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, data: dict) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackendError(f"Cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise BackendError(f"Expected an object in {path}")
    return data


def read_revision(component: Path) -> str | None:
    properties = component / "source.properties"
    if not properties.is_file():
        return None
    match = re.search(
        r"(?m)^Pkg\.Revision[ \t]*=[ \t]*(.+)$", properties.read_text(encoding="utf-8")
    )
    return revision(match.group(1)) if match else None


def verify_component(component: Path, package: str, expected: str) -> None:
    actual = read_revision(component)
    if actual != expected:
        raise BackendError(
            f"Expected {package}@{expected}, found revision {actual!r} in {component}"
        )
    metadata = component / "package.xml"
    if metadata.exists():
        try:
            tree = ET.parse(metadata)
            local = next(
                node for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "localPackage"
            )
            identity = package_path(local.attrib["path"].replace(";", "/"))
        except (ET.ParseError, KeyError, StopIteration) as error:
            raise BackendError(f"Invalid Android package metadata in {metadata}") from error
        if identity != package:
            raise BackendError(f"Package metadata identifies {identity}, expected {package}")


def load_manifest(install: Path) -> dict:
    data = read_json(install / MANIFEST)
    if type(data.get("schema")) is not int or data["schema"] != 1:
        raise BackendError(f"Unsupported install manifest in {install}; reinstall this tool")
    package_path(data.get("tool"))
    revision(data.get("version"))
    components = data.get("components")
    if not isinstance(components, list) or not components:
        raise BackendError(f"Invalid component list in {install / MANIFEST}")
    for component in components:
        if not isinstance(component, dict):
            raise BackendError(f"Invalid component in {install / MANIFEST}")
        package_path(component.get("package"))
        revision(component.get("revision"))
    if not isinstance(data.get("packages"), dict):
        raise BackendError(f"Invalid packages in {install / MANIFEST}")
    options = Options.parse({"packages": data["packages"], "channel": data.get("channel")})
    data["packages"] = options.packages
    return data
