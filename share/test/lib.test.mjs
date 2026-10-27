import assert from "node:assert/strict";
import test from "node:test";
import { apiImageUrl, available, groupLines, imageUrl, isTrade, sortLines, toText, totals, tradeSides, typeOf } from "../site/lib.js";

const doc = {
  sections: [
    { name: "Commander", cards: [{ id: "a", name: "Tymna", set: "CMD", cn: "12", qty: 1, price: 0.5 }] },
    { name: "Main", cards: [{ id: "b", name: "Sol Ring", set: "C21", cn: "263", qty: 2, finish: "foil", price: 3 }, { id: "c", name: "Island", qty: 4 }] },
    { name: "Empty", cards: [] },
  ],
};

test("totals count cards and value per section", () => {
  const t = totals(doc);
  assert.deepEqual([t.cards, t.lines, t.value], [7, 3, 6.5]);
  assert.deepEqual(t.sections.map((s) => [s.name, s.cards, s.value]), [["Commander", 1, 0.5], ["Main", 6, 6], ["Empty", 0, 0]]);
});

test("toText writes a decklist other tools read and skips empty sections", () => {
  assert.equal(toText(doc), "Commander\n1 Tymna (CMD) 12\n\nMain\n2 Sol Ring (C21) 263 *F*\n4 Island\n");
});

test("imageUrl uses Scryfall's image server for card ids and the API only for anything else", () => {
  assert.equal(imageUrl("4f152dd9-2b35-45b2-90fe-8c71d0634226"), "https://cards.scryfall.io/normal/front/4/f/4f152dd9-2b35-45b2-90fe-8c71d0634226.jpg");
  assert.equal(imageUrl("a/b?c"), "https://api.scryfall.com/cards/a%2Fb%3Fc?format=image&version=normal");
  assert.equal(apiImageUrl("x y"), "https://api.scryfall.com/cards/x%20y?format=image&version=normal");
});

const rich = {
  sections: [{ name: "Cards", cards: [
    { id: "a", name: "Sol Ring", qty: 1, ty: "Artifact", mv: 1, co: "C", ra: "uncommon", price: 2, set: "C21", cn: "263" },
    { id: "b", name: "Tymna", qty: 1, ty: "Legendary Creature — Human Cleric", mv: 3, co: "WB", ra: "rare", price: 0.5, set: "CMD", cn: "12" },
    { id: "c", name: "Island", qty: 4, ty: "Basic Land — Island", mv: 0, co: "C", ra: "common", set: "C21", cn: "300" },
    { id: "d", name: "Swords to Plowshares", qty: 1, ty: "Instant", mv: 1, co: "W", ra: "uncommon", price: 3, set: "CMD", cn: "5" },
  ] }],
};

test("typeOf picks the first type of the usual order", () => {
  assert.equal(typeOf("Artifact Creature — Golem"), "Creature");
  assert.equal(typeOf("Basic Land — Island"), "Land");
  assert.equal(typeOf(undefined), "Other");
});

test("groups follow the usual order and sorts are stable on the name", () => {
  const names = (gs) => gs.map((g) => [g.name, g.cards.map((c) => c.name)]);
  assert.deepEqual(names(groupLines(rich, "type")), [["Creature", ["Tymna"]], ["Instant", ["Swords to Plowshares"]], ["Artifact", ["Sol Ring"]], ["Land", ["Island"]]]);
  assert.deepEqual(groupLines(rich, "colour").map((g) => g.name), ["White", "Multicolor", "Colorless"]);
  assert.deepEqual(groupLines(rich, "mv").map((g) => g.name), ["0", "1", "3"]);
  assert.deepEqual(groupLines(rich, "rarity").map((g) => g.name), ["Rare", "Uncommon", "Common"]);
  assert.deepEqual(groupLines(rich, "none")[0].cards.map((c) => c.name), ["Island", "Sol Ring", "Swords to Plowshares", "Tymna"]);
  assert.deepEqual(groupLines(rich, "sections", "price")[0].cards.map((c) => c.name), ["Swords to Plowshares", "Sol Ring", "Tymna", "Island"]);  // dearest first, no price last
  assert.deepEqual(sortLines(rich.sections[0].cards, "mv").map((c) => c.name), ["Island", "Sol Ring", "Swords to Plowshares", "Tymna"]);
  assert.deepEqual(sortLines(rich.sections[0].cards, "qty")[0].name, "Island");
});

test("a link made before type, colour and mana value existed offers only what it has", () => {
  const old = { sections: [{ name: "Main", cards: [{ id: "a", name: "A", qty: 1 }] }] };
  assert.deepEqual(available(old), { type: false, colour: false, mv: false, rarity: false, price: false });
  assert.equal(available(rich).type, true);
  assert.deepEqual(groupLines(old, "type").map((g) => g.name), ["Other"]);
});

test("a trade is shown as its two sides, with what each is worth", () => {
  const trade = { kind: "trade", sections: [
    { name: "Giving", cards: [{ id: "a", name: "Sol Ring", qty: 2, price: 1.5 }] },
    { name: "Getting", cards: [{ id: "b", name: "Island", qty: 1, price: 0.25 }, { id: "c", name: "Swamp", qty: 3 }] },
  ] };
  assert.equal(isTrade(trade), true);
  assert.equal(isTrade({ ...trade, kind: "deck" }), false);
  assert.equal(isTrade({ kind: "trade", sections: [{ name: "Other", cards: [] }] }), false);
  const s = tradeSides(trade);
  assert.deepEqual([s.out.count, s.out.value, s.in.count, s.in.value], [2, 3, 4, 0.25]);
  assert.deepEqual(tradeSides({ kind: "trade", sections: [trade.sections[1]] }).out, { cards: [], count: 0, value: 0 });  // a side with nothing is not in the document
});
