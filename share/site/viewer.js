// Scrybinder share viewer: shows a share document fetched from the share service (?id=) or opened from a file.
// Everything from the document is written with textContent / attributes, never as HTML.
import { SHARE_API } from "./config.js";
import { eur, imageUrl, totals, toText } from "./lib.js";

const $ = (id) => document.getElementById(id);
let current = null;

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

function tile(c, prices) {
  const img = el("img", { alt: c.name || "card", loading: "lazy", decoding: "async", src: imageUrl(c.id) });
  img.addEventListener("error", () => { img.replaceWith(el("div", { class: "noimg", text: c.name || c.id })); }, { once: true });
  const tags = el("div", { class: "tags" }, el("span", { class: "qty", text: `×${c.qty}` }));
  if (c.finish) tags.append(el("span", { class: "tag foil", text: c.finish === "etched" ? "Etched" : "Foil" }));
  if (c.cond) tags.append(el("span", { class: "tag", text: c.cond }));
  const meta = [c.name, [c.set, c.cn].filter(Boolean).join(" #")].filter(Boolean).join(" · ");
  const li = el("li", { class: "card", title: meta }, img, tags);
  const cap = el("div", { class: "cap" }, el("span", { class: "nm", text: c.name || c.id }));
  if (c.set) cap.append(el("span", { class: "ed", text: `${c.set} ${c.cn || ""}` }));
  if (prices && c.price != null) cap.append(el("span", { class: "pr", text: eur(c.price * c.qty) }));
  if (c.loc) cap.append(el("span", { class: "ed", text: c.loc }));
  li.append(cap);
  return li;
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
  const root = $("sections");
  root.replaceChildren();
  doc.sections.forEach((s, i) => {
    if (!s.cards.length) return;
    const st = t.sections[i];
    root.append(el("section", {}, el("h2", {}, el("span", { text: s.name }), el("small", { text: `${st.cards}${doc.prices ? ` · ${eur(st.value)}` : ""}` })),
      el("ul", { class: "grid" }, ...s.cards.map((c) => tile(c, doc.prices)))));
  });
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
