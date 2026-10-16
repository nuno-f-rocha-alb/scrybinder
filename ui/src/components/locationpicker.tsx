import { useEffect, useRef, useState } from "react";
import { IconChevronDown, IconStack2, IconTrash } from "@tabler/icons-react";
import type { Loc } from "../api";

const label = (l: string) => l || "(no location)";

/** Choose which locations the collection shows: none checked is all of them. The locations of decks (`deck_id`) can be chosen but not removed. */
export default function LocationPicker({ locs, value, onChange, onRemove, onMerge }: { locs: Loc[]; value: string[]; onChange: (v: string[]) => void; onRemove: (l: Loc) => void; onMerge: (names: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc, true);
    return () => { window.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc, true); };
  }, [open]);
  const toggle = (l: string) => onChange(value.includes(l) ? value.filter((x) => x !== l) : [...value, l]);
  const mergeable = value.filter((v) => locs.some((l) => l.location === v && l.deck_id === null));  // in the order they were ticked; decks keep their own
  const text = value.length === 0 ? "All locations" : value.length === 1 ? label(value[0]) : `${value.length} locations`;

  return (
    <div ref={box} className="relative">
      <button className="field flex w-auto min-w-44 cursor-pointer items-center justify-between gap-2" aria-haspopup="listbox" aria-expanded={open} aria-label={`Locations: ${text}`} onClick={() => setOpen(!open)}>
        <span className="truncate">{text}</span><IconChevronDown className="size-4 shrink-0 text-mute" aria-hidden />
      </button>
      {open && (
        <div role="group" aria-label="Locations" className="absolute left-0 top-full z-30 mt-1 max-h-[60vh] min-w-64 overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-2xl">
          <button className="flex w-full cursor-pointer items-center rounded-lg px-3 py-1.5 text-left text-sm hover:bg-raised" onClick={() => onChange([])}>
            <span className={value.length === 0 ? "font-medium text-accent" : ""}>All locations</span>
          </button>
          <div role="separator" className="my-1 h-px bg-line" />
          {locs.map((l) => (
            <div key={l.location} className="group flex items-center rounded-lg hover:bg-raised">
              <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-3 py-1.5 text-sm">
                <input type="checkbox" checked={value.includes(l.location)} onChange={() => toggle(l.location)} className="accent-[var(--color-accent)]" />
                {l.deck_id !== null && <IconStack2 className="size-3.5 shrink-0 text-accent" aria-label="Deck" />}
                <span className="min-w-0 flex-1 truncate">{label(l.location)}</span>
                <span className="shrink-0 text-xs tabular-nums text-mute">{l.cards}</span>
              </label>
              {l.deck_id === null && l.location !== "" && (
                <button className="mr-1 flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-mute opacity-0 hover:bg-line hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                  aria-label={`Delete the location ${l.location}`} onClick={() => { setOpen(false); onRemove(l); }}><IconTrash className="size-4" /></button>
              )}
            </div>
          ))}
          {mergeable.length > 1 && <>
            <div role="separator" className="my-1 h-px bg-line" />
            <button className="flex w-full cursor-pointer items-center rounded-lg px-3 py-1.5 text-left text-sm text-accent hover:bg-raised" title="Put the cards of the ticked locations into one"
              onClick={() => { setOpen(false); onMerge(mergeable); }}>Merge the {mergeable.length} ticked locations…</button>
          </>}
        </div>
      )}
    </div>
  );
}
