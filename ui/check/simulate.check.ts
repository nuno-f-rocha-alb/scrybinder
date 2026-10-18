// Run: npx tsx check/simulate.check.ts  (from ui/)
import { seeded, simulate } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string, color_identity: string[], board = "main"): DeckCard => ({ name, quantity, type_line, color_identity, board, image_id: null } as DeckCard);
const run = (cards: DeckCard[], commander = false, n = 2000) => simulate(cards, commander, n, seeded(1));

// all lands: 7 lands is out of range, 10 seen by turn 4, a mono-colour deck always has its colour
let r = run([mk("Island", 60, "Basic Land — Island", ["U"])]);
assert.deepEqual([r.keepableShare, r.avgLandsOpening, r.avgLandsByTurn4, r.allColorsByTurn4Share, r.deckColors], [0, 7, 10, 1, ["U"]]);
// no lands: nothing keepable, no colour source
r = run([mk("Bear", 60, "Creature", ["G"])]);
assert.deepEqual([r.keepableShare, r.avgLandsOpening, r.avgLandsByTurn4, r.allColorsByTurn4Share], [0, 0, 0, 0]);
// two colours, lands of one only: never both
r = run([mk("Forest", 24, "Basic Land — Forest", ["G"]), mk("Spell", 36, "Instant", ["U"])]);
assert.equal(r.allColorsByTurn4Share, 0);
// a realistic deck: 24 lands in 60 -> expected 2.8 lands in 7 and 4 in 10 (hypergeometric means), keepable between 0 and 1
r = run([mk("Forest", 12, "Basic Land — Forest", ["G"]), mk("Island", 12, "Basic Land — Island", ["U"]), mk("Spell", 36, "Instant", ["U"])]);
assert.ok(Math.abs(r.avgLandsOpening - 2.8) < 0.1 && Math.abs(r.avgLandsByTurn4 - 4) < 0.1, JSON.stringify(r));
assert.ok(r.keepableShare > 0.7 && r.keepableShare < 0.9 && r.allColorsByTurn4Share > 0.5 && r.allColorsByTurn4Share < 1, JSON.stringify(r));
assert.deepEqual(run([mk("Forest", 12, "Basic Land — Forest", ["G"]), mk("Island", 12, "Basic Land — Island", ["U"])]), run([mk("Forest", 12, "Basic Land — Forest", ["G"]), mk("Island", 12, "Basic Land — Island", ["U"])]));  // seeded: repeatable
// commander band is 3-5 and the commander is not in the library; tiny decks and n = 0 do not break
r = run([mk("Forest", 36, "Basic Land — Forest", ["G"]), mk("Boss", 1, "Creature", ["G"], "commander")], true);
assert.equal(r.keepableShare, 0); assert.deepEqual(r.deckColors, ["G"]);
r = run([mk("Forest", 3, "Basic Land — Forest", ["G"])]); assert.equal(r.avgLandsOpening, 3);
r = run([mk("Forest", 3, "Basic Land — Forest", ["G"])], false, 0); assert.deepEqual([r.hands, r.keepableShare, r.avgLandsOpening], [0, 0, 0]);
// a land that makes mana without colour in its identity (Command Tower) counts through produced_mana
const tower = { ...mk("Command Tower", 30, "Land", []), produced_mana: ["W", "U"] } as DeckCard;
r = run([tower, mk("Spell", 30, "Instant", ["W", "U"])]);
assert.ok(r.allColorsByTurn4Share > 0.9, JSON.stringify(r));
console.log("simulate ok");
