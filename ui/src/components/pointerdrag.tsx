import { useEffect, useRef, useState } from "react";
import type { Zone } from "../goldfish";

export type Dragging = { uid: number; x: number; y: number; over: Zone | null };

const zoneAt = (x: number, y: number): Zone | null => (document.elementFromPoint(x, y)?.closest("[data-zone]") as HTMLElement | null)?.dataset.zone as Zone | undefined ?? null;

/**
 * Drag a card with the mouse or a finger (press, move, release) onto an element marked `data-zone="<zone>"`.
 * Our own pointer events instead of the browser's drag-and-drop, which does not work in every webview.
 * A press that moves less than 5 px is a plain click; after a real drag the click that follows is swallowed.
 * `start(uid)` goes on `onPointerDown`; `drag` is the card in flight (for the ghost and the highlights).
 */
export function usePointerDrag(onDrop: (uid: number, zone: Zone) => void) {
  const [drag, setDrag] = useState<Dragging | null>(null);
  const drop = useRef(onDrop);
  drop.current = onDrop;
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);  // unmounting mid-drag removes the listeners

  const start = (uid: number) => (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const x0 = e.clientX, y0 = e.clientY;
    let on = false;
    const move = (ev: PointerEvent) => {
      if (!on && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 5) return;
      on = true;
      setDrag({ uid, x: ev.clientX, y: ev.clientY, over: zoneAt(ev.clientX, ev.clientY) });
    };
    const finish = (ev: PointerEvent | KeyboardEvent, release: boolean) => {
      if (ev instanceof KeyboardEvent && ev.key !== "Escape") return;
      cleanup();
      if (!on) return;
      const swallow = (c: Event) => { c.stopPropagation(); c.preventDefault(); };
      window.addEventListener("click", swallow, { capture: true, once: true });
      setTimeout(() => window.removeEventListener("click", swallow, { capture: true }), 100);  // no click came (released elsewhere)
      setDrag(null);
      const z = release && ev instanceof PointerEvent ? zoneAt(ev.clientX, ev.clientY) : null;
      if (z) drop.current(uid, z);
    };
    const up = (ev: PointerEvent) => finish(ev, true);
    const cancel = (ev: PointerEvent) => finish(ev, false);
    const key = (ev: KeyboardEvent) => finish(ev, false);
    const cleanup = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel); window.removeEventListener("keydown", key);
      stop.current = null;
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel); window.addEventListener("keydown", key);
    stop.current = () => { cleanup(); setDrag(null); };
  };
  return { drag, start };
}
