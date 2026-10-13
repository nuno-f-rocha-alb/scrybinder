"""Search of oracle cards (one row per card, whatever its printings) to find cards to add to a deck."""
import json
import re

SORTS = {"name": "o.name", "cmc": "o.cmc, o.name", "popularity": "o.edhrec_rank IS NULL, o.edhrec_rank, o.name"}
LIMIT_MAX = 100


def _match(column: str, text: str) -> str | None:
    """FTS5 expression: every word of `text` as a prefix, in one column."""
    toks = re.findall(r"\w+", text or "")
    return "%s : (%s)" % (column, " ".join('"%s"*' % t for t in toks)) if toks else None


def _float(v, what: str):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")


def search(db, q: str = "", text: str = "", colors: str = "", type: str = "", cmc_min=None, cmc_max=None,
           owned: bool = False, legal: bool = False, deck: int | None = None, sort: str = "name",
           limit: int = 50, offset: int = 0) -> dict:
    """Cards by name (`q`) and rules text (`text`), colours (all the given ones; `C` for colourless), type words, CMC range, owned,
    and, with `legal` and a `deck`, only those legal in the deck's format and, in Commander, inside the commander's colour identity.
    Returns {total, rows}; each row has the newest paper printing's image, the copies owned and the quantity already in the deck."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}")
    if legal and deck is None:
        raise ValueError("legal needs a deck")
    colors = colors.upper()
    if set(colors) - set("WUBRGC"):
        raise ValueError("colors: letters from WUBRGC")
    lo, hi = _float(cmc_min, "cmc_min"), _float(cmc_max, "cmc_max")
    limit, offset = max(1, min(int(limit), LIMIT_MAX)), max(0, int(offset))
    w, p = ["EXISTS (SELECT 1 FROM cards k WHERE k.oracle_id = o.oracle_id AND k.digital = 0)"], []  # paper cards only
    match = " AND ".join(m for m in (_match("name", q), _match("oracle_text", text)) if m)
    if match:
        w.append("o.rowid IN (SELECT rowid FROM oracle_fts WHERE oracle_fts MATCH ?)")
        p.append(match)
    if "C" in colors and len(colors) > 1:
        raise ValueError("colors: C (colourless) cannot be mixed with other colours")
    if colors == "C":
        w.append("o.colors = '[]'")
    else:
        w += [f"o.colors LIKE '%\"{c}\"%'" for c in colors]
    for word in re.findall(r"\w+", type or ""):
        w.append("instr(lower(o.type_line), ?) > 0")
        p.append(word.lower())
    if lo is not None:
        w.append("o.cmc >= ?")
        p.append(lo)
    if hi is not None:
        w.append("o.cmc <= ?")
        p.append(hi)
    if owned:
        w.append("EXISTS (SELECT 1 FROM collection c JOIN cards k ON k.id = c.scryfall_id WHERE k.oracle_id = o.oracle_id AND c.proxy = 0)")
    if deck is not None:
        d = db.execute("SELECT format FROM decks WHERE id=?", (deck,)).fetchone()
        if not d:
            raise KeyError(deck)
        if legal and d["format"] != "casual":
            w.append("json_extract(o.legalities, '$.' || ?) IN ('legal', 'restricted')")
            p.append(d["format"])
            if d["format"] == "commander":
                cmd = [json.loads(j or "[]") for (j,) in db.execute(
                    "SELECT o2.color_identity FROM deck_cards dc JOIN oracle_cards o2 ON o2.oracle_id = dc.oracle_id"
                    " WHERE dc.deck_id=? AND dc.board='commander'", (deck,))]
                if cmd:  # no commander yet: no colour limit
                    allowed = {i for ci in cmd for i in ci}
                    w += [f"o.color_identity NOT LIKE '%\"{c}\"%'" for c in "WUBRG" if c not in allowed]
    where = " AND ".join(w)
    total = db.execute(f"SELECT COUNT(*) FROM oracle_cards o WHERE {where}", p).fetchone()[0]
    ids = [r[0] for r in db.execute(f"SELECT o.oracle_id FROM oracle_cards o WHERE {where} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
                                    [*p, limit, offset])]
    rows = []
    for oid in ids:  # the details only for the page
        r = dict(db.execute("SELECT oracle_id, name, mana_cost, cmc, type_line, color_identity, oracle_text, edhrec_rank"
                            " FROM oracle_cards WHERE oracle_id=?", (oid,)).fetchone())
        r["color_identity"] = json.loads(r["color_identity"] or "[]")
        img = db.execute("SELECT id, image_small, image_normal FROM cards WHERE oracle_id=? AND digital=0 AND image_small IS NOT NULL"
                         " ORDER BY released_at DESC LIMIT 1", (oid,)).fetchone()
        r.update(dict(img) if img else {"id": None, "image_small": None, "image_normal": None})
        r["price"] = db.execute("SELECT MIN(eur) FROM cards WHERE oracle_id=? AND digital=0", (oid,)).fetchone()[0]  # as decks price it
        r["owned"] = db.execute("SELECT COALESCE(SUM(c.quantity), 0) FROM collection c JOIN cards k ON k.id = c.scryfall_id"
                                " WHERE k.oracle_id=? AND c.proxy=0", (oid,)).fetchone()[0]
        r["in_deck"] = (db.execute("SELECT COALESCE(SUM(quantity), 0) FROM deck_cards WHERE deck_id=? AND oracle_id=?"
                                   " AND board != 'maybe'", (deck, oid)).fetchone()[0] if deck is not None else 0)
        rows.append(r)
    return {"total": total, "rows": rows}
