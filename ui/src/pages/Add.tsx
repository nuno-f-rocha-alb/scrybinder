import { useEffect, useState } from "react";
import { Combo, Select } from "../components/select";
import { IconSearch } from "@tabler/icons-react";
import { api, CONDITIONS, eur, FINISH, LANGS, Print, qs } from "../api";
import { Badge, CardImg, ExtLinks, Field, Modal, useToast } from "../components/ui";
import { GridControls, sourceFor, useCardGrid } from "../components/cardgrid";
import DeckPicker from "../components/deckpicker";
import CardDetails from "../components/carddetails";

type Hit = { oracle_id: string | null; name: string; prints: number; sample_id: string };
type P = Print & { owned: number; free: number; owned_finish: Record<string, number> };
const LIMIT = 50;  // what the server returns at most
const store = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const finishesOf = (p: P): string[] => { const f = JSON.parse(p.finishes || "[]") as string[]; return f.length ? f : ["nonfoil"]; };
const priceOf = (p: P, finish: string) => (finish === "foil" ? p.eur_foil : finish === "etched" ? p.eur_etched : p.eur);

/** One card: pick the printing, the finish, how many and where, and add it. It stays open so another finish or printing can follow. */
function AddDialog({ hit, locs, toast, onClose }: { hit: Hit; locs: string[]; toast: (m: string, err?: boolean) => void; onClose: () => void }) {
  const [prints, setPrints] = useState<P[] | null>(null);
  const [picked, setPicked] = useState<P | null>(null);
  const [form, setForm] = useState({ finish: "nonfoil", quantity: 1, condition: "NM", language: "en", location: store("scrybinder.loc", ""), price: "" });
  const [toDeck, setToDeck] = useState<P | null>(null);
  const [details, setDetails] = useState<string | null>(null);

  const load = (keep?: string) => api<P[]>("/cards/prints?" + qs(hit.oracle_id ? { oracle_id: hit.oracle_id } : { name: hit.name })).then((r) => {
    setPrints(r);
    setPicked((cur) => r.find((p) => p.id === (keep ?? cur?.id ?? hit.sample_id)) ?? r[0] ?? null);
  }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [hit.oracle_id, hit.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // the finish must be one this printing comes in
    if (picked) setForm((f) => (finishesOf(picked).includes(f.finish) ? f : { ...f, finish: finishesOf(picked)[0] }));
  }, [picked]);

  const add = async () => {
    if (!picked) return;
    try {
      try { localStorage.setItem("scrybinder.loc", form.location); } catch { /* no storage */ }
      await api("/collection", { method: "POST", body: JSON.stringify({
        scryfall_id: picked.id, finish: form.finish, quantity: form.quantity, condition: form.condition,
        language: form.language, location: form.location, purchase_price: form.price === "" ? null : +form.price }) });
      toast(`Added: ${form.quantity}× ${picked.name} (${picked.set_code.toUpperCase()} #${picked.collector_number})`);
      load(picked.id);  // "you own" updates
    } catch (e) { toast((e as Error).message, true); }
  };
  const mine = (p: P) => Object.entries(p.owned_finish ?? {}).map(([f, q]) => `${q} ${FINISH[f]?.toLowerCase() ?? f}`).join(", ");

  return (
    <Modal title={hit.name} onClose={onClose} wide>
      <div onKeyDown={(e) => e.key === "Enter" && picked && !["TEXTAREA", "BUTTON"].includes((e.target as HTMLElement).tagName) && add()}>
        <h2 className="mb-4 text-lg font-semibold">{hit.name}</h2>
        {!prints && <p className="text-mute">Loading…</p>}
        {prints && picked && (
          <div className="grid gap-6 md:grid-cols-[260px_minmax(0,1fr)]">
            <div>
              <CardImg id={picked.id} size="large" className="shadow-lg shadow-black/50" />
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs"><ExtLinks id={picked.id} cardmarketId={picked.cardmarket_id} />
                <button className="cursor-pointer text-accent hover:underline" onClick={() => setDetails(picked.id)}>Card details</button></div>
            </div>
            <div className="min-w-0 space-y-4">
              <div>
                <div className="font-medium">{picked.set_name} <span className="text-mute">· {picked.set_code.toUpperCase()} #{picked.collector_number} · {picked.released_at?.slice(0, 4)}</span></div>
                <div className="text-sm text-mute">{eur(priceOf(picked, form.finish))}{picked.owned > 0 && <span className="ml-3 text-gold">you own {mine(picked)}</span>}</div>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Field label="Finish"><Select className="field" value={form.finish} onChange={(e) => setForm({ ...form, finish: e.target.value })}>
                  {finishesOf(picked).map((f) => <option key={f} value={f}>{FINISH[f] ?? f}</option>)}</Select></Field>
                <Field label="Quantity"><input type="number" min={1} className="field" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Math.max(1, +e.target.value) })} /></Field>
                <Field label="Condition"><Select className="field" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
                  {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</Select></Field>
                <Field label="Language"><Select className="field" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                  {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Location"><Combo className="field" suggestions={locs} value={form.location} onChange={(v) => setForm({ ...form, location: v })} placeholder="e.g. Box 3" /></Field>
                <Field label="Purchase price (€, optional)"><input type="number" step="0.01" min={0} className="field" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn-primary" onClick={add}>Add (Enter)</button>
                <button className="btn-ghost" onClick={() => setToDeck(picked)}>Add to a deck…</button>
                <button className="btn-ghost" onClick={onClose}>Close</button>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Printings <span className="font-normal text-mute">({prints.length})</span></h3>
                <div className="grid max-h-72 grid-cols-[repeat(auto-fill,minmax(96px,1fr))] content-start gap-2 overflow-y-auto pr-1">
                  {prints.map((p) => (
                    <button key={p.id} onClick={() => setPicked(p)} aria-pressed={picked.id === p.id} title={`${p.set_name} #${p.collector_number}`}
                      className={`cursor-pointer rounded-lg p-1 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-accent ${picked.id === p.id ? "bg-accent-soft ring-2 ring-accent" : "hover:bg-raised"}`}>
                      <CardImg id={p.id} size="small" />
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]"><b>{p.set_code.toUpperCase()}</b><span className="text-mute">#{p.collector_number}</span>
                        {p.full_art ? <Badge>Full art</Badge> : null}</div>
                      {p.owned > 0 && <div className="text-[11px] text-gold">×{p.owned}</div>}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        {prints && !picked && <p className="text-mute">No printings found.</p>}
      </div>
      {toDeck && <DeckPicker oracleId={toDeck.oracle_id} scryfallId={toDeck.id} name={toDeck.name} onClose={() => setToDeck(null)} onDone={(n) => { setToDeck(null); toast(`${toDeck.name} added to ${n}`); }} />}
      {details && <CardDetails printId={details} onClose={() => setDetails(null)} />}
    </Modal>
  );
}

export default function Add() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [searched, setSearched] = useState("");  // the query whose result has arrived: avoids "No results" while loading
  const [open, setOpen] = useState<Hit | null>(null);
  const [locs, setLocs] = useState<string[]>([]);
  const { toast, node } = useToast();
  const grid = useCardGrid();

  useEffect(() => { api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location).filter(Boolean))); }, []);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    let live = true;  // a slower earlier answer must not replace a newer one
    const t = setTimeout(() => api<Hit[]>("/cards/search?" + qs({ q, limit: LIMIT })).then((h) => { if (live) { setHits(h); setSearched(q); } }).catch(() => { if (live) { setHits([]); setSearched(q); } }), 200);
    return () => { live = false; clearTimeout(t); };
  }, [q]);

  return (
    <div>
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">Add cards</h1>
      <div className="mb-5 flex flex-wrap items-center gap-4">
        <div className="relative w-full max-w-xl">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
          <input autoFocus className="field pl-9" placeholder="Card name (e.g. sol ring)…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Card name" />
        </div>
        {hits.length > 0 && <GridControls g={grid} />}
      </div>
      {!q.trim() && <div className="flex h-72 items-center justify-center rounded-2xl border border-dashed border-line px-6 text-center text-sm text-mute">Search for a card by name: pick one to choose its printing, finish and how many to add.</div>}
      {q.trim() && searched === q && hits.length === 0 && <p className="text-sm text-mute">No results.</p>}
      {hits.length > 0 && (
        <>
          <div ref={grid.setGridEl} className="grid content-start gap-4" style={grid.style}>
            {hits.map((h) => (
              <button key={h.oracle_id ?? h.name} onClick={() => setOpen(h)} className="group cursor-pointer text-left outline-none" title={`${h.name} — choose a printing`}>
                <div className="relative transition-transform duration-200 group-hover:-translate-y-1 group-focus-visible:-translate-y-1">
                  <CardImg id={h.sample_id} size={sourceFor(grid.tilePx)} className="shadow-lg shadow-black/50 group-focus-visible:ring-2 group-focus-visible:ring-accent" />
                  {h.prints > 1 && <span className="absolute right-1.5 top-1.5 rounded-full bg-black/80 px-2 py-0.5 text-xs font-semibold tabular-nums">{h.prints} printings</span>}
                </div>
                <div className="mt-2 truncate text-sm font-medium">{h.name}</div>
              </button>
            ))}
          </div>
          {hits.length >= LIMIT && <p className="mt-4 text-sm text-mute">Showing the first {LIMIT} cards: type more of the name to narrow it down.</p>}
        </>
      )}
      {open && <AddDialog hit={open} locs={locs} toast={toast} onClose={() => setOpen(null)} />}
      {node}
    </div>
  );
}
