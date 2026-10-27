import { useCallback, useEffect, useState } from "react";
import { IconPlus } from "@tabler/icons-react";
import { api, FINISH, LANGS } from "../api";
import { Badge, CardImg } from "./ui";

type Item = {
  card_id: number; name: string; board: string; need: number; collection_id: number; scryfall_id: string; set_code: string; set_name: string;
  collector_number: string; finish: string; condition: string; language: string; free: number; preferred: boolean;
};
type Located = { locations: { location: string; items: Item[] }[]; copies: number };

const give = (i: Item) => Math.min(i.free, i.need);

/** What to send for `items` in one go: a card never gets more than it needs and a row never gives more than it has free,
 * however many entries share them (two rows of one card in a location, or a card in the main deck and the sideboard). */
function plan(items: Item[]) {
  const need = new Map<number, number>(), free = new Map<number, number>();
  return items.flatMap((i) => {
    const q = Math.min(need.get(i.card_id) ?? i.need, free.get(i.collection_id) ?? i.free);
    need.set(i.card_id, (need.get(i.card_id) ?? i.need) - q);
    free.set(i.collection_id, (free.get(i.collection_id) ?? i.free) - q);
    return q > 0 ? [{ card_id: i.card_id, collection_id: i.collection_id, quantity: q }] : [];
  });
}

/** The free copies of what the deck still lacks, by the location they are in: so you can fetch them from the binder in one go and add them. */
export default function ByLocation({ deckId, toast, onChanged }: { deckId: number; toast: (m: string, err?: boolean) => void; onChanged: () => void }) {
  const [data, setData] = useState<Located | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<Located>(`/decks/${deckId}/locate`).then(setData).catch((e) => toast(e.message, true)), [deckId]);
  useEffect(() => { load(); }, [load]);

  const add = (items: Item[]) => {
    setBusy(true);
    api<{ assigned: number }>(`/decks/${deckId}/assign-copies`, { method: "POST", body: JSON.stringify({ items: plan(items) }) })
      .then((r) => { toast(`Added ${r.assigned} ${r.assigned === 1 ? "copy" : "copies"} to the deck`); onChanged(); return load(); })
      .catch((e) => { toast(e.message, true); load(); }).finally(() => setBusy(false));
  };

  if (!data) return <p className="text-mute">Loading…</p>;
  if (!data.locations.length) return <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-mute">No free copy of what this deck lacks: every card is assigned, held by another deck, or not in your collection.</p>;
  return (
    <div>
      <p className="mb-4 text-sm text-mute">{data.copies} free {data.copies === 1 ? "copy" : "copies"} you own of cards this deck still needs, by where they are. Adding assigns them to the deck and moves them to its location.</p>
      <div className="space-y-6">
        {data.locations.map((g) => (
          <section key={g.location} aria-label={g.location || "No location"}>
            <div className="mb-1 flex flex-wrap items-center gap-3 border-b border-line pb-1">
              <h3 className="font-semibold">{g.location || "No location"}</h3>
              <span className="text-sm text-mute tabular-nums">{g.items.length} {g.items.length === 1 ? "card" : "cards"}</span>
              <button className="btn-ghost ml-auto !py-1 text-xs" disabled={busy} onClick={() => add(g.items)}
                title="Add what each of these cards still needs from this location"><IconPlus className="size-3.5" />Add all from here</button>
            </div>
            <ul className="divide-y divide-line">
              {g.items.map((i) => (
                <li key={`${i.card_id}-${i.collection_id}`} className="flex items-center gap-3 py-2">
                  <div className="w-10 shrink-0"><CardImg id={i.scryfall_id} size="small" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                      {i.name}{i.board !== "main" && <span className="text-xs font-normal text-mute">{i.board}</span>}
                      {i.preferred && <Badge>Preferred</Badge>}
                    </div>
                    <div className="text-xs text-mute">
                      <span className="uppercase">{i.set_code}</span> #{i.collector_number}{i.finish !== "nonfoil" && <> · {FINISH[i.finish]}</>} · {LANGS[i.language] ?? i.language} · {i.condition}
                    </div>
                    <div className="text-xs text-mute tabular-nums">{i.free} free here · the deck needs {i.need}</div>
                  </div>
                  <button className="btn-primary !py-1 text-xs" disabled={busy} onClick={() => add([i])}>Add {give(i)}</button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
