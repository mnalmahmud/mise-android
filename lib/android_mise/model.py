"""Validated requests, SDK identifiers, and package revisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class BackendError(Exception):
    """An actionable failure reported to mise without a Python traceback."""


FAMILIES = frozenset({"ndk", "build-tools", "cmdline-tools", "cmake"})
KNOWN_OPTIONS = frozenset({"channel", "packages", "repository_url", "timeout"})
REVISION = re.compile(r"^(\d+(?:\.\d+)*)(?:[- ]?(alpha|beta|rc)[. ]?(\d+))?$", re.I)


def package_path(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.+-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.+-]*)*", value
    ):
        raise BackendError(f"Invalid SDK package path: {value!r}; use slash-delimited names")
    return value


def metadata_url(value: Any) -> str:
    message = "repository_url must be an HTTPS URL or an absolute local file:// URL"
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise BackendError(message)
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and parsed.port != 0:
            return value
        if (
            parsed.scheme == "file"
            and parsed.netloc in {"", "localhost"}
            and parsed.path.startswith("/")
        ):
            return value
    except ValueError as error:
        raise BackendError(message) from error
    raise BackendError(message)


def revision(value: str) -> str:
    if not isinstance(value, str):
        raise BackendError("Android revisions must be strings")
    match = REVISION.fullmatch(value.strip())
    if not match:
        raise BackendError(f"Unsupported Android revision: {value!r}")
    base, kind, number = match.groups()
    base = ".".join(str(int(part)) for part in base.split("."))
    return base + (f"-{kind.lower()}.{int(number)}" if kind else "")


def version_key(value: str) -> tuple:
    base, _, preview = revision(value).partition("-")
    numbers = tuple(int(part) for part in base.split("."))
    # 1, 1.0 and 1.0.0 compare equally before preview/final ordering.
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    if not preview:
        return numbers, 3, 0
    kind, number = preview.split(".")
    return numbers, {"alpha": 0, "beta": 1, "rc": 2}[kind], int(number)


def is_sdk(tool: str) -> bool:
    return tool == "sdk" or tool.startswith("sdk/")


def absolute_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise BackendError(f"{name} must be a nonempty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise BackendError(f"{name} must be absolute (or start with ~/)")
    return path.resolve()


@dataclass(frozen=True)
class Options:
    channel: str
    packages: dict[str, str] | None
    repository_url: str | None
    timeout: int

    @classmethod
    def parse(cls, raw: dict | None) -> Options:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise BackendError("Tool options must be a table")
        unknown = set(raw) - KNOWN_OPTIONS
        if unknown:
            raise BackendError("Unknown Android option(s): " + ", ".join(sorted(unknown)))
        channel = raw.get("channel", "stable")
        if not isinstance(channel, str) or channel not in {"stable", "beta", "canary"}:
            raise BackendError("channel must be stable, beta, or canary")
        packages = raw.get("packages")
        if packages is not None:
            if not isinstance(packages, dict):
                raise BackendError("packages must be a table of SDK package names and versions")
            normalized = {}
            for name, version in packages.items():
                package_path(name)
                if is_sdk(name):
                    raise BackendError("SDK bundles cannot contain another SDK bundle")
                normalized[name] = version if version == "latest" else revision(version)
            packages = normalized
        repository = raw.get("repository_url")
        if repository is not None:
            repository = metadata_url(repository)
        timeout = raw.get("timeout", 1800)
        # mise serializes scalar tool options as strings, including TOML integers.
        if isinstance(timeout, str) and re.fullmatch(r"[0-9]{1,5}", timeout):
            timeout = int(timeout)
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise BackendError("timeout must be an integer between 1 and 86400 seconds")
        return cls(channel, packages, repository, timeout)


@dataclass(frozen=True)
class Request:
    tool: str
    options: Options
    version: str | None
    install_path: Path | None

    @classmethod
    def parse(cls, data: dict) -> Request:
        if not isinstance(data, dict):
            raise BackendError("Expected a JSON object from mise")
        tool = package_path(data.get("tool"))
        version = revision(data["version"]) if data.get("version") else None
        install_path = (
            absolute_path(data["install_path"], "install_path")
            if data.get("install_path")
            else None
        )
        options = Options.parse(data.get("options"))
        if options.packages is not None and not is_sdk(tool):
            raise BackendError("The packages option is only available for android:sdk entries")
        return cls(tool, options, version, install_path)

    def installation(self) -> Path:
        if self.install_path is None or self.version is None:
            raise BackendError("This hook requires install_path and a resolved version")
        return self.install_path


@dataclass(frozen=True)
class Package:
    path: str
    revision: str
    version: str
    download_url: str = ""
    checksum_type: str = ""
    checksum: str = ""
