import { IconBox, IconCheck, IconCopy, IconShoppingCart, IconSwitchHorizontal } from "@tabler/icons-react";
import type { CardStatus } from "../decks";

const PIP: Record<string, string> = { W: "#f6f1c9", U: "#7fb8e8", B: "#9d8f99", R: "#ee8a6e", G: "#6dbb85", C: "#c9c5c0", X: "#c9c5c0" };

/** A mana cost as small coloured circles: "{2}{W}{U/B}" (hybrid shows the first colour). */
export function ManaCost({ cost }: { cost: string | null | undefined }) {
  const syms = (cost ?? "").match(/\{[^}]+\}/g) ?? [];
  if (!syms.length) return null;
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`Mana cost ${syms.map((s) => s.slice(1, -1)).join(" ")}`}>
      {syms.map((s, i) => {
        const t = s.slice(1, -1);
        const col = t.split("/").find((p) => PIP[p]);
        return <span key={i} aria-hidden className="inline-flex size-[15px] items-center justify-center rounded-full text-[8.5px] font-bold leading-none text-black"
          style={{ background: col ? PIP[col] : "#d4d0cb" }}>{t.replace(/\//g, "")}</span>;
      })}
    </span>
  );
}

const STATUS: Record<CardStatus, { label: string; cls: string; Icon: typeof IconCheck; hint: string }> = {
  assigned: { label: "Assigned", cls: "text-ok", Icon: IconCheck, hint: "Every copy is assigned to this deck" },
  available: { label: "Available", cls: "text-accent", Icon: IconBox, hint: "You own free copies you can assign" },
  elsewhere: { label: "In other deck", cls: "text-gold", Icon: IconSwitchHorizontal, hint: "Your copies are assigned to other decks" },
  missing: { label: "Missing", cls: "text-danger", Icon: IconShoppingCart, hint: "You do not own enough copies" },
  proxy: { label: "Proxy", cls: "text-mute", Icon: IconCopy, hint: "A proxy: present in the deck, never counted as missing" },
};

/** Status with an icon and a word, never colour alone. */
export function StatusBadge({ status, title }: { status: CardStatus; title?: string }) {
  const s = STATUS[status];
  return <span title={title ?? s.hint} className={`inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium ${s.cls}`}><s.Icon className="size-3.5" aria-hidden />{s.label}</span>;
}

export const STATUS_RING: Record<CardStatus, string> = {
  assigned: "ring-ok/70", available: "ring-accent/70", elsewhere: "ring-gold/70", missing: "ring-danger/70", proxy: "ring-mute/50",
};

/** The status as a small round icon (for the visual views, where there is no room for the word). */
export function StatusDot({ status, title }: { status: CardStatus; title?: string }) {
  const s = STATUS[status];
  return <span role="img" aria-label={s.label} title={title ?? `${s.label}: ${s.hint}`}
    className={`flex size-5 items-center justify-center rounded-full bg-bg/90 ring-1 ring-line ${s.cls}`}><s.Icon className="size-3" aria-hidden /></span>;
}
