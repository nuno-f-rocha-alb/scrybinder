import { useState } from "react";
import { Combo, Select } from "../components/select";
import { IconPencil, IconTrash, IconX } from "@tabler/icons-react";
import { api, ApiError, CONDITIONS, FINISH, LANGS } from "../api";
import { Blocked, Modal } from "../components/ui";

type Done = (msg: string, err?: boolean) => void;

/** Fixed bar at the bottom with the current selection and the bulk actions. */
export function BulkBar({ count, total, onSelectAll, onClear, onEdit, onDelete, onExit }: {
  count: number; total: number; onSelectAll: () => void; onClear: () => void; onEdit: () => void; onDelete: () => void; onExit: () => void;
}) {
  return (
    <div role="toolbar" aria-label="Bulk actions"
      className="fixed inset-x-0 bottom-5 z-40 mx-auto flex w-fit max-w-[95vw] flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface/95 px-4 py-3 shadow-2xl backdrop-blur">
      <span className="text-sm"><b className="tabular-nums text-ink">{count}</b> <span className="text-mute">{count === 1 ? "row selected" : "rows selected"}</span></span>
      {count < total && <button className="cursor-pointer text-sm text-accent hover:underline" onClick={onSelectAll}>Select all ({total})</button>}
      {count > 0 && <button className="cursor-pointer text-sm text-mute hover:text-ink" onClick={onClear}>Clear</button>}
      <span className="mx-1 h-5 w-px bg-line" aria-hidden />
      <button className="btn-ghost" disabled={!count} onClick={onEdit}><IconPencil className="size-4" />Edit</button>
      <button className="btn-danger" disabled={!count} onClick={onDelete}><IconTrash className="size-4" />Delete</button>
      <button className="btn-ghost" onClick={onExit} aria-label="Leave selection mode"><IconX className="size-4" />Done</button>
    </div>
  );
}

type FieldDef = { key: string; label: string; kind: "text" | "select" | "bool" | "number" | "area"; options?: [string, string][] };
const FIELDS: FieldDef[] = [
  { key: "location", label: "Location", kind: "text" },
  { key: "finish", label: "Finish", kind: "select", options: Object.entries(FINISH) },
  { key: "condition", label: "Condition", kind: "select", options: CONDITIONS.map((c) => [c, c]) },
  { key: "language", label: "Language", kind: "select", options: Object.entries(LANGS) },
  { key: "altered", label: "Altered", kind: "bool" },
  { key: "signed", label: "Signed", kind: "bool" },
  { key: "misprint", label: "Misprint", kind: "bool" },
  { key: "proxy", label: "Proxy", kind: "bool" },
  { key: "purchase_price", label: "Purchase price (€)", kind: "number" },
  { key: "notes", label: "Notes (replaces)", kind: "area" },
];
const DEFAULT: Record<string, string> = { finish: "nonfoil", condition: "NM", language: "en", altered: "1", signed: "1", misprint: "1", proxy: "1" };

/** Only the fields whose "Change" switch is on are sent. */
export function BulkEdit({ ids, locations, onClose, onDone }: { ids: number[]; locations: string[]; onClose: () => void; onDone: Done }) {
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [val, setVal] = useState<Record<string, string>>(DEFAULT);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState<string | null>(null);  // the copies are in decks: wait for "Release and continue"
  const chosen = FIELDS.filter((f) => on[f.key]);

  const submit = async (release = "") => {
    const fields: Record<string, string | number | null> = {};
    for (const f of chosen) {
      const v = val[f.key] ?? "";
      fields[f.key] = f.kind === "bool" ? Number(v === "1") : f.kind === "number" ? (v === "" ? null : Number(v)) : v;
    }
    setBusy(true);
    try {
      const r = await api<{ updated: number; merged: number; skipped: number }>("/collection/bulk" + release, { method: "POST", body: JSON.stringify({ ids, action: "update", fields }) });
      onDone(`${r.updated} rows updated${r.merged ? ` · ${r.merged} merged into identical rows` : ""}${r.skipped ? ` · ${r.skipped} skipped (that printing does not exist in that finish)` : ""}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { setBlocked(e.message); setBusy(false); } else { onDone((e as Error).message, true); setBusy(false); }
    }
  };

  return (
    <Modal onClose={onClose} title="Bulk edit">
      <h2 className="text-xl font-semibold">Edit {ids.length} {ids.length === 1 ? "row" : "rows"}</h2>
      <p className="mb-4 mt-1 text-sm text-mute">Switch on only the fields you want to change; the others stay as they are. If two rows end up identical their quantities are added.</p>
      <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <div key={f.key} className={`rounded-xl border p-3 transition ${on[f.key] ? "border-accent/60 bg-accent-soft" : "border-line"} ${f.kind === "area" ? "sm:col-span-2" : ""}`}>
            <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={!!on[f.key]} onChange={(e) => setOn({ ...on, [f.key]: e.target.checked })} className="accent-[var(--color-accent)]" />Change {f.label.toLowerCase()}
            </label>
            {f.kind === "text" && <><Combo className="field" suggestions={locations} disabled={!on[f.key]} value={val[f.key] ?? ""} placeholder="empty = no location"
              onChange={(v) => setVal({ ...val, [f.key]: v })} /></>}
            {f.kind === "select" && <Select className="field" disabled={!on[f.key]} value={val[f.key]} onChange={(e) => setVal({ ...val, [f.key]: e.target.value })}>
              {f.options!.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}
            {f.kind === "bool" && <Select className="field" disabled={!on[f.key]} value={val[f.key]} onChange={(e) => setVal({ ...val, [f.key]: e.target.value })}>
              <option value="1">Yes</option><option value="0">No</option></Select>}
            {f.kind === "number" && <input type="number" min={0} step="0.01" className="field" disabled={!on[f.key]} value={val[f.key] ?? ""} placeholder="empty = no price"
              onChange={(e) => setVal({ ...val, [f.key]: e.target.value })} />}
            {f.kind === "area" && <textarea className="field min-h-16" disabled={!on[f.key]} value={val[f.key] ?? ""} onChange={(e) => setVal({ ...val, [f.key]: e.target.value })} />}
          </div>
        ))}
      </div>
      {blocked && <Blocked message={blocked} onRelease={() => submit("?release=1")} onCancel={() => setBlocked(null)} />}
      <div className="mt-5 flex items-center justify-between">
        <span className="text-sm text-mute">{chosen.length ? `Changing: ${chosen.map((f) => f.label.split(" (")[0].toLowerCase()).join(", ")}` : "No field switched on"}</span>
        <div className="flex gap-2"><button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!chosen.length || busy} onClick={() => submit()}>{busy ? "Saving…" : `Apply to ${ids.length}`}</button></div>
      </div>
    </Modal>
  );
}

/** Explicit confirmation: deleting has no "undo" in the interface (the rows are kept in data/trash). */
export function BulkDelete({ ids, preview, onClose, onDone }: { ids: number[]; preview: string[]; onClose: () => void; onDone: Done }) {
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState<string | null>(null);
  const run = async (release = "") => {
    setBusy(true);
    try {
      const r = await api<{ deleted: number }>("/collection/bulk" + release, { method: "POST", body: JSON.stringify({ ids, action: "delete" }) });
      onDone(`${r.deleted} rows deleted (backup in data/trash)`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { setBlocked(e.message); setBusy(false); } else { onDone((e as Error).message, true); setBusy(false); }
    }
  };
  return (
    <Modal onClose={onClose} title="Bulk delete">
      <h2 className="text-xl font-semibold text-danger">Delete {ids.length} {ids.length === 1 ? "row" : "rows"}?</h2>
      <p className="mt-2 text-sm text-mute">The rows and all their copies leave the collection. Before deleting, a copy is saved in <code>data/trash</code> so you can recover them, but there is no “undo” in the app.</p>
      {preview.length > 0 && (
        <ul className="mt-3 space-y-0.5 rounded-lg border border-line bg-bg p-3 text-sm">
          {preview.map((p) => <li key={p} className="truncate">{p}</li>)}
          {ids.length > preview.length && <li className="text-mute">… and {ids.length - preview.length} more</li>}
        </ul>
      )}
      {blocked && <Blocked message={blocked} onRelease={() => run("?release=1")} onCancel={() => setBlocked(null)} />}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" autoFocus onClick={onClose}>Cancel</button>
        <button className="btn-danger" disabled={busy} onClick={() => run()}>{busy ? "Deleting…" : `Yes, delete ${ids.length}`}</button>
      </div>
    </Modal>
  );
}
