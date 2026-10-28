"""Entry point called by mise's Lua hooks."""

import json
import os
import sys

from android_mise.backend import dispatch
from android_mise.model import BackendError


def main():
    try:
        if sys.platform not in {"linux", "darwin"}:
            raise BackendError("mise-android supports Linux and macOS")
        if len(sys.argv) != 2:
            raise BackendError("Expected one hook action")
        raw = os.environ.get("MISE_ANDROID_REQUEST")
        if raw is None:
            raise BackendError("MISE_ANDROID_REQUEST is missing; invoke this helper through mise")
        try:
            request = json.loads(raw)
        except ValueError as error:
            raise BackendError(f"Invalid mise request JSON: {error}") from error
        print(json.dumps(dispatch(sys.argv[1], request)))
    except (BackendError, OSError) as error:
        print(f"mise-android: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
