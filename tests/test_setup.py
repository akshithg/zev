import io
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

    def test_status_request_rejects_non_json_responses(self):
        for body in (b"pong", b"", b"\xff"):
            with self.subTest(body=body):
                with patch("zev.setup.urllib.request.urlopen", return_value=io.BytesIO(body)):
                    ok, detail = setup.http_json(setup.BRIDGE_ENDPOINT)
                self.assertFalse(ok)
                self.assertTrue(detail)

    def test_compare_versions(self):
        self.assertLess(setup.compare_versions("0.2.1", "0.2.2"), 0)
        self.assertEqual(setup.compare_versions("0.2.2", "0.2.2"), 0)
        self.assertGreater(setup.compare_versions("0.3.0", "0.2.9"), 0)

    def test_doctor_needs_only_the_bridge_endpoint(self):
        def fake_http_json(url, timeout=1.0):
            if url == setup.BRIDGE_ENDPOINT:
                return True, {"version": "0.2.2"}
            raise AssertionError(url)

        with (
            patch.object(setup, "package_version", return_value="0.2.2"),
            patch.object(setup, "bundled_xpi_path", return_value=Path(__file__)),
            patch.object(setup, "bridge_version_from_xpi", return_value="0.2.2"),
            patch.object(setup, "http_json", side_effect=fake_http_json),
        ):
            result = setup.run_doctor()

        self.assertTrue(result.ready)
        self.assertEqual(result.installed_bridge_version, "0.2.2")


class StaleBridgeTests(unittest.TestCase):
    def test_running_bridge_older_than_bundled_build_is_flagged(self):
        with (
            patch.object(setup, "bundled_xpi_path", return_value=Path("/tmp/zev-bridge.xpi")),
            patch.object(setup, "bridge_version_from_xpi", return_value="0.2.0"),
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
            patch.object(setup, "http_json", return_value=(True, {"status": "ok", "version": "0.1.0"})),
        ):
            result = setup.run_doctor()

        bridge = next(c for c in result.checks if c.name == "zev-bridge")
        self.assertTrue(bridge.ok)
        self.assertTrue(result.ready)


if __name__ == "__main__":
    unittest.main()
