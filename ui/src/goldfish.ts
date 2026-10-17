/** Solo playtest ("goldfishing"): pure game state, no React. Every function returns a new Game. */
import { primaryType } from "./decks";
import type { DeckCard } from "./decks";

export type Zone = "library" | "hand" | "battlefield" | "graveyard" | "exile" | "command";
export type GCard = { uid: number; name: string; image_id: string | null; type_line: string | null; tapped: boolean; commander?: boolean };
export type Game = Record<Zone, GCard[]> & {
  turn: number; life: number; mulligans: number; onPlay: boolean;
  phase: "mulligan" | "bottom" | "playing"; toBottom: number; freeMulligan: boolean;
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
    turn: 1, life: commander ? 40 : 20, mulligans: 0, onPlay, phase: "mulligan", toBottom: 0, freeMulligan: commander,
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

/** Start playing; on the draw the first turn has a draw step. */
const begin = (g: Game): Game => draw({ ...g, phase: "playing" }, g.onPlay ? 0 : 1);

/** Keep the hand: London mulligan, so one card goes to the bottom per mulligan taken (the first is free in Commander). */
export function keep(g: Game): Game {
  const n = Math.min(Math.max(0, g.mulligans - (g.freeMulligan ? 1 : 0)), g.hand.length);
  return n ? { ...g, phase: "bottom", toBottom: n } : begin(g);
}

/** Move one card between zones (`bottom` puts it at the end of the library, otherwise on top; the battlefield appends). Untaps it. */
export function move(g: Game, uid: number, to: Zone, bottom = false): Game {
  const from = (Object.keys(g) as (keyof Game)[]).find((z) => Array.isArray(g[z]) && (g[z] as GCard[]).some((c) => c.uid === uid)) as Zone | undefined;
  if (!from) return g;
  const card = { ...(g[from].find((c) => c.uid === uid) as GCard), tapped: false };
  const out = { ...g, [from]: g[from].filter((c) => c.uid !== uid) };
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

/** Untap everything and draw (no draw on turn 1 when on the play). */
export function nextTurn(g: Game): Game {
  const t = { ...g, turn: g.turn + 1, battlefield: g.battlefield.map((c) => ({ ...c, tapped: false })) };
  return draw(t, 1);
}

export const isLand = (c: GCard) => primaryType(c.type_line) === "land";

export const shuffleLibrary = (g: Game, rnd?: () => number): Game => ({ ...g, library: shuffle(g.library, rnd) });
