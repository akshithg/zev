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

    def test_setup_check_is_non_mutating(self):
        result = cli.setup.DoctorResult(
            checks=(
                cli.setup.CheckResult("Zotero local API", True, "ok"),
                cli.setup.CheckResult("zev-bridge", True, "ok, version 1.2.3"),
            ),
            package_version="1.2.3",
            bundled_bridge_version="1.2.3",
            installed_bridge_version="1.2.3",
        )
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi"),
            patch.object(cli.setup, "run_doctor", return_value=result),
            patch.object(cli.setup, "install_bridge_into_profile") as install_mock,
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["setup", "--check"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: ready", stdout.getvalue())
        install_mock.assert_not_called()


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


class SetupRestartTests(unittest.TestCase):
    def _doctor(self):
        return cli.setup.DoctorResult(
            checks=(cli.setup.CheckResult("zev-bridge", True, "ok"),),
            package_version="0.1.0",
            bundled_bridge_version="0.1.0",
            installed_bridge_version="0.1.0",
        )

    def test_restart_quits_installs_launches_and_waits(self):
        stdout = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "discover_default_profile", return_value=None),
            patch.object(cli.setup, "run_doctor", return_value=self._doctor()),
            patch.object(cli.setup, "quit_zotero", return_value=True) as quit_mock,
            patch.object(cli.setup, "install_bridge_into_profile", return_value="/p/zev-bridge@zev.dev.xpi") as inst,
            patch.object(cli.setup, "launch_zotero") as launch,
            patch.object(cli.setup, "wait_for_bridge", return_value="0.1.0"),
            redirect_stdout(stdout),
        ):
            exit_code = cli.main(["setup", "--install-profile", "--restart"])

        self.assertEqual(exit_code, 0)
        quit_mock.assert_called_once()
        inst.assert_called_once()
        launch.assert_called_once()
        self.assertIn("Bridge is up, version 0.1.0", stdout.getvalue())

    def test_nothing_is_installed_when_zotero_refuses_to_quit(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "discover_default_profile", return_value=None),
            patch.object(cli.setup, "run_doctor", return_value=self._doctor()),
            patch.object(cli.setup, "quit_zotero", return_value=False),
            patch.object(cli.setup, "install_bridge_into_profile") as inst,
            patch.object(cli.setup, "launch_zotero") as launch,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(["setup", "--install-profile", "--restart"])

        self.assertEqual(exit_code, 1)
        inst.assert_not_called()
        launch.assert_not_called()
        self.assertIn("did not quit", stderr.getvalue())

    def test_bridge_that_never_comes_up_is_reported(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "discover_default_profile", return_value=None),
            patch.object(cli.setup, "run_doctor", return_value=self._doctor()),
            patch.object(cli.setup, "quit_zotero", return_value=True),
            patch.object(cli.setup, "install_bridge_into_profile", return_value="/p/x.xpi"),
            patch.object(cli.setup, "launch_zotero"),
            patch.object(cli.setup, "wait_for_bridge", return_value=None),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(["setup", "--install-profile", "--restart"])

        self.assertEqual(exit_code, 1)
        self.assertIn("did not come up", stderr.getvalue())

    def test_unregistered_addon_is_refused_with_ui_instructions(self):
        stderr = io.StringIO()
        with (
            patch.object(cli.setup, "resolve_setup_xpi", return_value="/tmp/zev-bridge.xpi"),
            patch.object(cli.setup, "run_doctor", return_value=self._doctor()),
            patch.object(cli.setup, "discover_default_profile", return_value="/p"),
            patch.object(cli.setup, "is_addon_registered", return_value=False),
            patch.object(cli.setup, "quit_zotero") as quit_mock,
            patch.object(cli.setup, "install_bridge_into_profile") as inst,
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(["setup", "--install-profile", "--restart"])

        # Nothing may be touched: quitting Zotero to perform an install that
        # cannot work is worse than refusing up front.
        self.assertEqual(exit_code, 1)
        quit_mock.assert_not_called()
        inst.assert_not_called()
        self.assertIn("Install Add-on From File", stderr.getvalue())
