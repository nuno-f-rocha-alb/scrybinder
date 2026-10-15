import { useEffect, useState } from "react";
import { IconSearch } from "@tabler/icons-react";
import { api, CONDITIONS, eur, FINISH, LANGS, Print, qs } from "../api";
import { Badge, CardImg, ExtLinks, Field, useToast } from "../components/ui";
import { GridControls, sourceFor, useCardGrid } from "../components/cardgrid";
import { nameAndLinks, useContextMenu } from "../components/contextmenu";
import DeckPicker from "../components/deckpicker";
import CardDetails from "../components/carddetails";

type Hit = { oracle_id: string | null; name: string; prints: number; sample_id: string };
const store = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };

export default function Add() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [searched, setSearched] = useState("");  // the query whose result has arrived: avoids "No results" while loading
  const [prints, setPrints] = useState<Print[]>([]);
  const [picked, setPicked] = useState<Print | null>(null);
  const [form, setForm] = useState({ finish: "nonfoil", quantity: 1, condition: "NM", language: "en", location: store("scrybinder.loc", ""), price: "" });
  const [locs, setLocs] = useState<string[]>([]);
  const { toast, node } = useToast();
  const menu = useContextMenu();
  const [toDeck, setToDeck] = useState<Print | null>(null);
  const [details, setDetails] = useState<string | null>(null);
  const grid = useCardGrid();

  useEffect(() => { api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location).filter(Boolean))); }, []);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => api<Hit[]>("/cards/search?" + qs({ q })).then((h) => { setHits(h); setSearched(q); }).catch(() => { setHits([]); setSearched(q); }), 200);
    return () => clearTimeout(t);
  }, [q]);

  const open = (h: Hit) => {
    setPicked(null);
    api<Print[]>("/cards/prints?" + qs(h.oracle_id ? { oracle_id: h.oracle_id } : { name: h.name })).then(setPrints);
  };
  const finishes = (p: Print): string[] => (JSON.parse(p.finishes || "[]") as string[]).map((f) => (f === "nonfoil" ? "nonfoil" : f));
  const pick = (p: Print) => {
    setPicked(p);
    const fs = finishes(p);
    setForm((f) => ({ ...f, finish: fs.includes(f.finish) ? f.finish : fs[0] ?? "nonfoil" }));
  };
  const add = async () => {
    if (!picked) return;
    try {
      try { localStorage.setItem("scrybinder.loc", form.location); } catch { /* no storage */ }
      await api("/collection", { method: "POST", body: JSON.stringify({
        scryfall_id: picked.id, finish: form.finish, quantity: form.quantity, condition: form.condition,
        language: form.language, location: form.location, purchase_price: form.price === "" ? null : +form.price }) });
      toast(`Added: ${form.quantity}× ${picked.name} (${picked.set_code.toUpperCase()} #${picked.collector_number})`);
    } catch (e) { toast((e as Error).message, true); }
  };
  const quickAdd = (p: Print) => {  // one copy, near mint, English, in the location typed in the form
    const fs = finishes(p);
    api("/collection", { method: "POST", body: JSON.stringify({ scryfall_id: p.id, finish: fs.includes("nonfoil") ? "nonfoil" : fs[0] ?? "nonfoil", quantity: 1, location: form.location }) })
      .then(() => toast(`Added: 1× ${p.name} (${p.set_code.toUpperCase()} #${p.collector_number})`)).catch((e) => toast(e.message, true));
  };
  const price = (p: Print) => (form.finish === "foil" ? p.eur_foil : form.finish === "etched" ? p.eur_etched : p.eur);

  return (
    <div onKeyDown={(e) => e.key === "Enter" && picked && (e.target as HTMLElement).tagName !== "TEXTAREA" && add()}>
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">Add cards</h1>
      <div className="mb-5 max-w-[1500px]">
        <div className="relative max-w-xl">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
          <input autoFocus className="field pl-9" placeholder="Card name (e.g. lightning bolt)…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Card name" />
        </div>
        {(hits.length > 0 || (q.trim() && searched === q)) && (
          <ul className="mt-3 flex max-h-28 flex-wrap gap-2 overflow-y-auto">
            {hits.map((h) => (
              <li key={h.oracle_id ?? h.name}>
                <button onClick={() => open(h)} className="flex cursor-pointer items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm hover:border-accent hover:bg-raised">
                  <span>{h.name}</span><span className="text-xs text-mute">{h.prints}</span>
                </button>
              </li>
            ))}
            {hits.length === 0 && <li className="px-1 py-1.5 text-sm text-mute">No results.</li>}
          </ul>
        )}
      </div>
      <div className="grid max-w-[1500px] gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">

        {prints.length === 0 ? (
          <div className="flex h-72 items-center justify-center rounded-2xl border border-dashed border-line px-6 text-center text-sm text-mute">
            {hits.length ? "Pick a card from the list to see its printings." : "Search for a card by name to see all its printings."}
          </div>
        ) : (
        <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center justify-end gap-3"><GridControls g={grid} /></div>
        <div ref={grid.setGridEl} className="grid max-h-[75vh] content-start gap-4 overflow-y-auto pr-1" style={grid.style}>
          {prints.map((p) => (
            <button key={p.id} onClick={() => pick(p)} onContextMenu={(e) => menu.open(e, [
              { label: "Choose this printing", onSelect: () => pick(p) },
              { label: "Add one to the collection", onSelect: () => quickAdd(p) },
              { label: "View details", onSelect: () => setDetails(p.id) },
              { label: "Add to a deck…", onSelect: () => setToDeck(p) },
              "sep", ...nameAndLinks(p.name, p.id, p.cardmarket_id, toast)])} aria-pressed={picked?.id === p.id}
              className={`cursor-pointer rounded-xl p-1.5 text-left transition ${picked?.id === p.id ? "bg-accent-soft ring-2 ring-accent" : "hover:bg-raised"}`}>
              <CardImg id={p.id} size={sourceFor(grid.tilePx)} />
              <div className="mt-1.5 flex flex-wrap items-center gap-1 text-xs">
                <b>{p.set_code.toUpperCase()}</b><span className="text-mute">#{p.collector_number}</span>
                {p.full_art ? <Badge>Full art</Badge> : null}
              </div>
              <div className="truncate text-[11px] text-mute">{p.set_name} · {p.released_at?.slice(0, 4)}</div>
            </button>
          ))}
        </div>
        </div>
        )}

        <aside className="rounded-2xl border border-line bg-surface p-4 lg:sticky lg:top-6 lg:self-start">
          {!picked ? <p className="text-sm text-mute">Pick the exact printing to add it to your collection.</p> : (
            <div className="space-y-3">
              <div><div className="font-semibold">{picked.name}</div>
                <div className="text-xs text-mute">{picked.set_name} · #{picked.collector_number} · {eur(price(picked))}</div>
                <div className="mt-1"><ExtLinks id={picked.id} cardmarketId={picked.cardmarket_id} /></div></div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Finish"><select className="field" value={form.finish} onChange={(e) => setForm({ ...form, finish: e.target.value })}>
                  {finishes(picked).map((f) => <option key={f} value={f}>{FINISH[f] ?? f}</option>)}</select></Field>
                <Field label="Quantity"><input type="number" min={1} className="field" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Math.max(1, +e.target.value) })} /></Field>
                <Field label="Condition"><select className="field" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
                  {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</select></Field>
                <Field label="Language"><select className="field" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                  {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
              </div>
              <Field label="Location"><input className="field" list="addlocs" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="e.g. Box 3" />
                <datalist id="addlocs">{locs.map((l) => <option key={l} value={l} />)}</datalist></Field>
              <Field label="Purchase price (€, optional)"><input type="number" step="0.01" min={0} className="field" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
              <button className="btn-primary w-full" onClick={add}>Add (Enter)</button>
            </div>
          )}
        </aside>
      </div>
      {toDeck && <DeckPicker oracleId={toDeck.oracle_id} scryfallId={toDeck.id} name={toDeck.name} onClose={() => setToDeck(null)} onDone={(n) => { setToDeck(null); toast(`${toDeck.name} added to ${n}`); }} />}
      {details && <CardDetails printId={details} onClose={() => setDetails(null)} />}
      {menu.node}
      {node}
    </div>
  );
}
