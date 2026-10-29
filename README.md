# mise-android

Install Android SDK packages with [mise](https://mise.jdx.dev/).

## Setup

Requires mise 2026.10.19 or newer and Linux or macOS on x64 or ARM64.
The plugin runs using Lua included with mise. Downloads use `curl`, with
`sha256sum` on Linux or `shasum` on macOS to check Google's Android command.

```sh
mise plugins install vfox-backend:android https://github.com/mnalmahmud/mise-android
```

Add packages to your project's `mise.toml`:

```toml
[settings]
experimental = true
minimum_release_age_excludes = ["android:*"]

[plugins]
"vfox-backend:android" = "https://github.com/mnalmahmud/mise-android"

[tools]
"android:sdk" = "36"
"android:platform-tools" = "latest"
```

Run `mise install`. `android:sdk` installs the platform for the selected API level;
`platform-tools` provides `adb` and `fastboot`. Google installs each package's
required dependencies too.

Google's package lists omit release dates. The Android exclusion skips its
release-age check while keeping the checks for other tools.

## One SDK folder

All packages use `$MISE_DATA_DIR/android/sdk`, usually
`~/.local/share/mise/android/sdk`. mise sets `ANDROID_HOME` to that folder.

Platforms, NDKs, build tools, and system images can share this SDK:

```text
sdk/
├── platforms/android-35/
├── platforms/android-36/
├── ndk/30.0.16248370/
├── build-tools/36.0.0/
├── emulator/
├── platform-tools/
└── system-images/android-36/google_apis/x86_64/
```

The emulator and platform tools each have one installed version. Installing a
different version changes it for every project using this SDK. Activation checks
the installed package against the project's saved request. To apply a different
version, run, for example:

```sh
mise install --force android:emulator
```

Switching projects reads package information and sets paths. Installations and
removals update the shared SDK.

## Choose packages

Each package has its own tool entry:

```toml
[tools]
"android:sdk" = "36"
"android:platform-tools" = "latest"
"android:build-tools" = "36.0.0"
"android:ndk" = "30.0.16248370"
"android:emulator" = "latest"
"android:system-image" = "36"
```

| Tool | Version selects |
| --- | --- |
| `android:sdk` | Android API level |
| `android:system-image` | Android API level; newest matching image revision |
| `android:platform-tools`, `android:emulator` | Tool version |
| `android:ndk`, `android:build-tools`, `android:cmdline-tools`, `android:cmake` | Tool version |

Use a specific version or `latest`. `latest` is resolved when installing. To
refresh an installed package, run `mise install --force android:TOOL`.

The selected NDK sets `ANDROID_NDK_HOME`. Google's Linux NDK builds require an x64
host; the macOS NDK supports x64 and ARM64.

List available versions:

```sh
mise ls-remote android:ndk
```

For preview versions, set `channel = "beta"` or `channel = "canary"` and use the
full version shown in the list.

## System images

`"android:system-image" = "36"` selects the `google_apis` image for Android 36 and
your machine's CPU. `google_apis` includes Google Play services. Google installs
the emulator when the image requires it.

To choose the image variant or CPU explicitly:

```toml
"android:system-image" = { version = "36", variant = "google_apis_playstore", arch = "x86_64" }
```

`google_apis_playstore` includes the Play Store. The default architecture is
`x86_64` on x64 hosts and `arm64-v8a` on ARM64 hosts. Available images depend on
the API level, variant, and architecture.

An explicit emulator version must meet the image's minimum requirement. The plugin
checks the project's package requests before starting the installer. An image can
upgrade an older emulator when the project leaves its version unspecified.

Create a virtual device configuration with Android's tools after installing the
image. To change `variant`, `arch`, or `channel`, reinstall the tool with
`mise install --force android:system-image`.

## Removal

```sh
mise uninstall android:sdk@36
mise uninstall android:ndk@30.0.16248370
```

Removal asks Google's command to remove the selected package from the SDK. Other
packages stay in the shared folder. Removing an old mise entry for an emulator or
platform-tools version preserves a different version currently installed there.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `channel` | `"stable"` | `stable`, `beta`, or `canary` releases |
| `variant` | `"google_apis"` | Image variant for `android:system-image` |
| `arch` | Host CPU | Image architecture for `android:system-image` |
| `timeout` | `1800` | Installer time limit in seconds, from 1 to 86400 |
| `repository_url` | Google's package list | Package metadata from HTTPS or an absolute local `file://` address |

The plugin uses Google's `android` command from your command search path, or
downloads a checksum-verified copy into mise's cache. Google handles package
archives and licenses. `repository_url` controls discovery and dependency checks;
Google's command controls package download locations.

`mise cache clear android` clears cached version lists and downloaded copies of
the Android command. The SDK stays in mise's data folder. Google's command may
also save files in your Android user folder.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout and checks.

## License

[MIT](LICENSE). Android tools retain their own licenses.
