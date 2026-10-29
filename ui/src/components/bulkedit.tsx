import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { BOARDS, BOARD_LABEL, Board } from "../decks";
import { Modal } from "./ui";
import { Skipped } from "./decklist";
import type { ImportReport } from "./decklist";

type Edit = { added: { name: string; quantity: number }[]; changed: { name: string; from: number; to: number }[]; removed: { name: string; quantity: number }[]; skipped: ImportReport["skipped"]; applied: boolean };

/** Edit a whole board as text, one card per line (Moxfield's Bulk Edit): change a quantity, delete a line, paste a list. Save makes the deck match. */
export default function BulkEdit({ deckId, onClose, onDone }: { deckId: number; onClose: () => void; onDone: (summary: string) => void }) {
  const [board, setBoard] = useState<Board>("main");
  const [saved, setSaved] = useState<Partial<Record<Board, string>>>({});  // what the deck has now, per board
  const [text, setText] = useState<Partial<Record<Board, string>>>({});     // what is in the box, per board (the ones opened)
  const [report, setReport] = useState<{ board: Board; edit: Edit } | null>(null);
  const [review, setReview] = useState<{ board: Board; edit: Edit }[] | null>(null);  // what Save is about to remove, to confirm
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const done = useRef<string[]>([]);  // boards already saved: the deck page has to reload even if the rest fails
  const asked = useRef(new Set<Board>());

  useEffect(() => {
    if (asked.current.has(board)) return;
    asked.current.add(board);
    api<{ text: string }>(`/decks/${deckId}/bulk-edit?board=${board}`)
      .then((r) => { setSaved((s) => ({ ...s, [board]: r.text })); setText((t) => ({ ...t, [board]: r.text })); })
      .catch((e) => setErr(e.message));
  }, [board, deckId]);

  const dirty = BOARDS.filter((b) => text[b] !== undefined && text[b]!.trim() !== (saved[b] ?? "").trim());
  const label = (b: Board) => BOARD_LABEL[b] + (dirty.includes(b) ? " •" : "");

  const post = (b: Board, dry_run: boolean) => api<Edit>(`/decks/${deckId}/bulk-edit`, { method: "POST", body: JSON.stringify({ board: b, text: text[b], dry_run }) });

  /** A check first: lines that cannot be read stop it, and removals are shown to be confirmed; then each board is saved, one after the other (they share the database connection). */
  const save = async (confirmed = false) => {
    setBusy(true); setErr(""); setReport(null); setReview(null);
    try {
      if (!confirmed) {
        const checks: { board: Board; edit: Edit }[] = [];
        for (const b of dirty) {
          const edit = await post(b, true);
          if (edit.skipped.length) { setBoard(b); setReport({ board: b, edit }); return; }
          checks.push({ board: b, edit });
        }
        if (checks.some((c) => c.edit.removed.length)) { setReview(checks); return; }
      }
      for (const b of dirty) {
        const edit = await post(b, false);
        if (!edit.applied) { setBoard(b); setReport({ board: b, edit }); return; }
        setSaved((s) => ({ ...s, [b]: text[b]! }));
        done.current.push(`${BOARD_LABEL[b]}: ${[edit.added.length && `${edit.added.length} added`, edit.changed.length && `${edit.changed.length} changed`, edit.removed.length && `${edit.removed.length} removed`].filter(Boolean).join(", ")}`);
      }
      onDone(done.current.join(" · "));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const close = () => (done.current.length ? onDone(done.current.join(" · ")) : onClose());
  const here = report?.board === board ? report.edit : null;
  const lines = (text[board] ?? "").split("\n").filter((l) => l.trim()).length;
  return (
    <Modal title="Bulk edit" onClose={close}>
      <h2 className="mb-1 text-lg font-semibold">Bulk edit</h2>
      <p className="mb-3 text-sm text-mute">One card per line, like <code>2 Sol Ring (C21) 263 #ramp</code>. Change a number, delete a line or paste a list; Save makes the board match the text. Copies assigned to a line stay with it.</p>
      <div role="tablist" aria-label="Board" className="mb-2 flex flex-wrap gap-1">
        {BOARDS.map((b) => <button key={b} role="tab" aria-selected={b === board} className={b === board ? "btn-primary" : "btn-ghost"} onClick={() => setBoard(b)}>{label(b)}</button>)}
      </div>
      <textarea className="field h-80 font-mono text-xs" aria-label={`${BOARD_LABEL[board]} list`} spellCheck={false} wrap="off" disabled={text[board] === undefined}
        value={text[board] ?? "Loading…"} onChange={(e) => { setText((t) => ({ ...t, [board]: e.target.value })); setReport(null); setReview(null); }} />
      <p className="mt-1 text-xs text-mute">{BOARD_LABEL[board]} · {lines} {lines === 1 ? "line" : "lines"}</p>
      {here && <Skipped report={{ lines: 0, cards: 0, preview: [], skipped: here.skipped }} />}
      {here && <p className="mt-2 text-sm text-gold">Nothing was saved: fix or delete the lines above (a misspelt card would be removed from the deck).</p>}
      {review && (
        <div className="mt-3 rounded-lg border border-line bg-bg p-3 text-sm" role="alert">
          <p className="mb-1 font-medium text-gold">These cards will be removed from the deck:</p>
          <ul className="max-h-40 overflow-y-auto text-xs">
            {review.flatMap((r) => r.edit.removed.map((x, i) => <li key={`${r.board}-${i}`} className="flex gap-2 py-0.5"><span className="w-8 shrink-0 text-right tabular-nums">{x.quantity}</span><span className="min-w-0 flex-1 truncate">{x.name}</span><span className="shrink-0 text-mute">{BOARD_LABEL[r.board]}</span></li>))}
          </ul>
          <p className="mt-1 text-xs text-mute">{review.reduce((n, r) => n + r.edit.added.length, 0)} added, {review.reduce((n, r) => n + r.edit.changed.length, 0)} changed. Copies assigned to a removed card go back to the collection.</p>
        </div>
      )}
      {err && <p className="mt-3 text-sm text-danger">{err}{done.current.length ? ` (already saved: ${done.current.join("; ")})` : ""}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={close}>Cancel</button>
        {review ? <button className="btn-primary" disabled={busy} onClick={() => save(true)}>Remove {review.reduce((n, r) => n + r.edit.removed.length, 0)} and save</button>
          : <button className="btn-primary" disabled={busy || dirty.length === 0} onClick={() => save()}>Save{dirty.length > 1 ? ` ${dirty.length} boards` : ""}</button>}
      </div>
    </Modal>
  );
}
