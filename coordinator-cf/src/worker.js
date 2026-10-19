// AREA coordinator on Cloudflare Workers (ADR 0002, P3 — option A).
// Control plane only: relays a fixed, typed set of jobs between a UI and a runner.
// Runs NO agents and holds NO secrets. Each pairing TOKEN is a private channel,
// backed by one Durable Object instance (idFromName(token)).

const ALLOWED = new Set(["doctor", "run", "clone", "intake", "iterate", "deploy", "export"]);

// One channel = one DO instance. Holds the runner + its UIs in memory and relays
// between them (the JS port of area/net/hub.py).
export class CoordChannel {
  constructor(state, env) {
    this.runner = null;
    this.uis = new Set();
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.pathname.endsWith("/ws/runner") ? "runner" : "ui";
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    server.accept();

    if (role === "runner") {
      this.runner = server;
      this._bcast(JSON.stringify({ type: "coord", runner: true }));
    } else {
      this.uis.add(server);
      server.send(JSON.stringify({ type: "coord", runner: !!this.runner }));
    }

    server.addEventListener("message", (ev) => {
      if (role === "ui") {
        if (this._relayable(ev.data) && this.runner) {
          try { this.runner.send(ev.data); } catch (_) { /* dead runner */ }
        }
      } else {
        this._bcast(ev.data); // runner output → this channel's UIs only
      }
    });

    const bye = () => {
      if (role === "runner") {
        if (server === this.runner) {
          this.runner = null;
          this._bcast(JSON.stringify({ type: "coord", runner: false }));
        }
      } else {
        this.uis.delete(server);
      }
    };
    server.addEventListener("close", bye);
    server.addEventListener("error", bye);

    return new Response(null, { status: 101, webSocket: client });
  }

  _bcast(data) {
    for (const u of [...this.uis]) {
      try { u.send(data); } catch (_) { this.uis.delete(u); }
    }
  }

  // Only a typed job / chat / apps request may cross the wire (no arbitrary shell).
  _relayable(raw) {
    try {
      const m = JSON.parse(raw);
      if (m.type === "chat" || m.type === "apps") return true;
      return m.type === "job" && ALLOWED.has(m.kind) && !!m.id;
    } catch (_) {
      return false;
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
      // The pairing token names the channel (its Durable Object). Empty = local.
      const token = url.searchParams.get("token") || "local";
      const id = env.COORD.idFromName(token);
      return env.COORD.get(id).fetch(request);
    }
    // "/" and other static paths are served by the assets binding; anything the
    // Worker reaches here has no asset.
    return new Response("not found", { status: 404 });
  },
};
