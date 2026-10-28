# Changelog

## 0.1.0

Initial standalone backend for mise:

- Install an Android platform alone or add explicitly selected SDK components.
- Keep complete SDKs and individual packages in separate mise installations.
- Discover package versions from repository XML, filtered by host and channel.
- Reuse Android CLI from `PATH` or download and checksum-verify a private copy.
- Resolve packages before installation, verify the final SDK, and write an atomic manifest.
- Export the selected installation's environment without writing files during activation.
- Bound metadata reads, cache metadata, and terminate timed-out installer process groups.
- Exercise offline behavior and real mise integration, with Linux/macOS CI configured.
