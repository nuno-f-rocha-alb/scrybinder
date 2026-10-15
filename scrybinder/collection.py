"""Collection: rows aggregated by (printing, finish, condition, language, location, flags)."""
import json
import re

from . import decks

KEY = ("scryfall_id", "finish", "condition", "language", "location", "altered", "signed", "misprint", "proxy")
EDITABLE = KEY[1:] + ("quantity", "purchase_price", "purchase_currency", "purchase_date", "notes")
DEFAULTS = {"finish": "nonfoil", "condition": "NM", "language": "en", "location": "", "altered": 0, "signed": 0,
            "misprint": 0, "proxy": 0, "quantity": 1, "purchase_currency": "EUR", "notes": ""}
# current price: bulk column according to the finish
_PRICE = "CASE c.finish WHEN 'foil' THEN k.eur_foil WHEN 'etched' THEN k.eur_etched ELSE k.eur END"


def _norm(d: dict) -> dict:
    out = {**DEFAULTS, **{k: v for k, v in d.items() if v is not None or k.startswith("purchase")}}
    for f in ("altered", "signed", "misprint", "proxy"):
        out[f] = int(bool(out[f]))
    out["location"] = (out["location"] or "").strip()
    out["quantity"] = int(out["quantity"])
    if out["quantity"] < 1:
        raise ValueError("quantity must be >= 1")
    return out


def add(db, **fields) -> int:
    """Add a row; if the key already exists the quantity is summed. Returns the row id."""
    r = _norm(fields)
    where = " AND ".join(f"{k}=?" for k in KEY)
    with db:
        row = db.execute(f"SELECT id, purchase_price FROM collection WHERE {where}",
                         [r[k] for k in KEY]).fetchone()
        if row:
            # ponytail: an existing purchase price wins; only filled in when it was empty
            db.execute("UPDATE collection SET quantity=quantity+?, purchase_price=COALESCE(purchase_price,?),"
                       " manabox_id=COALESCE(manabox_id,?) WHERE id=?",
                       (r["quantity"], r.get("purchase_price"), r.get("manabox_id"), row["id"]))
            return row["id"]
        cols = list(KEY) + ["quantity", "purchase_price", "purchase_currency", "purchase_date", "notes",
                            "manabox_id"] + (["added_at"] if r.get("added_at") else [])
        cur = db.execute(f"INSERT INTO collection ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [r.get(c) for c in cols])
        return cur.lastrowid


def update(db, row_id: int, release: bool = False, **fields) -> int:
    """Edit a row. If the new key collides with another row they are merged. Returns the resulting id.
    Copies assigned to decks follow a merge; fewer copies than assigned (or a proxy) raise decks.Conflict unless `release`."""
    cur = db.execute("SELECT * FROM collection WHERE id=?", (row_id,)).fetchone()
    if not cur:
        raise KeyError(row_id)
    merged = {**dict(cur), **{k: v for k, v in fields.items() if k in EDITABLE}}
    r = _norm(merged)
    where = " AND ".join(f"{k}=?" for k in KEY)
    with db:
        decks.check_row(db, row_id, r["quantity"], bool(r["proxy"]), release)
        other = db.execute(f"SELECT id FROM collection WHERE {where} AND id<>?", [r[k] for k in KEY] + [row_id]).fetchone()
        if other:
            decks.transfer(db, row_id, other["id"])
            db.execute("UPDATE collection SET quantity=quantity+?, purchase_price=COALESCE(purchase_price,?) WHERE id=?",
                       (r["quantity"], r["purchase_price"], other["id"]))
            db.execute("DELETE FROM collection WHERE id=?", (row_id,))
            return other["id"]
        sets = ",".join(f"{k}=?" for k in EDITABLE)
        db.execute(f"UPDATE collection SET {sets} WHERE id=?", [r[k] for k in EDITABLE] + [row_id])
    return row_id


def delete(db, row_id: int, release: bool = False):
    decks.check_delete(db, [row_id], release)
    with db:
        db.execute("DELETE FROM collection WHERE id=?", (row_id,))


def move(db, row_id: int, location: str, quantity: int | None = None, release: bool = False) -> int:
    """Move `quantity` (or everything) to another location; merges with the identical row at the destination."""
    cur = db.execute("SELECT * FROM collection WHERE id=?", (row_id,)).fetchone()
    if not cur:
        raise KeyError(row_id)
    q = cur["quantity"] if quantity is None else int(quantity)
    if not 1 <= q <= cur["quantity"]:
        raise ValueError("invalid quantity")
    if q == cur["quantity"]:
        return update(db, row_id, release=release, location=location)
    with db:
        decks.check_row(db, row_id, cur["quantity"] - q, False, release)
        db.execute("UPDATE collection SET quantity=quantity-? WHERE id=?", (q, row_id))
        d = dict(cur)
        d.update(location=location, quantity=q)
        return add(db, **{k: d[k] for k in d if k not in ("id", "added_at")})


def _fts(q: str) -> str:
    toks = re.findall(r"\w+", q)
    return " ".join(f'"{t}"*' for t in toks)


def _filters(q="", set_code="", location=None, finish="", language=""):
    w, p = [], []
    if _fts(q):
        w.append("k.rowid IN (SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?)")
        p.append(_fts(q))
    if set_code:
        w.append("k.set_code=?"); p.append(set_code.lower())
    if location is not None:
        w.append("c.location=?"); p.append(location)
    if finish:
        w.append("c.finish=?"); p.append(finish)
    if language:
        w.append("c.language=?"); p.append(language)
    return ("WHERE " + " AND ".join(w)) if w else "", p


def matching_ids(db, q="", set_code="", location=None, finish="", language="") -> list[int]:
    """Ids of every row matching the filter (for 'select all' without loading the rows)."""
    where, p = _filters(q, set_code, location, finish, language)
    return [r[0] for r in db.execute(f"SELECT c.id FROM collection c JOIN cards k ON k.id=c.scryfall_id {where}", p)]


def search(db, q="", set_code="", location=None, finish="", language="", sort="name", limit=100, offset=0):
    where, p = _filters(q, set_code, location, finish, language)
    order = {"name": "k.name, k.set_code", "added": "c.added_at DESC", "price": "price DESC NULLS LAST",
             "set": "k.set_code, CAST(k.collector_number AS INTEGER)"}.get(sort, "k.name")
    base = f"FROM collection c JOIN cards k ON k.id=c.scryfall_id {where}"
    rows = db.execute(
        f"SELECT c.*, k.name, k.set_code, k.set_name, k.collector_number, k.rarity, k.cardmarket_id, "
        f"{_PRICE} AS price {base} ORDER BY {order} LIMIT ? OFFSET ?", p + [limit, offset]).fetchall()
    tot = db.execute(f"SELECT COUNT(*) AS rows_, COALESCE(SUM(c.quantity),0) AS cards, "
                     f"COALESCE(SUM(c.quantity*({_PRICE})),0) AS value {base}", p).fetchone()
    rows = [dict(r) for r in rows]
    held = {}
    for u in decks.users(db, [r["id"] for r in rows]):  # which decks hold copies of each row
        held.setdefault(u["collection_id"], []).append({"deck_id": u["deck_id"], "name": u["name"], "quantity": u["quantity"]})
    for r in rows:
        r["decks"] = held.get(r["id"], [])
    return {"rows": rows, "total_rows": tot["rows_"], "total_cards": tot["cards"],
            "total_value": round(tot["value"], 2)}


def set_progress(db, location=None, q="", hide_empty=True, group=False) -> list[dict]:
    """Per set: printings you own / total non-digital printings in the bulk.
    group=True: the same card (oracle_id) with different art/frames counts as 1."""
    if db.execute("SELECT 1 FROM set_totals LIMIT 1").fetchone() is None:
        from .scryfall import refresh_set_totals  # database created before this table existed
        refresh_set_totals(db)
    key = "COALESCE(ck.oracle_id,ck.id)" if group else "ck.id"
    w, p = ["1"], []
    if location is not None:
        p.append(location)
    if q:
        w.append("(t.name LIKE ? OR t.code LIKE ?)")
        p += [f"%{q}%", f"{q}%"]
    # CROSS JOIN fixes the order: start from the collection rows instead of scanning every card
    sub = (f"SELECT ck.set_code AS code, COUNT(DISTINCT {key}) AS owned, SUM(c.quantity) AS copies FROM collection c"
           f" CROSS JOIN cards ck ON ck.id=c.scryfall_id {'WHERE c.location=?' if location is not None else ''} GROUP BY ck.set_code")
    rows = db.execute(
        f"SELECT t.code, t.name, t.released_at, {'t.total_grouped' if group else 't.total'} AS total,"
        f" COALESCE(o.owned,0) AS owned, COALESCE(o.copies,0) AS copies, s.icon_svg_uri IS NOT NULL AS has_icon"
        f" FROM set_totals t LEFT JOIN ({sub}) o ON o.code=t.code LEFT JOIN sets s ON s.code=t.code"
        f" WHERE {' AND '.join(w)}" + (" AND o.owned>0" if hide_empty else ""), p).fetchall()
    return [dict(r, percent=round(100 * r["owned"] / r["total"], 1)) for r in rows]


def locations(db) -> list[dict]:
    """Every location with its number of cards: the ones in use and the ones made on purpose (0 cards while empty)."""
    return [dict(r) for r in db.execute(
        "SELECT location, SUM(quantity) AS cards FROM (SELECT location, quantity FROM collection UNION ALL SELECT name, 0 FROM locations)"
        " GROUP BY location ORDER BY location")]


def create_location(db, name) -> str:
    """Make a location that can be empty, to move cards into later. Returns the name (trimmed)."""
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 60:
        raise ValueError("a location needs a name of up to 60 characters")
    with db:
        db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (name,))
    return name


def delete_location(db, name: str) -> None:
    """Remove a location made on purpose; a location that holds cards cannot be removed."""
    if db.execute("SELECT 1 FROM collection WHERE location=?", (name,)).fetchone():
        raise ValueError("that location still has cards: move them first")
    with db:
        db.execute("DELETE FROM locations WHERE name=?", (name,))


BULK_FIELDS = {"finish", "condition", "language", "location", "altered", "signed", "misprint", "proxy", "notes",
               "purchase_price", "purchase_currency", "purchase_date"}
_FINISHES, _CONDITIONS = {"nonfoil", "foil", "etched"}, {"NM", "LP", "MP", "HP", "DMG"}


def _validate_bulk(f: dict):
    """Types and limits before touching any row: a bad value must not leave the operation half done."""
    for k, n in (("location", 200), ("notes", 2000), ("purchase_currency", 8), ("purchase_date", 32), ("language", 8)):
        if k in f and f[k] is not None and (not isinstance(f[k], str) or len(f[k]) > n):
            raise ValueError(f"{k}: text up to {n} characters")
    if "language" in f and not f["language"]:
        raise ValueError("language: required")
    p = f.get("purchase_price")
    if "purchase_price" in f and p is not None and (isinstance(p, bool) or not isinstance(p, (int, float)) or p < 0):
        raise ValueError("purchase_price: number >= 0 or empty")
    for k in ("altered", "signed", "misprint", "proxy"):
        if k in f and f[k] not in (0, 1, True, False):
            raise ValueError(f"{k}: 0 ou 1")


def bulk_update(db, ids: list[int], **fields) -> dict:
    """Apply the same fields to several rows. Validates everything first; rows that become identical are merged."""
    fields = {k: v for k, v in fields.items() if k in BULK_FIELDS}
    if not fields:
        raise ValueError("nothing to change")
    if "finish" in fields and fields["finish"] not in _FINISHES:
        raise ValueError(f"invalid finish: {fields['finish']}")
    if "condition" in fields and fields["condition"] not in _CONDITIONS:
        raise ValueError(f"invalid condition: {fields['condition']}")
    _validate_bulk(fields)
    if fields.get("proxy"):  # a proxy cannot hold assignments: refuse before changing anything
        used = decks.users(db, ids)
        if used:
            raise decks._conflict(used)
    updated = merged = skipped = 0
    for i in dict.fromkeys(ids):
        if "finish" in fields:  # do not allow foil/etched on a printing that does not exist in that finish
            r = db.execute("SELECT k.finishes FROM collection c JOIN cards k ON k.id=c.scryfall_id WHERE c.id=?", (i,)).fetchone()
            if r is not None and fields["finish"] not in json.loads(r[0] or "[]"):
                skipped += 1
                continue
        try:
            rid = update(db, i, **fields)
        except KeyError:  # already merged/deleted by an earlier row of this operation
            continue
        updated += 1
        merged += rid != i
    return {"updated": updated, "merged": merged, "skipped": skipped}


def bulk_delete(db, ids: list[int], trash_dir=None, release: bool = False) -> int:
    """Delete several rows. They are first saved to <trash_dir>/<date>.json so they can be recovered."""
    import json
    from datetime import datetime
    from pathlib import Path
    ids = list(dict.fromkeys(int(i) for i in ids))
    rows = []
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        rows += [dict(r) for r in db.execute(
            f"SELECT * FROM collection WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
    if not rows:
        return 0
    decks.check_delete(db, [r["id"] for r in rows], release)
    if trash_dir is not None:
        d = Path(trash_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{datetime.now():%Y%m%d-%H%M%S}-{len(rows)}-linhas.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    with db:
        for k in range(0, len(rows), 500):
            chunk = [r["id"] for r in rows[k:k + 500]]
            db.execute(f"DELETE FROM collection WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    return len(rows)
