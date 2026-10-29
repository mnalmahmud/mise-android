# Changelog

## 0.1.0

- Install Android platforms and tools into one shared SDK folder.
- Resolve required dependencies from Google's package metadata.
- Check project version conflicts before starting the installer.
- Select system images by API level, with optional variant and CPU architecture.
- Set Android paths when activating tools through mise.
- Run using Lua included with mise.
- Download and verify package archives directly, preserving permissions and symbolic links.
- Keep Android package metadata and license records in the SDK.
- Restore previous packages after failed replacements and serialize SDK updates.
