import { useEffect, useRef, useState } from "react";
import type { Zone } from "../goldfish";

export type Dragging = { uid: number; x: number; y: number; fx: number; fy: number; over: Zone | null; target: number | null };

/** The table card (marked `data-uid`) under the pointer, if any. */
const cardAt = (x: number, y: number): number | null => { const u = (document.elementFromPoint(x, y)?.closest("[data-uid]") as HTMLElement | null)?.dataset.uid; return u === undefined ? null : Number(u); };

const zoneAt = (x: number, y: number): Zone | null => (document.elementFromPoint(x, y)?.closest("[data-zone]") as HTMLElement | null)?.dataset.zone as Zone | undefined ?? null;

/**
 * Drag a card with the mouse or a finger (press, move, release) onto an element marked `data-zone="<zone>"`.
 * Our own pointer events instead of the browser's drag-and-drop, which does not work in every webview.
 * A press that moves less than 5 px is a plain click; after a real drag the click that follows is swallowed.
 * `start(uid)` goes on `onPointerDown`; `drag` is the card in flight (for the ghost and the highlights).
 */
export type DropAt = { x: number; y: number; fx: number; fy: number; target: number | null };  // the pointer, and where in the card it held it (fractions of the card)

export function usePointerDrag(onDrop: (uid: number, zone: Zone, at: DropAt) => void) {
  const [drag, setDrag] = useState<Dragging | null>(null);
  const drop = useRef(onDrop);
  drop.current = onDrop;
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);  // unmounting mid-drag removes the listeners

  const start = (uid: number) => (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const x0 = e.clientX, y0 = e.clientY;
    const r = e.currentTarget.getBoundingClientRect();
    const fx = r.width ? (x0 - r.left) / r.width : 0.5, fy = r.height ? (y0 - r.top) / r.height : 0.5;
    let on = false;
    const move = (ev: PointerEvent) => {
      if (!on && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 5) return;
      on = true;
      setDrag({ uid, x: ev.clientX, y: ev.clientY, fx, fy, over: zoneAt(ev.clientX, ev.clientY), target: cardAt(ev.clientX, ev.clientY) });
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
      if (z && ev instanceof PointerEvent) drop.current(uid, z, { x: ev.clientX, y: ev.clientY, fx, fy, target: cardAt(ev.clientX, ev.clientY) });
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
