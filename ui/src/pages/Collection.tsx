import { useCallback, useEffect, useRef, useState } from "react";
import { IconChecklist, IconCheck, IconLayoutGrid, IconList, IconSearch } from "@tabler/icons-react";
import { api, CONDITIONS, Collection as Coll, eur, FINISH, LANGS, qs, Row, useGroup } from "../api";
import { Badge, CardImg, Drawer, ExtLinks, Field, Hit, Modal, useToast } from "../components/ui";
import { GridControls, sourceFor, useCardGrid } from "../components/cardgrid";
import { BulkBar, BulkDelete, BulkEdit } from "./Bulk";

const PAGE = 60;

export default function Collection({ initialSet, initialLocation }: { initialSet?: string; initialLocation?: string }) {
  const [q, setQ] = useState("");
  const [location, setLocation] = useState<string | undefined>(initialLocation);
  const [setCode, setSetCode] = useState(initialSet ?? "");
  const [group, setGroup] = useGroup();
  const [prog, setProg] = useState<{ owned: number; total: number; percent: number } | null>(null);
  const [finish, setFinish] = useState("");
  const [sort, setSort] = useState("name");
  const [view, setView] = useState<"grid" | "table">(() => (localStorage.getItem("scrybinder.view") as "grid") || "grid");
  const [data, setData] = useState<Coll | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const [locs, setLocs] = useState<{ location: string; cards: number }[]>([]);
  const [edit, setEdit] = useState<Row | null>(null);
  const grid = useCardGrid();
  const [selecting, setSelecting] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [bulk, setBulk] = useState<"edit" | "delete" | null>(null);
  const lastPick = useRef<number | null>(null);
  const filterKey = useRef("");
  const { toast, node } = useToast();

  const load = useCallback(() => {
    api<Coll>("/collection?" + qs({ q, set: setCode, location, finish, sort, limit })).then(setData).catch((e) => toast(e.message, true));
    api<{ location: string; cards: number }[]>("/locations").then(setLocs).catch(() => {});
  }, [q, setCode, location, finish, sort, limit]);
  useEffect(() => { const t = setTimeout(load, 150); return () => clearTimeout(t); }, [load]);
  useEffect(() => {
    if (!setCode) { setProg(null); return; }
    api<{ code: string; owned: number; total: number; percent: number }[]>("/sets?" + qs({ q: setCode, location, hide_empty: "false", group: group ? "true" : "false" }))
      .then((r) => setProg(r.find((s) => s.code === setCode) ?? null)).catch(() => setProg(null));
  }, [setCode, location, group, data?.total_cards]);
  useEffect(() => { setLimit(PAGE); }, [q, setCode, location, finish, sort]);
  useEffect(() => { setSel(new Set()); lastPick.current = null; }, [q, setCode, location, finish]);  // the selection belongs to the current filter
  useEffect(() => {
    if (!selecting) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape" && !bulk && !edit) { setSel(new Set()); setSelecting(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selecting, bulk, edit]);

  const rows = data?.rows ?? [];
  filterKey.current = JSON.stringify([q, setCode, location, finish]);
  const pick = (i: number, shift: boolean) => {
    setSel((s) => {
      const n = new Set(s);
      if (shift && lastPick.current !== null) {  // range from the last click: follows the state of the clicked row
        const [a, b] = [Math.min(lastPick.current, i), Math.max(lastPick.current, i)];
        const on = !s.has(rows[i].id);
        for (let k = a; k <= b; k++) on ? n.add(rows[k].id) : n.delete(rows[k].id);
      } else n.has(rows[i].id) ? n.delete(rows[i].id) : n.add(rows[i].id);
      return n;
    });
    lastPick.current = i;
  };
  const selectAll = () => {
    const key = filterKey.current;
    api<{ ids: number[] }>("/collection/ids?" + qs({ q, set: setCode, location, finish }))
      .then((r) => { if (key === filterKey.current) setSel(new Set(r.ids)); })  // the filter changed meanwhile: discard
      .catch((e) => toast(e.message, true));
  };
  const bulkDone = (m: string, err?: boolean) => { setBulk(null); if (!err) { setSel(new Set()); setSelecting(false); } toast(m, err); load(); };
  const open = (r: Row, i: number, e: React.MouseEvent) => (selecting ? pick(i, e.shiftKey) : setEdit(r));
  const setV = (v: "grid" | "table") => { setView(v); try { localStorage.setItem("scrybinder.view", v); } catch { /* no storage */ } };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Collection</h1>
          {data && (
            <p className="mt-1 text-sm text-mute">
              <b className="text-ink">{data.total_cards}</b> cards · {data.total_rows} rows ·{" "}
              value <b className="text-gold">{eur(data.total_value)}</b>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input className="field w-60 pl-9" placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          </div>
          <select className="field w-auto" value={location ?? "*"} aria-label="Location"
            onChange={(e) => setLocation(e.target.value === "*" ? undefined : e.target.value)}>
            <option value="*">All locations</option>
            {locs.map((l) => <option key={l.location} value={l.location}>{l.location || "(no location)"} · {l.cards}</option>)}
          </select>
          <select className="field w-auto" value={finish} onChange={(e) => setFinish(e.target.value)} aria-label="Finish">
            <option value="">All finishes</option>
            {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="name">Name</option><option value="set">Set</option>
            <option value="price">Price</option><option value="added">Most recent</option>
          </select>
          {view === "grid" && <GridControls g={grid} />}
          <button className={selecting ? "btn-primary" : "btn-ghost"} aria-pressed={selecting}
            onClick={() => { setSelecting(!selecting); setSel(new Set()); }}><IconChecklist className="size-4" />Select</button>
          <div className="flex rounded-lg border border-line bg-surface p-0.5">
            {([["grid", IconLayoutGrid, "Grid"], ["table", IconList, "Table"]] as const).map(([v, I, l]) => (
              <button key={v} onClick={() => setV(v)} aria-label={l} aria-pressed={view === v}
                className={`cursor-pointer rounded-md p-1.5 ${view === v ? "bg-accent-soft text-accent" : "text-mute hover:text-ink"}`}><I className="size-4" /></button>
            ))}
          </div>
        </div>
      </div>

      {setCode && (
        <div className="mb-4 flex flex-wrap items-center gap-4">
          <button onClick={() => setSetCode("")} className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-sm text-accent">
            Set: {setCode.toUpperCase()} <span aria-hidden>✕</span><span className="sr-only">remove filter</span>
          </button>
          {prog && <span className="text-sm tabular-nums text-mute"><b className="text-ink">{prog.owned}</b> / {prog.total} · {prog.percent.toLocaleString()} %</span>}
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="The same card with different art/frames counts as 1 in the totals">
            <input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)} className="accent-[var(--color-accent)]" />Group printings
          </label>
        </div>
      )}

      {data && data.rows.length === 0 && (
        <div className="rounded-2xl border border-dashed border-line p-16 text-center text-mute">
          {q || location !== undefined || finish ? "No cards match these filters." : "Your collection is empty. Add cards or import a ManaBox CSV."}
        </div>
      )}

      {data && view === "grid" && (
        <div ref={grid.setGridEl} className="grid gap-4" style={grid.style}>
          {data.rows.map((r, i) => (
            <button key={r.id} onClick={(e) => open(r, i, e)} aria-pressed={selecting ? sel.has(r.id) : undefined} className="group cursor-pointer text-left outline-none select-none">
              <div className="relative transition-transform duration-200 group-hover:-translate-y-1 group-focus-visible:-translate-y-1">
                <CardImg id={r.scryfall_id} size={sourceFor(grid.tilePx)} className={`shadow-lg shadow-black/50 group-focus-visible:ring-2 group-focus-visible:ring-accent ${sel.has(r.id) ? "ring-2 ring-accent brightness-75" : ""}`} />
                {selecting && <span aria-hidden className={`absolute bottom-1.5 left-1.5 flex size-6 items-center justify-center rounded-full border-2 ${sel.has(r.id) ? "border-accent bg-accent text-white" : "border-white/70 bg-black/50"}`}>{sel.has(r.id) && <IconCheck className="size-4" stroke={3} />}</span>}
                <span className="absolute right-1.5 top-1.5 rounded-full bg-black/80 px-2 py-0.5 text-xs font-semibold tabular-nums">×{r.quantity}</span>
                {r.finish !== "nonfoil" && <span className="absolute left-1.5 top-1.5"><Badge foil>{FINISH[r.finish].toUpperCase()}</Badge></span>}
              </div>
              <div className="mt-2 truncate text-sm font-medium">{r.name}</div>
              <div className="flex items-center justify-between gap-2 text-xs text-mute">
                <span className="min-w-0 truncate">{r.set_code.toUpperCase()} · {r.collector_number}{r.location && ` · ${r.location}`}</span>
                <span className="shrink-0 text-gold">{eur(r.price)}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {data && view === "table" && data.rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-xs uppercase tracking-wide text-mute">
              <tr>{selecting && <th className="w-10 px-3 py-2.5"><input type="checkbox" aria-label="Select all loaded rows" checked={rows.length > 0 && rows.every((r) => sel.has(r.id))}
                onChange={(e) => setSel(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())} className="accent-[var(--color-accent)]" /></th>}{["Qty", "Name", "Set", "No.", "Finish", "Cond.", "Language", "Location", "Price"].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={r.id} onClick={(e) => open(r, i, e)} className={`cursor-pointer select-none border-t border-line hover:bg-raised/60 ${sel.has(r.id) ? "bg-accent-soft" : ""}`}>
                  {selecting && <td className="px-3 py-2"><input type="checkbox" readOnly tabIndex={-1} aria-label={`Select ${r.name}`} checked={sel.has(r.id)} className="pointer-events-none accent-[var(--color-accent)]" /></td>}
                  <td className="px-3 py-2 tabular-nums">{r.quantity}</td>
                  <td className="px-3 py-2 font-medium">{r.name}</td>
                  <td className="px-3 py-2 text-mute">{r.set_code.toUpperCase()}</td>
                  <td className="px-3 py-2 text-mute">{r.collector_number}</td>
                  <td className="px-3 py-2">{r.finish === "nonfoil" ? "" : <Badge foil>{FINISH[r.finish]}</Badge>}</td>
                  <td className="px-3 py-2 text-mute">{r.condition}</td>
                  <td className="px-3 py-2 text-mute">{r.language}</td>
                  <td className="px-3 py-2 text-mute">{r.location}</td>
                  <td className="px-3 py-2 text-gold">{eur(r.price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total_rows > data.rows.length && (
        <div className="mt-6 text-center">
          <button className="btn-ghost" onClick={() => setLimit(limit + PAGE * 2)}>Show more ({data.rows.length} of {data.total_rows})</button>
        </div>
      )}

      {selecting && <BulkBar count={sel.size} total={data?.total_rows ?? 0} onSelectAll={selectAll} onClear={() => setSel(new Set())}
        onEdit={() => setBulk("edit")} onDelete={() => setBulk("delete")} onExit={() => { setSelecting(false); setSel(new Set()); }} />}
      {bulk === "edit" && <BulkEdit ids={[...sel]} locations={locs.map((l) => l.location).filter(Boolean)} onClose={() => setBulk(null)} onDone={bulkDone} />}
      {bulk === "delete" && <BulkDelete ids={[...sel]} preview={rows.filter((r) => sel.has(r.id)).slice(0, 6).map((r) => `${r.quantity}× ${r.name} (${r.set_code.toUpperCase()})`)} onClose={() => setBulk(null)} onDone={bulkDone} />}
      {edit && <EditModal row={edit} locations={locs.map((l) => l.location).filter(Boolean)} onClose={() => setEdit(null)}
        onDone={(m) => { setEdit(null); load(); toast(m); }} onError={(m) => toast(m, true)} />}
      {node}
    </div>
  );
}

function EditModal({ row, locations, onClose, onDone, onError }: {
  row: Row; locations: string[]; onClose: () => void; onDone: (msg: string) => void; onError: (msg: string) => void;
}) {
  const [f, setF] = useState({ ...row });
  const [moveTo, setMoveTo] = useState("");
  const [moveQty, setMoveQty] = useState(1);
  const [confirmDel, setConfirmDel] = useState(false);
  const set = <K extends keyof Row>(k: K, v: Row[K]) => setF((o) => ({ ...o, [k]: v }));
  const run = (p: Promise<unknown>, msg: string) => p.then(() => onDone(msg)).catch((e) => onError(e.message));
  const flag = (k: "altered" | "signed" | "misprint" | "proxy", label: string) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f[k]} onChange={(e) => set(k, e.target.checked ? 1 : 0)} className="accent-[var(--color-accent)]" />{label}</label>
  );
  const save = () => run(api(`/collection/${row.id}`, { method: "PATCH", body: JSON.stringify({
    quantity: f.quantity, finish: f.finish, condition: f.condition, language: f.language, location: f.location,
    altered: f.altered, signed: f.signed, misprint: f.misprint, proxy: f.proxy, notes: f.notes,
    purchase_price: f.purchase_price, purchase_date: f.purchase_date }) }), "Saved");

  return (
    <Drawer onClose={onClose} title={row.name}>
      <div className="flex flex-col gap-5 md:flex-row md:gap-0">
        {/* the card overlaps the fields box (like Scryfall): -ml-6 on the box + pl-10 so the content is not covered */}
        <Hit className="relative z-10 mx-auto w-full max-w-[360px] self-start md:sticky md:top-0 md:mx-0 md:w-[46%] md:shrink-0">
          <CardImg id={row.scryfall_id} size="large" className="shadow-[0_10px_28px_rgba(0,0,0,0.6)]" /></Hit>
        <Hit className="min-w-0 flex-1 rounded-xl border border-line/70 bg-surface/85 p-5 backdrop-blur-md md:-ml-6 md:pl-10 md:pt-6">
          <h2 className="text-xl font-semibold">{row.name}</h2>
          <p className="text-sm text-mute">{row.set_name} ({row.set_code.toUpperCase()}) · #{row.collector_number} · {eur(row.price)}</p>
          <div className="mb-4 mt-1"><ExtLinks id={row.scryfall_id} cardmarketId={row.cardmarket_id} /></div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity"><input type="number" min={1} className="field" value={f.quantity} onChange={(e) => set("quantity", Math.max(1, +e.target.value))} /></Field>
            <Field label="Finish"><select className="field" value={f.finish} onChange={(e) => set("finish", e.target.value as Row["finish"])}>
              {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Condition"><select className="field" value={f.condition} onChange={(e) => set("condition", e.target.value as Row["condition"])}>
              {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Language"><select className="field" value={f.language} onChange={(e) => set("language", e.target.value)}>
              {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Location"><input className="field" list="locs" value={f.location} onChange={(e) => set("location", e.target.value)} />
              <datalist id="locs">{locations.map((l) => <option key={l} value={l} />)}</datalist></Field>
            <Field label="Purchase price (€)"><input type="number" step="0.01" min={0} className="field" value={f.purchase_price ?? ""}
              onChange={(e) => set("purchase_price", e.target.value === "" ? null : +e.target.value)} /></Field>
            <Field label="Purchase date"><input type="date" className="field" value={f.purchase_date?.slice(0, 10) ?? ""} onChange={(e) => set("purchase_date", e.target.value || null)} /></Field>
          </div>
          <div className="my-3 flex flex-wrap gap-x-5 gap-y-2">{flag("altered", "Altered")}{flag("signed", "Signed")}{flag("misprint", "Misprint")}{flag("proxy", "Proxy")}</div>
          <Field label="Notes"><textarea className="field min-h-16" value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>

          <div className="mt-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-bg p-3">
            <Field label="Move to"><input className="field w-44" list="locs" value={moveTo} onChange={(e) => setMoveTo(e.target.value)} placeholder="Location" /></Field>
            <Field label="Quantity"><input type="number" min={1} max={row.quantity} className="field w-20" value={moveQty} onChange={(e) => setMoveQty(+e.target.value)} /></Field>
            <button className="btn-ghost" disabled={!moveTo || moveTo === row.location}
              onClick={() => run(api(`/collection/${row.id}/move`, { method: "POST", body: JSON.stringify({ location: moveTo, quantity: moveQty }) }), `Moved ${moveQty} to ${moveTo}`)}>Move</button>
          </div>

          <div className="mt-5 flex items-center justify-between">
            {confirmDel ? (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-danger">Delete {row.quantity}× {row.name}?</span>
                <button className="btn-danger" onClick={() => run(api(`/collection/${row.id}`, { method: "DELETE" }), "Deleted")}>Yes, delete</button>
                <button className="btn-ghost" onClick={() => setConfirmDel(false)}>Cancel</button>
              </div>
            ) : <button className="btn-danger" onClick={() => setConfirmDel(true)}>Delete</button>}
            <div className="flex gap-2"><button className="btn-ghost" onClick={onClose}>Close</button><button className="btn-primary" onClick={save}>Save</button></div>
          </div>
        </Hit>
      </div>
    </Drawer>
  );
}
