import { useState } from "react";
import { Modal, useToast } from "./ui";
import { exportDeckList } from "../decks";

export const INCLUDE_ALL = ["collection", "elsewhere", "proxy", "missing"];
const OPTIONS: [string, string][] = [
  ["collection", "In my collection (assigned, free to assign, or basic lands)"],
  ["elsewhere", "In another deck"],
  ["proxy", "Proxies"],
  ["missing", "Missing (not owned)"],
];

/** Which cards of the deck go out, by where they are. */
export function DeckInclude({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-sm font-medium">Include cards</legend>
      {OPTIONS.map(([k, label]) => (
        <label key={k} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.includes(k)} onChange={(e) => onChange(e.target.checked ? [...value, k] : value.filter((x) => x !== k))} />{label}
        </label>
      ))}
      {!value.length && <p role="alert" className="text-sm text-danger">Choose at least one.</p>}
    </fieldset>
  );
}

/** Saves the deck as a text list with only the chosen cards. */
export default function ExportDialog({ id, name, onClose }: { id: number; name: string; onClose: () => void }) {
  const [include, setInclude] = useState(INCLUDE_ALL);
  const { toast, node } = useToast();
  return (
    <Modal title="Export list" onClose={onClose}>
      <h2 className="mb-3 text-lg font-semibold">Export list</h2>
      <DeckInclude value={include} onChange={setInclude} />
      <div className="mt-4 flex gap-2">
        <button className="btn-primary" disabled={!include.length}
          onClick={() => exportDeckList(id, name, toast, include.length === INCLUDE_ALL.length ? undefined : include)}>Save list</button>
        <button className="btn-ghost" onClick={onClose}>Close</button>
      </div>
      {node}
    </Modal>
  );
}
