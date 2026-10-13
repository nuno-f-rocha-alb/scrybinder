/** Types of the deck API and the grouping of a deck list. */
export const FORMATS = ["commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual"] as const;
export type Format = (typeof FORMATS)[number];
export type Board = "main" | "side" | "commander" | "maybe";
export const BOARDS: Board[] = ["main", "side", "commander", "maybe"];
export const BOARD_LABEL: Record<Board, string> = { main: "Main deck", side: "Sideboard", commander: "Commander", maybe: "Maybeboard" };
export type CardStatus = "assigned" | "available" | "elsewhere" | "missing" | "proxy";

export type DeckCard = {
  id: number; oracle_id: string; scryfall_id: string | null; quantity: number; board: Board; name: string; mana_cost: string;
  cmc: number; type_line: string | null; color_identity: string[]; owned: number; assigned: number; price: number | null;
  image_id: string | null; tags: string[]; status: CardStatus; missing: number; available: number;
  elsewhere: { deck_id: number; name: string; quantity: number }[]; assignments: { collection_id: number; quantity: number }[];
};
export type DeckSummary = { cards: number; assigned: number; available: number; missing: number; proxies: number; cost_to_complete: number };
export type DeckInfo = { id: number; name: string; format: Format; description: string; summary: DeckSummary; cover?: string | null };
export type Deck = DeckInfo & { cards: DeckCard[] };
export type Problem = { severity: "error" | "warning"; card: string | null; rule: string; message: string };
export type Legality = { problems: Problem[]; counts: { main: number; side: number; commander: number }; game_changers: number; legal: boolean };
export type DeckStats = {
  totals: Record<Board, number>; types: Record<string, number>; lands: number; price: number; cost_to_complete: number; game_changers: number;
  color_identity: string[];
};
export type OracleRow = {
  oracle_id: string; name: string; mana_cost: string; cmc: number; type_line: string | null; color_identity: string[]; oracle_text: string | null;
  id: string | null; price: number | null; owned: number; in_deck: number;
};
/** What the preview panel shows: a deck card or a search result. */
export type Preview = { image_id: string | null; name: string; type_line: string | null; mana_cost: string; price: number | null; owned?: number; status?: CardStatus; tags?: string[] };

const TYPES = ["land", "creature", "planeswalker", "battle", "artifact", "enchantment", "instant", "sorcery"] as const;
/** Primary type of a card (front face), the same rule the statistics use. */
export function primaryType(typeLine: string | null): string {
  const t = (typeLine ?? "").split(" // ")[0].toLowerCase();
  return TYPES.find((x) => t.includes(x)) ?? "other";
}
const GROUP_ORDER = ["creature", "planeswalker", "battle", "artifact", "enchantment", "instant", "sorcery", "land", "other"];
const GROUP_LABEL: Record<string, string> = {
  creature: "Creatures", planeswalker: "Planeswalkers", battle: "Battles", artifact: "Artifacts", enchantment: "Enchantments",
  instant: "Instants", sorcery: "Sorceries", land: "Lands", other: "Other",
};
export type Group = { key: string; label: string; cards: DeckCard[]; count: number };

/** Commander first, then the main deck by type, then the sideboard and the maybeboard. Cards keep the server's order (by name). */
export function groupCards(cards: DeckCard[]): Group[] {
  const out: Group[] = [];
  const add = (key: string, label: string, cs: DeckCard[]) => cs.length && out.push({ key, label, cards: cs, count: cs.reduce((n, c) => n + c.quantity, 0) });
  add("commander", "Commander", cards.filter((c) => c.board === "commander"));
  const main = cards.filter((c) => c.board === "main");
  for (const t of GROUP_ORDER) add(t, GROUP_LABEL[t], main.filter((c) => primaryType(c.type_line) === t));
  add("side", "Sideboard", cards.filter((c) => c.board === "side"));
  add("maybe", "Maybeboard", cards.filter((c) => c.board === "maybe"));
  return out;
}

export const toPreview = (c: DeckCard): Preview => ({ image_id: c.image_id, name: c.name, type_line: c.type_line, mana_cost: c.mana_cost, price: c.price, owned: c.owned, status: c.status, tags: c.tags });
export const resultPreview = (r: OracleRow): Preview => ({ image_id: r.id, name: r.name, type_line: r.type_line, mana_cost: r.mana_cost, price: r.price, owned: r.owned });
