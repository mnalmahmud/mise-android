# Contributing

Keep changes small, the code easy to follow, and the README accurate.
The plugin uses the Lua interpreter included with mise and a small Bash script.
Python is used only to run the development tests.

## Run the checks

From the project folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
MISE_ANDROID_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check lib tests
.venv/bin/ruff format --check lib tests
mise exec stylua@2.5.2 -- stylua --check lib hooks metadata.lua tests/unit.lua
```

The second test command runs the Lua checks and tests the plugin through mise.
It needs `mise` on your command search path. Set `MISE_BIN` to use a different mise
executable. You do not need a separate Lua installation.

Tests use temporary folders and a small replacement for Google's `android` command.
They must not download Android SDK packages, accept licenses, or change a real SDK.
GitHub runs the checks on Linux and macOS with Python 3.10 and 3.14. It also tests
both the oldest supported mise release and the current stable release.

## Find the code

| File or folder | What it does |
| --- | --- |
| `hooks/` | Receive calls from mise |
| `lib/android.lua` | Find the Android command, install packages, and set project paths |
| `lib/common.lua` | Check settings, compare versions, download files, and save records |
| `lib/catalog.lua` | Read Google's package lists and find suitable versions |
| `lib/xml.lua` | Read the XML format used by Google's lists |
| `lib/install.sh` | Run the installer and stop it and its children if it takes too long |
| `tests/unit.lua` | Check the Lua code inside mise's own interpreter |
| `tests/data/` | Sample package lists and the test `android` command |

## Keep these rules

- Find every requested package before starting an installation.
- Check the result before saving a successful installation record.
- Keep each SDK inside the folder mise provides for it.
- Read files when switching SDKs; do not change them or contact Google.
- Keep separately installed tools independent of SDKs.
- Keep one format for installation records; this project has no older releases to support.
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

Include your OS and mise version, the relevant `mise.toml` settings, the
command you ran, and its error output. Remove private values before sharing them.
For a code change, explain what was wrong, what changed, and which checks passed.
