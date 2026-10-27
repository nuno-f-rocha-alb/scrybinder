import { useEffect, useState } from "react";
import { IconCopy, IconExternalLink, IconRefresh, IconTrash } from "@tabler/icons-react";
import { api } from "../api";
import { Field, Modal, openExternal, useToast } from "./ui";
import { DeckInclude, INCLUDE_ALL } from "./deckinclude";

type Summary = { configured: boolean; kind: string; title: string; lines: number; cards: number; bytes: number; existing: { id: string; url: string; expires_at: string | null } | null };
type Made = { id: string; url: string; expires: string | null; lines: number; cards: number };
export type Shared = { id: string; kind: string; title: string; url: string; created_at: string; expires_at: string | null; can_update: boolean };

const day = (s: string | null) => (s ? s.slice(0, 10) : "");
const copy = (text: string, toast: (m: string, e?: boolean) => void) => navigator.clipboard.writeText(text).then(() => toast("Link copied")).catch(() => toast("Could not copy", true));

/** Makes a share link for `spec` (what to share: {kind, deck_id | trade_id | list_id | ids | filters}). Nothing leaves the computer until "Create link". */
export default function ShareDialog({ spec, title, collection, onClose }: { spec: Record<string, unknown>; title: string; collection?: boolean; onClose: () => void }) {
  const [name, setName] = useState(title);
  const [note, setNote] = useState("");
  const [prices, setPrices] = useState(false);
  const [locations, setLocations] = useState(false);
  const [cash, setCash] = useState(false);
  const [pre, setPre] = useState<Summary | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<Made | null>(null);
  const [links, setLinks] = useState(false);
  const { toast, node } = useToast();
  const [include, setInclude] = useState(INCLUDE_ALL);
  const [chosen, setChosen] = useState(false);  // an update keeps the saved choice unless it is changed here
  const deck = spec.kind === "deck";
  const what = deck ? { ...spec, include } : spec;  // a deck can leave out cards by where they are
  const body = { ...what, title: name, note, prices, locations, cash };

  useEffect(() => {
    if (deck && !include.length) { setPre(null); setErr(""); return; }
    let live = true;  // an older answer must not replace a newer one
    api<Summary>("/share/preview", { method: "POST", body: JSON.stringify({ ...what, prices, locations, cash }) }).then((r) => { if (live) { setPre(r); setErr(""); } })
      .catch((e) => { if (live) { setPre(null); setErr(e.message); } });
    return () => { live = false; };
  }, [JSON.stringify(what), prices, locations, cash]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setBusy(true);
    try { setMade(await api<Made>("/share", { method: "POST", body: JSON.stringify(body) })); setErr(""); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const update = async (id: string) => {  // the same link, with the cards as they are now and the options chosen here
    setBusy(true);
    try { setMade(await api<Made>(`/shares/${id}`, { method: "PUT", body: JSON.stringify({ title: name, note, prices, locations, cash, ...(deck && chosen ? { include } : {}) }) })); setErr(""); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const old = pre?.existing;

  if (links) return <SharedLinks onClose={() => setLinks(false)} />;
  return (
    <Modal title="Share" onClose={onClose}>
      <h2 className="mb-1 text-lg font-semibold">Share a link</h2>
      <p className="mb-4 text-sm text-mute">A copy of the list is kept on the Scrybinder share service for 30 days. Anyone with the link can see it. Notes, locations, purchase prices{spec.kind === "trade" ? " and the other person" : ""} are never sent{collection ? " (locations only if you tick the box)" : ""}.</p>
      {!made && <div className="space-y-3">
        <Field label="Title"><input className="field" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Message for the viewer (optional)"><textarea className="field" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {deck && <DeckInclude value={include} onChange={(v) => { setInclude(v); setChosen(true); }} />}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={prices} onChange={(e) => setPrices(e.target.checked)} />Include Cardmarket prices</label>
        {spec.kind === "trade" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cash} onChange={(e) => setCash(e.target.checked)} />Include the cash (what was paid or received)</label>}
        {collection && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={locations} onChange={(e) => setLocations(e.target.checked)} />Include where each card is (its location)</label>}
        <p className="text-sm text-mute" aria-live="polite">{pre ? `${pre.cards} cards in ${pre.lines} lines (${Math.max(1, Math.round(pre.bytes / 1024))} KB) will be sent.` : err ? "" : "Checking…"}</p>
        {pre && !pre.configured && <p role="alert" className="text-sm text-gold">Sharing is not set up in this build: the share service has not been deployed yet (see share/README.md).</p>}
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
        {old && <p className="rounded-xl border border-dashed border-accent/50 p-3 text-sm">You already shared this (<span className="break-all text-mute">{old.url}</span>). <b>Update link</b> puts what you have now under the same address and gives it 30 more days; <b>Create a new link</b> makes a second one.</p>}
        <div className="flex flex-wrap gap-2">
          {old && <button className="btn-primary" disabled={!pre?.configured || busy} onClick={() => update(old.id)}>{busy ? "Updating…" : "Update link"}</button>}
          <button className={old ? "btn-ghost" : "btn-primary"} disabled={!pre || !pre.configured || busy} onClick={create}>{busy ? "Creating…" : old ? "Create a new link" : "Create link"}</button>
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-ghost ml-auto" onClick={() => setLinks(true)}>Your shared links</button>
        </div>
      </div>}
      {made && <div className="space-y-3">
        <input className="field" readOnly value={made.url} aria-label="Share link" onFocus={(e) => e.currentTarget.select()} />
        <p className="text-sm text-mute">{made.cards} cards. The link works until {day(made.expires)}. You can update it later (same address) or delete it from "Your shared links".</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" onClick={() => copy(made.url, toast)}><IconCopy className="size-4" />Copy link</button>
          <button className="btn-ghost" onClick={() => openExternal(made.url)}><IconExternalLink className="size-4" />Open</button>
          <button className="btn-ghost" onClick={onClose}>Done</button>
        </div>
      </div>}
      {node}
    </Modal>
  );
}

/** The links made from this computer, with Copy, Open and Delete (which also removes the copy from the share service). */
export function SharedLinks({ onClose }: { onClose?: () => void }) {
  const [list, setList] = useState<Shared[] | null>(null);
  const [busy, setBusy] = useState("");
  const { toast, node } = useToast();
  const load = () => api<Shared[]>("/shares").then(setList).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const remove = async (s: Shared) => {
    if (!window.confirm(`Delete the link "${s.title}"? Anyone who has it will no longer be able to open it.`)) return;
    setBusy(s.id);
    try { await api(`/shares/${s.id}`, { method: "DELETE" }); toast("Link deleted"); await load(); } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const update = async (s: Shared) => {
    setBusy(s.id);
    try { await api(`/shares/${s.id}`, { method: "PUT", body: JSON.stringify({}) }); toast("Link updated: same address, the cards as they are now"); await load(); }
    catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const expired = (s: Shared) => !!s.expires_at && s.expires_at < new Date().toISOString();
  const body = (
    <div>
      {onClose && <h2 className="mb-3 text-lg font-semibold">Your shared links</h2>}
      {!list && <p className="text-mute">Loading…</p>}
      {list && !list.length && <p className="text-mute">You have not shared anything yet.</p>}
      <ul className="space-y-2">
        {list?.map((s) => (
          <li key={s.id} className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-surface p-3 ${expired(s) ? "opacity-60" : ""}`}>
            <span className="min-w-0 flex-1 truncate font-medium">{s.title} <span className="font-normal text-mute">· {s.kind} · {expired(s) ? "expired" : `until ${day(s.expires_at)}`}</span></span>
            <button className="btn-ghost !py-1" onClick={() => copy(s.url, toast)} disabled={expired(s)}><IconCopy className="size-4" />Copy</button>
            <button className="btn-ghost !py-1" onClick={() => openExternal(s.url)} disabled={expired(s)}><IconExternalLink className="size-4" />Open</button>
            <button className="btn-ghost !py-1" onClick={() => update(s)} disabled={expired(s) || !s.can_update || busy === s.id}
              title={!s.can_update ? "Made by an older version: make a new link" : "Put the cards as they are now under this same link (30 more days)"}><IconRefresh className="size-4" />Update</button>
            <button className="btn-danger !py-1" onClick={() => remove(s)} disabled={busy === s.id} aria-label={`Delete ${s.title}`}><IconTrash className="size-4" />Delete</button>
          </li>
        ))}
      </ul>
      {node}
    </div>
  );
  return onClose ? <Modal title="Your shared links" onClose={onClose} wide>{body}<div className="mt-4"><button className="btn-ghost" onClick={onClose}>Close</button></div></Modal> : body;
}
