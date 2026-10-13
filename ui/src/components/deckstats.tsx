import { useState } from "react";
import { IconAlertTriangle, IconCheck, IconInfoCircle, IconX } from "@tabler/icons-react";
import { eur } from "../api";
import { CardFilter, DeckStats, Format, Legality, atLeast } from "../decks";
import { ManaCost, PIP } from "./mana";

const COLORS = ["W", "U", "B", "R", "G"];
const NAME: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colourless" };
const TYPE_LABEL: Record<string, string> = {
  land: "Lands", creature: "Creatures", planeswalker: "Planeswalkers", battle: "Battles", artifact: "Artifacts", enchantment: "Enchantments",
  instant: "Instants", sorcery: "Sorceries", other: "Other",
};
const pct = (x: number) => `${Math.round(x * 100)}%`;
const card = "rounded-xl border border-line bg-surface p-4";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <dt className="text-xs text-mute">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold tabular-nums">{value}</dd>
      {hint && <div className="text-[11px] text-mute tabular-nums">{hint}</div>}
    </div>
  );
}

/** One bar of a horizontal list; a button when it can filter the deck list. */
function HBar({ label, count, max, active, onClick, color }: { label: string; count: number; max: number; active?: boolean; onClick: () => void; color?: string }) {
  return (
    <button onClick={onClick} aria-pressed={active} aria-label={`${label}: ${count}. Show these cards`}
      className={`group flex w-full cursor-pointer items-center gap-3 rounded-md px-1.5 py-1 text-left outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent ${active ? "bg-accent-soft" : ""}`}>
      <span className="w-28 shrink-0 truncate text-sm">{label}</span>
      <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-raised"><span className="block h-full rounded-full bg-accent" style={{ width: `${(count / max) * 100}%`, background: color }} /></span>
      <span className="w-8 shrink-0 text-right text-sm tabular-nums">{count}</span>
    </button>
  );
}

function Curve({ stats, active, onFilter }: { stats: DeckStats; active: CardFilter | null; onFilter: (f: CardFilter) => void }) {
  const max = Math.max(1, ...stats.curve.map((b) => b.permanents + b.spells));
  return (
    <section className={card} aria-label="Mana curve">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Mana curve</h3>
        <span className="flex items-center gap-3 text-xs text-mute">
          <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-accent" aria-hidden />Permanents</span>
          <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-gold" aria-hidden />Spells</span>
        </span>
      </div>
      <div className="flex h-44 items-end gap-2">
        {stats.curve.map((b) => {
          const total = b.permanents + b.spells, label = b.cmc === 7 ? "7+" : String(b.cmc);
          const on = active?.kind === "cmc" && active.value === String(b.cmc);
          return (
            <button key={b.cmc} disabled={!total} aria-pressed={on} aria-label={`Mana value ${label}: ${b.permanents} permanents and ${b.spells} spells. Show these cards`}
              onClick={() => onFilter({ kind: "cmc", value: String(b.cmc), label: `Mana value ${label}` })}
              className={`group flex h-full min-w-0 flex-1 cursor-pointer flex-col items-center justify-end gap-1 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default ${on ? "bg-accent-soft" : "hover:bg-raised"}`}>
              <span className="text-xs tabular-nums text-mute">{total || ""}</span>
              <span className="flex w-full max-w-9 flex-col justify-end overflow-hidden rounded-t-md" style={{ height: `${(total / max) * 100}%`, minHeight: total ? 3 : 0 }}>
                <span className="bg-gold" style={{ flexGrow: b.spells }} /><span className="bg-accent" style={{ flexGrow: b.permanents }} />
              </span>
              <span className="text-xs font-medium">{label}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Colours({ stats, active, onFilter }: { stats: DeckStats; active: CardFilter | null; onFilter: (f: CardFilter) => void }) {
  const symbols = COLORS.reduce((n, c) => n + stats.pips[c], 0), landSrc = COLORS.reduce((n, c) => n + stats.land_sources[c], 0);
  const rows = [...COLORS, "C"].filter((c) => stats.pips[c] || stats.sources[c]);
  const warn = new Map(stats.color_warnings.map((w) => [w.color, w]));
  return (
    <section className={card} aria-label="Colours">
      <h3 className="mb-1 text-sm font-semibold">Colours: symbols and mana sources</h3>
      <p className="mb-3 text-xs text-mute">A colour should have about as many sources as it has symbols. Lands that make two colours count for both.</p>
      {rows.length === 0 && <p className="text-sm text-mute">No coloured symbols or sources yet.</p>}
      <ul className="space-y-2">
        {rows.map((c) => {
          const sym = c === "C" ? 0 : stats.pips[c] / (symbols || 1), src = c === "C" ? 0 : stats.land_sources[c] / (landSrc || 1);
          const on = active?.kind === "color" && active.value === c, w = warn.get(c);
          return (
            <li key={c}>
              <button onClick={() => onFilter({ kind: "color", value: c, label: NAME[c] + " cards" })} aria-pressed={on} aria-label={`${NAME[c]}: ${stats.pips[c]} symbols, ${stats.sources[c]} sources. Show these cards`}
                className={`w-full cursor-pointer rounded-md p-1.5 text-left outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent ${on ? "bg-accent-soft" : ""}`}>
                <span className="flex items-center gap-2 text-sm">
                  <ManaCost cost={`{${c}}`} /><span className="font-medium">{NAME[c]}</span>
                  <span className="ml-auto text-xs text-mute tabular-nums">{stats.pips[c]} symbols · {stats.sources[c]} sources ({stats.land_sources[c]} lands)</span>
                </span>
                {c !== "C" && (
                  <span className="mt-1.5 grid grid-cols-[64px_1fr_36px] items-center gap-x-2 gap-y-1 text-[11px] text-mute">
                    <span>Symbols</span><span className="h-2 overflow-hidden rounded-full bg-raised"><span className="block h-full rounded-full" style={{ width: pct(sym), background: PIP[c] }} /></span><span className="tabular-nums">{pct(sym)}</span>
                    <span>Land sources</span><span className="h-2 overflow-hidden rounded-full bg-raised"><span className="block h-full rounded-full opacity-70 ring-1 ring-inset ring-ink/30" style={{ width: pct(src), background: PIP[c] }} /></span><span className="tabular-nums">{pct(src)}</span>
                  </span>
                )}
                {w && <span className="mt-1.5 flex items-center gap-1 text-xs text-gold"><IconAlertTriangle className="size-3.5" aria-hidden />Few sources for how many symbols it has</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Counts({ title, data, label, kind, active, onFilter, empty }: {
  title: string; data: Record<string, number>; label: (k: string) => string; kind: CardFilter["kind"]; active: CardFilter | null; onFilter: (f: CardFilter) => void; empty?: string;
}) {
  const entries = Object.entries(data), max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <section className={card} aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {entries.length === 0 && <p className="text-sm text-mute">{empty ?? "Nothing yet."}</p>}
      {entries.map(([k, n]) => <HBar key={k} label={label(k)} count={n} max={max} active={active?.kind === kind && active.value === k} onClick={() => onFilter({ kind, value: k, label: label(k) })} />)}
    </section>
  );
}

/** "How likely is it to have N lands (or sources of a colour) by turn T?": the hypergeometric tail over the library. */
function Odds({ stats }: { stats: DeckStats }) {
  const library = stats.totals.main;  // the commander waits in the command zone
  const [turnText, setTurnText] = useState("3");  // the fields keep what is typed (even empty); the values are clamped for the maths
  const [needText, setNeedText] = useState("3");
  const [play, setPlay] = useState(true);
  const [what, setWhat] = useState("lands");
  const clamp = (t: string, lo: number, hi: number) => Math.min(hi, Math.max(lo, parseInt(t, 10) || lo));
  const turn = clamp(turnText, 1, 10), need = clamp(needText, 1, 7);
  const K = what === "lands" ? stats.lands : stats.land_sources[what] ?? 0;
  const draws = (t: number) => 6 + t + (play ? 0 : 1);  // 7 cards and one more per turn, none on the first turn on the play
  const p = atLeast(library, K, draws(turn), need);
  return (
    <section className={`${card} lg:col-span-2`} aria-label="Chance of having enough lands">
      <h3 className="mb-1 text-sm font-semibold">Chance of having enough lands or sources</h3>
      <p className="mb-3 text-xs text-mute">From a {library}-card library, drawing {draws(turn)} cards by turn {turn} ({play ? "on the play" : "on the draw"}), {K} of them {what === "lands" ? "lands" : `${NAME[what].toLowerCase()} land sources`}.</p>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1.5 text-mute">At least
          <input type="number" min={1} max={7} className="field !w-16" value={needText} onChange={(e) => setNeedText(e.target.value)} onBlur={() => setNeedText(String(need))} /></label>
        <label className="flex items-center gap-1.5 text-mute">of
          <select className="field w-auto" value={what} onChange={(e) => setWhat(e.target.value)}>
            <option value="lands">Lands</option>
            {COLORS.filter((c) => stats.land_sources[c]).map((c) => <option key={c} value={c}>{NAME[c]} sources</option>)}
          </select></label>
        <label className="flex items-center gap-1.5 text-mute">by turn
          <input type="number" min={1} max={10} className="field !w-16" value={turnText} onChange={(e) => setTurnText(e.target.value)} onBlur={() => setTurnText(String(turn))} /></label>
        <select className="field w-auto" aria-label="On the play or on the draw" value={play ? "play" : "draw"} onChange={(e) => setPlay(e.target.value === "play")}>
          <option value="play">On the play</option><option value="draw">On the draw</option>
        </select>
        <span className="ml-auto text-2xl font-semibold tabular-nums" aria-live="polite">{pct(p)}</span>
      </div>
      <ol className="grid grid-cols-5 gap-2 sm:grid-cols-10" aria-label="The same chance on each turn">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((t) => {
          const q = atLeast(library, K, draws(t), need);
          return (
            <li key={t} className={`rounded-md px-1.5 py-1 text-center ${t === turn ? "bg-accent-soft ring-1 ring-accent" : "bg-raised"}`}>
              <div className="text-[10px] text-mute">Turn {t}</div>
              <div className="text-sm font-medium tabular-nums">{pct(q)}</div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function StatsPanel({ stats, active, onFilter }: { stats: DeckStats; active: CardFilter | null; onFilter: (f: CardFilter) => void }) {
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        <Tile label="Average mana value" value={stats.cmc.average.toLocaleString()} hint={`${stats.cmc.average_with_lands.toLocaleString()} with lands`} />
        <Tile label="Median mana value" value={String(stats.cmc.median)} hint={`${stats.cmc.median_with_lands} with lands`} />
        <Tile label="Lands" value={String(stats.lands)} hint={`${stats.totals.main + stats.totals.commander} cards`} />
        <Tile label="Price" value={eur(stats.price)} hint={stats.cost_to_complete ? `${eur(stats.cost_to_complete)} to complete` : "Nothing to buy"} />
        <Tile label="Game changers" value={String(stats.game_changers)} />
      </dl>
      <div className="grid gap-4 lg:grid-cols-2">
        <Curve stats={stats} active={active} onFilter={onFilter} />
        <Colours stats={stats} active={active} onFilter={onFilter} />
        <Counts title="Types" data={stats.types} kind="type" label={(k) => TYPE_LABEL[k] ?? k} active={active} onFilter={onFilter} />
        <Counts title="Tags" data={stats.tags} kind="tag" label={(k) => k} active={active} onFilter={onFilter} empty="No tags yet. Tag cards (ramp, removal...) to count them here." />
        <Odds stats={stats} />
      </div>
    </div>
  );
}

/** The problems of the deck in its format; a card name previews that card. */
export function LegalityPanel({ legality, format, onCard, onClose }: { legality: Legality; format: Format; onCard: (name: string) => void; onClose: () => void }) {
  const errors = legality.problems.filter((p) => p.severity === "error").length, warnings = legality.problems.length - errors;
  return (
    <section className={`${card} mb-4`} aria-label="Legality">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">
          {format === "casual" ? "Casual: no deck rules" : legality.legal ? `Legal in ${format[0].toUpperCase() + format.slice(1)}` : `${errors} ${errors === 1 ? "issue" : "issues"} in ${format[0].toUpperCase() + format.slice(1)}`}
          {warnings > 0 && <span className="ml-2 font-normal text-gold">{warnings} {warnings === 1 ? "warning" : "warnings"}</span>}
        </h3>
        <span className="ml-auto text-xs text-mute tabular-nums">{legality.counts.main} main · {legality.counts.side} side{legality.counts.commander ? ` · ${legality.counts.commander} commander` : ""} · {legality.game_changers} game changers</span>
        <button className="flex size-6 items-center justify-center rounded-md text-mute hover:bg-raised hover:text-ink" aria-label="Close the legality panel" onClick={onClose}><IconX className="size-4" /></button>
      </div>
      {legality.problems.length === 0 ? (
        <p className="flex items-center gap-1.5 text-sm text-ok"><IconCheck className="size-4" aria-hidden />No problems found.</p>
      ) : (
        <ul className="space-y-1">
          {legality.problems.map((p, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              {p.severity === "error" ? <IconAlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-label="Error" /> : <IconInfoCircle className="mt-0.5 size-4 shrink-0 text-gold" aria-label="Warning" />}
              <span>{p.card ? <button className="mr-1 cursor-pointer font-medium text-accent hover:underline" onClick={() => onCard(p.card!)}>{p.card}</button> : null}{p.card ? p.message.replace(p.card, "").replace(/^[\s:,-]+/, "") || p.message : p.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
