import { useState } from "react";
import { CardImg, Modal } from "./ui";
import { MenuItem, useContextMenu } from "./contextmenu";
import type { DeckCard } from "../decks";
import { GCard, Game, SimResult, Zone, bottomOne, draw, isLand, keep, move, mulligan, newGame, nextTurn, seeded, shuffleLibrary, simulate, toggleTap } from "../goldfish";

const btn = "cursor-pointer rounded-lg border border-line px-3 py-1.5 text-sm outline-none hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default disabled:opacity-40";
const ZONE_LABEL: Record<Zone, string> = { hand: "Hand", battlefield: "Battlefield", graveyard: "Graveyard", exile: "Exile", library: "Library", command: "Command zone" };

/** A land that is not also a creature goes in the land area; everything else in the nonland area (the tournament game layout). */
const landArea = (c: GCard) => isLand(c) && !/creature/i.test(c.type_line ?? "");

function Face({ c, w = "w-24" }: { c: GCard; w?: string }) {
  return c.image_id ? <div className={w}><CardImg id={c.image_id} size="small" /></div>
    : <div className={`${w} flex aspect-[63/88] items-center justify-center rounded bg-raised p-1 text-center text-xs`}>{c.name}</div>;
}

/** A card on the table: click acts, right-click lists the moves. A tapped card turns sideways in a square cell so its neighbours do not overlap. */
function Card({ c, onClick, onMenu, square }: { c: GCard; onClick?: () => void; onMenu: (e: React.MouseEvent) => void; square?: boolean }) {
  return (
    <button onClick={onClick} onContextMenu={onMenu} aria-label={`${c.name}${c.tapped ? " (tapped)" : ""}`} title={`${c.name} — right-click for more`}
      className={`flex shrink-0 cursor-pointer items-center justify-center rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent ${square ? "size-[8.6rem]" : ""}`}>
      <span className={`block transition-transform ${c.tapped ? "rotate-90" : ""}`}><Face c={c} /></span>
    </button>
  );
}

/** A pile to the side of the battlefield: the top card (or an empty slot), a name and a count. */
function Pile({ label, cards, onClick, back }: { label: string; cards: GCard[]; onClick?: () => void; back?: boolean }) {
  const top = cards[0];
  return (
    <button onClick={onClick} disabled={!onClick} aria-label={`${label}: ${cards.length} cards`}
      className="flex w-28 cursor-pointer flex-col items-center gap-1 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default">
      {back && cards.length ? <div className="aspect-[63/88] w-24 rounded-[4.5%] border border-line bg-gradient-to-br from-raised to-surface" />
        : !back && top ? <Face c={top} />
        : <div className="aspect-[63/88] w-24 rounded-[4.5%] border border-dashed border-line" />}
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

/** Solo playtest of a deck: draw, mulligan and play turns against nobody. */
export default function Playtest({ cards, commander }: { cards: DeckCard[]; commander: boolean }) {
  const [onPlay, setOnPlay] = useState(true);
  const [g, setG] = useState<Game | null>(null);
  const [search, setSearch] = useState<string | null>(null);  // the library search box (null: closed)
  const [pile, setPile] = useState<"graveyard" | "exile" | null>(null);  // the pile whose cards are listed
  const menu = useContextMenu();
  const start = () => setG(newGame(cards, commander, onPlay));

  const library = cards.filter((c) => c.board === "main").reduce((n, c) => n + c.quantity, 0);
  if (!g) return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-mute">Play alone against nobody: shuffle, draw a hand, mulligan and take turns to see how the deck behaves.</p>
      {library === 0 ? <p className="text-mute">Add cards to the main deck first.</p> : <>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play (no draw on turn 1)</label>
        <button className={btn} onClick={start}>Start playtest</button>
      </>}
      <Simulate cards={cards} commander={commander} />
    </div>
  );

  const set = (f: (x: Game) => Game) => setG((x) => (x ? f(x) : x));
  const playing = g.phase === "playing";
  const cardMenu = (c: GCard, zone: Zone) => (e: React.MouseEvent) => {
    if (!playing) return;  // the opening hand is only kept or sent back
    const to = (z: Zone, bottom = false): MenuItem => ({ label: z === "library" ? (bottom ? "Bottom of library" : "Top of library") : ZONE_LABEL[z], onSelect: () => set((x) => move(x, c.uid, z, bottom)) });
    menu.open(e, [
      ...(zone === "battlefield" ? [{ label: c.tapped ? "Untap" : "Tap", onSelect: () => set((x) => toggleTap(x, c.uid)) }, "sep" as const] : []),
      ...(["battlefield", "hand", "graveyard", "exile"] as const).filter((z) => z !== zone).map((z) => to(z)),
      ...(c.commander && zone !== "command" ? [to("command")] : []),  // a commander may return to the command zone instead
      "sep", to("library"), to("library", true),
    ]);
  };
  const handClick = (c: GCard) => set((x) => (x.phase === "bottom" ? bottomOne(x, c.uid) : x.phase === "playing" ? move(x, c.uid, "battlefield") : x));
  const lands = g.battlefield.filter(isLand).length;
  const area = (title: string, list: GCard[]) => (
    <div className="min-h-[9.5rem] p-2" role="group" aria-label={title}>
      <h3 className="mb-1 text-xs uppercase tracking-wide text-mute">{title} ({list.length})</h3>
      <div className="flex flex-wrap">{list.map((c) => <Card key={c.uid} c={c} square onClick={() => set((x) => toggleTap(x, c.uid))} onMenu={cardMenu(c, "battlefield")} />)}</div>
    </div>
  );

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
        {playing && <>
          <button className={btn} onClick={() => set(nextTurn)}>Next turn</button>
          <button className={btn} disabled={!g.library.length} onClick={() => set((x) => draw(x))}>Draw</button>
          <button className={btn} onClick={() => setSearch("")}>Search library</button>
          <button className={btn} onClick={() => set((x) => shuffleLibrary(x))}>Shuffle</button>
        </>}
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={onPlay} onChange={(e) => setOnPlay(e.target.checked)} />On the play</label>
        <button className={btn} onClick={start}>New game</button>
      </div>
      {g.phase === "bottom" && <p className="mb-3 text-sm text-accent" role="status">Click {g.toBottom} card{g.toBottom > 1 ? "s" : ""} in your hand to put on the bottom of the library.</p>}
      {playing && <p className="mb-2 text-xs text-mute">Click a battlefield card to tap it, a hand card to play it. Right-click any card for more.</p>}

      <div className="flex items-start gap-4">
        {/* the table: nonlands nearest the opponent (top), lands nearest the player (bottom) */}
        <section aria-label="Battlefield" className="min-w-0 flex-1 rounded-xl border border-line">
          {area("Nonland permanents", g.battlefield.filter((c) => !landArea(c)))}
          <div className="border-t border-dashed border-line" />
          {area("Lands", g.battlefield.filter(landArea))}
        </section>
        {/* library, graveyard and exile together on one side, with the command zone */}
        <aside aria-label="Zones" className="flex shrink-0 flex-col gap-3">
          <Pile label="Library" cards={g.library} back onClick={playing && g.library.length ? () => set((x) => draw(x)) : undefined} />
          <Pile label="Graveyard" cards={g.graveyard} onClick={g.graveyard.length ? () => setPile("graveyard") : undefined} />
          <Pile label="Exile" cards={g.exile} onClick={g.exile.length ? () => setPile("exile") : undefined} />
          {commander && (
            <div className="flex flex-col items-center gap-1" role="group" aria-label="Command zone">
              {g.command.map((c) => <Card key={c.uid} c={c} onClick={playing ? () => set((x) => move(x, c.uid, "battlefield")) : undefined} onMenu={cardMenu(c, "command")} />)}
              {!g.command.length && <div className="aspect-[63/88] w-24 rounded-[4.5%] border border-dashed border-line" />}
              <span className="text-xs text-mute">Command zone ({g.command.length})</span>
            </div>
          )}
        </aside>
      </div>

      <section aria-label="Hand" className="mt-4">
        <h3 className="mb-1 text-sm font-medium text-mute">{g.phase === "mulligan" ? "Opening hand" : "Hand"} ({g.hand.length})</h3>
        <div className="flex min-h-12 flex-wrap gap-1">
          {g.hand.map((c) => <Card key={c.uid} c={c} onClick={() => handClick(c)} onMenu={cardMenu(c, "hand")} />)}
        </div>
      </section>

      {pile && (
        <Modal title={ZONE_LABEL[pile]} onClose={() => setPile(null)} wide>
          <h2 className="mb-1 text-lg font-semibold">{ZONE_LABEL[pile]} ({g[pile].length})</h2>
          <p className="mb-3 text-xs text-mute">Right-click a card to move it.</p>
          <div className="flex flex-wrap gap-2">
            {g[pile].map((c) => <Card key={c.uid} c={c} onMenu={cardMenu(c, pile)} />)}
          </div>
        </Modal>
      )}
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
      {menu.node}
    </div>
  );
}
