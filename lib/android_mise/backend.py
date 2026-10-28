"""Isolated SDK installations; activation reads metadata and never changes files."""

from dataclasses import replace

from . import android_cli, catalog
from .model import BackendError, Request, is_sdk, version_key
from .storage import MANIFEST, atomic_json, load_manifest, verify_component


def select(request: Request, version: str):
    available = catalog.catalog(request)
    selected = max(available, key=version_key) if version == "latest" else version
    if selected not in available:
        raise BackendError(
            f"Repository does not offer {request.tool}@{version} in {request.options.channel}"
        )
    return available[selected]


def plan(request: Request):
    base = select(request, request.version)
    components = {base.path: base}
    if is_sdk(request.tool):
        for tool, version in sorted((request.options.packages or {}).items()):
            component = select(replace(request, tool=tool), version)
            existing = components.get(component.path)
            if existing and existing.revision != component.revision:
                raise BackendError(f"An SDK cannot contain two revisions of {component.path}")
            components[component.path] = component
    return list(components.values())


def install(request: Request) -> dict:
    root = request.installation()
    sdk = root / "sdk"
    if sdk.exists() or sdk.is_symlink():
        raise BackendError(f"SDK installation already exists: {sdk}; reinstall through mise")
    components = plan(request)
    sdk.mkdir(parents=True)
    android_cli.run(
        request, sdk, "install", *(package.path + "@" + package.revision for package in components)
    )
    installed = []
    for package in components:
        verify_component(sdk / package.path, package.path, package.revision)
        installed.append(
            {
                "package": package.path,
                "revision": package.revision,
                "download": {
                    "url": package.download_url,
                    "checksum_type": package.checksum_type,
                    "checksum": package.checksum,
                },
            }
        )
    atomic_json(
        root / MANIFEST,
        {
            "schema": 1,
            "tool": request.tool,
            "version": request.version,
            "channel": request.options.channel,
            "components": installed,
            "packages": request.options.packages or {},
        },
    )
    return {}


def environment(request: Request) -> dict:
    root = request.installation()
    manifest = load_manifest(root)
    if manifest["tool"] != request.tool or manifest["version"] != request.version:
        raise BackendError(f"Installation does not match {request.tool}@{request.version}")
    if manifest["packages"] != (request.options.packages or {}):
        raise BackendError("SDK packages changed since installation; reinstall this tool")
    if manifest["channel"] != request.options.channel:
        raise BackendError("Release channel changed since installation; reinstall this tool")
    sdk = root / "sdk"
    values, paths, ndks = [], [], []
    if is_sdk(request.tool):
        values.append({"key": "ANDROID_HOME", "value": str(sdk)})
    for component in manifest["components"]:
        path = sdk / component["package"]
        if not path.is_dir():
            raise BackendError(f"Installed SDK component is missing: {path}; reinstall it")
        family = component["package"].split("/", 1)[0]
        if family == "ndk":
            ndks.append((component["revision"], path))
        if family in {"cmdline-tools", "cmake"}:
            paths.append(path / "bin")
        elif family not in {"platforms", "system-images", "sources"}:
            paths.append(path)
    if ndks:
        _, selected = max(ndks, key=lambda item: version_key(item[0]))
        values.append({"key": "ANDROID_NDK_HOME", "value": str(selected)})
    values.extend(
        {"key": "PATH", "value": str(path)} for path in dict.fromkeys(paths) if path.is_dir()
    )
    return {"env_vars": values}


def dispatch(action: str, data: dict) -> dict:
    request = Request.parse(data)
    if action == "versions":
        return {"versions": sorted(catalog.catalog(request), key=version_key)}
    if action == "install":
        return install(request)
    if action == "env":
        return environment(request)
    raise BackendError(f"Unknown backend action: {action!r}")
