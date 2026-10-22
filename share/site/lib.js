// Pure helpers of the viewer (no DOM), so they can be tested with `node --test`.
export const eur = (v) => (v == null ? "" : v.toLocaleString("en", { style: "currency", currency: "EUR" }));

// Card images come straight from Scryfall's image server (no request limit). The same image through the API is only the fallback:
// the API limits how many requests a page may make, which is what stopped big lists from showing their pictures.
const safe = (id) => encodeURIComponent(id);
export const imageUrl = (id) => (/^[0-9a-f]{8}-/i.test(id) ? `https://cards.scryfall.io/normal/front/${id[0]}/${id[1]}/${id}.jpg` : apiImageUrl(id));
export const apiImageUrl = (id) => `https://api.scryfall.com/cards/${safe(id)}?format=image&version=normal`;

export function totals(doc) {
  const out = { cards: 0, lines: 0, value: 0, sections: [] };
  for (const s of doc.sections) {
    const t = { name: s.name, cards: 0, value: 0 };
    for (const c of s.cards) {
      t.cards += c.qty;
      t.value += (c.price || 0) * c.qty;
    }
    out.cards += t.cards;
    out.lines += s.cards.length;
    out.value += t.value;
    out.sections.push(t);
  }
  return out;
}

// "2 Sol Ring (C21) 263 *F*": the format Moxfield, Archidekt and Scrybinder read.
export function toText(doc) {
  const line = (c) => `${c.qty} ${c.name || c.id}${c.set ? ` (${c.set}) ${c.cn || ""}`.trimEnd() : ""}${c.finish === "foil" ? " *F*" : c.finish === "etched" ? " *E*" : ""}`;
  return doc.sections.filter((s) => s.cards.length).map((s) => `${s.name}\n${s.cards.map(line).join("\n")}`).join("\n\n") + "\n";
}

// --- grouping and sorting (what a card line carries: ty type line, mv mana value, co colours, ra rarity; all optional) ---

export const TYPES = ["Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"];
const COLOURS = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };
const COLOUR_ORDER = ["White", "Blue", "Black", "Red", "Green", "Multicolor", "Colorless"];
const RARITY_ORDER = ["mythic", "rare", "uncommon", "common"];

export const typeOf = (ty) => TYPES.find((t) => (ty || "").includes(t)) || "Other";
export const colourOf = (co) => (co == null ? "Unknown" : co === "C" ? "Colorless" : co.length > 1 ? "Multicolor" : COLOURS[co] || "Unknown");
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/** Which groupings and sorts the data supports: a link made by an older version has no type, colour or mana value to use. */
export function available(doc) {
  const lines = doc.sections.flatMap((s) => s.cards);
  const has = (k) => lines.some((c) => c[k] !== undefined);
  return { type: has("ty"), colour: has("co"), mv: has("mv"), rarity: has("ra"), price: lines.some((c) => c.price != null) };
}

const KEYS = {
  type: (c) => typeOf(c.ty),
  colour: (c) => colourOf(c.co),
  mv: (c) => (c.mv == null ? "Unknown" : c.mv >= 7 ? "7+" : String(Math.floor(c.mv))),
  rarity: (c) => (c.ra ? cap(c.ra) : "Unknown"),
  set: (c) => c.set || "Unknown",
};
const ORDERS = {
  type: [...TYPES, "Other"],
  colour: [...COLOUR_ORDER, "Unknown"],
  mv: ["0", "1", "2", "3", "4", "5", "6", "7+", "Unknown"],
  rarity: [...RARITY_ORDER.map(cap), "Unknown"],
};

export function sortLines(lines, by) {
  const name = (a, b) => (a.name || a.id).localeCompare(b.name || b.id) || (a.set || "").localeCompare(b.set || "");
  const num = (v, dir) => (a, b) => (dir * ((v(a) ?? -1) - (v(b) ?? -1))) || name(a, b);
  const cmp = { name, mv: num((c) => c.mv, 1), price: num((c) => (c.price == null ? null : c.price * c.qty), -1), qty: num((c) => c.qty, -1),
    set: (a, b) => (a.set || "").localeCompare(b.set || "") || String(a.cn || "").localeCompare(String(b.cn || ""), undefined, { numeric: true }) || name(a, b) }[by] || name;
  return [...lines].sort(cmp);
}

/** The sections to show: the ones of the document, or the lines regrouped by type, colour, mana value, rarity or set (or one list). */
export function groupLines(doc, by, sortBy = "name") {
  if (by === "sections" || !KEYS[by] && by !== "none") return doc.sections.filter((s) => s.cards.length).map((s) => ({ name: s.name, cards: sortLines(s.cards, sortBy) }));
  const all = doc.sections.flatMap((s) => s.cards);
  if (by === "none") return [{ name: "All cards", cards: sortLines(all, sortBy) }];
  const groups = new Map();
  for (const c of all) {
    const k = KEYS[by](c);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  }
  const order = ORDERS[by];
  const rank = (k) => (order ? (order.indexOf(k) < 0 ? order.length : order.indexOf(k)) : 0);
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])).map(([name, cards]) => ({ name, cards: sortLines(cards, sortBy) }));
}
