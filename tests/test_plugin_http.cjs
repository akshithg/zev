const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

// Exercise the plugin's socket callbacks, replacing only Zotero/XPCOM boundaries.
const source = fs.readFileSync(path.join(__dirname, "../zotero-plugin/bootstrap.js"), "utf8");
function bridge(port = 24119) {
  const timers = [];
  let listener;
  let binding;
  const Zotero = { calls: 0, debug() {}, Prefs: { get: () => undefined } };
  const context = vm.createContext({
    Zotero, TextEncoder, TextDecoder, Uint8Array,
    Services: { tm: { mainThread: {} } },
    Ci: { nsITimer: { TYPE_ONE_SHOT: 0 } },
    Cc: {
      "@mozilla.org/network/server-socket;1": { createInstance: () => ({
        init(...args) { binding = args; },
        asyncListen(value) { listener = value; },
        close() {},
      }) },
      "@mozilla.org/scriptableinputstream;1": { createInstance: () => ({
        init(stream) { this.stream = stream; },
        available() { return this.stream.available(); },
        readBytes(n) { return this.stream.read(n); },
        close() { this.stream.close(); },
      }) },
      "@mozilla.org/binaryoutputstream;1": { createInstance: () => ({
        setOutputStream(stream) { this.stream = stream; },
        writeByteArray(bytes) { this.stream.bytes.push(Buffer.from(bytes)); },
        close() { this.stream.close(); },
      }) },
      "@mozilla.org/timer;1": { createInstance: () => {
        const timer = {
          cancelled: false,
          initWithCallback(callback, delay) { this.callback = callback; this.delay = delay; },
          cancel() { this.cancelled = true; },
          fire() { if (!this.cancelled) this.callback.notify(); },
        };
        timers.push(timer);
        return timer;
      } },
    },
  });
  Zotero.Prefs.get = (name) => name.endsWith(".port") ? port : undefined;
  vm.runInContext(source, context);
  context.startServer();
  return {
    Zotero, timers, binding,
    stop: () => context.stopServer(),
    connect() {
      let bytes = Buffer.alloc(0);
      let callback;
      let eof = false;
      const input = {
        closed: false,
        QueryInterface() { return this; },
        asyncWait(value) { callback = value; },
        available() { if (eof) throw new Error("stream closed"); return bytes.length; },
        read(n) { const result = bytes.subarray(0, n).toString("latin1"); bytes = bytes.subarray(n); return result; },
        close() { this.closed = true; },
      };
      const output = { bytes: [], closed: false, close() { this.closed = true; } };
      listener.onSocketAccepted(null, {
        openInputStream: () => input,
        openOutputStream: () => output,
      });
      function ready() { const current = callback; callback = null; if (current) current.onInputStreamReady(input); }
      return {
        input, output,
        feed(chunk) { bytes = Buffer.concat([bytes, Buffer.from(chunk)]); ready(); },
        end() { eof = true; ready(); },
        response() {
          const raw = Buffer.concat(output.bytes);
          if (!raw.length) return null;
          const separator = raw.indexOf("\r\n\r\n");
          const headers = raw.subarray(0, separator).toString();
          const body = raw.subarray(separator + 4);
          const length = Number(headers.match(/Content-Length: (\d+)/)[1]);
          assert.equal(body.length, length);
          assert.doesNotMatch(headers, /Access-Control-Allow/i);
          return { status: Number(headers.split(" ")[1]), body: JSON.parse(body.toString()) };
        },
      };
    },
  };
}

function request({ method = "POST", route = "/execute", body = JSON.stringify({code: 'Zotero.calls++; return "café 雪";'}), headers = {}, port = 24119 } = {}) {
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(body);
  const fields = {
    Host: `127.0.0.1:${port}`,
    "Content-Type": "application/json",
    "X-Zev-Client": "1",
    "Content-Length": String(bytes.length),
    ...headers,
  };
  const head = [`${method} ${route} HTTP/1.1`, ...Object.entries(fields).filter(([, v]) => v !== null).map(([k, v]) => `${k}: ${v}`), "", ""].join("\r\n");
  return Buffer.concat([Buffer.from(head), bytes]);
}
const settle = () => new Promise(setImmediate);

test("loopback binding, valid CLI request, and UTF-8 response", async () => {
  const b = bridge();
  assert.deepEqual(b.binding, [24119, true, -1]);
  const c = b.connect();
  c.feed(request());
  await settle();
  assert.deepEqual(c.response(), {status: 200, body: {ok: true, result: "café 雪"}});
  assert.equal(b.Zotero.calls, 1);
  assert.equal(c.input.closed, true);
});

test("headers and multibyte body can arrive one byte at a time", async () => {
  const b = bridge();
  const c = b.connect();
  const bytes = request();
  for (let i = 0; i < bytes.length - 1; i++) {
    c.feed(bytes.subarray(i, i + 1));
    assert.equal(c.response(), null);
    assert.equal(b.Zotero.calls, 0);
  }
  c.feed(bytes.subarray(-1));
  await settle();
  assert.equal(c.response().body.result, "café 雪");
  assert.equal(b.Zotero.calls, 1);
  assert.equal(b.timers[0].cancelled, true);
});

for (const [name, options, status] of [
  ["nonloopback Host", {headers: {Host: "example.invalid:24119"}}, 403],
  ["missing Host", {headers: {Host: null}}, 403],
  ["wrong port", {headers: {Host: "127.0.0.1:80"}}, 403],
  ["Origin", {headers: {Origin: "https://example.invalid"}}, 403],
  ["null Origin", {headers: {Origin: "null"}}, 403],
  ["empty Origin", {headers: {Origin: ""}}, 403],
  ["missing client header", {headers: {"X-Zev-Client": null}}, 403],
  ["wrong client header", {headers: {"X-Zev-Client": "0"}}, 403],
  ["text body", {headers: {"Content-Type": "text/plain"}}, 415],
  ["form body", {headers: {"Content-Type": "application/x-www-form-urlencoded"}}, 415],
  ["missing type", {headers: {"Content-Type": null}}, 415],
  ["missing length", {headers: {"Content-Length": null}}, 411],
  ["negative length", {headers: {"Content-Length": "-1"}}, 400],
  ["invalid length", {headers: {"Content-Length": "3x"}}, 400],
  ["oversized body", {headers: {"Content-Length": "1048577"}}, 413],
  ["transfer encoding", {headers: {"Transfer-Encoding": "chunked"}}, 400],
  ["malformed JSON", {body: "not-json"}, 400],
  ["missing code", {body: "{}"}, 400],
  ["nonstring code", {body: '{"code":42}'}, 400],
  ["empty code", {body: '{"code":"  "}'}, 400],
  ["null JSON", {body: "null"}, 400],
  ["embedded NULL", {body: Buffer.from([0])}, 400],
  ["invalid UTF-8", {body: Buffer.from([0xff])}, 400],
  ["extra bytes", {headers: {"Content-Length": "1"}}, 400],
  ["preflight", {method: "OPTIONS"}, 404],
]) {
  test(`rejects ${name} before evaluation`, async () => {
    const b = bridge();
    const c = b.connect();
    c.feed(request(options));
    await settle();
    assert.equal(c.response().status, status);
    assert.equal(b.Zotero.calls, 0);
    assert.equal(c.input.closed, true);
  });
}

for (const host of ["localhost:24119", "[::1]:24119", "LOCALHOST:24119"]) {
  test(`accepts loopback Host ${host}`, async () => {
    const c = bridge().connect();
    c.feed(request({headers: {Host: host, "Content-Type": "application/json; charset=utf-8"}}));
    await settle();
    assert.equal(c.response().body.ok, true);
  });
}

test("configured port is validated", async () => {
  const c = bridge(24120).connect();
  c.feed(request({port: 24120}));
  await settle();
  assert.equal(c.response().body.ok, true);
});

test("status remains available to doctor without execution headers", () => {
  const c = bridge().connect();
  c.feed(request({method: "GET", route: "/status", body: "", headers: {"Content-Type": null, "X-Zev-Client": null, "Content-Length": null}}));
  assert.equal(c.response().body.status, "ok");
});

for (const extra of ["Host: localhost:24119", "Content-Length: 1", "bad header", " folded: value", "Bad Name: value"]) {
  test(`rejects malformed or duplicate header ${extra}`, () => {
    const b = bridge();
    const c = b.connect();
    const bytes = request().toString();
    c.feed(bytes.replace("\r\n\r\n", `\r\n${extra}\r\n\r\n`));
    assert.equal(c.response().status, 400);
    assert.equal(b.Zotero.calls, 0);
  });
}

test("oversized headers are rejected before an unbounded read", () => {
  const c = bridge().connect();
  c.feed(Buffer.from("GET /status HTTP/1.1\r\nX-Large: " + "x".repeat(16384)));
  assert.equal(c.response().status, 431);
});

for (const bytes of [Buffer.alloc(0), request().subarray(0, 10), request().subarray(0, -1)]) {
  test(`absolute read deadline closes incomplete request (${bytes.length} bytes)`, () => {
    const b = bridge();
    const c = b.connect();
    if (bytes.length) c.feed(bytes);
    assert.equal(c.response(), null);
    assert.equal(b.timers[0].delay, 5000);
    b.timers[0].fire();
    assert.equal(c.response().status, 408);
    assert.equal(c.input.closed, true);
    assert.equal(b.Zotero.calls, 0);
    c.feed(request());
    assert.equal(b.Zotero.calls, 0);
  });
}

test("EOF before body completion is rejected", () => {
  const b = bridge();
  const c = b.connect();
  c.feed(request().subarray(0, -1));
  c.end();
  assert.equal(c.response().status, 400);
  assert.equal(b.Zotero.calls, 0);
  assert.equal(b.timers[0].cancelled, true);
});

test("shutdown cancels pending reads and their timers", () => {
  const b = bridge();
  const c = b.connect();
  b.stop();
  assert.equal(c.input.closed, true);
  assert.equal(c.output.closed, true);
  assert.equal(b.timers[0].cancelled, true);
  c.feed(request());
  assert.equal(b.Zotero.calls, 0);
});

test("read deadline stops when evaluation starts, without cancelling JavaScript", async () => {
  const b = bridge();
  let resolve;
  b.Zotero.wait = new Promise(r => { resolve = r; });
  const c = b.connect();
  c.feed(request({body: JSON.stringify({code: "await Zotero.wait; return 7;"})}));
  assert.equal(b.timers[0].cancelled, true);
  b.timers[0].fire();
  assert.equal(c.response(), null);
  resolve();
  await settle();
  assert.equal(c.response().body.result, 7);
});

test("execution errors preserve the existing result envelope", async () => {
  const c = bridge().connect();
  c.feed(request({body: JSON.stringify({code: 'throw new Error("test failure");'})}));
  await settle();
  assert.deepEqual(c.response(), {status: 200, body: {ok: false, error: "Error: test failure"}});
});

test("a body at the 1 MiB limit is accepted across chunks", async () => {
  const b = bridge();
  const c = b.connect();
  const body = JSON.stringify({code: "Zotero.calls++; return 7;"}).padEnd(1048576, " ");
  const bytes = request({body});
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    c.feed(bytes.subarray(offset, offset + 8192));
  }
  await settle();
  assert.equal(c.response().body.result, 7);
  assert.equal(b.Zotero.calls, 1);
});
