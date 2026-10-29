# mise-android

Install Android SDK packages with [mise](https://mise.jdx.dev/).

## Setup

Requires mise 2026.10.19 or newer and Linux or macOS on x64 or ARM64.
The plugin runs using Lua included with mise. Downloads use `curl`, with
`sha1sum`, `sha256sum`, or `sha512sum` on Linux and `shasum` on macOS for checksums.
Extraction uses `unzip`, preserving executable permissions and NDK symbolic links.

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
`platform-tools` provides `adb` and `fastboot`. The plugin also installs the
dependencies required by Google's package metadata.

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

mise's `--force` removes the selected package before reinstalling it.

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

The selected NDK sets `ANDROID_NDK_HOME`. Google's native Linux tool packages
require x64. Platform packages can also be managed on Linux ARM64. The macOS NDK
supports x64 and ARM64.

List available versions:

```sh
mise ls-remote android:ndk
```

For preview versions, set `channel = "beta"` or `channel = "canary"` and use the
full version shown in the list.

## System images

`"android:system-image" = "36"` selects the `google_apis` image for Android 36 and
your machine's CPU. `google_apis` includes Google Play services. The emulator is
installed when the image requires it.

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
Images already installed in the shared SDK also constrain the emulator version.

Create a virtual device configuration with Android's tools after installing the
image. To change `variant`, `arch`, or `channel`, reinstall the tool with
`mise install --force android:system-image`.

## Removal

```sh
mise uninstall android:sdk@36
mise uninstall android:ndk@30.0.16248370
```

Removal deletes the selected package from the SDK. Other packages stay in the
shared folder. Removing an old mise entry for an emulator or
platform-tools version preserves a different version currently installed there.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `channel` | `"stable"` | `stable`, `beta`, or `canary` releases |
| `variant` | `"google_apis"` | Image variant for `android:system-image` |
| `arch` | Host CPU | Image architecture for `android:system-image` |
| `timeout` | `1800` | Time limit for each download, extraction, or waiting for another installation, from 1 to 86400 seconds |
| `repository_url` | Google's package list | Package metadata from HTTPS or an absolute local `file://` address |

The plugin downloads package archives directly from the URLs in Google's XML
lists and verifies their published checksums before extraction. Packages are
prepared in temporary folders before replacing installed files. A failed
replacement restores the previous package.

Installing a package accepts its included Android SDK license. The license text
is kept in `package.xml`, with acceptance records under the SDK's `licenses/`
folder. These files use Android's SDK formats.

`repository_url` supplies package URLs, checksums, dependencies, and licenses.
The default uses Google's HTTPS package lists. Local `file://` package lists and
archives can be used for offline installations.

`mise cache clear` clears mise's cache, including downloaded SDK archives.
The installed SDK stays in mise's data folder.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout and checks.

## License

[MIT](LICENSE). Android tools retain their own licenses.
