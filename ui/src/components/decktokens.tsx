import { ReactNode, useEffect, useState } from "react";
import { api, img } from "../api";

type Token = { image_id: string; name: string; type_line: string | null; made_by: string[] };

/** A collapsed line under the deck ("Tokens (7) – Expand") that opens its content, like Moxfield. `force` keeps it open. */
export function Fold({ title, count, force, children }: { title: string; count: number; force?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const shown = open || !!force;
  return (
    <section className="mt-6 border-t border-line pt-3" aria-label={title}>
      <h3 className="text-sm font-semibold">{title} ({count})
        <button className="ml-2 cursor-pointer font-normal text-accent hover:underline" aria-expanded={shown} onClick={() => setOpen(!open)}>{shown ? "– Collapse" : "– Expand"}</button>
      </h3>
      {shown && <div className="mt-3">{children}</div>}
    </section>
  );
}

/** The tokens the cards of the deck make, one image per kind, with the cards that make it. `rev` changes when the cards do. */
export default function DeckTokens({ deckId, rev, grid }: { deckId: number; rev?: unknown; grid: { style: React.CSSProperties } }) {
  const [tokens, setTokens] = useState<Token[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;  // a slower, older answer must not overwrite a newer one
    api<Token[]>(`/decks/${deckId}/tokens`).then((t) => { if (live) { setTokens(t); setErr(""); } }).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [deckId, rev]);
  if (err) return <p className="mt-6 text-danger">Tokens: {err}</p>;
  if (!tokens) return null;
  return (
    <Fold title="Tokens" count={tokens.length}>
      {!tokens.length ? <p className="text-mute">No tokens: none of the cards in the main deck makes one (or the card database has no token data yet: Settings → update the card database).</p> : (
        <div className="grid gap-4" style={grid.style}>
          {tokens.map((t) => <img key={t.image_id} src={img(t.image_id)} alt={t.name} title={`${t.name} · made by ${t.made_by.join(", ")}`} loading="lazy" className="w-full rounded-[4.5%/3.2%]" />)}
        </div>
      )}
    </Fold>
  );
}
