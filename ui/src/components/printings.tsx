import { useEffect, useMemo, useState } from "react";
import { Select } from "./select";
import { api, eur, FINISH } from "../api";
import { Badge, CardImg, HoverZoom, Modal } from "./ui";

export type Print = {
  id: string; set_code: string; set_name: string; collector_number: string; released_at: string; rarity: string;
  finishes: string; eur: number | null; eur_foil: number | null; eur_etched: number | null; owned: number; free: number;
  owned_finish: Record<string, number>;  // what you own of this printing, per finish
};
export type Finish = "nonfoil" | "foil" | "etched";

const priceOf = (p: Print, f: Finish) => (f === "foil" ? p.eur_foil : f === "etched" ? p.eur_etched : p.eur);
const finishesOf = (p: Print): Finish[] => { const f = (p.finishes ? JSON.parse(p.finishes) : []) as Finish[]; return f.length ? f : ["nonfoil"]; };
const BUTTON: Record<Finish, string> = { nonfoil: "Select", foil: "Select foil", etched: "Select etched" };

/** Pick the printing a deck card prefers, and its finish: the ones you own and no other deck holds first, then the rest. Each printing has one
 * button per finish it comes in. `current` / `currentFinish` are the chosen ones (null = not chosen). */
export default function PrintingDialog({ deckId, oracleId, name, current, currentFinish, onPick, onClose }: {
  deckId: number; oracleId: string; name: string; current: string | null; currentFinish: string | null; onPick: (scryfallId: string, finish: Finish) => void; onClose: () => void;
}) {
  const [prints, setPrints] = useState<Print[] | null>(null);
  const [set, setSet] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api<Print[]>(`/cards/prints?oracle_id=${encodeURIComponent(oracleId)}&deck=${deckId}`).then(setPrints).catch((e) => setErr(e.message)); }, [oracleId, deckId]);

  const sets = useMemo(() => [...new Map((prints ?? []).map((p) => [p.set_code, p.set_name])).entries()], [prints]);
  const shown = (prints ?? []).filter((p) => !set || p.set_code === set);
  const owned = shown.filter((p) => p.free > 0), rest = shown.filter((p) => p.free <= 0);
  const cheap = useMemo(() => {  // the lowest price of any printing in any of its finishes
    let best: { id: string; finish: Finish; price: number } | null = null;
    for (const p of prints ?? []) for (const f of finishesOf(p)) { const v = priceOf(p, f); if (v != null && (!best || v < best.price)) best = { id: p.id, finish: f, price: v }; }
    return best;
  }, [prints]);

  const row = (p: Print) => {
    const mine = Object.entries(p.owned_finish ?? {}).map(([f, q]) => `${q} ${FINISH[f]?.toLowerCase() ?? f}`).join(", ");
    return (
      <li key={p.id} className="flex items-center gap-4 py-2.5">
        <HoverZoom className="w-16 shrink-0" zoom={<CardImg id={p.id} size="large" />}><CardImg id={p.id} size="small" /></HoverZoom>
        <div className="min-w-0 flex-1 text-sm">
          <div className="truncate font-medium">{p.set_name}</div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-mute">
            <span className="uppercase">{p.set_code}</span><span>#{p.collector_number}</span><span className="capitalize">{p.rarity}</span><span>{p.released_at.slice(0, 4)}</span>
            {p.id === current && <Badge>{currentFinish ? `Current · ${FINISH[currentFinish]}` : "Current"}</Badge>}
            {p.owned > 0 && <span className="text-gold">you own {mine}{p.free < p.owned && ` (${p.free} free)`}</span>}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {finishesOf(p).map((f) => (
            <button key={f} className="btn-ghost !flex-col !items-end !gap-0 !py-1 text-xs" disabled={p.id === current && f === currentFinish} onClick={() => onPick(p.id, f)}
              aria-label={`${BUTTON[f]} ${p.set_name} ${p.collector_number}`}>
              <span>{BUTTON[f]}</span><span className="text-[10.5px] font-normal text-mute tabular-nums">{eur(priceOf(p, f))}</span>
            </button>
          ))}
        </div>
      </li>
    );
  };

  return (
    <Modal title={`Switch printing of ${name}`} onClose={onClose}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Switch printing</h2><span className="text-mute">{name}</span>
        <Select className="field !w-52 !py-1 ml-auto text-xs" aria-label="Filter by set" value={set} onChange={(e) => setSet(e.target.value)}>
          <option value="">All sets</option>
          {sets.map(([code, n]) => <option key={code} value={code}>{n} ({code.toUpperCase()})</option>)}
        </Select>
      </div>
      {!prints && !err && <p className="text-sm text-mute">Loading…</p>}
      {owned.length > 0 && <section aria-label="Owned">
        <h3 className="text-sm font-semibold text-gold">Owned <span className="font-normal text-mute">· in your collection and in no other deck</span></h3>
        <ul className="divide-y divide-line">{owned.map(row)}</ul>
      </section>}
      {rest.length > 0 && <section aria-label="Other printings" className={owned.length ? "mt-5 border-t border-line pt-4" : ""}>
        {owned.length > 0 && <h3 className="text-sm font-semibold">Other printings</h3>}
        <ul className="divide-y divide-line">{rest.map(row)}</ul>
      </section>}
      {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={!cheap} onClick={() => cheap && onPick(cheap.id, cheap.finish)}>Use cheapest</button>
      </div>
    </Modal>
  );
}
