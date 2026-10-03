import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class PluginBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        for name in (
            "LICENSE",
            "pyproject.toml",
            "scripts/build_zotero_plugin.py",
            "zotero-plugin/manifest.json",
            "zotero-plugin/bootstrap.js",
        ):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / name, destination)

    def build(self):
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts/build_zotero_plugin.py"), "--check-version-sync"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.root / "zotero-plugin/dist/zev-bridge.xpi"

    def test_license_is_preserved_in_standalone_and_bundled_xpi(self):
        standalone = self.build()
        bundled = self.root / "src/zev/assets/zev-bridge.xpi"
        self.assertEqual(standalone.read_bytes(), bundled.read_bytes())
        for path in (standalone, bundled):
            with self.subTest(path=path), zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read("LICENSE"), (REPO_ROOT / "LICENSE").read_bytes())

    def test_rebuilding_preserves_artifacts_and_update_hash(self):
        xpi = self.build()
        feed = self.root / "zotero-plugin/dist/zev-bridge-updates.json"
        original_xpi = xpi.read_bytes()
        original_feed = feed.read_bytes()
        self.build()
        self.assertEqual(xpi.read_bytes(), original_xpi)
        self.assertEqual(feed.read_bytes(), original_feed)
        with zipfile.ZipFile(xpi) as archive:
            version = json.loads(archive.read("manifest.json"))["version"]
        updates = json.loads(feed.read_text())["addons"]["zev-bridge@zev.dev"]["updates"]
        self.assertEqual(updates[0]["version"], version)
        self.assertEqual(updates[0]["update_hash"], "sha256:" + hashlib.sha256(original_xpi).hexdigest())

    def test_wheel_verifier_rejects_missing_or_changed_license(self):
        source_xpi = self.root / "zotero-plugin/dist/zev-bridge.xpi"
        source_xpi.parent.mkdir(parents=True)
        wheel_path = self.root / "zev.whl"
        for license_bytes in (None, b"incorrect license"):
            with self.subTest(license_bytes=license_bytes):
                with zipfile.ZipFile(source_xpi, "w") as xpi:
                    xpi.writestr("manifest.json", "{}")
                    xpi.writestr("bootstrap.js", "")
                    if license_bytes is not None:
                        xpi.writestr("LICENSE", license_bytes)
                with zipfile.ZipFile(wheel_path, "w") as wheel:
                    wheel.writestr("zev/assets/zev-bridge.xpi", source_xpi.read_bytes())
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts/verify_wheel_xpi.py"), str(wheel_path)],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LICENSE" if license_bytes is None else "license", result.stderr)


if __name__ == "__main__":
    unittest.main()
