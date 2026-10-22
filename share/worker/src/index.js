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

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const KINDS = { deck: "Deck", list: "List", trade: "Trade", collection: "Collection" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The address people are given: chat apps (WhatsApp, Telegram, Discord) read the preview tags of THIS page, which they cannot do from the
// static viewer (it is the same page for every list), then people are sent on to the viewer. Everything from the document is escaped.
export function previewPage(id, doc, env) {
  const viewer = (env.VIEWER_URL || "https://nuno-f-rocha-alb.github.io/scrybinder/").replace(/\/?$/, "/");
  const target = `${viewer}?id=${id}`;
  let title = "Scrybinder share", desc = "A deck, list, trade or collection shared from Scrybinder.", image = `${viewer}og.png`;
  if (doc) {
    const lines = doc.sections.flatMap((s) => s.cards);
    const cards = lines.reduce((n, c) => n + c.qty, 0);
    const value = doc.prices ? lines.reduce((n, c) => n + (c.price || 0) * c.qty, 0) : null;
    title = doc.title.slice(0, 90);
    desc = [KINDS[doc.kind] || doc.kind, `${cards} ${cards === 1 ? "card" : "cards"}`, doc.meta?.format, value != null ? `about ${value.toFixed(2)} EUR` : null].filter(Boolean).join(" · ");
    if (doc.note) desc += ` — ${doc.note.replace(/\s+/g, " ").slice(0, 120)}`;
    const first = lines.find((c) => UUID.test(c.id));
    if (first) image = `https://cards.scryfall.io/art_crop/front/${first.id[0]}/${first.id[1]}/${first.id}.jpg`;  // the art of the first card (the commander of a deck)
  }
  const t = esc(`${title} · Scrybinder`), d = esc(desc.slice(0, 200)), u = esc(target), i = esc(image);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${t}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="${d}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Scrybinder">
<meta property="og:title" content="${t}"><meta property="og:description" content="${d}">
<meta property="og:url" content="${u}"><meta property="og:image" content="${i}"><meta property="og:image:alt" content="${esc(title)}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="${t}"><meta name="twitter:description" content="${d}"><meta name="twitter:image" content="${i}">
<meta http-equiv="refresh" content="0;url=${u}"><link rel="canonical" href="${u}"></head>
<body style="font-family:system-ui,sans-serif;background:#0e1118;color:#e8e8ec;padding:2rem"><p>Opening <a style="color:#8b6cf0" href="${u}">${esc(title)}</a>…</p></body></html>`;
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const page = url.pathname.match(/^\/s\/([0-9A-Za-z]{12})$/);
  if (page && (request.method === "GET" || request.method === "HEAD")) {
    const rec = await env.SHARES.get(page[1], "json");
    return new Response(request.method === "HEAD" ? null : previewPage(page[1], rec?.doc, env), {
      status: rec ? 200 : 404,
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https:" },
    });
  }
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
