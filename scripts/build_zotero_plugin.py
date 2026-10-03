#!/usr/bin/env python3
"""Build and validate the Zotero bridge release artifacts.

The bridge has two release artifacts:

* zev-bridge.xpi, the installable Zotero plugin archive
* zev-bridge-updates.json, the Zotero update manifest consumed by update_url

This script writes both artifacts deterministically so CI can rebuild them and
fail when a committed artifact is stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "zotero-plugin"
DIST_DIR = PLUGIN_DIR / "dist"
MANIFEST_PATH = PLUGIN_DIR / "manifest.json"
BOOTSTRAP_PATH = PLUGIN_DIR / "bootstrap.js"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
LICENSE_PATH = REPO_ROOT / "LICENSE"
BUNDLED_XPI_PATH = REPO_ROOT / "src/zev/assets/zev-bridge.xpi"

PLUGIN_ID = "zev-bridge@zev.dev"
XPI_NAME = "zev-bridge.xpi"
UPDATE_MANIFEST_NAME = "zev-bridge-updates.json"
DEFAULT_REPOSITORY = "akshithg/zev"
DEFAULT_UPDATE_URL = f"https://github.com/{DEFAULT_REPOSITORY}/releases/latest/download/{UPDATE_MANIFEST_NAME}"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
        help="GitHub repository in owner/name form used for release URLs.",
    )
    parser.add_argument(
        "--release-tag",
        default="",
        help="Release tag used in the update manifest. Defaults to v<manifest version>.",
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    bridge_version = str(manifest["version"])
    release_tag = args.release_tag or f"v{bridge_version}"

    project_version = _read_pyproject_version()
    if project_version != bridge_version:
        raise SystemExit(
            f"pyproject.toml version {project_version!r} does not match Zotero bridge version {bridge_version!r}"
        )

    if release_tag != f"v{bridge_version}":
        raise SystemExit(f"release tag {release_tag!r} does not match bridge version v{bridge_version}")

    _validate_manifest(manifest)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    xpi_path = DIST_DIR / XPI_NAME
    update_manifest_path = DIST_DIR / UPDATE_MANIFEST_NAME
    _write_xpi(xpi_path)
    BUNDLED_XPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(xpi_path, BUNDLED_XPI_PATH)
    digest = hashlib.sha256(xpi_path.read_bytes()).hexdigest()
    _write_update_manifest(
        update_manifest_path,
        manifest=manifest,
        repository=args.repository,
        release_tag=release_tag,
        digest=digest,
    )

    print(f"Built: {xpi_path}")
    print(f"Bundled: {BUNDLED_XPI_PATH}")
    print(f"Built: {update_manifest_path}")
    print(f"Bridge version: {bridge_version}")
    print(f"Release tag: {release_tag}")
    print(f"XPI sha256: {digest}")
    return 0


def _read_pyproject_version() -> str:
    text = PYPROJECT_PATH.read_text()
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise SystemExit("Could not find project version in pyproject.toml")
    return match.group(1)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("manifest_version") != 2:
        raise SystemExit("Zotero bridge manifest_version must be 2")
    if manifest.get("version") is None:
        raise SystemExit("Zotero bridge manifest must declare version")

    zotero = manifest.get("applications", {}).get("zotero", {})
    if zotero.get("id") != PLUGIN_ID:
        raise SystemExit(f"Zotero bridge id must be {PLUGIN_ID}")
    if zotero.get("update_url") != DEFAULT_UPDATE_URL:
        raise SystemExit(
            f"Zotero bridge update_url must point at the stable GitHub release asset: {DEFAULT_UPDATE_URL}"
        )
    if not zotero.get("strict_min_version") or not zotero.get("strict_max_version"):
        raise SystemExit("Zotero bridge manifest must declare strict compatibility bounds")


def _write_xpi(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for source in (MANIFEST_PATH, BOOTSTRAP_PATH, LICENSE_PATH):
            info = zipfile.ZipInfo(source.name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def _write_update_manifest(
    path: Path,
    *,
    manifest: dict[str, Any],
    repository: str,
    release_tag: str,
    digest: str,
) -> None:
    zotero = manifest["applications"]["zotero"]
    update_link = f"https://github.com/{repository}/releases/download/{release_tag}/{XPI_NAME}"
    payload = {
        "addons": {
            PLUGIN_ID: {
                "updates": [
                    {
                        "version": manifest["version"],
                        "update_link": update_link,
                        "update_hash": f"sha256:{digest}",
                        "applications": {
                            "zotero": {
                                "strict_min_version": zotero["strict_min_version"],
                                "strict_max_version": zotero["strict_max_version"],
                            }
                        },
                    }
                ]
            }
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
