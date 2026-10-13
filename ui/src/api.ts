import { useState } from "react";

export type Row = {
  id: number; scryfall_id: string; quantity: number; finish: "nonfoil" | "foil" | "etched";
  condition: "NM" | "LP" | "MP" | "HP" | "DMG"; language: string; location: string;
  altered: number; signed: number; misprint: number; proxy: number;
  purchase_price: number | null; purchase_currency: string; purchase_date: string | null; notes: string;
  name: string; set_code: string; set_name: string; collector_number: string; rarity: string; price: number | null; cardmarket_id?: number | null;
};
export type Collection = { rows: Row[]; total_rows: number; total_cards: number; total_value: number };
export type Print = {
  id: string; name: string; set_code: string; set_name: string; collector_number: string; released_at: string;
  rarity: string; finishes: string; frame: string; full_art: number; border_color: string; promo_types: string;
  eur: number | null; eur_foil: number | null; eur_etched: number | null; lang: string; cardmarket_id?: number | null;
};
export type Status = {
  cards_in_db: number; bulk_age_days: number | null; bulk_stale: boolean; credit: string; version?: string;
  job: { state: string; done: number; total: number; error: string | null; cards: number };
  index?: { indexed: number; rows: number; eligible: number };
  index_job?: { state: string; mode: string | null; done: number; total: number; error: string | null; failed: number; detail?: string };
};

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch("/api" + path, { ...opts, headers: { "Content-Type": "application/json", ...opts.headers } });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(typeof j.detail === "string" ? j.detail : r.statusText);
  }
  return r.json();
}

export const qs = (o: Record<string, string | number | undefined | null>) =>
  Object.entries(o).filter(([k, v]) => v !== undefined && v !== null && (v !== "" || k === "location"))
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

export const img = (id: string, size: "small" | "normal" | "large" = "normal") => `/api/image/${id}?size=${size}`;
export const eur = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString(undefined, { style: "currency", currency: "EUR" }));
export const FINISH: Record<string, string> = { nonfoil: "Non-foil", foil: "Foil", etched: "Etched" };
export const CONDITIONS = ["NM", "LP", "MP", "HP", "DMG"] as const;
export const LANGS: Record<string, string> = {
  en: "English", pt: "Portuguese", es: "Spanish", fr: "French", de: "German", it: "Italian",
  ja: "Japanese", ko: "Korean", ru: "Russian", zhs: "Chinese simpl.", zht: "Chinese trad.", ph: "Phyrexian",
};

/** "Group printings" (the same card with different art counts as 1); remembered between sessions. */
export function useGroup(): [boolean, (v: boolean) => void] {
  const [g, setG] = useState(() => { try { return localStorage.getItem("scrybinder.group") === "1"; } catch { return false; } });
  return [g, (v) => { setG(v); try { localStorage.setItem("scrybinder.group", v ? "1" : "0"); } catch { /* no storage */ } }];
}
