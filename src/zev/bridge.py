"""Execute JavaScript inside Zotero via the zev-bridge plugin's HTTP endpoint.

The plugin exposes a simple HTTP server on localhost. POST /execute with
{"code": "..."} to evaluate JS in Zotero's privileged context.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 24119
DEFAULT_TIMEOUT = 15  # seconds


class BridgeError(Exception):
    """Any failure communicating with the zev-bridge plugin."""


def execute_js(
    code: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Send JavaScript code to Zotero for evaluation via the bridge plugin.

    Returns the parsed result dict on success.
    Raises BridgeError on connection, HTTP, or evaluation failures.
    """
    url = f"http://{host}:{port}/execute"
    payload = json.dumps({"code": code}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "X-Zev-Client": "1"},
        method="POST",
    )

    uncertain = "JavaScript may still be running or have completed. Verify the affected state before retrying."
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            with e:
                rejection = json.loads(e.read(4096).decode("utf-8"))
            if isinstance(rejection, dict) and isinstance(rejection.get("error"), str):
                detail = ": " + rejection["error"]
        except (ValueError, OSError):
            pass
        raise BridgeError(f"Bridge request rejected: HTTP {e.code}{detail}") from e
    except TimeoutError as e:
        raise BridgeError(f"Bridge request timed out. {uncertain}") from e
    except urllib.error.URLError as e:
        if "Connection refused" in str(e):
            raise BridgeError(
                f"Cannot connect to zev-bridge at {host}:{port}. Is Zotero running with the Zev Bridge plugin?"
            ) from e
        raise BridgeError(f"Bridge request failed: {e}. {uncertain}") from e
    except Exception as e:
        raise BridgeError(f"Bridge request failed: {e}. {uncertain}") from e

    if not body.get("ok"):
        raise BridgeError(f"JS evaluation error: {body.get('error', 'unknown')}")

    return body
