import { useMemo, useState } from "react";
import { IconDownload } from "@tabler/icons-react";
import { img } from "../api";
import { Deck, DeckCard, groupCards } from "../decks";

// The deck as a poster: stacks of cards by type with only the title bars showing, the commander first and the sideboard apart
// (the "visual view" of MTGGoldfish). One layout draws both the page (an SVG, so it scales to the window) and the PNG.
const CW = 252, CH = 352, STRIP = 46, GAP = 16, PAD = 28, LABEL = 32, COLS = 6, MAXS = 8, HEAD = 124, FOOT = 44;
const W = PAD * 2 + COLS * CW + (COLS - 1) * GAP;
const BG = "#14161a", INK = "#e8eaed", MUTE = "#9aa0a6";

type Item = { c: DeckCard; x: number; y: number; k: string; vis: number };  // `vis`: the height of the card that shows
type Layout = { items: Item[]; labels: { x: number; y: number; text: string }[]; h: number };

/** Every copy is its own strip; a group longer than MAXS cards continues in the next stack. */
export function buildLayout(cards: DeckCard[]): Layout {
  const items: Item[] = [], labels: Layout["labels"] = [];
  let y = HEAD;
  const flow = (groups: ReturnType<typeof groupCards>) => {
    const stacks = groups.flatMap((g) => {
      const copies = g.cards.flatMap((c) => Array.from({ length: c.quantity }, (_, i) => ({ c, i })));
      return Array.from({ length: Math.ceil(copies.length / MAXS) }, (_, n) => ({ label: n === 0 ? `${g.label} ${g.count}` : "", copies: copies.slice(n * MAXS, (n + 1) * MAXS), key: g.key }));
    });
    for (let r = 0; r * COLS < stacks.length; r++) {
      const row = stacks.slice(r * COLS, (r + 1) * COLS);
      row.forEach((s, col) => {
        const x = PAD + col * (CW + GAP);
        if (s.label) labels.push({ x, y: y + 22, text: s.label });
        s.copies.forEach(({ c, i }, n) => items.push({ c, x, y: y + LABEL + n * STRIP, k: `${s.key}:${c.id}:${i}`, vis: n === s.copies.length - 1 ? CH : STRIP }));
      });
      y += LABEL + Math.max(...row.map((s) => (s.copies.length - 1) * STRIP)) + CH + GAP;
    }
  };
  const all = groupCards(cards, "type", "cmc");
  flow(all.filter((g) => g.key !== "side" && g.key !== "maybe"));
  flow(all.filter((g) => g.key === "side"));
  return { items, labels, h: y + FOOT };
}

const subtitle = (deck: Deck) => {
  const n = deck.cards.filter((c) => c.board !== "maybe").reduce((s, c) => s + c.quantity, 0);
  return `${deck.format[0].toUpperCase()}${deck.format.slice(1)} · ${n} cards`;
};

function load(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}

/** The PNG of the poster (1.5× the layout's size), as a data: URL. */
export async function posterPng(deck: Deck, layout: Layout): Promise<string> {
  const S = 1.5, cv = document.createElement("canvas");
  cv.width = Math.round(W * S); cv.height = Math.round(layout.h * S);
  const ctx = cv.getContext("2d")!;
  ctx.scale(S, S);
  ctx.fillStyle = BG; ctx.fillRect(0, 0, W, layout.h);
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = INK; ctx.font = "700 44px system-ui, sans-serif"; ctx.fillText(deck.name, PAD, 64, W - 2 * PAD);
  ctx.fillStyle = MUTE; ctx.font = "400 22px system-ui, sans-serif"; ctx.fillText(subtitle(deck), PAD, 100);
  ctx.font = "600 20px system-ui, sans-serif";
  ctx.fillStyle = INK;
  for (const l of layout.labels) ctx.fillText(l.text, l.x, l.y, CW);
  const ids = [...new Set(layout.items.map((i) => i.c.image_id).filter((x): x is string => !!x))];
  const pics = new Map(await Promise.all(ids.map(async (id) => [id, await load(img(id, "normal"))] as const)));
  for (const { c, x, y } of layout.items) {
    ctx.save();
    ctx.beginPath(); ctx.roundRect(x, y, CW, CH, 12); ctx.clip();
    const p = c.image_id ? pics.get(c.image_id) : null;
    if (p) ctx.drawImage(p, x, y, CW, CH);
    else { ctx.fillStyle = "#2a2d33"; ctx.fillRect(x, y, CW, CH); ctx.fillStyle = INK; ctx.font = "600 18px system-ui, sans-serif"; ctx.fillText(c.name, x + 10, y + 28, CW - 20); }
    ctx.restore();
    ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.roundRect(x, y, CW, CH, 12); ctx.stroke();
  }
  ctx.fillStyle = MUTE; ctx.font = "400 16px system-ui, sans-serif";
  ctx.fillText("Made with Scrybinder · Card images © Scryfall", PAD, layout.h - 16);
  return cv.toDataURL("image/png");
}

export async function savePoster(deck: Deck, layout: Layout, toast: (m: string, err?: boolean) => void) {
  try {
    const png = await posterPng(deck, layout);
    const name = `${deck.name.replace(/[^\w .-]+/g, "").trim() || "deck"}.png`;
    const bridge = (window as { pywebview?: { api?: { save_image?: (n: string, d: string) => Promise<string | null> } } }).pywebview?.api;
    if (bridge?.save_image) { const path = await bridge.save_image(name, png); if (path) toast(`Saved to ${path}`); return; }
    const a = document.createElement("a");  // in a normal browser
    a.href = png; a.download = name; a.click();
  } catch (e) { toast((e as Error).message, true); }
}

export default function DeckVisual({ deck, onOpen, onHover, toast }: { deck: Deck; onOpen: (c: DeckCard) => void; onHover: (c: DeckCard) => void; toast: (m: string, err?: boolean) => void }) {
  const layout = useMemo(() => buildLayout(deck.cards), [deck.cards]);
  const [hot, setHot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const card = ({ c, x, y, k }: Item) => (
    <g key={k} transform={`translate(${x} ${y})`} role="button" tabIndex={0} aria-label={c.name} className="cursor-pointer outline-none"
      onClick={() => onOpen(c)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(c); } }}
      onMouseEnter={() => { setHot(k); onHover(c); }} onMouseLeave={() => setHot(null)} onFocus={() => { setHot(k); onHover(c); }} onBlur={() => setHot(null)}>
      <g clipPath="url(#dv-round)">
        <rect width={CW} height={CH} fill="#2a2d33" />
        {c.image_id ? <image href={img(c.image_id, "normal")} width={CW} height={CH} /> : <text x={10} y={28} fill={INK} fontSize={18} fontWeight={600}>{c.name}</text>}
      </g>
      <rect width={CW} height={CH} rx={12} fill="none" stroke="rgba(0,0,0,.55)" strokeWidth={1.5} />
    </g>
  );
  const on = layout.items.find((i) => i.k === hot);
  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <p className="text-sm text-mute">Click a card to see it. The image is the whole deck, as shown here.</p>
        <button className="btn-ghost ml-auto" disabled={busy} onClick={async () => { setBusy(true); await savePoster(deck, layout, toast); setBusy(false); }}>
          <IconDownload className="size-4" />{busy ? "Making the image…" : "Download image"}
        </button>
      </div>
      <svg viewBox={`0 0 ${W} ${layout.h}`} className="mx-auto block h-auto w-full max-w-[1648px] rounded-xl" role="group" aria-label={`${deck.name}, the deck as a picture`}>
        <defs><clipPath id="dv-round"><rect width={CW} height={CH} rx={12} /></clipPath></defs>
        <rect width={W} height={layout.h} fill={BG} />
        <text x={PAD} y={64} fill={INK} fontSize={44} fontWeight={700}>{deck.name}</text>
        <text x={PAD} y={100} fill={MUTE} fontSize={22}>{subtitle(deck)}</text>
        {layout.labels.map((l) => <text key={`${l.x}:${l.y}`} x={l.x} y={l.y} fill={INK} fontSize={20} fontWeight={600}>{l.text}</text>)}
        {layout.items.map(card)}
        {on && <rect x={on.x} y={on.y} width={CW} height={on.vis} rx={12} fill="none" stroke="#a78bfa" strokeWidth={3} pointerEvents="none" />}
        <text x={PAD} y={layout.h - 16} fill={MUTE} fontSize={16}>Made with Scrybinder · Card images © Scryfall</text>
      </svg>
    </div>
  );
}
