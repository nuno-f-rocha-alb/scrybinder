import { useCallback, useEffect, useState } from "react";
import { api, Status } from "../api";
import { PlaymatSection } from "../components/playmat";

type Gpu = {
  supported: boolean; driver: number | null; gpu: string | null; wheel: { tag: string; torch: string; size: number } | null;
  installed: { tag: string; torch: string } | null; pending_removal: boolean; active: boolean; device: string | null;
  job: { state: string; done: number; total: number; error: string | null };
};

type Bridge = { save_db?: (name: string) => Promise<string | null>; restore_db?: () => Promise<{ staged?: boolean; error?: string; cards?: number; collection?: number } | null> };

/** A copy of the database, and putting one back (applied at the next start, because the running app has the database open). */
function BackupSection({ pending }: { pending?: boolean }) {
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState(false);
  const bridge = (window as { pywebview?: { api?: Bridge } }).pywebview?.api;
  const name = () => `scrybinder-backup-${new Date().toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "-")}.db`;
  const staged = (r: { cards?: number; collection?: number }) => setMsg(`Ready to restore (${(r.collection ?? 0).toLocaleString()} collection rows). Now close Scrybinder completely (wait until its window is gone) and open it again to finish: your current database is kept next to it as scrybinder.db.before-restore.`);
  const backup = async () => {
    setErr(""); setMsg("");
    if (!bridge?.save_db) { window.location.assign("/api/backup"); setMsg("The backup is downloading."); return; }
    try { const path = await bridge.save_db(name()); if (path) setMsg(`Saved to ${path}`); } catch (e) { setErr((e as Error).message); }
  };
  const restore = async () => {
    setErr(""); setMsg(""); setConfirm(false);
    try {
      if (bridge?.restore_db) {
        const r = await bridge.restore_db();
        if (r?.error) setErr(r.error); else if (r) staged(r);
      }
    } catch (e) { setErr((e as Error).message); }
  };
  const upload = async (f: File | null) => {
    if (!f) return;
    setErr(""); setMsg("");
    try {
      const r = await fetch("/api/restore", { method: "POST", body: f });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : r.statusText);
      staged(j);
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <section className="mt-4 rounded-2xl border border-line bg-surface p-5">
      <h2 className="font-semibold">Backup &amp; restore</h2>
      <p className="mt-1 text-sm text-mute">A backup is one file with your whole database: collection, decks and the card data. Images, the visual index and the logs are not in it.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" onClick={backup}>Back up now</button>
        {!confirm
          ? <button className="btn-ghost" onClick={() => setConfirm(true)}>Restore from a backup…</button>
          : <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gold/40 bg-gold/10 px-3 py-2 text-sm" role="alert">
              <span>Restoring replaces your collection and decks at the next start (the current database is kept as <code>.before-restore</code>).</span>
              {bridge?.restore_db
                ? <button className="btn-primary" onClick={restore}>Choose a backup file</button>
                : <label className="btn-primary cursor-pointer">Choose a backup file<input type="file" accept=".db,application/octet-stream" className="sr-only" onChange={(e) => { setConfirm(false); upload(e.target.files?.[0] ?? null); }} /></label>}
              <button className="btn-ghost" onClick={() => setConfirm(false)}>Cancel</button>
            </div>}
      </div>
      {pending && !msg && <p className="mt-3 text-sm text-gold" role="status">A restore is waiting. Close Scrybinder completely (wait until its window is gone, and check that no other Scrybinder is open) and open it again to finish it.</p>}
      {msg && <p className="mt-3 text-sm text-ok" role="status">{msg}</p>}
      {err && <p className="mt-3 text-sm text-danger" role="alert">{err}</p>}
    </section>
  );
}

/** Optional GPU acceleration for the installed app: downloads the CUDA build of PyTorch (see scrybinder/gpu.py). */
function GpuSection() {
  const [g, setG] = useState<Gpu | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const load = useCallback(() => api<Gpu>("/gpu").then(setG).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  const busy = !!g && ["download", "extract", "test"].includes(g.job.state);
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [busy, load]);
  if (!g) return null;
  const gb = (n: number) => (n / 1e9).toFixed(1);
  const enable = () => { setErr(""); setNote(""); api("/gpu/install", { method: "POST" }).then(load).catch((e) => setErr(e.message)); };
  const remove = () => {
    setErr("");
    api<{ restart_needed: boolean }>("/gpu/remove", { method: "POST" })
      .then((r) => { setNote(r.restart_needed ? "It is removed when you restart Scrybinder." : "Removed."); load(); })
      .catch((e) => setErr(e.message));
  };
  const j = g.job;
  const offered = g.supported && g.wheel && !g.installed && !g.pending_removal;
  return (
    <section className="mt-4 rounded-2xl border border-line bg-surface p-5">
      <h2 className="font-semibold">GPU acceleration</h2>
      <p className="mt-1 text-sm text-mute">
        The visual model runs on: <b className="text-ink">{g.device ?? "not loaded yet"}</b>
        {g.gpu && <> · NVIDIA {g.gpu.replace(/^NVIDIA /, "")}</>}
      </p>
      {!g.supported && <p className="mt-2 text-xs text-mute">The installed Windows app can add GPU support from here. From source use <code>uv sync --extra vision-cuda</code>.</p>}
      {g.supported && !g.wheel && !g.installed && <p className="mt-2 text-xs text-mute">No NVIDIA GPU with a recent driver (CUDA 12.8 or newer) was found, so the model runs on the CPU.</p>}
      {offered && (
        <>
          <p className="mt-2 text-xs text-mute">
            The installer runs the visual model on the CPU. To use your NVIDIA GPU (much faster to build the index), Scrybinder downloads the CUDA build of PyTorch
            (<b>{gb(g.wheel!.size)} GB</b>, PyTorch {g.wheel!.torch} from download.pytorch.org, checksum verified) into your data folder, tests it, and uses it after a restart. You can remove it at any time.
          </p>
          <button className="btn-primary mt-4" disabled={busy} onClick={enable}>{busy ? "Working…" : `Enable GPU acceleration (${gb(g.wheel!.size)} GB download)`}</button>
        </>
      )}
      {g.installed && (
        <>
          <p className="mt-2 text-sm">{g.active ? (g.device?.startsWith("GPU") ? <span className="text-ok">In use.</span> : g.device === "CPU" ? <span className="text-danger">Installed, but PyTorch fell back to the CPU: check your NVIDIA driver (or remove it).</span> : "Installed. It is used when the visual model loads.") : "Installed. Restart Scrybinder to use it."} <span className="text-xs text-mute">PyTorch {g.installed.torch} ({g.installed.tag})</span></p>
          <button className="btn-ghost mt-3" disabled={busy} onClick={remove}>Remove GPU support</button>
        </>
      )}
      {g.pending_removal && !g.installed && <p className="mt-2 text-sm">It is removed when you restart Scrybinder.</p>}
      {(busy || j.state === "done" || j.state === "error") && j.state !== "idle" && (
        <div className="mt-4 text-sm" role="status">
          <div className={j.state === "error" ? "text-danger" : j.state === "done" ? "text-ok" : ""}>
            {j.state === "download" && `Downloading ${gb(j.done)} / ${gb(j.total)} GB…`}
            {j.state === "extract" && "Unpacking…"}
            {j.state === "test" && "Testing it on your GPU…"}
            {j.state === "done" && "Done. Restart Scrybinder to use the GPU."}
            {j.state === "error" && "It could not be installed; Scrybinder stays on the CPU."}
          </div>
          {j.state === "download" && j.total > 0 && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${(j.done / j.total) * 100}%` }} /></div>
          )}
          {j.error && <p className="mt-1 text-xs text-danger">{j.error}</p>}
        </div>
      )}
      {note && <p className="mt-2 text-xs text-mute">{note}</p>}
      {err && <p className="mt-2 text-xs text-danger">{err}</p>}
    </section>
  );
}

type Upd = {
  supported: boolean; version: string; checking: boolean; error: string | null; check_on_start: boolean;
  plan: { latest: string; up_to_date: boolean; needs_installer: boolean; url: string | null; notes: string; chain: { size: number }[] } | null;
  job: { state: string; done: number; total: number; step: number; steps: number; error: string | null };
};

/** Updates for the installed app: downloads only the files that changed, checks them and swaps them in (see scrybinder/updater.py). */
function UpdateSection({ refresh }: { refresh: () => void }) {
  const [u, setU] = useState<Upd | null>(null);
  const [err, setErr] = useState("");
  const [wait, setWait] = useState(false);
  const load = useCallback(() => api<Upd>("/update").then(setU).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  const busy = !!u && ["download", "verify", "apply"].includes(u.job.state);
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [busy, load]);
  if (!u) return null;
  const mb = (n: number) => (n / 1e6).toFixed(0);
  const call = (path: string, body?: object) => { setErr(""); return api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }); };
  const check = () => { setWait(true); call("/update/check").then(() => { load(); refresh(); }).catch((e) => setErr(e.message)).finally(() => setWait(false)); };
  const install = () => call("/update/install").then(load).catch((e) => setErr(e.message));
  const restart = () => call("/update/restart").catch((e) => setErr(e.message));
  const j = u.job, p = u.plan;
  const size = p ? p.chain.reduce((a, s) => a + s.size, 0) : 0;
  return (
    <section className="mt-4 rounded-2xl border border-line bg-surface p-5">
      <h2 className="font-semibold">Updates</h2>
      <p className="mt-1 text-sm text-mute">Scrybinder <b className="text-ink">{u.version}</b></p>
      {!u.supported && <p className="mt-2 text-xs text-mute">The installed Windows app can update itself from here. From source use <code>git pull</code>.</p>}
      {u.supported && j.state !== "done" && (
        <>
          <p className="mt-2 text-xs text-mute">Checks the releases on github.com and downloads only the files that changed (checksums verified), then asks you to restart. Nothing is sent about you.</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button className="btn-ghost" disabled={busy || wait} onClick={check}>{wait ? "Checking…" : "Check for updates"}</button>
            {p && !p.up_to_date && p.chain.length > 0 && <button className="btn-primary" disabled={busy} onClick={install}>{busy ? "Working…" : `Update to ${p.latest} (${mb(size)} MB)`}</button>}
            <label className="flex items-center gap-2 text-sm text-mute">
              <input type="checkbox" checked={u.check_on_start} onChange={(e) => call("/update/settings", { check_on_start: e.target.checked }).then(load).catch((x) => setErr(x.message))} />
              Check on start-up
            </label>
          </div>
          {p?.up_to_date && <p className="mt-3 text-sm text-ok">Up to date.</p>}
          {p && !p.up_to_date && p.needs_installer && (
            <p className="mt-3 text-sm">{p.latest} is available, but there is no short update path from {u.version}: <a className="text-accent underline" href={p.url ?? "#"} target="_blank" rel="noreferrer">download the installer</a>.</p>
          )}
          {p && !p.up_to_date && !p.needs_installer && p.notes && <details className="mt-3 text-sm"><summary className="cursor-pointer text-mute">What's new in {p.latest}</summary><pre className="mt-2 whitespace-pre-wrap text-xs text-mute">{p.notes}</pre></details>}
        </>
      )}
      {j.state !== "idle" && (
        <div className="mt-4 text-sm" role="status">
          <div className={j.state === "error" ? "text-danger" : j.state === "done" ? "text-ok" : ""}>
            {j.state === "download" && `Downloading${j.steps > 1 ? ` (${j.step}/${j.steps})` : ""}: ${mb(j.done)} / ${mb(j.total)} MB…`}
            {j.state === "verify" && "Checking the files…"}
            {j.state === "apply" && "Replacing the files…"}
            {j.state === "done" && "Updated. Restart Scrybinder to use the new version."}
            {j.state === "error" && "It could not be updated; this version stays as it was."}
          </div>
          {j.state === "download" && j.total > 0 && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${(j.done / j.total) * 100}%` }} /></div>
          )}
          {j.error && <p className="mt-1 text-xs text-danger">{j.error}</p>}
          {j.state === "done" && <button className="btn-primary mt-3" onClick={restart}>Restart now</button>}
        </div>
      )}
      {u.error && <p className="mt-2 text-xs text-danger">Could not reach GitHub: {u.error}</p>}
      {err && <p className="mt-2 text-xs text-danger">{err}</p>}
    </section>
  );
}

const LABEL: Record<string, string> = { download: "Downloading bulk data…", import: "Importing cards…", done: "Done", error: "Error" };

export default function Settings({ status, refresh }: { status: Status | null; refresh: () => void }) {
  const running = status?.job.state === "download" || status?.job.state === "import";
  const ij = status?.index_job;
  const building = ij?.state === "prepare" || ij?.state === "build";
  const [est, setEst] = useState<{ printings: number; hours: number; gb: number } | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!running && !building) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [running, building]);

  const startIndex = (mode: "pilot" | "all") => {
    setErr(""); setEst(null);
    api("/index/build", { method: "POST", body: JSON.stringify({ mode }) }).then(refresh).catch((e) => setErr(e.message));
  };
  const askFull = () => { setErr(""); api<{ printings: number; hours: number; gb: number }>("/index/estimate").then(setEst).catch((e) => setErr(e.message)); };
  const stopIndex = () => api("/index/stop", { method: "POST" }).then(refresh).catch((e) => setErr(e.message));

  const start = () => api("/bulk/update", { method: "POST" }).then(refresh).catch(() => refresh());
  const j = status?.job;
  const mb = (n: number) => (n / 1048576).toFixed(0);
  return (
    <div className="max-w-2xl">
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">Settings</h1>
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-semibold">Card database (Scryfall)</h2>
        <p className="mt-1 text-sm text-mute">
          {status ? <>{status.cards_in_db.toLocaleString()} printings in the database ·{" "}
            {status.bulk_age_days == null ? "never updated" : `updated ${Math.floor(status.bulk_age_days)} days ago`}</> : "…"}
        </p>
        <p className="mt-2 text-xs text-mute">Downloads the “Default Cards” file (~80 MB) once, as the Scryfall API asks, and also updates the EUR prices (Cardmarket). Cards already in your collection are never deleted.</p>
        <button className="btn-primary mt-4" disabled={running} onClick={start}>{running ? "Updating…" : "Update bulk data now"}</button>
        {j && j.state !== "idle" && (
          <div className="mt-4 text-sm" role="status">
            <div className={j.state === "error" ? "text-danger" : j.state === "done" ? "text-ok" : ""}>
              {LABEL[j.state]} {j.state === "download" && j.total > 0 && `${mb(j.done)} / ${mb(j.total)} MB`}
              {j.state === "import" && `${j.done.toLocaleString()} cards`}
              {j.state === "done" && ` — ${j.cards.toLocaleString()} cards`}
            </div>
            {j.state === "download" && j.total > 0 && (
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${(j.done / j.total) * 100}%` }} /></div>
            )}
            {j.error && <p className="mt-1 text-xs text-danger">{j.error}</p>}
          </div>
        )}
      </section>
      <section className="mt-4 rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-semibold">Visual index (Scan)</h2>
        <p className="mt-1 text-sm text-mute">
          {status?.index && status.index.indexed > 0
            ? <>{status.index.indexed.toLocaleString()} of {status.index.eligible.toLocaleString()} printings indexed ·{" "}
              {status.index.indexed < status.index.eligible ? "pilot" : "complete"}</>
            : "No index: Scan uses OCR only."}
        </p>
        <p className="mt-2 text-xs text-mute">
          Identifies the exact printing from the artwork. <b>Pilot</b> (~5,000 printings: your collection, its reprints and some distractors) takes a few minutes.
          <b> Full</b> covers every printing (~110,000 images, ~12 GB, several hours); both can be stopped and resumed, and running them again only adds new printings.
          Images are downloaded from Scryfall at the standard rate limit.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-primary" disabled={building || running} onClick={() => startIndex("pilot")}>Build pilot index</button>
          <button className="btn-ghost" disabled={building || running} onClick={askFull}>Build full index…</button>
          {building && <button className="btn-ghost" onClick={stopIndex}>Stop</button>}
        </div>
        {est && !building && (
          <div className="mt-3 rounded-xl border border-line bg-raised p-3 text-sm">
            {est.printings === 0 ? "Nothing new to index." : <>{est.printings.toLocaleString()} new printings · ~{est.hours}+ h of downloads · ~{est.gb} GB in the data folder.</>}
            <div className="mt-2 flex gap-2">
              {est.printings > 0 && <button className="btn-primary" onClick={() => startIndex("all")}>Start</button>}
              <button className="btn-ghost" onClick={() => setEst(null)}>Cancel</button>
            </div>
          </div>
        )}
        {ij && ij.state !== "idle" && (
          <div className="mt-4 text-sm" role="status">
            <div className={ij.state === "error" ? "text-danger" : ij.state === "done" ? "text-ok" : ""}>
              {ij.state === "prepare" && "Preparing…"}
              {ij.state === "build" && `Indexing ${ij.done.toLocaleString()} / ${ij.total.toLocaleString()} (${ij.mode})${ij.detail ? ` · ${ij.detail}` : ""}`}
              {ij.state === "done" && `Done${ij.failed ? ` — ${ij.failed} images failed, run again to retry` : ""}`}
              {ij.state === "stopped" && "Stopped — start again to resume"}
              {ij.state === "error" && "Error"}
            </div>
            {ij.state === "build" && ij.total > 0 && (
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${(ij.done / ij.total) * 100}%` }} /></div>
            )}
            {ij.error && <p className="mt-1 text-xs text-danger">{ij.error}</p>}
          </div>
        )}
        {err && <p className="mt-2 text-xs text-danger">{err}</p>}
      </section>
      <PlaymatSection />
      <UpdateSection refresh={refresh} />
      <BackupSection pending={status?.restore_pending} />
      <GpuSection />
      <p className="mt-6 text-xs text-mute">Scrybinder {status?.version} · Card data and images © Scryfall (scryfall.com). Scrybinder is an unofficial project and is not affiliated with Wizards of the Coast. Magic: The Gathering is a trademark of Wizards of the Coast.</p>
    </div>
  );
}
