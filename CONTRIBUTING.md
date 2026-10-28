# Contributing

Keep the backend small and its behavior explicit. Runtime dependencies are Python's
standard library and mise's Lua modules. Use tests that run offline and leave a
developer's SDKs and configuration untouched.

## Local setup

Create a temporary project with a `mise.toml`, enable `experimental`, and link this
checkout as the backend:

```sh
mise plugins link android /absolute/path/to/mise-android
```

On mise 2026.10.19, an explicit link is required for local development; a local path
in `[plugins]` alone does not install the backend. Use a disposable project directory
and mise data, cache, and state directories when exercising installation manually.
The integration tests already provide that isolation.

## Architecture

The Lua hooks pass JSON requests through the environment to `lib/android_backend.py`.
That entry point handles the protocol and reports expected errors to mise. The
implementation lives in `lib/android_mise/`:

| Module | Owns |
| --- | --- |
| `model.py` | Request validation, package identifiers, revisions, options |
| `catalog.py` | Repository XML, host/channel filtering, version discovery |
| `network.py` | URL policy, bounded reads, metadata cache location and lifetime |
| `bootstrap.py` | CLI discovery, download locking, checksum-verified CLI caching |
| `android_cli.py` | Installer arguments, execution, timeout cleanup |
| `backend.py` | Package planning, installation, activation environment |
| `storage.py` | Atomic writes, manifests, installed-package metadata checks |

Installation resolves the complete plan, invokes Android CLI once, verifies every
requested package, and atomically writes the manifest. A failed plan must not start
the installer. A failed installer or verification must not commit a manifest.

Activation must remain read-only and work without network access or CLI execution.
mise caches its output. Keep SDK files under the installation directory supplied by
mise; do not introduce shared links, a shared mutable SDK, or a cleanup database.
Standalone packages must remain independent of complete SDKs.

## Checks

From the checkout, run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
MISE_ANDROID_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check lib tests
.venv/bin/ruff format --check lib tests
```

Integration tests require a real mise binary on `PATH`; set `MISE_BIN` to choose a
specific executable. They use temporary directories, local repository XML, and a
small test CLI. They must not download SDK archives or accept licenses.

Test repository changes with representative XML under `tests/data/`. Cover host
selection, channels, previews, and malformed metadata. Test installer failures and
final verification, including subprocess cleanup when changing execution behavior.
Run real-mise integration tests after changing hooks, options, layout, or activation.
mise passes scalar options to hooks as strings, including TOML integers and booleans.

CI checks Python 3.10 and 3.14 on Linux and macOS, with separate integration jobs for
the minimum supported mise release and the action's current stable default. A green
Linux run does not substitute for macOS validation.

## Changes and bug reports

Describe the observed problem, resulting behavior, and checks performed. Keep
README examples aligned with the implementation. Include OS, Python and mise
versions, the tool identifier, a minimal configuration, and relevant error output
when reporting a bug. Remove credentials and other private values from reports.
