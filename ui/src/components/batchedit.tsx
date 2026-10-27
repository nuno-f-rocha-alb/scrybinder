import { useState } from "react";
import { api } from "../api";
import { BOARDS, BOARD_LABEL, DeckCard } from "../decks";
import { Select } from "./select";
import { Field, Modal } from "./ui";

const list = (s: string) => s.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);

/** One window for every change that can be made to the selected cards together; a field left as it is changes nothing. */
export default function BatchEdit({ deckId, cards, onClose, onDone }: { deckId: number; cards: DeckCard[]; onClose: () => void; onDone: () => void }) {
  const [board, setBoard] = useState("");
  const [proxy, setProxy] = useState("");
  const [qty, setQty] = useState("");
  const [add, setAdd] = useState("");
  const [drop, setDrop] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const q = qty.trim() === "" ? null : Number(qty);
  const bad = q !== null && (!Number.isInteger(q) || q < 1);
  const nothing = !board && !proxy && q === null && !add.trim() && !drop.trim();

  const apply = async () => {
    setBusy(true); setErr("");
    let done = 0;
    try {
      for (const c of cards) {  // one after the other: the server shares one database connection, and a change can move copies between rows
        let tags = c.tags.filter((t) => !list(drop).includes(t));
        tags = [...new Set([...tags, ...list(add)])];
        if (proxy === "yes") tags = [...new Set([...tags, "proxy"])];
        if (proxy === "no") tags = tags.filter((t) => t !== "proxy");
        const body: Record<string, unknown> = {};
        if (board) body.board = board;
        if (q !== null) body.quantity = q;
        if (add.trim() || drop.trim() || proxy) body.tags = tags;
        await api(`/decks/${deckId}/cards/${c.id}`, { method: "PATCH", body: JSON.stringify(body) });
        done++;
      }
      onDone();
    } catch (e) {
      setErr(`${(e as Error).message}${done ? ` (${done} of ${cards.length} cards were changed)` : ""}`);
      if (done) onDone();
    } finally { setBusy(false); }
  };

  return (
    <Modal title="Edit selected cards" onClose={onClose}>
      <h2 className="mb-1 text-lg font-semibold">Edit {cards.length} {cards.length === 1 ? "card" : "cards"}</h2>
      <p className="mb-4 text-sm text-mute">Only the fields you change are applied to every selected card.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Board">
          <Select className="field" value={board} onChange={(e) => setBoard(e.target.value)}>
            <option value="">Keep as it is</option>{BOARDS.map((b) => <option key={b} value={b}>{BOARD_LABEL[b]}</option>)}
          </Select>
        </Field>
        <Field label="Proxy">
          <Select className="field" value={proxy} onChange={(e) => setProxy(e.target.value)}>
            <option value="">Keep as it is</option><option value="yes">Mark as proxy</option><option value="no">Not a proxy (real copies)</option>
          </Select>
        </Field>
        <Field label="Quantity (set every card to)"><input className="field" inputMode="numeric" placeholder="Keep as it is" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <span />
        <Field label="Add tags (comma separated)"><input className="field" value={add} onChange={(e) => setAdd(e.target.value)} placeholder="ramp, draw cards" /></Field>
        <Field label="Remove tags (comma separated)"><input className="field" value={drop} onChange={(e) => setDrop(e.target.value)} /></Field>
      </div>
      {proxy === "yes" && <p className="mt-3 text-xs text-mute">A proxy uses no copy of your collection: copies already assigned to these cards go back.</p>}
      {bad && <p role="alert" className="mt-3 text-sm text-danger">The quantity must be a whole number, 1 or more.</p>}
      {err && <p role="alert" className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-4 flex gap-2">
        <button className="btn-primary" disabled={busy || nothing || bad} onClick={apply}>{busy ? "Applying…" : "Apply"}</button>
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}
