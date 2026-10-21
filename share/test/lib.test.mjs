import assert from "node:assert/strict";
import test from "node:test";
import { imageUrl, toText, totals } from "../site/lib.js";

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

test("imageUrl escapes the id", () => {
  assert.equal(imageUrl("a/b?c"), "https://api.scryfall.com/cards/a%2Fb%3Fc?format=image&version=normal");
});
