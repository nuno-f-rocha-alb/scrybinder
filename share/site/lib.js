// Pure helpers of the viewer (no DOM), so they can be tested with `node --test`.
export const eur = (v) => (v == null ? "" : v.toLocaleString("en", { style: "currency", currency: "EUR" }));

export const imageUrl = (id) => `https://api.scryfall.com/cards/${encodeURIComponent(id)}?format=image&version=normal`;

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
