import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Combo, Select } from "../components/select";
import { IconCards, IconChecklist, IconCheck, IconFolderPlus, IconLayoutGrid, IconList, IconSearch, IconStack2 } from "@tabler/icons-react";
import { api, ApiError, CONDITIONS, Collection as Coll, eur, FINISH, GROUPS, GroupBy, LANGS, Loc, qsl, Row, useGroup } from "../api";
import { Badge, Blocked, CardImg, Drawer, ExtLinks, Field, Hit, Modal, useToast } from "../components/ui";
import { GridControls, sourceFor, useCardGrid } from "../components/cardgrid";
import { BulkBar, BulkDelete, BulkEdit } from "./Bulk";
import { MenuItem, nameAndLinks, useContextMenu } from "../components/contextmenu";
import DeckPicker from "../components/deckpicker";
import ValueHistory from "../components/valuehistory";
import SpareCards from "../components/sparecards";
import CardDetails, { CardInfoLoader } from "../components/carddetails";
import LocationPicker from "../components/locationpicker";

const ALL = 100000;  // the whole collection at once: the images load as they scroll into view
const placeName = (l: string) => l || "(no location)";
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
/** The row as one place of it (a row joined from several locations has the first row's fields, but the total quantity): what is edited, moved or deleted. */
const own = (r: Row): Row => ({ ...r, ...(r.places.find((p) => p.id === r.id) ?? r.places[0]), places: r.places }) as Row;
const idsOf = (r: Row) => r.places.map((p) => p.id);
const groupLabel = (by: GroupBy, key: string) => (by === "location" ? placeName(key) : by === "rarity" ? cap(key) : key);

export default function Collection({ initialSet, initialLocation, onOpenDeck }: { initialSet?: string; initialLocation?: string; onOpenDeck: (deckId: number, oracleId?: string) => void }) {
  const [q, setQ] = useState("");
  const [spareView, setSpareView] = useState(false);
  const [showMissing, setShowMissing] = useState(false);  // inside a set: the printings you do not own, faded
  const [missing, setMissing] = useState<{ scryfall_id: string; name: string; collector_number: string; price: number | null }[]>([]);
  const [locations, setLocations] = useState<string[]>(initialLocation !== undefined ? [initialLocation] : []);  // none = all
  const [setCode, setSetCode] = useState(initialSet ?? "");
  const [group, setGroup] = useGroup();
  const [groupBy, setGroupByState] = useState<GroupBy>(() => { try { const v = localStorage.getItem("scrybinder.groupby"); return GROUPS.some((g) => g[0] === v) ? (v as GroupBy) : "location"; } catch { return "location"; } });
  const setGroupBy = (g: GroupBy) => { setGroupByState(g); try { localStorage.setItem("scrybinder.groupby", g); } catch { /* no storage */ } };
  const [prog, setProg] = useState<{ owned: number; total: number; percent: number } | null>(null);
  const [finish, setFinish] = useState("");
  const [sort, setSort] = useState("name");
  const [view, setView] = useState<"grid" | "table">(() => (localStorage.getItem("scrybinder.view") as "grid") || "grid");
  const [data, setData] = useState<Coll | null>(null);
    const [locs, setLocs] = useState<Loc[]>([]);
  const [edit, setEdit] = useState<Row | null>(null);
  const grid = useCardGrid();
  const [selecting, setSelecting] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [bulk, setBulk] = useState<"edit" | "delete" | null>(null);
  const [delIds, setDelIds] = useState<{ ids: number[]; preview: string[] } | null>(null);  // rows to delete, from the right-click menu
  const [delLoc, setDelLoc] = useState<Loc | null>(null);
  const [merging, setMerging] = useState<string[] | null>(null);  // the locations being merged, in the order they were picked
  const lastPick = useRef<number | null>(null);
  const filterKey = useRef("");
  const { toast, node } = useToast();
  const [newLoc, setNewLoc] = useState<string | null>(null);  // the name being typed in the "New location" dialog
  const menu = useContextMenu();
  const [toDeck, setToDeck] = useState<Row | null>(null);
  const [detailsAt, setDetailsAt] = useState<number | null>(null);  // index of the row whose details are open

  const loadLocs = useCallback(() => api<Loc[]>("/locations").then(setLocs).catch(() => {}), []);
  const load = useCallback(() => {
    api<Coll>("/collection?" + qsl({ q, set: setCode, finish, sort, limit: ALL, group: groupBy }, locations)).then(setData).catch((e) => toast(e.message, true));
    loadLocs();
  }, [q, setCode, locations, finish, sort, groupBy]);
  useEffect(() => { const t = setTimeout(load, 150); return () => clearTimeout(t); }, [load]);
  useEffect(() => {
    if (!setCode) { setProg(null); return; }
    api<{ code: string; owned: number; total: number; percent: number }[]>("/sets?" + qsl({ q: setCode, hide_empty: "false", group: group ? "true" : "false" }, locations))
      .then((r) => setProg(r.find((s) => s.code === setCode) ?? null)).catch(() => setProg(null));
  }, [setCode, locations, group, data?.total_cards]);
  useEffect(() => {
    if (!setCode || !showMissing) { setMissing([]); return; }
    let live = true;  // a slower earlier answer must not replace a newer one
    api<{ missing: typeof missing }>(`/sets/${setCode}/missing?` + qsl({ group: group ? "true" : "false" }, locations))
      .then((r) => live && setMissing(r.missing)).catch(() => live && setMissing([]));
    return () => { live = false; };
  }, [setCode, showMissing, group, locations, data?.total_cards]);
  useEffect(() => { setSel(new Set()); lastPick.current = null; }, [q, setCode, locations, finish, groupBy]);  // the selection belongs to the current filter
  useEffect(() => {
    if (!selecting) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape" && !bulk && !edit && !delIds) { setSel(new Set()); setSelecting(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selecting, bulk, edit, delIds]);

  const rows = data?.rows ?? [];
  filterKey.current = JSON.stringify([q, setCode, locations, finish]);
  const isSel = (r: Row) => r.places.every((p) => sel.has(p.id));
  const sections = useMemo(() => {  // the server orders by group, so a group is a run of rows
    const out: { key: string; label: string; items: { r: Row; i: number }[] }[] = [];
    rows.forEach((r, i) => {
      const key = groupBy === "none" ? "" : r.group;
      const last = out[out.length - 1];
      if (last && last.key === key) last.items.push({ r, i });
      else out.push({ key, label: groupLabel(groupBy, key), items: [{ r, i }] });
    });
    return out;
  }, [rows, groupBy]);
  const pick = (i: number, shift: boolean) => {
    setSel((s) => {
      const n = new Set(s);
      const set = (r: Row, on: boolean) => idsOf(r).forEach((id) => (on ? n.add(id) : n.delete(id)));
      if (shift && lastPick.current !== null) {  // range from the last click: follows the state of the clicked row
        const [a, b] = [Math.min(lastPick.current, i), Math.max(lastPick.current, i)];
        const on = !rows[i].places.every((p) => s.has(p.id));
        for (let k = a; k <= b; k++) set(rows[k], on);
      } else set(rows[i], !rows[i].places.every((p) => s.has(p.id)));
      return n;
    });
    lastPick.current = i;
  };
  const selectAll = () => {
    const key = filterKey.current;
    api<{ ids: number[] }>("/collection/ids?" + qsl({ q, set: setCode, finish }, locations))
      .then((r) => { if (key === filterKey.current) setSel(new Set(r.ids)); })  // the filter changed meanwhile: discard
      .catch((e) => toast(e.message, true));
  };
  const bulkDone = (m: string, err?: boolean) => { setBulk(null); setDelIds(null); if (!err) { setSel(new Set()); setSelecting(false); } toast(m, err); load(); };
  const open = (r: Row, i: number, e: React.MouseEvent) => (selecting ? pick(i, e.shiftKey) : setEdit(own(r)));
  const createLoc = () => api<{ location: string }>("/locations", { method: "POST", body: JSON.stringify({ name: newLoc }) })
    .then((r) => { setNewLoc(null); setLocations([r.location]); toast(`Location ${r.location} created`); load(); }).catch((e) => toast(e.message, true));
  /** The deck badge of a card: to the deck (a menu when several hold it), on that card. */
  const toDecks = (r: Row, e: React.MouseEvent) => {
    e.stopPropagation();
    if (r.decks.length === 1) onOpenDeck(r.decks[0].deck_id, r.oracle_id);
    else menu.open(e, r.decks.map((d) => ({ label: `${d.name} (${d.quantity})`, onSelect: () => onOpenDeck(d.deck_id, r.oracle_id) })));
  };
  const rowMenu = (r: Row, i: number): MenuItem[] => {
    const o = own(r);
    return [
      { label: "Edit…", onSelect: () => setEdit(o) },
      { label: "Add one copy", onSelect: () => api(`/collection/${o.id}`, { method: "PATCH", body: JSON.stringify({ quantity: o.quantity + 1 }) }).then(() => { load(); toast(`${o.quantity + 1}× ${r.name}`); }).catch((e) => toast(e.message, true)) },
      { label: "View details", onSelect: () => setDetailsAt(i) },
      { label: "Add to a deck…", onSelect: () => setToDeck(o) },
      ...(r.decks.length ? r.decks.map((d) => ({ label: `Go to ${d.name}`, onSelect: () => onOpenDeck(d.deck_id, r.oracle_id) })) : []),
      { label: "Select", onSelect: () => { setSelecting(true); setSel(new Set(idsOf(r))); lastPick.current = i; } },
      "sep",
      { label: "Delete…", danger: true, onSelect: () => setDelIds({ ids: idsOf(r), preview: [`${r.quantity}× ${r.name} (${r.set_code.toUpperCase()})`] }) },
      "sep",
      ...nameAndLinks(r.name, r.scryfall_id, r.cardmarket_id, toast),
    ];
  };
  const setV = (v: "grid" | "table") => { setView(v); try { localStorage.setItem("scrybinder.view", v); } catch { /* no storage */ } };
  const where = (r: Row) => r.places.map((p) => `${p.quantity}× ${placeName(p.location)}`).join("\n");
  if (spareView) return <SpareCards onBack={() => setSpareView(false)} />;

  const heading = (s: { key: string; label: string; items: { r: Row }[] }) => groupBy === "none" ? null : (
    <h2 className="mb-2 mt-1 flex items-center gap-2 border-b border-line pb-1 text-sm font-semibold">
      {groupBy === "location" && locs.find((l) => l.location === s.key)?.deck_id != null && <IconStack2 className="size-4 text-accent" aria-label="Deck" />}
      {s.label}<span className="text-xs font-normal text-mute tabular-nums">{s.items.reduce((n, x) => n + x.r.quantity, 0)}</span>
    </h2>);

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
          <ValueHistory current={data?.total_value} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input className="field w-60 pl-9" placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          </div>
          <button className="btn-ghost" title="Copies that are in no deck: your trade binder" onClick={() => setSpareView(true)}><IconCards className="size-4" />Spare cards</button>
          <LocationPicker locs={locs} value={locations} onChange={setLocations} onRemove={setDelLoc} onMerge={setMerging} />
          <button className="btn-ghost" title="Make a location, empty, to move cards into" onClick={() => setNewLoc("")}><IconFolderPlus className="size-4" />New location</button>
          <Select className="field w-auto" value={finish} onChange={(e) => setFinish(e.target.value)} aria-label="Finish">
            <option value="">All finishes</option>
            {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <Select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="name">Name</option><option value="set">Set</option>
              <option value="price">Price</option><option value="added">Most recent</option>
            </Select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute" title="Cards that are in several locations are one card, except when grouped by location">Group
            <Select className="field w-auto" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}>
              {GROUPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select></label>
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
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Show the printings of this set you do not own, faded, after your cards">
            <input type="checkbox" checked={showMissing} onChange={(e) => setShowMissing(e.target.checked)} className="accent-[var(--color-accent)]" />Show missing
          </label>
        </div>
      )}

      {data && data.rows.length === 0 && (
        <div className="rounded-2xl border border-dashed border-line p-16 text-center text-mute">
          {q || locations.length || finish ? "No cards match these filters." : "Your collection is empty. Add cards or import a ManaBox CSV."}
        </div>
      )}

      {data && view === "grid" && (
        <div ref={grid.setGridEl}>
          {sections.map((s) => (
            <section key={s.key} className="mb-6" aria-label={s.label || "Cards"}>
              {heading(s)}
              <div className="grid gap-4" style={grid.style}>
                {s.items.map(({ r, i }) => (
                  <button key={r.id} onClick={(e) => open(r, i, e)} onContextMenu={(e) => menu.open(e, rowMenu(r, i))} aria-pressed={selecting ? isSel(r) : undefined} title={r.places.length > 1 ? where(r) : undefined} className="group cursor-pointer text-left outline-none select-none">
                    <div className="relative transition-transform duration-200 group-hover:-translate-y-1 group-focus-visible:-translate-y-1">
                      <CardImg id={r.scryfall_id} size={sourceFor(grid.tilePx)} className={`shadow-lg shadow-black/50 group-focus-visible:ring-2 group-focus-visible:ring-accent ${isSel(r) ? "ring-2 ring-accent brightness-75" : ""}`} />
                      {selecting && <span aria-hidden className={`absolute bottom-1.5 left-1.5 flex size-6 items-center justify-center rounded-full border-2 ${isSel(r) ? "border-accent bg-accent text-white" : "border-white/70 bg-black/50"}`}>{isSel(r) && <IconCheck className="size-4" stroke={3} />}</span>}
                      <span className="absolute right-1.5 top-1.5 rounded-full bg-black/80 px-2 py-0.5 text-xs font-semibold tabular-nums">×{r.quantity}</span>
                      {r.decks.length > 0 && <span role="link" tabIndex={0} onClick={(e) => toDecks(r, e)} onKeyDown={(e) => { if (e.key === "Enter") toDecks(r, e as unknown as React.MouseEvent); }}
                        className="absolute bottom-1.5 right-1.5 flex cursor-pointer items-center gap-1 rounded-full bg-black/80 px-2 py-0.5 text-xs text-accent hover:bg-accent hover:text-white" title={`In ${r.decks.map((d) => d.name).join(", ")}: click to see it there`}>
                        <IconCards className="size-3.5" aria-hidden /><span className="sr-only">In a deck: {r.decks.map((d) => d.name).join(", ")}</span></span>}
                      {r.finish !== "nonfoil" && <span className="absolute left-1.5 top-1.5"><Badge foil>{FINISH[r.finish].toUpperCase()}</Badge></span>}
                    </div>
                    <div className="mt-2 truncate text-sm font-medium">{r.name}</div>
                    <div className="flex items-center justify-between gap-2 text-xs text-mute">
                      <span className="min-w-0 truncate">{r.set_code.toUpperCase()} · {r.collector_number}{r.places.length > 1 ? ` · ${r.places.length} locations` : r.location && groupBy !== "location" ? ` · ${r.location}` : ""}</span>
                      <span className="shrink-0 text-gold">{eur(r.price)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {data && view === "table" && data.rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-xs uppercase tracking-wide text-mute">
              <tr>{selecting && <th className="w-10 px-3 py-2.5"><input type="checkbox" aria-label="Select all loaded rows" checked={rows.length > 0 && rows.every(isSel)}
                onChange={(e) => setSel(e.target.checked ? new Set(rows.flatMap(idsOf)) : new Set())} className="accent-[var(--color-accent)]" /></th>}{["Qty", "Name", "Set", "No.", "Finish", "Cond.", "Language", "Location", "Price"].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {sections.map((s) => [
                groupBy !== "none" && <tr key={`h:${s.key}`} className="border-t border-line bg-surface/60"><td colSpan={selecting ? 10 : 9} className="px-3 py-1.5 text-xs font-semibold">{s.label} <span className="font-normal text-mute tabular-nums">{s.items.reduce((n, x) => n + x.r.quantity, 0)}</span></td></tr>,
                ...s.items.map(({ r, i }) => (
                  <tr key={r.id} onClick={(e) => open(r, i, e)} onContextMenu={(e) => menu.open(e, rowMenu(r, i))} className={`cursor-pointer select-none border-t border-line hover:bg-raised/60 ${isSel(r) ? "bg-accent-soft" : ""}`}>
                    {selecting && <td className="px-3 py-2"><input type="checkbox" readOnly tabIndex={-1} aria-label={`Select ${r.name}`} checked={isSel(r)} className="pointer-events-none accent-[var(--color-accent)]" /></td>}
                    <td className="px-3 py-2 tabular-nums">{r.quantity}</td>
                    <td className="px-3 py-2 font-medium">{r.name}{r.decks.length > 0 && <span role="link" tabIndex={0} onClick={(e) => toDecks(r, e)} className="ml-2 inline-flex cursor-pointer items-center gap-1 text-xs font-normal text-accent hover:underline" title={`In ${r.decks.map((d) => d.name).join(", ")}: click to see it there`}><IconCards className="size-3.5" aria-hidden />{r.decks.length}<span className="sr-only"> decks: {r.decks.map((d) => d.name).join(", ")}</span></span>}</td>
                    <td className="px-3 py-2 text-mute">{r.set_code.toUpperCase()}</td>
                    <td className="px-3 py-2 text-mute">{r.collector_number}</td>
                    <td className="px-3 py-2">{r.finish === "nonfoil" ? "" : <Badge foil>{FINISH[r.finish]}</Badge>}</td>
                    <td className="px-3 py-2 text-mute">{r.condition}</td>
                    <td className="px-3 py-2 text-mute">{r.language}</td>
                    <td className="px-3 py-2 text-mute" title={r.places.length > 1 ? where(r) : undefined}>{r.places.length > 1 ? r.places.map((p) => `${placeName(p.location)} ×${p.quantity}`).join(", ") : r.location}</td>
                    <td className="px-3 py-2 text-gold">{eur(r.price)}</td>
                  </tr>
                )),
              ])}
            </tbody>
          </table>
        </div>
      )}

      {setCode && showMissing && (() => {
        const shown = missing.filter((m) => !q || m.name.toLowerCase().includes(q.toLowerCase()));
        return shown.length > 0 && (
          <section className="mb-6" aria-label="Missing from this set">
            <h2 className="mb-2 mt-1 flex items-center gap-2 border-b border-line pb-1 text-sm font-semibold">Missing<span className="text-xs font-normal text-mute tabular-nums">{shown.length}</span></h2>
            <div className="grid gap-4" style={grid.style}>
              {shown.map((m) => (
                <div key={m.scryfall_id} className="opacity-40 grayscale transition hover:opacity-70 hover:grayscale-0" title={`${m.name} — you do not own this`}>
                  <CardImg id={m.scryfall_id} size={sourceFor(grid.tilePx)} />
                  <div className="mt-2 truncate text-sm font-medium">{m.name}</div>
                  <div className="flex items-center justify-between gap-2 text-xs text-mute"><span>{setCode.toUpperCase()} · {m.collector_number}</span><span className="text-gold">{eur(m.price)}</span></div>
                </div>
              ))}
            </div>
          </section>
        );
      })()}

      {selecting && <BulkBar count={sel.size} total={data?.total_rows ?? 0} onSelectAll={selectAll} onClear={() => setSel(new Set())}
        onEdit={() => setBulk("edit")} onDelete={() => setBulk("delete")} onExit={() => { setSelecting(false); setSel(new Set()); }} />}
      {bulk === "edit" && <BulkEdit ids={[...sel]} locations={locs.map((l) => l.location).filter(Boolean)} onClose={() => setBulk(null)} onDone={bulkDone} />}
      {bulk === "delete" && <BulkDelete ids={[...sel]} preview={rows.filter(isSel).slice(0, 6).map((r) => `${r.quantity}× ${r.name} (${r.set_code.toUpperCase()})`)} onClose={() => setBulk(null)} onDone={bulkDone} />}
      {delIds && <BulkDelete ids={delIds.ids} preview={delIds.preview} onClose={() => setDelIds(null)} onDone={bulkDone} />}
      {delLoc && <DeleteLocation loc={delLoc} onClose={() => setDelLoc(null)}
        onDone={(m) => { setDelLoc(null); setLocations((v) => v.filter((x) => x !== delLoc.location)); toast(m); load(); }} onError={(m) => toast(m, true)} />}
      {merging && <MergeLocations names={merging} locs={locs} onClose={() => setMerging(null)}
        onDone={(into, m) => { setMerging(null); setLocations([into]); toast(m); load(); }} onError={(m) => toast(m, true)} />}
      {edit && <EditModal key={edit.id} row={edit} locations={locs.map((l) => l.location).filter(Boolean)} onClose={() => setEdit(null)} onSwitch={setEdit}
        onOpenDeck={(deckId) => { setEdit(null); onOpenDeck(deckId, edit.oracle_id); }}
        onDone={(m) => { setEdit(null); load(); toast(m); }} onError={(m) => toast(m, true)} />}
      {newLoc !== null && (
        <Modal title="New location" onClose={() => setNewLoc(null)}>
          <h2 className="mb-3 text-lg font-semibold">New location</h2>
          <p className="mb-3 text-sm text-mute">It stays in the list while it is empty, so you can move cards into it. Every deck already has a location of its own.</p>
          <input className="field" autoFocus maxLength={60} placeholder="e.g. Box 3" aria-label="Location name" value={newLoc} onChange={(e) => setNewLoc(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && newLoc.trim()) createLoc(); }} />
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setNewLoc(null)}>Cancel</button>
            <button className="btn-primary" disabled={!newLoc.trim()} onClick={createLoc}>Create</button>
          </div>
        </Modal>
      )}
      {toDeck && <DeckPicker oracleId={toDeck.oracle_id} scryfallId={toDeck.scryfall_id} finish={toDeck.finish} name={toDeck.name} onClose={() => setToDeck(null)}
        onDone={(n) => { setToDeck(null); load(); toast(`${toDeck.name} added to ${n}`); }} />}
      {detailsAt !== null && rows[detailsAt] && <CardDetails printId={rows[detailsAt].scryfall_id} onClose={() => setDetailsAt(null)}
        prev={detailsAt > 0 ? () => setDetailsAt(detailsAt - 1) : undefined} next={detailsAt < rows.length - 1 ? () => setDetailsAt(detailsAt + 1) : undefined} />}
      {menu.node}
      {node}
    </div>
  );
}

/** Merge locations: the name starts as the first one picked and can be changed. */
function MergeLocations({ names, locs, onClose, onDone, onError }: { names: string[]; locs: Loc[]; onClose: () => void; onDone: (into: string, msg: string) => void; onError: (msg: string) => void }) {
  const [into, setInto] = useState(names[0]);
  const cards = names.reduce((n, x) => n + (locs.find((l) => l.location === x)?.cards ?? 0), 0);
  const go = () => api<{ moved: number }>("/locations/merge", { method: "POST", body: JSON.stringify({ names, into }) })
    .then((r) => onDone(into.trim(), `${names.length} locations merged into ${into.trim()} (${r.moved} cards)`)).catch((e) => onError(e.message));
  return (
    <Modal title="Merge locations" onClose={onClose}>
      <h2 className="mb-2 text-lg font-semibold">Merge {names.length} locations</h2>
      <p className="mb-3 text-sm text-mute">The {cards} {cards === 1 ? "card" : "cards"} of {names.map(placeName).join(", ")} go into one location; identical cards join into one row.</p>
      <Field label="Name of the merged location">
        <input className="field" autoFocus maxLength={60} value={into} onChange={(e) => setInto(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && into.trim()) go(); }} />
      </Field>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={!into.trim()} onClick={go}>Merge</button>
      </div>
    </Modal>
  );
}

/** Remove a location: its cards go to "(no location)" (the default) or are deleted with it. */
function DeleteLocation({ loc, onClose, onDone, onError }: { loc: Loc; onClose: () => void; onDone: (msg: string) => void; onError: (msg: string) => void }) {
  const [cards, setCards] = useState<"move" | "delete">("move");
  const [blocked, setBlocked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = (release = "") => {
    setBusy(true);
    api<{ moved?: number; deleted?: number }>(`/locations?name=${encodeURIComponent(loc.location)}&cards=${cards}${release}`, { method: "DELETE" })
      .then((r) => onDone(r.deleted !== undefined ? `Location ${loc.location} and its ${r.deleted} cards deleted (backup in data/trash)` : `Location ${loc.location} removed${r.moved ? `, ${r.moved} cards moved to (no location)` : ""}`))
      .catch((e) => { if (e instanceof ApiError && e.status === 409) setBlocked(e.message); else onError(e.message); setBusy(false); });
  };
  return (
    <Modal title="Delete location" onClose={onClose}>
      <h2 className="mb-2 text-lg font-semibold">Delete the location {loc.location}?</h2>
      {loc.cards > 0 ? (
        <fieldset className="space-y-2 text-sm">
          <legend className="mb-2 text-mute">It holds {loc.cards} {loc.cards === 1 ? "card" : "cards"}. What happens to them?</legend>
          <label className="flex cursor-pointer items-start gap-2"><input type="radio" name="what" checked={cards === "move"} onChange={() => setCards("move")} className="mt-1 accent-[var(--color-accent)]" />
            <span>Move them to (no location) <span className="text-mute">(you can move them later)</span></span></label>
          <label className="flex cursor-pointer items-start gap-2"><input type="radio" name="what" checked={cards === "delete"} onChange={() => setCards("delete")} className="mt-1 accent-[var(--color-accent)]" />
            <span className={cards === "delete" ? "text-danger" : ""}>Delete the {loc.cards} {loc.cards === 1 ? "card" : "cards"} too <span className="text-mute">(a copy is saved in data/trash)</span></span></label>
        </fieldset>
      ) : <p className="text-sm text-mute">It is empty.</p>}
      {blocked && <Blocked message={blocked} onRelease={() => go("&release=1")} onCancel={() => setBlocked(null)} />}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-danger" disabled={busy} onClick={() => go()}>{cards === "delete" && loc.cards > 0 ? "Delete location and cards" : "Delete location"}</button>
      </div>
    </Modal>
  );
}

function EditModal({ row, locations, onClose, onDone, onError, onSwitch, onOpenDeck }: {
  row: Row; locations: string[]; onClose: () => void; onDone: (msg: string) => void; onError: (msg: string) => void; onSwitch: (r: Row) => void; onOpenDeck: (deckId: number) => void;
}) {
  const [f, setF] = useState({ ...row });
  const [moveTo, setMoveTo] = useState("");
  const [moveQty, setMoveQty] = useState(1);
  const [confirmDel, setConfirmDel] = useState(false);
  const set = <K extends keyof Row>(k: K, v: Row[K]) => setF((o) => ({ ...o, [k]: v }));
  const [blocked, setBlocked] = useState<{ message: string; retry: () => void } | null>(null);
  // `go` gets "" or "?release=1": a 409 (copies assigned to decks) offers to free them and run it again
  const run = (go: (release: string) => Promise<unknown>, msg: string) => go("").then(() => onDone(msg)).catch((e) => e instanceof ApiError && e.status === 409
    ? setBlocked({ message: e.message, retry: () => go("?release=1").then(() => onDone(msg)).catch((x) => onError(x.message)) }) : onError(e.message));
  const flag = (k: "altered" | "signed" | "misprint" | "proxy", label: string) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f[k]} onChange={(e) => set(k, e.target.checked ? 1 : 0)} className="accent-[var(--color-accent)]" />{label}</label>
  );
  const save = () => run((r) => api(`/collection/${row.id}${r}`, { method: "PATCH", body: JSON.stringify({
    quantity: f.quantity, finish: f.finish, condition: f.condition, language: f.language, location: f.location,
    altered: f.altered, signed: f.signed, misprint: f.misprint, proxy: f.proxy, notes: f.notes,
    purchase_price: f.purchase_price, purchase_date: f.purchase_date }) }), "Saved");
  const total = row.places.reduce((n, p) => n + p.quantity, 0);
  const allDecks = row.places.flatMap((p) => p.decks).reduce((m, d) => m.set(d.deck_id, { ...d, quantity: (m.get(d.deck_id)?.quantity ?? 0) + d.quantity }), new Map<number, Row["decks"][number]>());

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
          {row.places.length > 1 && <div className="mb-4 rounded-xl border border-line bg-bg p-3 text-sm">
            <div className="mb-1 font-medium">{total} copies in {row.places.length} locations</div>
            <ul>{row.places.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 py-0.5">
                <span className={p.id === row.id ? "font-medium text-accent" : ""}>{placeName(p.location)} <span className="text-mute">× {p.quantity}</span></span>
                {p.id === row.id ? <span className="text-xs text-mute">editing</span>
                  : <button className="cursor-pointer text-xs text-accent hover:underline" onClick={() => onSwitch({ ...row, ...p, places: row.places } as Row)}>Edit this</button>}
              </li>))}</ul>
          </div>}
          {allDecks.size > 0 && <div className="mb-4 rounded-xl border border-accent/40 bg-accent-soft p-3 text-sm">
            <div className="mb-1 flex items-center gap-1.5 font-medium text-accent"><IconCards className="size-4" aria-hidden />In {allDecks.size === 1 ? "a deck" : "decks"}</div>
            <ul>{[...allDecks.values()].map((d) => (
              <li key={d.deck_id}><button className="cursor-pointer text-left hover:text-accent hover:underline" title="Open the deck on this card" onClick={() => onOpenDeck(d.deck_id)}>{d.name}</button> <span className="text-mute">× {d.quantity}</span></li>
            ))}</ul>
          </div>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity"><input type="number" min={1} className="field" value={f.quantity} onChange={(e) => set("quantity", Math.max(1, +e.target.value))} /></Field>
            <Field label="Finish"><Select className="field" value={f.finish} onChange={(e) => set("finish", e.target.value as Row["finish"])}>
              {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <Field label="Condition"><Select className="field" value={f.condition} onChange={(e) => set("condition", e.target.value as Row["condition"])}>
              {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</Select></Field>
            <Field label="Language"><Select className="field" value={f.language} onChange={(e) => set("language", e.target.value)}>
              {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <Field label="Location"><Combo className="field" suggestions={locations} value={f.location} onChange={(v) => set("location", v)} /></Field>
            <Field label="Purchase price (€)"><input type="number" step="0.01" min={0} className="field" value={f.purchase_price ?? ""}
              onChange={(e) => set("purchase_price", e.target.value === "" ? null : +e.target.value)} /></Field>
            <Field label="Purchase date"><input type="date" className="field" value={f.purchase_date?.slice(0, 10) ?? ""} onChange={(e) => set("purchase_date", e.target.value || null)} /></Field>
          </div>
          <div className="my-3 flex flex-wrap gap-x-5 gap-y-2">{flag("altered", "Altered")}{flag("signed", "Signed")}{flag("misprint", "Misprint")}{flag("proxy", "Proxy")}</div>
          <Field label="Notes"><textarea className="field min-h-16" value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>

          <div className="mt-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-bg p-3">
            <Field label="Move to"><Combo className="field w-44" suggestions={locations} value={moveTo} onChange={setMoveTo} placeholder="Location" /></Field>
            <Field label="Quantity"><input type="number" min={1} max={row.quantity} className="field w-20" value={moveQty} onChange={(e) => setMoveQty(+e.target.value)} /></Field>
            <button className="btn-ghost" disabled={!moveTo || moveTo === row.location}
              onClick={() => run((r) => api(`/collection/${row.id}/move${r}`, { method: "POST", body: JSON.stringify({ location: moveTo, quantity: moveQty }) }), `Moved ${moveQty} to ${moveTo}`)}>Move</button>
          </div>

          {blocked && <Blocked message={blocked.message} onRelease={blocked.retry} onCancel={() => setBlocked(null)} />}
          <div className="mt-5 flex items-center justify-between">
            {confirmDel ? (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-danger">Delete {row.quantity}× {row.name}?</span>
                <button className="btn-danger" onClick={() => run((r) => api(`/collection/${row.id}${r}`, { method: "DELETE" }), "Deleted")}>Yes, delete</button>
                <button className="btn-ghost" onClick={() => setConfirmDel(false)}>Cancel</button>
              </div>
            ) : <button className="btn-danger" onClick={() => setConfirmDel(true)}>Delete</button>}
            <div className="flex gap-2"><button className="btn-ghost" onClick={onClose}>Close</button><button className="btn-primary" onClick={save}>Save</button></div>
          </div>

          <section className="mt-6 border-t border-line pt-5" aria-label="Card details">
            <CardInfoLoader printId={row.scryfall_id} />
          </section>
        </Hit>
      </div>
    </Drawer>
  );
}
