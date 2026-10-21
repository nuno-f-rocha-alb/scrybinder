// Scrybinder share service: keeps a share document for 30 days under a random id.
//   POST   /api/share            body = share document  -> {id, delete_token, expires}
//   GET    /api/share/:id        -> the document (CORS: the viewer only)
//   PUT    /api/share/:id        header X-Delete-Token, body = share document -> {id, expires}: same link, new cards, 30 more days
//   DELETE /api/share/:id        header X-Delete-Token   -> {ok}
// No accounts, no cookies, no logging of bodies. Bindings: SHARES (KV), RATE (optional rate limiter), VIEWER_ORIGIN, TTL_DAYS.
import { MAX_BYTES, validate } from "./validate.js";

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const ID_RE = /^[0-9A-Za-z]{12}$/;

const randomId = () => {
  const b = new Uint8Array(12);
  let out = "";
  while (out.length < 12) {
    crypto.getRandomValues(b);
    for (const x of b) if (x < 248 && out.length < 12) out += ALPHABET[x % 62];  // 248 = 62 * 4: no modulo bias
  }
  return out;
};
const sha256 = async (s) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)))].map((x) => x.toString(16).padStart(2, "0")).join("");
const same = (a, b) => {  // constant time for equal-length hex strings
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
};

const json = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", ...extra } });
const err = (status, message, extra) => json({ error: message }, status, extra);

export async function handle(request, env) {
  const url = new URL(request.url);
  const cors = env.VIEWER_ORIGIN ? { "Access-Control-Allow-Origin": env.VIEWER_ORIGIN, Vary: "Origin" } : {};
  const m = url.pathname.match(/^\/api\/share(?:\/([^/]+))?$/);
  if (!m) return err(404, "not found");
  const id = m[1];

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" } });

  if (request.method === "POST" && !id) {
    if (!(request.headers.get("Content-Type") || "").toLowerCase().startsWith("application/json")) return err(415, "send application/json");
    if (env.RATE) {
      const { success } = await env.RATE.limit({ key: request.headers.get("CF-Connecting-IP") || "unknown" });
      if (!success) return err(429, "too many shares, try again in a minute");
    }
    if (Number(request.headers.get("Content-Length") || 0) > MAX_BYTES) return err(413, "too big");
    const raw = await request.text();
    if (new TextEncoder().encode(raw).length > MAX_BYTES) return err(413, "too big");
    let doc;
    try {
      doc = validate(JSON.parse(raw));
    } catch (e) {
      return err(422, e instanceof SyntaxError ? "the body is not JSON" : e.message);
    }
    const ttl = Math.max(1, Number(env.TTL_DAYS) || 30) * 86400;
    const token = [...crypto.getRandomValues(new Uint8Array(24))].map((x) => x.toString(16).padStart(2, "0")).join("");
    const newId = randomId();
    const expires = new Date(Date.now() + ttl * 1000).toISOString();
    await env.SHARES.put(newId, JSON.stringify({ doc, h: await sha256(token), expires }), { expirationTtl: ttl });
    return json({ id: newId, delete_token: token, expires });
  }

  if (id && !ID_RE.test(id)) return err(404, "not found", cors);

  if (request.method === "GET" && id) {
    const rec = await env.SHARES.get(id, "json");
    return rec ? json(rec.doc, 200, cors) : err(404, "this link has expired or never existed", cors);
  }

  if (request.method === "PUT" && id) {  // the same link with the current cards: needs the delete token and gives the link a new 30 days
    const rec = await env.SHARES.get(id, "json");
    if (!rec) return err(404, "this link has expired or never existed");
    if (!same(await sha256(request.headers.get("X-Delete-Token") || ""), rec.h)) return err(403, "wrong delete token");
    if (!(request.headers.get("Content-Type") || "").toLowerCase().startsWith("application/json")) return err(415, "send application/json");
    if (Number(request.headers.get("Content-Length") || 0) > MAX_BYTES) return err(413, "too big");
    const raw = await request.text();
    if (new TextEncoder().encode(raw).length > MAX_BYTES) return err(413, "too big");
    let doc;
    try {
      doc = validate(JSON.parse(raw));
    } catch (e) {
      return err(422, e instanceof SyntaxError ? "the body is not JSON" : e.message);
    }
    const ttl = Math.max(1, Number(env.TTL_DAYS) || 30) * 86400;
    const expires = new Date(Date.now() + ttl * 1000).toISOString();
    await env.SHARES.put(id, JSON.stringify({ doc, h: rec.h, expires }), { expirationTtl: ttl });
    return json({ id, expires });
  }

  if (request.method === "DELETE" && id) {
    const rec = await env.SHARES.get(id, "json");
    if (!rec) return err(404, "not found");
    const token = request.headers.get("X-Delete-Token") || "";
    if (!same(await sha256(token), rec.h)) return err(403, "wrong delete token");
    await env.SHARES.delete(id);
    return json({ ok: true });
  }
  return err(405, "method not allowed");
}

export default { fetch: (request, env) => handle(request, env) };
