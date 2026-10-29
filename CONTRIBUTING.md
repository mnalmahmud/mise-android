# Contributing

## Checks

Tests use Python and a real mise executable. They run the Lua checks through mise,
using temporary folders, local package lists, and a test Android command.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check tests
.venv/bin/ruff format --check tests
mise exec stylua@2.5.2 -- stylua --check lib hooks metadata.lua tests/unit.lua
```

Set `MISE_BIN` to test a particular mise executable. GitHub runs the checks on
Linux and macOS with the oldest supported mise release and the current stable
release.

## Code layout

| Location | Purpose |
| --- | --- |
| `hooks/` | Receive calls from mise |
| `lib/android.lua` | Find the Android command, check project requests, and install or remove packages |
| `lib/sdk.lua` | Locate the shared SDK, read installed packages, save receipts, and return project paths |
| `lib/common.lua` | Check settings, compare versions, download files, and save records |
| `lib/catalog.lua` | Read Google's package lists and select suitable versions |
| `lib/xml.lua` | Read the XML used by the package lists |
| `tests/unit.lua` | Check Lua behavior in mise's interpreter |
| `tests/test_integration.py` | Test complete operations through mise |
| `tests/data/` | Sample package lists and the test Android command |

## Making changes

Resolve project requests and check dependency minimums before starting the installer.
Check installed versions and names before saving the tool's installation receipt.

Keep all packages in mise's shared `android/sdk` folder. Read Google's package
metadata for installed versions and dependencies. Each mise tool entry keeps a
receipt for its requested package. Removing an old receipt should preserve a
different version currently installed in a shared package location.

Activation reads package information and returns paths. Installation and removal
invalidate mise's cached environment results after updating the SDK. Test a version
change after activation has already populated that cache.

Cover package-list errors, preview releases, and downloads for different machines
when changing version selection. Cover failures and timeouts when changing
installation. Run the tests through mise after changing settings or hooks. mise
passes simple settings as strings, including TOML numbers and booleans.

## Local testing

Link the checkout from a temporary project:

```sh
mise plugins link android /absolute/path/to/mise-android
```

Add the README's settings and tools to that project's `mise.toml`. mise 2026.10.19
requires the link command for local testing. Use temporary mise data, cache, and
state folders, following `tests/test_integration.py`.

## Bug reports and changes

Include your OS, mise version, relevant configuration, command, and error output
in a bug report. Remove private values before sharing it.

For a code change, explain the problem, resulting behavior, and checks performed.
Update the README when the user-facing behavior changes.
