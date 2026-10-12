import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, img } from "../api";

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

/** Links to visually confirm the printing: Scryfall (by id) and Cardmarket (by idProduct, when it exists). */
export function ExtLinks({ id, cardmarketId }: { id: string; cardmarketId?: number | null }) {
  const open = (url: string) => (e: React.MouseEvent) => {
    e.preventDefault();  // inside the app window it opens in the system browser (the server only accepts these two sites)
    api("/open-url", { method: "POST", body: JSON.stringify({ url }) }).catch(() => window.open(url, "_blank", "noopener"));
  };
  const sf = `https://scryfall.com/card/${id}`, cm = cardmarketId ? `https://www.cardmarket.com/en/Magic/Products?idProduct=${cardmarketId}` : null;
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

export function Modal({ onClose, title, children }: { onClose: () => void; title: string; children: React.ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div role="dialog" aria-modal aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-line bg-surface p-6 shadow-2xl">
        {children}
      </div>
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
