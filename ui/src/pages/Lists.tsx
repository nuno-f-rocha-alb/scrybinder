import { useEffect, useState } from "react";
import { IconArrowLeft, IconCopy, IconDownload, IconPlus, IconSearch, IconShare, IconTrash, IconX } from "@tabler/icons-react";
import { api, CONDITIONS, Collection, eur, FINISH, Loc, Print, qs } from "../api";
import { Select } from "../components/select";
import { Badge, CardImg, Field, HoverZoom, Modal, useToast } from "../components/ui";
import ShareDialog from "../components/sharedialog";
import type { ListSummary } from "../components/addtolist";

type Item = {
  id: number; scryfall_id: string; name: string; set_code: string; collector_number: string; finish: string; condition: string; language: string;
  quantity: number; note: string; owned: number; price: number | null; line_value: number;
};
type ListT = ListSummary & { items: Item[] };
type Hit = { oracle_id: string | null; name: string; prints: number; sample_id: string };

const day = (s: string) => s.slice(0, 10);

/** Add cards to the list: from the collection (with the quantity you own) or any card (a card you do not own). */
function Picker({ onPick, onClose }: { onPick: (body: object) => Promise<void>; onClose: () => void }) {
  const [any, setAny] = useState(false);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Collection["rows"]>([]);
  const [hits, setHits] = useState<Hit[]>([]);
  const [hit, setHit] = useState<Hit | null>(null);
  const [prints, setPrints] = useState<Print[]>([]);
  useEffect(() => {
    if (!q.trim()) { setRows([]); setHits([]); return; }
    let live = true;  // a slower earlier answer must not replace a newer one
    const t = setTimeout(() => {
      if (!any) api<Collection>("/collection?" + qs({ q, group: "none", limit: 30 })).then((r) => live && setRows(r.rows)).catch(() => {});
      else api<Hit[]>("/cards/search?" + qs({ q, limit: 12 })).then((r) => live && setHits(r)).catch(() => {});
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, any]);
  useEffect(() => {
    if (!hit) { setPrints([]); return; }
    api<Print[]>("/cards/prints?" + qs(hit.oracle_id ? { oracle_id: hit.oracle_id } : { name: hit.name })).then(setPrints).catch(() => {});
  }, [hit]);

  return (
    <Modal title="Add cards to the list" onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{any ? "Any card (you may not own it)" : "From your collection"}</h2>
        <button className="btn-ghost !py-1" onClick={() => { setAny(!any); setQ(""); setHit(null); }}>{any ? "Pick from my collection" : "Any card…"}</button>
      </div>
      <div className="relative mb-3">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
        <input autoFocus className="field pl-9" placeholder="Card name" aria-label="Card name" value={q} onChange={(e) => { setQ(e.target.value); setHit(null); }}
          onKeyDown={(e) => { if (e.key === "Enter" && !any && rows[0]) onPick({ collection_ids: [rows[0].id] }); }} />
      </div>
      {!any && (
        <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
          {rows.map((r) => (
            <li key={r.id}><button onClick={() => onPick({ collection_ids: [r.id] })} disabled={!!r.proxy} title={r.proxy ? "A proxy is not a real copy" : undefined}
              className="flex w-full cursor-pointer items-center gap-3 rounded-lg p-2 text-left hover:bg-raised disabled:cursor-not-allowed disabled:opacity-50">
              <div className="w-10 shrink-0"><CardImg id={r.scryfall_id} size="small" /></div>
              <span className="min-w-0 flex-1 truncate font-medium">{r.name} <span className="font-normal text-mute">{r.set_code.toUpperCase()} #{r.collector_number}</span></span>
              <Badge foil={r.finish !== "nonfoil"}>{FINISH[r.finish]}</Badge><span className="text-xs text-mute">{r.condition} · {r.location || "no location"}</span>
              <span className="w-10 text-right tabular-nums">×{r.quantity}</span>
            </button></li>
          ))}
          {q.trim() && !rows.length && <li className="p-2 text-mute">No cards of yours match.</li>}
        </ul>
      )}
      {any && !hit && (
        <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.name}><button onClick={() => setHit(h)} className="flex w-full cursor-pointer items-center gap-3 rounded-lg p-2 text-left hover:bg-raised">
              <div className="w-10 shrink-0"><CardImg id={h.sample_id} size="small" /></div>
              <span className="flex-1 font-medium">{h.name}</span><span className="text-xs text-mute">{h.prints} printings</span>
            </button></li>
          ))}
        </ul>
      )}
      {any && hit && (
        <div>
          <button className="btn-ghost mb-3" onClick={() => setHit(null)}><IconArrowLeft className="size-4" />Results</button>
          <div className="grid max-h-[55vh] grid-cols-[repeat(auto-fill,minmax(110px,1fr))] content-start gap-2 overflow-y-auto pr-1">
            {prints.map((p) => (
              <button key={p.id} onClick={() => onPick({ items: [{ scryfall_id: p.id, quantity: 1, finish: (JSON.parse(p.finishes || "[]") as string[])[0] ?? "nonfoil" }] })}
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

function ItemRow({ it, onPatch, onRemove }: { it: Item; onPatch: (b: object) => void; onRemove: () => void }) {
  const [qty, setQty] = useState(String(it.quantity));
  useEffect(() => setQty(String(it.quantity)), [it.quantity]);
  return (
    <li className="flex gap-3 rounded-xl border border-line bg-surface p-2.5">
      <HoverZoom className="w-16 shrink-0" zoom={<CardImg id={it.scryfall_id} size="large" />}><CardImg id={it.scryfall_id} size="small" /></HoverZoom>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0"><div className="truncate font-medium">{it.name}</div><div className="text-xs text-mute">{it.set_code.toUpperCase()} #{it.collector_number}</div></div>
          <button className="cursor-pointer text-mute hover:text-danger" aria-label={`Remove ${it.name}`} onClick={onRemove}><IconX className="size-4" /></button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Qty"><input type="number" min={1} className="field !w-20 !py-1" value={qty} onChange={(e) => setQty(e.target.value)}
            onBlur={() => { const n = Math.max(1, Math.floor(+qty) || 1); setQty(String(n)); if (n !== it.quantity) onPatch({ quantity: n }); }} /></Field>
          <Field label="Finish"><Select className="field !py-1" value={it.finish} onChange={(e) => onPatch({ finish: e.target.value })}>
            {Object.entries(FINISH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
          <Field label="Condition"><Select className="field !py-1" value={it.condition} onChange={(e) => onPatch({ condition: e.target.value })}>
            {CONDITIONS.map((c) => <option key={c}>{c}</option>)}</Select></Field>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className={it.owned === 0 ? "text-mute" : it.quantity > it.owned ? "text-danger" : "text-gold"}>
            {it.owned === 0 ? "not in your collection" : it.quantity > it.owned ? `you own only ${it.owned}` : `you own ${it.owned}`}</span>
          <span className="font-medium tabular-nums">{eur(it.line_value)}</span>
        </div>
      </div>
    </li>
  );
}

function Detail({ id, onBack }: { id: number; onBack: () => void }) {
  const [l, setL] = useState<ListT | null>(null);
  const [adding, setAdding] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [meta, setMeta] = useState({ name: "", note: "" });
  const { toast, node } = useToast();
  const load = () => api<ListT>(`/lists/${id}`).then((r) => { setL(r); setMeta({ name: r.name, note: r.note }); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!l) return <p className="text-mute">Loading…</p>;
  const send = async (path: string, method: string, body?: object, ok?: string) => {
    try { await api(`/lists/${id}${path}`, { method, body: body && JSON.stringify(body) }); if (ok) toast(ok); await load(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const saveMeta = () => { if (!meta.name.trim()) { setMeta({ ...meta, name: l.name }); return; } if (meta.name !== l.name || meta.note !== l.note) send("", "PATCH", meta); };
  const copy = () => fetch(`/api/lists/${id}/export?format=text`).then((r) => r.text()).then((t) => navigator.clipboard.writeText(t)).then(() => toast("Copied")).catch(() => toast("Could not copy", true));
  // In the app window a native Save dialog (pywebview bridge); in a plain browser the normal download.
  const csv = async () => {
    const bridge = (window as { pywebview?: { api?: { save_csv?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    const url = `/api/lists/${id}/export?format=csv`;
    if (!bridge?.save_csv) { window.location.assign(url); return; }
    try { const r = await fetch(url); const p = await bridge.save_csv(`scrybinder-${l.name.replace(/[^\w.-]+/g, "_")}.csv`, await r.text()); if (p) toast(`Saved to ${p}`); } catch (e) { toast((e as Error).message, true); }
  };
  const remove = async () => {
    if (!window.confirm(`Delete the list "${l.name}"? Your collection is not touched.`)) return;
    try { await api(`/lists/${id}`, { method: "DELETE" }); onBack(); } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div>
      <button className="btn-ghost mb-3" onClick={onBack}><IconArrowLeft className="size-4" />Lists</button>
      <div className="mb-5 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Field label="Name"><input className="field text-lg font-semibold" value={meta.name} maxLength={100} onChange={(e) => setMeta({ ...meta, name: e.target.value })} onBlur={saveMeta} /></Field>
        <Field label="Note"><input className="field" value={meta.note} maxLength={1000} onChange={(e) => setMeta({ ...meta, note: e.target.value })} onBlur={saveMeta} placeholder="Shown to whoever opens a shared link" /></Field>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setAdding(true)}><IconPlus className="size-4" />Add cards</button>
        <button className="btn-ghost" onClick={() => setSharing(true)} disabled={!l.items.length}><IconShare className="size-4" />Share…</button>
        <button className="btn-ghost" onClick={copy} disabled={!l.items.length}><IconCopy className="size-4" />Copy as text</button>
        <button className="btn-ghost" onClick={csv} disabled={!l.items.length}><IconDownload className="size-4" />CSV</button>
        <span className="ml-2 text-sm text-mute tabular-nums">{l.cards} cards in {l.items.length} lines · about {eur(l.value)}</span>
        <button className="btn-danger ml-auto" onClick={remove}><IconTrash className="size-4" />Delete list</button>
      </div>
      {!l.items.length && <p className="rounded-xl border border-dashed border-line p-6 text-mute">No cards yet. Add some here, or right-click a card (or select several) in Cards or in a deck and choose "Add to a list…".</p>}
      <ul className="grid gap-2 min-[900px]:grid-cols-2 min-[1500px]:grid-cols-3">
        {l.items.map((it) => <ItemRow key={it.id} it={it} onPatch={(b) => send(`/items/${it.id}`, "PATCH", b)} onRemove={() => send(`/items/${it.id}`, "DELETE")} />)}
      </ul>
      {adding && <Picker onClose={() => setAdding(false)} onPick={async (b) => { await send("/items", "POST", b, "Added"); }} />}
      {sharing && <ShareDialog title={l.name} spec={{ kind: "list", list_id: id }} onClose={() => setSharing(false)} />}
      {node}
    </div>
  );
}

function FromLocation({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const [locs, setLocs] = useState<Loc[]>([]);
  const [loc, setLoc] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api<Loc[]>("/locations").then((l) => { setLocs(l); setLoc(l[0]?.location ?? null); }).catch((e) => setErr(e.message)); }, []);
  const go = () => api<{ id: number }>("/lists/from-location", { method: "POST", body: JSON.stringify({ location: loc, name }) }).then((r) => onDone(r.id)).catch((e) => setErr(e.message));
  return (
    <Modal title="New list from a location" onClose={onClose}>
      <h2 className="mb-1 text-lg font-semibold">New list from a location</h2>
      <p className="mb-3 text-sm text-mute">Copies the cards of a binder, a box or a deck into a new list that you can trim and share. Your collection is not changed.</p>
      <div className="space-y-3">
        <Field label="Location"><Select className="field" value={loc ?? ""} onChange={(e) => setLoc(e.target.value)}>
          {locs.map((l) => <option key={l.location} value={l.location}>{l.location || "(no location)"} ({l.cards})</option>)}</Select></Field>
        <Field label="Name of the list (optional)"><input className="field" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="Defaults to the location's name" /></Field>
      </div>
      {err && <p role="alert" className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-4 flex gap-2"><button className="btn-primary" disabled={loc === null} onClick={go}>Create list</button><button className="btn-ghost" onClick={onClose}>Cancel</button></div>
    </Modal>
  );
}

export default function Lists() {
  const [all, setAll] = useState<ListSummary[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [fromLoc, setFromLoc] = useState(false);
  const { toast, node } = useToast();
  useEffect(() => { if (open == null) api<ListSummary[]>("/lists").then(setAll).catch((e) => toast(e.message, true)); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const create = () => api<{ id: number }>("/lists", { method: "POST", body: JSON.stringify({ name }) }).then((r) => { setNaming(false); setName(""); setOpen(r.id); }).catch((e) => toast(e.message, true));
  if (open != null) return <Detail id={open} onBack={() => setOpen(null)} />;
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Lists</h1>
          <p className="mt-1 max-w-2xl text-sm text-mute">Sets of cards you pick to look at and to share: a trade binder, cards for sale, a wants list. A list is not a location: it does not move anything, a card can be in several lists, and it can hold cards you do not own.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setFromLoc(true)}>From a location…</button>
          <button className="btn-primary" onClick={() => setNaming(true)}><IconPlus className="size-4" />New list</button>
        </div>
      </div>
      {naming && (
        <form className="mb-5 flex max-w-xl flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create(); }}>
          <div className="min-w-48 flex-1"><Field label="Name"><input autoFocus className="field" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Trade binder" /></Field></div>
          <button type="submit" className="btn-primary" disabled={!name.trim()}>Create</button><button type="button" className="btn-ghost" onClick={() => setNaming(false)}>Cancel</button>
        </form>
      )}
      {!all && <p className="text-mute">Loading…</p>}
      {all && !all.length && <p className="text-mute">No lists yet.</p>}
      <ul className="space-y-2">
        {all?.map((l) => (
          <li key={l.id}><button onClick={() => setOpen(l.id)} className="flex w-full cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-line bg-surface p-3 text-left hover:bg-raised">
            <span className="min-w-0 flex-1 truncate font-medium">{l.name} <span className="font-normal text-mute">{l.note ? `· ${l.note}` : ""}</span></span>
            <span className="text-sm tabular-nums text-mute">{l.cards} cards · {l.lines} lines · {day(l.updated_at)}</span>
            <span className="w-24 text-right text-sm font-medium tabular-nums text-gold">{eur(l.value)}</span>
          </button></li>
        ))}
      </ul>
      {fromLoc && <FromLocation onClose={() => setFromLoc(false)} onDone={(id) => { setFromLoc(false); setOpen(id); }} />}
      {node}
    </div>
  );
}
