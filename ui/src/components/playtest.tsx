import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CardImg, Modal } from "./ui";
import { MenuItem, useContextMenu } from "./contextmenu";
import { usePointerDrag } from "./pointerdrag";
import type { DropAt } from "./pointerdrag";
import CardDetails from "./carddetails";
import type { DeckCard } from "../decks";
import { Box, GCard, Game, STEPS, SimResult, Step, Zone, addCounter, addNamed, attach, bottomMany, detach, draw, isLand, keep, move, mulligan, newGame, nextPhase, nextTurn, peek, placeCard, placeOf, pushHistory, reorderTop, seeded, settle, shuffleLibrary, simulate, toggleTap, token, untapAll } from "../goldfish";
import { warnings } from "../rules";
import { MatLayer, usePlaymat } from "./playmat";

const btn = "cursor-pointer rounded-lg border border-line px-3 py-1.5 text-sm outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default disabled:opacity-40";
const act = "cursor-pointer rounded-lg border border-accent/50 bg-accent/20 px-3 py-1.5 text-sm font-medium outline-none hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default disabled:opacity-40";  // the game actions, next to the hand
const ZONE_LABEL: Record<Zone, string> = { hand: "Hand", battlefield: "Battlefield", graveyard: "Graveyard", exile: "Exile", library: "Library", command: "Command zone" };
/** The whole turn as the bar shows it: untap and draw are steps too, but the game does them by itself instead of stopping there. */
const TURN: { key: string; label: string; step?: Step; auto?: string }[] = [
  { key: "untap", label: "Untap", auto: "Automatic: everything untaps when a turn begins" }, { key: "upkeep", label: "Upkeep", step: "upkeep" },
  { key: "draw", label: "Draw", auto: "Automatic: you draw on leaving upkeep" }, { key: "main1", label: "Main 1", step: "main1" },
  { key: "combat", label: "Combat", step: "combat" }, { key: "main2", label: "Main 2", step: "main2" }, { key: "end", label: "End", step: "end" },
];
const ZONES: Zone[] = ["library", "hand", "battlefield", "graveyard", "exile", "command"];
/** The card width of the table follows the window height, so the phase bar, the table and the hand fit on one screen. */
const CW = "clamp(4.25rem, 12vh, 6rem)";  // a card on the table at zoom 1
const ZOOMS = [1, 1.25, 1.5, 2, 2.5, 3];
const CARD_W = { "--cw": CW, "--hw": "clamp(5.5rem, 16vh, 9.5rem)" } as React.CSSProperties;

function Face({ c, w = "w-(--cw)" }: { c: GCard; w?: string }) {
  return c.image_id ? <div className={w}><CardImg id={c.image_id} size="normal" /></div>
    : <div className={`${w} flex aspect-[63/88] items-center justify-center rounded bg-raised p-1 text-center text-xs`}>{c.name}</div>;
}

/** A card on the table: click acts, press and drag moves it, right-click lists the moves. A tapped card turns sideways in a square cell so its neighbours do not overlap. */
function Card({ c, onClick, onMenu, at, lifted, ring, warn, badge, onHover, onPress, fan }: { c: GCard; onClick?: () => void; onMenu: (e: React.MouseEvent) => void; at?: { x: number; y: number; z: number; box: Box }; lifted?: boolean; ring?: boolean; warn?: boolean; badge?: number; onHover?: (c: GCard | null, at?: DOMRect) => void; onPress?: (e: React.PointerEvent) => void; fan?: { i: number; n: number } }) {
  const counters = [c.plus ? `${c.plus > 0 ? "+" : "−"}${Math.abs(c.plus)}/${c.plus > 0 ? "+" : "−"}${Math.abs(c.plus)}` : "", ...Object.entries(c.named ?? {}).map(([k, n]) => `${k} ${n}`)].filter(Boolean);
  const d = fan ? (fan.i - (fan.n - 1) / 2) * Math.min(1, 7 / Math.max(fan.n - 1, 1)) : 0;  // the fan: each card turns and sinks a little more the further it is from the middle (a big hand spreads less, so it stays on the screen)
  return (
    <button onClick={onClick} onContextMenu={onMenu} data-uid={at ? c.uid : undefined} aria-label={`${c.name}${c.tapped ? " (tapped)" : ""}${counters.length ? `, ${counters.join(", ")}` : ""}`} title={`${c.name} — drag to move, right-click for more`}
      onMouseEnter={(e) => { if (fan) e.currentTarget.style.setProperty("--zs", String(288 / e.currentTarget.offsetWidth)); onHover?.(c, e.currentTarget.getBoundingClientRect()); }} onMouseLeave={() => onHover?.(null)} onFocus={(e) => onHover?.(c, e.currentTarget.getBoundingClientRect())} onBlur={() => onHover?.(null)} onPointerDown={onPress}
      style={fan ? { "--r": `${d * 4}deg`, "--y": `${d * d * 2}px`, marginLeft: fan.i ? `calc(var(--hw) * ${-(1 - Math.min(0.8, 5.8 / Math.max(fan.n - 1, 1)))})` : 0, "--z": fan.i } as React.CSSProperties
        : at ? { position: "absolute", left: `${Math.min(at.x, 1 - at.box.w) * 100}%`, top: `${Math.min(at.y, 1 - at.box.h) * 100}%`, zIndex: at.z, width: "var(--cw)", opacity: lifted ? 0 : undefined, pointerEvents: lifted ? "none" : undefined } : undefined}  // on the free table, kept inside it
      className={`group relative flex shrink-0 cursor-pointer touch-none select-none items-center justify-center rounded-lg outline-none transition-transform focus-visible:ring-2 focus-visible:ring-accent ${fan ? "pointer-events-auto z-(--z) [transform:translateY(calc(var(--y)_+_var(--sink,0%)))_rotate(var(--r))] hover:z-[100] hover:[transform:none] focus-visible:z-[100] focus-visible:[transform:none] " : ""} ${ring ? "ring-2 ring-accent" : warn ? "ring-2 ring-amber-400" : ""}`}>
      <span className={`pointer-events-none block transition-transform ${c.tapped ? "rotate-90" : ""} ${fan ? "origin-bottom group-hover:scale-(--zs) group-focus-visible:scale-(--zs)" : ""}`}>  {/* a hand card grows in place to the size of the preview, straightened and above the others */}<Face c={c} w={fan ? "w-(--hw)" : undefined} /></span>
      {!!badge && <span className="absolute right-0 top-0 rounded bg-accent px-1 text-[11px] font-semibold text-white" title="Cards attached to this one">+{badge}</span>}
      {counters.length > 0 && <span className="absolute bottom-1 left-1/2 flex -translate-x-1/2 flex-col items-center gap-0.5 text-[11px] font-semibold">
        {counters.map((t) => <span key={t} className="rounded bg-black/80 px-1.5 text-white">{t}</span>)}</span>}
    </button>
  );
}

/** The back of a card, drawn here (nothing is downloaded): a dark border, a brown field and the oval with its rings. */
const CardBack = ({ className = "" }: { className?: string }) => (
  <svg viewBox="0 0 63 88" className={className} role="img" aria-label="Card back">
    <defs><radialGradient id="cb-f" cx="50%" cy="50%" r="70%"><stop offset="0" stopColor="#b5623a" /><stop offset="1" stopColor="#5a2a16" /></radialGradient>
      <radialGradient id="cb-o" cx="50%" cy="45%" r="60%"><stop offset="0" stopColor="#f3c27a" /><stop offset="0.55" stopColor="#c2562f" /><stop offset="1" stopColor="#3b4f8c" /></radialGradient></defs>
    <rect width="63" height="88" rx="3.2" fill="#14110f" />
    <rect x="3.5" y="3.5" width="56" height="81" rx="2" fill="url(#cb-f)" stroke="#2a1a10" strokeWidth="0.6" />
    <ellipse cx="31.5" cy="44" rx="19" ry="26" fill="url(#cb-o)" stroke="#1a1410" strokeWidth="1.2" />
    <ellipse cx="31.5" cy="44" rx="14" ry="20" fill="none" stroke="#f3dcae" strokeOpacity="0.7" strokeWidth="0.7" />
    <ellipse cx="31.5" cy="44" rx="8.5" ry="12.5" fill="none" stroke="#f3dcae" strokeOpacity="0.6" strokeWidth="0.7" />
    <ellipse cx="31.5" cy="44" rx="3.2" ry="4.8" fill="#14110f" fillOpacity="0.55" />
  </svg>
);

/** A pile to the side of the battlefield: the top card (or an empty slot), a name and a count. */
function Pile({ label, cards, onClick, back, zone, cls = "" }: { label: string; cards: GCard[]; onClick?: () => void; back?: boolean; zone: React.HTMLAttributes<HTMLElement>; cls?: string }) {
  const top = cards[0];
  const slot = "aspect-[63/88] w-[calc(var(--cw)*0.85)] rounded-[4.5%]";
  return (
    <button onClick={onClick} disabled={!onClick} aria-label={`${label}: ${cards.length} cards`} {...(zone as object)}
      className={`flex cursor-pointer flex-col items-center gap-1 rounded-lg p-1 outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default ${zone.className ?? ""} ${cls}`}>
      {back && cards.length ? <CardBack className={slot} />
        : !back && top ? <Face c={top} w="w-[calc(var(--cw)*0.85)]" />
        : <div className={`${slot} border border-dashed border-line`} />}
      <span className="text-xs text-mute">{label} ({cards.length})</span>
    </button>
  );
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

/** Deals many opening hands to see how consistent the deck is: land counts, keepable hands, colours by turn 4. */
function Simulate({ cards, commander }: { cards: DeckCard[]; commander: boolean }) {
  const [n, setN] = useState(1000);
  const [res, setRes] = useState<SimResult | null>(null);
  const run = () => setRes(simulate(cards, commander, Math.min(Math.max(1, n || 1), 100000), seeded(Date.now())));
  const [lo, hi] = commander ? [3, 5] : [2, 4];
  return (
    <section aria-label="Simulate opening hands" className="mt-8 rounded-xl border border-line p-4">
      <h3 className="mb-2 text-sm font-medium">Simulate opening hands</h3>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm">Hands
          <input type="number" min={1} max={100000} value={n} onChange={(e) => setN(Number(e.target.value))} aria-label="Number of hands"
            className="w-24 rounded-lg border border-line bg-raised px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent" /></label>
        <button className={btn} onClick={run}>Run</button>
      </div>
      {res && (
        <dl className="mt-3 grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm" aria-live="polite">
          <dt>Keepable hands ({lo}–{hi} lands)</dt><dd className="font-medium">{pct(res.keepableShare)}</dd>
          <dt>Lands in the opening seven</dt><dd className="font-medium">{res.avgLandsOpening.toFixed(2)}</dd>
          <dt>Lands seen by turn 4</dt><dd className="font-medium">{res.avgLandsByTurn4.toFixed(2)}</dd>
          <dt>Every colour from a land by turn 4</dt><dd className="font-medium">{pct(res.allColorsByTurn4Share)}</dd>
        </dl>
      )}
      <p className="mt-2 text-xs text-mute">Raw opening sevens without mulligans, on the play (turn 4 = seven cards plus three draws). Mana rocks and dorks do not count as colour sources.</p>
    </section>
  );
}

/** The opening hand in a window of its own: Keep or Mulligan; after a Keep that owes cards (London mulligan), pick which go to the bottom. */
function OpeningHand({ g, set }: { g: Game; set: (f: (x: Game) => Game) => void }) {
  const [pick, setPick] = useState<number[]>([]);  // the cards for the bottom, in the order chosen (this component is remounted for each phase)
  const bottom = g.phase === "bottom";
  const toggle = (uid: number) => setPick((p) => (p.includes(uid) ? p.filter((u) => u !== uid) : p.length < g.toBottom ? [...p, uid] : p));
  return (
    <div role="dialog" aria-modal aria-label="Opening hand" className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-2 overflow-hidden bg-black/80 px-4 backdrop-blur-sm">
      <h2 className="text-center text-3xl font-semibold">{bottom ? `Put ${g.toBottom} card${g.toBottom > 1 ? "s" : ""} on the bottom of the library` : "Opening hand"}</h2>
      <p className="max-w-2xl text-center text-sm text-mute">{g.freeMulligan && g.mulligans === 1 && !bottom ? "Free mulligan: this is your new seven, and no card goes to the bottom. Keep it, or mulligan again (then one card goes to the bottom)." : bottom ? `Click the cards to put under the library (${pick.length} of ${g.toBottom} chosen).`
        : `Keep this hand, or take a mulligan: shuffle it back and draw seven, then put one card per mulligan on the bottom${g.freeMulligan ? " (the first one is free in Commander)" : ""}.`}</p>
      {/* one line, fanned in an arc with the cards over each other; the card under the pointer rises and grows */}
      <div className="flex w-full justify-center pb-16 pt-24" style={{ "--ow": "min(15rem, 13vw)" } as React.CSSProperties}>
        {g.hand.map((c, i) => {
          const out = pick.includes(c.uid), mid = (g.hand.length - 1) / 2, d = i - mid;
          return (
            <button key={c.uid} disabled={!bottom} onClick={() => toggle(c.uid)} aria-pressed={bottom ? out : undefined} aria-label={c.name}
              style={{ "--r": `${d * 5}deg`, "--y": `${d * d * 7}px`, marginLeft: i ? "calc(var(--ow) * -0.2)" : 0, zIndex: i } as React.CSSProperties}
              className={`relative w-(--ow) shrink-0 rounded-xl outline-none transition-transform duration-150 [transform:translateY(var(--y))_rotate(var(--r))] hover:z-20 hover:[transform:translateY(-2rem)_scale(1.3)] focus-visible:z-20 focus-visible:ring-2 focus-visible:ring-accent ${bottom ? "cursor-pointer" : "cursor-default"} ${out ? "opacity-40 ring-2 ring-accent" : ""}`}>
              {c.image_id ? <CardImg id={c.image_id} size="normal" /> : <div className="flex aspect-[63/88] items-center justify-center rounded-xl bg-raised p-2 text-center text-sm">{c.name}</div>}
              {out && <span className="absolute inset-x-0 top-1/2 -translate-y-1/2 bg-black/80 py-1 text-center text-xs font-semibold">Bottom #{pick.indexOf(c.uid) + 1}</span>}
            </button>
          );
        })}
      </div>
      <div className="flex justify-center gap-3">
        {bottom ? <button className={`${act} !px-8 !py-2.5 !text-base`} disabled={pick.length !== g.toBottom} onClick={() => set((x) => bottomMany(x, pick))}>Confirm</button> : <>
          <button className={`${act} !px-8 !py-2.5 !text-base`} onClick={() => set(keep)}>Keep {g.hand.length}</button>
          <button className={`${btn} !px-8 !py-2.5 !text-base`} disabled={g.mulligans - (g.freeMulligan ? 1 : 0) >= 7} title="Mulligan down to no cards at most" onClick={() => set((x) => mulligan(x))}>Mulligan{g.mulligans ? ` (${g.mulligans})` : ""}</button>
        </>}
      </div>
    </div>
  );
}

/** Solo playtest of a deck: draw, mulligan and play turns against nobody. */
export default function Playtest({ cards, commander }: { cards: DeckCard[]; commander: boolean }) {
  const mat = usePlaymat();
  const [onPlay, setOnPlay] = useState(true);
  const [g, setG] = useState<Game | null>(null);
  const [search, setSearch] = useState<string | null>(null);  // the library search box (null: closed)
  const [pile, setPile] = useState<"graveyard" | "exile" | null>(null);  // the pile whose cards are listed
  const menu = useContextMenu();
  const [hist, setHist] = useState<Game[]>([]);  // the states before each action, for Undo (the newest last, at most 50)
  const [zoom, setZoom] = useState<GCard | null>(null);  // the card under the pointer: shown larger, and the target of the card shortcuts
  const [zoomAt, setZoomAt] = useState<DOMRect | null>(null);  // where that card is, for the preview beside it
  const hover = (c: GCard | null, at?: DOMRect) => { setZoom(c); setZoomAt(at ?? null); };
  const [tokenForm, setTokenForm] = useState<{ name: string; pt: string } | null>(null);
  const [scryDrag, setScryDrag] = useState<number | null>(null);  // the index of the scry card being dragged
  const [scry, setScry] = useState<{ n: number; fate: Record<number, "top" | "bottom" | "graveyard">; order: number[] } | null>(null);  // what each looked-at card becomes (absent: stays on top)
  const gRef = useRef<Game | null>(null);
  const [counterForm, setCounterForm] = useState<{ uid: number; name: string; n: number } | null>(null);
  const [ending, setEnding] = useState(false);
  const [ignored, setIgnored] = useState<string[]>([]);  // the warnings the player dismissed in this game
  const [attaching, setAttaching] = useState<number | null>(null);  // the card waiting for the one to attach to
  const [details, setDetails] = useState<string | null>(null);  // the printing whose details (rules, rulings, legality...) are open
  const keyRef = useRef<(e: KeyboardEvent) => void>(() => undefined);
  gRef.current = g;
  const [box, setBox] = useState<Box>({ w: 0.08, h: 0.25 });  // a card's size as a fraction of the table, measured below
  const boxRef = useRef(box);
  boxRef.current = box;
  const surface = useRef<HTMLDivElement>(null);  // the free table
  const scroller = useRef<HTMLDivElement>(null);  // the window onto it: the table is bigger than it when zoomed in
  const [zoomT, setZoomT] = useState(() => { try { const v = Number(localStorage.getItem("scrybinder.tablezoom")); return ZOOMS.includes(v) ? v : 1; } catch { return 1; } });
  const anchor = useRef<{ fx: number; fy: number; px: number; py: number } | null>(null);  // the point of the table under the pointer, kept there while zooming
  const zoomTo = (z: number, at?: { px: number; py: number }) => {
    const s = scroller.current, t = surface.current;
    if (s && t && z !== zoomT) {
      const px = at?.px ?? s.clientWidth / 2, py = at?.py ?? s.clientHeight / 2;
      anchor.current = { fx: (s.scrollLeft + px) / t.offsetWidth, fy: (s.scrollTop + py) / t.offsetHeight, px, py };
    }
    setZoomT(z);
    try { localStorage.setItem("scrybinder.tablezoom", String(z)); } catch { /* no storage */ }
  };
  const zoomRef = useRef(zoomTo);
  zoomRef.current = zoomTo;
  const zoomStep = (dir: 1 | -1, at?: { px: number; py: number }) => { const i = ZOOMS.indexOf(zoomT); const n = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i + dir))]; zoomRef.current(n, at); };
  const stepRef = useRef(zoomStep);
  stepRef.current = zoomStep;
  useLayoutEffect(() => {  // after the table has its new size, put the anchored point back under the pointer
    const s = scroller.current, t = surface.current, a = anchor.current;
    if (s && t && a) { s.scrollLeft = a.fx * t.offsetWidth - a.px; s.scrollTop = a.fy * t.offsetHeight - a.py; }
    anchor.current = null;
  }, [zoomT]);
  useEffect(() => {  // Ctrl + wheel over the table zooms it (a native listener: React's wheel events cannot be cancelled)
    const s = scroller.current;
    if (!s) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = s.getBoundingClientRect();
      stepRef.current(e.deltaY < 0 ? 1 : -1, { px: e.clientX - r.left, py: e.clientY - r.top });
    };
    s.addEventListener("wheel", onWheel, { passive: false });
    return () => s.removeEventListener("wheel", onWheel);
  }, [g !== null]);  // eslint-disable-line react-hooks/exhaustive-deps
  const probe = useRef<HTMLSpanElement>(null);   // as wide as a card on it
  const started = g !== null;
  useEffect(() => {
    const el = surface.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect(), pw = probe.current?.offsetWidth ?? 0;
      if (r.width > 0 && r.height > 0 && pw > 0) setBox({ w: pw / r.width, h: (pw * 88) / 63 / r.height });
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, [started]);
  const start = () => { setHist([]); setAttaching(null); setIgnored([]); setZoom(null); setG(newGame(cards, commander, onPlay)); };
  useEffect(() => {
    const h = (e: KeyboardEvent) => keyRef.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const set = (f: (x: Game) => Game) => {  // every change remembers the state it replaced, for Undo
    const cur = gRef.current;
    if (!cur) return;
    const next = settle(f(cur), boxRef.current);  // cards that just reached the table get a spot
    if (next !== cur) {
      setHist((h) => pushHistory(h, cur)); setG(next);
      const at = (x: Game, uid: number) => ZONES.find((k) => x[k].some((c) => c.uid === uid));
      setZoom((z) => { const k = z && at(next, z.uid); return z && k && at(cur, z.uid) === k ? next[k].find((c) => c.uid === z.uid) ?? null : null; });  // a card that left its zone is no longer under the pointer
    }
  };
  const { drag, start: press } = usePointerDrag((uid, z, at: DropAt) => set((x) => {
    const from = ZONES.find((k) => x[k].some((c) => c.uid === uid));
    const card = from && x[from].find((c) => c.uid === uid);
    if (!card || (z === "command" && !card.commander) || (from === z && z !== "battlefield")) return x;
    const moved = from === z ? x : move(x, uid, z);
    if (z === "battlefield" && at.target !== null) { const on = attach(moved, uid, at.target); if (on !== moved) return on; }  // let go over a card: attached to it
    const r = surface.current?.getBoundingClientRect();
    // on the table the card lands where it was let go, holding the same point of it as when picked up
    return z === "battlefield" && r?.width && r.height ? placeCard(moved, uid, (at.x - r.left) / r.width - at.fx * boxRef.current.w, (at.y - r.top) / r.height - at.fy * boxRef.current.h, boxRef.current) : moved;
  }));
  const dragged = drag && g ? ZONES.flatMap((k) => g[k]).find((c) => c.uid === drag.uid) : undefined;
  useEffect(() => { if (drag) setZoom(null); }, [drag !== null]);  // eslint-disable-line react-hooks/exhaustive-deps

  const library = cards.filter((c) => c.board === "main").reduce((n, c) => n + c.quantity, 0);
  if (!g) return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-mute">Play alone against nobody: shuffle, draw a hand, mulligan and take turns to see how the deck behaves.</p>
      {library === 0 ? <p className="text-mute">Add cards to the main deck first.</p> : <>
        {commander ? <p className="text-sm text-mute">Commander: the first player draws on turn 1 too, so the game starts from your kept hand and you draw at the draw step.</p>
          : <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play (no draw on turn 1)</label>}
        <button className={btn} onClick={start}>Start playtest</button>
      </>}
      <Simulate cards={cards} commander={commander} />
    </div>
  );

  const endGame = () => {
    if (!ending) { setEnding(true); setTimeout(() => setEnding(false), 4000); return; }
    setG(null); setHist([]); setAttaching(null); setIgnored([]); setZoom(null); setScry(null); setTokenForm(null); setSearch(null); setPile(null); setEnding(false);
  };
  /** An element a card can be dropped on: outlined while a card is in flight, with a ring under the pointer. */
  const zone = (z: Zone): React.HTMLAttributes<HTMLElement> => ({
    ...{ "data-zone": z } as object,
    className: drag ? (drag.over === z ? "ring-2 ring-accent bg-accent/10" : "outline-dashed outline-1 outline-accent/50") : "",
  });
  const undo = () => { const last = hist[hist.length - 1]; if (last) { setG(last); setHist(hist.slice(0, -1)); setZoom(null); } };
  const playing = g.phase === "playing";
  const warns = warnings(g).filter((w) => !ignored.includes(w.key));
  const cardMenu = (c: GCard, zone: Zone) => (e: React.MouseEvent) => {
    if (!playing) return;  // the opening hand is only kept or sent back
    const to = (z: Zone, bottom = false): MenuItem => ({ label: z === "library" ? (bottom ? "Bottom of library" : "Top of library") : ZONE_LABEL[z], onSelect: () => set((x) => move(x, c.uid, z, bottom)) });
    menu.open(e, [
      ...(c.image_id ? [{ label: "View details & rulings", onSelect: () => setDetails(c.image_id) }, "sep" as const] : []),  // a token has no card to look up
      ...(zone === "battlefield" ? [
        { label: c.tapped ? "Untap" : "Tap", onSelect: () => set((x) => toggleTap(x, c.uid)) },
        { label: "Attach to…", onSelect: () => setAttaching(c.uid) },
        ...(c.attachedTo !== undefined ? [{ label: "Detach", onSelect: () => set((x) => detach(x, c.uid)) }] : []), "sep" as const,
        { label: "+1/+1 counter", onSelect: () => set((x) => addCounter(x, c.uid, "plus", 1)) },
        { label: "−1/−1 counter", onSelect: () => set((x) => addCounter(x, c.uid, "plus", -1)) },
        { label: "Add a counter…", onSelect: () => setCounterForm({ uid: c.uid, name: "", n: 1 }) },
        ...Object.keys(c.named ?? {}).flatMap((k) => [
          { label: `${k} +1`, onSelect: () => set((x) => addNamed(x, c.uid, k, 1)) },
          { label: `${k} −1`, onSelect: () => set((x) => addNamed(x, c.uid, k, -1)) }]),
        "sep" as const] : []),
      ...(["battlefield", "hand", "graveyard", "exile"] as const).filter((z) => z !== zone).map((z) => to(z)),
      ...(c.commander && zone !== "command" ? [to("command")] : []),  // a commander may return to the command zone instead
      "sep", to("library"), to("library", true),
    ]);
  };
  keyRef.current = (e) => {
    const cur = gRef.current;
    const t = e.target as HTMLElement;
    if (!cur || cur.phase !== "playing" || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || document.querySelector("[aria-modal]")) return;
    const k = e.key.toLowerCase();
    if (k === "escape" && attaching !== null) { setAttaching(null); return; }
    if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); undo(); return; }
    if (e.ctrlKey || e.metaKey) return;
    const where = zoom && ZONES.find((z) => cur[z].some((c) => c.uid === zoom.uid));
    const sendTo: Record<string, Zone> = { g: "graveyard", e: "exile", h: "hand", b: "battlefield" };
    if (k === "d") set((x) => draw(x));
    else if (k === "n") set(e.shiftKey ? nextTurn : nextPhase);
    else if (k === "u") set(untapAll);
    else if (k === "t" && zoom && where === "battlefield") set((x) => toggleTap(x, zoom.uid));
    else if (sendTo[k] && zoom && where && where !== sendTo[k]) set((x) => move(x, zoom.uid, sendTo[k]));
    else return;
    e.preventDefault();
  };
  const handClick = (c: GCard) => set((x) => (x.phase === "playing" ? move(x, c.uid, "battlefield") : x));
  const lands = g.battlefield.filter(isLand).length;

  return (
    <div className="flex min-h-[calc(100vh-10rem)] flex-col" style={CARD_W}>
      <div className="mb-2 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Playtest controls">
        <span className="mr-2 text-sm">Turn <b>{g.turn}</b> · Library <b>{g.library.length}</b> · Lands <b>{lands}</b></span>
        <span className="mr-2 flex items-center gap-1 text-sm">Life
          <button className={btn} aria-label="Lose 1 life" onClick={() => set((x) => ({ ...x, life: x.life - 1 }))}>−</button>
          <b className="w-8 text-center">{g.life}</b>
          <button className={btn} aria-label="Gain 1 life" onClick={() => set((x) => ({ ...x, life: x.life + 1 }))}>+</button>
        </span>
        <button className={btn} disabled={!hist.length} onClick={undo}>Undo</button>
        {!commander && <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play</label>}
        <button className={btn} onClick={start}>New game</button>
        <button className={btn} onClick={endGame}>{ending ? "Click again to end" : "End playtest"}</button>
      </div>
      {playing && <ol aria-label="Phases of the turn" className="mb-2 flex flex-wrap gap-1 text-xs">
        {TURN.map((t) => <li key={t.key} aria-current={t.step === g.step ? "step" : undefined} title={t.auto}
          className={`rounded-full border px-2.5 py-0.5 ${t.step === g.step ? "border-accent bg-accent/20 font-semibold" : t.auto ? "border-dashed border-mute/70 text-mute" : "border-line text-mute"}`}>{t.label}</li>)}
      </ol>}
      {warns.length > 0 && <ul aria-label="Rule warnings" className="mb-2 space-y-1">
        {warns.map((w) => <li key={w.key} className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-400/60 bg-amber-400/10 px-3 py-1 text-xs">
          <span aria-hidden>⚠</span><b>{w.rule}</b><span>{w.text}</span>
          <button className="ml-auto cursor-pointer rounded border border-line px-2 py-0.5 outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent" onClick={() => setIgnored((i) => [...i, w.key])}>Ignore</button></li>)}
      </ul>}
      {playing && <p className="mb-2 text-xs text-mute">Click a battlefield card to tap it, a hand card to play it, or press and drag a card onto a zone. Right-click any card for more.
        Keys: <kbd>D</kbd> draw · <kbd>N</kbd> next phase · <kbd>Shift+N</kbd> next turn · <kbd>U</kbd> untap all · <kbd>Ctrl+Z</kbd> undo · over a card: <kbd>T</kbd> tap · <kbd>G</kbd> graveyard · <kbd>E</kbd> exile · <kbd>H</kbd> hand · <kbd>B</kbd> battlefield.</p>}

      <div className="flex flex-1 items-stretch gap-4">
        {/* the table: nonlands nearest the opponent (top), lands nearest the player (bottom) */}
        <div className="flex min-w-0 flex-1 flex-col">
        <section aria-label="Battlefield" {...(playing ? zone("battlefield") : {})} style={{ aspectRatio: "24 / 14", width: "min(100%, calc((100vh - 14rem) * 24 / 14))" }} className={`relative isolate mx-auto flex min-h-0 shrink-0 flex-col rounded-xl border border-line ${playing ? zone("battlefield").className : ""}`}>
          <div className="flex items-start justify-between gap-2 px-2 pt-2">
          <h3 className="text-xs uppercase tracking-wide text-mute">Battlefield ({g.battlefield.length}) · place cards anywhere; the last one you move stays on top; drop one on another to attach it</h3>
            <div role="group" aria-label="Zoom the table" className="flex shrink-0 items-center gap-1 text-xs">
              <button className={`${btn} !px-2 !py-0.5`} onClick={() => zoomStep(-1)} disabled={zoomT === ZOOMS[0]} aria-label="Zoom out" title="Zoom out (Ctrl + wheel)">−</button>
              <button className={`${btn} !px-2 !py-0.5 tabular-nums`} onClick={() => zoomTo(1)} disabled={zoomT === 1} title="Back to 100%">{Math.round(zoomT * 100)}%</button>
              <button className={`${btn} !px-2 !py-0.5`} onClick={() => zoomStep(1)} disabled={zoomT === ZOOMS[ZOOMS.length - 1]} aria-label="Zoom in" title="Zoom in (Ctrl + wheel)">+</button>
            </div>
          </div>
          {attaching !== null && <p role="status" className="px-2 text-xs text-accent">Click the card to attach it to (Esc cancels).</p>}
          {/* a free table: each card sits at its own x, y; the dashed line is only a guide between the permanents and the lands */}
          {/* the window keeps its size; the table inside it grows with the zoom (cards, mat and all) and scrolls */}
          <div className="relative min-h-[calc(var(--cw)*3.6)] flex-1">
          <div ref={scroller} className={`absolute inset-0 ${zoomT === 1 ? "overflow-hidden" : "overflow-auto"}`}>  {/* at 100% nothing needs scrolling: a tapped card at the edge would flash a scroll bar */}
          <div ref={surface} role="group" aria-label="Table" className="relative isolate" style={{ "--cw": `calc(${CW} * ${zoomT})`, width: `${zoomT * 100}%`, height: `${zoomT * 100}%` } as React.CSSProperties}>
            <MatLayer mat={mat} />
            <span ref={probe} aria-hidden className="invisible absolute w-(--cw)" />
            <div className="pointer-events-none absolute inset-x-0 top-2/3 border-t border-dashed border-line" />
            {g.battlefield.map((c) => (c.x === undefined || c.y === undefined) && c.attachedTo === undefined ? null
              : <Card key={c.uid} c={c} at={{ ...placeOf(g, c, box), box }} lifted={drag?.uid === c.uid || (!!drag && c.attachedTo === drag.uid)} ring={drag ? drag.target === c.uid && drag.uid !== c.uid : attaching !== null && attaching !== c.uid} warn={warns.some((w) => w.uids.includes(c.uid))} badge={g.battlefield.filter((k) => k.attachedTo === c.uid).length} onHover={hover} onPress={playing ? press(c.uid) : undefined} onClick={() => (attaching !== null ? (set((x) => attach(x, attaching, c.uid)), setAttaching(null)) : set((x) => toggleTap(x, c.uid)))} onMenu={cardMenu(c, "battlefield")} />)}
          </div>
          </div>
          </div>
          <div className="pointer-events-none absolute inset-0 z-20 flex items-end justify-center overflow-hidden rounded-xl">  {/* clips the lower part of the hand at the table edge */}
          <section aria-label="Hand" style={{ "--sink": "25%" } as React.CSSProperties} {...(playing ? zone("hand") : {})} className={`pointer-events-auto relative rounded-xl p-1 ${g.hand.length ? "" : "border border-dashed border-line"} ${playing ? zone("hand").className : ""} ${warns.some((w) => w.rule === "514.1") ? "ring-2 ring-amber-400" : ""}`}>
            <div className="flex h-[calc(var(--hw)*88/63*0.45)] min-w-[calc(var(--hw)*1.3)] items-end justify-center">  {/* an empty hand keeps a box to drop a card on */}
              {g.hand.map((c, i) => <Card key={c.uid} c={c} fan={{ i, n: g.hand.length }} onHover={hover} onPress={playing ? press(c.uid) : undefined} onClick={() => handClick(c)} onMenu={cardMenu(c, "hand")} />)}
            </div>
          </section>
          </div>
        </section>
          {playing && <div role="toolbar" aria-label="Actions" className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-accent/40 bg-accent/15 p-2">
            <span className="mr-1 text-xs font-medium uppercase tracking-wide text-mute">Actions</span>
            <button className={act} onClick={() => set(nextPhase)}>Next phase</button>
            <button className={act} onClick={() => set(nextTurn)}>Next turn</button>
            <button className={act} disabled={!g.library.length} onClick={() => set((x) => draw(x))}>Draw</button>
            <button className={act} onClick={() => set(untapAll)}>Untap all</button>
            <button className={act} onClick={() => setSearch("")}>Search library</button>
            <button className={act} onClick={() => set((x) => shuffleLibrary(x))}>Shuffle</button>
            <button className={act} disabled={!g.library.length} onClick={() => setScry({ n: 1, fate: {}, order: [] })}>Scry / surveil</button>
            <button className={act} onClick={() => setTokenForm({ name: "", pt: "" })}>Token</button>
          </div>}
        </div>
        {/* library, graveyard, exile and the command zone: beside the table: the command zone on the left, library, graveyard and exile in a column on the right (one column without a commander) */}
        <aside aria-label="Zones" className={`grid shrink-0 content-start gap-2 ${commander ? "grid-cols-2" : "grid-cols-1"}`}>
          {commander && (
            <div {...(playing ? zone("command") : {})} className={`col-start-1 row-span-3 row-start-1 flex flex-col items-center gap-1 rounded-lg p-1 ${playing ? zone("command").className : ""}`} role="group" aria-label="Command zone">
              {g.command.map((c) => <div key={c.uid} className="w-[calc(var(--cw)*0.85)]"><Card c={c} onPress={playing ? press(c.uid) : undefined} onClick={playing ? () => set((x) => move(x, c.uid, "battlefield")) : undefined} onMenu={cardMenu(c, "command")} /></div>)}
              {!g.command.length && <div className="aspect-[63/88] w-[calc(var(--cw)*0.85)] rounded-[4.5%] border border-dashed border-line" />}
              <span className="text-xs text-mute">Command zone ({g.command.length})</span>
            </div>
          )}
          <Pile cls={commander ? "col-start-2" : ""} label="Library" cards={g.library} back zone={playing ? zone("library") : {}} onClick={playing && g.library.length ? () => set((x) => draw(x)) : undefined} />
          <Pile cls={commander ? "col-start-2" : ""} label="Graveyard" cards={g.graveyard} zone={playing ? zone("graveyard") : {}} onClick={g.graveyard.length ? () => setPile("graveyard") : undefined} />
          <Pile cls={commander ? "col-start-2" : ""} label="Exile" cards={g.exile} zone={playing ? zone("exile") : {}} onClick={g.exile.length ? () => setPile("exile") : undefined} />
        </aside>
      </div>


      {!playing && <OpeningHand key={g.phase} g={g} set={set} />}
      {drag && dragged && <div className="pointer-events-none fixed z-[60] w-(--cw) opacity-90 drop-shadow-2xl" aria-hidden
        style={{ "--cw": `calc(${CW} * ${zoomT})`, left: `calc(${drag.x}px - ${drag.fx} * var(--cw))`, top: `calc(${drag.y}px - ${drag.fy} * var(--cw) * 88 / 63)` } as React.CSSProperties}>  {/* the size of a card on the table, held by the point you grabbed: where it shows is where it lands */}
        {g!.battlefield.filter((k) => k.attachedTo === dragged.uid).map((k, i) => <div key={k.uid} className="absolute w-(--cw)" style={{ zIndex: -1, left: `calc(var(--cw) * ${-0.22 * Math.min(i + 1, 4)})`, top: `calc(var(--cw) * 88 / 63 * ${0.16 * Math.min(i + 1, 4)})` }}><Face c={k} w="w-(--cw)" /></div>)}  {/* what is attached to it travels with it */}
        <Face c={dragged} w="w-(--cw)" /></div>}
      {pile && (
        <Modal title={ZONE_LABEL[pile]} onClose={() => setPile(null)} wide>
          <h2 className="mb-1 text-lg font-semibold">{ZONE_LABEL[pile]} ({g[pile].length})</h2>
          <p className="mb-3 text-xs text-mute">Right-click a card to move it.</p>
          <div className="flex flex-wrap gap-2">
            {g[pile].map((c) => <Card key={c.uid} c={c} onMenu={cardMenu(c, pile)} />)}
          </div>
        </Modal>
      )}
      {zoom && zoomAt && !drag && (() => {  // beside a table card: to its right, or to its left when there is no room; above a hand card; kept inside the window
        const w = 288, h = w * 88 / 63, gap = 12;
        const inHand = g.hand.some((c) => c.uid === zoom.uid);
        if (inHand) return null;  // a hand card grows by itself
        const left = inHand ? Math.min(Math.max(8, zoomAt.left + zoomAt.width / 2 - w / 2), window.innerWidth - w - 8) : zoomAt.right + gap + w <= window.innerWidth - 8 ? zoomAt.right + gap : Math.max(8, zoomAt.left - gap - w);
        const top = inHand ? Math.max(8, zoomAt.top - h - gap) : Math.min(Math.max(8, zoomAt.top + zoomAt.height / 2 - h / 2), window.innerHeight - h - 8);
        return <div className="pointer-events-none fixed z-40 overflow-hidden rounded-[4.5%] shadow-2xl shadow-black/70 ring-1 ring-white/10" style={{ left, top, width: w }} aria-hidden>
          {zoom.image_id ? <CardImg id={zoom.image_id} size="large" /> : <div className="flex aspect-[63/88] items-center justify-center bg-raised p-4 text-center text-sm">{zoom.name}</div>}</div>;
      })()}
      {counterForm && (
        <Modal title="Add a counter" onClose={() => setCounterForm(null)}>
          <h2 className="mb-3 text-lg font-semibold">Add a counter</h2>
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (counterForm.name.trim()) set((x) => addNamed(x, counterForm.uid, counterForm.name, counterForm.n)); setCounterForm(null); }}>
            <label className="text-xs font-medium text-mute">Counter name
              <input autoFocus className="field mt-1 block w-48" maxLength={20} value={counterForm.name} onChange={(e) => setCounterForm({ ...counterForm, name: e.target.value })} placeholder="Charge, loyalty, time…" /></label>
            <label className="text-xs font-medium text-mute">How many
              <input type="number" min={1} max={99} className="field mt-1 block w-24" value={counterForm.n} onChange={(e) => setCounterForm({ ...counterForm, n: Math.max(1, Math.floor(+e.target.value) || 1) })} /></label>
            <button type="submit" className={btn} disabled={!counterForm.name.trim()}>Add counter</button>
          </form>
          <p className="mt-3 text-xs text-mute">Right-click the card to add or remove more of it later. It goes away when it reaches 0, or when the card leaves the table.</p>
        </Modal>
      )}
      {tokenForm && (
        <Modal title="Make a token" onClose={() => setTokenForm(null)}>
          <h2 className="mb-3 text-lg font-semibold">Make a token</h2>
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); set((x) => token(x, { name: tokenForm.name || "Token", pt: tokenForm.pt })); setTokenForm(null); }}>
            <label className="text-xs font-medium text-mute">Name
              <input autoFocus className="field mt-1 block w-48" value={tokenForm.name} onChange={(e) => setTokenForm({ ...tokenForm, name: e.target.value })} placeholder="Soldier" /></label>
            <label className="text-xs font-medium text-mute">Power/toughness
              <input className="field mt-1 block w-28" value={tokenForm.pt} onChange={(e) => setTokenForm({ ...tokenForm, pt: e.target.value })} placeholder="1/1" /></label>
            <button type="submit" className={btn}>Make token</button>
          </form>
          <p className="mt-3 text-xs text-mute">The token goes to the battlefield and disappears when it leaves it.</p>
        </Modal>
      )}
      {scry && (() => {
        const natural = peek(g, scry.n);
        const rank = (u: number) => { const i = scry.order.indexOf(u); return i < 0 ? 99 : i; };
        const top = scry.order.length ? [...natural].sort((a, b) => rank(a.uid) - rank(b.uid)) : natural;  // the order the player chose
        const shift = (i: number, d: number) => { const o = top.map((c) => c.uid); [o[i], o[i + d]] = [o[i + d], o[i]]; setScry({ ...scry, order: o }); };
        const dragTo = (from: number, to: number) => { if (from === to || from < 0) return; const o = top.map((c) => c.uid); o.splice(to, 0, o.splice(from, 1)[0]); setScry({ ...scry, order: o }); };
        const ids = (f: string) => top.filter((c) => (scry.fate[c.uid] ?? "top") === f).map((c) => c.uid);
        // the cards kept on top stay in this order, the ones for the bottom go under the library, the surveilled ones go to the graveyard
        const apply = () => { set((x) => ids("graveyard").reduce((y, u) => move(y, u, "graveyard"), reorderTop(x, ids("top"), ids("bottom")))); setScry(null); };
        const fates = [["top", "Top"], ["bottom", "Bottom"], ["graveyard", "Graveyard"]] as const;
        return (
          <Modal title="Scry or surveil" onClose={() => setScry(null)} wide>
            <h2 className="mb-1 text-lg font-semibold">Top of the library</h2>
            <p className="mb-3 text-xs text-mute">Scry: choose Top or Bottom for each card. Surveil: send cards to the Graveyard instead of the bottom. Drag the cards (or use the arrows) to reorder the ones you keep on top.</p>
            <label className="mb-3 flex items-center gap-2 text-sm">Look at
              <input type="number" min={1} max={10} className="field w-20" value={scry.n} onChange={(e) => setScry({ n: Math.min(10, Math.max(1, Math.floor(Number(e.target.value)) || 1)), fate: {}, order: [] })} aria-label="Cards to look at" /> cards</label>
            <div className="flex flex-wrap gap-4">
              {top.map((c, i) => {
                const fate = scry.fate[c.uid] ?? "top";
                return (
                  <div key={c.uid} data-scry={i} className="flex w-40 flex-col items-center gap-1">
                    <div className={`touch-none select-none cursor-grab active:cursor-grabbing ${scryDrag === i ? "opacity-50" : ""}`}  /* pointer events, not HTML5 drag: that does not start in the app window */
                      onPointerDown={(e) => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); setScryDrag(i); }}
                      onPointerUp={(e) => { const to = Number((document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-scry]") as HTMLElement | null)?.dataset.scry ?? -1); setScryDrag(null); if (to >= 0) dragTo(i, to); }}
                      onPointerCancel={() => setScryDrag(null)} onDragStart={(e) => e.preventDefault()}>
                      <Face c={c} w="w-36" />
                    </div>
                    <span className="flex items-center gap-2 text-xs text-mute">
                      <button className="cursor-pointer rounded border border-line px-1.5 hover:bg-raised disabled:cursor-default disabled:opacity-30" disabled={i === 0} onClick={() => shift(i, -1)} aria-label={`Move ${c.name} earlier`}>◀</button>
                      <button className="cursor-pointer rounded border border-line px-1.5 hover:bg-raised disabled:cursor-default disabled:opacity-30" disabled={i === top.length - 1} onClick={() => shift(i, 1)} aria-label={`Move ${c.name} later`}>▶</button>
                    </span>
                    <span className="text-xs text-mute">{i + 1}. {fate === "top" ? "stays on top" : fate === "bottom" ? "to the bottom" : "to the graveyard"}</span>
                    <div role="group" aria-label={`What happens to ${c.name}`} className="flex w-full overflow-hidden rounded-lg border border-line text-xs">
                      {fates.map(([f, label]) => (
                        <button key={f} aria-pressed={fate === f} onClick={() => setScry({ ...scry, fate: { ...scry.fate, [c.uid]: f } })}
                          className={`flex-1 cursor-pointer px-1 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-accent ${fate === f ? "bg-accent/30 font-semibold" : "hover:bg-raised"}`}>{label}</button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            <button className={`${btn} mt-4`} onClick={apply}>Done</button>
          </Modal>
        );
      })()}
      {search !== null && (
        <Modal title="Search library" onClose={() => setSearch(null)}>
          <h2 className="mb-2 text-lg font-semibold">Search library ({g.library.length})</h2>
          <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or type, e.g. island, plains" aria-label="Filter the library"
            className="mb-3 w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent" />
          <p className="mb-2 text-xs text-mute">The chosen card moves and the library is shuffled.</p>
          <ul className="max-h-[55vh] overflow-y-auto">
            {g.library.filter((c) => `${c.name} ${c.type_line ?? ""}`.toLowerCase().includes(search.toLowerCase()))
              .sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
              <li key={c.uid} className="flex items-center justify-between gap-2 border-b border-line py-1 text-sm">
                <span>{c.name} <span className="text-mute">· {c.type_line}</span></span>
                <span className="flex gap-1">
                  {(["battlefield", "hand"] as const).map((z) => (
                    <button key={z} className="cursor-pointer rounded border border-line px-2 py-0.5 hover:bg-raised"
                      onClick={() => { set((x) => shuffleLibrary(move(x, c.uid, z))); setSearch(null); }}>{ZONE_LABEL[z]}</button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </Modal>
      )}
      <Simulate cards={cards} commander={commander} />
      {details && <CardDetails printId={details} onClose={() => setDetails(null)} />}
      {menu.node}
    </div>
  );
}
