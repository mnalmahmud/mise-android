"""Bounded downloads and one shared cache policy for upstream metadata."""

import hashlib
import os
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import BackendError, metadata_url
from .storage import atomic_write

METADATA_LIMIT = 16 * 1024 * 1024
CACHE_SECONDS = 3600


def cache_root() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "mise-android"
    if sys.platform == "darwin":
        return Path.home() / "Library/Caches/mise-android"
    return Path.home() / ".cache/mise-android"


class HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise BackendError("Refusing an HTTPS download redirected to an insecure URL")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def read(url: str, timeout: int = 30, maximum: int = METADATA_LIMIT) -> bytes:
    metadata_url(url)
    try:
        request = Request(url, headers={"User-Agent": "mise-android/0.1.0"})
        with build_opener(HTTPSRedirectHandler()).open(request, timeout=timeout) as response:
            content = response.read(maximum + 1)
    except (OSError, URLError, ValueError) as error:
        raise BackendError(f"Cannot fetch {url}: {error}") from error
    if len(content) > maximum:
        raise BackendError(f"Response from {url} exceeds the {maximum}-byte limit")
    return content


def cached_read(url: str, timeout: int = 30) -> bytes:
    metadata_url(url)
    if urlparse(url).scheme == "file":
        return read(url, timeout)
    path = cache_root() / "metadata" / hashlib.sha256(url.encode()).hexdigest()
    try:
        age = time.time() - path.stat().st_mtime
        if 0 <= age < CACHE_SECONDS:
            with path.open("rb") as stream:
                content = stream.read(METADATA_LIMIT + 1)
            if len(content) <= METADATA_LIMIT:
                return content
    except FileNotFoundError:
        pass
    content = read(url, timeout)
    atomic_write(path, content)
    return content
