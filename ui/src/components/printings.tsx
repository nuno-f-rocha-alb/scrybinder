import { useEffect, useMemo, useState } from "react";
import { api, eur } from "../api";
import { Badge, CardImg, Modal } from "./ui";

export type Print = {
  id: string; set_code: string; set_name: string; collector_number: string; released_at: string; rarity: string;
  finishes: string; eur: number | null; eur_foil: number | null; eur_etched: number | null; owned: number; free: number;
};

const cheapest = (p: Print) => Math.min(...[p.eur, p.eur_foil, p.eur_etched].filter((v): v is number => v != null), Infinity);

/** Pick the printing a deck card prefers: the ones you own and no other deck holds first, then the rest, each with image, price and finishes.
 * `current` is the chosen one (null = any). */
export default function PrintingDialog({ deckId, oracleId, name, current, onPick, onClose }: {
  deckId: number; oracleId: string; name: string; current: string | null; onPick: (scryfallId: string) => void; onClose: () => void;
}) {
  const [prints, setPrints] = useState<Print[] | null>(null);
  const [set, setSet] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api<Print[]>(`/cards/prints?oracle_id=${encodeURIComponent(oracleId)}&deck=${deckId}`).then(setPrints).catch((e) => setErr(e.message)); }, [oracleId, deckId]);

  const sets = useMemo(() => [...new Map((prints ?? []).map((p) => [p.set_code, p.set_name])).entries()], [prints]);
  const shown = (prints ?? []).filter((p) => !set || p.set_code === set);
  const owned = shown.filter((p) => p.free > 0), rest = shown.filter((p) => p.free <= 0);
  const cheap = useMemo(() => (prints ?? []).filter((p) => cheapest(p) < Infinity).sort((a, b) => cheapest(a) - cheapest(b))[0], [prints]);

  const row = (p: Print) => {
    const fin = p.finishes ? (JSON.parse(p.finishes) as string[]) : [];
    return (
      <li key={p.id} className="flex items-center gap-4 py-2.5">
        <div className="w-16 shrink-0"><CardImg id={p.id} size="small" /></div>
        <div className="min-w-0 flex-1 text-sm">
          <div className="truncate font-medium">{p.set_name}</div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-mute">
            <span className="uppercase">{p.set_code}</span><span>#{p.collector_number}</span><span className="capitalize">{p.rarity}</span><span>{p.released_at.slice(0, 4)}</span>
            {fin.includes("foil") && <Badge foil>Foil</Badge>}{fin.includes("etched") && <Badge foil>Etched</Badge>}
            {p.id === current && <Badge>Current</Badge>}
            {p.owned > 0 && <span className="text-gold">you own {p.owned}{p.free < p.owned && ` (${p.free} free)`}</span>}
          </div>
          <div className="text-xs text-mute tabular-nums">
            {eur(p.eur)}{p.eur_foil != null && <> · foil {eur(p.eur_foil)}</>}{p.eur_etched != null && <> · etched {eur(p.eur_etched)}</>}
          </div>
        </div>
        <button className="btn-ghost !py-1 text-xs" disabled={p.id === current} onClick={() => onPick(p.id)} aria-label={`Select ${p.set_name} ${p.collector_number}`}>Select</button>
      </li>
    );
  };

  return (
    <Modal title={`Switch printing of ${name}`} onClose={onClose}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Switch printing</h2><span className="text-mute">{name}</span>
        <select className="field !w-52 !py-1 ml-auto text-xs" aria-label="Filter by set" value={set} onChange={(e) => setSet(e.target.value)}>
          <option value="">All sets</option>
          {sets.map(([code, n]) => <option key={code} value={code}>{n} ({code.toUpperCase()})</option>)}
        </select>
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
        <button className="btn-primary" disabled={!cheap} onClick={() => cheap && onPick(cheap.id)}>Use cheapest</button>
      </div>
    </Modal>
  );
}
