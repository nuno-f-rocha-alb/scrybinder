import { useEffect, useState } from "react";
import { IconAdjustmentsHorizontal, IconPlus, IconSearch } from "@tabler/icons-react";
import { api, qs } from "../api";
import { BOARDS, BOARD_LABEL, Board, Deck, OracleRow, Preview, resultPreview } from "../decks";
import { ManaCost } from "./mana";
import { nameAndLinks, useContextMenu } from "./contextmenu";
import CardDetails from "./carddetails";

const COLORS = ["W", "U", "B", "R", "G", "C"];
const NAME: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colourless" };

/** Search for cards to add: by name, and with filters (rules text, type, colours, mana value, owned, sort). Enter adds the first result. */
export default function AddCards({ deck, onAdd, setPreview, toast }: { deck: Deck; onAdd: (oracleId: string, board: Board, newLine: boolean) => void; setPreview: (p: Preview) => void; toast: (m: string, err?: boolean) => void }) {
  const menu = useContextMenu();
  const [details, setDetails] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [board, setBoard] = useState<Board>(deck.format === "commander" && !deck.cards.some((c) => c.board === "commander") ? "commander" : "main");
  const [legalOnly, setLegalOnly] = useState(true);
  const [more, setMore] = useState(false);
  const [separate, setSeparate] = useState(() => { try { return localStorage.getItem("scrybinder.separate") === "1"; } catch { return false; } });
  const [text, setText] = useState("");
  const [type, setType] = useState("");
  const [colors, setColors] = useState<string[]>([]);
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  const [owned, setOwned] = useState(false);
  const [sort, setSort] = useState("name");
  const [rows, setRows] = useState<OracleRow[]>([]);
  const [total, setTotal] = useState(0);
  const [done, setDone] = useState("");  // the query whose results are shown: "No cards found" only once the search has answered

  const params = { q, text, type, colors: colors.join(""), cmc_min: lo, cmc_max: hi, owned: owned ? "true" : "", sort, deck: deck.id, legal: legalOnly ? "true" : "", limit: 20 };
  const key = qs(params);
  const searching = !!(q.trim() || text.trim() || type.trim() || colors.length || lo || hi || owned);
  useEffect(() => {
    if (!searching) { setRows([]); setTotal(0); return; }
    let live = true;  // an older, slower answer must not replace a newer one
    const t = setTimeout(() => api<{ rows: OracleRow[]; total: number }>("/oracle/search?" + key)
      .then((r) => { if (live) { setRows(r.rows); setTotal(r.total); setDone(key); } }).catch(() => { if (live) { setRows([]); setTotal(0); setDone(key); } }), 200);
    return () => { live = false; clearTimeout(t); };
  }, [key, searching, deck.cards]);

  const add = (r: OracleRow) => onAdd(r.oracle_id, board, separate);
  const setSep = (v: boolean) => { setSeparate(v); try { localStorage.setItem("scrybinder.separate", v ? "1" : "0"); } catch { /* no storage */ } };
  const toggle = (c: string) => setColors((cur) => (cur.includes(c) ? cur.filter((x) => x !== c) : c === "C" ? ["C"] : [...cur.filter((x) => x !== "C"), c]));
  const clear = () => { setText(""); setType(""); setColors([]); setLo(""); setHi(""); setOwned(false); setSort("name"); };
  const filtered = !!(text || type || colors.length || lo || hi || owned || sort !== "name");

  return (
    <div className="mb-5 rounded-xl border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" aria-hidden />
          <input className="field pl-9" placeholder="Find cards to add…" aria-label="Find cards to add" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && rows[0]) add(rows[0]); }} />
        </div>
        <button className={`btn-ghost ${filtered ? "!border-accent" : ""}`} aria-expanded={more} onClick={() => setMore((v) => !v)}><IconAdjustmentsHorizontal className="size-4" />Filters{filtered ? " •" : ""}</button>
        <select className="field w-auto" value={board} aria-label="Add to" onChange={(e) => setBoard(e.target.value as Board)}>
          {BOARDS.map((b) => <option key={b} value={b}>{BOARD_LABEL[b]}</option>)}
        </select>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="A card already in the deck gets a line of its own instead of adding to the existing one, so each line can have another printing">
          <input type="checkbox" checked={separate} onChange={(e) => setSep(e.target.checked)} className="accent-[var(--color-accent)]" />Separate line
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Only cards legal in this deck's format (and its commander's colours)">
          <input type="checkbox" checked={legalOnly} onChange={(e) => setLegalOnly(e.target.checked)} className="accent-[var(--color-accent)]" />Only legal
        </label>
      </div>

      {more && (
        <div className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-xs text-mute"><span className="mb-1 block">Rules text</span><input className="field" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. draw a card" /></label>
          <label className="block text-xs text-mute"><span className="mb-1 block">Type</span><input className="field" value={type} onChange={(e) => setType(e.target.value)} placeholder="e.g. legendary creature" /></label>
          <div className="text-xs text-mute"><span className="mb-1 block">Mana value</span>
            <span className="flex items-center gap-2">
              <input className="field" type="number" min={0} aria-label="Mana value from" placeholder="from" value={lo} onChange={(e) => setLo(e.target.value)} />
              <input className="field" type="number" min={0} aria-label="Mana value to" placeholder="to" value={hi} onChange={(e) => setHi(e.target.value)} /></span></div>
          <label className="block text-xs text-mute"><span className="mb-1 block">Sort by</span>
            <select className="field" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="name">Name</option><option value="cmc">Mana value</option><option value="popularity">Popularity</option></select></label>
          <div className="sm:col-span-2 lg:col-span-3"><span className="mb-1 block text-xs text-mute">Colours (all of the chosen ones)</span>
            <span className="flex flex-wrap items-center gap-2" role="group" aria-label="Colours">
              {COLORS.map((c) => (
                <button key={c} aria-pressed={colors.includes(c)} aria-label={NAME[c]} title={NAME[c]} onClick={() => toggle(c)}
                  className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-accent ${colors.includes(c) ? "border-accent bg-accent-soft text-ink" : "border-line text-mute hover:bg-raised"}`}>
                  <ManaCost cost={`{${c}}`} />{NAME[c]}</button>
              ))}
              <label className="ml-2 flex cursor-pointer items-center gap-2 text-sm text-mute"><input type="checkbox" checked={owned} onChange={(e) => setOwned(e.target.checked)} className="accent-[var(--color-accent)]" />Only cards I own</label>
            </span></div>
          <div className="flex items-end justify-end"><button className="btn-ghost !py-1 text-xs" disabled={!filtered} onClick={clear}>Clear filters</button></div>
        </div>
      )}

      {searching && done === key && rows.length === 0 && <p className="mt-3 text-sm text-mute">No cards found.</p>}
      {rows.length > 0 && (
        <>
          <p className="mt-3 text-xs text-mute tabular-nums">{total > rows.length ? `${rows.length} of ${total} cards. Narrow it down to see the rest.` : `${total} ${total === 1 ? "card" : "cards"}`}</p>
          <ul className="mt-1 max-h-96 divide-y divide-line overflow-y-auto">
            {rows.map((r) => (
              <li key={r.oracle_id} onMouseEnter={() => setPreview(resultPreview(r))} onContextMenu={(e) => menu.open(e, [
                ...BOARDS.map((b) => ({ label: `Add to ${BOARD_LABEL[b].toLowerCase()}`, onSelect: () => onAdd(r.oracle_id, b, separate) })),
                ...(r.id ? [{ label: "View details", onSelect: () => setDetails(r.id) }] : []),
                "sep" as const, ...nameAndLinks(r.name, r.id, null, toast)])} className="flex items-center gap-3 px-1 py-1.5 hover:bg-raised">
                <button className="btn-ghost !px-2 !py-1" onClick={() => add(r)} aria-label={`Add ${r.name}`}><IconPlus className="size-4" /></button>
                <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
                <ManaCost cost={r.mana_cost} />
                <span className="hidden w-48 truncate text-xs text-mute md:block">{r.type_line}</span>
                <span className="w-24 text-right text-xs text-mute tabular-nums">{r.in_deck ? `${r.in_deck} in deck · ` : ""}{r.owned} owned</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {details && <CardDetails printId={details} onClose={() => setDetails(null)} />}
      {menu.node}
    </div>
  );
}
