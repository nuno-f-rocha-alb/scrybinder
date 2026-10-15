import { useEffect, useState } from "react";
import { IconMinus, IconPlus, IconX } from "@tabler/icons-react";
import { api, eur, FINISH, LANGS } from "../api";
import { DeckCard } from "../decks";
import { Badge, Modal } from "./ui";
import { StatusBadge } from "./mana";
import PrintingDialog from "./printings";

type Copy = {
  id: number; scryfall_id: string; quantity: number; finish: string; condition: string; language: string; location: string;
  altered: number; signed: number; misprint: number; set_code: string; set_name: string; collector_number: string; price: number | null;
  here: number; free: number; elsewhere: { deck_id: number; name: string; quantity: number }[];
};
type Copies = { quantity: number; rows: Copy[] };

const STEP = "flex size-7 items-center justify-center rounded-md border border-line text-mute hover:bg-raised hover:text-ink disabled:pointer-events-none disabled:opacity-30";

/** Which copies of the collection are reserved for a deck card, and its tags (a `proxy` needs no copies). */
export default function AssignDialog({ deckId, card, onClose, onChanged }: { deckId: number; card: DeckCard; onClose: () => void; onChanged: () => void }) {
  const [data, setData] = useState<Copies | null>(null);
  const [want, setWant] = useState<Record<number, number>>({});
  const [err, setErr] = useState("");
  const [tag, setTag] = useState("");
  const [picking, setPicking] = useState(false);
  const proxy = card.tags.includes("proxy");
  const url = `/decks/${deckId}/cards/${card.id}`;

  useEffect(() => {  // again when the tags or quantity change: a proxy drops its copies and a smaller quantity trims them
    if (proxy) { setData({ quantity: card.quantity, rows: [] }); return; }
    let live = true;  // a slower answer for an earlier state must not replace this one
    api<Copies>(`${url}/copies`).then((d) => { if (!live) return; setData(d); setWant(Object.fromEntries(d.rows.map((r) => [r.id, r.here]))); setErr(""); }).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [url, proxy, card.quantity]);

  const rows = data?.rows ?? [], limit = data?.quantity ?? card.quantity;
  const total = Object.values(want).reduce((n, q) => n + q, 0);
  const max = (r: Copy) => r.here + r.free;  // what no other card holds
  const set = (r: Copy, q: number) => setWant((w) => ({ ...w, [r.id]: Math.max(0, Math.min(max(r), q)) }));
  const fill = () => { let left = limit; const next: Record<number, number> = {}; for (const r of rows) { next[r.id] = Math.min(max(r), left); left -= next[r.id]; } setWant(next); };
  const save = () => api(`${url}/assign`, { method: "PUT", body: JSON.stringify({ items: rows.filter((r) => want[r.id] > 0).map((r) => ({ collection_id: r.id, quantity: want[r.id] })) }) })
    .then(() => { onChanged(); onClose(); }).catch((e) => setErr(e.message));
  const patchTags = (tags: string[]) => api(url, { method: "PATCH", body: JSON.stringify({ tags }) }).then(() => onChanged()).catch((e) => setErr(e.message));
  const addTag = () => { const t = tag.trim().toLowerCase(); if (t && !card.tags.includes(t)) patchTags([...card.tags, t]); setTag(""); };

  const setPrinting = (scryfall_id: string) => api(url, { method: "PATCH", body: JSON.stringify({ scryfall_id }) })
    .then(() => { setPicking(false); onChanged(); }).catch((e) => { setPicking(false); setErr(e.message); });
  const other = card.scryfall_id && !rows.some((r) => r.scryfall_id === card.scryfall_id) ? rows[0] : undefined;  // a printing you own that the deck does not prefer

  return picking ? <PrintingDialog deckId={deckId} oracleId={card.oracle_id} name={card.name} current={card.scryfall_id} onPick={setPrinting} onClose={() => setPicking(false)} /> : (
    <Modal title={`Copies and tags of ${card.name}`} onClose={onClose}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">{card.name}</h2><StatusBadge status={card.status} />
        <button className="btn-ghost !py-1 text-xs" onClick={() => setPicking(true)}>Switch printing…</button>
        <span className="ml-auto text-sm text-mute tabular-nums">The deck has {card.quantity} · {card.owned} owned</span>
      </div>

      {other && <p className="mb-4 rounded-xl border border-dashed border-line p-3 text-sm text-mute">
        You own another printing: <span className="uppercase">{other.set_code}</span> #{other.collector_number}.{" "}
        <button className="text-accent hover:underline" onClick={() => setPrinting(other.scryfall_id)}>Use this printing</button>
      </p>}

      <section aria-label="Tags" className="mb-5">
        <h3 className="mb-2 text-sm font-semibold">Tags</h3>
        <div className="flex flex-wrap items-center gap-2">
          {card.tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 rounded-md bg-raised py-0.5 pl-2 pr-1 text-xs">
              {t}<button className="flex size-4 items-center justify-center rounded hover:bg-line" aria-label={`Remove the tag ${t}`} onClick={() => patchTags(card.tags.filter((x) => x !== t))}><IconX className="size-3" /></button>
            </span>
          ))}
          <input className="field !w-44 !py-1 text-xs" placeholder="Add a tag…" aria-label="Add a tag" maxLength={30} value={tag} onChange={(e) => setTag(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addTag(); }} />
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-mute" title="A proxy is in the deck but is not a real copy: it never counts as missing and uses no copy of your collection">
            <input type="checkbox" checked={proxy} onChange={(e) => patchTags(e.target.checked ? [...card.tags, "proxy"] : card.tags.filter((t) => t !== "proxy"))} className="accent-[var(--color-accent)]" />This is a proxy
          </label>
        </div>
      </section>

      <section aria-label="Copies">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">Copies from your collection</h3>
          {!proxy && <span className="text-sm text-mute tabular-nums">{total} of {limit} assigned</span>}
          {!proxy && rows.length > 0 && <span className="ml-auto flex gap-2">
            <button className="btn-ghost !py-1 text-xs" onClick={fill} title="Use the free copies, the preferred printing first">Fill with free copies</button>
            <button className="btn-ghost !py-1 text-xs" onClick={() => setWant(Object.fromEntries(rows.map((r) => [r.id, 0])))}>Clear</button>
          </span>}
        </div>
        {proxy && <p className="rounded-xl border border-dashed border-line p-4 text-sm text-mute">A proxy uses no copies. Untick “This is a proxy” to assign real ones.</p>}
        {!proxy && data && rows.length === 0 && <p className="rounded-xl border border-dashed border-line p-4 text-sm text-mute">You do not own this card (proxy copies in your collection do not count).</p>}
        <ul className="divide-y divide-line">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
              <div className="min-w-[180px] flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                  <span className="uppercase">{r.set_code}</span><span className="text-mute">#{r.collector_number}</span>
                  {r.finish !== "nonfoil" && <Badge foil>{FINISH[r.finish]}</Badge>}
                  {r.scryfall_id === card.scryfall_id && <Badge>Preferred</Badge>}
                </div>
                <div className="text-xs text-mute">{LANGS[r.language] ?? r.language} · {r.condition} · {r.location || "no location"} · {eur(r.price)}</div>
                <div className="text-xs text-mute tabular-nums">
                  {r.quantity} owned · {r.free} free{r.elsewhere.length > 0 && <> · <span className="text-gold">in {r.elsewhere.map((e) => `${e.deck_id === deckId ? "this deck (other board)" : e.name} (${e.quantity})`).join(", ")}</span></>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className={STEP} aria-label={`One less from ${r.set_code} ${r.collector_number}`} disabled={!want[r.id]} onClick={() => set(r, want[r.id] - 1)}><IconMinus className="size-4" /></button>
                <span className="w-6 text-center text-sm font-medium tabular-nums" aria-live="polite">{want[r.id] ?? 0}</span>
                <button className={STEP} aria-label={`One more from ${r.set_code} ${r.collector_number}`} disabled={(want[r.id] ?? 0) >= max(r) || total >= limit} onClick={() => set(r, (want[r.id] ?? 0) + 1)}><IconPlus className="size-4" /></button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Close</button>
        {!proxy && rows.length > 0 && <button className="btn-primary" onClick={save}>Save copies</button>}
      </div>
    </Modal>
  );
}
