// Scrybinder share viewer: shows a share document fetched from the share service (?id=) or opened from a file.
// Everything from the document is written with textContent / attributes, never as HTML.
import { SHARE_API } from "./config.js";
import { apiImageUrl, available, eur, groupLines, imageUrl, isTrade, totals, toText, tradeSides } from "./lib.js";

const $ = (id) => document.getElementById(id);
let current = null;
const KEY = "scrybinder.share.view";
const prefs = (() => { try { return { view: "grid", group: "sections", sort: "name", ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return { view: "grid", group: "sections", sort: "name" }; } })();
const savePrefs = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* no storage */ } };

const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  e.append(...kids);
  return e;
};

function message(text, isError = false) {
  const m = $("message");
  m.textContent = text;
  m.hidden = !text;
  m.className = isError ? "message error" : "message";
}

const finishTag = (c) => (c.finish ? el("span", { class: "tag foil", text: c.finish === "etched" ? "Etched" : "Foil" }) : null);

function tile(c, prices, compact) {
  const img = el("img", { alt: c.name || "card", loading: "lazy", decoding: "async", src: imageUrl(c.id) });
  let fallback = false;
  img.addEventListener("error", () => {
    if (!fallback && img.src !== apiImageUrl(c.id)) { fallback = true; img.src = apiImageUrl(c.id); return; }  // once through the API before giving up
    img.replaceWith(el("div", { class: "noimg", text: c.name || c.id }));
  });
  const tags = el("div", { class: "tags" }, el("span", { class: "qty", text: `×${c.qty}` }));
  const ft = finishTag(c);
  if (ft) tags.append(ft);
  if (c.cond) tags.append(el("span", { class: "tag", text: c.cond }));
  const meta = [c.name, [c.set, c.cn].filter(Boolean).join(" #"), c.ty].filter(Boolean).join(" · ");
  const li = el("li", { class: "card", title: meta }, img, tags);
  if (compact) return li;
  const cap = el("div", { class: "cap" }, el("span", { class: "nm", text: c.name || c.id }));
  if (c.set) cap.append(el("span", { class: "ed", text: `${c.set} ${c.cn || ""}` }));
  if (prices && c.price != null) cap.append(el("span", { class: "pr", text: eur(c.price * c.qty) }));
  if (c.loc) cap.append(el("span", { class: "ed", text: c.loc }));
  li.append(cap);
  return li;
}

function row(c, prices) {
  const li = el("li", { class: "row" }, el("span", { class: "q", text: `${c.qty}×` }), el("span", { class: "n", text: c.name || c.id }));
  const ft = finishTag(c);
  if (ft) li.append(ft);
  li.append(el("span", { class: "e", text: [c.set, c.cn].filter(Boolean).join(" ") }), el("span", { class: "t", text: c.ty || "" }));
  if (prices) li.append(el("span", { class: "p", text: c.price != null ? eur(c.price * c.qty) : "" }));
  return li;
}

function thumb(c) {
  const img = el("img", { alt: "", loading: "lazy", decoding: "async", src: imageUrl(c.id) });
  let fallback = false;
  img.addEventListener("error", () => {
    if (!fallback && img.src !== apiImageUrl(c.id)) { fallback = true; img.src = apiImageUrl(c.id); return; }
    img.replaceWith(el("div", { class: "noimg" }));
  });
  return img;
}

function tradeLine(c, prices) {
  const sub = [[c.set, c.cn].filter(Boolean).join(" #"), c.cond].filter(Boolean).join(" · ");
  const info = el("div", { class: "ti" }, el("div", { class: "tn" }, el("span", { text: c.name || c.id }), ...(finishTag(c) ? [finishTag(c)] : [])), el("div", { class: "ts", text: sub }));
  const li = el("li", { class: "tline" }, el("div", { class: "tt" }, thumb(c)), info, el("div", { class: "tq", text: `×${c.qty}` }));
  if (prices && c.price != null) li.append(el("div", { class: "tp" }, el("b", { text: eur(c.price * c.qty) }), ...(c.qty > 1 ? [el("small", { text: `${eur(c.price)} each` })] : [])));
  return li;
}

// A trade looks like the trade page of the app: what goes out on one side, what comes in on the other, then the balance.
function trade() {
  const doc = current, s = tradeSides(doc);
  const side = (title, hint, x) => el("section", { class: "side" },
    el("h2", {}, el("span", { text: title }), el("small", { text: `${x.count}${doc.prices ? ` · ${eur(x.value)}` : ""}` })),
    el("p", { class: "hint", text: hint }),
    x.cards.length ? el("ul", { class: "tlines" }, ...x.cards.map((c) => tradeLine(c, doc.prices))) : el("p", { class: "empty", text: "Nothing" }));
  const root = $("sections");
  root.append(el("div", { class: "trade" }, side("Going out", "What the sender gives", s.out), side("Coming in", "What the sender gets", s.in)));
  if (doc.prices) {
    const d = s.in.value - s.out.value;
    root.append(el("p", { class: "balance" }, el("span", { text: `Going out ${eur(s.out.value)}` }), el("span", { text: `Coming in ${eur(s.in.value)}` }),
      el("b", { text: Math.abs(d) < 0.005 ? "Even" : d > 0 ? `The sender gets ${eur(d)} more` : `The sender gives ${eur(-d)} more` })));
  }
}

function sections() {
  const doc = current;
  const root = $("sections");
  root.replaceChildren();
  if (isTrade(doc)) { trade(); return; }
  for (const g of groupLines(doc, prefs.group, prefs.sort)) {
    const n = g.cards.reduce((a, c) => a + c.qty, 0), v = g.cards.reduce((a, c) => a + (c.price || 0) * c.qty, 0);
    const list = prefs.view === "list" ? el("ul", { class: "rows" }, ...g.cards.map((c) => row(c, doc.prices)))
      : el("ul", { class: prefs.view === "compact" ? "grid small" : "grid" }, ...g.cards.map((c) => tile(c, doc.prices, prefs.view === "compact")));
    root.append(el("section", {}, el("h2", {}, el("span", { text: g.name }), el("small", { text: `${n}${doc.prices ? ` · ${eur(v)}` : ""}` })), list));
  }
}

const OPTIONS = {
  group: [["sections", "As shared"], ["type", "Type"], ["colour", "Colour"], ["mv", "Mana value"], ["rarity", "Rarity"], ["set", "Set"], ["none", "None"]],
  sort: [["name", "Name"], ["mv", "Mana value"], ["price", "Price"], ["qty", "Quantity"], ["set", "Set"]],
};

function controls() {
  const doc = current, a = available(doc);
  if (isTrade(doc)) { $("controls").hidden = true; return; }  // a trade is always shown as its two sides
  const ok = { type: a.type, colour: a.colour, mv: a.mv, rarity: a.rarity, price: a.price };
  const fill = (id, list, kind) => {
    const s = $(id);
    s.replaceChildren(...list.map(([v, l]) => { const o = el("option", { value: v, text: l }); if ((v in ok && !ok[v]) || (kind === "sort" && v === "price" && !ok.price)) o.disabled = true; return o; }));
    if (s.querySelector(`option[value="${prefs[kind]}"]:not(:disabled)`) === null) prefs[kind] = list[0][0];
    s.value = prefs[kind];
  };
  fill("group", OPTIONS.group, "group");
  fill("sort", OPTIONS.sort, "sort");
  for (const b of document.querySelectorAll("#view button")) b.setAttribute("aria-pressed", String(b.dataset.v === prefs.view));
  $("controls").hidden = false;
}

function render(doc) {
  current = doc;
  const t = totals(doc);
  document.title = `${doc.title} · Scrybinder share`;
  $("title").textContent = doc.title;
  const kinds = { deck: "Deck", list: "List", trade: "Trade", collection: "Collection" };
  $("kind").textContent = kinds[doc.kind] || doc.kind;
  $("kind").hidden = false;
  const chips = [[`${t.cards}`, t.cards === 1 ? "card" : "cards"], [`${t.lines}`, "lines"]];
  if (doc.meta?.format) chips.push(["", doc.meta.format]);
  if (doc.prices) chips.push([eur(t.value), "at Cardmarket prices"]);
  const cash = doc.meta?.cash;
  if (typeof cash === "number") chips.push(cash === 0 ? ["", "no cash"] : [eur(Math.abs(cash)), cash > 0 ? "cash paid to the sender" : "cash paid by the sender"]);
  if (doc.created) chips.push(["", doc.created]);
  $("chips").replaceChildren(...chips.map(([strong, text]) => el("li", {}, ...(strong ? [el("b", { text: strong }), ` ${text}`] : [text]))));
  $("note").textContent = doc.note || "";
  $("note").hidden = !doc.note;
  controls();
  sections();
  $("actions").hidden = false;
  $("open").hidden = true;
  message("");
}

async function load() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) return;
  if (!SHARE_API) { message("The share service is not configured for this viewer.", true); return; }
  message("Loading…");
  try {
    const r = await fetch(`${SHARE_API.replace(/\/$/, "")}/api/share/${encodeURIComponent(id)}`);
    if (r.status === 404) { message("This link has expired or was deleted. Ask the sender for a new one.", true); return; }
    if (!r.ok) throw new Error(String(r.status));
    render(await r.json());
  } catch {
    message("Could not load this link. Check your connection and try again.", true);
  }
}

function openFile(file) {
  if (!file) return;
  if (file.size > 3 * 1024 * 1024) { message("That file is too big to be a share file.", true); return; }
  file.text().then((t) => {
    const doc = JSON.parse(t);
    if (doc?.format !== "scrybinder-share" || !Array.isArray(doc.sections)) throw new Error();
    render(doc);
  }).catch(() => message("This is not a Scrybinder share file.", true));
}

for (const [id, kind] of [["group", "group"], ["sort", "sort"]]) $(id).addEventListener("change", (e) => { prefs[kind] = e.target.value; savePrefs(); sections(); });
for (const b of document.querySelectorAll("#view button")) b.addEventListener("click", () => { prefs.view = b.dataset.v; savePrefs(); controls(); sections(); });
$("file").addEventListener("change", (e) => openFile(e.target.files[0]));
for (const ev of ["dragover", "drop"]) document.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop") openFile(e.dataTransfer.files[0]); });
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(toText(current)); $("copy").textContent = "Copied"; }
  catch { $("copy").textContent = "Could not copy"; }
  setTimeout(() => { $("copy").textContent = "Copy as text"; }, 1800);
});
$("download").addEventListener("click", () => {
  const a = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(current)], { type: "application/json" })), download: `${current.title.replace(/[^\w.-]+/g, "_") || "share"}.scrybinder.json` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
load();
