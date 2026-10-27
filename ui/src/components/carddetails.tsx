import { useEffect, useState } from "react";
import { IconAlertTriangle, IconBan, IconCheck, IconChevronLeft, IconChevronRight, IconX } from "@tabler/icons-react";
import { api, eur, FINISH } from "../api";
import { CardImg, Modal, cardmarketUrl, openExternal, scryfallUrl } from "./ui";
import { ManaCost } from "./mana";

type Details = {
  id: string; oracle_id: string | null; name: string; set_code: string; set_name: string; collector_number: string; released_at: string; rarity: string;
  finishes: string[]; border_color: string; full_art: number; cardmarket_id: number | null; eur: number | null; eur_foil: number | null; eur_etched: number | null;
  cm_low: number | null; cm_avg: number | null; cm_trend: number | null; cm_low_foil: number | null; cm_avg_foil: number | null; cm_trend_foil: number | null;
  mana_cost: string | null; cmc: number | null; type_line: string | null; oracle_text: string | null; keywords: string[]; legalities: Record<string, string>;
  game_changer: boolean; edhrec_rank: number | null; owned: number;
};
type PrintRow = { id: string; set_code: string; set_name: string; collector_number: string; rarity: string; released_at: string; eur: number | null; eur_foil: number | null; owned: number };
type Ruling = { published_at: string; comment: string; source: string };

const FORMAT_ORDER = ["standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper", "brawl", "standardbrawl", "historic", "timeless", "alchemy",
  "competitivebrawl", "oathbreaker", "duel", "penny", "premodern", "oldschool", "predh", "paupercommander", "gladiator", "future"];
const FORMAT_NAME: Record<string, string> = { standardbrawl: "Standard Brawl", paupercommander: "Pauper EDH", oldschool: "Old School", predh: "PreDH", duel: "Duel Commander", competitivebrawl: "Competitive Brawl" };
const formatName = (f: string) => FORMAT_NAME[f] ?? f.charAt(0).toUpperCase() + f.slice(1);

/** Rules text with its {T}, {2}, {W} symbols drawn as mana symbols; faces ("A // B") are separated. */
function RulesText({ text }: { text: string }) {
  return (
    <div className="space-y-3 text-[15px] leading-relaxed">
      {text.split(" // ").map((face, i) => (
        <div key={i} className={i ? "border-t border-line pt-3" : ""}>
          {face.split("\n").map((line, j) => (
            <p key={j} className="mb-1.5">{line.split(/(\{[^}]+\})/).map((part, k) => (/^\{[^}]+\}$/.test(part) ? <ManaCost key={k} cost={part} /> : part))}</p>
          ))}
        </div>
      ))}
    </div>
  );
}

const LEGAL = {
  legal: { Icon: IconCheck, cls: "text-ok", label: "Legal" },
  not_legal: { Icon: IconBan, cls: "text-mute", label: "Not legal" },
  banned: { Icon: IconX, cls: "text-danger", label: "Banned" },
  restricted: { Icon: IconAlertTriangle, cls: "text-gold", label: "Restricted" },
} as const;

/** Cardmarket's three prices of the printing (low, average, trend), per finish; nothing until the prices are turned on in Settings. */
function CardmarketPrices({ d }: { d: Details }) {
  const rows = [["Non-foil", d.cm_low, d.cm_avg, d.cm_trend], ["Foil", d.cm_low_foil, d.cm_avg_foil, d.cm_trend_foil]] as const;
  const shown = rows.filter((r) => r[1] != null || r[2] != null || r[3] != null);
  if (!shown.length) return null;
  return (
    <div className="mt-2 text-xs" aria-label="Cardmarket prices">
      <div className="text-mute">Cardmarket</div>
      {shown.map(([label, low, avg, trend]) => (
        <div key={label} className="mt-0.5 flex flex-wrap gap-x-3 tabular-nums"><span className="w-16 text-mute">{label}</span><span>Low {eur(low)}</span><span>Avg {eur(avg)}</span><span>Trend {eur(trend)}</span></div>
      ))}
    </div>
  );
}

/** The text side of a card: rules, printing (with the list of all printings), legality and rulings. `onPick` makes the printings clickable. */
export function CardInfo({ d, id, onPick }: { d: Details; id: string; onPick?: (id: string) => void }) {
  const [rulings, setRulings] = useState<Ruling[] | null | "error">(null);
  const [prints, setPrints] = useState<PrintRow[] | null>(null);
  const [showPrints, setShowPrints] = useState(false);
  useEffect(() => {
    let live = true;
    setRulings(null);
    api<Ruling[]>(`/cards/${id}/rulings`).then((r) => live && setRulings(r)).catch(() => live && setRulings("error"));
    return () => { live = false; };
  }, [id]);
  useEffect(() => {
    if (!showPrints || !d.oracle_id) return;
    api<PrintRow[]>(`/cards/prints?oracle_id=${encodeURIComponent(d.oracle_id)}`).then(setPrints).catch(() => setPrints([]));
  }, [showPrints, d.oracle_id]);
  const formats = FORMAT_ORDER.filter((f) => f in d.legalities);  // the formats we have a name for, in a fixed order
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-semibold tracking-tight text-accent">{d.name}</h2><ManaCost cost={d.mana_cost} />
        {d.game_changer && <span className="rounded-md bg-gold/15 px-2 py-0.5 text-xs text-gold">Game changer</span>}
      </div>
      <p className="mt-0.5 text-sm text-mute">{d.type_line}</p>
      {d.oracle_text && <div className="mt-4"><RulesText text={d.oracle_text} /></div>}
      {d.keywords.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{d.keywords.map((k) => <span key={k} className="rounded-md bg-raised px-2 py-0.5 text-xs text-mute">{k}</span>)}</div>}

      <section className="mt-5 rounded-xl border border-line p-3 text-sm" aria-label="Printing">
        <div className="font-medium">{d.set_name} <span className="font-normal text-mute">({d.set_code.toUpperCase()})</span></div>
        <div className="text-mute">#{d.collector_number} · <span className="capitalize">{d.rarity}</span> · {d.released_at?.slice(0, 4)}{d.border_color === "borderless" ? " · borderless" : ""}</div>
        <div className="mt-1 text-xs text-mute">Comes in: {d.finishes.map((f) => FINISH[f] ?? f).join(", ") || "—"}</div>
        <CardmarketPrices d={d} />
        {d.oracle_id && <button className="mt-2 cursor-pointer text-accent hover:underline" aria-expanded={showPrints} onClick={() => setShowPrints((v) => !v)}>
          {showPrints ? "Hide all printings" : "Show all printings"}</button>}
        {showPrints && (
          <ul className="mt-2 max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {!prints && <li className="p-2 text-mute">Loading…</li>}
            {prints?.map((p) => (
              <li key={p.id}><button className={`flex w-full cursor-pointer items-center justify-between gap-3 px-2 py-1.5 text-left hover:bg-raised ${p.id === id ? "bg-accent-soft" : ""}`} onClick={() => onPick?.(p.id)}>
                <span className="min-w-0 truncate"><b className="uppercase">{p.set_code}</b> #{p.collector_number} <span className="text-mute">{p.set_name} · {p.released_at?.slice(0, 4)}</span></span>
                <span className="shrink-0 text-xs text-mute tabular-nums">{p.owned > 0 && <span className="mr-2 text-gold">own {p.owned}</span>}{eur(p.eur)}</span>
              </button></li>
            ))}
          </ul>
        )}
      </section>

      {formats.length > 0 && (
        <section className="mt-5" aria-label="Legalities">
          <h3 className="mb-2 text-sm font-semibold">Legality</h3>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
            {formats.map((f) => {
              const L = LEGAL[d.legalities[f] as keyof typeof LEGAL] ?? LEGAL.not_legal;
              return <li key={f} className="flex items-center gap-1.5"><L.Icon className={`size-4 shrink-0 ${L.cls}`} aria-hidden /><span className={d.legalities[f] === "legal" ? "" : "text-mute"}>{formatName(f)}</span><span className="sr-only">: {L.label}</span></li>;
            })}
          </ul>
        </section>
      )}

      <section className="mt-6" aria-label="Rulings">
        <h3 className="mb-2 text-lg font-semibold">Rulings</h3>
        {rulings === null && <p className="text-sm text-mute">Loading…</p>}
        {rulings === "error" && <p className="text-sm text-mute">The rulings could not be loaded: they come from Scryfall and need a connection (the first time).</p>}
        {Array.isArray(rulings) && rulings.length === 0 && <p className="text-sm text-mute">No rulings for this card.</p>}
        {Array.isArray(rulings) && rulings.map((r, i) => (
          <div key={i} className="mb-3"><div className="text-sm text-mute tabular-nums">{r.published_at}</div><p className="text-[15px] leading-relaxed">{r.comment}</p></div>
        ))}
      </section>
    </div>
  );
}

/** The card info for a printing, loaded here: for places that already show the image (the collection's edit drawer). */
export function CardInfoLoader({ printId }: { printId: string }) {
  const [d, setD] = useState<Details | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setD(null); setErr("");
    api<Details>(`/cards/${printId}/details`).then((r) => live && setD(r)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [printId]);
  if (err) return <p className="text-sm text-danger">{err}</p>;
  return d ? <CardInfo d={d} id={printId} /> : <p className="text-sm text-mute">Loading...</p>;
}

/** Everything about a card in one place: the image, prices, links, rules text, printing, all printings, legalities and rulings. `printId` is the
 * printing shown; `prev` / `next` (when given) step through the list it came from, also with the arrow keys. */
export default function CardDetails({ printId, onClose, prev, next }: { printId: string; onClose: () => void; prev?: () => void; next?: () => void }) {
  const [id, setId] = useState(printId);
  const [d, setD] = useState<Details | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => { setId(printId); }, [printId]);
  useEffect(() => {
    let live = true;
    setD(null); setErr("");
    api<Details>(`/cards/${id}/details`).then((r) => live && setD(r)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [id]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement).tagName)) return;
      if (e.key === "ArrowLeft" && prev) { e.preventDefault(); prev(); }
      if (e.key === "ArrowRight" && next) { e.preventDefault(); next(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [prev, next]);

  return (
    <Modal title={d ? `Details of ${d.name}` : "Card details"} onClose={onClose} wide>
      <div className="mb-4 flex items-center justify-end gap-2">
        {prev && <button className="btn-ghost" onClick={prev} aria-label="Previous card"><IconChevronLeft className="size-4" />Prev</button>}
        {next && <button className="btn-ghost" onClick={next} aria-label="Next card">Next<IconChevronRight className="size-4" /></button>}
        <button className="btn-primary" onClick={onClose}><IconX className="size-4" />Close</button>
      </div>
      {err && <p className="text-danger">{err}</p>}
      {!d && !err && <p className="text-mute">Loading…</p>}
      {d && (
        <div className="grid gap-6 md:grid-cols-[300px_minmax(0,1fr)]">
          <div>
            <CardImg key={id} id={id} size="large" className="shadow-[0_10px_28px_rgba(0,0,0,0.6)]" />
            <div className="mt-3 space-y-1 text-sm tabular-nums">
              <div className="flex justify-between"><span className="text-mute">Non-foil</span><span>{eur(d.eur)}</span></div>
              {d.finishes.includes("foil") && <div className="flex justify-between"><span className="text-mute">Foil</span><span>{eur(d.eur_foil)}</span></div>}
              {d.finishes.includes("etched") && <div className="flex justify-between"><span className="text-mute">Etched</span><span>{eur(d.eur_etched)}</span></div>}
              <div className="pt-1 text-xs text-mute">Prices from Cardmarket, in euros</div>
              {d.owned > 0 && <div className="pt-1 text-gold">You own {d.owned} of this printing</div>}
            </div>
            <div className="mt-3 flex flex-col gap-2">
              {d.cardmarket_id && <button className="btn-ghost justify-center" onClick={() => openExternal(cardmarketUrl(d.cardmarket_id!))}>Buy on Cardmarket ↗</button>}
              <button className="btn-ghost justify-center" onClick={() => openExternal(scryfallUrl(d.id))}>Open on Scryfall ↗</button>
            </div>
          </div>

          <CardInfo d={d} id={id} onPick={setId} />
        </div>
      )}
    </Modal>
  );
}
