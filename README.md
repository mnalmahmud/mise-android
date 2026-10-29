# mise-android

Install and switch Android SDKs with [mise](https://mise.jdx.dev/).

Each SDK gets its own folder. You can also install tools such as `adb` or the NDK
on their own.

## What you need

- mise 2026.10.19 or newer.
- Linux or macOS, on x64 or ARM64.

Also needs `bash`, `curl`, and `sha256sum` on Linux or `shasum` on macOS. These are
common system tools. You do not need Python or a separate Lua installation.

If Google's `android` command is already installed, this plugin uses it. Otherwise,
it downloads a copy and checks that the file matches what Google published.
Downloads are available for both x64 and ARM64 on Linux and macOS. Windows is not
supported by this plugin yet.

## Install

```sh
mise plugins install vfox-backend:android https://github.com/mnalmahmud/mise-android
```

Add this to your project's `mise.toml`:

```toml
[settings]
experimental = true

[plugins]
"vfox-backend:android" = "https://github.com/mnalmahmud/mise-android"

[tools]
"android:sdk" = "36"
```

Then run:

```sh
mise install
```

This installs only SDK platform 36.

## Add tools to an SDK

Replace the `android:sdk` line with the tools you need:

```toml
"android:sdk" = { version = "36", packages = { platform-tools = "latest", ndk = "latest" } }
```

`platform-tools` includes `adb`. The NDK provides tools for C and C++ code. You can
also add packages such as `build-tools = "36.0.0"`.

Use a version number to keep a particular version, or `latest` to choose the newest
available version when you install. Nothing else is added unless you ask for it.

After changing the package list, run:

```sh
mise install --force android:sdk
mise exec -- adb version
```

Run the same install command to update packages set to `latest`. Upgrading the SDK's
platform number does not update packages inside an existing installation.

## Use the SDK in a project

mise sets `ANDROID_HOME` to the selected SDK's folder and makes its commands
available. If the SDK includes an NDK, mise also sets `ANDROID_NDK_HOME`. With
multiple NDK versions, it chooses the highest version.

Let mise set these values instead of adding them to your shell settings or the
`[env]` section of `mise.toml`. Choose one complete SDK per project.

If two projects need different tools for the same SDK platform, give each SDK
a name:

```toml
"android:sdk/my-project" = { version = "36", packages = { ndk = "latest" } }
```

Another project can choose a different name and package list. To reinstall a named
SDK, use its full name:

```sh
mise install --force android:sdk/my-project
```

## Install one tool

For example, to install an NDK without a complete SDK:

```toml
"android:ndk" = "30.0.16248370"
```

Each tool stays in its own folder. Separate tools are not combined into an SDK and
do not set `ANDROID_HOME`. An NDK still sets `ANDROID_NDK_HOME`.

| Name in `mise.toml` | What the version number means |
| --- | --- |
| `android:sdk` or `android:sdk/NAME` | SDK platform number, such as `36` |
| `android:platform-tools`, `android:emulator` | Version of the tool |
| `android:ndk`, `android:build-tools`, `android:cmdline-tools`, `android:cmake` | Version of the tool |
| `android:platforms/android-36` | Version of that platform package, not its platform number |
| `android:system-images/android-36/google_apis/x86_64` | Version of that emulator image |

List available versions with:

```sh
mise ls-remote android:ndk
```

The list comes from Google and includes packages for your machine.

## Other settings

| Setting | Default | What it does |
| --- | --- | --- |
| `packages` | Empty | Adds the listed tools to `android:sdk` |
| `channel` | `"stable"` | Choose `stable`, `beta`, or `canary` releases |
| `timeout` | `1800` | Stop an installation after this many seconds; allowed range is 1–86400 |
| `repository_url` | Google's package list | Read the package list from another HTTPS address or a local `file://` address |

For example, to use preview NDK releases:

```toml
"android:ndk" = { version = "latest", channel = "canary" }
```

You may also need to allow previews in mise or request a specific preview version.
Reinstall after changing `channel`. Changing `repository_url` changes the package
list, not where Google's `android` command downloads packages.

## Remove an installation

```sh
mise uninstall android:sdk@36
```

mise removes that installation's folder. Your other SDKs are left alone. Switching
between installed versions does not move or rewrite SDK files.

## What this plugin handles

Google's `android` command downloads the SDK packages and handles their licenses.
This plugin checks the installed versions before marking an installation complete.
It does not accept licenses for you or check SDK download files itself.

Downloaded copies of the `android` command are saved in mise's cache folder and
checked before reuse. `mise cache clear android` removes them. mise also saves
version lists to avoid repeated downloads. Google's command may save additional
files in your Android user folder.

This plugin does not set up Android Studio, create virtual devices, or manage your
app's dependencies. mise's lock file does not save SDK download checksums, and
Google's package lists do not provide dates for mise's release-age check.

See [CONTRIBUTING.md](CONTRIBUTING.md) to work on the plugin.

## License

[MIT](LICENSE). Android tools keep their own licenses.
