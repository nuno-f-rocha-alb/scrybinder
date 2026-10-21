import { useEffect, useState } from "react";
import { IconArrowLeft, IconCopy, IconPlus, IconShare, IconSearch, IconTrash, IconX } from "@tabler/icons-react";
import { api, CONDITIONS, eur, FINISH, LANGS, Print, qs, Collection } from "../api";
import { Combo, Select } from "../components/select";
import { Badge, CardImg, Field, HoverZoom, Modal, useToast } from "../components/ui";
import ShareDialog from "../components/sharedialog";

type Line = {
  id: number; scryfall_id: string; name: string; set_code: string; collector_number: string; finish: string; condition: string; language: string;
  location: string; quantity: number; untracked?: number; price: number | null; price_each: number | null; line_value: number; available?: number;
};
type Trade = {
  id: number; who: string; note: string; cash: number; traded_on: string | null; status: "draft" | "done"; created_at: string; done_at: string | null;
  out_cards: number; in_cards: number; out_value: number; in_value: number; net: number; out: Line[]; in: Line[];
};
type Hit = { oracle_id: string | null; name: string; prints: number; sample_id: string };
type Side = "out" | "in";

const day = (s: string | null) => (s ? s.slice(0, 10) : "");
const when = (t: Trade) => day(t.traded_on ?? t.done_at ?? t.created_at);
const signed = (v: number) => (v > 0 ? "+" : "") + eur(v);

/** Picks a card for one side of the trade: a collection row for what goes out, a printing for what comes in. */
const held = (r: Collection["rows"][number]) => r.decks.reduce((n, d) => n + d.quantity, 0);

function Picker({ side, onPick, onClose }: { side: Side; onPick: (body: object, extra: boolean) => Promise<void>; onClose: () => void }) {
  const [extra, setExtra] = useState(false);  // going out: a card you own that is not in the collection
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Collection["rows"]>([]);
  const [hits, setHits] = useState<Hit[]>([]);
  const [hit, setHit] = useState<Hit | null>(null);
  const [prints, setPrints] = useState<Print[]>([]);
  useEffect(() => {
    if (!q.trim()) { setRows([]); setHits([]); return; }
    let live = true;  // a slower earlier answer must not replace a newer one
    const t = setTimeout(() => {
      if (side === "out" && !extra) api<Collection>("/collection?" + qs({ q, group: "none", limit: 30 })).then((r) => live && setRows(r.rows)).catch(() => {});
      else api<Hit[]>("/cards/search?" + qs({ q, limit: 12 })).then((r) => live && setHits(r)).catch(() => {});
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, side, extra]);
  useEffect(() => {
    if (!hit) { setPrints([]); return; }
    api<Print[]>("/cards/prints?" + qs(hit.oracle_id ? { oracle_id: hit.oracle_id } : { name: hit.name })).then(setPrints).catch(() => {});
  }, [hit]);

  return (
    <Modal title={side === "out" ? "Add a card going out" : "Add a card coming in"} onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{side === "in" ? "Coming in: search any card" : extra ? "Going out: a card that is not in your collection" : "Going out: pick from your collection"}</h2>
        {side === "out" && <button className="btn-ghost !py-1" onClick={() => { setExtra(!extra); setQ(""); setHit(null); }}>{extra ? "Pick from my collection" : "Not in my collection…"}</button>}
      </div>
      {extra && <p className="mb-3 text-sm text-mute">For a card you own but never added to Scrybinder: it is listed and valued in the trade, and nothing is taken out of the collection when you confirm.</p>}
      <div className="relative mb-3">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
        <input autoFocus className="field pl-9" placeholder="Card name" aria-label="Card name" value={q} onChange={(e) => { setQ(e.target.value); setHit(null); }}
          onKeyDown={(e) => { if (e.key === "Enter" && side === "out" && !extra && rows[0] && !rows[0].proxy && held(rows[0]) < rows[0].quantity) onPick({ collection_id: rows[0].id, quantity: 1 }, false); }} />
      </div>
      {side === "out" && !extra && (
        <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
          {rows.map((r) => (
            <li key={r.id}><button onClick={() => onPick({ collection_id: r.id, quantity: 1 }, false)} disabled={!!r.proxy || held(r) >= r.quantity}
              title={r.proxy ? "A proxy is not a real copy" : held(r) >= r.quantity ? "Every copy is in a deck" : undefined}
              className="flex w-full cursor-pointer items-center gap-3 rounded-lg p-2 text-left hover:bg-raised disabled:cursor-not-allowed disabled:opacity-50">
              <div className="w-10 shrink-0"><CardImg id={r.scryfall_id} size="small" /></div>
              <span className="min-w-0 flex-1 truncate font-medium">{r.name} <span className="font-normal text-mute">{r.set_code.toUpperCase()} #{r.collector_number}</span></span>
              <Badge foil={r.finish !== "nonfoil"}>{FINISH[r.finish]}</Badge><span className="text-xs text-mute">{r.condition} · {r.location || "no location"}{r.decks.length ? ` · in ${r.decks.map((d) => d.name).join(", ")}` : ""}</span>
              <span className="w-10 text-right tabular-nums">×{r.quantity}</span>
            </button></li>
          ))}
          {q.trim() && !rows.length && <li className="p-2 text-mute">No cards of yours match.</li>}
        </ul>
      )}
      {(side === "in" || extra) && !hit && (
        <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.name}><button onClick={() => setHit(h)} className="flex w-full cursor-pointer items-center gap-3 rounded-lg p-2 text-left hover:bg-raised">
              <div className="w-10 shrink-0"><CardImg id={h.sample_id} size="small" /></div>
              <span className="flex-1 font-medium">{h.name}</span><span className="text-xs text-mute">{h.prints} printings</span>
            </button></li>
          ))}
        </ul>
      )}
      {(side === "in" || extra) && hit && (
        <div>
          <button className="btn-ghost mb-3" onClick={() => setHit(null)}><IconArrowLeft className="size-4" />Results</button>
          <div className="grid max-h-[55vh] grid-cols-[repeat(auto-fill,minmax(110px,1fr))] content-start gap-2 overflow-y-auto pr-1">
            {prints.map((p) => (
              <button key={p.id} onClick={() => onPick({ scryfall_id: p.id, quantity: 1, finish: (JSON.parse(p.finishes || "[]") as string[])[0] ?? "nonfoil" }, extra)}
                className="cursor-pointer rounded-lg p-1 text-left hover:bg-raised" title={`${p.set_name} #${p.collector_number}`}>
                <CardImg id={p.id} size="small" />
                <div className="mt-1 text-[11px]"><b>{p.set_code.toUpperCase()}</b> <span className="text-mute">#{p.collector_number} · {eur(p.eur)}</span></div>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-4"><button className="btn-ghost" onClick={onClose}>Done</button></div>
    </Modal>
  );
}

function LineRow({ side, line, editable, locs, onPatch, onRemove }: { side: Side; line: Line; editable: boolean; locs: string[]; onPatch: (b: object) => void; onRemove: () => void }) {
  const short = side === "out" && editable && !line.untracked && (line.available ?? 0) < line.quantity;
  const [price, setPrice] = useState(line.price == null ? "" : String(line.price));
  const [qty, setQty] = useState(String(line.quantity));
  const [loc, setLoc] = useState(line.location);
  useEffect(() => setPrice(line.price == null ? "" : String(line.price)), [line.price]);
  useEffect(() => setQty(String(line.quantity)), [line.quantity]);
  useEffect(() => setLoc(line.location), [line.location]);  // typed values are sent when the field is left, not on every key
  return (
    <li className="flex gap-3 rounded-xl border border-line bg-surface p-2.5">
      <HoverZoom className="w-16 shrink-0" zoom={<CardImg id={line.scryfall_id} size="large" />}><CardImg id={line.scryfall_id} size="small" /></HoverZoom>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0"><div className="truncate font-medium">{line.name}</div>
            <div className="text-xs text-mute">{line.set_code.toUpperCase()} #{line.collector_number} · {line.condition} · {LANGS[line.language] ?? line.language}
              {side === "out" && line.location ? ` · ${line.location}` : ""}</div></div>
          <div className="flex shrink-0 items-center gap-2">{line.untracked ? <Badge>Not in collection</Badge> : null}<Badge foil={line.finish !== "nonfoil"}>{FINISH[line.finish]}</Badge>
            {editable && <button className="cursor-pointer text-mute hover:text-danger" aria-label={`Remove ${line.name}`} onClick={onRemove}><IconX className="size-4" /></button>}</div>
        </div>
        {editable ? (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Qty"><input type="number" min={1} className="field !w-20 !py-1" value={qty}
              onChange={(e) => setQty(e.target.value)} onBlur={() => { const n = Math.max(1, Math.floor(+qty) || 1); setQty(String(n)); if (n !== line.quantity) onPatch({ quantity: n }); }} /></Field>
            <Field label="€ each (blank = market)"><input type="number" min={0} step="0.01" className="field !w-32 !py-1" value={price} placeholder={line.price_each == null ? "" : String(line.price_each)}
              onChange={(e) => setPrice(e.target.value)} onBlur={() => { if ((line.price == null ? "" : String(line.price)) !== price) onPatch({ price: price === "" ? null : +price }); }} /></Field>
            {(side === "in" || !!line.untracked) && <>
              <Field label="Finish"><Select className="field !py-1" value={line.finish} onChange={(e) => onPatch({ finish: e.target.value })}>
                {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              <Field label="Condition"><Select className="field !py-1" value={line.condition} onChange={(e) => onPatch({ condition: e.target.value })}>
                {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</Select></Field>
              {side === "in" && <Field label="Goes to"><Combo className="field !w-36 !py-1" suggestions={locs} value={loc} onChange={setLoc} onBlur={() => { if (loc !== line.location) onPatch({ location: loc }); }} placeholder="no location" /></Field>}
            </>}
          </div>
        ) : <div className="text-xs text-mute">×{line.quantity} · {eur(line.price_each)} each</div>}
        <div className="flex items-center justify-between text-xs"><span className={short ? "text-danger" : "text-mute"}>
          {short ? `only ${line.available} free to trade (the rest is in decks or gone)` : side === "out" && editable && !line.untracked ? `${line.available} free` : ""}</span>
          <span className="font-medium tabular-nums">{eur(line.line_value)}</span></div>
      </div>
    </li>
  );
}

function Detail({ id, onBack }: { id: number; onBack: () => void }) {
  const [t, setT] = useState<Trade | null>(null);
  const [adding, setAdding] = useState<Side | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [locs, setLocs] = useState<string[]>([]);
  const [meta, setMeta] = useState({ who: "", note: "", cash: "", date: "" });
  const { toast, node } = useToast();
  const load = () => api<Trade>(`/trades/${id}`).then((r) => { setT(r); setMeta({ who: r.who, note: r.note, cash: r.cash ? String(r.cash) : "", date: r.traded_on ?? "" }); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location).filter(Boolean))).catch(() => {}); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!t) return <p className="text-mute">Loading…</p>;
  const draft = t.status === "draft";
  const send = async (path: string, method: string, body?: object, ok?: string) => {
    try { await api(`/trades/${id}${path}`, { method, body: body && JSON.stringify(body) }); if (ok) toast(ok); await load(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const saveMeta = () => {
    if (meta.who !== t.who || meta.note !== t.note || +meta.cash !== t.cash || meta.date !== (t.traded_on ?? "")) send("", "PATCH", { who: meta.who, note: meta.note, cash: +meta.cash || 0, date: meta.date });
  };
  const evenOut = () => send("", "PATCH", { cash: Math.round((t.out_value - t.in_value) * 100) / 100 }, "Cash set so the trade evens out");
  const summary = () => {
    const l = (x: Line) => `${x.quantity}x ${x.name} (${x.set_code.toUpperCase()} #${x.collector_number}${x.finish !== "nonfoil" ? ", " + FINISH[x.finish].toLowerCase() : ""}) ${eur(x.line_value)}`;
    const text = [`Trade${t.who ? " with " + t.who : ""} ${when(t)}`, "", `I give (${eur(t.out_value)}):`, ...t.out.map(l), "", `I get (${eur(t.in_value)}):`, ...t.in.map(l),
      ...(t.cash ? ["", `Cash: ${signed(t.cash)}`] : [])].join("\n");
    navigator.clipboard.writeText(text).then(() => toast("Copied")).catch(() => toast("Could not copy", true));
  };
  const remove = async () => {
    if (!window.confirm(draft ? "Delete this draft? Your collection is not touched." : "Delete this entry from the history? Your collection stays as it is.")) return;
    try { await api(`/trades/${id}`, { method: "DELETE" }); onBack(); } catch (e) { toast((e as Error).message, true); }
  };
  const confirm = async () => {
    try { await api(`/trades/${id}/confirm`, { method: "POST" }); setConfirming(false); toast("Trade confirmed: the collection is updated"); await load(); }
    catch (e) { setConfirming(false); toast((e as Error).message, true); }
  };
  const column = (side: Side) => {
    const lines = side === "out" ? t.out : t.in;
    return (
      <section aria-label={side === "out" ? "Going out" : "Coming in"} className="min-w-0">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">{side === "out" ? "Going out" : "Coming in"} <span className="font-normal text-mute">· {side === "out" ? t.out_cards : t.in_cards} · {eur(side === "out" ? t.out_value : t.in_value)}</span></h2>
          {draft && <button className="btn-ghost !py-1" onClick={() => setAdding(side)}><IconPlus className="size-4" />Add card</button>}
        </div>
        <ul className="space-y-2">
          {lines.map((l) => <LineRow key={l.id} side={side} line={l} editable={draft} locs={locs}
            onPatch={(b) => send(`/${side}/${l.id}`, "PATCH", b)} onRemove={() => send(`/${side}/${l.id}`, "DELETE")} />)}
          {!lines.length && <li className="rounded-xl border border-dashed border-line p-4 text-sm text-mute">{side === "out" ? "Nothing leaving yet." : "Nothing coming in yet."}</li>}
        </ul>
      </section>
    );
  };

  return (
    <div>
      <button className="btn-ghost mb-3" onClick={onBack}><IconArrowLeft className="size-4" />Trades</button>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t.who || "Trade"}</h1>
        {draft ? <Badge>Pending: the collection is not changed yet</Badge> : <Badge>Done {when(t)}</Badge>}
      </div>
      <div className="mb-5 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_9rem_10rem]">
        <Field label="With (who / where)"><input className="field" value={meta.who} disabled={!draft} onChange={(e) => setMeta({ ...meta, who: e.target.value })} onBlur={saveMeta} /></Field>
        <Field label="Note"><input className="field" value={meta.note} onChange={(e) => setMeta({ ...meta, note: e.target.value })} onBlur={saveMeta} /></Field>
        <Field label="Date"><input type="date" className="field" value={meta.date} onChange={(e) => setMeta({ ...meta, date: e.target.value })} onBlur={saveMeta} /></Field>
        <Field label="Cash received (− if paid)"><input type="number" step="0.01" className="field" value={meta.cash} disabled={!draft} onChange={(e) => setMeta({ ...meta, cash: e.target.value })} onBlur={saveMeta} /></Field>
      </div>
      <div className="grid gap-6 min-[900px]:grid-cols-2">{column("out")}{column("in")}</div>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
        <div className="text-sm tabular-nums">
          Out {eur(t.out_value)} · In {eur(t.in_value)} · Cash {signed(t.cash)} · <b className={t.net < 0 ? "text-danger" : "text-ok"}>Net {signed(t.net)}</b>
          <span className="ml-1 text-mute">(market prices unless you set one)</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setSharing(true)} disabled={!t.out.length && !t.in.length} title="Make a link to this trade (without the person, the note or the cash)"><IconShare className="size-4" />Share</button>
          <button className="btn-ghost" onClick={summary} disabled={!t.out.length && !t.in.length}><IconCopy className="size-4" />Copy as text</button>
          {draft && <button className="btn-ghost" onClick={evenOut} disabled={!t.out.length && !t.in.length} title="Set the cash so that the net is zero">Even out with cash</button>}
          <button className="btn-danger" onClick={remove}><IconTrash className="size-4" />{draft ? "Delete draft" : "Delete from history"}</button>
          {draft && <button className="btn-primary" disabled={!t.out.length && !t.in.length} onClick={() => setConfirming(true)}>Confirm trade</button>}
        </div>
      </div>
      {sharing && <ShareDialog title="Trade" spec={{ kind: "trade", trade_id: id }} onClose={() => setSharing(false)} />}
      {adding && <Picker side={adding} onClose={() => setAdding(null)}
        onPick={async (b, extra) => { await send(extra ? "/extra" : `/${adding}`, "POST", b, "Added"); }} />}
      {confirming && (
        <Modal title="Confirm trade" onClose={() => setConfirming(false)}>
          <h2 className="mb-2 text-lg font-semibold">Confirm this trade?</h2>
          <p className="text-sm">{t.out_cards} {t.out_cards === 1 ? "copy leaves" : "copies leave"} your collection and {t.in_cards} {t.in_cards === 1 ? "copy is" : "copies are"} added. This cannot be undone from here.</p>
          <div className="mt-4 flex gap-2"><button className="btn-primary" onClick={confirm}>Confirm</button><button className="btn-ghost" onClick={() => setConfirming(false)}>Cancel</button></div>
        </Modal>
      )}
      {node}
    </div>
  );
}

export default function Trades() {
  const [list, setList] = useState<Trade[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const { toast, node } = useToast();
  useEffect(() => { if (open == null) api<Trade[]>("/trades").then(setList).catch((e) => toast(e.message, true)); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = (list ?? []).filter((t) => !f || `${t.who} ${t.note} ${when(t)}`.toLowerCase().includes(f));
  const done = (list ?? []).filter((t) => t.status === "done");
  const create = () => api<{ id: number }>("/trades", { method: "POST", body: JSON.stringify({}) }).then((r) => setOpen(r.id)).catch((e) => toast(e.message, true));
  if (open != null) return <Detail id={open} onBack={() => setOpen(null)} />;

  const section = (title: string, items: Trade[]) => items.length > 0 && (
    <section className="mb-6">
      <h2 className="mb-2 text-sm font-semibold text-mute">{title}</h2>
      <ul className="space-y-2">
        {items.map((t) => (
          <li key={t.id}><button onClick={() => setOpen(t.id)} className="flex w-full cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-line bg-surface p-3 text-left hover:bg-raised">
            <span className="min-w-0 flex-1 truncate font-medium">{t.who || "Trade"} <span className="font-normal text-mute">{when(t)}{t.note ? ` · ${t.note}` : ""}</span></span>
            <span className="text-sm tabular-nums text-mute">{t.out_cards} out · {t.in_cards} in{t.cash ? ` · cash ${signed(t.cash)}` : ""}</span>
            <span className={`w-24 text-right text-sm font-medium tabular-nums ${t.net < 0 ? "text-danger" : "text-ok"}`}>{signed(t.net)}</span>
          </button></li>
        ))}
      </ul>
    </section>
  );
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Trades</h1>
          <p className="mt-1 text-sm text-mute">In-person trades and sales. A pending trade changes nothing until you confirm it; then the cards going out leave your collection and the ones coming in are added.</p>
        </div>
        <button className="btn-primary" onClick={create}><IconPlus className="size-4" />New trade</button>
      </div>
      {!list && <p className="text-mute">Loading…</p>}
      {list && !list.length && <p className="text-mute">No trades yet.</p>}
      {list && list.length > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-4">
          <div className="relative w-full max-w-sm"><IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input className="field pl-9" placeholder="Filter by person, note or date" aria-label="Filter trades" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
          {done.length > 0 && <span className="text-sm text-mute">{done.length} done · out {eur(done.reduce((n, t) => n + t.out_value, 0))} · in {eur(done.reduce((n, t) => n + t.in_value, 0))} · cash {signed(done.reduce((n, t) => n + t.cash, 0))}</span>}
        </div>
      )}
      {list && <>{section("Pending", shown.filter((t) => t.status === "draft"))}{section("History", done.filter((t) => shown.includes(t)))}</>}
      {list && list.length > 0 && !shown.length && <p className="text-mute">No trade matches.</p>}
      {node}
    </div>
  );
}
