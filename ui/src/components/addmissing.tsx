import { useEffect, useState } from "react";
import { api } from "../api";
import { Field, Modal } from "./ui";

/** Adds the missing copies of a deck (all of them, or only `cardIds`) to the collection, in a location, and assigns them. With `printing`
 * it adds copies of the printing a card prefers instead, even when you own the card in another printing. */
export default function AddMissingDialog({ deckId, cardIds, count, printing, onClose, onDone }: {
  deckId: number; cardIds?: number[]; count: number; printing?: { cardId: number; label: string }; onClose: () => void; onDone: (added: number) => void;
}) {
  const [qty, setQty] = useState(1);
  const [location, setLocation] = useState("");
  const [locs, setLocs] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location).filter(Boolean))).catch(() => {}); }, []);

  const go = () => {
    setBusy(true);
    api<{ added: number }>(printing ? `/decks/${deckId}/cards/${printing.cardId}/add-copy` : `/decks/${deckId}/add-missing`,
      { method: "POST", body: JSON.stringify(printing ? { quantity: qty, location } : { card_ids: cardIds, location }) })
      .then((r) => onDone(r.added)).catch((e) => { setErr(e.message); setBusy(false); });
  };

  return (
    <Modal title="Add the missing copies to your collection" onClose={onClose}>
      <h2 className="mb-2 text-lg font-semibold">Add to your collection</h2>
      {printing ? (
        <>
          <p className="mb-4 text-sm text-mute">Copies of <b className="text-ink">{printing.label}</b> will be added and assigned to this card, even if you own the card in another printing.</p>
          <Field label="Copies"><input type="number" min={1} max={999} className="field mb-3 !w-24" value={qty} onChange={(e) => setQty(Math.max(1, +e.target.value || 1))} /></Field>
        </>
      ) : (
        <p className="mb-4 text-sm text-mute">
          {count} missing {count === 1 ? "copy" : "copies"} will be added, in the preferred printing (the cheapest when the deck has none), and assigned to the deck. Proxies are skipped.
        </p>
      )}
      <Field label="Location (optional)">
        <input className="field" list="missinglocs" value={location} maxLength={60} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Deck box" />
        <datalist id="missinglocs">{locs.map((l) => <option key={l} value={l} />)}</datalist>
      </Field>
      {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy} onClick={go}>Add to collection</button>
      </div>
    </Modal>
  );
}
