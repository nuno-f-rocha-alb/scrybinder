import { useCallback, useEffect, useRef, useState } from "react";
import { IconCamera, IconTrash } from "@tabler/icons-react";
import { api, eur } from "../api";

type Snap = { id: number; name: string; created_at: string; cards: number; value: number };
type Entry = { oracle_id: string; name: string; board: string; old_qty: number; new_qty: number; delta_qty: number; price: number | null; line_delta: number };
type Diff = { added: Entry[]; removed: Entry[]; changed: Entry[]; price_difference: number };

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function Rows({ title, rows, tone }: { title: string; rows: Entry[]; tone: string }) {
  if (!rows.length) return null;
  return (
    <section className="mt-4">
      <h3 className={`mb-1 text-sm font-semibold ${tone}`}>{title} ({rows.length})</h3>
      <table className="w-full text-sm"><tbody>
        {rows.map((e) => (
          <tr key={`${e.oracle_id}-${e.board}`} className="border-b border-line/60">
            <td className="py-1 pr-3">{e.name}{e.board !== "main" && <span className="ml-2 text-xs text-mute">{e.board}</span>}</td>
            <td className="px-3 text-mute tabular-nums">{e.old_qty} → {e.new_qty}</td>
            <td className="pl-3 text-right tabular-nums">{e.line_delta > 0 ? "+" : ""}{eur(e.line_delta)}</td>
          </tr>
        ))}
      </tbody></table>
    </section>
  );
}

/** Saved copies of a deck's card list, and what changed between any two states of the deck. */
export default function Snapshots({ deckId, toast, onRestored }: { deckId: number; toast: (m: string, err?: boolean) => void; onRestored?: () => void }) {
  const [snaps, setSnaps] = useState<Snap[] | null>(null);
  const [name, setName] = useState("");
  const [base, setBase] = useState("latest");
  const [target, setTarget] = useState("current");
  const [diff, setDiff] = useState<Diff | null>(null);
  const say = useRef(toast);  // toast is a new function on every render of the page: reading it from a ref keeps load stable
  say.current = toast;
  const load = useCallback(() => api<Snap[]>(`/decks/${deckId}/snapshots`).then(setSnaps).catch((e) => say.current(e.message, true)), [deckId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!snaps?.length) { setDiff(null); return; }
    let live = true;
    api<Diff>(`/decks/${deckId}/compare?base=${base}&target=${target}`).then((d) => live && setDiff(d)).catch(() => live && setDiff(null));
    return () => { live = false; };
  }, [deckId, base, target, snaps]);

  const save = () => api<{ id: number }>(`/decks/${deckId}/snapshots`, { method: "POST", body: JSON.stringify({ name: name.trim() || new Date().toLocaleString() }) })
    .then((r) => { setName(""); setBase(String(r.id)); setTarget("current"); toast("Snapshot saved"); return load(); }).catch((e) => toast(e.message, true));
  const [confirm, setConfirm] = useState<number | null>(null);  // the snapshot whose Restore was clicked once
  const restore = (s: Snap) => {
    if (confirm !== s.id) { setConfirm(s.id); setTimeout(() => setConfirm((c) => (c === s.id ? null : c)), 4000); return; }
    setConfirm(null);
    api<{ restored: number; skipped: number }>(`/decks/${deckId}/snapshots/${s.id}/restore`, { method: "POST" })
      .then((r) => { toast(`Deck restored to "${s.name}"${r.skipped ? ` (${r.skipped} cards could not be added)` : ""}. Your previous deck is saved as a snapshot.`); setBase("latest"); setTarget("current"); onRestored?.(); return load(); })
      .catch((e) => toast(e.message, true));
  };
  const remove = (s: Snap) => api(`/decks/${deckId}/snapshots/${s.id}`, { method: "DELETE" })
    .then(() => { if (base === String(s.id)) setBase("latest"); if (target === String(s.id)) setTarget("current"); return load(); }).catch((e) => toast(e.message, true));

  const options = (extra: string[]) => [...extra.map((v) => <option key={v} value={v}>{v === "current" ? "The deck now" : "Newest snapshot"}</option>), ...(snaps ?? []).map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)];
  const none = diff && !diff.added.length && !diff.removed.length && !diff.changed.length;
  return (
    <div className="max-w-3xl">
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <label className="text-xs font-medium text-mute">Name
          <input className="field mt-1 block w-64" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} placeholder="Before the changes" /></label>
        <button className="btn-primary" onClick={save}><IconCamera className="size-4" />Save snapshot</button>
      </div>
      {snaps === null && <p className="text-mute">Loading…</p>}
      {snaps && !snaps.length && <p className="text-mute">No snapshots yet. A snapshot keeps the deck's cards as they are now, so you can see later what changed.</p>}
      {snaps && snaps.length > 0 && <>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-mute"><th className="py-2 pr-3 font-medium">Snapshot</th><th className="px-3 font-medium">Saved</th><th className="px-3 text-right font-medium">Cards</th><th className="px-3 text-right font-medium">Value</th><th /></tr></thead>
          <tbody>{snaps.map((s) => (
            <tr key={s.id} className="border-b border-line/60">
              <td className="py-1.5 pr-3">{s.name}</td><td className="px-3 text-mute">{when(s.created_at)}</td>
              <td className="px-3 text-right tabular-nums">{s.cards}</td><td className="px-3 text-right tabular-nums">{eur(s.value)}</td>
              <td className="whitespace-nowrap text-right"><button className="btn-ghost" onClick={() => restore(s)} title="Put the deck back as it was in this snapshot (the deck now is saved first)">{confirm === s.id ? "Click again to restore" : "Restore"}</button><button className="btn-ghost" aria-label={`Delete snapshot ${s.name}`} onClick={() => remove(s)}><IconTrash className="size-4" /></button></td>
            </tr>
          ))}</tbody>
        </table>
        <h2 className="mb-2 mt-6 font-semibold">Compare</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select className="field w-auto" value={base} onChange={(e) => setBase(e.target.value)} aria-label="Compare from">{options(["latest"])}</select>
          <span className="text-mute">to</span>
          <select className="field w-auto" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Compare to">{options(["current"])}</select>
        </div>
        {diff && (
          <div aria-live="polite">
            <p className="mt-3 text-sm text-mute">{none ? "No differences." : <>The change costs <b className="text-ink">{eur(diff.price_difference)}</b> at today's prices.</>}</p>
            <Rows title="Added" rows={diff.added} tone="text-ok" />
            <Rows title="Removed" rows={diff.removed} tone="text-danger" />
            <Rows title="Changed" rows={diff.changed} tone="text-gold" />
          </div>
        )}
      </>}
    </div>
  );
}
