import { useEffect, useState } from "react";
import { api, eur } from "../api";

type Snap = { date: string; total_value: number; total_cards: number };

/** The collection's value after each price refresh: a small line and the last few days. Hidden until the first refresh has been noted. */
export default function ValueHistory({ current }: { current: number | undefined }) {
  const [snaps, setSnaps] = useState<Snap[] | null>(null);
  useEffect(() => { api<{ snapshots: Snap[] }>("/collection/value-history").then((r) => setSnaps(r.snapshots)).catch(() => setSnaps([])); }, [current]);
  if (snaps === null) return null;
  const vals = snaps.map((s) => s.total_value), lo = Math.min(...vals), hi = Math.max(...vals);
  const pts = snaps.map((s, i) => `${snaps.length > 1 ? (i / (snaps.length - 1)) * 200 : 100},${hi === lo ? 20 : 36 - ((s.total_value - lo) / (hi - lo)) * 32}`).join(" ");
  return (
    <details className="mt-1 text-sm">
      <summary className="cursor-pointer text-mute outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-accent">Value over time</summary>
      {snaps.length === 0
        ? <p className="mt-2 max-w-md text-mute">Nothing noted yet: the value is saved each time the card prices are updated in Settings.</p>
        : (
          <div className="mt-2 flex flex-wrap items-center gap-6 rounded-xl border border-line bg-surface p-3">
            <svg viewBox="0 0 200 40" className="h-12 w-52 text-gold" role="img" aria-label={`Collection value from ${eur(vals[0])} to ${eur(vals[vals.length - 1])}`}>
              {snaps.length > 1 ? <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="2" /> : <circle cx="100" cy="20" r="3" fill="currentColor" />}
            </svg>
            <table className="tabular-nums">
              <tbody>{snaps.slice(-6).reverse().map((s) => (
                <tr key={s.date}><td className="pr-4 text-mute">{s.date}</td><td className="pr-4 text-right">{eur(s.total_value)}</td><td className="text-right text-mute">{s.total_cards} {s.total_cards === 1 ? "card" : "cards"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
    </details>
  );
}
