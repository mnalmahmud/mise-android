# mise-android

Install Android SDKs and tools with [mise](https://mise.jdx.dev/).

## Setup

Requires mise 2026.10.19 or newer and Linux or macOS on x64 or ARM64.
The plugin runs using Lua included with mise. Downloads use `curl`, with
`sha256sum` on Linux or `shasum` on macOS to check the downloaded Android command.

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

Run `mise install` to install SDK platform 36.

## Choose the SDK tools

Add the tools your project needs under `packages`:

```toml
"android:sdk" = { version = "36", packages = { platform-tools = "latest", build-tools = "36.0.0", ndk = "latest" } }
```

The platform is included by default. `platform-tools` adds `adb` and `fastboot`;
`ndk` adds the tools for C and C++ builds. Use a specific version or `latest` for
each package.

After changing `packages` or `channel`, or to refresh packages set to `latest`, run:

```sh
mise install --force android:sdk
mise exec -- adb version
```

`latest` is chosen at installation time.

mise sets `ANDROID_HOME` to this SDK's folder and adds its commands to your command
search path. If an NDK is included, it also sets `ANDROID_NDK_HOME` to the highest
installed NDK version. Let mise supply these values in your project.

Choose one SDK per project. Give it a name when projects need different tools for
the same platform:

```toml
"android:sdk/app" = { version = "36", packages = { ndk = "latest" } }
```

Each name gets a separate installation. Use the full name when reinstalling:
`mise install --force android:sdk/app`.

## Install individual tools

For example, to install an NDK:

```toml
"android:ndk" = "30.0.16248370"
```

Individual tools get their own folders and command paths. An NDK also sets
`ANDROID_NDK_HOME`. Use `android:sdk` for tools that need a complete SDK folder
and `ANDROID_HOME`.

| Tool name | Version selects |
| --- | --- |
| `android:sdk`, `android:sdk/NAME` | SDK platform number, such as `36` |
| `android:platform-tools`, `android:emulator` | Tool version |
| `android:ndk`, `android:build-tools`, `android:cmdline-tools`, `android:cmake` | Tool version |
| `android:platforms/android-36` | Release of that platform package |
| `android:system-images/android-36/google_apis/x86_64` | Release of that emulator image |

Find versions available for your machine:

```sh
mise ls-remote android:ndk
```

For a preview release, set `channel = "beta"` or `channel = "canary"` and use its
full version from the list.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `packages` | Empty | Additional tools and versions for `android:sdk` |
| `channel` | `"stable"` | `stable`, `beta`, or `canary` releases |
| `timeout` | `1800` | Installer time limit in seconds, from 1 to 86400 |
| `repository_url` | Google's package list | Read package information from an HTTPS address or absolute local `file://` address |

`repository_url` controls the package list. Google's Android command controls
package download locations.

## Installation and removal

The plugin uses Google's `android` command from your command search path, or
downloads a copy into mise's cache and checks Google's published SHA-256 checksum.
Google's command handles SDK downloads and licenses. The plugin checks installed
versions before saving the installation record.

Each installation keeps its own SDK folder. Switching SDKs reads the saved record
and updates the paths for your project. Remove an SDK with:

```sh
mise uninstall android:sdk@36
```

`mise cache clear android` clears saved version lists and downloaded copies of the
Android command. Google's command may also save files in your Android user folder.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout and checks.

## License

[MIT](LICENSE). Android tools retain their own licenses.
