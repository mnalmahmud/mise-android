# Contributing

Keep changes small, the code easy to follow, and the README accurate.
The plugin uses Python's standard library and the Lua tools included with mise.

## Run the checks

From the project folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
MISE_ANDROID_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check lib tests
.venv/bin/ruff format --check lib tests
```

The second test command also tests the plugin through mise. It needs `mise` on your
command search path. Set `MISE_BIN` to use a different mise executable.

Tests use temporary folders and a small replacement for Google's `android` command.
They must not download Android SDK packages, accept licenses, or change a real SDK.
GitHub runs the checks on Linux and macOS with Python 3.10 and 3.14. It also tests
both the oldest supported mise release and the current stable release.

## Find the code

| File or folder | What it does |
| --- | --- |
| `hooks/` and `lib/bridge.lua` | Receive calls from mise and pass them to Python |
| `lib/android_backend.py` | Read the request, run it, and return a result or error |
| `lib/android_mise/model.py` | Check settings, names, and version numbers |
| `lib/android_mise/catalog.py` | Read Google's package lists and find suitable versions |
| `lib/android_mise/network.py` | Download files and save temporary copies of package lists |
| `lib/android_mise/bootstrap.py` | Find or download Google's `android` command |
| `lib/android_mise/android_cli.py` | Run that command and stop it if it takes too long |
| `lib/android_mise/backend.py` | Decide what to install and what settings a project needs |
| `lib/android_mise/storage.py` | Save installation records and check installed packages |
| `tests/data/` | Sample package lists and the test `android` command |

## Keep these rules

- Find every requested package before starting an installation.
- Check the result before saving a successful installation record.
- Keep each SDK inside the folder mise provides for it.
- Read files when switching SDKs; do not change them or contact Google.
- Keep separately installed tools independent of SDKs.
- Leave the user's shell settings and existing SDKs alone.

When changing package-list handling, test missing and invalid entries, previews,
and packages for different machines. When changing installation, test failures as
well as success. Run the tests through mise after changing settings or how the
plugin is called. mise passes simple settings as strings, even TOML numbers and
booleans.

## Try a local copy

Use a temporary project and link this checkout:

```sh
mise plugins link android /absolute/path/to/mise-android
```

Add the settings and tools from the README to the temporary project's `mise.toml`.
On mise 2026.10.19, the link command is required; a local path in `[plugins]` alone
is not enough. Use separate mise data, cache, and state folders for manual testing,
just as the tests do.

## Report a problem

Include your OS, Python and mise versions, the relevant `mise.toml` settings, the
command you ran, and its error output. Remove private values before sharing them.
For a code change, explain what was wrong, what changed, and which checks passed.
