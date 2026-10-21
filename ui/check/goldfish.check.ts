// Run: npx tsx check/goldfish.check.ts  (from ui/)
import { bottomOne, keep, mulligan, move, newGame, nextTurn, toggleTap } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, board: string, type_line = "Creature"): DeckCard => ({ name, quantity, board, type_line, image_id: null } as DeckCard);
const cards = [mk("Forest", 30, "main", "Basic Land — Forest"), mk("Bear", 29, "main"), mk("Boss", 1, "commander", "Legendary Creature")];
const total = (g: ReturnType<typeof newGame>) => ["library", "hand", "battlefield", "graveyard", "exile", "command"].reduce((n, z) => n + (g as unknown as Record<string, unknown[]>)[z].length, 0);

let g = newGame(cards, true);
assert.equal(g.hand.length, 7); assert.equal(g.command.length, 1); assert.equal(g.library.length, 52); assert.equal(g.life, 40);
// commander: first mulligan is free, the second bottoms one
g = keep(mulligan(g)); assert.equal(g.phase, "playing"); assert.equal(g.hand.length, 7);
let h = mulligan(mulligan(newGame(cards, true))); h = keep(h); assert.equal(h.phase, "bottom");
h = bottomOne(h, h.hand[0].uid); assert.equal(h.phase, "playing"); assert.equal(h.hand.length, 6); assert.equal(h.library.length, 53);
// non-commander: one bottom per mulligan
let p = keep(mulligan(newGame(cards, false))); assert.equal(p.phase, "bottom"); p = bottomOne(p, p.hand[0].uid); assert.equal(p.hand.length, 6);
// turns: no draw on turn 1 on the play, draw on the draw, draw each later turn
const play = keep(newGame(cards, false)); assert.equal(play.hand.length, 7);
assert.equal(keep(newGame(cards, false, false)).hand.length, 7);   // the opening hand is not a draw: nobody draws before turn 1's draw step
const t2 = nextTurn(play); assert.equal(t2.turn, 2); assert.equal(t2.hand.length, 8);
// moves conserve cards; tapping; untap on turn
let m = move(t2, t2.hand[0].uid, "battlefield"); assert.equal(m.battlefield.length, 1); assert.equal(total(m), 60);
m = toggleTap(m, m.battlefield[0].uid); assert.ok(m.battlefield[0].tapped);
assert.ok(!nextTurn(m).battlefield[0].tapped);
m = move(m, m.battlefield[0].uid, "graveyard"); assert.equal(total(m), 60); assert.ok(!m.graveyard[0].tapped);
// empty library does not crash
assert.equal(newGame([mk("A", 3, "main")], false).hand.length, 3);

// a commander can return to the command zone
{
  let c = newGame(cards, true); const boss = c.command[0];
  assert.ok(boss.commander); c = move(c, boss.uid, "battlefield"); c = move(c, boss.uid, "command");
  assert.equal(c.command.length, 1); assert.equal(c.battlefield.length, 0);
}
console.log("goldfish ok");
