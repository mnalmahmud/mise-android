"""Find an existing Android CLI, or cache a SHA-256-verified Google binary."""

import fcntl
import hashlib
import os
import platform
import re
import sys
from pathlib import Path

from . import network
from .model import BackendError, version_key
from .storage import atomic_write

BASE_URL = "https://dl.google.com/android/cli"
VERSION_INDEX = BASE_URL + "/latest/debian/dists/stable/main/binary-amd64/Packages"


def platform_name(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    architecture = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    result = {
        ("linux", "x86_64"): "linux_x86_64",
        ("darwin", "x86_64"): "darwin_x86_64",
        ("darwin", "arm64"): "darwin_arm64",
    }.get((system, architecture))
    if not result:
        raise BackendError(
            f"Google publishes no supported Android CLI binary for {system}/{machine}. "
            "An existing compatible android executable on PATH can still be used."
        )
    return result


def existing_cli():
    for directory in os.get_exec_path():
        path = Path(directory) / "android"
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        # Re-entering an unresolved mise shim while bootstrapping can recurse.
        if path.resolve().name in {"mise", "mise.exe"} or (
            path.parent.name == "shims" and path.parent.parent.name == "mise"
        ):
            continue
        return path.absolute()
    return None


def parse_latest(data: bytes) -> str:
    versions = []
    try:
        paragraphs = data.decode("utf-8").split("\n\n")
    except UnicodeDecodeError as error:
        raise BackendError("Google returned an invalid Android CLI package index") from error
    for paragraph in paragraphs:
        if re.search(r"(?m)^Package: android-cli\s*$", paragraph):
            match = re.search(r"(?m)^Version: (\d+(?:\.\d+)*)\s*$", paragraph)
            if match:
                versions.append(match.group(1))
    if not versions:
        raise BackendError("Google's package index contains no Android CLI version")
    return max(versions, key=version_key)


def parse_checksum(data: bytes) -> str:
    try:
        text = data.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise BackendError("Google returned an invalid Android CLI SHA-256 file") from error
    match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?(?:\./)?android)?", text)
    if not match:
        raise BackendError("Google returned an invalid Android CLI SHA-256 file")
    return match.group(1).lower()


def resolve(timeout=30) -> Path:
    existing = existing_cli()
    if existing:
        return existing
    target_platform = platform_name()
    cache = network.cache_root()
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(cache / "bootstrap.lock", flags, 0o600), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        version = parse_latest(network.cached_read(VERSION_INDEX, min(timeout, 60)))
        directory = cache / version / target_platform
        executable = directory / "android"
        digest_file = directory / "sha256"
        if executable.is_file() and digest_file.is_file():
            digest = digest_file.read_bytes().strip()
            if (
                re.fullmatch(rb"[0-9a-f]{64}", digest)
                and hashlib.sha256(executable.read_bytes()).hexdigest().encode("ascii") == digest
            ):
                executable.chmod(0o755)
                return executable
        url = f"{BASE_URL}/{version}/{target_platform}/android"
        expected = parse_checksum(network.read(url + ".sha256", min(timeout, 60), 4096))
        content = network.read(url, min(timeout, 120), 64 * 1024 * 1024)
        if hashlib.sha256(content).hexdigest() != expected:
            raise BackendError(
                "Android CLI checksum mismatch; the downloaded file was not installed"
            )
        atomic_write(executable, content, mode=0o755)
        atomic_write(digest_file, (expected + "\n").encode("ascii"))
        return executable
