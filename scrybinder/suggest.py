"""Card suggestions for a Commander deck, with what you own: from EDHREC (opt-in) or, without it, from your collection by popularity."""
import json

from . import decks, edhrec

# a card is listed once, under the first of these that has it (the type lists before the "top / lift / new" ones)
ORDER = ["creatures", "instants", "sorceries", "utilityartifacts", "manaartifacts", "enchantments", "planeswalkers", "battles",
         "utilitylands", "lands", "topcards", "highliftcards", "newcards"]
COLLECTION_LIMIT = 150


def _commanders(db, deck_id: int) -> list[dict]:
    d = decks._deck(db, deck_id)
    if d["format"] != "commander":
        raise ValueError("suggestions are for Commander decks")
    rows = [dict(r) for r in db.execute(
        "SELECT o.oracle_id, o.name, o.color_identity FROM deck_cards d JOIN oracle_cards o ON o.oracle_id = d.oracle_id"
        " WHERE d.deck_id=? AND d.board='commander' ORDER BY d.id", (deck_id,))]
    if not rows:
        raise ValueError("this deck has no commander yet: put one in the Commander section")
    return rows[:2]


def _have(db, oracle_ids: list[str]) -> dict:
    """Per oracle id: copies owned (proxies are not copies), copies assigned to decks, and the decks that hold them."""
    out = {o: {"owned": 0, "assigned": 0, "decks": [], "print": None} for o in oracle_ids}
    for k in range(0, len(oracle_ids), 400):
        chunk = oracle_ids[k:k + 400]
        mark = ",".join("?" * len(chunk))
        for o, n in db.execute(f"SELECT k.oracle_id, SUM(c.quantity) FROM collection c JOIN cards k ON k.id = c.scryfall_id"
                               f" WHERE c.proxy = 0 AND k.oracle_id IN ({mark}) GROUP BY k.oracle_id", chunk):
            out[o]["owned"] = n
        # the printing you own (most copies, newest on a tie: the one a card gets when it is added to a deck), so the image is yours
        for o, sid in db.execute(f"SELECT k.oracle_id, c.scryfall_id FROM collection c JOIN cards k ON k.id = c.scryfall_id"
                                 f" WHERE c.proxy = 0 AND k.oracle_id IN ({mark}) ORDER BY c.quantity ASC, k.released_at ASC, c.id DESC", chunk):
            out[o]["print"] = sid
        for o, n, name in db.execute(
                f"SELECT k.oracle_id, SUM(a.quantity), dk.name FROM deck_assignments a JOIN deck_cards dc ON dc.id = a.deck_card_id"
                f" JOIN decks dk ON dk.id = dc.deck_id JOIN collection c ON c.id = a.collection_id JOIN cards k ON k.id = c.scryfall_id"
                f" WHERE k.oracle_id IN ({mark}) GROUP BY k.oracle_id, dk.id ORDER BY dk.name", chunk):
            out[o]["assigned"] += n
            out[o]["decks"].append(name)
    return out


def _fits(row, identity: set, in_deck: set) -> bool:
    """Not in the deck yet, legal in Commander, inside the commander's colors, and not a basic land."""
    legal = json.loads(row["legalities"] or "{}").get("commander") in ("legal", "restricted")
    return (row["oracle_id"] not in in_deck and legal and set(json.loads(row["color_identity"] or "[]")) <= identity
            and "Basic Land" not in (row["type_line"] or ""))


def _card(row, have, image_id=None, **extra) -> dict:
    """A suggestion; its image is the printing you own when you own the card, else `image_id` (EDHREC's / the newest printing)."""
    h = have[row["oracle_id"]]
    return {"oracle_id": row["oracle_id"], "name": row["name"], "mana_cost": row["mana_cost"], "type_line": row["type_line"],
            "owned": h["owned"], "free": max(h["owned"] - h["assigned"], 0), "elsewhere": h["decks"], "image_id": h["print"] or image_id, **extra}


def suggestions(db, deck_id: int, data_dir, use_edhrec: bool) -> dict:
    """{source, commander, cards[]} for a Commander deck. With EDHREC: its lists (inclusion %, synergy, lift) for the commander(s);
    otherwise the cards you own that fit the deck, most popular first (Scryfall's EDHREC rank). Cards already in the deck are left out."""
    cmd = _commanders(db, deck_id)
    identity = {c for r in cmd for c in json.loads(r["color_identity"] or "[]")}
    in_deck = {r[0] for r in db.execute("SELECT oracle_id FROM deck_cards WHERE deck_id=?", (deck_id,))}
    cols = "o.oracle_id, o.name, o.mana_cost, o.type_line, o.color_identity, o.legalities"
    if use_edhrec:
        data = edhrec.fetch(edhrec.slug([r["name"] for r in cmd]), data_dir)
        picked, seen = [], set()
        for tag in ORDER:
            for lst in (l for l in data["lists"] if l["tag"] == tag):
                ids = [c["id"] for c in lst["cards"] if c["id"]]
                oracle = {}
                for k in range(0, len(ids), 400):
                    mark = ",".join("?" * len(ids[k:k + 400]))
                    oracle.update(db.execute(f"SELECT id, oracle_id FROM cards WHERE id IN ({mark})", ids[k:k + 400]).fetchall())
                for c in lst["cards"]:
                    o = oracle.get(c["id"])
                    if o and o not in seen:
                        seen.add(o)
                        picked.append((o, c, lst))
        rows = {}
        oids = [p[0] for p in picked]
        for k in range(0, len(oids), 400):
            mark = ",".join("?" * len(oids[k:k + 400]))
            rows.update({r["oracle_id"]: r for r in db.execute(f"SELECT {cols} FROM oracle_cards o WHERE o.oracle_id IN ({mark})", oids[k:k + 400])})
        have = _have(db, oids)
        cards = [_card(rows[o], have, image_id=c["id"], category=lst["header"], category_key=lst["tag"],
                       inclusion=(c["num_decks"] / c["potential_decks"]) if c.get("potential_decks") else None, synergy=c.get("synergy"), lift=c.get("lift"))
                 for o, c, lst in picked if o in rows and _fits(rows[o], identity, in_deck)]
        return {"source": "edhrec", "stale": data["stale"], "fetched": data["fetched"], "slug": data["slug"],
                "commander": {"names": [r["name"] for r in cmd], **data["card"]}, "cards": cards}
    ids = [r[0] for r in db.execute("SELECT DISTINCT k.oracle_id FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE c.proxy = 0 AND k.oracle_id IS NOT NULL")]
    owned = []
    for k in range(0, len(ids), 400):
        mark = ",".join("?" * len(ids[k:k + 400]))
        owned += db.execute(f"SELECT {cols}, o.edhrec_rank FROM oracle_cards o WHERE o.oracle_id IN ({mark})", ids[k:k + 400]).fetchall()
    owned.sort(key=lambda r: (r["edhrec_rank"] is None, r["edhrec_rank"] or 0, r["name"]))
    fit = [r for r in owned if _fits(r, identity, in_deck)][:COLLECTION_LIMIT]
    have = _have(db, [r["oracle_id"] for r in fit])
    best = {r["oracle_id"]: (db.execute("SELECT id FROM cards WHERE oracle_id=? AND digital=0 AND image_small IS NOT NULL ORDER BY released_at DESC LIMIT 1", (r["oracle_id"],)).fetchone() or [None])[0] for r in fit}
    return {"source": "collection", "stale": False, "commander": {"names": [r["name"] for r in cmd]},
            "cards": [_card(r, have, image_id=best.get(r["oracle_id"]), category="Your collection", category_key="collection", inclusion=None, synergy=None, lift=None) for r in fit]}
