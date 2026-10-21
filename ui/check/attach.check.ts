// Run: npx tsx check/attach.check.ts  (from ui/)
import { attach, detach, keep, move, newGame, placeCard, placeOf, settle } from "../src/goldfish";
import type { DeckCard } from "../src/decks";
import assert from "node:assert/strict";

const mk = (name: string, quantity: number, type_line: string): DeckCard => ({ name, quantity, type_line, board: "main", image_id: null } as unknown as DeckCard);
const cards = [mk("Bear", 10, "Creature — Bear"), mk("Aura", 10, "Enchantment — Aura"), mk("Rock", 10, "Artifact")];
const box = { w: 0.1, h: 0.3 };

let g = keep(newGame(cards, false));
const all0 = [...g.hand, ...g.library];  // from anywhere in the deck, so the shuffle cannot matter
const ids = (n: string) => all0.filter((c) => c.name === n).map((c) => c.uid);
const pick = [ids("Bear")[0], ids("Aura")[0], ids("Rock")[0]];
const [bear, aura, rock] = pick;
for (const u of pick) g = move(g, u, "battlefield");
g = settle(g, box);
const get = (x: typeof g, u: number) => x.battlefield.find((c) => c.uid === u)!;

// attach: accepted and rejected cases (a rejection returns the same object)
assert.equal(attach(g, aura, aura), g);              // not to itself
assert.equal(attach(g, 999, bear), g);               // unknown card
assert.equal(attach(g, aura, 999), g);               // unknown host
const a = attach(g, aura, bear);
assert.equal(get(a, aura).attachedTo, bear);
assert.equal(attach(a, rock, aura), a);              // the host is itself attached
assert.equal(attach(a, bear, rock), a);              // a card with attachments cannot be attached
assert.equal(attach(a, aura, rock).battlefield.find((c) => c.uid === aura)!.attachedTo, rock);   // moved to another host
assert.equal(attach(move(g, rock, "graveyard"), aura, rock).battlefield.some((c) => c.attachedTo), false);   // host not on the table

// placeOf: the card's own spot, or the host's shifted left and down and just under it; stays inside the table
const h = placeCard(a, bear, 0.5, 0.2, box);
assert.deepEqual(placeOf(h, get(h, bear), box), { x: 0.5, y: 0.2, z: 2 * get(h, bear).z! });
const p = placeOf(h, get(h, aura), box);
assert.ok(Math.abs(p.x - 0.478) < 1e-9 && Math.abs(p.y - 0.248) < 1e-9); assert.equal(p.z, 2 * get(h, bear).z! - 1);
const edge = placeCard(a, bear, 0, 0.7, box);        // left edge, bottom: the shifted card is clamped
const q = placeOf(edge, get(edge, aura), box); assert.ok(q.x === 0 && Math.abs(q.y - 0.7) < 1e-9);
// a second and a fifth attachment get a bigger offset, capped at four
let many = h;
const rocks = ids("Rock").slice(0, 5); for (const u of rocks) many = attach(move(many, u, "battlefield"), u, bear);
many = settle(many, box);
const offs = [aura, ...rocks].map((u) => placeOf(many, get(many, u), box).x);
assert.ok(offs.every((x, i) => i === 0 || x <= offs[i - 1] + 1e-9)); assert.equal(offs[4], offs[5]);

// dropping on the table by hand detaches; detach clears only the link
assert.equal(get(placeCard(h, aura, 0.1, 0.1, box), aura).attachedTo, undefined);
assert.equal(get(detach(h, aura), aura).attachedTo, undefined); assert.equal(detach(g, aura), g);

// the host leaving the table frees what was attached, where it was stored; an attachment leaving forgets its host
const left = move(h, bear, "graveyard");
assert.equal(get(left, aura).attachedTo, undefined); assert.equal(get(left, aura).x, get(h, aura).x);
const gone = move(h, aura, "hand");
assert.ok(gone.hand.every((c) => c.attachedTo === undefined));
// a card played from the hand straight onto a host stays attached through settle, and gets its own spot when detached
const fresh = ids("Aura")[1];
const played = settle(attach(move(h, fresh, "battlefield"), fresh, bear), box);
assert.equal(get(played, fresh).attachedTo, bear); assert.equal(get(played, fresh).x, undefined);
const freed = settle(detach(played, fresh), box);
assert.ok(get(freed, fresh).x !== undefined && get(freed, fresh).attachedTo === undefined);
console.log("attach ok");
