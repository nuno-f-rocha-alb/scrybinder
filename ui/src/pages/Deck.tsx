import { useCallback, useEffect, useRef, useState } from "react";
import { IconAlertTriangle, IconArrowLeft, IconBox, IconCheck, IconCopy, IconDownload, IconPlus, IconTrash, IconUpload, IconX } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { BOARDS, BOARD_LABEL, Board, CardFilter, Deck as DeckT, DeckCard as DeckCardT, DeckStats, FORMATS, Format, GROUPS, GroupBy, Legality, OracleRow, Preview, SORTS, SortBy, VIEWS, View, groupCards, matchesFilter, resultPreview, toPreview } from "../decks";
import { CardImg, Modal, cardmarketUrl, openExternal, scryfallUrl, useToast } from "../components/ui";
import { MenuItem, useContextMenu } from "../components/contextmenu";
import PrintingDialog from "../components/printings";
import DeckPicker from "../components/deckpicker";
import { ManaCost, StatusBadge } from "../components/mana";
import { GridControls, useCardGrid } from "../components/cardgrid";
import { DeckView, useZoom } from "../components/deckviews";
import { LegalityPanel, StatsPanel } from "../components/deckstats";
import AssignDialog from "../components/assign";
import AddMissingDialog from "../components/addmissing";
import AddCards from "../components/addcards";
import ImportDialog, { Skipped } from "../components/decklist";
import type { ImportReport } from "../components/decklist";

const cap = (f: string) => f[0].toUpperCase() + f.slice(1);

/** A choice remembered between sessions (the view, the grouping...). */
function useChoice<T extends string>(key: string, def: T, ok: readonly T[]): [T, (v: T) => void] {
  const [v, set] = useState<T>(() => { try { const x = localStorage.getItem("scrybinder.deck." + key) as T | null; return x && ok.includes(x) ? x : def; } catch { return def; } });
  return [v, (x) => { set(x); try { localStorage.setItem("scrybinder.deck." + key, x); } catch { /* no storage */ } }];
}

/** The big card on the left: the one under the pointer, and it stays on the last one when the pointer leaves. */
function PreviewPanel({ p }: { p: Preview | null }) {
  return (
    <aside className="sticky top-6 hidden w-[300px] shrink-0 self-start lg:block" aria-label="Card preview">
      {p?.image_id ? <CardImg id={p.image_id} size="large" /> : <div className="aspect-[63/88] w-full rounded-[4.5%] bg-raised" />}
      {p && (
        <div className="mt-3 space-y-1.5 text-sm">
          <div className="flex items-start justify-between gap-2">
            <div className="font-medium leading-snug">{p.name}</div>
            <ManaCost cost={p.mana_cost} />
          </div>
          <div className="text-xs text-mute">{p.type_line}</div>
          <div className="flex items-center justify-between text-xs text-mute tabular-nums">
            <span>{eur(p.price)}</span>
            {p.owned !== undefined && <span>You own {p.owned}</span>}
          </div>
          {p.status && <StatusBadge status={p.status} />}
          {!!p.tags?.length && <div className="flex flex-wrap gap-1">{p.tags.map((t) => <span key={t} className="rounded-md bg-raised px-1.5 py-0.5 text-[10.5px] text-mute">{t}</span>)}</div>}
        </div>
      )}
    </aside>
  );
}

export default function Deck({ id, onBack }: { id: number; onBack: () => void }) {
  const [deck, setDeck] = useState<DeckT | null>(null);
  const [legality, setLegality] = useState<Legality | null>(null);
  const [stats, setStats] = useState<DeckStats | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { toast, node } = useToast();
  const [view, setView] = useChoice<View>("view", "list", VIEWS.map((v) => v.id));
  const [group, setGroup] = useChoice<GroupBy>("group", "type", GROUPS.map((g) => g.id));
  const [sort, setSort] = useChoice<SortBy>("sort", "name", SORTS.map((x) => x.id));
  const [every, setEvery] = useChoice<"1" | "0">("every", "0", ["0", "1"]);
  const grid = useCardGrid();
  const { zoom, close, onZoom, show } = useZoom();
  const [tab, setTab] = useState<"cards" | "stats">("cards");
  const [filter, setFilter] = useState<CardFilter | null>(null);
  const [showProblems, setShowProblems] = useState(false);
  const [assignId, setAssignId] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [switchId, setSwitchId] = useState<number | null>(null);
  const [pickId, setPickId] = useState<number | null>(null);
  const [missingFor, setMissingFor] = useState<DeckCardT | null>(null);
  const menu = useContextMenu();
  const hovered = useRef<number | null>(null);  // the id of the card under the pointer or focus: the target of the Alt+number shortcuts
  const quickRef = useRef<(id: number, n: number) => void>(() => {});
  const [imported, setImported] = useState<ImportReport | null>(null);

  const reload = useCallback(() => Promise.all([api<DeckT>(`/decks/${id}`), api<Legality>(`/decks/${id}/legality`), api<DeckStats>(`/decks/${id}/stats`)])
    .then(([d, l, s]) => { setDeck(d); setName(d.name); setLegality(l); setStats(s); setErr(""); }).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { reload(); }, [reload]);
  const act = (p: Promise<unknown>) => { p.then(reload).catch((e) => toast(e.message, true)); };
  const patchCard = (c: DeckCardT, body: object) => act(api(`/decks/${id}/cards/${c.id}`, { method: "PATCH", body: JSON.stringify(body) }));
  quickRef.current = (cardId, n) => {  // Alt+1 one more, Alt+2 one less (the last removes it), Alt+3 sideboard, Alt+4 maybeboard
    const c = deck?.cards.find((x) => x.id === cardId);  // the current card, not the one the pointer entered
    if (!c) return;
    if (n === 1) patchCard(c, { quantity: c.quantity + 1 });
    else if (n === 2) { if (c.quantity === 1) hovered.current = null; c.quantity === 1 ? act(api(`/decks/${id}/cards/${c.id}`, { method: "DELETE" })) : patchCard(c, { quantity: c.quantity - 1 }); }
    else patchCard(c, { board: n === 3 ? "side" : "maybe" });
  };
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const c = hovered.current, n = ({ Digit1: 1, Digit2: 2, Digit3: 3, Digit4: 4 } as Record<string, number>)[e.code];
      if (c === null || !n || !e.altKey || e.ctrlKey || e.metaKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement).tagName)) return;
      e.preventDefault();
      quickRef.current(c, n);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const shown = preview ?? (deck?.cards[0] ? toPreview(deck.cards[0]) : null);

  if (err && !deck) return <div><button className="btn-ghost mb-4" onClick={onBack}><IconArrowLeft className="size-4" />Decks</button><p className="text-danger">{err}</p></div>;
  if (!deck) return <p className="text-mute">Loading…</p>;
  const missingCount = deck.cards.reduce((n, c) => n + (c.board === "maybe" ? 0 : c.missing), 0);

  const cardMenu = (c: DeckCardT): MenuItem[] => [
    { label: "Switch printing…", onSelect: () => setSwitchId(c.id) },
    "sep",
    { label: "Add one", hint: "Alt+1", onSelect: () => quickRef.current(c.id, 1) },
    { label: c.quantity === 1 ? "Remove from deck" : "Remove one", hint: "Alt+2", danger: true, onSelect: () => quickRef.current(c.id, 2) },
    "sep",
    ...(c.board !== "main" ? [{ label: "Move to main deck", onSelect: () => patchCard(c, { board: "main" }) }] : []),
    ...(c.board !== "side" ? [{ label: "Move to sideboard", hint: "Alt+3", onSelect: () => quickRef.current(c.id, 3) }] : []),
    ...(c.board !== "maybe" ? [{ label: "Move to maybeboard", hint: "Alt+4", onSelect: () => quickRef.current(c.id, 4) }] : []),
    ...(deck.format === "commander" && c.board !== "commander" ? [{ label: "Set as commander", onSelect: () => patchCard(c, { board: "commander" }) }] : []),
    "sep",
    { label: "Add to another deck…", onSelect: () => setPickId(c.id) },
    ...(c.missing > 0 && c.board !== "maybe" ? [{ label: `Add the missing ${c.missing} to collection…`, onSelect: () => setMissingFor(c) }] : []),
    { label: "Copies and tags…", onSelect: () => setAssignId(c.id) },
    "sep",
    { label: "View details", onSelect: () => show(c) },
    { label: "Copy card name", onSelect: () => navigator.clipboard.writeText(c.name).then(() => toast("Name copied")).catch(() => toast("Could not copy", true)) },
    { label: "Set as deck image", onSelect: () => { patchDeck({ cover_card_id: c.id }); toast("Deck image set"); } },
    ...(c.image_id ? ["sep" as const, { label: "Open on Scryfall", onSelect: () => openExternal(scryfallUrl(c.image_id!)) }] : []),
    ...(c.cardmarket_id ? [{ label: "Open on Cardmarket", onSelect: () => openExternal(cardmarketUrl(c.cardmarket_id!)) }] : []),
  ];

  const exportList = async () => {
    const bridge = (window as { pywebview?: { api?: { save_text?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    if (!bridge?.save_text) { window.location.assign(`/api/decks/${id}/export`); return; }
    try {
      const r = await fetch(`/api/decks/${id}/export`);
      if (!r.ok) throw new Error(r.statusText);
      const path = await bridge.save_text(`${deck.name.replace(/[^\w .-]+/g, "").trim() || "deck"}.txt`, await r.text());
      if (path) toast(`Saved to ${path}`);
    } catch (e) { toast((e as Error).message, true); }
  };
  const patchDeck = (body: object) => act(api(`/decks/${id}`, { method: "PATCH", body: JSON.stringify(body) }));
  const errors = legality?.problems.filter((p) => p.severity === "error").length ?? 0;
  const main = (stats?.totals.main ?? 0) + (stats?.totals.commander ?? 0);
  const cards = filter ? deck.cards.filter((c) => matchesFilter(c, filter)) : deck.cards;
  const pick = (f: CardFilter) => {  // a click on a chart: show those cards, or clear the filter when it is already the one
    if (filter?.kind === f.kind && filter.value === f.value) setFilter(null);
    else { setFilter(f); setTab("cards"); }
  };

  return (
    <div className="flex items-start gap-6">
      <PreviewPanel p={shown} />
      <div className="min-w-0 flex-1">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <button className="btn-ghost" onClick={onBack} aria-label="Back to decks"><IconArrowLeft className="size-4" />Decks</button>
          <input className="field min-w-[200px] flex-1 !text-lg !font-semibold" aria-label="Deck name" value={name} maxLength={120}
            onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== deck.name && patchDeck({ name })} />
          <select className="field w-auto" aria-label="Format" value={deck.format} onChange={(e) => patchDeck({ format: e.target.value as Format })}>
            {FORMATS.map((f) => <option key={f} value={f}>{cap(f)}</option>)}
          </select>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <button className="btn-ghost" title="Reserve the free copies of your collection for the cards that still need them"
            onClick={() => api<{ assigned: number }>(`/decks/${id}/assign-free`, { method: "POST" }).then((r) => { toast(r.assigned ? `Assigned ${r.assigned} ${r.assigned === 1 ? "copy" : "copies"}` : "No free copies to assign"); reload(); }).catch((e) => toast(e.message, true))}>
            <IconBox className="size-4" />Assign free copies
          </button>
          {missingCount > 0 && <button className="btn-ghost" title="Add the copies you are missing to your collection (not the proxies)" onClick={() => setAdding(true)}>
            <IconPlus className="size-4" />Add missing to collection
          </button>}
          <button className="btn-ghost" title="Add the cards of a list (Moxfield, Archidekt, MTGO style) to this deck" onClick={() => setImporting(true)}>
            <IconUpload className="size-4" />Import list
          </button>
          <button className="btn-ghost" title="Save the deck as a text list" onClick={exportList}>
            <IconDownload className="size-4" />Export list
          </button>
          <button className="btn-ghost" title="Copy this deck (without assigned copies)"
            onClick={() => api<{ id: number }>(`/decks/${id}/duplicate`, { method: "POST" }).then(() => toast("Deck duplicated")).catch((e) => toast(e.message, true))}>
            <IconCopy className="size-4" />Duplicate
          </button>
          <button className="btn-danger ml-auto" onClick={() => {
            if (!confirmDelete) { setConfirmDelete(true); setTimeout(() => setConfirmDelete(false), 4000); return; }
            api(`/decks/${id}`, { method: "DELETE" }).then(onBack).catch((e) => toast(e.message, true));
          }}><IconTrash className="size-4" />{confirmDelete ? "Click again to delete" : "Delete"}</button>
        </div>

        <div role="tablist" aria-label="Deck sections" className="mb-4 flex gap-1 border-b border-line">
          {([["cards", "Cards"], ["stats", "Statistics"]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`-mb-px cursor-pointer border-b-2 px-4 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent ${tab === k ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink"}`}>{l}</button>
          ))}
        </div>

        {showProblems && legality && <LegalityPanel legality={legality} format={deck.format} onClose={() => setShowProblems(false)}
          onCard={(n) => { const c = deck.cards.find((x) => x.name === n); if (c) setPreview(toPreview(c)); }} />}

        {tab === "stats" && (stats ? <StatsPanel stats={stats} active={filter} onFilter={pick} /> : <p className="text-mute">Loading…</p>)}

        {tab === "cards" && <>
        <AddCards deck={deck} setPreview={setPreview} onAdd={(oracle_id, board) => act(api(`/decks/${id}/cards`, { method: "POST", body: JSON.stringify({ oracle_id, board }) }))} />

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-mute">View
            <select className="field w-auto" value={view} onChange={(e) => setView(e.target.value as View)}>{VIEWS.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Group
            <select className="field w-auto" value={group} onChange={(e) => setGroup(e.target.value as GroupBy)}>{GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}</select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>{SORTS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
          {view === "stacks" && (
            <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Show a strip for every copy instead of one with a count">
              <input type="checkbox" checked={every === "1"} onChange={(e) => setEvery(e.target.checked ? "1" : "0")} className="accent-[var(--color-accent)]" />Every copy
            </label>
          )}
          {(view === "grid" || view === "stacks" || view === "spoiler") && <GridControls g={grid} />}
        </div>

        {filter && (
          <div className="mb-4 flex items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1">Showing: {filter.label} <span className="text-mute">({cards.reduce((n, c) => n + c.quantity, 0)} cards)</span>
              <button className="flex size-5 items-center justify-center rounded-full hover:bg-line" aria-label="Clear the filter" onClick={() => setFilter(null)}><IconX className="size-3.5" /></button></span>
          </div>
        )}
        {cards.length === 0 && <div className="rounded-2xl border border-dashed border-line p-12 text-center text-mute">{filter ? "No cards match this filter." : "This deck is empty. Search above to add cards."}</div>}
        <DeckView groups={groupCards(cards, group, sort)} view={view} every={every === "1"} layout={grid} ctx={{ deckId: id, act, setPreview, onZoom, onAssign: (c) => setAssignId(c.id), hover: (c) => { hovered.current = c?.id ?? null; }, onMenu: (c, e) => menu.open(e, cardMenu(c)) }} />
        </>}

        <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line bg-surface/95 px-6 py-3 text-sm backdrop-blur">
          <span className="font-medium tabular-nums">{main} <span className="font-normal text-mute">main deck</span> / {stats?.totals.side ?? 0} <span className="font-normal text-mute">sideboard</span></span>
          {deck.format === "casual" ? <span className="text-mute">Casual</span> : (
            <button className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-raised ${errors ? "text-danger" : "text-ok"}`} aria-expanded={showProblems} onClick={() => setShowProblems((v) => !v)}
              title="Show what is wrong with the deck">
              {errors ? <><IconAlertTriangle className="size-4" aria-hidden />{errors} {errors === 1 ? "issue" : "issues"}</> : <><IconCheck className="size-4" aria-hidden />Legal in {cap(deck.format)}</>}
            </button>
          )}
          <span className="tabular-nums">{eur(stats?.price)}</span>
          {!!stats?.cost_to_complete && <span className="tabular-nums text-danger">{eur(stats.cost_to_complete)} to complete</span>}
          <span className="ml-auto flex flex-wrap gap-x-3 text-xs text-mute tabular-nums">
            {Object.entries(stats?.types ?? {}).map(([t, n]) => <span key={t}>{n} {t}</span>)}
          </span>
        </div>
      </div>
      {adding && <AddMissingDialog deckId={id} count={missingCount} onClose={() => setAdding(false)}
        onDone={(n) => { setAdding(false); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {missingFor && <AddMissingDialog deckId={id} cardIds={[missingFor.id]} count={missingFor.missing} onClose={() => setMissingFor(null)}
        onDone={(n) => { setMissingFor(null); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {switchId !== null && deck.cards.find((c) => c.id === switchId) && (() => { const c = deck.cards.find((x) => x.id === switchId)!;
        return <PrintingDialog deckId={id} oracleId={c.oracle_id} name={c.name} current={c.scryfall_id} onClose={() => setSwitchId(null)}
          onPick={(sid) => { setSwitchId(null); patchCard(c, { scryfall_id: sid }); }} />; })()}
      {pickId !== null && deck.cards.find((c) => c.id === pickId) && (() => { const c = deck.cards.find((x) => x.id === pickId)!;
        return <DeckPicker oracleId={c.oracle_id} scryfallId={c.scryfall_id} name={c.name} excludeId={id} onClose={() => setPickId(null)}
          onDone={(n) => { setPickId(null); toast(`${c.name} added to ${n}`); }} />; })()}
      {menu.node}
      {importing && <ImportDialog deckId={id} onClose={() => setImporting(false)} onDone={(r) => { setImporting(false); setImported(r); reload(); }} />}
      {imported && (
        <Modal title="Deck list imported" onClose={() => setImported(null)}>
          <h2 className="mb-2 text-lg font-semibold">Imported {imported.cards} {imported.cards === 1 ? "card" : "cards"}</h2>
          <Skipped report={imported} />
          <div className="mt-5 flex justify-end"><button className="btn-primary" onClick={() => setImported(null)}>Done</button></div>
        </Modal>
      )}
      {assignId !== null && deck.cards.find((c) => c.id === assignId) && (
        <AssignDialog deckId={id} card={deck.cards.find((c) => c.id === assignId)!} onClose={() => setAssignId(null)} onChanged={reload} />
      )}
      {zoom && (
        <Modal title={zoom.name} onClose={close}>
          <div className="mx-auto max-w-[340px]"><CardImg id={zoom.image_id ?? ""} size="large" /></div>
          <p className="mt-3 text-center text-sm font-medium">{zoom.name}</p>
          <div className="mt-1 flex justify-center"><StatusBadge status={zoom.status} /></div>
        </Modal>
      )}
      {node}
    </div>
  );
}
