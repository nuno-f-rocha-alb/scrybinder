import { Children, Fragment, ReactElement, ReactNode, isValidElement, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IconCheck, IconChevronDown } from "@tabler/icons-react";

type Opt = { value: string; label: string; disabled?: boolean };

/** The <option>s inside `children`, also through fragments and .map()s. */
function options(children: ReactNode): Opt[] {
  const out: Opt[] = [];
  Children.forEach(children, (c) => {
    if (!isValidElement(c)) return;
    const el = c as ReactElement<{ value?: string | number; disabled?: boolean; children?: ReactNode }>;
    if (el.type === Fragment) out.push(...options(el.props.children));
    else {
      const label = Children.toArray(el.props.children).join("");
      out.push({ value: String(el.props.value ?? label), label, disabled: el.props.disabled });
    }
  });
  return out;
}

/** A floating list under (or over) an element, in the app's own style: inside the window, scrolls when long, closes on Escape / outside click / scroll. */
function Popover({ anchor, onClose, className = "", children }: { anchor: HTMLElement; onClose: () => void; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current!, a = anchor.getBoundingClientRect();
    const room = window.innerHeight - a.bottom - 8, up = room < 200 && a.top > room;
    el.style.minWidth = `${Math.max(a.width, 120)}px`;
    el.style.maxHeight = `${Math.min(320, (up ? a.top : room) - 4)}px`;
    el.style.left = `${Math.max(4, Math.min(a.left, window.innerWidth - el.offsetWidth - 4))}px`;
    el.style.top = up ? `${Math.max(4, a.top - el.offsetHeight - 4)}px` : `${a.bottom + 4}px`;
  }, [anchor]);
  useEffect(() => {
    const away = (e: Event) => { if (!ref.current?.contains(e.target as Node) && !anchor.contains(e.target as Node)) onClose(); };
    const scrolled = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    window.addEventListener("mousedown", away);
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", onClose);
    return () => { window.removeEventListener("mousedown", away); window.removeEventListener("scroll", scrolled, true); window.removeEventListener("resize", onClose); };
  }, [anchor, onClose]);
  return createPortal(
    <div ref={ref} onMouseDown={(e) => e.stopPropagation()} className={`fixed z-[80] overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-2xl ${className}`}>{children}</div>, document.body);
}

type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> & { value: string | number; onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void };

/** A drop-in for <select> that opens the app's own list instead of the browser's: the same `value`, `onChange(e)` (with `e.target.value`) and <option> children. */
export function Select({ value, onChange, children, className = "", disabled, title, onClick, ...rest }: SelectProps) {
  const opts = options(children);
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(-1);
  const btn = useRef<HTMLButtonElement>(null);
  const cur = opts.find((o) => o.value === String(value));
  const choose = (o: Opt) => { setOpen(false); btn.current?.focus(); if (o.value !== String(value)) onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } } as unknown as React.ChangeEvent<HTMLSelectElement>); };
  const show = () => { setAt(opts.findIndex((o) => o.value === String(value))); setOpen(true); };
  const step = (d: number) => { let i = at; do i = (i + d + opts.length) % opts.length; while (opts[i]?.disabled && i !== at); setAt(i); };
  const keys = (e: React.KeyboardEvent) => {
    if (!open) { if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); show(); } return; }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if (e.key === "Home") { e.preventDefault(); setAt(0); }
    else if (e.key === "End") { e.preventDefault(); setAt(opts.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (opts[at] && !opts[at].disabled) choose(opts[at]); }
    else if (e.key === "Tab") setOpen(false);
  };
  useEffect(() => {  // keep the highlighted option in view
    if (open) document.querySelector<HTMLElement>("[data-sel-at='true']")?.scrollIntoView({ block: "nearest" });
  }, [open, at]);
  return (
    <>
      <button ref={btn} type="button" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-label={rest["aria-label"]} disabled={disabled} title={title}
        onClick={(e) => { onClick?.(e as unknown as React.MouseEvent<HTMLSelectElement>); if (!open) show(); else setOpen(false); }} onKeyDown={keys} onKeyUp={(e) => { if (e.key === " ") e.preventDefault(); }}  // Space would click the button again on release and close the list it just opened
        className={`${className} flex cursor-pointer items-center justify-between gap-2 text-left disabled:cursor-default disabled:opacity-50`}>
        <span className="min-w-0 flex-1 truncate">{cur?.label ?? ""}</span><IconChevronDown className="size-4 shrink-0 text-mute" aria-hidden />
      </button>
      {open && btn.current && (
        <Popover anchor={btn.current} onClose={() => setOpen(false)}>
          <div role="listbox" aria-label={rest["aria-label"]}>
            {opts.map((o, i) => (
              <div key={o.value} role="option" aria-selected={o.value === String(value)} aria-disabled={o.disabled} data-sel-at={i === at}
                onMouseEnter={() => setAt(i)} onClick={() => !o.disabled && choose(o)}
                className={`flex cursor-pointer items-center justify-between gap-4 rounded-lg px-3 py-1.5 text-sm ${i === at ? "bg-raised" : ""} ${o.disabled ? "cursor-default opacity-40" : ""} ${o.value === String(value) ? "text-accent" : ""}`}>
                <span>{o.label || " "}</span>{o.value === String(value) && <IconCheck className="size-4 shrink-0" aria-hidden />}
              </div>
            ))}
          </div>
        </Popover>
      )}
    </>
  );
}

/** A text field with suggestions in the app's own style (in place of <input list> + <datalist>): you can still type anything. */
export function Combo({ value, onChange, suggestions, className = "field", ...rest }: Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "list"> & { value: string; onChange: (v: string) => void; suggestions: string[] }) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const shown = suggestions.filter((s) => s.toLowerCase().includes(value.trim().toLowerCase()) && s !== value);
  const pick = (s: string) => { onChange(s); setOpen(false); setAt(-1); };
  return (
    <>
      <input {...rest} ref={input} className={className} value={value} autoComplete="off" role="combobox" aria-expanded={open && shown.length > 0} aria-autocomplete="list"
        onChange={(e) => { onChange(e.target.value); setOpen(true); setAt(-1); }} onFocus={() => setOpen(true)} onClick={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!open || !shown.length) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setAt((at + 1) % shown.length); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setAt((at - 1 + shown.length) % shown.length); }
          else if (e.key === "Enter" && at >= 0) { e.preventDefault(); pick(shown[at]); }
          else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
        }} />
      {open && shown.length > 0 && input.current && !rest.disabled && (
        <Popover anchor={input.current} onClose={() => setOpen(false)}>
          {shown.map((s, i) => (
            <div key={s} role="option" aria-selected={i === at} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)} onMouseEnter={() => setAt(i)}
              className={`cursor-pointer rounded-lg px-3 py-1.5 text-sm ${i === at ? "bg-raised" : ""}`}>{s}</div>
          ))}
        </Popover>
      )}
    </>
  );
}
