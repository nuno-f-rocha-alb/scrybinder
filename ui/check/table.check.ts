// Run: npx tsx check/table.check.ts  (from ui/)
import { autoPlace, keep, move, newGame, placeCard, raise, settle, toggleTap } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string): DeckCard => ({ name, quantity, type_line, board: "main", image_id: null } as unknown as DeckCard);
const cards = [mk("Forest", 20, "Basic Land — Forest"), mk("Bear", 20, "Creature — Bear"), mk("Rock", 20, "Artifact")];
const box = { w: 0.1, h: 0.3 };

let g = keep(newGame(cards, false));
const byName = (n: string) => g.hand.find((c) => c.name === n)!.uid;
const [land, bear, rock] = [byName("Forest"), byName("Bear"), byName("Rock")];
for (const u of [land, bear, rock]) g = move(g, u, "battlefield");
assert.ok(g.battlefield.every((c) => c.x === undefined));            // moving gives no position by itself
g = settle(g, box);
const at = (u: number) => g.battlefield.find((c) => c.uid === u)!;
// rows: creature at the top, other permanents in the middle, land at the bottom (literal: (1 - h) * 0, 1/2, 1 = 0, 0.35, 0.7)
assert.equal(at(bear).y, 0); assert.equal(at(rock).y, 0.35); assert.ok(Math.abs(at(land).y! - 0.7) < 1e-9);
assert.equal(settle(g, box), g);                                      // nothing left to place: same object

// a second creature takes the next free slot of the row, never the same spot
const bear2 = g.hand.find((c) => c.name === "Bear")!.uid;
g = settle(move(g, bear2, "battlefield"), box);
assert.ok(Math.abs(at(bear2).x! - at(bear).x!) >= box.w / 2 && at(bear2).y === 0);

// placeCard clamps inside the table, puts the card on top and touches nothing else
const z0 = g.zTop;
const p = placeCard(g, rock, 2, -1, box);
const r = p.battlefield.find((c) => c.uid === rock)!;
assert.equal(r.x, 0.9); assert.equal(r.y, 0); assert.equal(r.z, z0 + 1); assert.equal(p.zTop, z0 + 1);
assert.deepEqual(p.battlefield.filter((c) => c.uid !== rock), g.battlefield.filter((c) => c.uid !== rock));
assert.equal(placeCard(g, 9999, 0.5, 0.5, box), g); assert.equal(placeCard(g, rock, NaN, 0.5, box), g);

// raise only bumps z; tapping keeps the position; leaving the table forgets it
const up = raise(p, bear).battlefield.find((c) => c.uid === bear)!;
assert.equal(up.z, p.zTop + 1); assert.equal(up.x, at(bear).x);
assert.equal(toggleTap(p, rock).battlefield.find((c) => c.uid === rock)!.x, 0.9);
const back = move(move(p, rock, "hand"), rock, "battlefield").battlefield.find((c) => c.uid === rock)!;
assert.equal(back.x, undefined);

// a full row stacks a little off instead of failing
let full = keep(newGame([mk("Bear", 60, "Creature")], false));
for (let i = 0; i < 7; i++) full = settle(move(full, full.hand[0].uid, "battlefield"), box);
assert.equal(full.battlefield.length, 7);
assert.ok(full.battlefield.every((c) => c.x! >= 0 && c.x! <= 0.9 && c.y === 0));
console.log("table ok");
