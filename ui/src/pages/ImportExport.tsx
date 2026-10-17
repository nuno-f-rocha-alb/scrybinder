import { useEffect, useState } from "react";
import { Combo, Select } from "../components/select";
import { IconDownload, IconUpload } from "@tabler/icons-react";
import { api, qs } from "../api";
import { useToast } from "../components/ui";

type Result = { imported: number; cards: number; skipped: [number, string][] };
const FORMATS = [
  { id: "manabox", name: "ManaBox", note: "Lossless round trip: keeps ids, condition, flags and dates." },
  { id: "moxfield", name: "Moxfield", note: "Collection CSV; the location goes into the Tags column." },
  { id: "cardmarket", name: "Cardmarket", note: "Stock list by cardmarketId; current price from the bulk data (EUR). Cards without a cardmarketId or with a language that has no Cardmarket code are left out." },
];

export default function ImportExport() {
  const [file, setFile] = useState<File | null>(null);
  const [loc, setLoc] = useState("");
  const [fmt, setFmt] = useState<"manabox" | "moxfield">("manabox");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [exportLoc, setExportLoc] = useState<string | undefined>(undefined);
  const [locs, setLocs] = useState<string[]>([]);
  const { toast, node } = useToast();
  useEffect(() => { api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location))); }, []);

  const pick = (f: File | null) => {
    setFile(f); setRes(null);
    if (f && !loc) setLoc(f.name.replace(/\.csv$/i, "").replace(/\b\w/g, (c) => c.toUpperCase()));
  };
  // In the app window a native Save dialog (pywebview bridge); in a plain browser the normal download.
  const exportCsv = async (id: string) => {
    const bridge = (window as { pywebview?: { api?: { save_csv?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    if (!bridge?.save_csv) { window.location.assign(`/api/export/${id}?${qs({ location: exportLoc })}`); return; }
    try {
      const r = await fetch(`/api/export/${id}?${qs({ location: exportLoc })}`);
      if (!r.ok) throw new Error(r.statusText);
      const path = await bridge.save_csv(`scrybinder-${id}.csv`, await r.text());
      if (path) toast(`Saved to ${path}`);
    } catch (e) { toast((e as Error).message, true); }
  };
  const run = async () => {
    if (!file) return;
    setBusy(true);
    try {
      setRes(await api<Result>(`/import/${fmt}?` + qs({ location: loc }), { method: "POST", headers: { "Content-Type": "text/csv" }, body: await file.text() }));
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-10">
      <section>
        <h1 className="mb-1 text-2xl font-semibold tracking-tight">Import</h1>
        <p className="mb-4 max-w-2xl text-sm text-mute">{fmt === "manabox"
          ? <>Choose the CSV exported from ManaBox. Cards are linked by <code>scryfall_id</code>, so the exact printing is kept.</>
          : <>Choose the collection CSV exported from Moxfield. It has no <code>scryfall_id</code>, so cards are matched by edition and collector number.</>} Importing the same file twice adds the quantities up.</p>
        <div className="flex max-w-2xl flex-wrap items-end gap-3 rounded-2xl border border-line bg-surface p-4">
          <Select className="field w-auto" value={fmt} onChange={(e) => { setFmt(e.target.value as typeof fmt); setRes(null); }} aria-label="Import format">
            <option value="manabox">ManaBox</option><option value="moxfield">Moxfield</option></Select>
          <label className="btn-ghost cursor-pointer"><IconUpload className="size-4" />{file ? file.name : "Choose CSV file"}
            <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => pick(e.target.files?.[0] ?? null)} /></label>
          <div className="min-w-48 flex-1"><span className="mb-1 block text-xs font-medium text-mute">Location for the imported cards</span>
            <Combo className="field" suggestions={locs.filter(Boolean)} value={loc} onChange={setLoc} placeholder="e.g. Red boxes" /></div>
          <button className="btn-primary" disabled={!file || busy} onClick={run}>{busy ? "Importing…" : "Import"}</button>
        </div>
        {res && (
          <div className="mt-4 max-w-2xl rounded-2xl border border-line bg-surface p-4 text-sm" role="status">
            <p className="text-ok">Imported <b>{res.cards}</b> cards in {res.imported} rows.</p>
            {res.skipped.length > 0 && (
              <details className="mt-2" open><summary className="cursor-pointer text-gold">{res.skipped.length} rows skipped</summary>
                <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs text-mute">{res.skipped.map(([n, m]) => <li key={n}>row {n}: {m}</li>)}</ul></details>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-1 text-2xl font-semibold tracking-tight">Export</h2>
        <div className="mb-4 flex items-center gap-2 text-sm text-mute">Location:
          <Select className="field w-auto" value={exportLoc ?? "*"} onChange={(e) => setExportLoc(e.target.value === "*" ? undefined : e.target.value)}>
            <option value="*">Whole collection</option>
            {locs.map((l) => <option key={l} value={l}>{l || "(no location)"}</option>)}
          </Select></div>
        <div className="grid max-w-4xl gap-4 sm:grid-cols-3">
          {FORMATS.map((f) => (
            <button key={f.id} type="button" onClick={() => exportCsv(f.id)}
              className="group flex cursor-pointer flex-col gap-2 rounded-2xl border border-line bg-surface p-4 text-left transition hover:border-accent hover:bg-raised">
              <span className="flex items-center justify-between text-lg font-semibold">{f.name}<IconDownload className="size-5 text-mute group-hover:text-accent" /></span>
              <span className="text-xs text-mute">{f.note}</span>
            </button>
          ))}
        </div>
      </section>
      {node}
    </div>
  );
}
