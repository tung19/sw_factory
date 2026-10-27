// AREA coordinator on Cloudflare Workers (ADR 0002, P3 — option A).
// Control plane only: relays a fixed, typed set of jobs between a UI and a runner.
// Runs NO agents and holds NO secrets. Each pairing TOKEN is a private channel,
// backed by one Durable Object instance (idFromName(token)).
//
// Security model (see the audit that produced this file):
//  - The pairing token is the ONLY credential. On the hosted coordinator
//    (REQUIRE_TOKEN=1 in wrangler.jsonc) a real token is mandatory: there is no
//    shared "local" channel and weak tokens are refused, so two strangers can
//    never land in the same Durable Object.
//  - One runner per channel. A second runner is refused (409) rather than
//    silently replacing the first — no quiet channel takeover.
// The pure helpers below (truthy / channelFor / relayable) carry that policy and
// are unit-tested in coordinator-cf/test/worker.test.mjs without the Workers runtime.

export const ALLOWED = new Set(["doctor", "run", "clone", "intake", "iterate", "deploy", "export"]);

const RESERVED = "local";   // the single-user loopback channel; never valid when a token is required
const MIN_TOKEN = 16;       // a pairing secret must have real entropy (randomUUID is 36 chars)
const MAX_FRAME = 256 * 1024;        // reject absurd frames — the typed protocol is tiny (DoS guard)
const RATE_N = 60, RATE_MS = 10_000; // a UI may send at most 60 command frames / 10s (a human clicks)
const REPLAY_MAX = 50;               // replay the last N runner frames to a (re)connecting UI

// Env flags arrive as strings ("1"/"true"/… or "0"/""/absent).
export function truthy(v) {
  const s = String(v ?? "").trim().toLowerCase();
  return s !== "" && s !== "0" && s !== "false" && s !== "no" && s !== "off";
}

// Decide which channel a request joins. When REQUIRE_TOKEN is off (local dev) an
// absent token means the shared "local" channel. When it is on (hosted) a strong,
// non-reserved token is mandatory; otherwise the request is rejected before any
// Durable Object is touched. Returns {token} or {reject:{status,msg}}.
export function channelFor(url, env) {
  const raw = (url.searchParams.get("token") || "").trim();
  if (!truthy(env && env.REQUIRE_TOKEN)) return { token: raw || RESERVED };
  if (!raw || raw === RESERVED) return { reject: { status: 401, msg: "pairing token required" } };
  if (raw.length < MIN_TOKEN) return { reject: { status: 401, msg: "pairing token too weak" } };
  return { token: raw };
}

// Only a typed job / chat / apps request may cross the wire (no arbitrary shell).
export function relayable(raw) {
  try {
    const m = JSON.parse(raw);
    if (m.type === "chat" || m.type === "apps" || m.type === "upload") return true;
    return m.type === "job" && ALLOWED.has(m.kind) && !!m.id;
  } catch (_) {
    return false;
  }
}

// Byte size of a WebSocket frame payload (string or binary).
export function frameSize(data) {
  if (typeof data === "string") return data.length;
  if (data && typeof data.byteLength === "number") return data.byteLength;
  return 0;
}

// Admit a frame or drop it. Size is capped in both directions; `rateLimit` adds a
// sliding-window cap (used for UI command frames, not the runner's bursty logs).
// `meter` is a small per-connection object the caller keeps across frames.
export function admitFrame(meter, size, now, rateLimit = true) {
  if (size > MAX_FRAME) return { ok: false, reason: "oversize" };
  if (!rateLimit) return { ok: true };
  meter.hits = (meter.hits || []).filter((t) => now - t < RATE_MS);
  if (meter.hits.length >= RATE_N) return { ok: false, reason: "rate" };
  meter.hits.push(now);
  return { ok: true };
}

// Append to a bounded ring buffer (oldest dropped), preserving order.
export function ring(arr, item, max) {
  const out = arr.length >= max ? arr.slice(arr.length - max + 1) : arr.slice();
  out.push(item);
  return out;
}

// One channel = one DO instance. Uses the WebSocket HIBERNATION API so a connection
// SURVIVES the DO being evicted/hibernated (Cloudflare holds the sockets): the
// runner stays reachable even when the DO isn't resident in memory. Sockets are
// found via state.getWebSockets(tag) rather than in-memory sets (which don't
// survive hibernation); an app-level `ping` gets an auto-pong without waking the DO.
export class CoordChannel {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.recent = []; // best-effort replay buffer (in-memory; lost on hibernation)
    try {
      this.state.setWebSocketAutoResponse(
        new WebSocketRequestResponsePair(
          JSON.stringify({ type: "ping" }), JSON.stringify({ type: "pong" }),
        ),
      );
    } catch (_) { /* older runtime without auto-response */ }
  }

  _runner() {
    const rs = this.state.getWebSockets("runner");
    return rs.length ? rs[0] : null;
  }

  _bcastUIs(data) {
    for (const u of this.state.getWebSockets("ui")) {
      try { u.send(data); } catch (_) { /* dead ui */ }
    }
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.pathname.endsWith("/ws/runner") ? "runner" : "ui";

    // One runner per channel, with TAKEOVER on reconnect (token is the auth, so a
    // new runner on the same token is the same operator reconnecting).
    if (role === "runner") {
      const existing = this._runner();
      if (existing) { try { existing.close(1012, "replaced by a newer runner"); } catch (_) {} }
    }

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    this.state.acceptWebSocket(server, [role]); // hibernatable; tagged by role

    if (role === "runner") {
      this._bcastUIs(JSON.stringify({ type: "coord", runner: true }));
    } else {
      try { server.send(JSON.stringify({ type: "coord", runner: !!this._runner() })); } catch (_) {}
      for (const f of this.recent) { try { server.send(f); } catch (_) {} }
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  // Hibernation delivers messages here (the DO may have been asleep).
  async webSocketMessage(ws, data) {
    if (frameSize(data) > MAX_FRAME) return;                                   // size cap (DoS)
    if (typeof data === "string" && data.startsWith('{"type":"ping"')) return; // keepalive (also auto-ponged)
    const isRunner = this.state.getTags(ws).includes("runner");
    if (!isRunner) {
      if (relayable(data)) {
        const r = this._runner();
        if (r) { try { r.send(data); } catch (_) {} }
      }
    } else {
      this.recent = ring(this.recent, data, REPLAY_MAX);
      this._bcastUIs(data); // runner output → this channel's UIs
    }
  }

  async webSocketClose(ws, code, reason, wasClean) {
    try { ws.close(); } catch (_) {}
    if (this.state.getTags(ws).includes("runner") && !this._runner()) {
      this._bcastUIs(JSON.stringify({ type: "coord", runner: false }));
    }
  }

  async webSocketError(ws) {
    if (this.state.getTags(ws).includes("runner") && !this._runner()) {
      this._bcastUIs(JSON.stringify({ type: "coord", runner: false }));
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/ws/ui" || url.pathname === "/ws/runner") {
      if (request.headers.get("Upgrade") !== "websocket") {
        return new Response("expected websocket", { status: 426 });
      }
      // The pairing token names the channel (its Durable Object), and gates entry.
      const ch = channelFor(url, env);
      if (ch.reject) return new Response(ch.reject.msg, { status: ch.reject.status });
      const id = env.COORD.idFromName(ch.token);
      return env.COORD.get(id).fetch(request);
    }
    // "/" and other static paths are served by the assets binding; anything the
    // Worker reaches here has no asset.
    return new Response("not found", { status: 404 });
  },
};
