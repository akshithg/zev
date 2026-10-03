import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from zev import cli
from zev.bridge import BridgeError


class CliMainTests(unittest.TestCase):
    def test_version_prints_package_version(self):
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "package_version", return_value="1.2.3"),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "zev 1.2.3\n")

    def test_short_version_prints_package_version(self):
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "package_version", return_value="1.2.3"),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["-V"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "zev 1.2.3\n")

    def test_no_args_prints_help_to_stderr_and_fails(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main([])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("usage: zev", stderr.getvalue())

    def test_download_only_prints_xpi_without_contacting_zotero(self):
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "run_doctor") as doctor,
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["setup", "--download-only"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "/tmp/zev-bridge.xpi\n")
        doctor.assert_not_called()

    def test_setup_guides_installation_through_plugins_window(self):
        result = cli.setup.DoctorResult(
            checks=(cli.setup.CheckResult("zev-bridge", False, "not running"),),
            package_version="1.2.3",
            bundled_bridge_version="1.2.3",
            installed_bridge_version=None,
        )
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "run_doctor", return_value=result),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["setup"])
        self.assertEqual(exit_code, 1)
        self.assertIn("/tmp/zev-bridge.xpi", stdout.getvalue())
        self.assertIn("Open Zotero Tools -> Plugins", stdout.getvalue())
        self.assertIn("Restart Zotero", stdout.getvalue())

    def test_setup_check_is_non_mutating(self):
        result = cli.setup.DoctorResult(
            checks=(cli.setup.CheckResult("zev-bridge", True, "ok, version 1.2.3"),),
            package_version="1.2.3",
            bundled_bridge_version="1.2.3",
            installed_bridge_version="1.2.3",
        )
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi") as resolve_xpi,
            patch.object(cli.setup, "run_doctor", return_value=result),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["setup", "--check"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: ready", stdout.getvalue())
        resolve_xpi.assert_not_called()


class EvalCommandTests(unittest.TestCase):
    def test_reads_file_and_unwraps_json_stringify_result(self):
        stdout = io.StringIO()
        with (
            patch.object(cli, "execute_js", return_value={"ok": True, "result": '{"n": 1}'}) as run,
            redirect_stdout(stdout),
        ):
            with patch("pathlib.Path.read_text", return_value="return JSON.stringify({n:1});"):
                exit_code = cli.main(["eval", "some.js"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"n": 1})
        self.assertEqual(run.call_args.args[0], "return JSON.stringify({n:1});")

    def test_non_json_result_passes_through_unparsed(self):
        stdout = io.StringIO()
        with (
            patch.object(cli, "execute_js", return_value={"ok": True, "result": "plain text"}),
            patch("pathlib.Path.read_text", return_value="return 'plain text';"),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["eval", "some.js"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "plain text")

    def test_raw_shows_the_bridge_envelope(self):
        stdout = io.StringIO()
        with (
            patch.object(cli, "execute_js", return_value={"ok": True, "result": '{"n": 1}'}),
            patch("pathlib.Path.read_text", return_value="x"),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["eval", "some.js", "--raw"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"ok": True, "result": '{"n": 1}'})

    def test_bridge_failure_reports_to_stderr_and_exits_nonzero(self):
        stderr = io.StringIO()
        with (
            patch.object(cli, "execute_js", side_effect=BridgeError("Zotero is not running")),
            patch("pathlib.Path.read_text", return_value="x"),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(["eval", "some.js"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Zotero is not running", stderr.getvalue())

    def test_empty_input_is_rejected(self):
        stderr = io.StringIO()
        with patch("pathlib.Path.read_text", return_value="   \n"), redirect_stderr(stderr):
            exit_code = cli.main(["eval", "some.js"])

        self.assertEqual(exit_code, 2)
        self.assertIn("no JavaScript", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
