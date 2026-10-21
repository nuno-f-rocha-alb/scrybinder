/** Warnings, not enforcement: obvious breaches of the Comprehensive Rules on the Playtest table. Pure; nothing is moved or blocked. */
import type { Game } from "./goldfish";

export type Warning = { key: string; rule: string; text: string; uids: number[] };

const HAND_MAX = 7;
/** The front face of a type line: a card on the table is its front face, and a back face must not make it an Aura or a legend. */
const front = (t: string | null) => (t ?? "").split(" // ")[0];
const legendary = (t: string | null) => /\blegendary\b/i.test(front(t));

/** The warnings for a game in play, in a stable order: 704.5j, 704.5f, 704.5m, 514.1. `key` is the same while the situation is, so it can be ignored. */
export function warnings(g: Game): Warning[] {
  if (g.phase !== "playing") return [];
  const out: Warning[] = [];
  const mk = (rule: string, text: string, uids: number[], key = [...uids].sort((a, b) => a - b).join(",")) => out.push({ key: `${rule}:${key}`, rule, text, uids });

  // 704.5j: two or more legendary permanents with the same name
  const byName = new Map<string, number[]>();
  for (const c of g.battlefield) if (legendary(c.type_line)) byName.set(c.name, [...(byName.get(c.name) ?? []), c.uid]);
  for (const [name, uids] of byName) if (uids.length > 1) mk("704.5j", `Legend rule: ${uids.length} × ${name} on the battlefield, keep one.`, uids);

  // 704.5f: a creature with toughness 0 or less (+1/+1 counters count; a toughness that is not a plain number, such as *, never warns)
  for (const c of g.battlefield) {
    const creature = /\bcreature\b/i.test(front(c.type_line)) || (c.token && c.toughness !== undefined);
    if (creature && c.toughness !== undefined && /^-?\d+$/.test(c.toughness) && Number(c.toughness) + (c.plus ?? 0) <= 0)
      mk("704.5f", `${c.name} has toughness ${Number(c.toughness) + (c.plus ?? 0)}: it is put into the graveyard.`, [c.uid]);
  }

  // 704.5m: an Aura that is not attached to anything
  for (const c of g.battlefield) if (/\baura\b/i.test(front(c.type_line)) && c.attachedTo === undefined) mk("704.5m", `${c.name} is an Aura and is not attached: attach it, or it is put into the graveyard.`, [c.uid]);

  // 514.1: at the end step, discard down to the maximum hand size
  if (g.step === "end" && g.hand.length > HAND_MAX) mk("514.1", `Hand size: ${g.hand.length} cards, discard ${g.hand.length - HAND_MAX} to ${HAND_MAX}.`, [], `turn ${g.turn}`);  // ignored for this turn only
  return out;
}
