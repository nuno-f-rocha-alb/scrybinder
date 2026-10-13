import { useCallback, useEffect, useState } from "react";
import { IconAlertTriangle, IconArrowLeft, IconCheck, IconCopy, IconMinus, IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { BOARDS, BOARD_LABEL, Board, Deck as DeckT, DeckCard, DeckStats, FORMATS, Format, Legality, OracleRow, Preview, groupCards, resultPreview, toPreview } from "../decks";
import { CardImg, useToast } from "../components/ui";
import { ManaCost, StatusBadge } from "../components/mana";

const cap = (f: string) => f[0].toUpperCase() + f.slice(1);

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

function Row({ c, deckId, act, setPreview }: { c: DeckCard; deckId: number; act: (p: Promise<unknown>) => void; setPreview: (p: Preview) => void }) {
  const patch = (body: object) => act(api(`/decks/${deckId}/cards/${c.id}`, { method: "PATCH", body: JSON.stringify(body) }));
  const remove = () => act(api(`/decks/${deckId}/cards/${c.id}`, { method: "DELETE" }));
  const btn = "flex size-6 items-center justify-center rounded-md text-mute hover:bg-line hover:text-ink";
  return (
    <li onMouseEnter={() => setPreview(toPreview(c))} onFocus={() => setPreview(toPreview(c))} className="grid grid-cols-[84px_minmax(0,1fr)_auto_116px_64px_92px] items-center gap-3 rounded-md px-2 py-1 hover:bg-raised">
      <div className="flex items-center gap-1">
        <button className={btn} aria-label={c.quantity === 1 ? `Remove ${c.name}` : `One less ${c.name}`} onClick={() => (c.quantity === 1 ? remove() : patch({ quantity: c.quantity - 1 }))}>
          {c.quantity === 1 ? <IconTrash className="size-3.5" /> : <IconMinus className="size-3.5" />}
        </button>
        <span className="w-6 text-center text-sm font-medium tabular-nums">{c.quantity}</span>
        <button className={btn} aria-label={`One more ${c.name}`} onClick={() => patch({ quantity: c.quantity + 1 })}><IconPlus className="size-3.5" /></button>
      </div>
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <span className="truncate">{c.name}</span>
        {c.missing > 0 && <span className="shrink-0 text-xs text-danger">{c.missing} missing</span>}
        {c.tags.map((t) => <span key={t} className="shrink-0 rounded-md bg-raised px-1.5 py-0.5 text-[10.5px] text-mute">{t}</span>)}
      </div>
      <ManaCost cost={c.mana_cost} />
      <StatusBadge status={c.status} title={c.elsewhere.length ? `Assigned to: ${c.elsewhere.map((e) => e.name).join(", ")}` : undefined} />
      <span className="text-right text-xs text-mute tabular-nums">{eur(c.price)}</span>
      <select className="field !w-auto !px-1.5 !py-0.5 text-xs" aria-label={`Board of ${c.name}`} value={c.board} onChange={(e) => patch({ board: e.target.value })}>
        {BOARDS.map((b) => <option key={b} value={b}>{BOARD_LABEL[b]}</option>)}
      </select>
    </li>
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
  const cards = deck.cards;

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

        <AddCards deck={deck} setPreview={setPreview} onAdd={(oracle_id, board) => act(api(`/decks/${id}/cards`, { method: "POST", body: JSON.stringify({ oracle_id, board }) }))} />

        {cards.length === 0 && <div className="rounded-2xl border border-dashed border-line p-12 text-center text-mute">This deck is empty. Search above to add cards.</div>}
        {groupCards(cards).map((g) => (
          <section key={g.key} className="mb-5" aria-label={g.label}>
            <h2 className="mb-1 flex items-baseline gap-2 border-b border-line pb-1 text-sm font-semibold">{g.label}<span className="text-xs font-normal text-mute">{g.count}</span></h2>
            <ul>{g.cards.map((c) => <Row key={c.id} c={c} deckId={id} act={act} setPreview={setPreview} />)}</ul>
          </section>
        ))}

        <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line bg-surface/95 px-6 py-3 text-sm backdrop-blur">
          <span className="font-medium tabular-nums">{main} <span className="font-normal text-mute">main deck</span> / {stats?.totals.side ?? 0} <span className="font-normal text-mute">sideboard</span></span>
          {deck.format === "casual" ? <span className="text-mute">Casual</span> : errors ? (
            <span className="inline-flex items-center gap-1 text-danger" title={legality?.problems.map((p) => p.message).join("\n")}><IconAlertTriangle className="size-4" aria-hidden />{errors} {errors === 1 ? "issue" : "issues"}</span>
          ) : <span className="inline-flex items-center gap-1 text-ok"><IconCheck className="size-4" aria-hidden />Legal in {cap(deck.format)}</span>}
          <span className="tabular-nums">{eur(stats?.price)}</span>
          {!!stats?.cost_to_complete && <span className="tabular-nums text-danger">{eur(stats.cost_to_complete)} to complete</span>}
          <span className="ml-auto flex flex-wrap gap-x-3 text-xs text-mute tabular-nums">
            {Object.entries(stats?.types ?? {}).map(([t, n]) => <span key={t}>{n} {t}</span>)}
          </span>
        </div>
      </div>
      {node}
    </div>
  );
}
