import { useCallback, useEffect, useState } from "react";
import { IconAlertTriangle, IconArrowLeft, IconCheck, IconCopy, IconPlus, IconSearch, IconTrash, IconX } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { BOARDS, BOARD_LABEL, Board, CardFilter, Deck as DeckT, DeckStats, FORMATS, Format, GROUPS, GroupBy, Legality, OracleRow, Preview, SORTS, SortBy, VIEWS, View, groupCards, matchesFilter, resultPreview, toPreview } from "../decks";
import { CardImg, Modal, useToast } from "../components/ui";
import { ManaCost, StatusBadge } from "../components/mana";
import { GridControls, useCardGrid } from "../components/cardgrid";
import { DeckView, useZoom } from "../components/deckviews";
import { LegalityPanel, StatsPanel } from "../components/deckstats";

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

function AddCards({ deck, onAdd, setPreview }: { deck: DeckT; onAdd: (oracleId: string, board: Board) => void; setPreview: (p: Preview) => void }) {
  const [q, setQ] = useState("");
  const [board, setBoard] = useState<Board>(deck.format === "commander" && !deck.cards.some((c) => c.board === "commander") ? "commander" : "main");
  const [legalOnly, setLegalOnly] = useState(true);
  const [rows, setRows] = useState<OracleRow[]>([]);
  const [done, setDone] = useState("");  // the query whose results are shown: "No cards found" only once the search has answered
  useEffect(() => {
    if (!q.trim()) { setRows([]); return; }
    let live = true;  // an older, slower answer must not replace a newer one
    const t = setTimeout(() => api<{ rows: OracleRow[] }>("/oracle/search?" + qs({ q, deck: deck.id, legal: legalOnly ? "true" : "", limit: 8 }))
      .then((r) => { if (live) { setRows(r.rows); setDone(q); } }).catch(() => { if (live) { setRows([]); setDone(q); } }), 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, legalOnly, deck.id, deck.cards]);
  const add = (r: OracleRow) => onAdd(r.oracle_id, board);
  return (
    <div className="mb-5 rounded-xl border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" aria-hidden />
          <input className="field pl-9" placeholder="Find cards to add…" aria-label="Find cards to add" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && rows[0]) add(rows[0]); }} />
        </div>
        <select className="field w-auto" value={board} aria-label="Add to" onChange={(e) => setBoard(e.target.value as Board)}>
          {BOARDS.map((b) => <option key={b} value={b}>{BOARD_LABEL[b]}</option>)}
        </select>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Only cards legal in this deck's format (and its commander's colours)">
          <input type="checkbox" checked={legalOnly} onChange={(e) => setLegalOnly(e.target.checked)} className="accent-[var(--color-accent)]" />Only legal
        </label>
      </div>
      {q.trim() && done === q && rows.length === 0 && <p className="mt-3 text-sm text-mute">No cards found.</p>}
      {rows.length > 0 && (
        <ul className="mt-2 divide-y divide-line">
          {rows.map((r) => (
            <li key={r.oracle_id} onMouseEnter={() => setPreview(resultPreview(r))} className="flex items-center gap-3 px-1 py-1.5 hover:bg-raised">
              <button className="btn-ghost !px-2 !py-1" onClick={() => add(r)} aria-label={`Add ${r.name}`}><IconPlus className="size-4" /></button>
              <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
              <ManaCost cost={r.mana_cost} />
              <span className="hidden w-48 truncate text-xs text-mute md:block">{r.type_line}</span>
              <span className="w-24 text-right text-xs text-mute tabular-nums">{r.in_deck ? `${r.in_deck} in deck · ` : ""}{r.owned} owned</span>
            </li>
          ))}
        </ul>
      )}
    </div>
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
  const { zoom, close, onZoom } = useZoom();
  const [tab, setTab] = useState<"cards" | "stats">("cards");
  const [filter, setFilter] = useState<CardFilter | null>(null);
  const [showProblems, setShowProblems] = useState(false);

  const reload = useCallback(() => Promise.all([api<DeckT>(`/decks/${id}`), api<Legality>(`/decks/${id}/legality`), api<DeckStats>(`/decks/${id}/stats`)])
    .then(([d, l, s]) => { setDeck(d); setName(d.name); setLegality(l); setStats(s); setErr(""); }).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { reload(); }, [reload]);
  const act = (p: Promise<unknown>) => { p.then(reload).catch((e) => toast(e.message, true)); };
  const shown = preview ?? (deck?.cards[0] ? toPreview(deck.cards[0]) : null);

  if (err && !deck) return <div><button className="btn-ghost mb-4" onClick={onBack}><IconArrowLeft className="size-4" />Decks</button><p className="text-danger">{err}</p></div>;
  if (!deck) return <p className="text-mute">Loading…</p>;

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
          <button className="btn-ghost" title="Copy this deck (without assigned copies)"
            onClick={() => api<{ id: number }>(`/decks/${id}/duplicate`, { method: "POST" }).then(() => toast("Deck duplicated")).catch((e) => toast(e.message, true))}>
            <IconCopy className="size-4" />Duplicate
          </button>
          <button className="btn-danger" onClick={() => {
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
        <DeckView groups={groupCards(cards, group, sort)} view={view} every={every === "1"} layout={grid} ctx={{ deckId: id, act, setPreview, onZoom }} />
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
