// Oracle for the coordinator's control-plane POLICY — the part that decides who
// may join a channel and what may cross the wire. Pure logic, no Workers runtime:
// this is the JS analogue of tests/test_net.py (which tests the Python hub). The
// WebSocketPair glue is the only thing left untested here, deliberately.
//
// Run: node --test coordinator-cf/test/   (also `npm test` in this dir)
import { test } from "node:test";
import assert from "node:assert/strict";
import { truthy, channelFor, relayable, ALLOWED, CoordChannel, frameSize, admitFrame, ring } from "../src/worker.js";

const u = (qs) => new URL("https://c.example.dev/ws/ui" + qs);

// ---- truthy -----------------------------------------------------------------
test("truthy: env-string flag parsing", () => {
  for (const on of ["1", "true", "yes", "on", "TRUE"]) assert.equal(truthy(on), true, on);
  for (const off of ["", "0", "false", "no", "off", undefined, null]) assert.equal(truthy(off), false, String(off));
});

// ---- channelFor: local dev (no token required) ------------------------------
test("channelFor: without REQUIRE_TOKEN, empty → shared 'local' channel", () => {
  assert.deepEqual(channelFor(u(""), {}), { token: "local" });
  assert.deepEqual(channelFor(u("?token=abc"), {}), { token: "abc" });
});

// ---- channelFor: hosted (the fix) -------------------------------------------
test("channelFor: REQUIRE_TOKEN rejects a missing token (no shared 'local')", () => {
  const r = channelFor(u(""), { REQUIRE_TOKEN: "1" });
  assert.ok(r.reject, "must reject");
  assert.equal(r.reject.status, 401);
});

test("channelFor: REQUIRE_TOKEN rejects the reserved 'local' sentinel explicitly", () => {
  const r = channelFor(u("?token=local"), { REQUIRE_TOKEN: "1" });
  assert.ok(r.reject);
  assert.equal(r.reject.status, 401);
});

test("channelFor: REQUIRE_TOKEN rejects a weak (short) token", () => {
  const r = channelFor(u("?token=short123"), { REQUIRE_TOKEN: "1" });
  assert.ok(r.reject);
  assert.equal(r.reject.status, 401);
});

test("channelFor: REQUIRE_TOKEN admits a strong token to its own channel", () => {
  const strong = "9f1c7b2a-0e4d-4a11-bc33-77aa55ee9900"; // randomUUID shape
  assert.deepEqual(channelFor(u("?token=" + strong), { REQUIRE_TOKEN: "1" }), { token: strong });
});

test("channelFor: two different strong tokens → two different channels", () => {
  const a = channelFor(u("?token=" + "a".repeat(20)), { REQUIRE_TOKEN: "1" });
  const b = channelFor(u("?token=" + "b".repeat(20)), { REQUIRE_TOKEN: "1" });
  assert.notEqual(a.token, b.token);
});

// ---- relayable: only typed, whitelisted messages cross ----------------------
test("relayable: whitelisted jobs with an id pass; everything else is dropped", () => {
  for (const kind of ALLOWED) assert.equal(relayable(JSON.stringify({ type: "job", kind, id: "1" })), true, kind);
  assert.equal(relayable(JSON.stringify({ type: "job", kind: "rm -rf", id: "1" })), false); // kind not allowed
  assert.equal(relayable(JSON.stringify({ type: "job", kind: "run" })), false);             // no id
  assert.equal(relayable(JSON.stringify({ type: "chat", id: "1", text: "hi" })), true);
  assert.equal(relayable(JSON.stringify({ type: "apps" })), true);
  assert.equal(relayable(JSON.stringify({ type: "upload", uid: "x", i: 0, n: 2, data: "AA" })), true);
  assert.equal(relayable(JSON.stringify({ type: "log", line: "x" })), false);
  assert.equal(relayable("not json"), false);
});

// ---- one runner per channel, with takeover on reconnect (hibernation DO) -----
function mockState(sockets = []) {
  const tags = new Map(sockets.map((s) => [s, s._tags || ["runner"]]));
  return {
    setWebSocketAutoResponse() {},
    acceptWebSocket(ws, t) { sockets.push(ws); tags.set(ws, t); },
    getWebSockets(tag) { return sockets.filter((s) => !tag || (tags.get(s) || []).includes(tag)); },
    getTags(ws) { return tags.get(ws) || []; },
  };
}

test("CoordChannel: a reconnecting runner closes the stale one (1012), not 409", async () => {
  let closedCode = null;
  const stale = { _tags: ["runner"], close(c) { closedCode = c; }, send() {} };
  const ch = new CoordChannel(mockState([stale]), {});
  try {
    await ch.fetch(new Request("https://c.example.dev/ws/runner", { headers: { Upgrade: "websocket" } }));
  } catch (_) {
    // WebSocketPair isn't available under node:test — we only assert the takeover
    // (closing the stale runner) that runs before the pair is created.
  }
  assert.equal(closedCode, 1012);
});

test("CoordChannel.webSocketMessage: UI job → runner; oversize dropped", () => {
  const runner = { _tags: ["runner"], sent: [], send(d) { this.sent.push(d); } };
  const ui = { _tags: ["ui"], send() {} };
  const ch = new CoordChannel(mockState([runner, ui]), {});
  ch.webSocketMessage(ui, JSON.stringify({ type: "job", kind: "run", id: "1" }));
  assert.equal(runner.sent.length, 1);                 // relayed to the runner
  ch.webSocketMessage(ui, "x".repeat(256 * 1024 + 1)); // oversize → dropped
  assert.equal(runner.sent.length, 1);
});

// ---- DoS guards: frame size + rate ------------------------------------------
test("frameSize: string length and binary byteLength", () => {
  assert.equal(frameSize("hello"), 5);
  assert.equal(frameSize(new ArrayBuffer(12)), 12);
  assert.equal(frameSize(undefined), 0);
});

test("admitFrame: oversize is dropped in either direction", () => {
  const big = 256 * 1024 + 1;
  assert.equal(admitFrame({}, big, 0, true).ok, false);
  assert.equal(admitFrame({}, big, 0, false).ok, false); // runner too
  assert.equal(admitFrame({}, 100, 0, false).ok, true);
});

test("admitFrame: UI rate cap trips after the window fills, runner is uncapped", () => {
  const meter = {};
  let last;
  for (let i = 0; i < 65; i++) last = admitFrame(meter, 10, 1000 + i, true);
  assert.equal(last.ok, false);           // 61st+ within the window is dropped
  assert.equal(last.reason, "rate");
  // the runner stream is never rate-limited (bursty logs)
  const rmeter = {};
  let ok = true;
  for (let i = 0; i < 500; i++) ok = ok && admitFrame(rmeter, 10, 1000 + i, false).ok;
  assert.equal(ok, true);
});

test("admitFrame: the rate window slides (old hits expire)", () => {
  const meter = {};
  for (let i = 0; i < 60; i++) admitFrame(meter, 10, 1000 + i, true); // fill the window
  assert.equal(admitFrame(meter, 10, 1060, true).ok, false);          // still full
  assert.equal(admitFrame(meter, 10, 1000 + 10_001, true).ok, true);  // 10s later → room
});

// ---- replay buffer: bounded, ordered ----------------------------------------
test("ring: caps length, keeps the most recent in order", () => {
  let buf = [];
  for (let i = 0; i < 5; i++) buf = ring(buf, "f" + i, 3);
  assert.deepEqual(buf, ["f2", "f3", "f4"]);
});
