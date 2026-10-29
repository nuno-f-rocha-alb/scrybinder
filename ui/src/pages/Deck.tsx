import { useCallback, useEffect, useRef, useState } from "react";
import { Select } from "../components/select";
import { createPortal } from "react-dom";
import { IconAlertTriangle, IconArrowLeft, IconBox, IconCheck, IconChecklist, IconCopy, IconDownload, IconEdit, IconListDetails, IconPlus, IconShare, IconStack2, IconTrash, IconUpload, IconX } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { BOARDS, BOARD_LABEL, Board, CardFilter, Deck as DeckT, DeckCard as DeckCardT, DeckStats, editionOf, FORMATS, Format, GROUPS, GroupBy, Legality, OracleRow, Preview, SORTS, SortBy, VIEWS, View, groupCards, matchesFilter, resultPreview, toPreview } from "../decks";
import { CardImg, FinishTag, Modal, cardmarketUrl, openExternal, scryfallUrl, useToast } from "../components/ui";
import { MenuItem, useContextMenu } from "../components/contextmenu";
import PrintingDialog from "../components/printings";
import DeckPicker from "../components/deckpicker";
import CardDetails from "../components/carddetails";
import { ManaCost, StatusBadge } from "../components/mana";
import { GridControls, useCardGrid } from "../components/cardgrid";
import { DeckView, useZoom } from "../components/deckviews";
import { LegalityPanel, StatsPanel } from "../components/deckstats";
import AssignDialog from "../components/assign";
import Playtest from "../components/playtest";
import DeckVisual from "../components/deckvisual";
import ByLocation from "../components/bylocation";
import Snapshots from "../components/snapshots";
import DeckTokens, { Fold } from "../components/decktokens";
import Suggestions from "../components/suggestions";
import AddMissingDialog from "../components/addmissing";
import AddCards from "../components/addcards";
import ShareDialog from "../components/sharedialog";
import ExportDialog from "../components/deckinclude";
import BatchEdit from "../components/batchedit";
import AddToList, { ListPayload } from "../components/addtolist";
import BulkEdit from "../components/bulkedit";
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
            <div className="font-medium leading-snug">{p.name} <FinishTag finish={p.finish} /></div>
            <ManaCost cost={p.mana_cost} />
          </div>
          <div className="text-xs text-mute">{p.type_line}</div>
          {p.edition && <div className="text-xs text-mute">{p.edition}{p.finish === "foil" ? " · foil" : p.finish === "etched" ? " · etched" : ""}</div>}
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

export default function Deck({ id, onBack, focusOracle }: { id: number; onBack: () => void; focusOracle?: string }) {
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
  const { zoom, close, onZoom: zoomTo } = useZoom();
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [missingIds, setMissingIds] = useState<number[] | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const focused = useRef(false);
  const [foldedC, setFoldedC] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<"cards" | "visual" | "locate" | "stats" | "suggestions" | "playtest" | "snapshots">("cards");
  const [filter, setFilter] = useState<CardFilter | null>(null);
  const [showProblems, setShowProblems] = useState(false);
  const [assignId, setAssignId] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const [bulking, setBulking] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [batch, setBatch] = useState(false);
  const [toList, setToList] = useState<{ payload: ListPayload; what: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [folded, setFolded] = useState<Set<string>>(() => { try { return new Set<string>(JSON.parse(localStorage.getItem("scrybinder.folded") ?? "[]")); } catch { return new Set<string>(); } });
  const setFoldedKeys = (next: Set<string>) => { setFolded(next); try { const kept = (JSON.parse(localStorage.getItem("scrybinder.folded") ?? "[]") as string[]).filter((k) => k.startsWith("sug:")); localStorage.setItem("scrybinder.folded", JSON.stringify([...[...next].filter((k) => !k.startsWith("sug:")), ...kept])); }  /* the Suggestions tab shares this key: keep its entries */ catch { /* no storage */ } };
  const [switchId, setSwitchId] = useState<number | null>(null);
  const [pickId, setPickId] = useState<number | null>(null);
  const [missingFor, setMissingFor] = useState<DeckCardT | null>(null);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const [copyFor, setCopyFor] = useState<DeckCardT | null>(null);
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
  const toggle = (cid: number) => setSelected((s) => { const n = new Set(s); n.has(cid) ? n.delete(cid) : n.add(cid); return n; });
  const onZoom = (c: DeckCardT) => (selecting ? toggle(c.id) : zoomTo(c));  // while selecting, a click picks the card
  useEffect(() => {
    if (!selecting) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape" && !missingIds) { setSelecting(false); setSelected(new Set()); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selecting, missingIds]);
  useEffect(() => {  // coming from the collection's deck badge: show the card, scroll to it and flash it
    if (!deck || !focusOracle || focused.current) return;
    const c = deck.cards.find((x) => x.oracle_id === focusOracle);
    focused.current = true;
    if (!c) return;
    setFolded(new Set());  // not saved: only so that the card is not inside a folded group
    setPreview(toPreview(c));
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const el = document.querySelector<HTMLElement>(`[data-dc="${c.id}"]`);
      el?.scrollIntoView({ block: "center" });
      el?.animate([{ outline: "3px solid var(--color-accent)", outlineOffset: "2px" }, { outline: "3px solid var(--color-accent)", outlineOffset: "2px", offset: 0.7 }, { outline: "3px solid transparent", outlineOffset: "2px" }], { duration: 2600 });
    }));
  }, [deck, focusOracle]);

  if (err && !deck) return <div><button className="btn-ghost mb-4" onClick={onBack}><IconArrowLeft className="size-4" />Decks</button><p className="text-danger">{err}</p></div>;
  if (!deck) return <p className="text-mute">Loading…</p>;
  const statusSlot = document.getElementById("status-root");
  const noPrinting = deck.cards.filter((c) => !c.scryfall_id).length;  // lines that have no edition yet
  const missingCount = deck.cards.reduce((n, c) => n + (c.board === "maybe" ? 0 : c.missing), 0);

  const cardMenu = (c: DeckCardT): MenuItem[] => [
    { label: "Select", onSelect: () => { setSelecting(true); setSelected(new Set([c.id])); } },
    "sep",
    { label: "Switch printing…", onSelect: () => setSwitchId(c.id) },
    "sep",
    { label: "Add one", hint: "Alt+1", onSelect: () => quickRef.current(c.id, 1) },
    { label: "Add one as a new line", onSelect: () => act(api(`/decks/${id}/cards/${c.id}/duplicate`, { method: "POST" })) },
    { label: c.quantity === 1 ? "Remove from deck" : "Remove one", hint: "Alt+2", danger: true, onSelect: () => quickRef.current(c.id, 2) },
    "sep",
    ...(c.board !== "main" ? [{ label: "Move to main deck", onSelect: () => patchCard(c, { board: "main" }) }] : []),
    ...(c.board !== "side" ? [{ label: "Move to sideboard", hint: "Alt+3", onSelect: () => quickRef.current(c.id, 3) }] : []),
    ...(c.board !== "maybe" ? [{ label: "Move to considering", hint: "Alt+4", onSelect: () => quickRef.current(c.id, 4) }] : []),
    ...(deck.format === "commander" && c.board !== "commander" ? [{ label: "Set as commander", onSelect: () => patchCard(c, { board: "commander" }) }] : []),
    "sep",
    { label: "Add to another deck…", onSelect: () => setPickId(c.id) },
    ...(c.image_id ? [{ label: "Add to a list…", onSelect: () => setToList({ payload: { items: [{ scryfall_id: c.image_id as string, finish: c.finish ?? undefined, quantity: c.quantity }] }, what: c.name }) }] : []),
    ...(c.missing > 0 && c.board !== "maybe" ? [{ label: `Add the missing ${c.missing} to collection…`, onSelect: () => setMissingFor(c) }] : []),
    ...(c.scryfall_id ? [{ label: "Add this printing to the collection…", onSelect: () => setCopyFor(c) }] : []),
    { label: "Copies and tags…", onSelect: () => setAssignId(c.id) },
    "sep",
    { label: "View details", onSelect: () => setDetailsId(c.id) },
    { label: "Copy card name", onSelect: () => navigator.clipboard.writeText(c.name).then(() => toast("Name copied")).catch(() => toast("Could not copy", true)) },
    { label: "Set as deck image", onSelect: () => { patchDeck({ cover_card_id: c.id }); toast("Deck image set"); } },
    ...(c.image_id ? ["sep" as const, { label: "Open on Scryfall", onSelect: () => openExternal(scryfallUrl(c.image_id!)) }] : []),
    ...(c.cardmarket_id ? [{ label: "Open on Cardmarket", onSelect: () => openExternal(cardmarketUrl(c.cardmarket_id!)) }] : []),
  ];

  const patchDeck = (body: object) => act(api(`/decks/${id}`, { method: "PATCH", body: JSON.stringify(body) }));
  const errors = legality?.problems.filter((p) => p.severity === "error").length ?? 0;
  const main = (stats?.totals.main ?? 0) + (stats?.totals.commander ?? 0);
  const cards = filter ? deck.cards.filter((c) => matchesFilter(c, filter)) : deck.cards;
  const groups = groupCards(cards, group, sort);
  const deckGroups = groups.filter((g) => g.key !== "maybe");  // the maybeboard sits in its own line under the deck and the tokens, grouped the same way
  const consideringGroups = groupCards(cards.filter((c) => c.board === "maybe"), group, sort, "maybe");
  const consideringCount = consideringGroups.reduce((n, g) => n + g.count, 0);
  const allFolded = deckGroups.length > 0 && deckGroups.every((g) => folded.has(g.key));
  const ctx = { deckId: id, act, setPreview, onZoom, selecting, selected, onAssign: (c: DeckCardT) => setAssignId(c.id), hover: (c: DeckCardT | null) => { hovered.current = c?.id ?? null; }, onMenu: (c: DeckCardT, e: React.MouseEvent) => menu.open(e, cardMenu(c)) };
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
          <Select className="field w-auto" aria-label="Format" value={deck.format} onChange={(e) => patchDeck({ format: e.target.value as Format })}>
            {FORMATS.map((f) => <option key={f} value={f}>{cap(f)}</option>)}
          </Select>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <button className="btn-ghost" title="Reserve the free copies of your collection for the cards that still need them"
            onClick={() => api<{ assigned: number }>(`/decks/${id}/assign-free`, { method: "POST" }).then((r) => { toast(r.assigned ? `Assigned ${r.assigned} ${r.assigned === 1 ? "copy" : "copies"}` : "No free copies to assign"); reload(); }).catch((e) => toast(e.message, true))}>
            <IconBox className="size-4" />Assign free copies
          </button>
          {noPrinting > 0 && <button className="btn-ghost" title="Give every card without an edition one: that of the copies assigned to it, else the one you own, else the cheapest"
            onClick={() => api<{ filled: number }>(`/decks/${id}/fill-printings`, { method: "POST" }).then((r) => { toast(`${r.filled} ${r.filled === 1 ? "card" : "cards"} got an edition`); reload(); }).catch((e) => toast(e.message, true))}>
            <IconStack2 className="size-4" />Set editions ({noPrinting})
          </button>}
          {missingCount > 0 && <button className="btn-ghost" title="Add the copies you are missing to your collection (not the proxies)" onClick={() => setAdding(true)}>
            <IconPlus className="size-4" />Add missing to collection
          </button>}
          <button className={selecting ? "btn-primary" : "btn-ghost"} aria-pressed={selecting} title="Pick several cards to act on them together"
            onClick={() => { setSelecting(!selecting); setSelected(new Set()); }}><IconChecklist className="size-4" />Select</button>
          <button className="btn-ghost" title="Edit a whole board as text: change quantities, delete lines, paste a list" onClick={() => setBulking(true)}>
            <IconListDetails className="size-4" />Bulk edit
          </button>
          <button className="btn-ghost" title="Add the cards of a list (Moxfield, Archidekt, MTGO style) to this deck" onClick={() => setImporting(true)}>
            <IconUpload className="size-4" />Import list
          </button>
          <button className="btn-ghost" title="Make a link to this deck that anyone can open" onClick={() => setSharing(true)}><IconShare className="size-4" />Share</button>
          <button className="btn-ghost" title="Save the deck as a text list" onClick={() => setExporting(true)}>
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
          {([["cards", "Cards"], ["visual", "Visual"], ["locate", "Find copies"], ["stats", "Statistics"], ["playtest", "Playtest"], ["snapshots", "Snapshots"], ...(deck.format === "commander" ? [["suggestions", "Suggestions"] as const] : [])] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`-mb-px cursor-pointer border-b-2 px-4 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent ${tab === k ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink"}`}>{l}</button>
          ))}
        </div>

        {showProblems && legality && <LegalityPanel legality={legality} format={deck.format} onClose={() => setShowProblems(false)}
          onCard={(n) => { const c = deck.cards.find((x) => x.name === n); if (c) setPreview(toPreview(c)); }} />}

        {tab === "visual" && <DeckVisual deck={deck} onOpen={zoomTo} onHover={(c) => setPreview(toPreview(c))} toast={toast} />}

        {tab === "locate" && <ByLocation deckId={id} toast={toast} onChanged={reload} />}

        {tab === "stats" && <>{stats ? <StatsPanel stats={stats} active={filter} onFilter={pick} /> : <p className="text-mute">Loading…</p>}</>}

        <div hidden={tab !== "playtest"}><Playtest cards={deck.cards} commander={deck.format === "commander"} /></div>  {/* stays mounted: switching tabs keeps the game */}

        {tab === "snapshots" && <Snapshots deckId={id} toast={toast} onRestored={reload} />}

        {tab === "suggestions" && deck.format === "commander" && <Suggestions deckId={id} toast={toast} onAdded={reload} />}

        {tab === "cards" && <>
        {selecting && (() => {
          const picks = deck.cards.filter((c) => selected.has(c.id));
          const missing = picks.reduce((n, c) => n + (c.board === "maybe" ? 0 : c.missing), 0);
          const end = () => { setSelecting(false); setSelected(new Set()); setConfirmRemove(false); };
          // one after the other: the server shares one database connection, and each change can move copies between rows
          const each = async (f: (c: DeckCardT) => Promise<unknown>) => { for (const c of picks) await f(c); };
          const run = (p: Promise<unknown>) => { p.then(() => { setSelected(new Set()); reload(); }).catch((e) => toast(e.message, true)); };
          return (
            <>
            <div role="toolbar" aria-label="Selected cards" className="sticky top-0 z-20 mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-accent/40 bg-surface/95 px-3 py-2 shadow-lg backdrop-blur">
              <span className="mr-2 text-sm font-medium tabular-nums">{picks.length} selected</span>
              <button className="btn-ghost !py-1" onClick={() => setSelected(new Set(cards.map((c) => c.id)))}>Select all shown</button>
              <button className="btn-ghost !py-1" disabled={!picks.length} onClick={() => setSelected(new Set())}>Clear</button>
              <span className="mx-1 h-5 w-px bg-line" aria-hidden />
              <button className="btn-primary !py-1" disabled={!missing} title={missing ? "Put the copies these cards are missing into your collection (not the proxies)" : "Nothing missing in the selected cards"}
                onClick={() => setMissingIds(picks.map((c) => c.id))}><IconPlus className="size-4" />Add missing to collection ({missing})</button>
              <button className="btn-ghost !py-1" disabled={!picks.length} title="Reserve the free copies of your collection for the selected cards"
                onClick={() => api<{ assigned: number }>(`/decks/${id}/assign-free`, { method: "POST", body: JSON.stringify({ card_ids: picks.map((c) => c.id) }) }).then((r) => { toast(r.assigned ? `Assigned ${r.assigned} ${r.assigned === 1 ? "copy" : "copies"}` : "No free copies to assign"); setSelected(new Set()); reload(); }).catch((e) => toast(e.message, true))}>
                <IconBox className="size-4" />Assign free copies</button>
              <button className="btn-ghost !py-1" disabled={!picks.length} title="Change the board, proxy, quantity or tags of the selected cards" onClick={() => setBatch(true)}><IconEdit className="size-4" />Edit</button>
              <button className="btn-ghost !py-1" disabled={!picks.length} title="Add the selected cards to a list"
                onClick={() => setToList({ payload: { items: picks.filter((c) => c.image_id).map((c) => ({ scryfall_id: c.image_id as string, finish: c.finish ?? undefined, quantity: c.quantity })) }, what: `${picks.length} selected ${picks.length === 1 ? "card" : "cards"}` })}>Add to list</button>
              <button className="btn-danger !py-1" disabled={!picks.length} onClick={() => {
                if (!confirmRemove) { setConfirmRemove(true); setTimeout(() => setConfirmRemove(false), 4000); return; }
                setConfirmRemove(false); run(each((c) => api(`/decks/${id}/cards/${c.id}`, { method: "DELETE" })));
              }}><IconTrash className="size-4" />{confirmRemove ? "Click again to remove" : "Remove"}</button>
              <button className="btn-ghost ml-auto !py-1" onClick={end}>Done</button>
            </div>
            {batch && <BatchEdit deckId={id} cards={picks} onClose={() => setBatch(false)} onDone={() => { setBatch(false); setSelected(new Set()); reload(); }} />}
            </>
          );
        })()}
        <AddCards deck={deck} setPreview={setPreview} toast={toast} onAdd={(oracle_id, board, new_line) => act(api(`/decks/${id}/cards`, { method: "POST", body: JSON.stringify({ oracle_id, board, new_line }) }))} />

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-mute">View
            <Select className="field w-auto" value={view} onChange={(e) => setView(e.target.value as View)}>{VIEWS.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</Select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Group
            <Select className="field w-auto" value={group} onChange={(e) => setGroup(e.target.value as GroupBy)}>{GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}</Select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <Select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>{SORTS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</Select></label>
          {view === "stacks" && (
            <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Show a strip for every copy instead of one with a count">
              <input type="checkbox" checked={every === "1"} onChange={(e) => setEvery(e.target.checked ? "1" : "0")} className="accent-[var(--color-accent)]" />Every copy
            </label>
          )}
          {(view === "grid" || view === "stacks" || view === "spoiler") && <GridControls g={grid} />}
          <button className="btn-ghost !py-1 text-xs" title="Fold or unfold every group" onClick={() => setFoldedKeys(allFolded ? new Set() : new Set(deckGroups.map((g) => g.key)))}>{allFolded ? "Unfold all" : "Fold all"}</button>
        </div>

        {filter && (
          <div className="mb-4 flex items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1">Showing: {filter.label} <span className="text-mute">({cards.reduce((n, c) => n + c.quantity, 0)} cards)</span>
              <button className="flex size-5 items-center justify-center rounded-full hover:bg-line" aria-label="Clear the filter" onClick={() => setFilter(null)}><IconX className="size-3.5" /></button></span>
          </div>
        )}
        {cards.length === 0 && <div className="rounded-2xl border border-dashed border-line p-12 text-center text-mute">{filter ? "No cards match this filter." : "This deck is empty. Search above to add cards."}</div>}
        <DeckView groups={deckGroups} folded={folded} onToggle={(k) => { const n = new Set(folded); n.has(k) ? n.delete(k) : n.add(k); setFoldedKeys(n); }} view={view} every={every === "1"} layout={grid} ctx={ctx} />
        <DeckTokens grid={grid} deckId={id} rev={deck.cards.filter((c) => c.board === "main" || c.board === "commander").map((c) => c.name).join("|")} />
        {consideringGroups.length > 0 && <Fold title="Considering" count={consideringCount} force={selecting || !!filter}>
          <DeckView groups={consideringGroups} folded={foldedC} onToggle={(k) => { const n = new Set(foldedC); n.has(k) ? n.delete(k) : n.add(k); setFoldedC(n); }} view={view} every={every === "1"} layout={{ ...grid, setGridEl: () => {} }} ctx={ctx} />
        </Fold>}
        </>}

{/* the summary lives in a slot under the scrolling area (App), so it is always at the bottom of the window whatever the cards */}
        {statusSlot ? createPortal(
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line bg-surface px-6 py-3 text-sm">
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
        , statusSlot) : null}
      </div>
      {adding && <AddMissingDialog deckId={id} count={missingCount} onClose={() => setAdding(false)}
        onDone={(n) => { setAdding(false); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {missingIds && <AddMissingDialog deckId={id} cardIds={missingIds} count={deck.cards.filter((c) => missingIds.includes(c.id)).reduce((n, c) => n + (c.board === "maybe" ? 0 : c.missing), 0)} onClose={() => setMissingIds(null)}
        onDone={(n) => { setMissingIds(null); setSelected(new Set()); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {missingFor && <AddMissingDialog deckId={id} cardIds={[missingFor.id]} count={missingFor.missing} onClose={() => setMissingFor(null)}
        onDone={(n) => { setMissingFor(null); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {copyFor && <AddMissingDialog deckId={id} count={0} printing={{ cardId: copyFor.id, label: `${editionOf(copyFor)}${copyFor.finish === "foil" ? " · foil" : copyFor.finish === "etched" ? " · etched" : ""}` }} onClose={() => setCopyFor(null)}
        onDone={(n) => { setCopyFor(null); toast(`${n} ${n === 1 ? "copy" : "copies"} added to your collection`); reload(); }} />}
      {detailsId !== null && (() => {
        const order = groups.flatMap((g) => g.cards);  // Prev / Next follow the list as it is shown: its groups, sort and filter
        const i = order.findIndex((x) => x.id === detailsId), at = deck.cards.find((x) => x.id === detailsId);
        const to = (k: number) => () => setDetailsId(order[k].id);
        return at?.image_id ? <CardDetails printId={at.image_id} onClose={() => setDetailsId(null)} prev={i > 0 ? to(i - 1) : undefined} next={i >= 0 && i < order.length - 1 ? to(i + 1) : undefined} /> : null;
      })()}
      {switchId !== null && deck.cards.find((c) => c.id === switchId) && (() => { const c = deck.cards.find((x) => x.id === switchId)!;
        return <PrintingDialog deckId={id} oracleId={c.oracle_id} name={c.name} current={c.scryfall_id} currentFinish={c.finish} onClose={() => setSwitchId(null)}
          onPick={(sid, finish) => { setSwitchId(null); patchCard(c, { scryfall_id: sid, finish }); }} />; })()}
      {pickId !== null && deck.cards.find((c) => c.id === pickId) && (() => { const c = deck.cards.find((x) => x.id === pickId)!;
        return <DeckPicker oracleId={c.oracle_id} scryfallId={c.scryfall_id} finish={c.finish} name={c.name} excludeId={id} onClose={() => setPickId(null)}
          onDone={(n) => { setPickId(null); toast(`${c.name} added to ${n}`); }} />; })()}
      {menu.node}
      {toList && <AddToList payload={toList.payload} what={toList.what} onClose={() => setToList(null)} onDone={(m) => { setToList(null); toast(m); }} />}
      {exporting && deck && <ExportDialog id={id} name={deck.name} onClose={() => setExporting(false)} />}
      {sharing && deck &&<ShareDialog title={deck.name} spec={{ kind: "deck", deck_id: id }} onClose={() => setSharing(false)} />}
      {bulking && <BulkEdit deckId={id} onClose={() => setBulking(false)} onDone={(m) => { setBulking(false); toast(m || "No changes"); reload(); }} />}
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
