import { useEffect, useState } from "react";
import { api, img } from "../api";

type Token = { image_id: string; name: string; type_line: string | null; made_by: string[] };

/** The tokens the cards of the deck make, one image per kind, with the cards that make it. */
export default function DeckTokens({ deckId }: { deckId: number }) {
  const [tokens, setTokens] = useState<Token[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Token[]>(`/decks/${deckId}/tokens`).then(setTokens).catch((e) => setErr(e.message)); }, [deckId]);
  if (err) return <p className="text-danger">{err}</p>;
  if (!tokens) return <p className="text-mute">Loading…</p>;
  if (!tokens.length) return <p className="text-mute">No tokens: none of the cards in the main deck makes one (or the card database has no token data yet: Settings → update the card database).</p>;
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
      {tokens.map((t) => (
        <figure key={t.image_id} className="m-0">
          <img src={img(t.image_id)} alt={t.name} loading="lazy" className="w-full rounded-[4.5%/3.2%]" />
          <figcaption className="mt-1 text-xs text-mute"><span className="text-ink">{t.name}</span>{t.type_line && t.type_line !== "Token" && <> ({t.type_line.replace("Token ", "")})</>} · made by {t.made_by.join(", ")}</figcaption>
        </figure>
      ))}
    </div>
  );
}
