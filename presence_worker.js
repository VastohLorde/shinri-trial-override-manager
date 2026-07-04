// Override Manager - Community Presence backend (Cloudflare Worker)
// ------------------------------------------------------------------
// Lets Override Manager users on the same GMod server see each other WITHOUT
// any in-game Lua (servers block clientside Lua). Each app heartbeats which
// server it's on + its community packs; others on the same server read it back.
//
// DEPLOY (one time, free):
//   1. Create a free Cloudflare account -> Workers & Pages -> Create Worker.
//   2. Create a KV namespace (Storage & Databases -> KV -> Create). Name it e.g.
//      "PRESENCE". Bind it to the worker as variable name  PRESENCE
//      (Worker -> Settings -> Variables -> KV Namespace Bindings).
//   3. Paste this file as the worker code and Deploy.
//   4. Copy the worker URL (https://<name>.<sub>.workers.dev) and put it in the
//      app as DEFAULT_PRESENCE_URL (override_manager.py).
//
// Endpoints:
//   POST /beat   {server, id, name, packs:[...]}  -> {ok:true}
//   GET  /peers?server=<ip:port>&exclude=<id>     -> {peers:[{id,name,packs,ts}]}

const TTL_SECONDS = 90; // a user is "present" for 90s after their last heartbeat
const MAX_PACKS = 60;
const MAX_STR = 64;

function clampStr(s) {
  return String(s == null ? "" : s).slice(0, MAX_STR);
}

// A server key must look like an ip:port so one user can't scribble on shared keys.
function safeServer(s) {
  s = String(s || "");
  return /^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$/.test(s) ? s : null;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const kv = env.PRESENCE;
    if (!kv) return json({ error: "KV not bound" }, 500);

    if (request.method === "POST" && url.pathname === "/beat") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      const server = safeServer(body.server);
      const id = clampStr(body.id);
      if (!server || !id) return json({ error: "server+id required" }, 400);
      const rec = {
        id,
        name: clampStr(body.name) || "Player",
        packs: Array.isArray(body.packs) ? body.packs.slice(0, MAX_PACKS).map(clampStr) : [],
        ts: Math.floor(Date.now() / 1000),
      };
      // TTL auto-expires the record, so stale users vanish on their own.
      await kv.put(`p:${server}:${id}`, JSON.stringify(rec), { expirationTtl: TTL_SECONDS });
      return json({ ok: true });
    }

    if (request.method === "GET" && url.pathname === "/peers") {
      const server = safeServer(url.searchParams.get("server"));
      const exclude = clampStr(url.searchParams.get("exclude"));
      if (!server) return json({ peers: [] });
      const list = await kv.list({ prefix: `p:${server}:` });
      const peers = [];
      for (const k of list.keys) {
        const raw = await kv.get(k.name);
        if (!raw) continue;
        try {
          const rec = JSON.parse(raw);
          if (rec.id && rec.id !== exclude) peers.push(rec);
        } catch { /* skip */ }
      }
      return json({ peers });
    }

    return json({ ok: true, service: "ovr-presence" });
  },
};
