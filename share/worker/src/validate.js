// Checks a share document and returns it cleaned (unknown fields dropped). Mirrors `parse` in scrybinder/share.py.
export const FORMAT = "scrybinder-share";
export const VERSION = 1;
export const MAX_LINES = 20000;
export const MAX_BYTES = 2 * 1024 * 1024;
const KINDS = ["deck", "list", "trade", "collection"];
const FINISHES = ["nonfoil", "foil", "etched"];
const CONDITIONS = ["NM", "LP", "MP", "HP", "DMG"];

const text = (v, what, limit = 200) => {
  if (v !== undefined && v !== null && typeof v !== "string") throw new Error(`${what}: text`);
  return (v || "").trim().slice(0, limit);
};

export function validate(doc) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc) || doc.format !== FORMAT) throw new Error("this is not a Scrybinder share document");
  if (doc.v !== VERSION) throw new Error("unsupported version");
  if (!KINDS.includes(doc.kind)) throw new Error("unknown kind");
  if (!Array.isArray(doc.sections) || doc.sections.length < 1 || doc.sections.length > 20) throw new Error("sections: 1 to 20");
  let n = 0;
  const sections = doc.sections.map((s) => {
    if (!s || typeof s !== "object" || !Array.isArray(s.cards)) throw new Error("a section needs cards");
    const cards = s.cards.map((c) => {
      if (!c || typeof c !== "object" || typeof c.id !== "string" || c.id.length < 1 || c.id.length > 64) throw new Error("a card needs an id");
      if (!Number.isInteger(c.qty) || c.qty < 1 || c.qty > 9999) throw new Error("qty: 1 to 9999");
      const finish = c.finish ?? "nonfoil";
      if (!FINISHES.includes(finish)) throw new Error("finish: nonfoil, foil or etched");
      const cond = c.cond ?? "NM";
      if (!CONDITIONS.includes(cond)) throw new Error("condition: NM, LP, MP, HP or DMG");
      const card = { id: c.id, name: text(c.name, "name"), set: text(c.set, "set", 10), cn: text(c.cn, "cn", 12), qty: c.qty };
      if (finish !== "nonfoil") card.finish = finish;
      if (cond !== "NM") card.cond = cond;
      if (c.lang && c.lang !== "en") card.lang = text(c.lang, "lang", 6);
      if (c.loc) card.loc = text(c.loc, "loc");
      if (c.ty) card.ty = text(c.ty, "ty", 80);
      if (typeof c.mv === "number" && Number.isFinite(c.mv) && c.mv >= 0 && c.mv <= 1000) card.mv = c.mv;
      if (typeof c.co === "string" && /^[WUBRGC]{1,5}$/.test(c.co)) card.co = c.co;
      if (["common", "uncommon", "rare", "mythic", "special", "bonus"].includes(c.ra)) card.ra = c.ra;
      if (c.price !== undefined && c.price !== null) {
        if (typeof c.price !== "number" || !Number.isFinite(c.price) || c.price < 0) throw new Error("price: a number");
        card.price = Math.round(c.price * 100) / 100;
      }
      return card;
    });
    n += cards.length;
    if (n > MAX_LINES) throw new Error(`too many cards (the limit is ${MAX_LINES} lines)`);
    return { name: text(s.name, "section") || "Cards", cards };
  });
  const out = { format: FORMAT, v: VERSION, kind: doc.kind, title: text(doc.title, "title") || doc.kind, created: text(doc.created, "created", 10), prices: !!doc.prices, sections };
  if (doc.note) out.note = text(doc.note, "note", 1000);
  if (doc.meta && typeof doc.meta === "object" && typeof doc.meta.format === "string") out.meta = { format: doc.meta.format.slice(0, 20) };
  if (doc.kind === "trade" && doc.meta && typeof doc.meta.cash === "number" && Number.isFinite(doc.meta.cash)) out.meta = { ...out.meta, cash: Math.round(doc.meta.cash * 100) / 100 };
  return out;
}
