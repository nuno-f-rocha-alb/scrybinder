import { useEffect, useState } from "react";
import { IconArrowLeft, IconCopy, IconDownload } from "@tabler/icons-react";
import { api, eur, qs } from "../api";
import { useToast } from "./ui";

type Item = { id: number; name: string; set_code: string | null; collector_number: string | null; finish: string; condition: string; location: string; spare: number; price: number | null; line_value: number };
type Spare = { items: Item[]; total_spare: number; total_value: number };

/** Copies that are in no deck: the trade binder. Hold back some copies of each card with "keep". */
export default function SpareCards({ onBack }: { onBack: () => void }) {
  const [keep, setKeep] = useState(0);
  const [data, setData] = useState<Spare | null>(null);
  const [err, setErr] = useState("");
  const { toast, node } = useToast();
  useEffect(() => {
    let live = true;  // a slower earlier answer must not replace a newer one
    api<Spare>(`/collection/spare?${qs({ keep })}`).then((d) => { if (live) { setData(d); setErr(""); } }).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [keep]);

  const url = (format: string) => `/api/collection/spare?${qs({ keep, format })}`;
  const copy = () => fetch(url("text")).then((r) => r.text()).then((t) => navigator.clipboard.writeText(t)).then(() => toast("Copied")).catch(() => toast("Could not copy", true));
  // In the app window a native Save dialog (pywebview bridge); in a plain browser the normal download.
  const csv = async () => {
    const bridge = (window as { pywebview?: { api?: { save_csv?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    if (!bridge?.save_csv) { window.location.assign(url("csv")); return; }
    try {
      const r = await fetch(url("csv"));
      if (!r.ok) throw new Error(r.statusText);
      const path = await bridge.save_csv("scrybinder-spare-cards.csv", await r.text());
      if (path) toast(`Saved to ${path}`);
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <button className="btn-ghost mb-2" onClick={onBack}><IconArrowLeft className="size-4" />Collection</button>
          <h1 className="text-2xl font-semibold tracking-tight">Spare cards</h1>
          {data && <p className="mt-1 text-sm text-mute">{data.total_spare} {data.total_spare === 1 ? "copy" : "copies"} in no deck · about {eur(data.total_value)}</p>}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-medium text-mute">Keep of each card
            <input type="number" min={0} max={99} value={keep} onChange={(e) => setKeep(Math.max(0, Math.floor(Number(e.target.value)) || 0))} className="field mt-1 block w-24" aria-label="Copies of each card to keep" /></label>
          <button className="btn-ghost" onClick={copy} disabled={!data?.items.length}><IconCopy className="size-4" />Copy as text</button>
          <button className="btn-ghost" onClick={csv} disabled={!data?.items.length}><IconDownload className="size-4" />Download CSV</button>
        </div>
      </div>
      {err && <p className="mb-4 text-sm text-danger">{err}</p>}
      {!data && !err && <p className="text-mute">Loading…</p>}
      {data && !data.items.length && <p className="text-mute">{keep ? "Nothing is spare once you keep that many of each card." : "Every copy you own is in a deck."}</p>}
      {data && data.items.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-mute">
            <th className="py-2 pr-3 font-medium">Card</th><th className="px-3 font-medium">Printing</th><th className="px-3 font-medium">Location</th>
            <th className="px-3 font-medium">Spare</th><th className="px-3 text-right font-medium">Price</th><th className="pl-3 text-right font-medium">Total</th>
          </tr></thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.id} className="border-b border-line/60">
                <td className="py-1.5 pr-3">{i.name}</td>
                <td className="px-3 text-mute">{(i.set_code ?? "").toUpperCase()} #{i.collector_number}{i.finish !== "nonfoil" ? ` · ${i.finish}` : ""}</td>
                <td className="px-3 text-mute">{i.location || "—"}</td>
                <td className="px-3">{i.spare}</td>
                <td className="px-3 text-right">{eur(i.price)}</td>
                <td className="pl-3 text-right">{eur(i.line_value)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td colSpan={5} className="pt-3 text-right font-medium">Total</td><td className="pt-3 text-right font-medium">{eur(data.total_value)}</td></tr></tfoot>
        </table>
      )}
      {node}
    </div>
  );
}
