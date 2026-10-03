import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from zev.bridge import BridgeError, execute_js


class BridgeClientTests(unittest.TestCase):
    def test_cli_supplies_protocol_header_and_json_body(self):
        response = io.BytesIO(b'{"ok": true, "result": "done"}')
        with patch("zev.bridge.urllib.request.urlopen", return_value=response) as send:
            self.assertEqual(execute_js('return "café";')["result"], "done")
        request = send.call_args.args[0]
        self.assertEqual(request.get_header("X-zev-client"), "1")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"code": 'return "café";'})
        self.assertEqual(send.call_count, 1)

    def test_connection_refusal_has_setup_guidance(self):
        with patch("zev.bridge.urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaisesRegex(BridgeError, "Is Zotero running"):
                execute_js("return 1;")

    def test_timeout_reports_uncertain_outcome_without_retry(self):
        for error in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            with self.subTest(error=error):
                with patch("zev.bridge.urllib.request.urlopen", side_effect=error) as send:
                    with self.assertRaisesRegex(BridgeError, "may still be running.*before retrying"):
                        execute_js("return 1;")
                    self.assertEqual(send.call_count, 1)

    def test_lost_connection_reports_uncertain_outcome(self):
        with patch("zev.bridge.urllib.request.urlopen", side_effect=urllib.error.URLError("connection reset")):
            with self.assertRaisesRegex(BridgeError, "may still be running"):
                execute_js("return 1;")

    def test_http_rejection_includes_server_explanation(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:24119/execute",
            413,
            "Content Too Large",
            None,
            io.BytesIO(b'{"error": "request body exceeds 1 MiB"}'),
        )
        with patch("zev.bridge.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(BridgeError, "HTTP 413: request body exceeds 1 MiB"):
                execute_js("return 1;")

    def test_http_rejection_with_non_json_body_is_reported(self):
        error = urllib.error.HTTPError("http://127.0.0.1:24119/execute", 403, "Forbidden", None, io.BytesIO(b"error"))
        with patch("zev.bridge.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(BridgeError, "HTTP 403"):
                execute_js("return 1;")

    def test_evaluation_failure_is_reported(self):
        response = io.BytesIO(b'{"ok": false, "error": "test failure"}')
        with patch("zev.bridge.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(BridgeError, "JS evaluation error: test failure"):
                execute_js("return 1;")
