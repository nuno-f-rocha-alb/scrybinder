import assert from "node:assert/strict";
import test from "node:test";
import { handle } from "../src/index.js";

const kv = () => {
  const m = new Map();
  return {
    m,
    puts: [],
    async put(k, v, opts) { m.set(k, v); this.puts.push(opts); },
    async get(k, type) { const v = m.get(k); return v === undefined ? null : type === "json" ? JSON.parse(v) : v; },
    async delete(k) { m.delete(k); },
  };
};
const env = (extra = {}) => ({ SHARES: kv(), VIEWER_ORIGIN: "https://v.example", ...extra });
const doc = (over = {}) => ({ format: "scrybinder-share", v: 1, kind: "deck", title: "T", sections: [{ name: "Main", cards: [{ id: "abc", name: "Sol Ring", qty: 1 }] }], ...over });
const post = (e, body, headers = { "Content-Type": "application/json" }) =>
  handle(new Request("https://w.example/api/share", { method: "POST", headers, body: typeof body === "string" ? body : JSON.stringify(body) }), e);

test("stores a document for 30 days and returns an id and a delete token", async () => {
  const e = env();
  const r = await post(e, doc());
  assert.equal(r.status, 200);
  const j = await r.json();
  assert.match(j.id, /^[0-9A-Za-z]{12}$/);
  assert.equal(j.delete_token.length, 48);
  assert.equal(e.SHARES.puts[0].expirationTtl, 30 * 86400);
  assert.ok(!e.SHARES.m.get(j.id).includes(j.delete_token), "only the hash of the token is kept");
});

test("GET returns the document with CORS for the viewer only; unknown ids are 404", async () => {
  const e = env();
  const { id } = await (await post(e, doc())).json();
  const r = await handle(new Request(`https://w.example/api/share/${id}`), e);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), "https://v.example");
  assert.equal((await r.json()).sections[0].cards[0].name, "Sol Ring");
  assert.equal((await handle(new Request("https://w.example/api/share/AAAAAAAAAAAA"), e)).status, 404);
  assert.equal((await handle(new Request("https://w.example/api/share/short"), e)).status, 404);
});

test("DELETE needs the token", async () => {
  const e = env();
  const { id, delete_token } = await (await post(e, doc())).json();
  const del = (t) => handle(new Request(`https://w.example/api/share/${id}`, { method: "DELETE", headers: t ? { "X-Delete-Token": t } : {} }), e);
  assert.equal((await del()).status, 403);
  assert.equal((await del("0".repeat(48))).status, 403);
  assert.equal((await del(delete_token)).status, 200);
  assert.equal((await handle(new Request(`https://w.example/api/share/${id}`), e)).status, 404);
});

test("rejects what is not a valid share document", async () => {
  const e = env();
  assert.equal((await post(e, doc(), { "Content-Type": "text/plain" })).status, 415);
  assert.equal((await post(e, "not json")).status, 422);
  for (const bad of [doc({ format: "x" }), doc({ v: 2 }), doc({ kind: "x" }), doc({ sections: [] }),
    doc({ sections: [{ cards: [{ id: "a", qty: 0 }] }] }), doc({ sections: [{ cards: [{ id: "a", qty: 1, finish: "gold" }] }] }),
    doc({ sections: [{ cards: [{ id: "a", qty: 1, price: -1 }] }] })]) {
    assert.equal((await post(e, bad)).status, 422);
  }
  assert.equal(e.SHARES.m.size, 0);
});

test("unknown fields are dropped before storing", async () => {
  const e = env();
  const { id } = await (await post(e, doc({ secret: "x", sections: [{ cards: [{ id: "a", qty: 2, notes: "mine", purchase_price: 5 }] }] }))).json();
  const stored = JSON.parse(e.SHARES.m.get(id)).doc;
  assert.equal(stored.secret, undefined);
  assert.deepEqual(stored.sections[0].cards[0], { id: "a", name: "", set: "", cn: "", qty: 2 });
});

test("too big a body is 413 and the rate limit is 429", async () => {
  const e = env();
  const big = doc({ note: "x".repeat(3 * 1024 * 1024) });
  assert.equal((await post(e, big)).status, 413);
  const limited = env({ RATE: { limit: async () => ({ success: false }) } });
  assert.equal((await post(limited, doc())).status, 429);
});

test("too many lines are refused", async () => {
  const cards = Array.from({ length: 20001 }, (_, i) => ({ id: "a" + i, qty: 1 }));
  assert.equal((await post(env(), doc({ sections: [{ cards }] }))).status, 422);
});

test("the cash of a trade is kept, for a trade only", async () => {
  const e = env();
  const tradeDoc = doc({ kind: "trade", meta: { cash: -5.557, other: "x" } });
  const { id } = await (await post(e, tradeDoc)).json();
  assert.deepEqual(JSON.parse(e.SHARES.m.get(id)).doc.meta, { cash: -5.56 });
  const other = await (await post(e, doc({ kind: "deck", meta: { cash: 3 } }))).json();
  assert.equal(JSON.parse(e.SHARES.m.get(other.id)).doc.meta, undefined);
});

test("PUT replaces the document under the same id, needs the token and renews the time", async () => {
  const e = env();
  const { id, delete_token } = await (await post(e, doc())).json();
  const put = (token, body = doc({ title: "New" }), headers = { "Content-Type": "application/json" }) =>
    handle(new Request(`https://w.example/api/share/${id}`, { method: "PUT", headers: { ...headers, ...(token ? { "X-Delete-Token": token } : {}) }, body: JSON.stringify(body) }), e);
  assert.equal((await put()).status, 403);
  assert.equal((await put("0".repeat(48))).status, 403);
  assert.equal((await put(delete_token, doc(), { "Content-Type": "text/plain" })).status, 415);
  assert.equal((await put(delete_token, doc({ kind: "x" }))).status, 422);
  const r = await put(delete_token);
  assert.equal(r.status, 200);
  assert.equal((await r.json()).id, id);
  assert.equal(JSON.parse(e.SHARES.m.get(id)).doc.title, "New");
  assert.equal(e.SHARES.puts.at(-1).expirationTtl, 30 * 86400);
  const del = await handle(new Request(`https://w.example/api/share/${id}`, { method: "DELETE", headers: { "X-Delete-Token": delete_token } }), e);
  assert.equal(del.status, 200);  // the token still works after an update
  assert.equal((await handle(new Request(`https://w.example/api/share/${id}`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Delete-Token": delete_token }, body: JSON.stringify(doc()) }), e)).status, 404);
});

test("type, mana value, colours and rarity are kept when valid and dropped when not", async () => {
  const e = env();
  const good = { id: "a", qty: 1, ty: "Instant", mv: 2, co: "WU", ra: "rare" };
  const bad = { id: "b", qty: 1, ty: "x".repeat(200), mv: -1, co: "Q!", ra: "godly" };
  const { id } = await (await post(e, doc({ sections: [{ cards: [good, bad] }] }))).json();
  const [g, b] = JSON.parse(e.SHARES.m.get(id)).doc.sections[0].cards;
  assert.deepEqual([g.ty, g.mv, g.co, g.ra], ["Instant", 2, "WU", "rare"]);
  assert.deepEqual([b.ty.length, b.mv, b.co, b.ra], [80, undefined, undefined, undefined]);
});

test("the /s/<id> page has the preview tags of that list, escaped, and sends people to the viewer", async () => {
  const e = env({ VIEWER_URL: "https://v.example/app/" });
  const tricky = doc({ title: `Tymna "the" <script>alert(1)</script> & co`, note: "bring <b>sleeves</b>", meta: { format: "commander" },
    sections: [{ name: "Commander", cards: [{ id: "4f152dd9-2b35-45b2-90fe-8c71d0634226", qty: 1, price: 2.5 }, { id: "b", qty: 3, price: 1 }] }], prices: true });
  const { id } = await (await post(e, tricky)).json();
  const r = await handle(new Request(`https://w.example/s/${id}`), e);
  const html = await r.text();
  assert.equal(r.status, 200);
  assert.match(r.headers.get("Content-Type"), /text\/html/);
  assert.ok(!html.includes("<script>") && !html.includes("<b>"), "nothing from the document is left unescaped");
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(html.includes('og:image" content="https://cards.scryfall.io/art_crop/front/4/f/4f152dd9-2b35-45b2-90fe-8c71d0634226.jpg"'));
  assert.ok(html.includes("Deck · 4 cards · commander · about 5.50 EUR"));
  assert.ok(html.includes(`url=https://v.example/app/?id=${id}`));
  assert.match(r.headers.get("Content-Security-Policy"), /default-src 'none'/);
  const head = await handle(new Request(`https://w.example/s/${id}`, { method: "HEAD" }), e);
  assert.equal(head.status, 200);
  assert.equal(await head.text(), "");
});

test("an unknown or malformed /s/ page is a generic preview with a 404, never an error page of the document", async () => {
  const e = env();
  const r = await handle(new Request("https://w.example/s/AAAAAAAAAAAA"), e);
  assert.equal(r.status, 404);
  const html = await r.text();
  assert.ok(html.includes("og:title") && html.includes("og.png"));
  assert.equal((await handle(new Request("https://w.example/s/short"), e)).status, 404);
  assert.equal((await handle(new Request("https://w.example/s/AAAAAAAAAAAA/x"), e)).status, 404);
});
