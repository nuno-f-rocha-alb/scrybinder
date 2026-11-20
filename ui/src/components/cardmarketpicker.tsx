import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { IconAlertTriangle, IconChevronLeft } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { Badge, Modal, cardmarketUrl, openExternal } from "./ui";

type Candidate = {
  id_product: number; name: string; id_expansion: number; date_added: string | null; expansion_size: number; set_hint: string | null;
  trend: number | null; trend_foil: number | null; used_by: string[];
};
/** The part of the card details the picker needs; the server answers a pick with the whole details, which the caller keeps. */
type Printing = { id: string; name: string; set_code: string; collector_number: string; cm_product: number | null; cm_source: string | null };

/** Choose the Cardmarket product of a printing Scryfall has none for: search the product list by name (or paste an id), see each product's
 * expansion, date and price, and which printings already hold it. The choice is kept across updates and prices the card. */
export default function CardmarketPicker<D extends Printing>({ d, onPicked, onBack }: { d: D; onPicked: (d: D) => void; onBack: () => void }) {
  const [q, setQ] = useState(d.name.split(" // ")[0]);
  const [rows, setRows] = useState<Candidate[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api<Candidate[]>("/cardmarket/products?" + qs({ q, card: d.id })).then((r) => { if (live) { setRows(r); setErr(""); } })
        .catch((e) => { if (live) { setRows([]); setErr((e as Error).message); } });
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, d.id]);

  const save = (idProduct: number | null) => {
    setBusy(true);
    api<D>(`/cards/${d.id}/cardmarket`, { method: "PUT", body: JSON.stringify({ id_product: idProduct }) })
      .then(onPicked).catch((e) => setErr((e as Error).message)).finally(() => setBusy(false));
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button className="btn-ghost" onClick={onBack}><IconChevronLeft className="size-4" />Back to the card</button>
        {d.cm_source === "manual" && <button className="btn-ghost" disabled={busy} onClick={() => save(null)}>Remove my choice</button>}
      </div>
      <h2 className="mt-3 text-xl font-semibold tracking-tight">Cardmarket product for {d.name}</h2>
      <p className="mt-1 text-sm text-mute">
        {d.set_code.toUpperCase()} #{d.collector_number}. Cardmarket's list has no collector numbers, so pick the product whose expansion and price match what you see on
        Cardmarket (use <em>Open</em> to check). The product you choose prices this printing and is kept when prices update.
      </p>
      <label className="mt-4 block text-xs font-medium text-mute">
        <span className="mb-1 block">Search by name, or paste a product id</span>
        <input className="field w-full" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      </label>
      {err && <p role="alert" className="mt-3 text-sm text-danger">{err}</p>}
      {rows && !err && rows.length === 0 && <p className="mt-3 text-sm text-mute">No product with that name. Cardmarket does not sell every card as a single (tokens and art cards, for one), and a card it added today shows up after the next daily update.</p>}
      {rows && rows.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-xl border border-line" aria-label="Cardmarket products">
          {rows.map((r) => (
            <li key={r.id_product} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-sm font-medium">{r.name}{r.id_product === d.cm_product && <Badge>Current</Badge>}</div>
                <div className="text-xs text-mute">
                  Expansion {r.id_expansion} · {r.expansion_size} products{r.set_hint && <> · holds cards of {r.set_hint.toUpperCase()}</>}{r.date_added && <> · added {r.date_added}</>}
                </div>
                {r.used_by.length > 0 && (
                  <div className="mt-0.5 flex items-center gap-1 text-xs text-gold"><IconAlertTriangle className="size-3.5 shrink-0" aria-hidden />Already used by {r.used_by.join(", ")}</div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <div className="text-right text-xs tabular-nums"><div>Trend {eur(r.trend)}</div><div className="text-mute">Foil {eur(r.trend_foil)}</div></div>
                <button className="btn-ghost" onClick={() => openExternal(cardmarketUrl(r.id_product))} aria-label={`Open ${r.name} (product ${r.id_product}) on Cardmarket`}>Open ↗</button>
                <button className="btn-primary" disabled={busy || r.id_product === d.cm_product} onClick={() => save(r.id_product)}>Choose</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type CmInfo = Printing & { cm_enabled: boolean };

/** A link that opens the picker for a printing, for places that do not show the whole card details (the collection's edit drawer).
 * Nothing shows when Cardmarket prices are off or Scryfall already gave the printing its product. `onChanged` runs after a choice is saved. */
export function CardmarketLink({ printId, onChanged }: { printId: string; onChanged: () => void }) {
  const [d, setD] = useState<CmInfo | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    api<CmInfo>(`/cards/${printId}/details`).then((r) => live && setD(r)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [printId]);
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };  // not the drawer under it as well
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [open]);
  if (!d || !d.cm_enabled || d.cm_source === "scryfall") return null;
  return (
    <>
      <button className="cursor-pointer text-xs text-accent hover:underline" onClick={() => setOpen(true)}>{d.cm_product ? "Change Cardmarket product…" : "Find Cardmarket product…"}</button>
      {open && createPortal(
        <Modal title="Cardmarket product" onClose={() => setOpen(false)}>
          <CardmarketPicker d={d} onPicked={() => { setOpen(false); onChanged(); }} onBack={() => setOpen(false)} />
        </Modal>, document.body)}
    </>
  );
}
