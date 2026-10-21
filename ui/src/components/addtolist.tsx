import { useEffect, useState } from "react";
import { api } from "../api";
import { Select } from "./select";
import { Field, Modal } from "./ui";

export type ListSummary = { id: number; name: string; note: string; cards: number; lines: number; value: number; updated_at: string };
/** What to add: collection rows (by id) or cards (a printing, with the finish and quantity wanted; a card you do not own is fine). */
export type ListPayload = { collection_ids: number[] } | { items: { scryfall_id: string; finish?: string; quantity?: number; condition?: string; language?: string }[] };

const NEW = "new";
const LAST = "scrybinder.list";

/** Pick a list (or make one) and put the cards in it. `what` names the cards in the title ("3 cards", "Sol Ring"). */
export default function AddToList({ payload, what, onClose, onDone }: { payload: ListPayload; what: string; onClose: () => void; onDone: (message: string) => void }) {
  const [lists, setLists] = useState<ListSummary[] | null>(null);
  const [pick, setPick] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<ListSummary[]>("/lists").then((l) => {
      setLists(l);
      let last = ""; try { last = localStorage.getItem(LAST) ?? ""; } catch { /* no storage */ }
      setPick(l.some((x) => String(x.id) === last) ? last : l.length ? String(l[0].id) : NEW);
    }).catch((e) => setErr(e.message));
  }, []);

  const go = async () => {
    setBusy(true); setErr("");
    try {
      let id = pick, label = lists?.find((l) => String(l.id) === pick)?.name ?? "";
      if (pick === NEW) { id = String((await api<{ id: number }>("/lists", { method: "POST", body: JSON.stringify({ name }) })).id); label = name.trim(); }
      const r = await api<{ added: number }>(`/lists/${id}/items`, { method: "POST", body: JSON.stringify(payload) });
      try { localStorage.setItem(LAST, id); } catch { /* no storage */ }
      onDone(`Added ${r.added} ${r.added === 1 ? "copy" : "copies"} to "${label}"`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Add to a list" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (pick && (pick !== NEW || name.trim())) go(); }}>
        <h2 className="mb-3 text-lg font-semibold">Add {what} to a list</h2>
        {!lists && !err && <p className="text-mute">Loading…</p>}
        {lists && (
          <div className="space-y-3">
            <Field label="List"><Select className="field" value={pick} onChange={(e) => setPick(e.target.value)}>
              {lists.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.cards})</option>)}<option value={NEW}>New list…</option></Select></Field>
            {pick === NEW && <Field label="Name of the new list"><input autoFocus className="field" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Trade binder" /></Field>}
          </div>
        )}
        {err && <p role="alert" className="mt-3 text-sm text-danger">{err}</p>}
        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary" disabled={busy || !lists || (pick === NEW && !name.trim())}>{busy ? "Adding…" : "Add"}</button>
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  );
}
