import { useEffect, useState } from "react";
import { IconArrowLeft, IconCopy, IconDownload } from "@tabler/icons-react";
import { api, eur } from "../api";
import { useToast } from "./ui";

type Item = { oracle_id: string; name: string; needed: number; price: number | null; line_total: number; decks: { deck_id: number; name: string; needed: number }[] };
type List = { items: Item[]; total_needed: number; total_value: number };

/** What is still missing across every deck: a table, a text list to paste into Cardmarket's want list, and a CSV. */
export default function ShoppingList({ onBack }: { onBack: () => void }) {
  const [list, setList] = useState<List | null>(null);
  const [err, setErr] = useState("");
  const { toast, node } = useToast();
  useEffect(() => { api<List>("/decks/shopping-list").then(setList).catch((e) => setErr(e.message)); }, []);

  const copy = () => fetch("/api/decks/shopping-list?format=text").then((r) => r.text()).then((t) => navigator.clipboard.writeText(t))
    .then(() => toast("Copied")).catch(() => toast("Could not copy", true));
  // In the app window a native Save dialog (pywebview bridge); in a plain browser the normal download.
  const csv = async () => {
    const bridge = (window as { pywebview?: { api?: { save_csv?: (n: string, t: string) => Promise<string | null> } } }).pywebview?.api;
    if (!bridge?.save_csv) { window.location.assign("/api/decks/shopping-list?format=csv"); return; }
    try {
      const r = await fetch("/api/decks/shopping-list?format=csv");
      if (!r.ok) throw new Error(r.statusText);
      const path = await bridge.save_csv("scrybinder-shopping-list.csv", await r.text());
      if (path) toast(`Saved to ${path}`);
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <button className="btn-ghost mb-2" onClick={onBack}><IconArrowLeft className="size-4" />Decks</button>
          <h1 className="text-2xl font-semibold tracking-tight">Shopping list</h1>
          {list && <p className="mt-1 text-sm text-mute">{list.total_needed} {list.total_needed === 1 ? "card" : "cards"} missing across your decks · about {eur(list.total_value)}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={copy} disabled={!list?.items.length}><IconCopy className="size-4" />Copy as text</button>
          <button className="btn-ghost" onClick={csv} disabled={!list?.items.length}><IconDownload className="size-4" />Download CSV</button>
        </div>
      </div>
      {err && <p className="mb-4 text-sm text-danger">{err}</p>}
      {!list && !err && <p className="text-mute">Loading…</p>}
      {list && !list.items.length && <p className="text-mute">Nothing to buy: every card of every deck is in your collection.</p>}
      {list && list.items.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-mute">
            <th className="py-2 pr-3 font-medium">Card</th><th className="px-3 font-medium">Needed</th><th className="px-3 font-medium">Decks</th>
            <th className="px-3 text-right font-medium">Price</th><th className="pl-3 text-right font-medium">Total</th>
          </tr></thead>
          <tbody>
            {list.items.map((i) => (
              <tr key={i.oracle_id} className="border-b border-line/60">
                <td className="py-1.5 pr-3">{i.name}</td>
                <td className="px-3">{i.needed}</td>
                <td className="px-3 text-mute">{i.decks.map((d) => `${d.name}${d.needed > 1 ? ` ×${d.needed}` : ""}`).join(", ")}</td>
                <td className="px-3 text-right">{eur(i.price)}</td>
                <td className="pl-3 text-right">{eur(i.line_total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td colSpan={4} className="pt-3 text-right font-medium">Total</td><td className="pt-3 text-right font-medium">{eur(list.total_value)}</td></tr></tfoot>
        </table>
      )}
      {node}
    </div>
  );
}
