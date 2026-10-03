# Releasing zev

Keep release artifacts on GitHub; do not publish this project to a package
registry. GitHub Releases contain:

- The Python wheel and source distribution
- The Zotero bridge plugin as `zev-bridge.xpi`

The release also includes `zev-bridge-updates.json`, which is the update feed referenced by the XPI manifest. Zotero uses that JSON file to discover future bridge updates and compatibility changes.

## Versioning

Keep the project version in `pyproject.toml` and the bridge version in `zotero-plugin/manifest.json` in sync. `make build` enforces this.

Bump the version whenever bridge code, bridge compatibility, or Python package behavior changes. The bridge version must always increase when the XPI changes, because Zotero will not treat a same-version XPI as an upgrade.

Use a tag that matches the version. The examples below assume a release version
of `0.2.2`; substitute the version being released.

## Build Artifacts

Build the plugin artifacts with:

```bash
make build
```

This writes:

- `zotero-plugin/dist/zev-bridge.xpi`
- `zotero-plugin/dist/zev-bridge-updates.json`

The update manifest includes:

- the bridge version
- a versioned GitHub release URL for `zev-bridge.xpi`
- the XPI sha256 digest
- Zotero compatibility bounds from `zotero-plugin/manifest.json`

Rebuild the bundled XPI with `make build` and include it in the release prep
commit. After committing, verify the artifacts and run the tests:

```bash
make verify-build
make test
```

CI also runs `make build` and fails if the committed bundled XPI is stale.

## GitHub Release

Create and push a tag that matches the version in `pyproject.toml` and `zotero-plugin/manifest.json`:

```bash
git tag v0.2.2
git push origin v0.2.2
```

The release workflow:

1. Builds the deterministic Zotero bridge artifacts.
2. Verifies the tag matches the bridge version.
3. Runs unit tests.
4. Builds the Python wheel and sdist.
5. Uploads the Python distributions, `zev-bridge.xpi`, and
   `zev-bridge-updates.json` to the GitHub release.

To test the tag guard locally before pushing a release tag:

```bash
make release-build RELEASE_TAG=v0.2.2
```

After the workflow completes, verify the release assets:

```bash
curl -L https://github.com/akshithg/zev/releases/latest/download/zev-bridge-updates.json
curl -L https://github.com/akshithg/zev/releases/latest/download/zev-bridge.xpi -o /tmp/zev-bridge.xpi
shasum -a 256 /tmp/zev-bridge.xpi
```

The hash should match the `update_hash` field in the update manifest.

## Zotero Compatibility Updates

Zotero supports updating compatibility through the update manifest. If a future Zotero version only needs a compatibility bump, update `strict_max_version`, bump the bridge version, rebuild, and release the XPI/update manifest pair.

Existing users with an old bridge whose `update_url` points to a missing feed may need one manual reinstall from the latest GitHub release. Once they install a bridge with the current update URL, future updates can flow through Zotero's plugin update mechanism.
