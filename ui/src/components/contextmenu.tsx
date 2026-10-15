import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cardmarketUrl, openExternal, scryfallUrl } from "./ui";

export type MenuItem = "sep" | { label: string; onSelect: () => void; hint?: string; danger?: boolean; disabled?: boolean };
type Open = { x: number; y: number; items: MenuItem[] };

/** The items every card menu ends with: copy the name and open the printing on Scryfall (and Cardmarket when it has a product). */
export function nameAndLinks(name: string, printId: string | null | undefined, cardmarketId: number | null | undefined, toast: (m: string, err?: boolean) => void): MenuItem[] {
  return [
    { label: "Copy card name", onSelect: () => navigator.clipboard.writeText(name).then(() => toast("Name copied")).catch(() => toast("Could not copy", true)) },
    ...(printId ? ["sep" as const, { label: "Open on Scryfall", onSelect: () => openExternal(scryfallUrl(printId)) }] : []),
    ...(cardmarketId ? [{ label: "Open on Cardmarket", onSelect: () => openExternal(cardmarketUrl(cardmarketId)) }] : []),
  ];
}

/** A right-click menu (also Shift+F10 / the menu key): `open(event, items)` from an `onContextMenu`, and render `node` once. */
export function useContextMenu() {
  const [m, setM] = useState<Open | null>(null);
  const open = useCallback((e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault();
    e.stopPropagation();
    setM({ x: e.clientX, y: e.clientY, items });
  }, []);
  const close = useCallback(() => setM(null), []);
  const node = m ? <Menu m={m} onClose={close} /> : null;
  return { open, node };
}

function Menu({ m, onClose }: { m: Open; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const back = useRef<Element | null>(document.activeElement);  // focus goes back there when the menu closes

  useLayoutEffect(() => {  // keep it inside the window, whatever the edge it was opened near; before it is painted and before it takes focus
    const el = ref.current!;
    el.style.maxHeight = `${window.innerHeight - 8}px`;  // a menu taller than the window scrolls inside itself
    const r = el.getBoundingClientRect();
    el.style.left = `${Math.max(4, Math.min(m.x, window.innerWidth - r.width - 4))}px`;
    el.style.top = `${Math.max(4, Math.min(m.y, window.innerHeight - r.height - 4))}px`;
    el.querySelector<HTMLElement>("button:not(:disabled)")?.focus({ preventScroll: true });  // focusing must not scroll the page: that closes the menu
  }, [m]);
  useEffect(() => {
    const out = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    window.addEventListener("mousedown", out);
    window.addEventListener("contextmenu", out, true);
    const scrolled = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(); };  // the page moved under it; its own scroll does not count
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", onClose);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("mousedown", out); window.removeEventListener("contextmenu", out, true);
      window.removeEventListener("scroll", scrolled, true); window.removeEventListener("resize", onClose); window.removeEventListener("blur", onClose);
    };
  }, [onClose]);
  useEffect(() => () => (back.current as HTMLElement | null)?.focus?.(), []);

  const keys = (e: React.KeyboardEvent) => {
    const btns = [...ref.current!.querySelectorAll<HTMLElement>("button:not(:disabled)")];
    const i = btns.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); btns[(i + 1) % btns.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length]?.focus(); }
    else if (e.key === "Home") { e.preventDefault(); btns[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); btns[btns.length - 1]?.focus(); }
    else if (e.key === "Tab") { e.preventDefault(); onClose(); }
  };

  return createPortal(
    <div ref={ref} role="menu" onKeyDown={keys} style={{ left: m.x, top: m.y }} onContextMenu={(e) => e.preventDefault()}
      className="fixed z-[70] min-w-[220px] max-w-[320px] overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-2xl">
      {m.items.map((it, i) => it === "sep"
        ? <div key={i} role="separator" className="my-1 h-px bg-line" />
        : <button key={i} role="menuitem" disabled={it.disabled} onClick={() => { onClose(); it.onSelect(); }}
            className={`flex w-full cursor-pointer items-center justify-between gap-6 rounded-lg px-3 py-1.5 text-left text-sm outline-none focus-visible:bg-raised enabled:hover:bg-raised disabled:cursor-default disabled:opacity-40 ${it.danger ? "text-danger" : ""}`}>
            <span>{it.label}</span>{it.hint && <span className="text-xs text-mute">{it.hint}</span>}
          </button>)}
    </div>, document.body);
}
