# mise-android

A [mise](https://mise.jdx.dev/) backend for Android SDKs and individual SDK packages.
Lua hooks call a Python implementation that uses only the standard library.

Each installation owns its SDK files. Selecting a complete SDK sets `ANDROID_HOME`
and adds its tools to `PATH`. An included NDK also sets `ANDROID_NDK_HOME`.
Activation reads the installation manifest without changing files.

## Requirements

- mise 2026.10.19 or newer, with experimental backends enabled.
- Python 3.10 or newer on `PATH` as `python3`.
- Linux or macOS on x64 or ARM64. Packages must be available for the host.

The backend uses an executable named `android` on `PATH`, skipping mise shims.
Otherwise it downloads Google's Android CLI into its own cache and verifies the
published SHA-256. Automatic CLI downloads support Linux x64 and macOS x64/ARM64.
Linux ARM64 requires an existing compatible CLI. Windows is unsupported.

## Setup

Install the backend:

```sh
mise plugins install vfox-backend:android https://github.com/mnalmahmud/mise-android
```

Create a `mise.toml`:

```toml
[settings]
experimental = true

[plugins]
"vfox-backend:android" = "https://github.com/mnalmahmud/mise-android"

[tools]
"core:python" = "3.14"
"android:sdk" = "36"
```

Run `mise install`. This installs the Android 36 platform only.
To include other components, replace the SDK entry with an explicit package table:

```toml
"android:sdk" = { version = "36", packages = { platform-tools = "latest", build-tools = "36.0.0", ndk = "latest" } }
```

Then reinstall and check the selected platform-tools:

```sh
mise install --force android:sdk
mise exec -- adb version
```

The backend does not accept SDK licenses on your behalf. License handling belongs
to Google's tooling.

## Complete SDKs

`android:sdk` versions are Android API levels. The corresponding platform is always
installed. Omitting `packages`, or setting `packages = {}`, adds no other components.
Package versions can be pinned or set to `latest`, which is resolved at installation.

Use a name when the same API level needs different component sets:

```toml
"android:sdk/native" = { version = "36", packages = { ndk = "latest" } }
```

Another project can use a different name, such as `sdk/mobile`, for its component
set. Names create separate installation identities. Activate one complete SDK at a
time so `ANDROID_HOME` has one owner. Let the backend supply Android environment
variables instead of hardcoding them in shell startup files or mise's `[env]` table.
If an SDK contains multiple NDK revisions, `ANDROID_NDK_HOME` selects the highest.
An SDK without an NDK does not set that variable.

After changing `packages` or `channel`, reinstall the affected entry. Reinstall also
refreshes components set to `latest`; upgrading the SDK API level is a separate step.
For a named SDK:

```sh
mise install --force android:sdk/native
```

## Individual packages

Standalone packages expose their own executables without setting `ANDROID_HOME` or
joining other installations. A standalone NDK also sets `ANDROID_NDK_HOME`.

| Tool | Version selects |
| --- | --- |
| `android:sdk`, `android:sdk/NAME` | Android API level |
| `android:platform-tools`, `android:emulator` | Package revision |
| `android:ndk`, `android:build-tools`, `android:cmdline-tools`, `android:cmake` | Versioned package directory |
| `android:platforms/android-36` | Revision of that exact platform package |
| `android:system-images/android-36/google_apis/x86_64` | Revision of that exact image package |

Use slashes in package identifiers, including keys in `packages`.
List available versions before choosing one:

```sh
mise ls-remote android:ndk
```

Discovery reads Google's repository XML and filters by host and release channel.
Only revisions present in that metadata can be selected. Stable excludes previews.
For another channel:

```toml
"android:ndk" = { version = "latest", channel = "canary" }
```

Preview suffixes remain part of the version. mise's prerelease selection rules still
apply; pin a preview or configure mise to include prereleases when needed.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `packages` | No additions | SDK component names mapped to versions; complete SDKs only |
| `channel` | `"stable"` | `stable`, `beta`, or `canary` |
| `timeout` | `1800` | Installer timeout in seconds, from 1 to 86400 |
| `repository_url` | Google's repository for the package | HTTPS metadata URL or absolute local `file://` URL |

Unknown options and invalid values are rejected. `repository_url` changes discovery
metadata only; Android CLI still controls package download sources.

## Storage and verification

Each mise installation contains `sdk/` and `.mise-android-package.json`. The backend
resolves all requested packages before starting one installer command, passes that
SDK directory explicitly, and checks the final package revisions. It also checks
package identities when `package.xml` is present. The manifest is written only after
verification succeeds. Timeouts terminate the installer process group.

The manifest records selected archive URLs and published checksums as provenance.
SDK archive downloads and their verification are delegated to Android CLI; the
backend does not independently verify those downloaded archives. An existing CLI
on `PATH` is trusted as a user-provided executable. A downloaded CLI is checked
against Google's SHA-256 file before installation and against its cached digest
before reuse.

Metadata is cached for one hour. Local metadata files are read directly. The cache
lives under an absolute `$XDG_CACHE_HOME/mise-android`, or defaults to
`~/.cache/mise-android` on Linux and `~/Library/Caches/mise-android` on macOS.
Google's launcher can maintain additional runtime files in the Android user directory.

There are no shared SDK links, imports from existing SDKs, or global ownership
records. mise removes installations and cleans up failed installs:

```sh
mise uninstall android:sdk@36
mise prune --dry-run
```

mise's custom backend protocol does not record SDK archive digests in `mise.lock`.
The repository entries do not provide release timestamps, so mise cannot check
minimum release age for them. Android Studio, AVD configuration, running emulators,
and application dependencies are outside this backend's scope.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, local setup, and checks.
CI is configured for Linux and macOS; local Linux checks do not establish macOS support.

## License

[MIT](LICENSE). Downloaded Android components retain their upstream licenses.
