#!/usr/bin/env python3
"""Verify that a built zev wheel contains the bundled Zotero bridge XPI."""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

WHEEL_XPI_PATH = "zev/assets/zev-bridge.xpi"
SOURCE_XPI_PATH = Path("zotero-plugin/dist/zev-bridge.xpi")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Path to a built zev wheel.")
    args = parser.parse_args()

    if not SOURCE_XPI_PATH.is_file():
        raise SystemExit(f"Missing source XPI: {SOURCE_XPI_PATH}")

    with zipfile.ZipFile(args.wheel) as wheel:
        try:
            xpi_bytes = wheel.read(WHEEL_XPI_PATH)
        except KeyError as exc:
            raise SystemExit(f"Wheel is missing {WHEEL_XPI_PATH}") from exc

    if xpi_bytes != SOURCE_XPI_PATH.read_bytes():
        raise SystemExit("Wheel XPI does not match zotero-plugin/dist/zev-bridge.xpi")

    with zipfile.ZipFile(io.BytesIO(xpi_bytes)) as xpi:
        names = set(xpi.namelist())
        missing = {"manifest.json", "bootstrap.js", "LICENSE"} - names
        if missing:
            raise SystemExit(f"Bundled XPI is missing: {', '.join(sorted(missing))}")
        if xpi.read("LICENSE") != Path("LICENSE").read_bytes():
            raise SystemExit("Bundled XPI license does not match the repository LICENSE")

    print(f"Verified bundled XPI in {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
