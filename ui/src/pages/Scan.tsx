import { useCallback, useEffect, useRef, useState } from "react";
import { IconCamera, IconFolder, IconPhoto, IconSearch } from "@tabler/icons-react";
import { api, CONDITIONS, eur, FINISH, LANGS, Print, qs } from "../api";
import { Badge, CardImg, ExtLinks, HoverZoom, Modal, useToast } from "../components/ui";

type Cand = Pick<Print, "id" | "name" | "set_code" | "set_name" | "collector_number" | "released_at" | "finishes" | "eur" | "eur_foil" | "eur_etched"> & { score?: number };
type Pending = {
  id: number; qty: number; label: string; detected: boolean; confidence: "high" | "medium" | "low" | "none"; candidates: Cand[];
  ocr: { name: string; number: string | null; set: string | null; name_match: number; rotated: boolean };
};
type Read = {
  id: number; confidence: "high" | "medium" | "low" | "none"; scryfall_id: string | null; finish: string; qty: number;
  condition: string; language: string; card: (Cand & { finishes: string; cardmarket_id?: number | null }) | null;
};
type State = { running: boolean; source: string | null; message: string; beep: number; split_next: boolean; list_mode: boolean; page_mode: boolean; pending: Pending[]; reads: Read[] };

const LANG_KEYS = Object.keys(LANGS);
const CONF: Record<string, { t: string; c: string }> = {
  high: { t: "High confidence", c: "text-ok" }, medium: { t: "Check the printing", c: "text-gold" },
  low: { t: "Low confidence — please check", c: "text-danger" }, none: { t: "Not recognised — search by name", c: "text-danger" },
};
const store = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };

/** The live camera picture: one JPEG asked for a few times a second (not a continuous stream, see /api/scan/frame). */
function CameraPreview() {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let live = true, last: string | null = null, busy = false;
    const tick = async () => {
      if (busy) return;  // the previous picture has not arrived yet
      busy = true;
      try {
        const r = await fetch("/api/scan/frame", { cache: "no-store" });
        if (r.ok && live) {
          const u = URL.createObjectURL(await r.blob());
          setUrl(u);
          if (last) URL.revokeObjectURL(last);  // pictures are not kept: a stream's frames piled up in the page
          last = u;
        }
      } catch { /* the camera stopped between two pictures */ } finally { busy = false; }
    };
    const t = setInterval(tick, 120);
    tick();
    return () => { live = false; clearInterval(t); if (last) URL.revokeObjectURL(last); };
  }, []);
  return url ? <img src={url} alt="Camera preview" className="w-full rounded-xl border border-line" />
    : <div className="flex aspect-video w-full items-center justify-center rounded-xl border border-line bg-surface text-xs text-mute">Waiting for the camera…</div>;
}

export default function Scan() {
  const [st, setSt] = useState<State | null>(null);
  const [mode, setMode] = useState<"photos" | "folder" | "webcam">("photos");
  const [folder, setFolder] = useState(store("scrybinder.scanfolder", ""));
  const [cam, setCam] = useState("0");
  const [loc, setLoc] = useState(store("scrybinder.loc", ""));
  const [busy, setBusy] = useState(0);
  const [listMode, setListMode] = useState(store("scrybinder.listmode", "1") === "1");
  const [binder, setBinder] = useState(store("scrybinder.binder", "0") === "1");
  const { toast, node } = useToast();
  const beepSeen = useRef<number | null>(null);
  const audio = useRef<AudioContext | null>(null);

  const poll = useCallback(() => api<State>("/scan/state").then(setSt).catch(() => {}), []);
  useEffect(() => {  // the server keeps the mode; the user's choice persists in the browser
    api("/scan/mode", { method: "POST", body: JSON.stringify({ list: listMode }) }).catch(() => {});
    try { localStorage.setItem("scrybinder.listmode", listMode ? "1" : "0"); } catch { /* no storage */ }
  }, [listMode]);
  useEffect(() => {  // photos are binder pages (3x3): the folder watcher follows the same switch
    api("/scan/mode", { method: "POST", body: JSON.stringify({ page: binder }) }).catch(() => {});
    try { localStorage.setItem("scrybinder.binder", binder ? "1" : "0"); } catch { /* no storage */ }
  }, [binder]);
  useEffect(() => { poll(); const t = setInterval(poll, 700); return () => clearInterval(t); }, [poll]);

  const unlockAudio = () => { try { audio.current ??= new AudioContext(); void audio.current.resume(); } catch { /* no audio */ } };
  const beep = () => {
    try {
      audio.current ??= new AudioContext();
      const a = audio.current, o = a.createOscillator(), g = a.createGain();
      o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(a.destination);
      o.start(); o.stop(a.currentTime + 0.12);
    } catch { /* no audio: ignore */ }
  };
  useEffect(() => {
    if (!st) return;
    if (beepSeen.current !== null && st.beep > beepSeen.current) beep();
    beepSeen.current = st.beep;
  }, [st?.beep]);

  const upload = async (files: FileList | File[]) => {
    unlockAudio();  // the user gesture unlocks the sound of the following captures
    for (const f of Array.from(files)) {
      setBusy((n) => n + 1);
      try {
        const r = await api<{ detected?: number }>(`/scan/${binder ? "page" : "photo"}?` + qs({ name: f.name }), { method: "POST", headers: { "Content-Type": f.type || "image/jpeg" }, body: f });
        if (binder) toast(r.detected ? `${f.name}: ${r.detected} cards detected` : `${f.name}: no cards detected`, !r.detected);
      }
      catch (e) { toast(`${f.name}: ${(e as Error).message}`, true); }
      finally { setBusy((n) => n - 1); poll(); }
    }
  };
  const start = async () => {
    try {
      try { localStorage.setItem("scrybinder.scanfolder", folder); } catch { /* no storage */ }
      await api("/scan/start", { method: "POST", body: JSON.stringify({ kind: mode, target: mode === "folder" ? folder : cam }) });
      unlockAudio();
      (document.activeElement as HTMLElement | null)?.blur();  // otherwise the keyboard shortcuts get stuck in the field
      beep(); poll();  // the click unlocks the browser audio
    } catch (e) { toast((e as Error).message, true); }
  };
  const stop = () => api("/scan/stop", { method: "POST" }).then(poll);
  const split = useCallback(() => api("/scan/split-next", { method: "POST", body: JSON.stringify({ on: !st?.split_next }) }).then(poll), [st?.split_next, poll]);
  useEffect(() => {  // N: the next card opens a new entry (foil, another condition…)
    const h = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "n" || (e.target as HTMLElement).closest("input,select,textarea")) return;
      e.preventDefault(); split();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [split]);

  const cur = st?.pending[0];
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Scan</h1>
          <p className="mt-1 text-sm text-mute">{listMode ? `${st?.reads.reduce((n, r) => n + r.qty, 0) ?? 0} cards in the list` : st?.pending.length ? `${st.pending.length} to confirm` : "Nothing to confirm"}</p>
        </div>
        <label className="text-xs font-medium text-mute">Location for the scanned cards
          <input className="field mt-1 w-56" value={loc} placeholder="e.g. Box 3" aria-label="Location"
            onChange={(e) => { setLoc(e.target.value); try { localStorage.setItem("scrybinder.loc", e.target.value); } catch { /* no storage */ } }} />
        </label>
      </div>

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div className="flex rounded-xl border border-line bg-surface p-1" role="tablist">
            {([["photos", IconPhoto, "Photos"], ["folder", IconFolder, "Folder"], ["webcam", IconCamera, "Camera"]] as const).map(([m, I, l]) => (
              <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                className={`flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm ${mode === m ? "bg-accent-soft text-accent" : "text-mute hover:text-ink"}`}><I className="size-4" />{l}</button>
            ))}
          </div>

          {mode === "photos" && (
            <label onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
              className="flex h-40 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line text-center text-sm text-mute transition hover:border-accent hover:text-ink">
              <IconPhoto className="size-7" />{busy ? `Processing… (${busy})` : "Drop photos here or click"}
              <span className="text-xs">{binder ? "A full binder page, up to 9 cards" : "One card per photo, on a plain background"}</span>
              <input type="file" accept="image/*" multiple className="sr-only" onChange={(e) => { if (e.target.files) upload(e.target.files); e.target.value = ""; }} />
            </label>
          )}
          {mode !== "webcam" && (
            <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-line bg-surface p-3 text-sm">
              <input type="checkbox" className="mt-1" checked={binder} onChange={(e) => setBinder(e.target.checked)} />
              <span><b>Binder page (3×3)</b><br /><span className="text-xs text-mute">Each photo is a page of up to 9 cards, laid out as in a binder. Every card becomes its own entry.</span></span>
            </label>
          )}
          {mode === "folder" && (
            <div className="space-y-2 rounded-2xl border border-line bg-surface p-4">
              <label className="text-xs font-medium text-mute">Folder to watch (new files only)
                <input className="field mt-1" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\Users\…\Scans" /></label>
              {st?.running && st.source?.startsWith("folder") ? <button className="btn-ghost w-full" onClick={stop}>Stop</button>
                : <button className="btn-primary w-full" disabled={!folder} onClick={start}>Start watching</button>}
            </div>
          )}
          {mode === "webcam" && (
            <div className="space-y-2 rounded-2xl border border-line bg-surface p-4">
              <label className="text-xs font-medium text-mute">Camera index (0 = first)
                <input type="number" min={0} className="field mt-1" value={cam} onChange={(e) => setCam(e.target.value)} /></label>
              {st?.running && st.source?.startsWith("webcam") ? <button className="btn-ghost w-full" onClick={stop}>Stop</button>
                : <button className="btn-primary w-full" onClick={start}>Start camera</button>}
              {st?.message && <p className="text-xs text-danger">{st.message}</p>}
              <p className="text-xs text-mute">Capture is automatic when the card stays still for 0.4 s. Swap the card and repeat.</p>
              {st?.running && st.source?.startsWith("webcam") && (
                <button className="btn-ghost w-full !py-1 text-xs" title="Saves the whole camera frame and the outline the app found, in the debug folder of the data folder: attach it when a card is not detected"
                  onClick={() => api<{ path: string }>("/scan/debug-frame", { method: "POST" }).then((r) => toast(`Saved ${r.path}`)).catch((e) => toast((e as Error).message, true))}>
                  Save a debug frame
                </button>
              )}
            </div>
          )}
          {st?.running && st.source?.startsWith("webcam") && <CameraPreview />}

          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={listMode} onChange={(e) => setListMode(e.target.checked)} />
            <span>List mode<span className="block text-xs text-mute">Scanned cards go to an editable list; nothing enters your collection until you press Add.</span></span>
          </label>
          {st?.running && (
            <div className="space-y-1">
              <button className={st.split_next ? "btn-primary w-full" : "btn-ghost w-full"} onClick={split}>
                {st.split_next ? (listMode ? "The next card is foil ✓" : "The next card opens a new entry ✓") : (listMode ? "Next card is foil" : "Next card is different (foil…)")} <kbd className="rounded bg-black/25 px-1.5 text-xs">N</kbd>
              </button>
              <p className="text-xs text-mute">Identical cards in a row add to the quantity of the same entry. Press this before showing the foil.</p>
            </div>
          )}

          {st && st.pending.length > 1 && (
            <div><h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-mute">Queue</h2>
              <div className="flex flex-wrap gap-2">{st.pending.slice(1, 13).map((p) => (
                <div key={p.id} className="relative"><img src={`/api/scan/capture/${p.id}`} alt="" className="h-20 rounded-md border border-line" />
                  {p.qty > 1 && <span className="absolute right-1 top-1 rounded bg-accent px-1.5 text-xs font-semibold text-white">×{p.qty}</span>}</div>))}</div></div>
          )}
        </aside>

        <section className="min-w-0">{listMode ? <ReadsList reads={st?.reads ?? []} location={loc} onChange={poll} toast={toast} />
          : cur ? <Confirm key={cur.id} item={cur} location={loc} onDone={(m, err) => { toast(m, err); poll(); }} />
          : <div className="flex h-72 items-center justify-center rounded-2xl border border-dashed border-line text-sm text-mute">Scanned cards appear here for you to confirm.</div>}</section>
      </div>
      {node}
    </div>
  );
}

function Confirm({ item, location, onDone }: { item: Pending; location: string; onDone: (msg: string, err?: boolean) => void }) {
  const [cands, setCands] = useState<Cand[]>(item.candidates);
  const [idx, setIdx] = useState(0);
  const [finish, setFinish] = useState("nonfoil");
  const [qty, setQty] = useState(item.qty);
  useEffect(() => setQty(item.qty), [item.qty]);  // the same card read again while you confirm: the quantity follows
  const [cond, setCond] = useState<string>("NM");
  const [lang, setLang] = useState("en");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ oracle_id: string; name: string }[]>([]);
  const typing = useRef(false);
  const c = cands[idx];

  const finishes = (x?: Cand): string[] => (x ? (JSON.parse(x.finishes || "[]") as string[]) : []);
  useEffect(() => { if (c && !finishes(c).includes(finish)) setFinish(finishes(c)[0] ?? "nonfoil"); }, [c?.id]);

  const accept = useCallback(async () => {
    if (!c) return;
    try {
      await api(`/scan/${item.id}/confirm`, { method: "POST", body: JSON.stringify({ scryfall_id: c.id, finish, quantity: qty, condition: cond, language: lang, location }) });
      onDone(`${qty}× ${c.name} (${c.set_code.toUpperCase()} #${c.collector_number})`);
    } catch (e) { onDone((e as Error).message, true); }
  }, [c, finish, qty, cond, lang, location, item.id]);
  const discard = () => api(`/scan/${item.id}/discard`, { method: "POST" }).then(() => onDone("Discarded")).catch((e) => onDone(e.message, true));

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (typing.current || (e.target as HTMLElement).closest("input,select,textarea") ) return;
      const k = e.key;
      if (k === "Enter") accept();
      else if (k === "Escape") discard();
      else if (k === "ArrowRight") setIdx((i) => Math.min(cands.length - 1, i + 1));
      else if (k === "ArrowLeft") setIdx((i) => Math.max(0, i - 1));
      else if (k === "+" || k === "=") setQty((n) => n + 1);
      else if (k === "-") setQty((n) => Math.max(1, n - 1));
      else if (k.toLowerCase() === "f") setFinish((f) => (finishes(c).includes("foil") && f === "nonfoil" ? "foil" : "nonfoil"));
      else if (k.toLowerCase() === "c") setCond((x) => CONDITIONS[(CONDITIONS.indexOf(x as typeof CONDITIONS[number]) + 1) % CONDITIONS.length]);
      else if (k.toLowerCase() === "l") setLang((x) => LANG_KEYS[(LANG_KEYS.indexOf(x) + 1) % LANG_KEYS.length]);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [accept, cands.length, c?.id]);

  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => api<typeof hits>("/cards/search?" + qs({ q })).then((r) => setHits(r.slice(0, 6))).catch(() => setHits([])), 200);
    return () => clearTimeout(t);
  }, [q]);
  const pickName = (h: { oracle_id: string }) => api<Print[]>("/cards/prints?" + qs({ oracle_id: h.oracle_id })).then((p) => { setCands(p); setIdx(0); setQ(""); setHits([]); });

  const conf = CONF[item.confidence];
  const price = c ? (finish === "foil" ? c.eur_foil : finish === "etched" ? c.eur_etched : c.eur) : null;
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <span className={`text-sm font-medium ${conf.c}`}>{conf.t}</span>
        <span className="text-xs text-mute">{item.label && `${item.label} · `}OCR: “{item.ocr.name || "—"}”{item.ocr.number && ` · no. ${item.ocr.number}`}{!item.detected && " · card not detected in the photo"}</span>
      </div>
      <div className="grid min-w-0 grid-cols-2 gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.1fr)]">
        <figure className="min-w-0"><div className="mx-auto aspect-[63/88] max-h-[44vh]"><img src={`/api/scan/capture/${item.id}`} alt="Capture" className="size-full rounded-[4.5%] bg-raised object-cover" /></div><figcaption className="mt-1 text-center text-xs text-mute">Capture</figcaption></figure>
        <figure className="min-w-0"><div className="mx-auto aspect-[63/88] max-h-[44vh]">{c ? <CardImg key={c.id} id={c.id} size="large" /> : <div className="flex size-full items-center justify-center rounded-[4.5%] bg-raised text-sm text-mute">No candidate</div>}</div>
          <figcaption className="mt-1 text-center text-xs text-mute">Scryfall{cands.length > 1 && ` · ${idx + 1}/${cands.length}`}</figcaption></figure>
        <div className="col-span-2 space-y-3 2xl:col-span-1">
          {c && <div><div className="text-lg font-semibold leading-tight">{c.name}</div>
            <div className="text-sm text-mute">{c.set_name} · {c.set_code.toUpperCase()} #{c.collector_number} · {c.released_at?.slice(0, 4)}</div>
            <div className="mt-1 text-sm text-gold">{eur(price)}</div></div>}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Row k="F" l="Finish" v={FINISH[finish] ?? finish} foil={finish !== "nonfoil"} />
            <Row k="+ / −" l="Quantity" v={`${qty}`} />
            <Row k="C" l="Condition" v={cond} />
            <Row k="L" l="Language" v={LANGS[lang]} />
          </div>
          <div className="flex gap-2">
            <button className="btn-primary flex-1" disabled={!c} onClick={accept}>Accept <kbd className="rounded bg-black/25 px-1.5 text-xs">Enter</kbd></button>
            <button className="btn-ghost" onClick={discard}>Discard <kbd className="rounded bg-black/25 px-1.5 text-xs">Esc</kbd></button>
          </div>
          <p className="text-xs text-mute"><kbd>←</kbd> <kbd>→</kbd> change the printing</p>
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input className="field pl-9" placeholder="Not this one? Search by name…" value={q} onChange={(e) => setQ(e.target.value)}
              onFocus={() => (typing.current = true)} onBlur={() => (typing.current = false)} aria-label="Search for another card" />
            {hits.length > 0 && <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-line bg-surface shadow-xl">
              {hits.map((h) => <li key={h.oracle_id}><button className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-raised" onMouseDown={() => pickName(h)}>{h.name}</button></li>)}</ul>}
          </div>
        </div>
      </div>
      {cands.length > 1 && (
        <div className="mt-5 flex gap-2 overflow-x-auto pb-1" aria-label="Candidate printings">
          {cands.map((x, i) => (
            <button key={x.id} onClick={() => setIdx(i)} aria-pressed={i === idx}
              className={`w-24 shrink-0 cursor-pointer rounded-lg p-1 text-left transition ${i === idx ? "bg-accent-soft ring-2 ring-accent" : "hover:bg-raised"}`}>
              <HoverZoom zoom={<CardImg id={x.id} />}><CardImg id={x.id} /></HoverZoom><div className="mt-1 truncate text-[11px]"><b>{x.set_code.toUpperCase()}</b> <span className="text-mute">#{x.collector_number}</span></div>
            </button>))}
        </div>
      )}
    </div>
  );
}

function Row({ k, l, v, foil }: { k: string; l: string; v: string; foil?: boolean }) {
  return <div className="rounded-lg border border-line bg-bg px-3 py-2"><div className="flex items-center justify-between text-[11px] text-mute"><span>{l}</span><kbd className="rounded bg-raised px-1">{k}</kbd></div>
    <div className="mt-0.5 font-medium">{foil ? <Badge foil>{v}</Badge> : v}</div></div>;
}

const unit = (r: Read) => (r.card ? (r.finish === "foil" ? r.card.eur_foil : r.finish === "etched" ? r.card.eur_etched : r.card.eur) : null);

const flag = (c: string) => c === "high" ? null : c === "medium" ? { t: "Check the printing", c: "text-gold border-gold" } : { t: "Please check", c: "text-danger border-danger" };

function ReadsList({ reads, location, onChange, toast }: { reads: Read[]; location: string; onChange: () => void; toast: (m: string, err?: boolean) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  const [committing, setCommitting] = useState(false);
  const patch = (id: number, body: object) => api(`/scan/reads/${id}`, { method: "PATCH", body: JSON.stringify(body) }).then(onChange).catch((e) => toast(e.message, true));
  const del = (id: number) => api(`/scan/reads/${id}`, { method: "DELETE" }).then(onChange).catch((e) => toast(e.message, true));
  const total = reads.reduce((n, r) => n + r.qty, 0);
  const todo = reads.filter((r) => r.confidence !== "high").length;
  const worth = reads.reduce((n, r) => n + (unit(r) ?? 0) * r.qty, 0);
  const noPrice = reads.filter((r) => unit(r) == null).length;
  const commit = async () => {
    setCommitting(true);
    try {
      const r = await api<{ added: number; rows: number; error?: string }>("/scan/reads/commit", { method: "POST", body: JSON.stringify({ location }) });
      toast(r.error ? `Added ${r.added}; stopped at: ${r.error}` : `${r.added} cards added to your collection${location ? ` (${location})` : ""}`, !!r.error);
    } catch (e) { toast((e as Error).message, true); }
    finally { setCommitting(false); onChange(); }
  };
  const [confirmClear, setConfirmClear] = useState(false);
  const clear = async () => { setConfirmClear(false); for (const r of reads) await del(r.id); };

  if (!reads.length) return <div className="flex h-72 items-center justify-center rounded-2xl border border-dashed border-line text-sm text-mute">Scanned cards appear here. Edit whatever you need and press Add when you are done.</div>;
  return (
    <div className="min-w-0 space-y-3">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-3">
        <div className="text-sm"><b>{total}</b> cards · {reads.length} entries{todo > 0 && <span className="ml-2 text-gold">{todo} to check</span>}
          <span className="ml-2 text-gold">≈ {eur(worth)}{noPrice > 0 && <span className="text-xs text-mute"> ({noPrice} without price)</span>}</span>
          <span className="ml-2 text-xs text-mute">Location: {location || "— (no location)"}</span></div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => setConfirmClear(true)}>Clear list</button>
          <button className="btn-primary" disabled={committing} onClick={commit}>Add {total} to collection</button>
        </div>
      </div>
      <ul className="space-y-2">
        {[...reads].reverse().map((r) => {
          const f = flag(r.confidence), c = r.card;
          const fin = c ? (JSON.parse(c.finishes || "[]") as string[]) : [];
          return (
            <li key={r.id} className={`rounded-xl border bg-surface p-3 ${f ? f.c.split(" ")[1] : "border-line"}`}>
              <div className="flex flex-wrap items-center gap-3">
                <HoverZoom zoom={<img src={`/api/scan/capture/${r.id}`} alt="" className="size-full object-cover" />}>
                  <img src={`/api/scan/capture/${r.id}`} alt="Capture" className="h-24 rounded-md border border-line" /></HoverZoom>
                <HoverZoom className="h-24 w-[69px] shrink-0" zoom={r.scryfall_id ? <CardImg id={r.scryfall_id} /> : null}>{r.scryfall_id && <CardImg id={r.scryfall_id} />}</HoverZoom>
                <div className="min-w-[12rem] flex-1">
                  <div className="font-semibold leading-tight">{c?.name ?? "No candidate"}</div>
                  {c && <div className="text-sm text-mute">{c.set_name} · {c.set_code.toUpperCase()} #{c.collector_number} · {c.released_at?.slice(0, 4)}</div>}
                  <div className="mt-1 text-sm text-gold">{eur(unit(r))}{r.qty > 1 && unit(r) != null && <span className="text-mute"> × {r.qty} = {eur((unit(r) ?? 0) * r.qty)}</span>}</div>
                  {r.scryfall_id && <div className="mt-1"><ExtLinks id={r.scryfall_id} cardmarketId={c?.cardmarket_id} /></div>}
                  {f && <div className={`mt-1 text-xs font-medium ${f.c.split(" ")[0]}`}>{f.t}</div>}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <select className="field w-28" value={r.finish} aria-label="Finish" onChange={(e) => patch(r.id, { finish: e.target.value })}>
                    {(fin.length ? fin : ["nonfoil"]).map((x) => <option key={x} value={x}>{FINISH[x] ?? x}</option>)}</select>
                  <div className="flex items-center rounded-lg border border-line">
                    <button className="px-2 py-1" aria-label="Less" onClick={() => patch(r.id, { qty: Math.max(1, r.qty - 1) })}>−</button>
                    <span className="min-w-6 text-center font-medium">{r.qty}</span>
                    <button className="px-2 py-1" aria-label="More" onClick={() => patch(r.id, { qty: r.qty + 1 })}>+</button></div>
                  <select className="field w-20" value={r.condition} aria-label="Condition" onChange={(e) => patch(r.id, { condition: e.target.value })}>
                    {CONDITIONS.map((x) => <option key={x}>{x}</option>)}</select>
                  <select className="field w-28" value={r.language} aria-label="Language" onChange={(e) => patch(r.id, { language: e.target.value })}>
                    {LANG_KEYS.map((x) => <option key={x} value={x}>{LANGS[x]}</option>)}</select>
                  <button className="btn-ghost" onClick={() => setOpen(open === r.id ? null : r.id)}>Printing</button>
                  <button className="btn-ghost" aria-label="Remove from list" onClick={() => del(r.id)}>Remove</button>
                </div>
              </div>
              {open === r.id && <PrintPicker read={r} onPick={(id) => { patch(r.id, { scryfall_id: id }); setOpen(null); }} />}
            </li>
          );
        })}
      </ul>
      {confirmClear && (
        <Modal onClose={() => setConfirmClear(false)} title="Clear list">
          <h2 className="text-xl font-semibold text-danger">Delete all {reads.length} entries from the list?</h2>
          <p className="mt-2 text-sm text-mute">Your collection is not touched.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" autoFocus onClick={() => setConfirmClear(false)}>Cancel</button>
            <button className="btn-danger" onClick={clear}>Yes, delete {reads.length}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function PrintPicker({ read, onPick }: { read: Read; onPick: (id: string) => void }) {
  const [cands, setCands] = useState<Cand[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ oracle_id: string; name: string }[]>([]);
  useEffect(() => { api<Cand[]>(`/scan/reads/${read.id}/candidates`).then(setCands).catch(() => {}); }, [read.id]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => api<typeof hits>("/cards/search?" + qs({ q })).then((r) => setHits(r.slice(0, 6))).catch(() => setHits([])), 200);
    return () => clearTimeout(t);
  }, [q]);
  const byName = (h: { oracle_id: string }) => api<Print[]>("/cards/prints?" + qs({ oracle_id: h.oracle_id })).then((p) => { setCands(p); setQ(""); setHits([]); });
  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <div className="relative max-w-sm">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
        <input className="field pl-9" placeholder="Another card? Search by name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search for another card" />
        {hits.length > 0 && <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-line bg-surface shadow-xl">
          {hits.map((h) => <li key={h.oracle_id}><button className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-raised" onMouseDown={() => byName(h)}>{h.name}</button></li>)}</ul>}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Candidate printings">
        {cands.map((x) => (
          <button key={x.id} onClick={() => onPick(x.id)} aria-pressed={x.id === read.scryfall_id}
            className={`w-24 shrink-0 cursor-pointer rounded-lg p-1 text-left transition ${x.id === read.scryfall_id ? "bg-accent-soft ring-2 ring-accent" : "hover:bg-raised"}`}>
            <HoverZoom zoom={<CardImg id={x.id} />}><CardImg id={x.id} /></HoverZoom><div className="mt-1 truncate text-[11px]"><b>{x.set_code.toUpperCase()}</b> <span className="text-mute">#{x.collector_number}</span></div>
          </button>))}
      </div>
    </div>
  );
}
