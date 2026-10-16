import { useState } from "react";
import { IconCheck, IconChevronDown, IconChevronRight, IconMinus, IconPlus, IconTrash } from "@tabler/icons-react";
import { api, eur } from "../api";
import { BOARDS, BOARD_LABEL, DeckCard, Group, Preview, View, shownPrints, toPreview } from "../decks";
import { CardImg, EditionTag, FinishTag } from "./ui";
import { ManaCost, STATUS_RING, StatusBadge, StatusDot } from "./mana";
import { sourceFor } from "./cardgrid";

export type Ctx = { deckId: number; act: (p: Promise<unknown>) => void; setPreview: (p: Preview) => void; onZoom: (c: DeckCard) => void; onAssign: (c: DeckCard) => void;
  onMenu: (c: DeckCard, e: React.MouseEvent) => void; hover: (c: DeckCard | null) => void; selecting?: boolean; selected?: Set<number> };
export type Layout = { tile: number; tilePx: number; style: React.CSSProperties; setGridEl: (el: HTMLDivElement | null) => void };

/** What every card element shares: the preview, the card under the pointer or focus (for the Alt+number shortcuts) and the right-click menu. */
const bind = (ctx: Ctx, c: DeckCard) => ({
  "data-dc": c.id,  // the page finds a card by it (scroll to it, flash it)
  onMouseEnter: () => { ctx.setPreview(toPreview(c)); ctx.hover(c); }, onMouseLeave: () => ctx.hover(null),
  onFocus: () => { ctx.setPreview(toPreview(c)); ctx.hover(c); }, onBlur: () => ctx.hover(null),
  onContextMenu: (e: React.MouseEvent) => ctx.onMenu(c, e),
});

/** The same few operations on a deck card in every view: one more, one less (the last one removes it), a board. */
function useOps(ctx: Ctx, c: DeckCard) {
  const url = `/decks/${ctx.deckId}/cards/${c.id}`;
  const patch = (body: object) => ctx.act(api(url, { method: "PATCH", body: JSON.stringify(body) }));
  return {
    more: () => patch({ quantity: c.quantity + 1 }),
    less: () => (c.quantity === 1 ? ctx.act(api(url, { method: "DELETE" })) : patch({ quantity: c.quantity - 1 })),
    board: (b: string) => patch({ board: b }),
  };
}

/** In select mode: a round check at the card (filled when it is selected); the row or tile itself toggles on click. */
function SelMark({ ctx, c, className = "" }: { ctx: Ctx; c: DeckCard; className?: string }) {
  if (!ctx.selecting) return null;
  const on = ctx.selected?.has(c.id);
  return <span aria-hidden className={`flex size-5 shrink-0 items-center justify-center rounded-full border-2 ${on ? "border-accent bg-accent text-white" : "border-white/70 bg-black/50"} ${className}`}>{on && <IconCheck className="size-3.5" stroke={3} />}</span>;
}
const picked = (ctx: Ctx, c: DeckCard) => !!ctx.selecting && !!ctx.selected?.has(c.id);

const STEP = "flex size-6 items-center justify-center rounded-md text-mute hover:bg-line hover:text-ink";

function Stepper({ c, ctx }: { c: DeckCard; ctx: Ctx }) {
  const o = useOps(ctx, c);
  return (
    <div className="flex items-center gap-1">
      <button className={STEP} aria-label={c.quantity === 1 ? `Remove ${c.name}` : `One less ${c.name}`} onClick={o.less}>
        {c.quantity === 1 ? <IconTrash className="size-3.5" /> : <IconMinus className="size-3.5" />}
      </button>
      <span className="w-6 text-center text-sm font-medium tabular-nums">{c.quantity}</span>
      <button className={STEP} aria-label={`One more ${c.name}`} onClick={o.more}><IconPlus className="size-3.5" /></button>
    </div>
  );
}

/** The status of a card is also the way to its copies and tags. */
function AssignBtn({ c, ctx, className = "", children }: { c: DeckCard; ctx: Ctx; className?: string; children: React.ReactNode }) {
  return (
    <button className={`cursor-pointer rounded outline-none focus-visible:ring-2 focus-visible:ring-accent ${className}`} aria-label={`Copies and tags of ${c.name}`} title="Copies and tags"
      onClick={(e) => { e.stopPropagation(); ctx.onAssign(c); }}>{children}</button>
  );
}

/** The printing(s) of a line, with the finish: the assigned copies (or the printing the deck prefers); two shown, the rest as a count. */
function PrintTags({ c }: { c: DeckCard }) {
  const s = shownPrints(c);
  return <>{s.slice(0, 2).map((p, i) => <span key={i} className="inline-flex shrink-0 items-center gap-1"><EditionTag setCode={p.set_code} number={p.collector_number} title={p.set_name} /><FinishTag finish={p.finish} /></span>)}
    {s.length > 2 && <span className="shrink-0 text-[11px] text-mute" title={`${s.length} printings`}>+{s.length - 2}</span>}</>;
}

const elsewhereHint = (c: DeckCard) => (c.elsewhere.length ? `Assigned to: ${c.elsewhere.map((e) => e.name).join(", ")}` : undefined);
const Tags = ({ c }: { c: DeckCard }) => <>{c.tags.map((t) => <span key={t} className="shrink-0 rounded-md bg-raised px-1.5 py-0.5 text-[10.5px] text-mute">{t}</span>)}</>;

/** List: every control on a row. On narrow screens the price and the board selector go away. */
function ListRow({ c, ctx }: { c: DeckCard; ctx: Ctx }) {
  const o = useOps(ctx, c);
  return (
    <li {...bind(ctx, c)} onClick={() => ctx.onZoom(c)}
      className={`grid grid-cols-[84px_minmax(0,1fr)_auto_104px] items-center gap-3 rounded-md px-2 py-1 hover:bg-raised md:grid-cols-[84px_minmax(0,1fr)_auto_116px_64px_92px] ${picked(ctx, c) ? "bg-accent-soft" : ""}`}>
      <div onClick={(e) => e.stopPropagation()}><Stepper c={c} ctx={ctx} /></div>
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <SelMark ctx={ctx} c={c} />
        <span className="truncate">{c.name}</span>
        <PrintTags c={c} />
        {c.missing > 0 && <span className="shrink-0 text-xs text-danger">{c.missing} missing</span>}
        <span className="hidden items-center gap-2 sm:flex"><Tags c={c} /></span>
      </div>
      <span className="justify-self-end"><ManaCost cost={c.mana_cost} /></span>
      <AssignBtn c={c} ctx={ctx} className="px-1 text-left hover:bg-line"><StatusBadge status={c.status} title={elsewhereHint(c)} /></AssignBtn>
      <span className="hidden text-right text-xs text-mute tabular-nums md:block">{eur(c.price)}</span>
      <select className="field hidden !w-auto !px-1.5 !py-0.5 text-xs md:block" aria-label={`Board of ${c.name}`} value={c.board} onClick={(e) => e.stopPropagation()}
        onChange={(e) => o.board(e.target.value)}>
        {BOARDS.map((b) => <option key={b} value={b}>{BOARD_LABEL[b]}</option>)}
      </select>
    </li>
  );
}

/** Compact: one dense line per card, the groups flow into as many columns as fit. The status is an icon. */
function CompactRow({ c, ctx }: { c: DeckCard; ctx: Ctx }) {
  const o = useOps(ctx, c);
  return (
    <li {...bind(ctx, c)} onClick={() => ctx.onZoom(c)}
      className={`group flex min-h-[30px] items-center gap-2 rounded px-1.5 py-[3px] text-[13px] hover:bg-raised ${picked(ctx, c) ? "bg-accent-soft" : ""}`}>
      <SelMark ctx={ctx} c={c} />
      <span className="w-5 shrink-0 text-right tabular-nums text-mute">{c.quantity}</span>
      <span className="min-w-0 flex-1 truncate">{c.name}</span>
      <PrintTags c={c} />
      <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex group-focus-within:flex" onClick={(e) => e.stopPropagation()}>
        <button className={STEP} aria-label={`One less ${c.name}`} onClick={o.less}><IconMinus className="size-3" /></button>
        <button className={STEP} aria-label={`One more ${c.name}`} onClick={o.more}><IconPlus className="size-3" /></button>
      </span>
      <AssignBtn c={c} ctx={ctx}><StatusDot status={c.status} title={elsewhereHint(c)} /></AssignBtn>
    </li>
  );
}

/** A card as an image, with its quantity, its collection status as a frame and an icon, and − / + on hover or focus. */
function Tile({ c, ctx, layout, crop }: { c: DeckCard; ctx: Ctx; layout: Layout; crop: boolean }) {
  const o = useOps(ctx, c);
  return (
    <div tabIndex={0} {...bind(ctx, c)} onClick={() => ctx.onZoom(c)}
      aria-label={`${c.quantity} ${c.name}, ${c.status}`}
      className={`group relative overflow-hidden rounded-[4.5%] outline-none ring-2 ring-offset-0 transition focus-visible:ring-accent ${picked(ctx, c) ? "ring-accent brightness-75" : STATUS_RING[c.status]} hover:ring-accent`}>
      {c.image_id ? <CardImg id={c.image_id} size={sourceFor(layout.tilePx)} className={crop ? "!aspect-[63/62] object-top" : ""} />
        : <div className={`flex w-full items-center justify-center bg-raised p-2 text-center text-xs text-mute ${crop ? "aspect-[63/62]" : "aspect-[63/88]"}`}>{c.name}</div>}
      <span className="absolute left-1.5 top-1.5 flex flex-col items-start gap-1">
        <SelMark ctx={ctx} c={c} />
        {c.quantity > 1 && <span className="rounded-md bg-bg/90 px-1.5 py-0.5 text-xs font-semibold tabular-nums">×{c.quantity}</span>}
        {shownPrints(c).slice(0, 2).map((p, i) => <span key={i} className="flex items-center gap-1"><span className="rounded-md bg-bg/90 px-1.5 py-0.5 text-[10.5px] uppercase tabular-nums">{p.set_code} #{p.collector_number}</span><FinishTag finish={p.finish} /></span>)}
      </span>
      <span className="absolute right-1.5 top-1.5"><AssignBtn c={c} ctx={ctx}><StatusDot status={c.status} title={elsewhereHint(c)} /></AssignBtn></span>
      <span className="absolute inset-x-0 bottom-0 flex justify-center gap-1 bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-6 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
        onClick={(e) => e.stopPropagation()}>
        <button className="flex size-7 items-center justify-center rounded-md bg-bg/90 text-ink hover:bg-accent" aria-label={c.quantity === 1 ? `Remove ${c.name}` : `One less ${c.name}`} onClick={o.less}>
          {c.quantity === 1 ? <IconTrash className="size-4" /> : <IconMinus className="size-4" />}
        </button>
        <button className="flex size-7 items-center justify-center rounded-md bg-bg/90 text-ink hover:bg-accent" aria-label={`One more ${c.name}`} onClick={o.more}><IconPlus className="size-4" /></button>
      </span>
    </div>
  );
}

/** One strip of a stack: only the title bar shows, the card under the pointer (or focus) opens, and so does the last one. */
function Strip({ c, ctx, layout, last, copy }: { c: DeckCard; ctx: Ctx; layout: Layout; last: boolean; copy?: number }) {
  const strip = Math.round(layout.tilePx * 0.15), full = Math.round((layout.tilePx * 88) / 63);
  const o = useOps(ctx, c);
  return (
    <div tabIndex={0} {...bind(ctx, c)} onClick={() => ctx.onZoom(c)}
      aria-label={`${c.quantity} ${c.name}, ${c.status}`}
      style={{ "--strip": `${strip}px`, "--full": `${full}px` } as React.CSSProperties}
      className={`group relative shrink-0 overflow-hidden rounded-[5px] outline-none ring-2 transition-[height] duration-150 motion-reduce:transition-none ${STATUS_RING[c.status]} hover:ring-accent focus-visible:ring-accent ${picked(ctx, c) ? "!ring-accent brightness-75" : ""} ${last ? "h-(--full)" : "h-(--strip) hover:h-(--full) focus:h-(--full)"}`}>
      {c.image_id ? <CardImg id={c.image_id} size={sourceFor(layout.tilePx)} className="!rounded-none" /> : <div className="h-full bg-raised p-1 text-xs">{c.name}</div>}
      <span className="absolute left-1 top-0.5 flex items-center gap-1">
        <SelMark ctx={ctx} c={c} className="!size-4" />
        {copy === undefined && c.quantity > 1 && <span className="rounded bg-bg/90 px-1 text-[11px] font-semibold tabular-nums">×{c.quantity}</span>}
        <FinishTag finish={shownPrints(c)[0]?.finish} />
      </span>
      <span className="absolute right-1 top-0.5"><AssignBtn c={c} ctx={ctx}><StatusDot status={c.status} title={elsewhereHint(c)} /></AssignBtn></span>
      <span className="absolute inset-x-0 bottom-0 hidden justify-center gap-1 bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-6 group-hover:flex group-focus-within:flex" onClick={(e) => e.stopPropagation()}>
        <button className="flex size-7 items-center justify-center rounded-md bg-bg/90 hover:bg-accent" aria-label={`One less ${c.name}`} onClick={o.less}><IconMinus className="size-4" /></button>
        <button className="flex size-7 items-center justify-center rounded-md bg-bg/90 hover:bg-accent" aria-label={`One more ${c.name}`} onClick={o.more}><IconPlus className="size-4" /></button>
      </span>
    </div>
  );
}

/** The title of a group; a click folds it (a folded group shows only this line). */
const Heading = ({ g, folded, onToggle }: { g: Group; folded: boolean; onToggle: () => void }) => (
  <h2 className={`flex items-center border-b border-line text-sm font-semibold ${folded ? "mb-3" : "mb-1.5"}`}>
    <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded pb-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-expanded={!folded} onClick={onToggle}
      title={folded ? "Show these cards" : "Hide these cards"}>
      {folded ? <IconChevronRight className="size-4 shrink-0 text-mute" aria-hidden /> : <IconChevronDown className="size-4 shrink-0 text-mute" aria-hidden />}
      {g.pip && <ManaCost cost={g.pip} />}{g.label}<span className="text-xs font-normal text-mute">{g.count}</span>
    </button>
  </h2>
);

/** The groups of a deck in the chosen view. Every view is responsive: columns and stacks flow into the space there is. */
export function DeckView({ groups, view, every, ctx, layout, folded, onToggle }: { groups: Group[]; view: View; every: boolean; ctx: Ctx; layout: Layout; folded: Set<string>; onToggle: (key: string) => void }) {
  const head = (g: Group) => <Heading g={g} folded={folded.has(g.key)} onToggle={() => onToggle(g.key)} />;
  if (view === "list") {
    return <>{groups.map((g) => <section key={g.key} className="mb-5" aria-label={g.label}>{head(g)}
      {!folded.has(g.key) && <ul>{g.cards.map((c) => <ListRow key={c.id} c={c} ctx={ctx} />)}</ul>}</section>)}</>;
  }
  if (view === "compact") {
    return (
      <div className="columns-[260px] gap-6">
        {groups.map((g) => <section key={g.key} className="mb-4 break-inside-avoid" aria-label={g.label}>{head(g)}
          {!folded.has(g.key) && <ul>{g.cards.map((c) => <CompactRow key={c.id} c={c} ctx={ctx} />)}</ul>}</section>)}
      </div>
    );
  }
  if (view === "stacks") {
    return (
      <div ref={layout.setGridEl} className="flex flex-wrap items-start gap-x-4 gap-y-6">
        {groups.map((g) => {
          const items = g.cards.flatMap((c) => (every ? Array.from({ length: c.quantity }, (_, i) => ({ c, i })) : [{ c, i: -1 }]));
          return (
            <section key={g.key} aria-label={g.label} style={{ width: layout.tilePx }} className="shrink-0">
              {head(g)}
              {!folded.has(g.key) && <div className="flex flex-col gap-[3px]">
                {items.map(({ c, i }, n) => <Strip key={`${c.id}:${i}`} c={c} ctx={ctx} layout={layout} last={n === items.length - 1} copy={i < 0 ? undefined : i} />)}
              </div>}
            </section>
          );
        })}
      </div>
    );
  }
  // grid (cards cropped to their title and art) and spoiler (whole cards, text readable)
  return (
    <div ref={layout.setGridEl}>
      {groups.map((g) => (
        <section key={g.key} className="mb-6" aria-label={g.label}>
          {head(g)}
          {!folded.has(g.key) && <div className="grid gap-4" style={layout.style}>{g.cards.map((c) => <Tile key={c.id} c={c} ctx={ctx} layout={layout} crop={view === "grid"} />)}</div>}
        </section>
      ))}
    </div>
  );
}

/** A big card in a dialog: what the preview panel shows, for screens that have no room for it (or no hover). */
export function useZoom() {
  const [zoom, setZoom] = useState<DeckCard | null>(null);
  const wide = () => window.matchMedia("(min-width: 1024px)").matches;
  return { zoom, close: () => setZoom(null), onZoom: (c: DeckCard) => { if (!wide()) setZoom(c); }, show: setZoom };
}
