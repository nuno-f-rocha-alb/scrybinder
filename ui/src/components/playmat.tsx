import { useEffect, useState } from "react";
import { IconFolderOpen, IconPhoto } from "@tabler/icons-react";
import { api, Print, qs } from "../api";
import { CardImg, Modal } from "./ui";

export type Mat = { kind: "none" | "file" | "card"; name?: string; card_id?: string; dim: number; blur: number };
type State = { folder: string; files: { name: string; size: number }[]; current: Mat };
type Hit = { oracle_id: string | null; name: string; prints: number; sample_id: string };

const fileUrl = (name: string, thumb = false) => `/api/playmat/file/${encodeURIComponent(name)}${thumb ? "?thumb=true" : ""}`;
const artUrl = (id: string) => `/api/playmat/art/${encodeURIComponent(id)}`;
export const matUrl = (m: Mat) => (m.kind === "file" && m.name ? fileUrl(m.name) : m.kind === "card" && m.card_id ? artUrl(m.card_id) : null);

/** The chosen playmat, or none (also while it loads or when it cannot be read: the table then looks as it always did). */
export function usePlaymat(): Mat | null {
  const [mat, setMat] = useState<Mat | null>(null);
  useEffect(() => { api<State>("/playmat").then((s) => setMat(s.current)).catch(() => {}); }, []);
  return mat;
}

/** Fills its positioned parent behind the content: the image, then a dark layer so cards stay easy to read. Card art is small, so it is blurred. */
export function MatLayer({ mat }: { mat: Mat | null }) {
  const [broken, setBroken] = useState(false);
  const url = mat ? matUrl(mat) : null;
  useEffect(() => setBroken(false), [url]);
  useEffect(() => {  // an image that cannot be loaded leaves the plain table
    if (!url) return;
    const i = new Image();
    i.onerror = () => setBroken(true);
    i.src = url;
  }, [url]);
  if (!mat || !url || broken) return null;
  const blur = mat.kind === "card" ? mat.blur : 0;
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-xl">
      <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url("${url}")`, filter: blur ? `blur(${blur}px)` : undefined, transform: blur ? "scale(1.08)" : undefined }} />
      <div className="absolute inset-0 bg-black" style={{ opacity: mat.dim }} />
    </div>
  );
}

/** Pick the art of a card: search, then choose the printing. */
function ArtPicker({ onPick, onClose }: { onPick: (id: string) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [hit, setHit] = useState<Hit | null>(null);
  const [prints, setPrints] = useState<Print[]>([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    let live = true;  // a slower earlier answer must not replace a newer one
    const t = setTimeout(() => api<Hit[]>("/cards/search?" + qs({ q, limit: 12 })).then((r) => live && setHits(r)).catch(() => {}), 200);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  useEffect(() => {
    if (!hit) { setPrints([]); return; }
    api<Print[]>("/cards/prints?" + qs(hit.oracle_id ? { oracle_id: hit.oracle_id } : { name: hit.name })).then(setPrints).catch(() => {});
  }, [hit]);
  return (
    <Modal title="Card art" onClose={onClose} wide>
      <h2 className="mb-3 text-lg font-semibold">Use the art of a card</h2>
      <input autoFocus className="field mb-3" placeholder="Card name" aria-label="Card name" value={q} onChange={(e) => { setQ(e.target.value); setHit(null); }} />
      {!hit && <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
        {hits.map((h) => (
          <li key={h.name}><button onClick={() => setHit(h)} className="flex w-full cursor-pointer items-center gap-3 rounded-lg p-2 text-left hover:bg-raised">
            <div className="w-10 shrink-0"><CardImg id={h.sample_id} size="small" /></div><span className="flex-1 font-medium">{h.name}</span><span className="text-xs text-mute">{h.prints} printings</span>
          </button></li>
        ))}
      </ul>}
      {hit && <div>
        <button className="btn-ghost mb-3" onClick={() => setHit(null)}>Results</button>
        <div className="grid max-h-[55vh] grid-cols-[repeat(auto-fill,minmax(150px,1fr))] content-start gap-2 overflow-y-auto pr-1">
          {prints.map((p) => (
            <button key={p.id} onClick={() => onPick(p.id)} className="cursor-pointer rounded-lg p-1 text-left hover:bg-raised" title={`${p.set_name} #${p.collector_number}`}>
              <img src={artUrl(p.id)} alt="" loading="lazy" className="aspect-[4/3] w-full rounded-md bg-raised object-cover" />
              <div className="mt-1 text-[11px]"><b>{p.set_code.toUpperCase()}</b> <span className="text-mute">#{p.collector_number}</span></div>
            </button>
          ))}
        </div>
      </div>}
      <div className="mt-4"><button className="btn-ghost" onClick={onClose}>Cancel</button></div>
    </Modal>
  );
}

/** Settings: the playmat of the Playtest. */
export function PlaymatSection() {
  const [s, setS] = useState<State | null>(null);
  const [err, setErr] = useState("");
  const [art, setArt] = useState(false);
  const load = () => api<State>("/playmat").then(setS).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const save = async (m: Partial<Mat> & { kind: Mat["kind"] }) => {
    if (!s) return;
    setErr("");
    try { const cur = await api<Mat>("/playmat", { method: "PUT", body: JSON.stringify({ dim: s.current.dim, blur: s.current.blur, ...m }) }); setS({ ...s, current: cur }); }
    catch (e) { setErr((e as Error).message); load(); }
  };
  const cur = s?.current;
  const tile = (selected: boolean, onClick: () => void, label: string, child: React.ReactNode) => (
    <button key={label} onClick={onClick} aria-pressed={selected} title={label}
      className={`group relative cursor-pointer overflow-hidden rounded-xl border-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent ${selected ? "border-accent" : "border-line hover:border-mute"}`}>
      <div className="aspect-[16/10] w-full bg-raised">{child}</div>
      <div className="truncate bg-surface px-2 py-1 text-xs">{label}</div>
    </button>
  );
  return (
    <section className="mt-4 rounded-2xl border border-line bg-surface p-5">
      <h2 className="font-semibold">Playmat</h2>
      <p className="mt-1 text-sm text-mute">The background of the Playtest table. Put your own images (png, jpg, webp) in the folder below, or use the art of a card.</p>
      {s && <>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {tile(cur?.kind === "none", () => save({ kind: "none" }), "None", <div className="flex h-full items-center justify-center text-xs text-mute">Plain table</div>)}
          {s.files.map((f) => tile(cur?.kind === "file" && cur.name === f.name, () => save({ kind: "file", name: f.name }), f.name,
            <img src={fileUrl(f.name, true)} alt="" loading="lazy" className="h-full w-full object-cover" />))}
          {cur?.kind === "card" && cur.card_id && tile(true, () => setArt(true), "Card art", <img src={artUrl(cur.card_id)} alt="" className="h-full w-full object-cover" />)}
          <button onClick={() => setArt(true)} className="flex aspect-[16/10] cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-line text-sm text-mute hover:border-accent hover:text-ink">
            <IconPhoto className="size-5" />Card art…</button>
        </div>
        {!s.files.length && <p className="mt-3 text-sm text-mute">No images in the folder yet.</p>}
        <div className="mt-4 grid max-w-md gap-3">
          <label className="text-xs font-medium text-mute">Dim: {Math.round((cur?.dim ?? 0) * 100)}%
            <input type="range" min={0} max={80} step={5} value={Math.round((cur?.dim ?? 0) * 100)} className="mt-1 block w-full"
              onChange={(e) => s && cur && setS({ ...s, current: { ...cur, dim: +e.target.value / 100 } })} onPointerUp={() => cur && save({ ...cur })} onKeyUp={() => cur && save({ ...cur })} /></label>
          {cur?.kind === "card" && <label className="text-xs font-medium text-mute">Blur: {cur.blur} px (card art is small, a little blur hides it)
            <input type="range" min={0} max={12} step={1} value={cur.blur} className="mt-1 block w-full"
              onChange={(e) => s && setS({ ...s, current: { ...cur, blur: +e.target.value } })} onPointerUp={() => save({ ...cur })} onKeyUp={() => save({ ...cur })} /></label>}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <button className="btn-ghost" onClick={() => api("/playmat/open-folder", { method: "POST" }).then(load).catch((e) => setErr(e.message))}><IconFolderOpen className="size-4" />Open folder</button>
          <code className="min-w-0 break-all text-xs text-mute">{s.folder}</code>
        </div>
      </>}
      {err && <p role="alert" className="mt-2 text-xs text-danger">{err}</p>}
      {art && <ArtPicker onClose={() => setArt(false)} onPick={(id) => { setArt(false); save({ kind: "card", card_id: id }); }} />}
    </section>
  );
}
