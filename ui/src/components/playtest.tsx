import { useState } from "react";
import { CardImg } from "./ui";
import type { DeckCard } from "../decks";
import { GCard, Game, Zone, bottomOne, draw, isLand, keep, move, mulligan, newGame, nextTurn, toggleTap } from "../goldfish";

const btn = "cursor-pointer rounded-lg border border-line px-3 py-1.5 text-sm outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default disabled:opacity-40";
const MOVES: [Zone, string][] = [["hand", "Hand"], ["battlefield", "Battlefield"], ["graveyard", "Graveyard"], ["exile", "Exile"]];

function Card({ c, zone, moves, onClick, onMove }: { c: GCard; zone: Zone; moves: boolean; onClick: () => void; onMove: (to: Zone, bottom?: boolean) => void }) {
  return (
    <div className="w-28 shrink-0">
      <button onClick={onClick} aria-label={`${c.name}${c.tapped ? " (tapped)" : ""}`} title={c.name}
        className={`block w-full cursor-pointer rounded-[4.5%] outline-none focus-visible:ring-2 focus-visible:ring-accent transition-transform ${c.tapped ? "rotate-12 opacity-70" : ""}`}>
        {c.image_id ? <CardImg id={c.image_id} size="small" /> : <div className="flex aspect-[63/88] items-center justify-center rounded bg-raised p-1 text-center text-xs">{c.name}</div>}
      </button>
      {moves && <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
        {MOVES.filter(([z]) => z !== zone).map(([z, l]) => <button key={z} className="cursor-pointer rounded border border-line px-1.5 hover:bg-raised" onClick={() => onMove(z)}>{l}</button>)}
        <button className="cursor-pointer rounded border border-line px-1.5 hover:bg-raised" onClick={() => onMove("library")}>Top</button>
        <button className="cursor-pointer rounded border border-line px-1.5 hover:bg-raised" onClick={() => onMove("library", true)}>Bottom</button>
      </div>}
    </div>
  );
}

/** Solo playtest of a deck: draw, mulligan and play turns against nobody. */
export default function Playtest({ cards, commander }: { cards: DeckCard[]; commander: boolean }) {
  const [onPlay, setOnPlay] = useState(true);
  const [g, setG] = useState<Game | null>(null);
  const start = () => setG(newGame(cards, commander, onPlay));

  const library = cards.filter((c) => c.board === "main").reduce((n, c) => n + c.quantity, 0);
  if (!g) return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-mute">Play alone against nobody: shuffle, draw a hand, mulligan and take turns to see how the deck behaves.</p>
      {library === 0 ? <p className="text-mute">Add cards to the main deck first.</p> : <>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play (no draw on turn 1)</label>
        <button className={btn} onClick={start}>Start playtest</button>
      </>}
    </div>
  );

  const set = (f: (x: Game) => Game) => setG((x) => (x ? f(x) : x));
  const handClick = (c: GCard) => set((x) => (x.phase === "bottom" ? bottomOne(x, c.uid) : x.phase === "playing" ? move(x, c.uid, "battlefield") : x));
  const row = (zone: Zone, label: string, click?: (c: GCard) => void) => (
    <section aria-label={label} className="mb-4">
      <h3 className="mb-1 text-sm font-medium text-mute">{label} ({g[zone].length})</h3>
      <div className="flex min-h-12 flex-wrap gap-2">
        {g[zone].map((c) => <Card key={c.uid} c={c} zone={zone} moves={g.phase === "playing"} onClick={() => click?.(c)} onMove={(to, bottom) => set((x) => move(x, c.uid, to, bottom))} />)}
      </div>
    </section>
  );
  const lands = g.battlefield.filter(isLand).length;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Playtest controls">
        <span className="mr-2 text-sm">Turn <b>{g.turn}</b> · Library <b>{g.library.length}</b> · Lands <b>{lands}</b></span>
        <span className="mr-2 flex items-center gap-1 text-sm">Life
          <button className={btn} aria-label="Lose 1 life" onClick={() => set((x) => ({ ...x, life: x.life - 1 }))}>−</button>
          <b className="w-8 text-center">{g.life}</b>
          <button className={btn} aria-label="Gain 1 life" onClick={() => set((x) => ({ ...x, life: x.life + 1 }))}>+</button>
        </span>
        {g.phase === "mulligan" && <>
          <button className={btn} onClick={() => set(keep)}>Keep</button>
          <button className={btn} onClick={() => set((x) => mulligan(x))}>Mulligan{g.mulligans ? ` (${g.mulligans})` : ""}</button>
        </>}
        {g.phase === "playing" && <>
          <button className={btn} onClick={() => set(nextTurn)}>Next turn</button>
          <button className={btn} disabled={!g.library.length} onClick={() => set((x) => draw(x))}>Draw</button>
        </>}
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play</label>
        <button className={btn} onClick={start}>New game</button>
      </div>
      {g.phase === "bottom" && <p className="mb-3 text-sm text-accent" role="status">Click {g.toBottom} card{g.toBottom > 1 ? "s" : ""} in your hand to put on the bottom of the library.</p>}
      {row("battlefield", "Battlefield (click to tap)", (c) => set((x) => toggleTap(x, c.uid)))}
      {row("hand", g.phase === "mulligan" ? "Opening hand" : "Hand (click to play)", handClick)}
      {commander && row("command", "Command zone", (c) => set((x) => (x.phase === "playing" ? move(x, c.uid, "battlefield") : x)))}
      {row("graveyard", "Graveyard")}
      {row("exile", "Exile")}
    </div>
  );
}
