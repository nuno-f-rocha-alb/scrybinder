import { useEffect, useState } from "react";
import { Select } from "../components/select";
import { IconSearch } from "@tabler/icons-react";
import { api, qs, useGroup } from "../api";
import SetMissing from "../components/setmissing";

type SetRow = { code: string; name: string; released_at: string; total: number; owned: number; copies: number; percent: number; has_icon: number };

function Icon({ code, on }: { code: string; on: boolean }) {
  const url = `url(/api/seticon/${code})`;
  return on ? (
    <span aria-hidden className="block size-9 shrink-0 bg-ink/90"
      style={{ WebkitMaskImage: url, maskImage: url, WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat", WebkitMaskSize: "contain", maskSize: "contain", WebkitMaskPosition: "center", maskPosition: "center" }} />
  ) : <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-raised text-[10px] font-bold uppercase text-mute">{code}</span>;
}

export default function Sets({ onOpen }: { onOpen: (code: string, location?: string) => void }) {
  const [rows, setRows] = useState<SetRow[] | null>(null);
  const [q, setQ] = useState("");
  const [location, setLocation] = useState<string | undefined>(undefined);
  const [hideEmpty, setHideEmpty] = useState(true);
  const [group, setGroup] = useGroup();
  const [sort, setSort] = useState<"percent" | "recent" | "name">("percent");
  const [locs, setLocs] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [missing, setMissing] = useState<{ code: string; name: string } | null>(null);

  useEffect(() => { api<{ location: string }[]>("/locations").then((l) => setLocs(l.map((x) => x.location))).catch(() => {}); }, []);
  useEffect(() => {
    const t = setTimeout(() => api<SetRow[]>("/sets?" + qs({ q, location, hide_empty: hideEmpty ? "true" : "false", group: group ? "true" : "false" }))
      .then((r) => { setRows(r); setErr(""); }).catch((e) => setErr(e.message)), 150);
    return () => clearTimeout(t);
  }, [q, location, hideEmpty, group]);

  if (missing) return <SetMissing code={missing.code} name={missing.name} group={group} location={location} onBack={() => setMissing(null)} />;

  const sorted = rows && [...rows].sort((a, b) =>
    sort === "percent" ? b.percent - a.percent || b.owned - a.owned
      : sort === "recent" ? (b.released_at ?? "").localeCompare(a.released_at ?? "") : a.name.localeCompare(b.name));

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Sets</h1>
          {rows && <p className="mt-1 text-sm text-mute">{rows.length} sets · {rows.reduce((n, r) => n + r.owned, 0)} {group ? "different cards" : "different printings"}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input className="field w-56 pl-9" placeholder="Search sets…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sets" />
          </div>
          <Select className="field w-auto" value={location ?? "*"} aria-label="Location" onChange={(e) => setLocation(e.target.value === "*" ? undefined : e.target.value)}>
            <option value="*">Whole collection</option>
            {locs.map((l) => <option key={l} value={l}>{l || "(no location)"}</option>)}
          </Select>
          <Select className="field w-auto" value={sort} aria-label="Sort" onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="percent">Highest percentage</option><option value="recent">Most recent</option><option value="name">Name</option>
          </Select>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute" title="The same card with different art/frames counts as 1">
            <input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)} className="accent-[var(--color-accent)]" />Group printings
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-mute">
            <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} className="accent-[var(--color-accent)]" />Hide empty sets
          </label>
        </div>
      </div>
      {err && <p className="mb-4 text-sm text-danger">{err}</p>}
      {sorted && sorted.length === 0 && <div className="rounded-2xl border border-dashed border-line p-16 text-center text-mute">No sets to show.</div>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
        {sorted?.map((s) => (
          <div key={s.code} className="relative">
          <button onClick={() => onOpen(s.code, location)}
            className="group relative flex cursor-pointer items-center gap-3 overflow-hidden rounded-xl border border-line bg-surface px-4 pb-5 pt-3.5 text-left outline-none transition hover:border-accent hover:bg-raised focus-visible:ring-2 focus-visible:ring-accent">
            <Icon code={s.code} on={!!s.has_icon} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium leading-tight">{s.name}</div>
              <div className="mt-0.5 text-sm text-mute tabular-nums"><span className="text-ink">{s.owned}</span> / {s.total}
                {s.copies > s.owned && <span className="ml-2 text-xs">({s.copies} copies)</span>}</div>
            </div>
            <span className={`absolute bottom-1.5 right-3 text-xs font-medium tabular-nums ${s.percent >= 100 ? "text-ok" : "text-mute"}`}>{s.percent.toLocaleString(undefined)} %</span>
            <span className="absolute inset-x-0 bottom-0 h-1 bg-raised" aria-hidden>
              <span className={`block h-full ${s.percent >= 100 ? "bg-ok" : "bg-accent"}`} style={{ width: `${Math.min(100, s.percent)}%` }} />
            </span>
          </button>
          {s.owned < s.total && <button onClick={() => setMissing({ code: s.code, name: s.name })} title="The printings you do not own" className="absolute right-2 top-1.5 cursor-pointer rounded px-1.5 py-0.5 text-[11px] text-mute outline-none hover:bg-raised hover:text-ink focus-visible:ring-2 focus-visible:ring-accent">Missing</button>}
          </div>
        ))}
      </div>
    </div>
  );
}
