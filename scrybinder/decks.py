"""Decks: their own card list (by oracle card) with a board, a preferred printing and tags per card.
A card's status says how much of it the collection covers; copy assignment comes in a later unit."""
import json
import re

FORMATS = ("commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual")
BOARDS = ("main", "side", "commander", "maybe")  # maybe never counts towards size, legality or statistics
TAG_MAX = 30
PROXY = "proxy"  # defined tag: the card is in the deck but is not a real copy

# copies owned (proxy rows of the collection are not real copies) and the cheapest price of the oracle card
_CARD_SQL = """
SELECT d.id, d.oracle_id, d.scryfall_id, d.quantity, d.board, o.name, o.mana_cost, o.cmc, o.type_line, o.color_identity,
       (SELECT COALESCE(SUM(c.quantity), 0) FROM collection c JOIN cards k ON k.id = c.scryfall_id
         WHERE k.oracle_id = d.oracle_id AND c.proxy = 0) AS owned,
       COALESCE((SELECT eur FROM cards WHERE id = d.scryfall_id),
                (SELECT MIN(eur) FROM cards WHERE oracle_id = d.oracle_id AND eur IS NOT NULL)) AS price,
       COALESCE((SELECT image_small FROM cards WHERE id = d.scryfall_id),
                (SELECT image_small FROM cards WHERE oracle_id = d.oracle_id AND image_small IS NOT NULL
                  ORDER BY digital, released_at DESC LIMIT 1)) AS image
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


def _card_state(r: dict) -> dict:
    """complete / partial / missing against the collection; `proxy` cards are present but never missing."""
    r["missing"] = 0 if PROXY in r["tags"] else max(r["quantity"] - r["owned"], 0)
    r["status"] = "proxy" if PROXY in r["tags"] else "complete" if not r["missing"] else "partial" if r["owned"] else "missing"
    return r


def cards(db, deck_id: int) -> list[dict]:
    tags = {}
    for cid, t in db.execute("SELECT deck_card_id, tag FROM deck_card_tags WHERE deck_card_id IN"
                             " (SELECT id FROM deck_cards WHERE deck_id=?) ORDER BY tag", (deck_id,)):
        tags.setdefault(cid, []).append(t)
    out = []
    for row in db.execute(_CARD_SQL, (deck_id,)):
        r = dict(row)
        r["color_identity"] = json.loads(r["color_identity"] or "[]")
        r["tags"] = tags.get(r["id"], [])
        out.append(_card_state(r))
    return out


def summary(cs: list[dict]) -> dict:
    """Counts over the boards that make the deck (everything but `maybe`)."""
    real = [c for c in cs if c["board"] != "maybe"]
    return {"cards": sum(c["quantity"] for c in real),
            "complete": sum(c["quantity"] for c in real if c["status"] in ("complete", "proxy")),
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
        d["summary"] = summary(cards(db, d["id"]))
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
            db.execute("DELETE FROM deck_cards WHERE id=?", (card_id,))
            card_id = other["id"]
        else:
            db.execute("UPDATE deck_cards SET quantity=?, board=?, scryfall_id=? WHERE id=?", (qty, board, sid, card_id))
        if tags is not None:
            _set_tags(db, card_id, tags)
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
