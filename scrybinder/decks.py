"""Decks: their own card list (by oracle card) with a board, a preferred printing and tags per card.
Cards can be assigned physical copies of the collection (reserved for that deck); a card's status says how much of
it is assigned, free to assign, held by other decks, or has to be bought."""
import csv
import io
import json
import re
import sqlite3

from . import cardmarket, deckrules, deckstats

FORMATS = ("commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual")
BOARDS = ("main", "side", "commander", "maybe")  # maybe never counts towards size, legality or statistics
TAG_MAX = 30
PROXY = "proxy"  # defined tag: the card is in the deck but is not a real copy
LOC_PREFIX = "Deck: "  # every deck is also a collection location, named after it; the prefix is reserved

# copies owned (proxy rows of the collection are not real copies) and the cheapest price of the oracle card
_CARD_SQL = """
SELECT x.*, (SELECT cardmarket_id FROM cards WHERE id = x.image_id) AS cardmarket_id,
       (SELECT set_code FROM cards WHERE id = x.scryfall_id) AS set_code,
       (SELECT set_name FROM cards WHERE id = x.scryfall_id) AS set_name,
       (SELECT collector_number FROM cards WHERE id = x.scryfall_id) AS collector_number FROM (
SELECT d.id, d.oracle_id, d.scryfall_id, d.finish, d.quantity, d.board, o.name, o.mana_cost, o.cmc, o.type_line, o.colors, o.color_identity,
       o.produced_mana, o.game_changer, o.power, o.toughness,
       (SELECT COALESCE(SUM(c.quantity), 0) FROM collection c JOIN cards k ON k.id = c.scryfall_id
         WHERE k.oracle_id = d.oracle_id AND c.proxy = 0) AS owned,
       (SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE deck_card_id = d.id) AS assigned,
       (SELECT COALESCE(SUM(a.quantity), 0) FROM deck_assignments a JOIN collection c ON c.id = a.collection_id
          JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id = d.oracle_id) AS assigned_all,
       COALESCE((SELECT @PRICE@ FROM cards WHERE id = d.scryfall_id),
                (SELECT MIN(@NONFOIL@) FROM cards WHERE oracle_id = d.oracle_id AND @NONFOIL@ IS NOT NULL)) AS price,
       COALESCE(d.scryfall_id,  -- the printing whose image the app shows (/api/image/<id>)
                (SELECT id FROM cards WHERE oracle_id = d.oracle_id AND digital = 0 AND image_small IS NOT NULL
                  ORDER BY released_at DESC LIMIT 1)) AS image_id
FROM deck_cards d JOIN oracle_cards o ON o.oracle_id = d.oracle_id
WHERE d.deck_id = ?) x ORDER BY x.board, x.name, x.id
"""


def _int(v) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise ValueError("quantity must be a whole number")
    return int(v)


def _tags(tags) -> list[str]:
    if isinstance(tags, str) or not isinstance(tags or [], (list, tuple)):
        raise ValueError("tags must be a list")
    out = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t).strip().lower())
        if not t or len(t) > TAG_MAX:
            raise ValueError(f"a tag must have 1 to {TAG_MAX} characters")
        if t not in out:
            out.append(t)
    return out


def _check(format=None, board=None):
    if format is not None and format not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    if board is not None and board not in BOARDS:
        raise ValueError(f"board must be one of {', '.join(BOARDS)}")


def _deck(db, deck_id: int):
    row = db.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
    if not row:
        raise KeyError(deck_id)
    return row


def _set_tags(db, card_id: int, tags):
    db.execute("DELETE FROM deck_card_tags WHERE deck_card_id=?", (card_id,))
    db.executemany("INSERT INTO deck_card_tags VALUES (?,?)", [(card_id, t) for t in _tags(tags)])


def cards(db, deck_id: int) -> list[dict]:
    """The deck's cards with their state. For each card, need = quantity - assigned and the free copies of the oracle card
    (owned - assigned to any deck) are shared out in order, so two boards of the same card do not both claim the same copy:
    - `proxy`: tagged proxy, present but never missing;
    - `basic`: a basic land with no printing chosen, never missing (a printing, e.g. a full art, makes it count like any card);
    - `assigned`: every copy is assigned;
    - `available`: free copies cover the rest (assign them);
    - `elsewhere`: not enough free copies and some are assigned to other decks (`elsewhere` lists them);
    - `missing`: not enough copies at all. `missing` is what has to be bought."""
    tags, assignments, elsewhere = {}, {}, {}
    for cid, t in db.execute("SELECT deck_card_id, tag FROM deck_card_tags WHERE deck_card_id IN"
                             " (SELECT id FROM deck_cards WHERE deck_id=?) ORDER BY tag", (deck_id,)):
        tags.setdefault(cid, []).append(t)
    for cid, coll, q in db.execute("SELECT deck_card_id, collection_id, quantity FROM deck_assignments WHERE deck_card_id IN"
                                   " (SELECT id FROM deck_cards WHERE deck_id=?) ORDER BY collection_id", (deck_id,)):
        assignments.setdefault(cid, []).append({"collection_id": coll, "quantity": q})
    held = {}  # what the assigned copies really are (printing and finish), so the deck follows the collection
    for cid, sid, fin, setc, num, setn, q in db.execute(
            "SELECT a.deck_card_id, c.scryfall_id, c.finish, k.set_code, k.collector_number, k.set_name, SUM(a.quantity) FROM deck_assignments a"
            " JOIN collection c ON c.id = a.collection_id JOIN cards k ON k.id = c.scryfall_id WHERE a.deck_card_id IN"
            " (SELECT id FROM deck_cards WHERE deck_id=?) GROUP BY a.deck_card_id, c.scryfall_id, c.finish ORDER BY SUM(a.quantity) DESC, c.id", (deck_id,)):
        held.setdefault(cid, []).append({"scryfall_id": sid, "finish": fin, "set_code": setc, "collector_number": num, "set_name": setn, "quantity": q})
    for oid, did, name, q in db.execute(
            "SELECT k.oracle_id, dk.id, dk.name, SUM(a.quantity) FROM deck_assignments a"
            " JOIN deck_cards dc ON dc.id = a.deck_card_id JOIN decks dk ON dk.id = dc.deck_id"
            " JOIN collection c ON c.id = a.collection_id JOIN cards k ON k.id = c.scryfall_id"
            " WHERE dk.id != ? AND k.oracle_id IN (SELECT oracle_id FROM deck_cards WHERE deck_id=?)"
            " GROUP BY k.oracle_id, dk.id ORDER BY dk.name", (deck_id, deck_id)):
        elsewhere.setdefault(oid, []).append({"deck_id": did, "name": name, "quantity": q})
    out, pool = [], {}
    sql = _CARD_SQL.replace("@PRICE@", cardmarket.finish_price_sql(db, "deck", "d.finish")).replace("@NONFOIL@", cardmarket.price_sql(db, "deck"))
    for row in db.execute(sql, (deck_id,)):
        r = dict(row)
        r["colors"] = json.loads(r["colors"] or "[]")
        r["color_identity"] = json.loads(r["color_identity"] or "[]")
        r["produced_mana"] = json.loads(r["produced_mana"] or "[]")
        r["game_changer"] = bool(r["game_changer"])
        r["tags"] = tags.get(r["id"], [])
        r["assignments"] = assignments.get(r["id"], [])
        r["owned_prints"] = held.get(r["id"], [])
        if not r["scryfall_id"] and r["owned_prints"]:  # no printing chosen: the card looks like the copy you assigned
            r["image_id"] = r["owned_prints"][0]["scryfall_id"]
        r["elsewhere"] = elsewhere.get(r["oracle_id"], [])
        free = pool.setdefault(r["oracle_id"], max(r["owned"] - r["assigned_all"], 0))
        need = max(r["quantity"] - r["assigned"], 0)
        take = min(need, free)
        if r["board"] != "maybe":
            pool[r["oracle_id"]] = free - take
        if PROXY in r["tags"]:
            r["missing"], r["status"] = 0, "proxy"
        else:
            r["missing"] = need - take
            r["status"] = ("assigned" if not need else "available" if not r["missing"]
                           else "elsewhere" if r["elsewhere"] else "missing")
        if (r["status"] in ("available", "elsewhere", "missing") and not r["scryfall_id"]
                and "Basic Land" in (r["type_line"] or "")):  # a basic land with no printing chosen: owning it or not does not matter
            r["missing"], r["status"] = 0, "basic"
        r["available"] = 0 if PROXY in r["tags"] or r["status"] == "basic" else take
        out.append(r)
    return out


INCLUDE = {"assigned": "collection", "available": "collection", "elsewhere": "elsewhere", "proxy": "proxy", "missing": "missing", "basic": "collection"}  # card status -> export option


def include_only(cs: list[dict], include) -> list[dict]:
    """The cards whose state is among `include` (any of collection, elsewhere, proxy, missing); None keeps them all."""
    if include is None:
        return cs
    if not isinstance(include, (list, tuple, set)) or not all(isinstance(i, str) for i in include) or not set(include) <= set(INCLUDE.values()):
        raise ValueError("include must list some of: " + ", ".join(sorted(set(INCLUDE.values()))))
    return [c for c in cs if INCLUDE[c["status"]] in include]


def summary(cs: list[dict]) -> dict:
    """Counts over the boards that make the deck (everything but `maybe`)."""
    real = [c for c in cs if c["board"] != "maybe"]
    return {"cards": sum(c["quantity"] for c in real),
            "assigned": sum(c["assigned"] for c in real),
            "available": sum(c["available"] for c in real),  # free copies that could be assigned now
            "missing": sum(c["missing"] for c in real),
            "proxies": sum(c["quantity"] for c in real if PROXY in c["tags"]),
            "cost_to_complete": round(sum(c["missing"] * (c["price"] or 0) for c in real), 2)}


def _folder_ok(db, folder_id):
    if isinstance(folder_id, bool) or not isinstance(folder_id, (int, type(None))):
        raise ValueError("folder_id must be a folder id or null")
    if folder_id is not None and not db.execute("SELECT 1 FROM deck_folders WHERE id=?", (folder_id,)).fetchone():
        raise ValueError("that folder does not exist")


def create(db, name: str, format: str = "casual", description: str = "", folder_id: int | None = None) -> int:
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("a deck needs a name")
    _check(format=format)
    _folder_ok(db, folder_id)
    with db:
        return db.execute("INSERT INTO decks (name, format, description, folder_id) VALUES (?,?,?,?)",
                          (name, format, description or "", folder_id)).lastrowid


def get(db, deck_id: int) -> dict:
    deck = dict(_deck(db, deck_id))
    deck["cards"] = cards(db, deck_id)
    deck["summary"] = summary(deck["cards"])
    return deck


def listing(db) -> list[dict]:
    out = []
    for row in db.execute("SELECT * FROM decks ORDER BY updated_at DESC, id DESC").fetchall():
        d = dict(row)
        cs = cards(db, d["id"])
        d["summary"] = summary(cs)
        chosen = next((c["image_id"] for c in cs if c["id"] == d["cover_card_id"]), None)  # set from the card's menu
        d["cover"] = chosen or next((c["image_id"] for c in cs if c["board"] != "maybe"), None)  # else the commander's, boards sort first
        out.append(d)
    return out


def update(db, deck_id: int, **fields) -> None:
    _deck(db, deck_id)
    folder = {"folder_id": fields["folder_id"]} if "folder_id" in fields else {}  # None puts the deck outside every folder
    cover = {"cover_card_id": fields["cover_card_id"]} if "cover_card_id" in fields else {}  # None goes back to the default cover
    fields = {k: v for k, v in fields.items() if k in ("name", "format", "description") and v is not None}
    _check(format=fields.get("format"))
    if folder:
        _folder_ok(db, folder["folder_id"])
        fields.update(folder)
    if cover:
        if cover["cover_card_id"] is not None and not db.execute("SELECT 1 FROM deck_cards WHERE id=? AND deck_id=?", (cover["cover_card_id"], deck_id)).fetchone():
            raise ValueError("that card is not in this deck")
        fields.update(cover)
    if "name" in fields and not (isinstance(fields["name"], str) and fields["name"].strip()):
        raise ValueError("a deck needs a name")
    old = location_names(db)
    if fields:
        with db:
            db.execute(f"UPDATE decks SET {', '.join(k + '=?' for k in fields)}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                       " WHERE id=?", [*fields.values(), deck_id])
    if "name" in fields:
        _relocate(db, old)  # the deck's location follows its name


def delete(db, deck_id: int) -> None:
    from . import collection  # collection imports decks
    old = location_names(db)
    loc = old[_deck(db, deck_id)["id"]]
    before = _held(db, deck_id)
    with db:
        db.execute("DELETE FROM deck_assignments WHERE deck_card_id IN (SELECT id FROM deck_cards WHERE deck_id=?)", (deck_id,))
        settle(db, deck_id, before)
        for (rid,) in db.execute("SELECT id FROM collection WHERE location=?", (loc,)).fetchall():  # the location goes with the deck
            collection.update(db, rid, location="")
        db.execute("DELETE FROM decks WHERE id=?", (deck_id,))  # cards and tags go with it (ON DELETE CASCADE)
    _relocate(db, old)  # a later deck of the same name moves up to the plain name


def location_names(db) -> dict[int, str]:
    """The location of every deck: `Deck: <name>`, and `Deck: <name> (2)`, `(3)`... for the later decks with the same name."""
    seen, out = {}, {}
    for did, name in db.execute("SELECT id, name FROM decks ORDER BY id"):
        seen[name] = seen.get(name, 0) + 1
        out[did] = f"{LOC_PREFIX}{name}" + (f" ({seen[name]})" if seen[name] > 1 else "")
    return out


def _relocate(db, old: dict[int, str]) -> None:
    """A deck was renamed or deleted: the decks whose location name changed take their cards along."""
    from . import collection  # collection imports decks
    new = location_names(db)
    moves = [(old[i], new[i]) for i in new if i in old and old[i] != new[i]]
    with db:
        for a, b in moves:
            for (rid,) in db.execute("SELECT id FROM collection WHERE location=?", (a,)).fetchall():
                collection.update(db, rid, location=b)


def _held(db, deck_id: int) -> dict[int, int]:
    """Copies of each collection row that are assigned to this deck."""
    return dict(db.execute("SELECT a.collection_id, SUM(a.quantity) FROM deck_assignments a JOIN deck_cards d ON d.id = a.deck_card_id"
                           " WHERE d.deck_id=? GROUP BY a.collection_id", (deck_id,)).fetchall())


def _shift(db, row, q: int, to_loc: str) -> int:
    """Move q copies of a collection row to a location, merging into the identical row there; returns the destination row."""
    from . import collection  # collection imports decks
    if q == row["quantity"]:  # the whole row: it keeps its id, and its assignments follow if it merges into another
        return collection.update(db, row["id"], location=to_loc)
    d = dict(row)
    d.update(location=to_loc, quantity=q)
    dest = collection.add(db, **{k: v for k, v in d.items() if k not in ("id", "added_at")})
    db.execute("UPDATE collection SET quantity=quantity-? WHERE id=?", (q, row["id"]))
    return dest


def settle(db, deck_id: int, before: dict[int, int] | None = None) -> None:
    """Keep the deck's location in step with its assignments, after a change. The copies assigned to the deck move into the location
    `Deck: <name>` (see location_names; a row is split when only some of it is assigned); of the rows in `before` (what was assigned before the change)
    the copies that are no longer assigned leave the location for "(no location)". Only rows whose assignment changed are touched:
    a deck is never filled by a side effect."""
    _deck(db, deck_id)
    loc = location_names(db)[deck_id]
    now = _held(db, deck_id)
    with db:
        for coll, q in now.items():
            row = db.execute("SELECT * FROM collection WHERE id=?", (coll,)).fetchone()
            if row["location"] == loc or (before or {}).get(coll) == q:  # only the rows this change touched: what was assigned earlier stays where it is
                continue
            if q >= row["quantity"]:
                _shift(db, row, row["quantity"], loc)
                continue
            mine = db.execute("SELECT a.deck_card_id, a.quantity FROM deck_assignments a JOIN deck_cards d ON d.id = a.deck_card_id"
                              " WHERE d.deck_id=? AND a.collection_id=?", (deck_id, coll)).fetchall()
            db.execute("DELETE FROM deck_assignments WHERE collection_id=? AND deck_card_id IN (SELECT id FROM deck_cards WHERE deck_id=?)", (coll, deck_id))
            dest = _shift(db, row, q, loc)  # part of the row: split it, and this deck's assignments move to the new row
            db.executemany("INSERT INTO deck_assignments VALUES (?,?,?) ON CONFLICT(deck_card_id, collection_id)"
                           " DO UPDATE SET quantity = quantity + excluded.quantity", [(dc, dest, aq) for dc, aq in mine])
        for coll, was in (before or {}).items():
            cut = was - now.get(coll, 0)
            row = db.execute("SELECT * FROM collection WHERE id=?", (coll,)).fetchone() if cut > 0 else None
            if not row or row["location"] != loc:
                continue
            used = db.execute("SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE collection_id=?", (coll,)).fetchone()[0]
            cut = min(cut, row["quantity"] - used)  # copies that another deck holds stay
            if cut > 0:
                _shift(db, row, cut, "")


def _touch(db, deck_id: int):
    db.execute("UPDATE decks SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (deck_id,))


def _printing_ok(db, oracle_id: str, scryfall_id):
    if scryfall_id is not None and not db.execute("SELECT 1 FROM cards WHERE id=? AND oracle_id=?", (scryfall_id, oracle_id)).fetchone():
        raise ValueError("that printing is not a printing of this card")


def _finish_ok(db, scryfall_id, finish):
    """A finish needs a printing, and the printing has to come in it."""
    if finish is None:
        return
    if finish not in ("nonfoil", "foil", "etched"):
        raise ValueError("finish must be nonfoil, foil or etched")
    row = db.execute("SELECT finishes FROM cards WHERE id=?", (scryfall_id,)).fetchone() if scryfall_id else None
    if not row or finish not in json.loads(row["finishes"] or "[]"):
        raise ValueError("that printing does not come in that finish")


def _find(db, deck_id, oracle_id, scryfall_id, board, finish=None, exclude=None):
    """The line of the deck with this card, printing, finish and board (not `exclude`, the line being changed); lines of the same
    card may repeat on purpose, this finds the first."""
    return db.execute("SELECT id FROM deck_cards WHERE deck_id=? AND oracle_id=? AND COALESCE(scryfall_id,'')=? AND COALESCE(finish,'')=? AND board=? AND id IS NOT ?"
                      " ORDER BY id LIMIT 1", (deck_id, oracle_id, scryfall_id or "", finish or "", board, exclude)).fetchone()


def add_card(db, deck_id: int, oracle_id: str, quantity: int = 1, board: str = "main", scryfall_id=None, tags=(), finish=None, new_line=False) -> int:
    """Add a card; the same card on the same board with the same printing and finish sums the quantity, unless `new_line` asks for a
    line of its own (to give it another printing)."""
    _deck(db, deck_id)
    _check(board=board)
    quantity = _int(quantity)
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not db.execute("SELECT 1 FROM oracle_cards WHERE oracle_id=?", (oracle_id,)).fetchone():
        raise ValueError("unknown card (update the bulk data)")
    _printing_ok(db, oracle_id, scryfall_id)
    _finish_ok(db, scryfall_id, finish)
    tags = _tags(tags)
    with db:
        row = None if new_line else _find(db, deck_id, oracle_id, scryfall_id, board, finish)
        if row:
            db.execute("UPDATE deck_cards SET quantity=quantity+? WHERE id=?", (quantity, row["id"]))
            cid = row["id"]
            db.executemany("INSERT OR IGNORE INTO deck_card_tags VALUES (?,?)", [(cid, t) for t in tags])
        else:
            cid = db.execute("INSERT INTO deck_cards (deck_id, oracle_id, scryfall_id, quantity, board, finish) VALUES (?,?,?,?,?,?)",
                             (deck_id, oracle_id, scryfall_id, quantity, board, finish)).lastrowid
            _set_tags(db, cid, tags)
        _touch(db, deck_id)
    return cid


def default_printing(db, oracle_id: str) -> tuple[str | None, str | None]:
    """The printing (and finish) a card gets when none is chosen: the one you own most copies of (in your finish), else the cheapest
    printing, newest first on a tie. (None, None) when the card has no usable printing."""
    own = db.execute("SELECT c.scryfall_id, c.finish FROM collection c JOIN cards k ON k.id = c.scryfall_id"
                     " WHERE k.oracle_id=? AND c.proxy=0 ORDER BY c.quantity DESC, k.released_at DESC, c.id LIMIT 1", (oracle_id,)).fetchone()
    if own:
        return own["scryfall_id"], own["finish"]
    p = db.execute("SELECT id, finishes FROM cards WHERE oracle_id=? AND digital=0 AND image_small IS NOT NULL"
                   " ORDER BY COALESCE(eur, eur_foil, eur_etched, 1e9), released_at DESC LIMIT 1", (oracle_id,)).fetchone()
    return (p["id"], _first_finish(p["finishes"])) if p else (None, None)


def fill_printings(db, deck_id: int) -> int:
    """Give every line without a printing one: that of the copies assigned to it, else the default. Returns the lines changed."""
    _deck(db, deck_id)
    n = 0
    for c in cards(db, deck_id):
        if c["scryfall_id"]:
            continue
        if c["owned_prints"]:
            sid, fin = c["owned_prints"][0]["scryfall_id"], c["owned_prints"][0]["finish"]
        else:
            sid, fin = default_printing(db, c["oracle_id"])
        if sid:
            update_card(db, deck_id, c["id"], scryfall_id=sid, finish=fin)
            n += 1
    return n


def duplicate_line(db, deck_id: int, card_id: int) -> int:
    """One more copy of a card as a line of its own (same printing, finish, board and tags): the deck gets one card more, and the
    new line can take another printing."""
    cur = db.execute("SELECT * FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not cur:
        raise KeyError(card_id)
    return add_card(db, deck_id, cur["oracle_id"], 1, cur["board"], cur["scryfall_id"], sorted(_card_tags(db, card_id)), cur["finish"], new_line=True)


def _card_tags(db, card_id: int) -> set[str]:
    return {r[0] for r in db.execute("SELECT tag FROM deck_card_tags WHERE deck_card_id=?", (card_id,))}


def _trim(db, card_id: int):
    """A card cannot hold more copies than its quantity: drop assignments (highest collection id first) until it fits."""
    over = (db.execute("SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE deck_card_id=?", (card_id,)).fetchone()[0]
            - db.execute("SELECT quantity FROM deck_cards WHERE id=?", (card_id,)).fetchone()[0])
    for coll, q in db.execute("SELECT collection_id, quantity FROM deck_assignments WHERE deck_card_id=?"
                              " ORDER BY collection_id DESC", (card_id,)).fetchall():
        if over <= 0:
            break
        cut = min(q, over)
        over -= cut
        if cut == q:
            db.execute("DELETE FROM deck_assignments WHERE deck_card_id=? AND collection_id=?", (card_id, coll))
        else:
            db.execute("UPDATE deck_assignments SET quantity=quantity-? WHERE deck_card_id=? AND collection_id=?", (cut, card_id, coll))


def update_card(db, deck_id: int, card_id: int, **fields) -> int:
    """Change quantity, board, printing (`scryfall_id`, None for any), its finish and/or tags. Another printing with no finish
    given drops the finish. Returns the card's id, which is another
    one when the change merges it into a card that already exists."""
    cur = db.execute("SELECT * FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not cur:
        raise KeyError(card_id)
    board = fields.get("board", cur["board"])
    sid = fields["scryfall_id"] if "scryfall_id" in fields else cur["scryfall_id"]
    fin = fields["finish"] if "finish" in fields else (cur["finish"] if sid == cur["scryfall_id"] else None)
    qty = _int(fields.get("quantity", cur["quantity"]))
    _check(board=board)
    if qty < 1:
        raise ValueError("quantity must be >= 1")
    _printing_ok(db, cur["oracle_id"], sid)
    _finish_ok(db, sid, fin)
    tags = _tags(fields["tags"]) if "tags" in fields else None
    before = _held(db, deck_id)
    with db:
        moved = (sid, fin, board) != (cur["scryfall_id"], cur["finish"], cur["board"])  # only a change of printing, finish or board can land on another line
        other = _find(db, deck_id, cur["oracle_id"], sid, board, fin, exclude=card_id) if moved else None
        if other and other["id"] != card_id:  # moved onto an existing card: merge into it
            db.execute("UPDATE deck_cards SET quantity=quantity+? WHERE id=?", (qty, other["id"]))
            db.execute("INSERT OR IGNORE INTO deck_card_tags SELECT ?, tag FROM deck_card_tags WHERE deck_card_id=?",
                       (other["id"], card_id))
            db.execute("INSERT INTO deck_assignments SELECT ?, collection_id, quantity FROM deck_assignments WHERE deck_card_id=?"
                       " AND true ON CONFLICT(deck_card_id, collection_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                       (other["id"], card_id))
            db.execute("DELETE FROM deck_cards WHERE id=?", (card_id,))  # its assignments go with it (ON DELETE CASCADE)
            card_id = other["id"]
        else:
            db.execute("UPDATE deck_cards SET quantity=?, board=?, scryfall_id=?, finish=? WHERE id=?", (qty, board, sid, fin, card_id))
        if tags is not None:
            _set_tags(db, card_id, tags)
        if PROXY in _card_tags(db, card_id):  # a proxy is not a real copy: nothing to reserve
            db.execute("DELETE FROM deck_assignments WHERE deck_card_id=?", (card_id,))
        _trim(db, card_id)
        _touch(db, deck_id)
    settle(db, deck_id, before)
    return card_id


def remove_card(db, deck_id: int, card_id: int) -> None:
    before = _held(db, deck_id)
    with db:
        if not db.execute("DELETE FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).rowcount:
            raise KeyError(card_id)
        _touch(db, deck_id)
    settle(db, deck_id, before)


def duplicate(db, deck_id: int) -> int:
    """Copy of the deck with its cards and tags (assignments of physical copies are not copied)."""
    src = _deck(db, deck_id)
    with db:
        new = db.execute("INSERT INTO decks (name, format, description) VALUES (?,?,?)",
                         (f"{src['name']} (copy)", src["format"], src["description"])).lastrowid
        for c in db.execute("SELECT * FROM deck_cards WHERE deck_id=?", (deck_id,)).fetchall():
            cid = db.execute("INSERT INTO deck_cards (deck_id, oracle_id, scryfall_id, quantity, board, finish) VALUES (?,?,?,?,?,?)",
                             (new, c["oracle_id"], c["scryfall_id"], c["quantity"], c["board"], c["finish"])).lastrowid
            db.execute("INSERT INTO deck_card_tags SELECT ?, tag FROM deck_card_tags WHERE deck_card_id=?", (cid, c["id"]))
    return new


class Conflict(Exception):
    """An operation would break an assignment (HTTP 409); `decks` lists the decks that hold the copies."""

    def __init__(self, message: str, decks=()):
        super().__init__(message)
        self.decks = list(decks)


def users(db, collection_ids) -> list[dict]:
    """Decks that hold copies of these collection rows."""
    ids = list(dict.fromkeys(collection_ids))
    out = []
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        out += [dict(r) for r in db.execute(
            "SELECT a.collection_id, dk.id AS deck_id, dk.name, SUM(a.quantity) AS quantity FROM deck_assignments a"
            " JOIN deck_cards dc ON dc.id = a.deck_card_id JOIN decks dk ON dk.id = dc.deck_id"
            f" WHERE a.collection_id IN ({','.join('?' * len(chunk))}) GROUP BY a.collection_id, dk.id ORDER BY dk.name", chunk)]
    return out


def _conflict(rows: list[dict], what: str = "copies are assigned to") -> Conflict:
    return Conflict(f"{what}: " + ", ".join(dict.fromkeys(r["name"] for r in rows)), rows)


def check_row(db, row_id: int, quantity: int, proxy: bool = False, release: bool = False):
    """Call before a collection row is changed to `quantity` (and `proxy`): fewer copies than assigned, or a proxy, would
    break its assignments. `release=True` frees the row from its decks instead of refusing."""
    rows = users(db, [row_id])
    if rows and (proxy or quantity < sum(r["quantity"] for r in rows)):
        if not release:
            raise _conflict(rows)
        db.execute("DELETE FROM deck_assignments WHERE collection_id=?", (row_id,))


def check_delete(db, row_ids, release: bool = False):
    """Call before collection rows are deleted. With `release` the assignments go with the rows (ON DELETE CASCADE)."""
    rows = users(db, row_ids)
    if rows and not release:
        raise _conflict(rows)


def transfer(db, from_id: int, to_id: int):
    """A collection row was merged into another: its assignments follow (summed where a card already holds the other)."""
    db.execute("INSERT INTO deck_assignments SELECT deck_card_id, ?, quantity FROM deck_assignments WHERE collection_id=?"
               " AND true ON CONFLICT(deck_card_id, collection_id) DO UPDATE SET quantity = quantity + excluded.quantity",
               (to_id, from_id))


def assign(db, deck_id: int, card_id: int, items) -> None:
    """Replace the copies reserved for a deck card with `items` ([{collection_id, quantity}], quantity 0 drops the row)."""
    card = db.execute("SELECT * FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not card:
        raise KeyError(card_id)
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    want = {}
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each item needs collection_id and quantity")
        coll, q = _int(it.get("collection_id")), _int(it.get("quantity"))
        if q < 0:
            raise ValueError("quantity must be >= 0")
        want[coll] = want.get(coll, 0) + q
    want = {c: q for c, q in want.items() if q}
    if PROXY in _card_tags(db, card_id) and want:
        raise ValueError("a proxy has no real copies to assign")
    if sum(want.values()) > card["quantity"]:
        raise ValueError(f"the deck has {card['quantity']} of this card: cannot assign {sum(want.values())}")
    clash = []
    for coll, q in want.items():
        row = db.execute("SELECT c.quantity, c.proxy, k.oracle_id FROM collection c JOIN cards k ON k.id = c.scryfall_id"
                         " WHERE c.id=?", (coll,)).fetchone()
        if not row or row["oracle_id"] != card["oracle_id"]:
            raise ValueError(f"collection row {coll} is not a copy of this card")
        if row["proxy"]:
            raise ValueError(f"collection row {coll} is a proxy")
        held = db.execute("SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE collection_id=? AND deck_card_id!=?",
                          (coll, card_id)).fetchone()[0]
        if held + q > row["quantity"]:
            if not held:
                raise ValueError(f"collection row {coll} has {row['quantity']} copies")
            clash += users(db, [coll])
    if clash:
        raise _conflict(clash, "not enough free copies, assigned to")
    before = _held(db, deck_id)
    with db:
        db.execute("DELETE FROM deck_assignments WHERE deck_card_id=?", (card_id,))
        db.executemany("INSERT INTO deck_assignments VALUES (?,?,?)", [(card_id, c, q) for c, q in want.items()])
        _touch(db, deck_id)
    settle(db, deck_id, before)


def move_copy(db, deck_id: int, card_id: int, from_deck_id: int, collection_id: int, quantity: int = 1) -> int:
    """Take `quantity` copies of a collection row from another deck for this deck card: the other deck loses them (it shows the card as
    missing again) and the copies move into this deck's location. Returns how many were moved."""
    card = db.execute("SELECT * FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not card:
        raise KeyError(card_id)
    _deck(db, from_deck_id)
    quantity = _int(quantity)
    if from_deck_id == deck_id:
        raise ValueError("choose another deck")
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    if PROXY in _card_tags(db, card_id):
        raise ValueError("a proxy has no real copies to assign")
    row = db.execute("SELECT c.proxy, k.oracle_id FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE c.id=?", (collection_id,)).fetchone()
    if not row or row["oracle_id"] != card["oracle_id"] or row["proxy"]:
        raise ValueError(f"collection row {collection_id} is not a real copy of this card")
    theirs = db.execute("SELECT a.deck_card_id, a.quantity FROM deck_assignments a JOIN deck_cards d ON d.id = a.deck_card_id"
                        " WHERE d.deck_id=? AND a.collection_id=? ORDER BY a.quantity DESC, a.deck_card_id", (from_deck_id, collection_id)).fetchall()
    if quantity > sum(t["quantity"] for t in theirs):
        raise ValueError("that deck does not hold that many copies")
    have = db.execute("SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE deck_card_id=?", (card_id,)).fetchone()[0]
    if have + quantity > card["quantity"]:
        raise ValueError(f"the deck has {card['quantity']} of this card: cannot assign {have + quantity}")
    before_to, before_from = _held(db, deck_id), _held(db, from_deck_id)
    with db:
        left = quantity
        for t in theirs:
            take = min(left, t["quantity"])
            if take == t["quantity"]:
                db.execute("DELETE FROM deck_assignments WHERE deck_card_id=? AND collection_id=?", (t["deck_card_id"], collection_id))
            else:
                db.execute("UPDATE deck_assignments SET quantity=quantity-? WHERE deck_card_id=? AND collection_id=?", (take, t["deck_card_id"], collection_id))
            left -= take
            if not left:
                break
        db.execute("INSERT INTO deck_assignments VALUES (?,?,?) ON CONFLICT(deck_card_id, collection_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                   (card_id, collection_id, quantity))
        _touch(db, deck_id)
        _touch(db, from_deck_id)
    settle(db, deck_id, before_to)  # the copies go into this deck's location first; the other deck then finds them gone and leaves them there
    settle(db, from_deck_id, before_from)
    return quantity


def assign_free(db, deck_id: int, only=None) -> int:
    """Assign every free copy the deck still needs (preferred printing first), for the deck cards in `only` when given.
    Never touches existing assignments."""
    _deck(db, deck_id)
    n = 0
    before = _held(db, deck_id)
    with db:
        for c in cards(db, deck_id):
            if c["board"] == "maybe" or c["status"] in ("proxy", "basic") or (only is not None and c["id"] not in only):
                continue
            need = c["quantity"] - c["assigned"]
            if need <= 0:
                continue
            for row in db.execute(
                    "SELECT c.id, c.quantity - COALESCE((SELECT SUM(quantity) FROM deck_assignments WHERE collection_id = c.id), 0) AS free"
                    " FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id=? AND c.proxy=0"
                    " ORDER BY (c.scryfall_id = ?) DESC, (c.finish = ?) DESC, c.id", (c["oracle_id"], c["scryfall_id"] or "", c["finish"] or "")).fetchall():
                take = min(need, row["free"])
                if take > 0:
                    db.execute("INSERT INTO deck_assignments VALUES (?,?,?) ON CONFLICT(deck_card_id, collection_id)"
                               " DO UPDATE SET quantity = quantity + excluded.quantity", (c["id"], row["id"], take))
                    need -= take
                    n += take
        if n:
            _touch(db, deck_id)
    if n:
        settle(db, deck_id, before)
    return n


def _first_finish(finishes_json) -> str:
    fin = json.loads(finishes_json or "[]")
    return "nonfoil" if "nonfoil" in fin or not fin else "foil" if "foil" in fin else "etched"


def add_copy(db, deck_id: int, card_id: int, quantity=1, location: str = "") -> int:
    """Put copies of the printing a deck card prefers (in its finish) into the collection and assign them to that card, even when
    you own the card in another printing (which is why it is not "missing"). Returns the copies added."""
    from . import collection  # collection imports decks
    card = db.execute("SELECT scryfall_id, finish FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not card:
        raise KeyError(card_id)
    if not card["scryfall_id"]:
        raise ValueError("choose a printing for this card first")
    quantity = _int(quantity)
    if not 1 <= quantity <= 999:
        raise ValueError("quantity must be between 1 and 999")
    finishes = db.execute("SELECT finishes FROM cards WHERE id=?", (card["scryfall_id"],)).fetchone()["finishes"]
    collection.add(db, scryfall_id=card["scryfall_id"], quantity=quantity, finish=card["finish"] or _first_finish(finishes), location=location)
    assign_free(db, deck_id, {card_id})
    return quantity


def add_missing(db, deck_id: int, card_ids=None, location: str = "") -> int:
    """Put the copies a deck is missing into the collection (proxies and the maybeboard never are), then assign them.
    `card_ids` limits it to those deck cards. The printing is the preferred one, else the cheapest. Returns the copies added."""
    from . import collection  # collection imports decks
    _deck(db, deck_id)
    if card_ids is not None and not isinstance(card_ids, list):
        raise ValueError("card_ids must be a list")
    only = None if card_ids is None else {_int(i) for i in card_ids}
    n = 0
    with db:
        for c in cards(db, deck_id):
            if c["missing"] <= 0 or c["board"] == "maybe" or (only is not None and c["id"] not in only):
                continue
            p = db.execute("SELECT id, finishes FROM cards WHERE oracle_id=? AND digital=0"
                           " ORDER BY (id=?) DESC, COALESCE(eur, eur_foil, eur_etched, 1e9), released_at DESC LIMIT 1",
                           (c["oracle_id"], c["scryfall_id"] or "")).fetchone()
            if not p:
                continue
            finish = _first_finish(p["finishes"])
            if c["finish"] and p["id"] == c["scryfall_id"]:
                finish = c["finish"]  # the deck wants this finish of its printing
            collection.add(db, scryfall_id=p["id"], quantity=c["missing"], finish=finish, location=location)
            n += c["missing"]
    if n:
        assign_free(db, deck_id, only)
    return n


def legality(db, deck_id: int, reference: str | None = None) -> dict:
    """Problems of the deck in its format (`reference`: the format whose per-card legality a casual deck is checked against)."""
    deck = _deck(db, deck_id)
    if reference is not None and reference not in FORMATS[:-1]:
        raise ValueError(f"reference must be one of {', '.join(FORMATS[:-1])}")
    rows = [dict(r) for r in db.execute(
        "SELECT d.board, d.quantity, o.name, o.type_line, o.oracle_text, o.keywords, o.color_identity, o.legalities, o.game_changer"
        " FROM deck_cards d JOIN oracle_cards o ON o.oracle_id = d.oracle_id WHERE d.deck_id=? ORDER BY d.board, o.name", (deck_id,))]
    for r in rows:
        for k in ("keywords", "color_identity", "legalities"):
            r[k] = json.loads(r[k] or ("{}" if k == "legalities" else "[]"))
    return deckrules.check(deck["format"], rows, reference)


def stats(db, deck_id: int) -> dict:
    """Statistics of the main deck and commander (see deckstats) plus what is left to buy."""
    _deck(db, deck_id)
    cs = cards(db, deck_id)
    return {**deckstats.compute(cs), "cost_to_complete": summary([c for c in cs if c["board"] in deckstats.BOARDS])["cost_to_complete"]}


FOLDER_NAME_MAX = 60


def _folder_name(name) -> str:
    name = re.sub(r"\s+", " ", name.strip()) if isinstance(name, str) else ""
    if not name or len(name) > FOLDER_NAME_MAX:
        raise ValueError(f"a folder name has 1 to {FOLDER_NAME_MAX} characters")
    return name


def folders(db) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT f.id, f.name, (SELECT COUNT(*) FROM decks d WHERE d.folder_id = f.id) AS decks FROM deck_folders f ORDER BY f.name")]


def create_folder(db, name: str) -> int:
    name = _folder_name(name)
    try:
        with db:
            return db.execute("INSERT INTO deck_folders (name) VALUES (?)", (name,)).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"there is already a folder called {name}") from None


def rename_folder(db, folder_id: int, name: str) -> None:
    name = _folder_name(name)
    if not db.execute("SELECT 1 FROM deck_folders WHERE id=?", (folder_id,)).fetchone():
        raise KeyError(folder_id)
    try:
        with db:
            db.execute("UPDATE deck_folders SET name=? WHERE id=?", (name, folder_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"there is already a folder called {name}") from None


def delete_folder(db, folder_id: int) -> None:
    """Delete a folder; its decks stay, outside every folder (ON DELETE SET NULL)."""
    with db:
        if not db.execute("DELETE FROM deck_folders WHERE id=?", (folder_id,)).rowcount:
            raise KeyError(folder_id)


def copies(db, deck_id: int, card_id: int) -> dict:
    """The copies of the collection that can go to a deck card (proxy rows are not copies): per row how many are assigned
    to this card (`here`) and to which other cards' decks (`elsewhere`), so the dialog can say how many are free."""
    card = db.execute("SELECT oracle_id, scryfall_id, finish, quantity FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not card:
        raise KeyError(card_id)
    rows = [dict(r) for r in db.execute(
        "SELECT c.id, c.scryfall_id, c.quantity, c.finish, c.condition, c.language, c.location, c.altered, c.signed, c.misprint,"
        " k.set_code, k.set_name, k.collector_number,"
        " " + cardmarket.finish_price_sql(db, "deck", "c.finish", "k.") + " AS price,"
        " COALESCE((SELECT quantity FROM deck_assignments WHERE deck_card_id=? AND collection_id=c.id), 0) AS here"
        " FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id=? AND c.proxy=0"
        " ORDER BY (c.scryfall_id = ?) DESC, (c.finish = ?) DESC, k.released_at DESC, c.id", (card_id, card["oracle_id"], card["scryfall_id"] or "", card["finish"] or ""))]
    other = {}
    for coll, did, name, q in db.execute(
            "SELECT a.collection_id, dk.id, dk.name, SUM(a.quantity) FROM deck_assignments a"
            " JOIN deck_cards dc ON dc.id = a.deck_card_id JOIN decks dk ON dk.id = dc.deck_id"
            f" WHERE a.deck_card_id != ? AND a.collection_id IN ({','.join('?' * len(rows)) or 'NULL'})"
            " GROUP BY a.collection_id, dk.id ORDER BY dk.name", [card_id, *[r["id"] for r in rows]]):
        other.setdefault(coll, []).append({"deck_id": did, "name": name, "quantity": q})
    for r in rows:
        r["elsewhere"] = other.get(r["id"], [])
        r["free"] = max(r["quantity"] - r["here"] - sum(e["quantity"] for e in r["elsewhere"]), 0)
    return {"quantity": card["quantity"], "rows": rows}


def shopping_list(db, include_side: bool = False) -> dict:
    """What is still missing across every deck, one entry per card: the sum of each deck's `missing` (what the deck would have to buy;
    a free copy two decks both see as available is not shared out between them). `maybe` never counts; `side` only on request."""
    boards = ("main", "commander") + (("side",) if include_side else ())
    items = {}
    for d in db.execute("SELECT id, name FROM decks ORDER BY name, id").fetchall():
        for c in cards(db, d["id"]):
            if c["board"] not in boards or not c["missing"]:
                continue
            it = items.setdefault(c["oracle_id"], {"oracle_id": c["oracle_id"], "name": c["name"], "needed": 0, "price": c["price"],
                                                   "cardmarket_id": c["cardmarket_id"], "decks": []})
            it["needed"] += c["missing"]
            if it["price"] is None:
                it["price"] = c["price"]
            mine = next((x for x in it["decks"] if x["deck_id"] == d["id"]), None)
            if mine:
                mine["needed"] += c["missing"]
            else:
                it["decks"].append({"deck_id": d["id"], "name": d["name"], "needed": c["missing"]})
    out = sorted(items.values(), key=lambda i: i["name"].lower())
    for it in out:
        it["line_total"] = round(it["needed"] * (it["price"] or 0), 2)
    return {"items": out, "total_needed": sum(i["needed"] for i in out), "total_value": round(sum(i["line_total"] for i in out), 2)}


def shopping_text(sl: dict) -> str:
    """`N Name` per line: what Cardmarket's want-list search accepts pasted."""
    return "".join(f"{i['needed']} {i['name']}\n" for i in sl["items"])


def shopping_csv(sl: dict) -> str:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["quantity", "name", "price_eur", "cardmarket_id"])
    w.writerows([i["needed"], i["name"], "" if i["price"] is None else i["price"], i["cardmarket_id"] or ""] for i in sl["items"])
    return buf.getvalue()


SNAPSHOT_NAME_MAX = 60


def _snapshot(db, deck_id: int, snapshot_id: int):
    _deck(db, deck_id)
    row = db.execute("SELECT * FROM deck_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise KeyError(snapshot_id)
    if row["deck_id"] != deck_id:
        raise ValueError("that snapshot belongs to another deck")
    return row


def save_snapshot(db, deck_id: int, name) -> int:
    """Save the deck's cards as they are now (name, board, quantity, printing and price; not tags or assigned copies)."""
    _deck(db, deck_id)
    name = re.sub(r"\s+", " ", name.strip()) if isinstance(name, str) else ""
    if not name or len(name) > SNAPSHOT_NAME_MAX:
        raise ValueError(f"a snapshot name has 1 to {SNAPSHOT_NAME_MAX} characters")
    with db:
        sid = db.execute("INSERT INTO deck_snapshots (deck_id, name) VALUES (?, ?)", (deck_id, name)).lastrowid
        db.executemany("INSERT INTO deck_snapshot_cards (snapshot_id, oracle_id, scryfall_id, finish, board, quantity, name, price) VALUES (?,?,?,?,?,?,?,?)",
                       [(sid, c["oracle_id"], c["scryfall_id"], c["finish"], c["board"], c["quantity"], c["name"], c["price"]) for c in cards(db, deck_id)])
    return sid


def snapshots(db, deck_id: int) -> list[dict]:
    _deck(db, deck_id)
    return [dict(r, value=round(r["value"], 2)) for r in db.execute(
        "SELECT s.id, s.name, s.created_at, COALESCE(SUM(c.quantity), 0) AS cards, COALESCE(SUM(c.quantity * COALESCE(c.price, 0)), 0) AS value"
        " FROM deck_snapshots s LEFT JOIN deck_snapshot_cards c ON c.snapshot_id = s.id WHERE s.deck_id=? GROUP BY s.id ORDER BY s.created_at DESC, s.id DESC", (deck_id,))]


def delete_snapshot(db, deck_id: int, snapshot_id: int) -> None:
    _snapshot(db, deck_id, snapshot_id)
    with db:
        db.execute("DELETE FROM deck_snapshots WHERE id=?", (snapshot_id,))  # its cards go with it (ON DELETE CASCADE)


def restore_snapshot(db, deck_id: int, snapshot_id: int) -> dict:
    """Put the deck back as it was in a snapshot: the deck now is saved first as a snapshot of its own, so nothing is lost, then its cards
    are replaced by the snapshot's. Tags and the assigned copies are not part of a snapshot: the copies go back to the collection
    (use "Assign free copies" to put them in the deck again)."""
    snap = _snapshot(db, deck_id, snapshot_id)
    lines = [dict(r) for r in db.execute("SELECT oracle_id, scryfall_id, finish, board, quantity FROM deck_snapshot_cards WHERE snapshot_id=?", (snapshot_id,))]
    safety = save_snapshot(db, deck_id, f"Before restoring {snap['name']}"[:SNAPSHOT_NAME_MAX])
    for c in cards(db, deck_id):
        remove_card(db, deck_id, c["id"])
    skipped = 0
    for ln in lines:
        try:
            add_card(db, deck_id, ln["oracle_id"], ln["quantity"], ln["board"], ln["scryfall_id"], finish=ln["finish"])
        except ValueError:  # the printing is gone from the card data (a bulk update): any printing will do
            try:
                add_card(db, deck_id, ln["oracle_id"], ln["quantity"], ln["board"])
            except ValueError:
                skipped += 1
    return {"safety_snapshot": safety, "restored": len(lines) - skipped, "skipped": skipped}


def _side(db, deck_id: int, which) -> tuple[dict, bool]:
    """The lines of one side of a comparison, summed per (card, board): `{key: {name, qty, price}}`, and whether it is the live deck."""
    if which == "current":
        lines, live = [(c["oracle_id"], c["board"], c["name"], c["quantity"], c["price"]) for c in cards(db, deck_id)], True
    else:
        _snapshot(db, deck_id, which)
        lines = [tuple(r) for r in db.execute("SELECT oracle_id, board, name, quantity, price FROM deck_snapshot_cards WHERE snapshot_id=?", (which,))]
        live = False
    out = {}
    for oid, board, name, q, price in lines:
        e = out.setdefault((oid, board), {"name": name, "qty": 0, "price": None})
        e["qty"] += q
        if e["price"] is None:
            e["price"] = price
    return out, live


def compare(db, deck_id: int, base="latest", target="current") -> dict:
    """What changed between two states of a deck (each `"current"` or a snapshot id; the default is the newest snapshot against the deck
    now): cards added, removed and with another quantity, by card and board. The price of a change is today's price when the card is in the
    live deck, else the one saved with the snapshot."""
    _deck(db, deck_id)
    if base == "latest":
        row = db.execute("SELECT id FROM deck_snapshots WHERE deck_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (deck_id,)).fetchone()
        if row is None:
            raise ValueError("no snapshots yet")
        base = row["id"]
    a, _ = _side(db, deck_id, base)
    b, _ = _side(db, deck_id, target)
    live, _ = _side(db, deck_id, "current")
    added, removed, changed = [], [], []
    for key in sorted(set(a) | set(b), key=lambda k: ((b.get(k) or a.get(k))["name"].lower(), k[1])):
        old, new = a.get(key), b.get(key)
        o, n = old["qty"] if old else 0, new["qty"] if new else 0
        if o == n:
            continue
        src = live.get(key) or new or old
        price = src["price"]
        entry = {"oracle_id": key[0], "name": (new or old)["name"], "board": key[1], "old_qty": o, "new_qty": n, "delta_qty": n - o,
                 "price": price, "line_delta": round((n - o) * (price or 0), 2)}
        (added if not o else removed if not n else changed).append(entry)
    return {"added": added, "removed": removed, "changed": changed,
            "price_difference": round(sum(e["line_delta"] for e in added + removed + changed), 2)}
