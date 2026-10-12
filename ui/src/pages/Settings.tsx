import { useEffect, useState } from "react";
import { api, Status } from "../api";

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
              {ij.state === "build" && `Indexing ${ij.done.toLocaleString()} / ${ij.total.toLocaleString()} (${ij.mode})`}
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
      <p className="mt-6 text-xs text-mute">Scrybinder {status?.version} · Card data and images © Scryfall (scryfall.com). Scrybinder is an unofficial project and is not affiliated with Wizards of the Coast. Magic: The Gathering is a trademark of Wizards of the Coast.</p>
    </div>
  );
}
