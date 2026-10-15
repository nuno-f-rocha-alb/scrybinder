import { useEffect, useState } from "react";
import { api } from "../api";
import { DeckInfo } from "../decks";
import { Modal } from "./ui";

/** Choose a deck and put one copy of a card in its main board (the printing is kept when there is one). */
export default function DeckPicker({ oracleId, scryfallId, name, excludeId, onClose, onDone }: {
  oracleId: string; scryfallId: string | null; name: string; excludeId?: number; onClose: () => void; onDone: (deckName: string) => void;
}) {
  const [decks, setDecks] = useState<DeckInfo[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<DeckInfo[]>("/decks").then(setDecks).catch((e) => setErr(e.message)); }, []);
  const add = (d: DeckInfo) => api(`/decks/${d.id}/cards`, { method: "POST", body: JSON.stringify({ oracle_id: oracleId, scryfall_id: scryfallId, quantity: 1, board: "main" }) })
    .then(() => onDone(d.name)).catch((e) => setErr(e.message));
  const list = (decks ?? []).filter((d) => d.id !== excludeId);
  return (
    <Modal title={`Add ${name} to a deck`} onClose={onClose}>
      <h2 className="mb-3 text-lg font-semibold">Add {name} to a deck</h2>
      {!decks && !err && <p className="text-sm text-mute">Loading…</p>}
      {decks && list.length === 0 && <p className="rounded-xl border border-dashed border-line p-4 text-sm text-mute">There is no other deck yet.</p>}
      <ul className="divide-y divide-line">
        {list.map((d) => (
          <li key={d.id}><button className="flex w-full cursor-pointer items-center justify-between gap-4 px-2 py-2.5 text-left text-sm hover:bg-raised" onClick={() => add(d)}>
            <span className="truncate font-medium">{d.name}</span><span className="shrink-0 text-xs text-mute"><span className="capitalize">{d.format}</span> · {d.summary.cards} cards</span>
          </button></li>
        ))}
      </ul>
      {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-5 flex justify-end"><button className="btn-ghost" onClick={onClose}>Cancel</button></div>
    </Modal>
  );
}
