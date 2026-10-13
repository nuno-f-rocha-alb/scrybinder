"""Decks: their own card list (by oracle card) with a board, a preferred printing and tags per card.
Cards can be assigned physical copies of the collection (reserved for that deck); a card's status says how much of
it is assigned, free to assign, held by other decks, or has to be bought."""
import json
import re

from . import deckrules, deckstats

FORMATS = ("commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual")
BOARDS = ("main", "side", "commander", "maybe")  # maybe never counts towards size, legality or statistics
TAG_MAX = 30
PROXY = "proxy"  # defined tag: the card is in the deck but is not a real copy

# copies owned (proxy rows of the collection are not real copies) and the cheapest price of the oracle card
_CARD_SQL = """
SELECT d.id, d.oracle_id, d.scryfall_id, d.quantity, d.board, o.name, o.mana_cost, o.cmc, o.type_line, o.colors, o.color_identity,
       o.produced_mana, o.game_changer,
       (SELECT COALESCE(SUM(c.quantity), 0) FROM collection c JOIN cards k ON k.id = c.scryfall_id
         WHERE k.oracle_id = d.oracle_id AND c.proxy = 0) AS owned,
       (SELECT COALESCE(SUM(quantity), 0) FROM deck_assignments WHERE deck_card_id = d.id) AS assigned,
       (SELECT COALESCE(SUM(a.quantity), 0) FROM deck_assignments a JOIN collection c ON c.id = a.collection_id
          JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id = d.oracle_id) AS assigned_all,
       COALESCE((SELECT eur FROM cards WHERE id = d.scryfall_id),
                (SELECT MIN(eur) FROM cards WHERE oracle_id = d.oracle_id AND eur IS NOT NULL)) AS price,
       COALESCE(d.scryfall_id,  -- the printing whose image the app shows (/api/image/<id>)
                (SELECT id FROM cards WHERE oracle_id = d.oracle_id AND digital = 0 AND image_small IS NOT NULL
                  ORDER BY released_at DESC LIMIT 1)) AS image_id
FROM deck_cards d JOIN oracle_cards o ON o.oracle_id = d.oracle_id
WHERE d.deck_id = ? ORDER BY d.board, o.name, d.id
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
    for oid, did, name, q in db.execute(
            "SELECT k.oracle_id, dk.id, dk.name, SUM(a.quantity) FROM deck_assignments a"
            " JOIN deck_cards dc ON dc.id = a.deck_card_id JOIN decks dk ON dk.id = dc.deck_id"
            " JOIN collection c ON c.id = a.collection_id JOIN cards k ON k.id = c.scryfall_id"
            " WHERE dk.id != ? AND k.oracle_id IN (SELECT oracle_id FROM deck_cards WHERE deck_id=?)"
            " GROUP BY k.oracle_id, dk.id ORDER BY dk.name", (deck_id, deck_id)):
        elsewhere.setdefault(oid, []).append({"deck_id": did, "name": name, "quantity": q})
    out, pool = [], {}
    for row in db.execute(_CARD_SQL, (deck_id,)):
        r = dict(row)
        r["colors"] = json.loads(r["colors"] or "[]")
        r["color_identity"] = json.loads(r["color_identity"] or "[]")
        r["produced_mana"] = json.loads(r["produced_mana"] or "[]")
        r["game_changer"] = bool(r["game_changer"])
        r["tags"] = tags.get(r["id"], [])
        r["assignments"] = assignments.get(r["id"], [])
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
        r["available"] = 0 if PROXY in r["tags"] else take
        out.append(r)
    return out


def summary(cs: list[dict]) -> dict:
    """Counts over the boards that make the deck (everything but `maybe`)."""
    real = [c for c in cs if c["board"] != "maybe"]
    return {"cards": sum(c["quantity"] for c in real),
            "assigned": sum(c["assigned"] for c in real),
            "available": sum(c["available"] for c in real),  # free copies that could be assigned now
            "missing": sum(c["missing"] for c in real),
            "proxies": sum(c["quantity"] for c in real if PROXY in c["tags"]),
            "cost_to_complete": round(sum(c["missing"] * (c["price"] or 0) for c in real), 2)}


def create(db, name: str, format: str = "casual", description: str = "") -> int:
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("a deck needs a name")
    _check(format=format)
    with db:
        return db.execute("INSERT INTO decks (name, format, description) VALUES (?,?,?)",
                          (name, format, description or "")).lastrowid


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
        d["cover"] = next((c["image_id"] for c in cs if c["board"] != "maybe"), None)  # the commander's, boards sort first
        out.append(d)
    return out


def update(db, deck_id: int, **fields) -> None:
    _deck(db, deck_id)
    fields = {k: v for k, v in fields.items() if k in ("name", "format", "description") and v is not None}
    _check(format=fields.get("format"))
    if "name" in fields and not (isinstance(fields["name"], str) and fields["name"].strip()):
        raise ValueError("a deck needs a name")
    if fields:
        with db:
            db.execute(f"UPDATE decks SET {', '.join(k + '=?' for k in fields)}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                       " WHERE id=?", [*fields.values(), deck_id])


def delete(db, deck_id: int) -> None:
    _deck(db, deck_id)
    with db:
        db.execute("DELETE FROM decks WHERE id=?", (deck_id,))  # cards and tags go with it (ON DELETE CASCADE)


def _touch(db, deck_id: int):
    db.execute("UPDATE decks SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (deck_id,))


def _printing_ok(db, oracle_id: str, scryfall_id):
    if scryfall_id is not None and not db.execute("SELECT 1 FROM cards WHERE id=? AND oracle_id=?", (scryfall_id, oracle_id)).fetchone():
        raise ValueError("that printing is not a printing of this card")


def _find(db, deck_id, oracle_id, scryfall_id, board):
    return db.execute("SELECT id FROM deck_cards WHERE deck_id=? AND oracle_id=? AND COALESCE(scryfall_id,'')=? AND board=?",
                      (deck_id, oracle_id, scryfall_id or "", board)).fetchone()


def add_card(db, deck_id: int, oracle_id: str, quantity: int = 1, board: str = "main", scryfall_id=None, tags=()) -> int:
    """Add a card; the same card on the same board with the same printing sums the quantity."""
    _deck(db, deck_id)
    _check(board=board)
    quantity = _int(quantity)
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not db.execute("SELECT 1 FROM oracle_cards WHERE oracle_id=?", (oracle_id,)).fetchone():
        raise ValueError("unknown card (update the bulk data)")
    _printing_ok(db, oracle_id, scryfall_id)
    tags = _tags(tags)
    with db:
        row = _find(db, deck_id, oracle_id, scryfall_id, board)
        if row:
            db.execute("UPDATE deck_cards SET quantity=quantity+? WHERE id=?", (quantity, row["id"]))
            cid = row["id"]
            db.executemany("INSERT OR IGNORE INTO deck_card_tags VALUES (?,?)", [(cid, t) for t in tags])
        else:
            cid = db.execute("INSERT INTO deck_cards (deck_id, oracle_id, scryfall_id, quantity, board) VALUES (?,?,?,?,?)",
                             (deck_id, oracle_id, scryfall_id, quantity, board)).lastrowid
            _set_tags(db, cid, tags)
        _touch(db, deck_id)
    return cid


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
    """Change quantity, board, printing (`scryfall_id`, None for any) and/or tags. Returns the card's id, which is another
    one when the change merges it into a card that already exists."""
    cur = db.execute("SELECT * FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).fetchone()
    if not cur:
        raise KeyError(card_id)
    board = fields.get("board", cur["board"])
    sid = fields["scryfall_id"] if "scryfall_id" in fields else cur["scryfall_id"]
    qty = _int(fields.get("quantity", cur["quantity"]))
    _check(board=board)
    if qty < 1:
        raise ValueError("quantity must be >= 1")
    _printing_ok(db, cur["oracle_id"], sid)
    tags = _tags(fields["tags"]) if "tags" in fields else None
    with db:
        other = _find(db, deck_id, cur["oracle_id"], sid, board)
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
            db.execute("UPDATE deck_cards SET quantity=?, board=?, scryfall_id=? WHERE id=?", (qty, board, sid, card_id))
        if tags is not None:
            _set_tags(db, card_id, tags)
        if PROXY in _card_tags(db, card_id):  # a proxy is not a real copy: nothing to reserve
            db.execute("DELETE FROM deck_assignments WHERE deck_card_id=?", (card_id,))
        _trim(db, card_id)
        _touch(db, deck_id)
    return card_id


def remove_card(db, deck_id: int, card_id: int) -> None:
    with db:
        if not db.execute("DELETE FROM deck_cards WHERE id=? AND deck_id=?", (card_id, deck_id)).rowcount:
            raise KeyError(card_id)
        _touch(db, deck_id)


def duplicate(db, deck_id: int) -> int:
    """Copy of the deck with its cards and tags (assignments of physical copies are not copied)."""
    src = _deck(db, deck_id)
    with db:
        new = db.execute("INSERT INTO decks (name, format, description) VALUES (?,?,?)",
                         (f"{src['name']} (copy)", src["format"], src["description"])).lastrowid
        for c in db.execute("SELECT * FROM deck_cards WHERE deck_id=?", (deck_id,)).fetchall():
            cid = db.execute("INSERT INTO deck_cards (deck_id, oracle_id, scryfall_id, quantity, board) VALUES (?,?,?,?,?)",
                             (new, c["oracle_id"], c["scryfall_id"], c["quantity"], c["board"])).lastrowid
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
    with db:
        db.execute("DELETE FROM deck_assignments WHERE deck_card_id=?", (card_id,))
        db.executemany("INSERT INTO deck_assignments VALUES (?,?,?)", [(card_id, c, q) for c, q in want.items()])
        _touch(db, deck_id)


def assign_free(db, deck_id: int) -> int:
    """Assign every free copy the deck still needs (preferred printing first). Never touches existing assignments."""
    _deck(db, deck_id)
    n = 0
    with db:
        for c in cards(db, deck_id):
            if c["board"] == "maybe" or c["status"] == "proxy":
                continue
            need = c["quantity"] - c["assigned"]
            if need <= 0:
                continue
            for row in db.execute(
                    "SELECT c.id, c.quantity - COALESCE((SELECT SUM(quantity) FROM deck_assignments WHERE collection_id = c.id), 0) AS free"
                    " FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id=? AND c.proxy=0"
                    " ORDER BY (c.scryfall_id = ?) DESC, c.id", (c["oracle_id"], c["scryfall_id"] or "")).fetchall():
                take = min(need, row["free"])
                if take > 0:
                    db.execute("INSERT INTO deck_assignments VALUES (?,?,?) ON CONFLICT(deck_card_id, collection_id)"
                               " DO UPDATE SET quantity = quantity + excluded.quantity", (c["id"], row["id"], take))
                    need -= take
                    n += take
        if n:
            _touch(db, deck_id)
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
