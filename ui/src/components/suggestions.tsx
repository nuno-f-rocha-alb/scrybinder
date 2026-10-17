import { useCallback, useEffect, useMemo, useState } from "react";
import { IconExternalLink, IconPlus } from "@tabler/icons-react";
import { api } from "../api";
import { CardImg, HoverZoom, openExternal } from "./ui";
import { GridControls, sourceFor, useCardGrid } from "./cardgrid";
import { Select } from "./select";
import { ManaCost } from "./mana";

type Sug = {
  oracle_id: string; name: string; mana_cost: string | null; cmc: number | null; colors: string[]; type_line: string | null; image_id: string | null; category: string; category_key: string;
  inclusion: number | null; synergy: number | null; lift: number | null; owned: number; free: number; elsewhere: string[];
};
type Result = { source: "edhrec" | "collection"; stale: boolean; fetched?: number; slug?: string; commander: { names: string[]; num_decks?: number; salt?: number; rank?: number }; cards: Sug[] };

const COLORS: [string, string][] = [["W", "White"], ["U", "Blue"], ["B", "Black"], ["R", "Red"], ["G", "Green"], ["M", "Multicolor"], ["C", "Colorless"]];
/** WUBRG order, then multicolor, then colorless. */
const colorKey = (c: Sug) => (c.colors.length === 0 ? "C" : c.colors.length > 1 ? "M" : c.colors[0]);
const SORTS = [["popularity", "Popularity"], ["synergy", "Synergy"], ["name", "Name"], ["color", "Color"], ["cmc", "Mana value"], ["owned", "Owned first"]] as const;
type SortBy = (typeof SORTS)[number][0];
type GroupBy = "category" | "color" | "none";
const pct = (v: number | null) => (v == null ? null : `${Math.round(v * 100)}%`);

/** Card suggestions for a Commander deck: from EDHREC when you have turned it on (one request per commander, kept for a day), else from your
 * own collection by popularity. Each card says how much of it you own and can be added to the deck. */
export default function Suggestions({ deckId, onAdded, toast }: { deckId: number; onAdded: () => void; toast: (m: string, err?: boolean) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [own, setOwn] = useState(false);
  const [freeOnly, setFreeOnly] = useState(false);
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const grid = useCardGrid();
  const [sort, setSort] = useState<SortBy>("popularity");
  const [groupBy, setGroupBy] = useState<GroupBy>("category");

  const load = useCallback((on: boolean) => {
    setBusy(true); setErr("");
    api<Result>(`/decks/${deckId}/suggestions?source=${on ? "edhrec" : "collection"}`).then(setRes).catch((e) => { setRes(null); setErr(e.message); }).finally(() => setBusy(false));
  }, [deckId]);
  useEffect(() => { api<{ enabled: boolean }>("/edhrec").then((r) => { setEnabled(r.enabled); load(r.enabled); }).catch((e) => setErr(e.message)); }, [load]);
  const turn = (on: boolean) => api<{ enabled: boolean }>("/edhrec", { method: "POST", body: JSON.stringify({ enabled: on }) }).then((r) => { setEnabled(r.enabled); load(r.enabled); }).catch((e) => toast(e.message, true));
  const add = (c: Sug) => api(`/decks/${deckId}/cards`, { method: "POST", body: JSON.stringify({ oracle_id: c.oracle_id, board: "main" }) })
    .then(() => { setRes((r) => r && { ...r, cards: r.cards.filter((x) => x.oracle_id !== c.oracle_id) }); toast(`${c.name} added to the deck`); onAdded(); }).catch((e) => toast(e.message, true));

  const cats = useMemo(() => [...new Map((res?.cards ?? []).map((c) => [c.category_key, c.category])).entries()], [res]);
  const order = useMemo(() => new Map((res?.cards ?? []).map((c, i) => [c.oracle_id, i])), [res]);  // the order the server gave: EDHREC's, or by popularity
  const cmp: Record<SortBy, (a: Sug, b: Sug) => number> = {
    popularity: (a, b) => (b.inclusion ?? 0) - (a.inclusion ?? 0),
    synergy: (a, b) => (b.synergy ?? -9) - (a.synergy ?? -9),
    name: (a, b) => a.name.localeCompare(b.name),
    color: (a, b) => COLORS.findIndex(([k]) => k === colorKey(a)) - COLORS.findIndex(([k]) => k === colorKey(b)),
    cmc: (a, b) => (a.cmc ?? 0) - (b.cmc ?? 0),
    owned: (a, b) => Number(b.free > 0) - Number(a.free > 0) || Number(b.owned > 0) - Number(a.owned > 0),
  };
  const shown = (res?.cards ?? []).filter((c) => (!own || c.owned > 0) && (!freeOnly || c.free > 0) && (!cat || c.category_key === cat) && c.name.toLowerCase().includes(q.trim().toLowerCase()));
  shown.sort((a, b) => cmp[sort](a, b) || (order.get(a.oracle_id) ?? 0) - (order.get(b.oracle_id) ?? 0) || a.name.localeCompare(b.name));
  const buckets: [string, string][] = groupBy === "category" ? cats : groupBy === "color" ? COLORS : [["", ""]];
  const groups = buckets.map(([k, label]) => ({ k, label, cards: shown.filter((c) => (groupBy === "category" ? c.category_key : groupBy === "color" ? colorKey(c) : "") === k) })).filter((g) => g.cards.length);

  return (
    <div>
      {enabled === false && (
        <div className="mb-4 rounded-xl border border-line bg-surface p-4 text-sm">
          <p className="font-medium">Suggestions from EDHREC</p>
          <p className="mt-1 text-mute">Turning this on makes Scrybinder ask <code>json.edhrec.com</code> for your commander's page: one request per commander, kept on your computer for a day. Only the commander's name is sent, nothing from your collection. Until then the list below comes from your own collection, most popular first.</p>
          <button className="btn-primary mt-3" onClick={() => turn(true)}>Turn on EDHREC suggestions</button>
        </div>
      )}
      {res && (
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-medium">{res.commander.names.join(" + ")}</span>
          {res.source === "edhrec" && <>
            {res.commander.num_decks != null && <span className="text-mute tabular-nums">{res.commander.num_decks.toLocaleString()} decks on EDHREC</span>}
            <button className="inline-flex cursor-pointer items-center gap-1 text-accent hover:underline" onClick={() => openExternal(`https://edhrec.com/commanders/${res.slug}`)}>Data from EDHREC <IconExternalLink className="size-3.5" aria-hidden /></button>
            {res.stale && <span className="text-gold" role="status">EDHREC could not be reached: showing the copy saved {res.fetched ? new Date(res.fetched * 1000).toLocaleDateString() : "earlier"}</span>}
            <button className="cursor-pointer text-mute hover:text-ink hover:underline" onClick={() => turn(false)}>Turn off</button>
          </>}
          {res.source === "collection" && <span className="text-mute">From your collection, by popularity</span>}
        </div>
      )}
      {err && <p className="mb-4 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger" role="alert">{err}</p>}
      {busy && <p className="text-mute">Loading…</p>}
      {res && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <input className="field w-56" placeholder="Search in the suggestions…" aria-label="Search in the suggestions" value={q} onChange={(e) => setQ(e.target.value)} />
          {cats.length > 1 && <Select className="field w-auto" aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>{cats.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <Select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Group
            <Select className="field w-auto" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}>
              <option value="category">Category</option><option value="color">Color</option><option value="none">None</option></Select></label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute"><input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} className="accent-[var(--color-accent)]" />Only what I own</label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Copies not assigned to any deck"><input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} className="accent-[var(--color-accent)]" />Only free copies</label>
          <GridControls g={grid} />
          <span className="text-xs text-mute tabular-nums">{shown.length} cards</span>
        </div>
      )}
      {res && !busy && shown.length === 0 && <div className="rounded-2xl border border-dashed border-line p-10 text-center text-mute">{res.cards.length ? "No suggestion matches these filters." : "Nothing to suggest right now."}</div>}
      <div ref={grid.setGridEl}>
      {groups.map((g) => (
        <section key={g.k} className="mb-6" aria-label={g.label || "Suggestions"}>
          {groupBy !== "none" && <h2 className="mb-2 border-b border-line pb-1 text-sm font-semibold">{g.label} <span className="text-xs font-normal text-mute tabular-nums">{g.cards.length}</span></h2>}
          <div className="grid gap-4" style={grid.style}>
            {g.cards.map((c) => (
              <div key={c.oracle_id} className="flex flex-col">
                <HoverZoom className="relative" zoom={c.image_id ? <CardImg id={c.image_id} size="large" /> : null}>
                  {c.image_id ? <CardImg id={c.image_id} size={sourceFor(grid.tilePx)} className="shadow-lg shadow-black/50" /> : <div className="flex aspect-[63/88] items-center justify-center rounded-[4.5%] bg-raised p-2 text-center text-xs text-mute">{c.name}</div>}
                  {c.inclusion != null && <span className="absolute right-1.5 top-1.5 rounded-full bg-black/80 px-2 py-0.5 text-xs font-semibold tabular-nums" title="Share of the decks of this commander that play it">{pct(c.inclusion)}</span>}
                </HoverZoom>
                <div className="mt-2 flex items-start justify-between gap-1 text-sm font-medium"><span className="min-w-0 truncate" title={c.name}>{c.name}</span><ManaCost cost={c.mana_cost} /></div>
                <div className={`text-xs ${c.owned ? "text-ok" : "text-mute"}`}>
                  {c.owned ? `You own ${c.owned}${c.free < c.owned ? ` · ${c.free} free` : ""}` : "Not in your collection"}
                  {c.synergy != null && <span className="ml-2 text-mute" title="How much more this commander's decks play it than others">synergy {c.synergy > 0 ? "+" : ""}{Math.round(c.synergy * 100)}%</span>}
                </div>
                {c.elsewhere.length > 0 && <div className="truncate text-xs text-mute" title={`Assigned to: ${c.elsewhere.join(", ")}`}>In {c.elsewhere.join(", ")}</div>}
                <button className="btn-ghost mt-2 !py-1" onClick={() => add(c)} aria-label={`Add ${c.name} to the deck`}><IconPlus className="size-4" />Add</button>
              </div>
            ))}
          </div>
        </section>
      ))}
      </div>
    </div>
  );
}
