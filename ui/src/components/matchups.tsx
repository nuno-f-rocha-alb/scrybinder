import { useCallback, useEffect, useState } from "react";
import { IconChevronDown, IconChevronRight, IconPlus } from "@tabler/icons-react";
import { api } from "../api";
import { CardImg, HoverZoom } from "./ui";
import { Select } from "./select";
import { ManaCost } from "./mana";

type Reason = { tag: string; label: string; exposure: number };
type Named = { name: string; quantity: number };
type Card = { oracle_id: string; name: string; mana_cost: string | null; cmc: number | null; owned: number; free: number; image_id: string | null };
type BoardIn = Card & { rel: number; copies: number; in_side: number; reasons: Reason[] };
type BoardOut = Card & { rel: number; quantity: number };
type Expect = { tag: string; label: string; main: number; side: number; cards: Named[] };
type Threat = { tag: string; label: string; your_share: number; their_main: number; their_side: number; cards: Named[] };
type Arch = {
  id: string; name: string; meta: number; colors: string; style: string; style_estimated: boolean; avg_cmc: number; shares: Record<string, number>;
  expect: Expect[]; threats: Threat[]; board_in: BoardIn[]; board_out: BoardOut[]; cover: number;
};
type Plan = Card & { quantity: number; in_side: number; helps: string[]; replaces: string[] };
type Result = { fetched: number | null; colors: string; deck: { shares: Record<string, number>; avg_cmc: number; spells: number }; labels: Record<string, string>; field: Arch[]; plan: Plan[]; cuts: (Card & { quantity: number })[] };

const pips = (colors: string) => colors.split("").map((c) => `{${c}}`).join("");
const pct = (v: number) => `${Math.round(v * 100)}%`;
/** How well the sideboard answers an archetype: the sum of the relevance of its cards against it. */
const coverage = (c: number) => (c < 0.5 ? ["Uncovered", "text-danger"] : c < 2 ? ["Thin", "text-gold"] : c < 4 ? ["Covered", "text-ok"] : ["Strong", "text-ok"]) as [string, string];
const SORTS = [["meta", "Metagame share"], ["cover", "Least covered first"], ["name", "Name"]] as const;
type SortBy = (typeof SORTS)[number][0];

function Bars({ shares, labels, skip = [] }: { shares: Record<string, number>; labels: Record<string, string>; skip?: string[] }) {
  const rows = Object.entries(shares).filter(([t, v]) => !skip.includes(t) && v >= 0.05).sort((a, b) => b[1] - a[1]);
  return (
    <ul className="space-y-1">
      {rows.map(([t, v]) => (
        <li key={t} className="flex items-center gap-2 text-xs">
          <span className="w-32 shrink-0 truncate text-mute">{labels[t] ?? t}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded bg-raised"><span className="block h-full bg-accent" style={{ width: pct(Math.min(1, v)) }} /></span>
          <span className="w-9 text-right tabular-nums">{pct(v)}</span>
        </li>
      ))}
    </ul>
  );
}

function CardRow({ c, right, onAdd, addLabel }: { c: Card; right?: React.ReactNode; onAdd?: () => void; addLabel?: string }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <HoverZoom className="min-w-0 flex-1" zoom={c.image_id ? <CardImg id={c.image_id} size="large" /> : null}>
        <span className="flex items-center justify-between gap-2"><span className="truncate" title={c.name}>{c.name}</span><ManaCost cost={c.mana_cost} /></span>
      </HoverZoom>
      <span className={`w-14 shrink-0 text-right text-xs ${c.owned ? "text-ok" : "text-mute"}`} title="Copies you own">{c.owned ? `own ${c.owned}` : "—"}</span>
      {right}
      {onAdd && <button className="btn-ghost !px-2 !py-0.5 text-xs" onClick={onAdd}><IconPlus className="size-3.5" />{addLabel ?? "Add"}</button>}
    </li>
  );
}

/** The Pauper deck against the saved metagame, archetype by archetype: what they play, what they bring against you, what of your deck that
 * hits, what to bring in and what could come out; plus a suggested sideboard that covers the field. All of it is read from card text: an
 * estimate to rank by, not a win rate. */
export default function Matchups({ deckId, source, ready, onAdded, toast }: { deckId: number; source: string; ready: boolean; onAdded: () => void; toast: (m: string, err?: boolean) => void }) {
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<SortBy>("meta");
  const [q, setQ] = useState("");

  const load = useCallback(() => {
    setBusy(true);
    api<Result>(`/pauper-meta/${source}/matchups?deck_id=${deckId}`).then((r) => { setRes(r); setErr(""); }).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  }, [source, deckId]);
  useEffect(() => { if (ready) load(); }, [ready, load]);

  const addSide = async (items: { oracle_id: string; name: string; quantity: number }[]) => {
    try {
      for (const it of items) if (it.quantity > 0) await api(`/decks/${deckId}/cards`, { method: "POST", body: JSON.stringify({ oracle_id: it.oracle_id, board: "side", quantity: it.quantity }) });  // in sequence: they share one connection
      toast(items.length === 1 ? `${items[0].name} added to the sideboard` : `${items.length} cards added to the sideboard`);
      onAdded(); load();
    } catch (e) { toast((e as Error).message, true); }
  };

  if (err) return <p className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger" role="alert">{err}</p>;
  if (!res) return <p className="text-mute">{busy ? "Analysing…" : "Waiting for the metagame…"}</p>;
  if (!res.field.length) return <div className="rounded-2xl border border-dashed border-line p-10 text-center text-mute">No metagame saved yet: refresh it first.</div>;

  const needle = q.trim().toLowerCase();
  const field = res.field.filter((a) => a.name.toLowerCase().includes(needle));
  field.sort(sort === "cover" ? (a, b) => a.cover - b.cover || b.meta - a.meta : sort === "name" ? (a, b) => a.name.localeCompare(b.name) : (a, b) => b.meta - a.meta);
  const missing = res.plan.map((p) => ({ ...p, quantity: Math.max(0, p.quantity - p.in_side) })).filter((p) => p.quantity > 0);
  const uncovered = res.field.filter((a) => coverage(a.cover)[0] === "Uncovered");
  const share = uncovered.reduce((n, a) => n + a.meta, 0);

  return (
    <div className="space-y-8">
      <section aria-label="Your deck">
        <h3 className="mb-2 text-sm font-semibold">Your deck</h3>
        {res.deck.spells ? (
          <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2">
            <div className="text-xs text-mute">{res.deck.spells} spells · average mana value {res.deck.avg_cmc}{res.colors ? ` · ${res.colors.split("").join(" ")}` : ""}
              {uncovered.length > 0 && <p className="mt-2 text-sm text-gold">Your sideboard has nothing for {uncovered.length} archetype{uncovered.length === 1 ? "" : "s"} ({Math.round(share * 10) / 10}% of the metagame): {uncovered.slice(0, 4).map((a) => a.name).join(", ")}{uncovered.length > 4 ? "…" : ""}.</p>}</div>
            <Bars shares={res.deck.shares} labels={res.labels} />
          </div>
        ) : <p className="text-sm text-mute">Add some spells to the main deck so the matchups have something to compare.</p>}
      </section>

      <section aria-label="Suggested sideboard">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-semibold">Suggested sideboard</h3>
          <span className="text-xs text-mute">chosen to cover the metagame by share, keeping what is already in your sideboard unless something is clearly better. It reads card text, so it can miss what a card does: judge the swaps</span>
          {missing.length > 0 && <button className="btn-primary !py-1 text-xs" onClick={() => addSide(missing)}>Add the {missing.reduce((n, p) => n + p.quantity, 0)} missing</button>}
        </div>
        {res.plan.length === 0 ? <p className="text-sm text-mute">Nothing in the pool answers this metagame in your colours.</p> : (
          <ul className="grid gap-x-8 gap-y-1 lg:grid-cols-2">
            {res.plan.map((p) => (
              <CardRow key={p.oracle_id} c={p}
                right={<span className="w-56 shrink-0 truncate text-xs text-mute" title={`Helps against: ${p.helps.join(", ") || "no archetype in particular"}`}><b className="mr-1 text-ink">{p.quantity}×</b>{p.in_side >= p.quantity ? "yours: kept" : p.replaces.length ? `instead of ${p.replaces.join(", ")}` : p.helps.join(", ")}</span>}
                onAdd={p.in_side < p.quantity ? () => addSide([{ ...p, quantity: p.quantity - p.in_side }]) : undefined} addLabel={`Add ${p.quantity - p.in_side}`} />
            ))}
          </ul>
        )}
        {res.cuts.length > 0 && <p className="mt-2 text-xs text-mute">Swapped out of your sideboard: {res.cuts.map((c) => `${c.quantity} ${c.name}`).join(", ")}. They score lower against this metagame by these estimates.</p>}
      </section>

      <section aria-label="The field">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-semibold">The field</h3>
          <input className="field w-48" placeholder="Search…" aria-label="Search archetypes" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="flex items-center gap-1.5 text-xs text-mute">Sort
            <Select className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        </div>
        <ul className="space-y-2">
          {field.map((a) => {
            const [word, tone] = coverage(a.cover);
            return (
              <li key={a.id} className="rounded-xl border border-line bg-surface">
                <button className="flex w-full cursor-pointer flex-wrap items-center gap-3 p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>
                  {open === a.id ? <IconChevronDown className="size-4 shrink-0 text-mute" aria-hidden /> : <IconChevronRight className="size-4 shrink-0 text-mute" aria-hidden />}
                  <span className="min-w-0 flex-1 truncate font-medium">{a.name}</span>
                  {a.colors && <ManaCost cost={pips(a.colors)} />}
                  <span className="text-xs text-mute" title={a.style_estimated ? "Estimated from the cards" : "From the site"}>{a.style}{a.style_estimated ? "?" : ""} · MV {a.avg_cmc}</span>
                  <span className="w-14 text-right text-sm font-semibold tabular-nums">{a.meta}%</span>
                  <span className={`w-24 text-right text-xs font-medium ${tone}`} title={`Your sideboard's relevance against it: ${a.cover}`}>{word}</span>
                </button>
                {open === a.id && (
                  <div className="grid gap-x-8 gap-y-5 border-t border-line p-3 lg:grid-cols-2">
                    <div>
                      <h4 className="mb-1 text-xs font-semibold uppercase text-mute">What they play</h4>
                      <Bars shares={a.shares} labels={res.labels} />
                    </div>
                    <div>
                      <h4 className="mb-1 text-xs font-semibold uppercase text-mute">What they bring against you</h4>
                      {a.expect.length === 0 ? <p className="text-xs text-mute">Nothing aimed at specific decks.</p> : (
                        <ul className="space-y-1 text-xs">
                          {a.expect.map((e) => <li key={e.tag} title={e.cards.map((c) => `${c.quantity} ${c.name}`).join(", ")}><b>{e.label}</b> <span className="text-mute">· main {e.main} · side {e.side} · {e.cards.slice(0, 3).map((c) => c.name).join(", ")}{e.cards.length > 3 ? "…" : ""}</span></li>)}
                        </ul>
                      )}
                      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase text-mute">What of your deck that hits</h4>
                      {a.threats.length === 0 ? <p className="text-xs text-ok">Nothing of your deck is a target for what they play.</p> : (
                        <ul className="space-y-1 text-xs">
                          {a.threats.map((t) => <li key={t.tag}><b className="text-gold">{t.label}</b> <span className="text-mute">· {pct(t.your_share)} of your spells · they have {t.their_main + t.their_side} answer{t.their_main + t.their_side === 1 ? "" : "s"} ({t.cards.slice(0, 3).map((c) => `${c.quantity} ${c.name}`).join(", ")})</span></li>)}
                        </ul>
                      )}
                    </div>
                    <div>
                      <h4 className="mb-1 text-xs font-semibold uppercase text-mute">Bring in</h4>
                      {a.board_in.length === 0 ? <p className="text-xs text-mute">Nothing in your colours does much against it.</p> : (
                        <ul className="space-y-1">
                          {a.board_in.map((c) => <CardRow key={c.oracle_id} c={c}
                            right={<span className="w-40 shrink-0 truncate text-xs text-mute" title={c.reasons.map((r) => `${r.label} ${pct(r.exposure)}`).join(", ")}><b className="mr-1 text-ink">{c.copies}×</b>{c.reasons.map((r) => r.label).slice(0, 2).join(", ")}</span>}
                            onAdd={c.in_side < c.copies ? () => addSide([{ ...c, quantity: c.copies - c.in_side }]) : undefined} addLabel="Add" />)}
                        </ul>
                      )}
                    </div>
                    <div>
                      <h4 className="mb-1 text-xs font-semibold uppercase text-mute">Could come out</h4>
                      {a.board_out.length === 0 ? <p className="text-xs text-mute">Everything situational in your main deck has a use against it.</p> : (
                        <ul className="space-y-1">
                          {a.board_out.map((c) => <CardRow key={c.oracle_id} c={c} right={<span className="w-40 shrink-0 text-xs text-mute"><b className="mr-1 text-ink">{c.quantity}×</b>little to hit</span>} />)}
                        </ul>
                      )}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
