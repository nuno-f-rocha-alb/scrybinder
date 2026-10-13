import { useEffect, useState } from "react";
import { IconAlertTriangle, IconCheck, IconChevronRight, IconFolder, IconFolderPlus, IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { api, eur, img } from "../api";
import { DeckInfo, FORMATS, Folder, Format, Legality } from "../decks";
import { Field, Modal, useToast } from "../components/ui";
import Deck from "./Deck";
import { ImportReport, Skipped } from "../components/decklist";

const label = (f: string) => f[0].toUpperCase() + f.slice(1);
const NONE = "none";  // the section of the decks that are in no folder

function Seal({ format, legality }: { format: Format; legality?: Legality }) {
  if (format === "casual" || !legality) return null;
  const errors = legality.problems.filter((p) => p.severity === "error").length;
  return errors ? (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-danger" title={legality.problems.map((p) => p.message).join("\n")}>
      <IconAlertTriangle className="size-3.5" aria-hidden />{errors} {errors === 1 ? "issue" : "issues"}
    </span>
  ) : <span className="inline-flex items-center gap-1 text-xs font-medium text-ok"><IconCheck className="size-3.5" aria-hidden />Legal</span>;
}

/** Which folders are folded, remembered between sessions. */
function useFolded(): [Set<string>, (k: string) => void] {
  const [folded, set] = useState<Set<string>>(() => { try { return new Set(JSON.parse(localStorage.getItem("scrybinder.deckfolders") ?? "[]")); } catch { return new Set(); } });
  return [folded, (k) => set((cur) => {
    const next = new Set(cur);
    next.has(k) ? next.delete(k) : next.add(k);
    try { localStorage.setItem("scrybinder.deckfolders", JSON.stringify([...next])); } catch { /* no storage */ }
    return next;
  })];
}

function DeckCard({ d, legality, folders, onOpen, onMove }: { d: DeckInfo; legality?: Legality; folders: Folder[]; onOpen: () => void; onMove: (folder: number | null) => void }) {
  return (
    <div className="group flex flex-col overflow-hidden rounded-xl border border-line bg-surface transition focus-within:border-accent hover:border-accent hover:bg-raised">
      <button onClick={onOpen} className="flex cursor-pointer flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <div className="h-36 w-full overflow-hidden bg-raised">
          {d.cover && <img src={img(d.cover, "normal")} alt="" loading="lazy" className="h-full w-full object-cover object-[50%_18%] transition group-hover:scale-[1.03]" />}
        </div>
        <div className="flex flex-col gap-1.5 p-4 pb-2">
          <div className="truncate text-base font-medium leading-tight">{d.name}</div>
          <div className="flex items-center justify-between text-sm text-mute">
            <span>{label(d.format)} · {d.summary.cards} cards</span>
            <Seal format={d.format} legality={legality} />
          </div>
          <div className="text-xs text-mute tabular-nums">
            {d.summary.missing ? <span className="text-danger">{d.summary.missing} to buy · {eur(d.summary.cost_to_complete)}</span>
              : d.summary.cards ? <span className="text-ok">Nothing to buy</span> : "Empty"}
          </div>
        </div>
      </button>
      <label className="flex items-center gap-2 px-4 pb-3 text-xs text-mute">
        <IconFolder className="size-3.5 shrink-0" aria-hidden /><span className="sr-only">Folder of {d.name}</span>
        <select className="field !px-2 !py-1 text-xs" value={d.folder_id ?? ""} onChange={(e) => onMove(e.target.value === "" ? null : Number(e.target.value))}>
          <option value="">No folder</option>
          {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      </label>
    </div>
  );
}

export default function Decks() {
  const [open, setOpen] = useState<number | null>(null);
  const [decks, setDecks] = useState<DeckInfo[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [legal, setLegal] = useState<Record<number, Legality>>({});
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [format, setFormat] = useState<Format>("commander");
  const [folder, setFolder] = useState<number | null>(null);
  const [list, setList] = useState("");
  const [report, setReport] = useState<{ id: number; r: ImportReport } | null>(null);
  const [folderDialog, setFolderDialog] = useState<{ id?: number; name: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [folded, toggle] = useFolded();
  const [err, setErr] = useState("");
  const { toast, node } = useToast();

  // the legality of the decks is asked again only when the list is (re)opened: moving a deck or editing a folder does not change it
  const load = (legality = false) => Promise.all([api<DeckInfo[]>("/decks"), api<Folder[]>("/deck-folders")]).then(([d, f]) => {
    setDecks(d); setFolders(f);
    if (legality) d.filter((x) => x.format !== "casual").forEach((x) => api<Legality>(`/decks/${x.id}/legality`).then((l) => setLegal((m) => ({ ...m, [x.id]: l }))).catch(() => {}));
  }).catch((e) => setErr(e.message));
  useEffect(() => { if (open === null) load(true); }, [open]);
  // an install updated from an older version fills the card rules in the background at start-up (a few seconds)
  const [rules, setRules] = useState<{ cards_in_db: number; oracle_cards: number } | null>(null);
  useEffect(() => {
    const ask = () => api<{ cards_in_db: number; oracle_cards: number }>("/status").then(setRules).catch(() => {});
    ask();
    const t = setInterval(() => setRules((r) => { if (!r || r.oracle_cards === 0) ask(); return r; }), 3000);
    return () => clearInterval(t);
  }, []);

  if (open !== null) return <Deck id={open} onBack={() => setOpen(null)} />;

  const run = (p: Promise<unknown>) => p.then(() => load()).catch((e) => toast(e.message, true));
  const create = async () => {
    try {
      const { id } = await api<{ id: number }>("/decks", { method: "POST", body: JSON.stringify({ name, format, folder_id: folder }) });
      // the deck exists now: if the list is refused the deck still opens (empty) and says why, instead of a retry making a second deck
      const r = list.trim() ? await api<ImportReport>(`/decks/${id}/import`, { method: "POST", body: JSON.stringify({ text: list }) })
        .catch((e: Error): ImportReport => ({ lines: 0, cards: 0, preview: [], skipped: [{ line: 0, text: "the pasted list", reason: e.message }] })) : null;
      setCreating(false); setName(""); setList("");
      if (r && r.skipped.length) setReport({ id, r }); else setOpen(id);  // lines that did not match a card are shown before the deck opens
    } catch (e) { setErr((e as Error).message); }
  };
  const saveFolder = () => {
    if (!folderDialog) return;
    const f = folderDialog;
    api(f.id ? `/deck-folders/${f.id}` : "/deck-folders", { method: f.id ? "PATCH" : "POST", body: JSON.stringify({ name: f.name }) })
      .then(() => { setFolderDialog(null); load(); }).catch((e) => setErr(e.message));
  };
  const move = (d: DeckInfo, to: number | null) => run(api(`/decks/${d.id}`, { method: "PATCH", body: JSON.stringify({ folder_id: to }) }));

  const grid = (list: DeckInfo[]) => (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
      {list.map((d) => <DeckCard key={d.id} d={d} legality={legal[d.id]} folders={folders} onOpen={() => setOpen(d.id)} onMove={(to) => move(d, to)} />)}
    </div>
  );
  const unfiled = decks?.filter((d) => d.folder_id === null) ?? [];
  const section = (key: string, title: React.ReactNode, count: number, body: React.ReactNode, actions?: React.ReactNode) => (
    <section key={key} className="mb-6" aria-label={typeof title === "string" ? title : undefined}>
      <div className="mb-3 flex items-center gap-2 border-b border-line pb-1.5">
        <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-expanded={!folded.has(key)} onClick={() => toggle(key)}>
          <IconChevronRight className={`size-4 shrink-0 text-mute transition-transform ${folded.has(key) ? "" : "rotate-90"}`} aria-hidden />
          <IconFolder className="size-4 shrink-0 text-mute" aria-hidden /><span className="truncate">{title}</span>
          <span className="text-xs font-normal text-mute">{count}</span>
        </button>
        {actions}
      </div>
      {!folded.has(key) && body}
    </section>
  );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Decks</h1>
          {decks && <p className="mt-1 text-sm text-mute">{decks.length} {decks.length === 1 ? "deck" : "decks"}{folders.length ? ` · ${folders.length} ${folders.length === 1 ? "folder" : "folders"}` : ""}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => { setErr(""); setFolderDialog({ name: "" }); }}><IconFolderPlus className="size-4" />New folder</button>
          <button className="btn-primary" onClick={() => { setErr(""); setFolder(null); setCreating(true); }}><IconPlus className="size-4" />New deck</button>
        </div>
      </div>
      {err && !creating && !folderDialog && <p className="mb-4 text-sm text-danger">{err}</p>}
      {rules && rules.oracle_cards === 0 && (
        <p className="mb-4 rounded-xl border border-gold/30 bg-gold/10 px-4 py-3 text-sm text-gold" role="status">
          {rules.cards_in_db ? "Preparing the card rules from your card database (a few seconds). If this stays, update the bulk data in Settings." : "Download the card database in Settings first: decks need the card rules in it."}
        </p>
      )}
      {decks && decks.length === 0 && !folders.length && (
        <div className="rounded-2xl border border-dashed border-line p-16 text-center text-mute">No decks yet. Create one to start building.</div>
      )}
      {decks && !folders.length && grid(unfiled)}
      {decks && folders.length > 0 && <>
        {folders.map((f) => {
          const inside = decks.filter((d) => d.folder_id === f.id);
          return section(String(f.id), f.name, inside.length,
            inside.length ? grid(inside) : <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-mute">Empty folder. Move a deck here from its folder menu.</p>,
            <span className="flex shrink-0 items-center gap-1">
              <button className="flex size-7 items-center justify-center rounded-md text-mute hover:bg-raised hover:text-ink" aria-label={`Rename ${f.name}`} onClick={() => { setErr(""); setFolderDialog({ id: f.id, name: f.name }); }}><IconPencil className="size-4" /></button>
              <button className={`flex h-7 items-center justify-center gap-1 rounded-md px-1.5 text-xs ${confirmDelete === f.id ? "bg-danger/15 text-danger" : "text-mute hover:bg-raised hover:text-danger"}`} aria-label={`Delete ${f.name}`}
                title="The decks in it stay, outside every folder"
                onClick={() => { if (confirmDelete !== f.id) { setConfirmDelete(f.id); setTimeout(() => setConfirmDelete((c) => (c === f.id ? null : c)), 4000); return; } setConfirmDelete(null); run(api(`/deck-folders/${f.id}`, { method: "DELETE" })); }}>
                <IconTrash className="size-4" />{confirmDelete === f.id && "Click again"}
              </button>
            </span>);
        })}
        {unfiled.length > 0 && section(NONE, "No folder", unfiled.length, grid(unfiled))}
      </>}

      {creating && (
        <Modal title="New deck" onClose={() => setCreating(false)}>
          <h2 className="mb-4 text-lg font-semibold">New deck</h2>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create(); }}>
            <Field label="Name"><input className="field" autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
            <Field label="Format">
              <select className="field" value={format} onChange={(e) => setFormat(e.target.value as Format)}>
                {FORMATS.map((f) => <option key={f} value={f}>{label(f)}</option>)}
              </select>
            </Field>
            {folders.length > 0 && (
              <Field label="Folder">
                <select className="field" value={folder ?? ""} onChange={(e) => setFolder(e.target.value === "" ? null : Number(e.target.value))}>
                  <option value="">No folder</option>
                  {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </Field>
            )}
            <Field label="Deck list (optional)">
              <textarea className="field h-32 font-mono text-xs" value={list} onChange={(e) => setList(e.target.value)} placeholder={"Paste a list from Moxfield, Archidekt or MTGO:\n1 Sol Ring\n10 Island"} />
            </Field>
            {err && <p className="text-sm text-danger">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setCreating(false)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={!name.trim()}>Create</button>
            </div>
          </form>
        </Modal>
      )}
      {report && (
        <Modal title="Deck created" onClose={() => { setOpen(report.id); setReport(null); }}>
          <h2 className="mb-2 text-lg font-semibold">Deck created with {report.r.cards} {report.r.cards === 1 ? "card" : "cards"}</h2>
          <Skipped report={report.r} />
          <div className="mt-5 flex justify-end"><button className="btn-primary" onClick={() => { setOpen(report.id); setReport(null); }}>Open the deck</button></div>
        </Modal>
      )}
      {folderDialog && (
        <Modal title={folderDialog.id ? "Rename folder" : "New folder"} onClose={() => setFolderDialog(null)}>
          <h2 className="mb-4 text-lg font-semibold">{folderDialog.id ? "Rename folder" : "New folder"}</h2>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); saveFolder(); }}>
            <Field label="Name"><input className="field" autoFocus value={folderDialog.name} maxLength={60} onChange={(e) => setFolderDialog({ ...folderDialog, name: e.target.value })} /></Field>
            {err && <p className="text-sm text-danger">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setFolderDialog(null)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={!folderDialog.name.trim()}>{folderDialog.id ? "Save" : "Create"}</button>
            </div>
          </form>
        </Modal>
      )}
      {node}
    </div>
  );
}
