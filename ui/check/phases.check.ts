// Run: npx tsx check/phases.check.ts  (from ui/)
import { STEPS, bottomMany, keep, mulligan, move, newGame, nextPhase, toggleTap, untapAll } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string): DeckCard => ({ name, quantity, type_line, board: "main", image_id: null } as unknown as DeckCard);
const cards = [mk("Forest", 30, "Basic Land — Forest"), mk("Bear", 30, "Creature")];

// a kept hand starts the game at the upkeep of turn 1, with the seven cards and no draw yet
const first = keep(newGame(cards, false));
assert.equal(first.step, "upkeep"); assert.equal(first.turn, 1); assert.equal(first.hand.length, 7);
// turn 1: on the play in a two-player game the first draw draws nothing; on the draw, or in Commander (three or more players), it draws one
const at = (g0: typeof first, n: number) => { let x = g0; for (let i = 0; i < n; i++) x = nextPhase(x); return x; };
assert.equal(at(first, 1).step, "main1"); assert.equal(at(first, 1).hand.length, 7);   // the draw is taken on leaving upkeep, and the turn goes straight to main 1
assert.equal(at(keep(newGame(cards, false, false)), 1).hand.length, 8);
const cmd = [...cards, { name: "Boss", quantity: 1, type_line: "Legendary Creature", board: "commander", image_id: null } as unknown as DeckCard];
assert.equal(at(keep(newGame(cmd, true, true)), 1).hand.length, 8);
let g = at(first, 1);   // main1 of turn 1
assert.equal(g.step, "main1");

// the phases from main1 (untap and draw are not stops) come back to main1 one turn later: one card drawn, battlefield untapped
const played = g.hand[0].uid;
g = toggleTap(move(g, played, "battlefield"), played);
assert.ok(g.battlefield[0].tapped);
const walked: string[] = [];
let n = g;
for (let i = 0; i < STEPS.length; i++) { n = nextPhase(n); walked.push(n.step); }
assert.deepEqual(walked, ["combat", "main2", "end", "upkeep", "main1"]);
assert.equal(n.turn, 2); assert.equal(n.library.length, g.library.length - 1); assert.equal(n.hand.length, g.hand.length + 1);
assert.ok(!n.battlefield[0].tapped);
// everything untaps on the way into the new turn (turn 2, upkeep), the draw comes on leaving upkeep, nothing else moves
const atEnd = nextPhase(nextPhase(nextPhase(g)));
assert.equal(atEnd.step, "end"); assert.ok(atEnd.battlefield[0].tapped);
const atUpkeep = nextPhase(atEnd);
assert.equal(atUpkeep.turn, 2); assert.ok(!atUpkeep.battlefield[0].tapped); assert.equal(atUpkeep.hand.length, g.hand.length);
assert.equal(nextPhase(atUpkeep).hand.length, g.hand.length + 1);
// an empty library does not crash on draw
assert.equal(nextPhase({ ...atUpkeep, step: "upkeep", library: [] }).hand.length, g.hand.length);

// untapAll touches only the battlefield
assert.ok(!untapAll(g).battlefield[0].tapped);

// bottomMany: exactly toBottom cards, in order, then the game starts; anything else changes nothing
const h = keep(mulligan(mulligan(newGame(cards, false))));   // two mulligans: two cards to the bottom
assert.equal(h.phase, "bottom"); assert.equal(h.toBottom, 2);
const [a, b, c] = h.hand.map((x) => x.uid);
assert.equal(bottomMany(h, [a]), h); assert.equal(bottomMany(h, [a, a]), h); assert.equal(bottomMany(h, [a, 99999]), h);
const done = bottomMany(h, [b, a]);
assert.equal(done.phase, "playing"); assert.equal(done.step, "upkeep"); assert.equal(done.hand.length, 5);
assert.deepEqual(done.library.slice(-2).map((x) => x.uid), [b, a]); assert.equal(done.library.length, h.library.length + 2);
assert.ok(done.hand.some((x) => x.uid === c));
console.log("phases ok");
