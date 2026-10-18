// Run: npx tsx check/extras.check.ts  (from ui/)
import { addCounter, addNamed, move, newGame, peek, pushHistory, reorderTop, token } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string): DeckCard => ({ name, quantity, type_line, board: "main", image_id: null, color_identity: [] } as unknown as DeckCard);
const cards = [mk("Forest", 30, "Basic Land — Forest"), mk("Bear", 30, "Creature")];
const all = (g: ReturnType<typeof newGame>) => [g.library, g.hand, g.battlefield, g.graveyard, g.exile, g.command].flat();

// counters: plus can go negative, generic never below 0, only the battlefield card changes, they are lost on leaving
let g = newGame(cards, false);
const inHand = g.hand[0].uid, bf = g.hand[1].uid;
g = move(g, bf, "battlefield");
g = addCounter(addCounter(g, bf, "plus", 1), bf, "plus", 1);
assert.equal(g.battlefield[0].plus, 2);
assert.equal(addCounter(g, bf, "plus", -5).battlefield[0].plus, -3);
assert.equal(addCounter(g, bf, "generic", -5).battlefield[0].counters, 0);
assert.equal(addCounter(g, bf, "generic", 3).battlefield[0].counters, 3);
assert.equal(addCounter(g, inHand, "plus", 1).hand.find((c) => c.uid === inHand)!.plus, undefined);
assert.equal(move(g, bf, "hand").hand.find((c) => c.uid === bf)!.plus, undefined);

// tokens: unique uid, vanish when they leave the battlefield, tapping keeps them
const before = all(g).length;
let t = token(g, { name: "Soldier", pt: "1/1" });
const tk = t.battlefield[t.battlefield.length - 1];
assert.equal(t.battlefield.length, g.battlefield.length + 1);
assert.ok(tk.token && tk.name === "Soldier (1/1)" && !all(g).some((c) => c.uid === tk.uid));
assert.equal(all(move(t, tk.uid, "graveyard")).length, before);   // gone from every zone, nothing added to the graveyard
assert.equal(move(t, tk.uid, "graveyard").graveyard.length, 0);
assert.equal(token(t, { name: "Soldier" }).battlefield.at(-1)!.uid !== tk.uid, true);

// peek and reorderTop
const lib = g.library.map((c) => c.uid);
assert.deepEqual(peek(g, 3).map((c) => c.uid), lib.slice(0, 3));
assert.deepEqual(g.library.map((c) => c.uid), lib);                       // peek changes nothing
assert.equal(peek(g, 0).length, 0);
const r = reorderTop(g, [lib[1]], [lib[0]]);
assert.equal(r.library.length, lib.length);
assert.deepEqual(r.library.map((c) => c.uid).slice(0, 2), [lib[1], lib[2]]);
assert.equal(r.library[r.library.length - 1].uid, lib[0]);
assert.deepEqual([...r.library.map((c) => c.uid)].sort((a, b) => a - b), [...lib].sort((a, b) => a - b));  // same cards
assert.equal(r.hand, g.hand);
assert.equal(reorderTop(g, [9999], []).library.length, lib.length);        // an unknown uid is ignored

// history is bounded
let h: number[] = [];
for (let i = 1; i <= 60; i++) h = pushHistory(h, i, 50);
assert.deepEqual([h.length, h[0], h[49]], [50, 11, 60]);
// named counters: your own names, 0 removes them, only on the battlefield, lost when the card leaves
let n = addNamed(addNamed(g, bf, " Charge ", 2), bf, "Loyalty", 3);
assert.deepEqual(n.battlefield[0].named, { Charge: 2, Loyalty: 3 });
n = addNamed(n, bf, "Charge", -1);
assert.equal(n.battlefield[0].named!.Charge, 1);
n = addNamed(n, bf, "Charge", -9);
assert.deepEqual(n.battlefield[0].named, { Loyalty: 3 });
assert.equal(addNamed(g, bf, "  ", 1), g);                                    // no name: nothing happens
assert.equal(addNamed(g, inHand, "Charge", 1).hand.find((c) => c.uid === inHand)!.named, undefined);
assert.equal(move(n, bf, "graveyard").graveyard[0].named, undefined);
console.log("extras ok");
