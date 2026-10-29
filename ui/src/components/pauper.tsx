import { useCallback, useEffect, useRef, useState } from "react";
import { IconChevronDown, IconChevronRight, IconExternalLink, IconPlus } from "@tabler/icons-react";
import { api } from "../api";
import { CardImg, HoverZoom, openExternal } from "./ui";
import { GridControls, sourceFor, useCardGrid } from "./cardgrid";
import { Select } from "./select";
import { ManaCost } from "./mana";

type Line = { oracle_id: string; name: string; quantity: number; owned: number; in_deck: number };
type Archetype = { id: string; name: string; meta: number; cat: string; author: string; event: string; date: string; url: string; colors: string; main: Line[]; side: Line[]; owned_main: number; total_main: number; match: number };
type Job = { state: "idle" | "running" | "done" | "error"; source: string | null; done: number; total: number; error: string | null };
type Meta = { fetched: number | null; stale: boolean; period: string; decks: Archetype[]; job: Job };
type Pop = { oracle_id: string; name: string; mana_cost: string | null; cmc: number | null; colors: string[]; image_id: string | null; share: number; archetypes: number; avg: number; main_share: number; side_share: number; fits: boolean; owned: number; free: number; elsewhere: string[] };

const SOURCES = [["goldfish", "MTGGoldfish"], ["top8", "MTGTop8"]] as const;
type Source = (typeof SOURCES)[number][0];
const HOME: Record<Source, string> = { goldfish: "https://www.mtggoldfish.com/metagame/pauper", top8: "https://www.mtgtop8.com/format?f=PAU" };
const SORTS = [["share", "Meta share"], ["name", "Name"], ["cmc", "Mana value"], ["owned", "Owned first"]] as const;
type SortBy = (typeof SORTS)[number][0];
const pips = (colors: string) => colors.split("").map((c) => `{${c}}`).join("");

/** The Pauper metagame for a Pauper deck: the archetypes of MTGGoldfish or MTGTop8 with a sample list each (and how much of it you own), and
 * the cards they play, most played first. Opt-in: Scrybinder asks those sites for their pages, one list per archetype, kept for a day. */
export default function PauperMeta({ deckId, onAdded, onOpenDeck, toast }: { deckId: number; onAdded: () => void; onOpenDeck: (id: number) => void; toast: (m: string, err?: boolean) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [source, setSource] = useState<Source>(() => { try { return localStorage.getItem("scrybinder.pauper-source") === "top8" ? "top8" : "goldfish"; } catch { return "goldfish"; } });
  const [meta, setMeta] = useState<Meta | null>(null);
  const [pop, setPop] = useState<Pop[] | null>(null);
  const [view, setView] = useState<"archetypes" | "cards">("archetypes");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [mono, setMono] = useState(false);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortBy>("share");
  const [board, setBoard] = useState<"main" | "side">("main");  // which part of the deck the popular cards are for
  const [fits, setFits] = useState(true);  // only cards inside the colours of the deck's spells
  const [closest, setClosest] = useState(false);  // archetypes: closest to this deck first
  const [made, setMade] = useState<Record<string, number>>({});  // archetype id -> the deck made from it (a second click opens it)
  const [busy, setBusy] = useState<string | null>(null);
  const [own, setOwn] = useState(false);
  const [missing, setMissing] = useState(false);
  const grid = useCardGrid();
  const asked = useRef(new Set<string>());  // sources already refreshed on their own since this tab opened: a failure must not loop

  const load = useCallback(() => {
    api<Meta>(`/pauper-meta/${source}?deck_id=${deckId}`).then((m) => { setMeta(m); setErr(""); }).catch((e) => setErr(e.message));
  }, [source, deckId]);
  const loadCards = useCallback(() => {
    api<{ cards: Pop[] }>(`/pauper-meta/${source}/cards?deck_id=${deckId}`).then((r) => setPop(r.cards)).catch((e) => setErr(e.message));
  }, [source, deckId]);
  const refresh = () => api<Job>(`/pauper-meta/${source}/refresh`, { method: "POST" }).then(load).catch((e) => setErr(e.message));

  useEffect(() => { api<{ enabled: boolean }>("/pauper-meta").then((r) => setEnabled(r.enabled)).catch((e) => setErr(e.message)); }, []);
  useEffect(() => { setMeta(null); setPop(null); setOpen(null); if (enabled) load(); }, [enabled, load]);
  useEffect(() => {  // no copy yet, or an old one: fetch it (once per source)
    if (!meta || meta.job.state === "running" || !meta.stale || asked.current.has(source)) return;
    asked.current.add(source);
    refresh();
  }, [meta]);  // eslint-disable-line react-hooks/exhaustive-deps
  const running = meta?.job.state === "running";
  useEffect(() => {  // follow a refresh; when it ends show what it got
    if (!running) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [running, load]);
  const finished = meta?.job.state === "done" || meta?.job.state === "error";
  useEffect(() => { if (view === "cards" && enabled && !running) loadCards(); }, [view, enabled, running, loadCards, meta?.fetched]);

  const turn = (on: boolean) => api<{ enabled: boolean }>("/pauper-meta", { method: "POST", body: JSON.stringify({ enabled: on }) }).then((r) => setEnabled(r.enabled)).catch((e) => toast(e.message, true));
  const pick = (s: Source) => { setSource(s); try { localStorage.setItem("scrybinder.pauper-source", s); } catch { /* no storage */ } };
  const create = (a: Archetype) => {
    if (made[a.id]) return onOpenDeck(made[a.id]);
    if (busy) return;
    setBusy(a.id);
    api<{ id: number }>(`/pauper-meta/${source}/create-deck`, { method: "POST", body: JSON.stringify({ id: a.id }) })
      .then((r) => { setMade((m) => ({ ...m, [a.id]: r.id })); onOpenDeck(r.id); }).catch((e) => toast(e.message, true)).finally(() => setBusy(null));
  };
  const add = (c: Pop) => api(`/decks/${deckId}/cards`, { method: "POST", body: JSON.stringify({ oracle_id: c.oracle_id, board }) })
    .then(() => { setPop((p) => p && p.filter((x) => x.oracle_id !== c.oracle_id)); toast(`${c.name} added to the ${board === "main" ? "deck" : "sideboard"}`); onAdded(); load(); }).catch((e) => toast(e.message, true));

  const needle = q.trim().toLowerCase();
  const decks = (meta?.decks ?? []).filter((a) => (!mono || a.colors.length === 1) && a.name.toLowerCase().includes(needle));
  if (closest) decks.sort((a, b) => b.match - a.match || b.meta - a.meta);
  const shareOf = (c: Pop) => (board === "main" ? c.main_share : c.side_share);
  const cmp: Record<SortBy, (a: Pop, b: Pop) => number> = {
    share: (a, b) => shareOf(b) - shareOf(a), name: (a, b) => a.name.localeCompare(b.name), cmc: (a, b) => (a.cmc ?? 0) - (b.cmc ?? 0),
    owned: (a, b) => Number(b.free > 0) - Number(a.free > 0) || Number(b.owned > 0) - Number(a.owned > 0),
  };
  const cards = (pop ?? []).filter((c) => shareOf(c) > 0 && (!fits || c.fits) && (!own || c.owned > 0) && (!missing || c.owned === 0) && c.name.toLowerCase().includes(needle));
  cards.sort((a, b) => cmp[sort](a, b) || shareOf(b) - shareOf(a) || a.name.localeCompare(b.name));
  const when = meta?.fetched ? new Date(meta.fetched * 1000).toLocaleDateString() : null;

  if (enabled === false) return (
    <div className="rounded-xl border border-line bg-surface p-4 text-sm">
      <p className="font-medium">The Pauper metagame</p>
      <p className="mt-1 text-mute">Turning this on makes Scrybinder read pages of <code>www.mtggoldfish.com</code> and <code>www.mtgtop8.com</code>: the metagame page and one sample list per archetype (about 60 pages, a refresh takes a minute or two), kept on your computer for a day. Nothing from your collection is sent.</p>
      <button className="btn-primary mt-3" onClick={() => turn(true)}>Turn on the Pauper metagame</button>
    </div>
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <div role="group" aria-label="Source" className="flex gap-1">
          {SOURCES.map(([k, l]) => <button key={k} aria-pressed={source === k} onClick={() => pick(k)} className={`cursor-pointer rounded-lg border px-3 py-1 ${source === k ? "border-accent text-ink" : "border-line text-mute hover:text-ink"}`}>{l}</button>)}
        </div>
        <div role="group" aria-label="View" className="flex gap-1">
          {([["archetypes", "Archetypes"], ["cards", "Popular cards"]] as const).map(([k, l]) => <button key={k} aria-pressed={view === k} onClick={() => setView(k)} className={`cursor-pointer rounded-lg border px-3 py-1 ${view === k ? "border-accent text-ink" : "border-line text-mute hover:text-ink"}`}>{l}</button>)}
        </div>
        <button className="inline-flex cursor-pointer items-center gap-1 text-accent hover:underline" onClick={() => openExternal(HOME[source])}>Data from {SOURCES.find(([k]) => k === source)![1]} <IconExternalLink className="size-3.5" aria-hidden /></button>
        {meta && !running && <span className="text-mute">{when ? `${meta.period}, saved ${when}` : "nothing saved yet"}</span>}
        <button className="btn-ghost !py-1 text-xs" disabled={running} onClick={refresh}>Refresh</button>
        <button className="cursor-pointer text-mute hover:text-ink hover:underline" onClick={() => turn(false)}>Turn off</button>
      </div>
      {running && <p className="mb-4 text-sm text-mute" role="status">Reading {meta!.job.source === "top8" ? "MTGTop8" : "MTGGoldfish"}… {meta!.job.done}/{meta!.job.total || "?"} lists (one page a second or so, so the sites are not overloaded)</p>}
      {finished && meta!.job.error && meta!.job.source === source && <p className="mb-4 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger" role="alert">{meta!.job.error}{meta!.decks.length ? " Showing the copy saved before." : ""}</p>}
      {err && <p className="mb-4 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger" role="alert">{err}</p>}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input className="field w-56" placeholder={view === "cards" ? "Search the cards…" : "Search the archetypes…"} aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        {view === "archetypes" && <>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute"><input type="checkbox" checked={mono} onChange={(e) => setMono(e.target.checked)} className="accent-[var(--color-accent)]" />Mono-colour only</label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Order by how much of each main deck this deck already has"><input type="checkbox" checked={closest} onChange={(e) => setClosest(e.target.checked)} className="accent-[var(--color-accent)]" />Closest to my deck first</label>
        </>}
        {view === "cards" && <>
          <label className="flex items-center gap-1.5 text-xs text-mute" title="Main deck: what the lists play maindeck. Sideboard: what they bring in against the field">For
            <Select className="field w-auto" value={board} onChange={(e) => setBoard(e.target.value as "main" | "side")}><option value="main">Main deck</option><option value="side">Sideboard</option></Select></label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="Only cards inside the colours of this deck's spells"><input type="checkbox" checked={fits} onChange={(e) => setFits(e.target.checked)} className="accent-[var(--color-accent)]" />Fits my colours</label>
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <Select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute"><input type="checkbox" checked={own} onChange={(e) => { setOwn(e.target.checked); if (e.target.checked) setMissing(false); }} className="accent-[var(--color-accent)]" />Only what I own</label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute"><input type="checkbox" checked={missing} onChange={(e) => { setMissing(e.target.checked); if (e.target.checked) setOwn(false); }} className="accent-[var(--color-accent)]" />Only what I don't own</label>
          <GridControls g={grid} />
        </>}
        <span className="text-xs text-mute tabular-nums">{view === "cards" ? cards.length : decks.length} {view === "cards" ? "cards" : "archetypes"}</span>
      </div>

      {view === "archetypes" && <>
        {meta && !running && decks.length === 0 && <div className="rounded-2xl border border-dashed border-line p-10 text-center text-mute">{meta.decks.length ? "No archetype matches these filters." : "No metagame saved yet."}</div>}
        <ul className="space-y-2">
          {decks.map((a) => (
            <li key={a.id} className="rounded-xl border border-line bg-surface">
              <div className="flex flex-wrap items-center gap-3 p-3">
                <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>
                  {open === a.id ? <IconChevronDown className="size-4 shrink-0 text-mute" aria-hidden /> : <IconChevronRight className="size-4 shrink-0 text-mute" aria-hidden />}
                  <span className="truncate font-medium">{a.name}</span>
                  {a.colors ? <ManaCost cost={pips(a.colors)} /> : <span className="text-xs text-mute">colourless</span>}
                  {a.cat && <span className="text-xs text-mute">{a.cat}</span>}
                </button>
                <span className="w-16 text-right text-sm font-semibold tabular-nums" title="Share of the metagame">{a.meta}%</span>
                <span className={`text-xs tabular-nums ${a.owned_main >= a.total_main && a.total_main ? "text-ok" : "text-mute"}`} title="Copies of the main deck you own">You own {a.owned_main}/{a.total_main}</span>
                {a.match > 0 && <span className="text-xs tabular-nums text-mute" title="Share of this main deck your deck already has">Your deck: {a.match}%</span>}
                <button className="btn-ghost !py-1" disabled={busy === a.id} onClick={() => create(a)} title={made[a.id] ? "Open the deck made from this list" : "Make a new Pauper deck from this list"}>{made[a.id] ? "Open deck" : busy === a.id ? "Creating…" : "Create deck"}</button>
              </div>
              {open === a.id && (
                <div className="border-t border-line p-3 text-sm">
                  <p className="mb-2 text-xs text-mute">{[a.author && `by ${a.author}`, a.event, a.date].filter(Boolean).join(" · ")} <button className="ml-2 inline-flex cursor-pointer items-center gap-1 text-accent hover:underline" onClick={() => openExternal(a.url)}>Source <IconExternalLink className="size-3" aria-hidden /></button></p>
                  <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                    {([["Main deck", a.main], ["Sideboard", a.side]] as const).map(([title, lines]) => lines.length > 0 && (
                      <div key={title}><h4 className="mb-1 text-xs font-semibold uppercase text-mute">{title} · {lines.reduce((n, l) => n + l.quantity, 0)}</h4>
                        <ul>{lines.map((l) => <li key={l.oracle_id + title} className={`flex justify-between gap-2 ${l.owned >= l.quantity ? "text-ok" : l.owned ? "text-gold" : ""}`}><span className="truncate">{l.quantity} {l.name}</span><span className="text-xs tabular-nums text-mute" title="You own · in this deck">{l.owned} · {l.in_deck >= l.quantity ? "✓" : l.in_deck}</span></li>)}</ul></div>
                    ))}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </>}

      {view === "cards" && <>
        {pop && !running && cards.length === 0 && <div className="rounded-2xl border border-dashed border-line p-10 text-center text-mute">{pop.length ? "No card matches these filters." : "Nothing to show: refresh the metagame first."}</div>}
        <div ref={grid.setGridEl}>
          <div className="grid gap-4" style={grid.style}>
            {cards.map((c) => (
              <div key={c.oracle_id} className="flex flex-col">
                <HoverZoom className="relative" zoom={c.image_id ? <CardImg id={c.image_id} size="large" /> : null}>
                  {c.image_id ? <CardImg id={c.image_id} size={sourceFor(grid.tilePx)} className="shadow-lg shadow-black/50" /> : <div className="flex aspect-[63/88] items-center justify-center rounded-[4.5%] bg-raised p-2 text-center text-xs text-mute">{c.name}</div>}
                  <span className="absolute right-1.5 top-1.5 rounded-full bg-black/80 px-2 py-0.5 text-xs font-semibold tabular-nums" title={`Sum of the metagame share of the archetypes that play it ${board === "main" ? "in the main deck" : "in the sideboard"}`}>{shareOf(c)}%</span>
                </HoverZoom>
                <div className="mt-2 flex items-start justify-between gap-1 text-sm font-medium"><span className="min-w-0 truncate" title={c.name}>{c.name}</span><ManaCost cost={c.mana_cost} /></div>
                <div className="text-xs text-mute">In {c.archetypes} {c.archetypes === 1 ? "list" : "lists"}{board === "main" && c.avg ? ` · ${c.avg} on average` : ""}</div>
                <div className={`text-xs ${c.owned ? "text-ok" : "text-mute"}`}>{c.owned ? `You own ${c.owned}${c.free < c.owned ? ` · ${c.free} free` : ""}` : "Not in your collection"}</div>
                <button className="btn-ghost mt-2 !py-1" onClick={() => add(c)} aria-label={`Add ${c.name} to the ${board === "main" ? "deck" : "sideboard"}`}><IconPlus className="size-4" />{board === "main" ? "Add" : "Add to side"}</button>
              </div>
            ))}
          </div>
        </div>
      </>}
    </div>
  );
}
