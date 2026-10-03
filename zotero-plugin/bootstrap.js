/* Zev Bridge — bootstrap plugin for Zotero 7, 8, and 9.
 *
 * Exposes a minimal HTTP endpoint on localhost that accepts JavaScript code
 * via POST and evaluates it inside Zotero's privileged context. This lets
 * external tools (like the zev CLI) call Zotero.Attachments,
 * Zotero.Items, etc. without needing direct database access.
 *
 * Binds to loopback. Trusted local apps can execute privileged code;
 * request checks exclude ordinary browser callers, without authenticating apps.
 */

const DEFAULT_PORT = 24119;
const PREF_ENABLED = "extensions.zev-bridge.enabled";
const PREF_PORT = "extensions.zev-bridge.port";
const MAX_HEADER_BYTES = 16 * 1024;
const MAX_BODY_BYTES = 1024 * 1024;
const READ_TIMEOUT_MS = 5000;
const pendingReads = new Set();

let serverSocket = null;
let pluginVersion = "unknown";

function log(msg) {
  Zotero.debug("[zev-bridge] " + msg);
}

function getPort() {
  try {
    var p = Zotero.Prefs.get(PREF_PORT);
    return typeof p === "number" && p > 0 ? p : DEFAULT_PORT;
  } catch (_) {
    return DEFAULT_PORT;
  }
}

function isEnabled() {
  try {
    return Zotero.Prefs.get(PREF_ENABLED) !== false;
  } catch (_) {
    return true;
  }
}

function sendHTTP(output, status, body) {
  var statusText = {
    200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
    408: "Request Timeout", 411: "Length Required", 413: "Content Too Large",
    415: "Unsupported Media Type", 431: "Request Header Fields Too Large",
    500: "Internal Server Error"
  }[status] || "Internal Server Error";

  // Both the header length and the write itself must be in UTF-8 bytes, not
  // JS string length. A JS string is UTF-16 code units, so any non-ASCII in
  // the body (accented author names, math symbols in titles) previously
  // understated Content-Length and silently truncated the response.
  var encoder = new TextEncoder();
  var bodyBytes = encoder.encode(body);
  var headBytes = encoder.encode(
    "HTTP/1.0 " + status + " " + statusText + "\r\n"
    + "Content-Type: application/json; charset=utf-8\r\n"
    + "Content-Length: " + bodyBytes.length + "\r\n"
    + "Connection: close\r\n"
    + "\r\n"
  );

  try {
    var binary = Cc["@mozilla.org/binaryoutputstream;1"]
      .createInstance(Ci.nsIBinaryOutputStream);
    binary.setOutputStream(output);
    binary.writeByteArray(headBytes);
    binary.writeByteArray(bodyBytes);
    binary.close();
  } catch (e) {
    log("Write error: " + e);
    try { output.close(); } catch (_) {}
  }
}

function requestError(status, message) {
  var error = new Error(message);
  error.status = status;
  throw error;
}

function parseHeaders(data, port) {
  var lines = data.split("\r\n");
  var firstLine = /^([A-Z]+) (\/[^ ]*) HTTP\/1\.[01]$/.exec(lines.shift());
  if (!firstLine) requestError(400, "invalid request line");
  var headers = Object.create(null);
  for (var line of lines) {
    var colon = line.indexOf(":");
    var name = line.substring(0, colon).toLowerCase();
    if (colon < 1 || !/^[!#$%&'*+.^_`|~0-9a-z-]+$/.test(name)
        || /[\x00-\x08\x0a-\x1f\x7f-\xff]/.test(line)
        || name in headers) {
      requestError(400, "invalid or duplicate header");
    }
    headers[name] = line.substring(colon + 1).trim();
  }

  var hosts = ["127.0.0.1:" + port, "localhost:" + port, "[::1]:" + port];
  if (!hosts.includes((headers.host || "").toLowerCase())) {
    requestError(403, "Host must name the loopback listener");
  }
  if ("origin" in headers) requestError(403, "browser origins are not allowed");
  if ("transfer-encoding" in headers) requestError(400, "transfer encoding is not supported");

  var method = firstLine[1];
  var path = firstLine[2];
  if (!(method === "GET" && path === "/status")
      && !(method === "POST" && path === "/execute")) {
    requestError(404, "not found");
  }
  if (method === "POST") {
    // This fixed header forces browser fetch callers through preflight. It is
    // public protocol information, not a secret or local-client authentication.
    if (headers["x-zev-client"] !== "1") requestError(403, "X-Zev-Client: 1 is required");
    if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(headers["content-type"] || "")) {
      requestError(415, "Content-Type must be application/json with UTF-8 encoding");
    }
    if (!("content-length" in headers)) requestError(411, "Content-Length is required");
  }
  var length = headers["content-length"] === undefined ? "0" : headers["content-length"];
  if (!/^\d+$/.test(length)) requestError(400, "invalid Content-Length");
  var bodyLength = Number(length);
  if (!Number.isSafeInteger(bodyLength) || bodyLength > MAX_BODY_BYTES) {
    requestError(413, "request body exceeds 1 MiB");
  }
  if (method === "GET" && bodyLength !== 0) requestError(400, "status request must have no body");
  return { method: method, path: path, bodyLength: bodyLength };
}

function handleRequest(request, body, output) {
  try {
    if (request.method === "GET") {
      sendHTTP(output, 200, JSON.stringify({ status: "ok", version: pluginVersion }));
      return;
    }

    var parsed;
    try {
      // nsIScriptableInputStream returns raw octets, not decoded Unicode text.
      var bytes = Uint8Array.from(body, function(c) { return c.charCodeAt(0); });
      parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch (_) {
      sendHTTP(output, 400, JSON.stringify({ error: "body must be valid UTF-8 JSON" }));
      return;
    }
    if (!parsed || typeof parsed.code !== "string" || !parsed.code.trim()) {
      sendHTTP(output, 400, JSON.stringify({ error: "code must be a nonempty string" }));
      return;
    }
    var code = parsed.code;

    try {
      var fn = new Function("Zotero", "return (async () => { " + code + " })();");
      var promise = fn(Zotero);

      promise.then(
        function(result) {
          sendHTTP(output, 200, JSON.stringify({ ok: true, result: result }));
        },
        function(err) {
          sendHTTP(output, 200, JSON.stringify({ ok: false, error: err.toString() }));
        }
      );
    } catch (e) {
      sendHTTP(output, 200, JSON.stringify({ ok: false, error: e.toString() }));
    }
  } catch (e) {
    log("Request error: " + e);
    try {
      sendHTTP(output, 500, JSON.stringify({ error: e.toString() }));
    } catch (_) {}
  }
}

function readRequest(transport, port) {
  var input = transport.openInputStream(0, 0, 0);
  var output = transport.openOutputStream(0, 0, 0);
  var asyncInput = input.QueryInterface(Ci.nsIAsyncInputStream);
  var sis = Cc["@mozilla.org/scriptableinputstream;1"]
    .createInstance(Ci.nsIScriptableInputStream);
  sis.init(input);
  var timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  var data = "";
  var request = null;
  var bodyStart = 0;
  var finished = false;

  function finish(status, error) {
    if (finished) return;
    finished = true;
    timer.cancel();
    pendingReads.delete(abort);
    try { asyncInput.asyncWait(null, 0, 0, Services.tm.mainThread); } catch (_) {}
    try { input.close(); } catch (_) {}
    if (status) sendHTTP(output, status, JSON.stringify({ error: error }));
  }
  function abort() {
    finish();
    try { output.close(); } catch (_) {}
  }
  var callback = {
    onInputStreamReady: function() {
      if (finished) return;
      try {
        var avail = sis.available();
        if (!avail) requestError(400, "incomplete request");
        // Read one byte beyond the limit to detect overflow without allocating
        // an unbounded chunk. Once headers are known, read only the body limit.
        var limit = request ? bodyStart + request.bodyLength : MAX_HEADER_BYTES;
        data += sis.readBytes(Math.min(avail, limit + 1 - data.length));
        if (!request) {
          var end = data.indexOf("\r\n\r\n");
          if (end === -1) {
            if (data.length > MAX_HEADER_BYTES) requestError(431, "headers exceed 16 KiB");
          } else {
            bodyStart = end + 4;
            if (bodyStart > MAX_HEADER_BYTES) requestError(431, "headers exceed 16 KiB");
            request = parseHeaders(data.substring(0, end), port);
          }
        }
        if (request) {
          var expected = bodyStart + request.bodyLength;
          if (data.length > expected) requestError(400, "unexpected bytes after request body");
          if (data.length === expected) {
            finish();
            handleRequest(request, data.substring(bodyStart), output);
            return;
          }
        }
        asyncInput.asyncWait(callback, 0, 0, Services.tm.mainThread);
      } catch (e) {
        finish(e.status || 400, e.status ? e.message : "could not read complete request");
      }
    }
  };
  pendingReads.add(abort);
  // An absolute deadline covers headers and body. It ends before JavaScript
  // starts and cannot interrupt synchronous code on Zotero's main thread.
  timer.initWithCallback({ notify: function() {
    finish(408, "request was not received within 5 seconds");
  } }, READ_TIMEOUT_MS, Ci.nsITimer.TYPE_ONE_SHOT);
  asyncInput.asyncWait(callback, 0, 0, Services.tm.mainThread);
}

function startServer() {
  if (!isEnabled()) {
    log("Disabled via preference.");
    return;
  }

  var port = getPort();

  try {
    serverSocket = Cc["@mozilla.org/network/server-socket;1"]
      .createInstance(Ci.nsIServerSocket);
    serverSocket.init(port, true, -1);

    serverSocket.asyncListen({
      onSocketAccepted: function(socket, transport) {
        readRequest(transport, port);
      },

      onStopListening: function(socket, status) {
        log("Server stopped (status=" + status + ")");
      }
    });

    log("Listening on 127.0.0.1:" + port);
  } catch (e) {
    log("Failed to start: " + e);
    serverSocket = null;
  }
}

function stopServer() {
  for (var abort of pendingReads) abort();
  if (serverSocket) {
    try {
      serverSocket.close();
      log("Server closed.");
    } catch (e) {
      log("Error closing: " + e);
    }
    serverSocket = null;
  }
}

// --- Zotero 7/8/9 bootstrap lifecycle ---

function startup(data, reason) {
  pluginVersion = data && data.version ? data.version : "unknown";
  log("Starting v" + data.version + " (reason=" + reason + ")");
  Zotero.uiReadyPromise.then(function() { startServer(); });
}

function shutdown(data, reason) {
  log("Shutting down (reason=" + reason + ")");
  stopServer();
}

function install(data, reason) {
  log("Installed v" + data.version);
}

function uninstall(data, reason) {
  log("Uninstalled v" + data.version);
}
