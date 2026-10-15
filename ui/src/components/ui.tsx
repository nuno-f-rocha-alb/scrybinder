import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, img } from "../api";

/** Shows `zoom` (a big version of the card image) next to the pointer while it is over `children`. Mouse only: touch has no hover. */
export function HoverZoom({ children, zoom, className = "" }: { children: React.ReactNode; zoom: React.ReactNode; className?: string }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const move = (e: { clientX: number; clientY: number }) => { if (window.matchMedia("(hover: hover)").matches) setAt({ x: e.clientX, y: e.clientY }); };
  const W = 320, H = Math.round((W * 88) / 63);  // the preview box: card proportions
  let left = 0, top = 0;
  if (at) {
    left = at.x + 24 + W > window.innerWidth ? at.x - 24 - W : at.x + 24;  // flip to the left near the right edge
    top = Math.min(Math.max(8, at.y - H / 2), Math.max(8, window.innerHeight - H - 8));
  }
  return (
    <div className={className} onMouseEnter={move} onMouseMove={move} onMouseLeave={() => setAt(null)}>
      {children}
      {at && createPortal(
        <div className="pointer-events-none fixed z-[60] overflow-hidden rounded-[4.5%] shadow-[0_16px_48px_rgba(0,0,0,0.7)] ring-1 ring-line" style={{ left, top, width: W, height: H }}>{zoom}</div>,
        document.body)}
    </div>
  );
}

export function CardImg({ id, size = "normal", className = "" }: { id: string; size?: "small" | "normal" | "large"; className?: string }) {
  const [tries, setTries] = useState(0);
  useEffect(() => setTries(0), [id, size]); // another card in the same component: start over
  const ok = tries < 3;
  // transient network failures: retry (the server retries too) before giving up
  const retry = () => setTimeout(() => setTries((t) => t + 1), 1200 * (tries + 1));
  return ok ? (
    <img key={tries} src={img(id, size) + (tries ? `&r=${tries}` : "")} alt="" loading="lazy" decoding="async" onError={retry}
      className={`aspect-[63/88] w-full rounded-[4.5%] bg-raised object-cover ${className}`} />
  ) : (
    <div className={`flex aspect-[63/88] w-full items-center justify-center rounded-[4.5%] bg-raised text-xs text-mute ${className}`}>no image</div>
  );
}

/** Opens a link in the system browser (inside the app window it must not navigate; the server only accepts Scryfall and Cardmarket). */
export function openExternal(url: string) {
  api("/open-url", { method: "POST", body: JSON.stringify({ url }) }).catch(() => window.open(url, "_blank", "noopener"));
}
export const scryfallUrl = (id: string) => `https://scryfall.com/card/${id}`;
export const cardmarketUrl = (idProduct: number) => `https://www.cardmarket.com/en/Magic/Products?idProduct=${idProduct}`;

/** Links to visually confirm the printing: Scryfall (by id) and Cardmarket (by idProduct, when it exists). */
export function ExtLinks({ id, cardmarketId }: { id: string; cardmarketId?: number | null }) {
  const open = (url: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    openExternal(url);
  };
  const sf = scryfallUrl(id), cm = cardmarketId ? cardmarketUrl(cardmarketId) : null;
  return (
    <span className="flex gap-3 text-xs">
      <a href={sf} target="_blank" rel="noreferrer" onClick={open(sf)} className="text-accent hover:underline">Scryfall ↗</a>
      {cm && <a href={cm} target="_blank" rel="noreferrer" onClick={open(cm)} className="text-accent hover:underline">Cardmarket ↗</a>}
    </span>
  );
}

/** Side panel on the right over the main area, with no background of its own: the other cards stay behind, blurred; the left
 * menu stays visible and clickable (mounted in #drawer-root, which only covers the main area). */
export function Drawer({ onClose, title, children }: { onClose: () => void; title: string; children: React.ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const root = document.getElementById("drawer-root");
  if (!root) return <Modal onClose={onClose} title={title}>{children}</Modal>;
  return createPortal(
    <div className="pointer-events-auto absolute inset-0 flex justify-end bg-black/50 backdrop-blur-sm" onMouseDown={onClose}>
      {/* the panel itself is click-through: only the card and the fields box (<Hit>) receive clicks; anywhere else closes it */}
      <aside role="dialog" aria-modal aria-label={title} className="drawer-in pointer-events-none h-full w-[min(740px,96%)] overflow-y-auto p-4 sm:p-6">
        {children}
      </aside>
    </div>, root);
}

/** Part of the panel that receives clicks without closing it. */
export function Hit({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`pointer-events-auto ${className}`} onMouseDown={(e) => e.stopPropagation()}>{children}</div>;
}

export function Modal({ onClose, title, children, wide }: { onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div role="dialog" aria-modal aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className={`max-h-[92vh] w-full ${wide ? "max-w-5xl" : "max-w-3xl"} overflow-y-auto rounded-2xl border border-line bg-surface p-6 shadow-2xl`}>
        {children}
      </div>
    </div>
  );
}

/** "Foil" / "Etched" on a card that is wanted in that finish (nothing for non-foil, as in the collection). */
export function FinishTag({ finish }: { finish?: string | null }) {
  return finish === "foil" || finish === "etched" ? <Badge foil>{finish === "foil" ? "Foil" : "Etched"}</Badge> : null;
}

/** The edition a deck card prefers, short ("SLD #2783"); nothing when none is chosen. Pair it with FinishTag. */
export function EditionTag({ setCode, number, title }: { setCode?: string | null; number?: string | null; title?: string | null }) {
  return setCode ? <span className="shrink-0 text-[11px] uppercase tabular-nums text-mute" title={title ?? undefined}>{setCode} #{number}</span> : null;
}

/** Shown when an operation would take copies away from decks: says which, and offers to free them and carry on. */
export function Blocked({ message, onRelease, onCancel }: { message: string; onRelease: () => void; onCancel: () => void }) {
  return (
    <div role="alert" className="mt-4 rounded-xl border border-gold/50 bg-gold/10 p-3 text-sm">
      <p className="first-letter:uppercase">{message}.</p>
      <p className="mt-1 text-mute">Release the copies from those decks and continue? The decks keep the cards and show them as missing.</p>
      <div className="mt-2 flex gap-2"><button className="btn-primary !py-1" onClick={onRelease}>Release and continue</button><button className="btn-ghost !py-1" onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-mute"><span className="mb-1 block">{label}</span>{children}</label>;
}

export function Badge({ children, foil }: { children: React.ReactNode; foil?: boolean }) {
  return <span className={`rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold leading-none ${foil ? "foil text-black" : "bg-raised text-mute"}`}>{children}</span>;
}

export function useToast() {
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 3500);
    return () => clearTimeout(t);
  }, [msg]);
  const node = msg && (
    <div role="status" className={`fixed bottom-5 right-5 z-[60] rounded-xl border px-4 py-3 text-sm shadow-xl ${msg.err ? "border-danger/50 bg-surface text-danger" : "border-ok/40 bg-surface text-ok"}`}>
      {msg.text}
    </div>
  );
  return { toast: (text: string, err = false) => setMsg({ text, err }), node };
}
