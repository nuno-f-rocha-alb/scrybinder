import { useState } from "react";
import { IconUpload } from "@tabler/icons-react";
import { api } from "../api";
import { Modal } from "./ui";

export type ImportReport = { lines: number; cards: number; skipped: { line: number; text: string; reason: string }[]; preview: { line: number; board: string; quantity: number; name: string }[] };

/** The lines that did not make it, with the line, what it said and why. */
export function Skipped({ report }: { report: ImportReport }) {
  if (!report.skipped.length) return null;
  return (
    <div className="mt-3">
      <p className="mb-1 text-sm font-medium text-gold">{report.skipped.length} {report.skipped.length === 1 ? "line was" : "lines were"} left out</p>
      <ul className="max-h-48 overflow-y-auto rounded-lg border border-line bg-bg p-2 text-xs">
        {report.skipped.map((s) => <li key={s.line} className="flex gap-2 py-0.5"><span className="w-10 shrink-0 text-right text-mute tabular-nums">{s.line}</span><span className="min-w-0 flex-1 truncate" title={s.text}>{s.text}</span><span className="shrink-0 text-danger">{s.reason}</span></li>)}
      </ul>
    </div>
  );
}

/** Paste a deck list (or load a .txt) and add it to the deck: Moxfield, Archidekt and MTGO style. A check first shows what would happen. */
export default function ImportDialog({ deckId, onClose, onDone }: { deckId: number; onClose: () => void; onDone: (r: ImportReport) => void }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const send = (dry_run: boolean) => {
    setBusy(true); setErr("");
    api<ImportReport>(`/decks/${deckId}/import`, { method: "POST", body: JSON.stringify({ text, dry_run }) })
      .then((r) => { if (dry_run) setReport(r); else onDone(r); }).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  const change = (t: string) => { setText(t); setReport(null); };

  return (
    <Modal title="Import a deck list" onClose={onClose}>
      <h2 className="mb-1 text-lg font-semibold">Import a deck list</h2>
      <p className="mb-4 text-sm text-mute">One card per line, like <code>4 Lightning Bolt</code> or <code>1 Sol Ring (C21) 263 #ramp</code>. Sections can be <code>Commander</code>, <code>Deck</code>, <code>Sideboard</code> and <code>Maybeboard</code>; without headings, a blank line starts the sideboard. The cards are added to this deck.</p>
      <textarea className="field h-56 font-mono text-xs" aria-label="Deck list" placeholder={"Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n10 Island"} value={text} onChange={(e) => change(e.target.value)} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="btn-ghost cursor-pointer"><IconUpload className="size-4" />{file || "Choose a .txt file"}
          <input type="file" accept=".txt,text/plain" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setFile(f.name); change(await f.text()); } }} /></label>
        {report && <span className="text-sm text-ok" role="status">{report.cards} {report.cards === 1 ? "card" : "cards"} from {report.lines} lines will be added</span>}
      </div>
      {report && <Skipped report={report} />}
      {err && <p className="mt-3 text-sm text-danger">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        {report ? <button className="btn-primary" disabled={busy || report.cards === 0} onClick={() => send(false)}>Import {report.cards} {report.cards === 1 ? "card" : "cards"}</button>
          : <button className="btn-primary" disabled={busy || !text.trim()} onClick={() => send(true)}>Check the list</button>}
      </div>
    </Modal>
  );
}
