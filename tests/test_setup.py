import configparser
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from zev import setup


class SetupHelperTests(unittest.TestCase):
    def test_bundled_xpi_path_is_present_and_readable(self):
        path = setup.bundled_xpi_path()

        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertEqual(setup.bridge_version_from_xpi(path), setup.package_version())

    def test_bridge_version_from_xpi_reads_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xpi_path = Path(temp_dir) / "bridge.xpi"
            with zipfile.ZipFile(xpi_path, "w") as archive:
                archive.writestr("manifest.json", json.dumps({"version": "9.8.7"}))

            self.assertEqual(setup.bridge_version_from_xpi(xpi_path), "9.8.7")

    def test_compare_versions(self):
        self.assertLess(setup.compare_versions("0.2.1", "0.2.2"), 0)
        self.assertEqual(setup.compare_versions("0.2.2", "0.2.2"), 0)
        self.assertGreater(setup.compare_versions("0.3.0", "0.2.9"), 0)

    def test_discovers_default_relative_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parser = configparser.ConfigParser()
            parser["Profile0"] = {
                "Name": "default",
                "IsRelative": "1",
                "Path": "Profiles/abc.default",
                "Default": "1",
            }
            with (root / "profiles.ini").open("w") as handle:
                parser.write(handle)

            self.assertEqual(
                setup.discover_default_profile(root),
                root / "Profiles/abc.default",
            )

    def test_install_profile_refuses_while_zotero_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xpi_path = Path(temp_dir) / "zev-bridge.xpi"
            xpi_path.write_bytes(b"xpi")

            with patch.object(setup, "is_zotero_running", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "Zotero is running"):
                    setup.install_bridge_into_profile(xpi_path, Path(temp_dir) / "profile")

    def test_install_profile_backs_up_existing_xpi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xpi_path = root / "zev-bridge.xpi"
            xpi_path.write_bytes(b"new")
            profile = root / "profile"
            extensions = profile / "extensions"
            extensions.mkdir(parents=True)
            destination = extensions / f"{setup.BRIDGE_ADDON_ID}.xpi"
            destination.write_bytes(b"old")

            with patch.object(setup, "is_zotero_running", return_value=False):
                installed = setup.install_bridge_into_profile(xpi_path, profile)

            self.assertEqual(installed, destination)
            self.assertEqual(destination.read_bytes(), b"new")
            backups = list(extensions.glob(f"{setup.BRIDGE_ADDON_ID}.xpi.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old")

    def test_run_doctor_reports_mocked_http_status(self):
        def fake_http_json(url, timeout=1.0):
            if url == setup.LOCAL_API_ENDPOINT:
                return True, "pong"
            if url == setup.BRIDGE_ENDPOINT:
                return True, {"version": "0.2.2"}
            raise AssertionError(url)

        with (
            patch.object(setup, "package_version", return_value="0.2.2"),
            patch.object(setup, "bundled_xpi_path", return_value=Path(__file__)),
            patch.object(setup, "bridge_version_from_xpi", return_value="0.2.2"),
            patch.object(setup, "discover_default_profile", return_value=Path("/tmp/zotero-profile")),
            patch.object(setup, "http_json", side_effect=fake_http_json),
        ):
            result = setup.run_doctor()

        self.assertTrue(result.ready)
        self.assertEqual(result.installed_bridge_version, "0.2.2")


if __name__ == "__main__":
    unittest.main()


class StaleBridgeTests(unittest.TestCase):
    def test_running_bridge_older_than_bundled_build_is_flagged(self):
        with (
            patch.object(setup, "bundled_xpi_path", return_value=Path("/tmp/zev-bridge.xpi")),
            patch.object(setup, "bridge_version_from_xpi", return_value="0.2.0"),
            patch.object(setup, "discover_default_profile", return_value=Path("/tmp/profile")),
            patch.object(setup, "http_json", return_value=(True, {"status": "ok", "version": "0.1.0"})),
        ):
            result = setup.run_doctor()

        bridge = next(c for c in result.checks if c.name == "zev-bridge")
        self.assertFalse(bridge.ok)
        self.assertIn("bundled build is 0.2.0", bridge.detail)
        self.assertFalse(result.ready)

    def test_matching_versions_are_clean(self):
        with (
            patch.object(setup, "bundled_xpi_path", return_value=Path("/tmp/zev-bridge.xpi")),
            patch.object(setup, "bridge_version_from_xpi", return_value="0.1.0"),
            patch.object(setup, "discover_default_profile", return_value=Path("/tmp/profile")),
            patch.object(setup, "http_json", return_value=(True, {"status": "ok", "version": "0.1.0"})),
        ):
            result = setup.run_doctor()

        bridge = next(c for c in result.checks if c.name == "zev-bridge")
        self.assertTrue(bridge.ok)
        self.assertTrue(result.ready)


class AddonRegistrationTests(unittest.TestCase):
    def test_detects_registered_and_unregistered_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            (profile / "extensions.json").write_text(
                json.dumps({"addons": [{"id": "zev-bridge@zev.dev", "version": "0.1.0"}]})
            )
            self.assertTrue(setup.is_addon_registered(profile))
            self.assertFalse(setup.is_addon_registered(profile, "other@example.com"))

    def test_missing_extensions_json_is_not_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(setup.is_addon_registered(Path(tmp)))
