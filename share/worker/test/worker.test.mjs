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
