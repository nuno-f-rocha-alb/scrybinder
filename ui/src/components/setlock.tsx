import { useEffect, useState } from "react";
import { IconLock, IconX } from "@tabler/icons-react";
import { api } from "../api";
import { Combo } from "./select";

type SetInfo = { code: string; name: string; released_at: string | null };
const label = (s: SetInfo) => `${s.code.toUpperCase()} · ${s.name}`;

/** Limits the scan to printings of the chosen sets (none chosen: any set). */
export default function SetLock({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [all, setAll] = useState<SetInfo[]>([]);
  const [text, setText] = useState("");
  useEffect(() => { api<SetInfo[]>("/sets?hide_empty=false").then((r) => setAll([...r].sort((a, b) => (b.released_at ?? "").localeCompare(a.released_at ?? "")))).catch(() => {}); }, []);
  const add = (s: string) => {
    const hit = all.find((x) => label(x) === s);
    if (hit && !value.includes(hit.code)) onChange([...value, hit.code]);
    setText("");
  };
  return (
    <div className="rounded-xl border border-line bg-surface p-3 text-sm">
      <div className="mb-1 flex items-center gap-2 font-medium"><IconLock className="size-4" />Only these sets</div>
      <div className="flex flex-wrap gap-1">
        {value.map((c) => (
          <span key={c} className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 text-xs text-accent">
            {all.find((x) => x.code === c)?.name ?? c.toUpperCase()}
            <button aria-label={`Remove ${c.toUpperCase()}`} className="cursor-pointer" onClick={() => onChange(value.filter((x) => x !== c))}><IconX className="size-3" /></button>
          </span>
        ))}
      </div>
      <Combo className="field mt-2" value={text} placeholder="Add a set: name or code (e.g. PLST)" aria-label="Add a set to the lock"
        suggestions={all.filter((x) => !value.includes(x.code)).map(label)}
        onChange={(v) => { if (all.some((x) => label(x) === v)) add(v); else setText(v); }} />
      <p className="mt-2 text-xs text-mute">{value.length
        ? "The scan only names printings from these sets; a card with none there comes out as not recognised."
        : "Leave empty to recognise any set. Choose some (e.g. PLST, The List) to ignore the other printings of each card."}</p>
    </div>
  );
}
