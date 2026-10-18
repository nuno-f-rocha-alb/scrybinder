import { useEffect, useState } from "react";
import { IconArrowLeft, IconCopy, IconDownload } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { useToast } from "./ui";

type Missing = { set_code: string; set_name: string; missing: { scryfall_id: string; name: string; collector_number: string; rarity: string; price: number | null }[]; count: number; total_price: number };

/** The printings of one set that you do not own, with what it costs to complete the set. */
export default function SetMissing({ code, name, group, location, onBack }: { code: string; name: string; group: boolean; location?: string; onBack: () => void }) {
  const [data, setData] = useState<Missing | null>(null);
  const [err, setErr] = useState("");
  const { toast, node } = useToast();
  const params = (format?: string) => qs({ group: group ? "true" : "false", location, format });
  useEffect(() => { api<Missing>(`/sets/${code}/missing?${params()}`).then(setData).catch((e) => setErr(e.message)); }, [code, group, location]); // eslint-disable-line react-hooks/exhaustive-deps

  const url = (format: string) => `/api/sets/${code}/missing?${params(format)}`;
  const copy = () => fetch(url("text")).then((r) => r.text()).then((t) => navigator.clipboard.writeText(t)).then(() => toast("Copied")).catch(() => toast("Could not copy", true));
  // In the app window a native Save dialog (pywebview bridge); in a plain browser the normal download.
  const csv = async () => {
    const bridge = (window as { pywebview?: { api?: { save_csv?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    if (!bridge?.save_csv) { window.location.assign(url("csv")); return; }
    try {
      const r = await fetch(url("csv"));
      if (!r.ok) throw new Error(r.statusText);
      const path = await bridge.save_csv(`scrybinder-missing-${code}.csv`, await r.text());
      if (path) toast(`Saved to ${path}`);
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <button className="btn-ghost mb-2" onClick={onBack}><IconArrowLeft className="size-4" />Sets</button>
          <h1 className="text-2xl font-semibold tracking-tight">Missing from {name}</h1>
          {data && <p className="mt-1 text-sm text-mute">{data.count} {group ? (data.count === 1 ? "card" : "cards") : (data.count === 1 ? "printing" : "printings")} · about {eur(data.total_price)} to complete{location !== undefined ? ` · in ${location || "(no location)"}` : ""}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={copy} disabled={!data?.count}><IconCopy className="size-4" />Copy as text</button>
          <button className="btn-ghost" onClick={csv} disabled={!data?.count}><IconDownload className="size-4" />Download CSV</button>
        </div>
      </div>
      {err && <p className="mb-4 text-sm text-danger">{err}</p>}
      {!data && !err && <p className="text-mute">Loading…</p>}
      {data && !data.count && <p className="text-mute">You own every {group ? "card" : "printing"} of this set.</p>}
      {data && data.count > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-mute">
            <th className="py-2 pr-3 font-medium">Card</th><th className="px-3 font-medium">Number</th><th className="px-3 font-medium">Rarity</th><th className="pl-3 text-right font-medium">Price</th>
          </tr></thead>
          <tbody>
            {data.missing.map((m) => (
              <tr key={m.scryfall_id} className="border-b border-line/60">
                <td className="py-1.5 pr-3">{m.name}</td><td className="px-3 text-mute">#{m.collector_number}</td>
                <td className="px-3 capitalize text-mute">{m.rarity}</td><td className="pl-3 text-right">{eur(m.price)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td colSpan={3} className="pt-3 text-right font-medium">Total</td><td className="pt-3 text-right font-medium">{eur(data.total_price)}</td></tr></tfoot>
        </table>
      )}
      {node}
    </div>
  );
}
