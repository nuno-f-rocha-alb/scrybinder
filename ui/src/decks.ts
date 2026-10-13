/** Types of the deck API and the grouping of a deck list. */
export const FORMATS = ["commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual"] as const;
export type Format = (typeof FORMATS)[number];
export type Board = "main" | "side" | "commander" | "maybe";
export const BOARDS: Board[] = ["main", "side", "commander", "maybe"];
export const BOARD_LABEL: Record<Board, string> = { main: "Main deck", side: "Sideboard", commander: "Commander", maybe: "Maybeboard" };
export type CardStatus = "assigned" | "available" | "elsewhere" | "missing" | "proxy";

export type DeckCard = {
  id: number; oracle_id: string; scryfall_id: string | null; quantity: number; board: Board; name: string; mana_cost: string;
  cmc: number; type_line: string | null; colors: string[]; color_identity: string[]; owned: number; assigned: number; price: number | null;
  image_id: string | null; tags: string[]; status: CardStatus; missing: number; available: number;
  elsewhere: { deck_id: number; name: string; quantity: number }[]; assignments: { collection_id: number; quantity: number }[];
};
export type DeckSummary = { cards: number; assigned: number; available: number; missing: number; proxies: number; cost_to_complete: number };
export type DeckInfo = { id: number; name: string; format: Format; description: string; folder_id: number | null; summary: DeckSummary; cover?: string | null };
export type Folder = { id: number; name: string; decks: number };
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
export type View = "list" | "compact" | "grid" | "stacks" | "spoiler";
export type GroupBy = "type" | "color" | "cmc" | "tag" | "status";
export type SortBy = "name" | "cmc" | "price";
export const VIEWS: { id: View; label: string }[] = [
  { id: "list", label: "List" }, { id: "compact", label: "Compact" }, { id: "grid", label: "Grid" }, { id: "stacks", label: "Stacks" }, { id: "spoiler", label: "Spoiler" },
];
export const GROUPS: { id: GroupBy; label: string }[] = [
  { id: "type", label: "Type" }, { id: "color", label: "Colour" }, { id: "cmc", label: "Mana value" }, { id: "tag", label: "Tag" }, { id: "status", label: "Collection status" },
];
export const SORTS: { id: SortBy; label: string }[] = [{ id: "name", label: "Name" }, { id: "cmc", label: "Mana value" }, { id: "price", label: "Price" }];

const TYPE_ORDER = ["creature", "planeswalker", "battle", "artifact", "enchantment", "instant", "sorcery", "land", "other"];
const TYPE_LABEL: Record<string, string> = {
  creature: "Creatures", planeswalker: "Planeswalkers", battle: "Battles", artifact: "Artifacts", enchantment: "Enchantments",
  instant: "Instants", sorcery: "Sorceries", land: "Lands", other: "Other",
};
const COLOR_ORDER = ["W", "U", "B", "R", "G", "multi", "none", "land"];
const COLOR_LABEL: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", multi: "Multicolour", none: "Colourless", land: "Lands" };
const STATUS_ORDER: CardStatus[] = ["missing", "elsewhere", "available", "assigned", "proxy"];
const STATUS_LABEL: Record<CardStatus, string> = { missing: "Missing", elsewhere: "In other decks", available: "Available to assign", assigned: "Assigned", proxy: "Proxies" };

export type Group = { key: string; label: string; cards: DeckCard[]; count: number; pip?: string };

const colorKey = (c: DeckCard) => (primaryType(c.type_line) === "land" ? "land" : c.colors.length > 1 ? "multi" : c.colors[0] ?? "none");
const cmcKey = (c: DeckCard) => (primaryType(c.type_line) === "land" ? "land" : String(Math.min(7, Math.floor(c.cmc))));

/** The groups of a deck. The commander is always first and the sideboard and maybeboard last; the main deck is grouped by `by`,
 * and the cards of every group are sorted by `sort` (price from the highest). */
export function groupCards(cards: DeckCard[], by: GroupBy = "type", sort: SortBy = "name"): Group[] {
  const cmp = (a: DeckCard, b: DeckCard) => (sort === "cmc" ? a.cmc - b.cmc : sort === "price" ? (b.price ?? 0) - (a.price ?? 0) : 0) || a.name.localeCompare(b.name);
  const out: Group[] = [];
  const add = (key: string, label: string, cs: DeckCard[], pip?: string) => cs.length && out.push({ key, label, pip, cards: [...cs].sort(cmp), count: cs.reduce((n, c) => n + c.quantity, 0) });
  add("commander", "Commander", cards.filter((c) => c.board === "commander"));
  const main = cards.filter((c) => c.board === "main");
  if (by === "type") for (const t of TYPE_ORDER) add(t, TYPE_LABEL[t], main.filter((c) => primaryType(c.type_line) === t));
  else if (by === "color") for (const k of COLOR_ORDER) add(k, COLOR_LABEL[k], main.filter((c) => colorKey(c) === k), "WUBRG".includes(k) ? `{${k}}` : undefined);
  else if (by === "cmc") for (const k of ["0", "1", "2", "3", "4", "5", "6", "7", "land"]) add(k, k === "land" ? "Lands" : k === "7" ? "Mana value 7+" : `Mana value ${k}`, main.filter((c) => cmcKey(c) === k));
  else if (by === "status") for (const st of STATUS_ORDER) add(st, STATUS_LABEL[st], main.filter((c) => c.status === st));
  else {  // tag: a card goes under its first tag (alphabetical), untagged cards last
    const tags = [...new Set(main.flatMap((c) => c.tags))].sort();
    for (const t of tags) add(`tag:${t}`, t, main.filter((c) => [...c.tags].sort()[0] === t));
    add("untagged", "Untagged", main.filter((c) => !c.tags.length));
  }
  add("side", "Sideboard", cards.filter((c) => c.board === "side"));
  add("maybe", "Maybeboard", cards.filter((c) => c.board === "maybe"));
  return out;
}

export const toPreview = (c: DeckCard): Preview => ({ image_id: c.image_id, name: c.name, type_line: c.type_line, mana_cost: c.mana_cost, price: c.price, owned: c.owned, status: c.status, tags: c.tags });
export const resultPreview = (r: OracleRow): Preview => ({ image_id: r.id, name: r.name, type_line: r.type_line, mana_cost: r.mana_cost, price: r.price, owned: r.owned });
