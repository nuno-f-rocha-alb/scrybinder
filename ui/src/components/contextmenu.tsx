import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
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

/** A short note in app.log about what the menu did (when it opened and why it closed), with the time on this side and the window numbers. */
function uiLog(body: Record<string, string | number | boolean | undefined>) {
  api("/ui-log", { method: "POST", body: JSON.stringify({ at: new Date().toISOString(), vh: window.innerHeight, vw: window.innerWidth, ...body }) }).catch(() => {});
}

/** A right-click menu (also Shift+F10 / the menu key): `open(event, items)` from an `onContextMenu`, and render `node` once. */
export function useContextMenu() {
  const [m, setM] = useState<Open | null>(null);
  const open = useCallback((e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault();
    e.stopPropagation();
    setM({ x: e.clientX, y: e.clientY, items });
    const row = e.currentTarget as HTMLElement;
    uiLog({ event: "menu-open", x: e.clientX, y: e.clientY, row: (row.innerText ?? "").replace(/\s+/g, " ").slice(0, 40), top: Math.round(row.getBoundingClientRect().top),
      left: Math.round(row.getBoundingClientRect().left), items: items.length, main: Math.round(document.querySelector("main")?.scrollTop ?? -1) });
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
    // Something outside the menu that happens in the first instants after it opened is not the user closing it (a second contextmenu event,
    // a layout scroll, a focus change of the host window): it is ignored, and written to app.log so it can be found out what it was.
    const opened = performance.now();
    const note = (what: string, reason: string, e: Event) => {
      const ms = Math.round(performance.now() - opened), t = e.target as HTMLElement | null;
      if (ms < 3000) uiLog({ event: `menu-${what}`, reason, ms, target: t?.tagName ?? String(t), cls: String(t?.className ?? "").slice(0, 60), x: m.x, y: m.y, h: ref.current?.offsetHeight });
    };
    const dismiss = (reason: string, grace: number) => (e: Event) => {
      if (ref.current?.contains(e.target as Node)) return;  // inside the menu (its own scroll, a click on it) does not count
      if (performance.now() - opened < grace) { note("ignored", reason, e); return; }
      note("closed", reason, e);
      onClose();
    };
    const out = dismiss("mousedown", 250), ctx = dismiss("contextmenu", 250), scrolled = dismiss("scroll", 400), resized = dismiss("resize", 400), blurred = dismiss("blur", 400);
    window.addEventListener("mousedown", out);
    window.addEventListener("contextmenu", ctx, true);
    window.addEventListener("scroll", scrolled, true);  // the page moved under it
    window.addEventListener("resize", resized);
    window.addEventListener("blur", blurred);
    return () => {
      window.removeEventListener("mousedown", out); window.removeEventListener("contextmenu", ctx, true);
      window.removeEventListener("scroll", scrolled, true); window.removeEventListener("resize", resized); window.removeEventListener("blur", blurred);
    };
  }, [onClose, m]);
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
