/** Solo playtest ("goldfishing"): pure game state, no React. Every function returns a new Game. */
import { primaryType } from "./decks";
import type { DeckCard } from "./decks";

export type Zone = "library" | "hand" | "battlefield" | "graveyard" | "exile" | "command";
export type GCard = { uid: number; name: string; image_id: string | null; type_line: string | null; tapped: boolean; commander?: boolean; plus?: number; counters?: number; named?: Record<string, number>; token?: boolean; x?: number; y?: number; z?: number };
/** The steps where the game stops. Untap and draw happen by themselves: untap on the way into a new turn, the draw on leaving upkeep. */
export const STEPS = ["upkeep", "main1", "combat", "main2", "end"] as const;
export type Step = (typeof STEPS)[number];
export type Game = Record<Zone, GCard[]> & {
  turn: number; step: Step; life: number; mulligans: number; onPlay: boolean; commander: boolean;
  phase: "mulligan" | "bottom" | "playing"; toBottom: number; freeMulligan: boolean;
  zTop: number;  // the highest `z` handed out on the free table: the card placed last is on top
};

const HAND = 7;

export function shuffle<T>(a: T[], rnd: () => number = Math.random): T[] {
  const b = [...a];
  for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; }
  return b;
}

/** A shuffled library from the main board and the commander(s) in the command zone, with a first hand drawn. */
export function newGame(cards: DeckCard[], commander: boolean, onPlay = true, rnd?: () => number): Game {
  let uid = 0;
  const all = (board: string) => cards.filter((c) => c.board === board).flatMap((c) =>
    Array.from({ length: c.quantity }, () => ({ uid: uid++, name: c.name, image_id: c.image_id, type_line: c.type_line, tapped: false, commander: board === "commander" })));
  const g: Game = {
    library: shuffle(all("main"), rnd), hand: [], battlefield: [], graveyard: [], exile: [], command: all("commander"),
    turn: 1, step: "upkeep", life: commander ? 40 : 20, mulligans: 0, onPlay, commander, phase: "mulligan", toBottom: 0, freeMulligan: commander, zTop: 0,
  };
  return draw(g, HAND);
}

export function draw(g: Game, n = 1): Game {
  const k = Math.min(n, g.library.length);
  return { ...g, library: g.library.slice(k), hand: [...g.hand, ...g.library.slice(0, k)] };
}

/** Shuffle the hand back and draw a fresh seven. */
export function mulligan(g: Game, rnd?: () => number): Game {
  const back = { ...g, library: shuffle([...g.library, ...g.hand], rnd), hand: [], mulligans: g.mulligans + 1 };
  return draw(back, HAND);
}

/** Start playing, at the upkeep of turn 1: the opening hand is not a draw, the draw of the first turn comes on leaving upkeep. */
const begin = (g: Game): Game => ({ ...g, phase: "playing" });

/** Keep the hand: London mulligan, so one card goes to the bottom per mulligan taken (the first is free in Commander). */
export function keep(g: Game): Game {
  const n = Math.min(Math.max(0, g.mulligans - (g.freeMulligan ? 1 : 0)), g.hand.length);
  return n ? { ...g, phase: "bottom", toBottom: n } : begin(g);
}

/** Move one card between zones (`bottom` puts it at the end of the library, otherwise on top; the battlefield appends). Untaps it. */
export function move(g: Game, uid: number, to: Zone, bottom = false): Game {
  const from = (Object.keys(g) as (keyof Game)[]).find((z) => Array.isArray(g[z]) && (g[z] as GCard[]).some((c) => c.uid === uid)) as Zone | undefined;
  if (!from) return g;
  const found = g[from].find((c) => c.uid === uid) as GCard;
  const out = { ...g, [from]: g[from].filter((c) => c.uid !== uid) };
  if (found.token && from === "battlefield" && to !== "battlefield") return out;  // a token that leaves the battlefield ceases to exist
  const { plus: _p, counters: _c, named: _n, x: _x, y: _y, z: _z, ...rest } = found;  // counters and the table position stay on the battlefield
  const card = { ...rest, tapped: false };
  out[to] = (to === "library" && bottom) || to === "battlefield" ? [...out[to], card] : [card, ...out[to]];
  return out;
}

/** During the "bottom" phase a click on a hand card sends it under the library. */
export function bottomOne(g: Game, uid: number): Game {
  if (g.phase !== "bottom" || !g.hand.some((c) => c.uid === uid)) return g;
  const r = move(g, uid, "library", true);
  return r.toBottom <= 1 ? begin({ ...r, toBottom: 0 }) : { ...r, toBottom: r.toBottom - 1 };
}

export function toggleTap(g: Game, uid: number): Game {
  return { ...g, battlefield: g.battlefield.map((c) => (c.uid === uid ? { ...c, tapped: !c.tapped } : c)) };
}

/** Jump to main 1 of the next turn: untap everything and draw a card. */
export function nextTurn(g: Game): Game {
  const t = { ...g, turn: g.turn + 1, step: "main1" as Step, battlefield: g.battlefield.map((c) => ({ ...c, tapped: false })) };
  return draw(t, 1);
}

/** Walk the steps of a turn. From end the next turn begins: everything untaps (no stop) and the game waits at upkeep. Leaving upkeep draws a card (none on turn 1 on the play in a two-player game; in Commander, three or more players, everyone draws) and lands on main 1. */
export function nextPhase(g: Game): Game {
  if (g.step === "upkeep") return draw({ ...g, step: "main1" }, g.turn === 1 && g.onPlay && !g.commander ? 0 : 1);
  if (g.step === "end") return untapAll({ ...g, step: "upkeep", turn: g.turn + 1 });
  return { ...g, step: STEPS[STEPS.indexOf(g.step) + 1] };
}

export const untapAll = (g: Game): Game => ({ ...g, battlefield: g.battlefield.map((c) => (c.tapped ? { ...c, tapped: false } : c)) });

/** London mulligan, all at once: exactly `toBottom` cards of the hand go under the library (in the order given) and the game starts. */
export function bottomMany(g: Game, uids: number[]): Game {
  if (g.phase !== "bottom" || uids.length !== g.toBottom || new Set(uids).size !== uids.length || !uids.every((u) => g.hand.some((c) => c.uid === u))) return g;
  const out = uids.reduce((x, u) => move(x, u, "library", true), g);
  return begin({ ...out, toBottom: 0 });
}

export const isLand = (c: GCard) => primaryType(c.type_line) === "land";

/** The size of a card on the table as a fraction of the table's width and height. */
export type Box = { w: number; h: number };
const DEFAULT_BOX: Box = { w: 0.08, h: 0.25 };
const clamp = (v: number, hi: number) => Math.min(Math.max(v, 0), Math.max(hi, 0));

/** Put a battlefield card at (x, y), fractions of the table, kept inside it, and on top of every other card. */
export function placeCard(g: Game, uid: number, x: number, y: number, box: Box = DEFAULT_BOX): Game {
  if (!Number.isFinite(x) || !Number.isFinite(y) || !g.battlefield.some((c) => c.uid === uid)) return g;
  const z = g.zTop + 1;
  return { ...g, zTop: z, battlefield: g.battlefield.map((c) => (c.uid === uid ? { ...c, x: clamp(x, 1 - box.w), y: clamp(y, 1 - box.h), z } : c)) };
}

/** Bring a battlefield card to the top, leaving it where it is. */
export function raise(g: Game, uid: number): Game {
  if (!g.battlefield.some((c) => c.uid === uid)) return g;
  const z = g.zTop + 1;
  return { ...g, zTop: z, battlefield: g.battlefield.map((c) => (c.uid === uid ? { ...c, z } : c)) };
}

/** Creatures (and tokens) in the front row at the top, other permanents in the middle, lands at the bottom nearest the player. */
const band = (c: GCard): 0 | 1 | 2 => (isLand(c) && !/creature/i.test(c.type_line ?? "") ? 2 : c.token || /creature/i.test(c.type_line ?? "") ? 0 : 1);

/** Place a card in the first free spot of its row, scanning left to right (stacked a little off when the row is full). */
export function autoPlace(g: Game, uid: number, box: Box = DEFAULT_BOX): Game {
  const c = g.battlefield.find((k) => k.uid === uid);
  if (!c) return g;
  const y = ((1 - box.h) * band(c)) / 2;
  const others = g.battlefield.filter((o) => o.uid !== uid && o.x !== undefined && o.y !== undefined);
  const free = (x: number) => !others.some((o) => Math.abs(o.x! - x) < box.w / 2 && Math.abs(o.y! - y) < box.h / 2);
  let x = 0.02;
  while (x <= 1 - box.w && !free(x)) x += box.w + 0.01;
  if (x > 1 - box.w) x = 0.02 + (others.filter((o) => Math.abs(o.y! - y) < box.h / 2).length % 5) * 0.02;
  return placeCard(g, uid, x, y, box);
}

/** Give every battlefield card that has no position yet one (cards played, searched, made as tokens...). Returns `g` itself when there is nothing to do. */
export const settle = (g: Game, box: Box = DEFAULT_BOX): Game => g.battlefield.filter((c) => c.x === undefined).reduce((x, c) => autoPlace(x, c.uid, box), g);

export const shuffleLibrary = (g: Game, rnd?: () => number): Game => ({ ...g, library: shuffle(g.library, rnd) });

export type SimResult = { hands: number; keepableShare: number; avgLandsOpening: number; avgLandsByTurn4: number; allColorsByTurn4Share: number; deckColors: string[] };

/** A small seeded generator (mulberry32) so a simulation gives the same numbers for the same deck. */
export function seeded(seed: number): () => number {
  return () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/**
 * Deal `n` opening sevens (no mulligans) and measure them. Keepable: 2-4 lands (3-5 in Commander). "By turn 4": the seven plus
 * three draws, on the play. A colour is available when a land that makes it (its produced mana, else its colour identity) was seen; rocks and dorks do not count.
 */
export function simulate(cards: DeckCard[], commander: boolean, n: number, rnd: () => number): SimResult {
  const pool = cards.filter((c) => c.board === "main").flatMap((c) => Array.from({ length: c.quantity }, () => ({ land: primaryType(c.type_line) === "land", ci: c.produced_mana?.length ? c.produced_mana : c.color_identity })));
  const deckColors = [...new Set(cards.filter((c) => c.board === "main" || c.board === "commander").flatMap((c) => c.color_identity))].sort();
  const [lo, hi] = commander ? [3, 5] : [2, 4];
  let keep = 0, open = 0, t4 = 0, colors = 0;
  const hands = Math.max(0, Math.floor(n));
  for (let i = 0; i < hands; i++) {
    const seen = shuffle(pool, rnd).slice(0, HAND + 3);
    const opening = seen.slice(0, HAND).filter((c) => c.land).length;
    open += opening; keep += opening >= lo && opening <= hi ? 1 : 0;
    t4 += seen.filter((c) => c.land).length;
    colors += deckColors.every((x) => seen.some((c) => c.land && c.ci.includes(x))) ? 1 : 0;
  }
  const mean = (x: number) => (hands ? x / hands : 0);
  return { hands, keepableShare: mean(keep), avgLandsOpening: mean(open), avgLandsByTurn4: mean(t4), allColorsByTurn4Share: mean(colors), deckColors };
}

/** Add `delta` +1/+1 counters ("plus", may go negative) or generic counters (never below 0) to a card on the battlefield. */
export function addCounter(g: Game, uid: number, kind: "plus" | "generic", delta: number): Game {
  return { ...g, battlefield: g.battlefield.map((c) => c.uid !== uid ? c : kind === "plus" ? { ...c, plus: (c.plus ?? 0) + delta } : { ...c, counters: Math.max(0, (c.counters ?? 0) + delta) }) };
}

/** A token on the battlefield (no image; `pt` such as "1/1" is shown with the name). */
export function token(g: Game, t: { name: string; pt?: string }): Game {
  const uid = 1 + Math.max(-1, ...(Object.values(g).filter(Array.isArray).flat() as GCard[]).map((c) => c.uid));
  const label = t.pt?.trim() ? `${t.name.trim()} (${t.pt.trim()})` : t.name.trim();
  return { ...g, battlefield: [...g.battlefield, { uid, name: label || "Token", image_id: null, type_line: "Token", tapped: false, token: true }] };
}

/** The top `n` cards of the library, without changing anything. */
export const peek = (g: Game, n: number): GCard[] => g.library.slice(0, Math.max(0, n));

/** Put the cards `top` (in that order) back on top of the library and the cards `bottom` at the end; the rest keep their order. */
export function reorderTop(g: Game, top: number[], bottom: number[]): Game {
  const by = new Map(g.library.map((c) => [c.uid, c]));
  const pick = (ids: number[]) => ids.map((u) => by.get(u)).filter((c): c is GCard => !!c);
  const moved = new Set([...top, ...bottom]);
  return { ...g, library: [...pick(top), ...g.library.filter((c) => !moved.has(c.uid)), ...pick(bottom)] };
}

/** A bounded undo history: the previous states, oldest dropped past `cap`. */
export const pushHistory = <T,>(stack: T[], state: T, cap = 50): T[] => [...stack, state].slice(-cap);

/** Add `delta` to a counter with a name of your own ("Charge", "Loyalty"...) on a battlefield card; at 0 it goes away. */
export function addNamed(g: Game, uid: number, name: string, delta: number): Game {
  const key = name.trim().slice(0, 20);
  if (!key) return g;
  return { ...g, battlefield: g.battlefield.map((c) => {
    if (c.uid !== uid) return c;
    const n = Math.max(0, (c.named?.[key] ?? 0) + delta), { [key]: _gone, ...rest } = c.named ?? {};
    return { ...c, named: n ? { ...rest, [key]: n } : rest };
  }) };
}
