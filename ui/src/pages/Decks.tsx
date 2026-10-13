import { useEffect, useState } from "react";
import { IconAlertTriangle, IconCheck, IconPlus } from "@tabler/icons-react";
import { api, eur, img } from "../api";
import { DeckInfo, FORMATS, Format, Legality } from "../decks";
import { Field, Modal } from "../components/ui";
import Deck from "./Deck";

const label = (f: string) => f[0].toUpperCase() + f.slice(1);

function Seal({ format, legality }: { format: Format; legality?: Legality }) {
  if (format === "casual" || !legality) return null;
  const errors = legality.problems.filter((p) => p.severity === "error").length;
  return errors ? (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-danger" title={legality.problems.map((p) => p.message).join("\n")}>
      <IconAlertTriangle className="size-3.5" aria-hidden />{errors} {errors === 1 ? "issue" : "issues"}
    </span>
  ) : <span className="inline-flex items-center gap-1 text-xs font-medium text-ok"><IconCheck className="size-3.5" aria-hidden />Legal</span>;
}

export default function Decks() {
  const [open, setOpen] = useState<number | null>(null);
  const [decks, setDecks] = useState<DeckInfo[] | null>(null);
  const [legal, setLegal] = useState<Record<number, Legality>>({});
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [format, setFormat] = useState<Format>("commander");
  const [err, setErr] = useState("");

  const load = () => api<DeckInfo[]>("/decks").then((d) => {
    setDecks(d);
    d.filter((x) => x.format !== "casual").forEach((x) => api<Legality>(`/decks/${x.id}/legality`).then((l) => setLegal((m) => ({ ...m, [x.id]: l }))).catch(() => {}));
  }).catch((e) => setErr(e.message));
  useEffect(() => { if (open === null) load(); }, [open]);

  if (open !== null) return <Deck id={open} onBack={() => setOpen(null)} />;

  const create = async () => {
    try {
      const { id } = await api<{ id: number }>("/decks", { method: "POST", body: JSON.stringify({ name, format }) });
      setCreating(false); setName(""); setOpen(id);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Decks</h1>
          {decks && <p className="mt-1 text-sm text-mute">{decks.length} {decks.length === 1 ? "deck" : "decks"}</p>}
        </div>
        <button className="btn-primary" onClick={() => { setErr(""); setCreating(true); }}><IconPlus className="size-4" />New deck</button>
      </div>
      {err && <p className="mb-4 text-sm text-danger">{err}</p>}
      {decks && decks.length === 0 && (
        <div className="rounded-2xl border border-dashed border-line p-16 text-center text-mute">No decks yet. Create one to start building.</div>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
        {decks?.map((d) => (
          <button key={d.id} onClick={() => setOpen(d.id)}
            className="group flex cursor-pointer flex-col overflow-hidden rounded-xl border border-line bg-surface text-left outline-none transition hover:border-accent hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent">
            <div className="h-36 w-full overflow-hidden bg-raised">
              {d.cover && <img src={img(d.cover, "normal")} alt="" loading="lazy" className="h-full w-full object-cover object-[50%_18%] transition group-hover:scale-[1.03]" />}
            </div>
            <div className="flex flex-col gap-1.5 p-4">
              <div className="truncate text-base font-medium leading-tight">{d.name}</div>
              <div className="flex items-center justify-between text-sm text-mute">
                <span>{label(d.format)} · {d.summary.cards} cards</span>
                <Seal format={d.format} legality={legal[d.id]} />
              </div>
              <div className="text-xs text-mute tabular-nums">
                {d.summary.missing ? <span className="text-danger">{d.summary.missing} to buy · {eur(d.summary.cost_to_complete)}</span>
                  : d.summary.cards ? <span className="text-ok">Nothing to buy</span> : "Empty"}
              </div>
            </div>
          </button>
        ))}
      </div>
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
            {err && <p className="text-sm text-danger">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setCreating(false)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={!name.trim()}>Create</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
