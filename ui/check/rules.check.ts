// Run: npx tsx check/rules.check.ts  (from ui/)
import { addCounter, attach, keep, move, newGame, nextPhase, settle, token } from "../src/goldfish";
import type { Game } from "../src/goldfish";
import { warnings } from "../src/rules";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string, toughness?: string): DeckCard => ({ name, quantity, type_line, toughness, board: "main", image_id: null } as unknown as DeckCard);
const cards = [mk("Tymna", 2, "Legendary Creature — Human", "2"), mk("Rograkh", 1, "Legendary Creature — Kobold", "1"), mk("Bear", 2, "Creature — Bear", "2"),
  mk("Star", 1, "Creature — Elemental", "1+*"), mk("Unknown", 1, "Creature — Mystery"), mk("Aura", 2, "Enchantment — Aura"), mk("Rock", 1, "Artifact — Equipment"), mk("Forest", 40, "Basic Land — Forest")];

let g: Game = keep(newGame(cards, false));
const all = [...g.hand, ...g.library];
const ids = (n: string) => all.filter((c) => c.name === n).map((c) => c.uid);
const put = (x: Game, ...us: number[]) => settle(us.reduce((y, u) => move(y, u, "battlefield"), x));
const rules = (x: Game) => warnings(x).map((w) => w.rule);

assert.deepEqual(rules(g), []);                                       // nothing on the table, a seven-card hand
assert.deepEqual(warnings({ ...g, phase: "mulligan" }), []);          // not while the opening hand is being chosen

// 704.5j: the same legendary twice; not once, not two different legends, not a non-legendary pair
const [t1, t2] = ids("Tymna");
assert.deepEqual(rules(put(g, t1)), []);
assert.deepEqual(rules(put(g, t1, ids("Rograkh")[0])), []);
assert.deepEqual(rules(put(g, ...ids("Bear"))), []);
const legend = warnings(put(g, t1, t2));
assert.equal(legend.length, 1); assert.equal(legend[0].rule, "704.5j"); assert.deepEqual(legend[0].uids, [t1, t2]); assert.equal(legend[0].key, `704.5j:${[t1, t2].sort((a, b) => a - b).join(",")}`);
assert.match(legend[0].text, /2 × Tymna/);

// 704.5f: 1/1 with -1/-1 is at 0; a 2/2 needs two; not at 1; not for * or an unknown toughness; tokens use their P/T
const [bear] = ids("Bear");
let b = put(g, bear);
assert.deepEqual(rules(b), []);
b = addCounter(b, bear, "plus", -1); assert.deepEqual(rules(b), []);
b = addCounter(b, bear, "plus", -1); assert.deepEqual(rules(b), ["704.5f"]);
b = addCounter(b, bear, "plus", 1); assert.deepEqual(rules(b), []);   // the counter came off: the warning goes
assert.deepEqual(rules(addCounter(put(g, ids("Star")[0]), ids("Star")[0], "plus", -5)), []);
assert.deepEqual(rules(addCounter(put(g, ids("Unknown")[0]), ids("Unknown")[0], "plus", -5)), []);
assert.deepEqual(rules(token(g, { name: "Soldier", pt: "1/0" })), ["704.5f"]);
assert.deepEqual(rules(token(g, { name: "Soldier", pt: "1/1" })), []);
assert.deepEqual(rules(token(g, { name: "Treasure" })), []);          // no P/T: not a creature we know of
const land = ids("Forest")[0];
assert.deepEqual(rules(addCounter(put(g, land), land, "plus", -5)), []);   // not a creature

// 704.5m: an Aura without a host (the Equipment is fine), gone once attached, back if the host leaves
const [aura] = ids("Aura"), rock = ids("Rock")[0];
assert.deepEqual(rules(put(g, rock)), []);
let a = put(g, aura, bear);
assert.deepEqual(rules(a), ["704.5m"]);
assert.deepEqual(rules(attach(a, aura, bear)), []);
assert.deepEqual(rules(move(attach(a, aura, bear), bear, "graveyard")), ["704.5m"]);

// 514.1: eight cards at the end step; not with seven, not at another step
let h = g;
h = { ...h, step: "end" }; assert.deepEqual(rules(h), []);
h = { ...h, hand: [...h.hand, h.library[0]] }; assert.deepEqual(rules(h), ["514.1"]);
assert.match(warnings(h)[0].text, /discard 1 to 7/); assert.deepEqual(warnings(h)[0].uids, []);
assert.deepEqual(rules({ ...h, step: "main2" }), []);
assert.deepEqual(rules(nextPhase(h)), []);                            // leaving the end step clears it

// the hand warning's key changes with the turn, so ignoring it once does not hide it for the rest of the game
assert.notEqual(warnings(h)[0].key, warnings({ ...h, turn: h.turn + 1 })[0].key);
// a back face does not make the card an Aura or a legend: only the front face counts
const odd = put(g, bear);
const turned = { ...odd, battlefield: odd.battlefield.map((c) => ({ ...c, type_line: "Creature — Bear // Legendary Enchantment — Aura" })) };
assert.deepEqual(rules(turned), []);

// all at once, in the order of the rules
const all4 = { ...put(g, t1, t2, aura), step: "end" as const, hand: [...g.hand, ...g.library.slice(0, 2)] };
assert.deepEqual(rules(all4), ["704.5j", "704.5m", "514.1"]);
console.log("rules ok");
