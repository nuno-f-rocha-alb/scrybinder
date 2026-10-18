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


def _locs(location) -> list[str]:
    """A location filter: one name, a list of names ("" is the cards with no location), or None/[] for all."""
    return [] if location is None else [location] if isinstance(location, str) else list(location)


def _filters(q="", set_code="", location=None, finish="", language=""):
    w, p = [], []
    if _fts(q):
        w.append("k.rowid IN (SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?)")
        p.append(_fts(q))
    if set_code:
        w.append("k.set_code=?"); p.append(set_code.lower())
    locs = _locs(location)
    if locs:
        w.append(f"c.location IN ({','.join('?' * len(locs))})"); p += locs
    if finish:
        w.append("c.finish=?"); p.append(finish)
    if language:
        w.append("c.language=?"); p.append(language)
    return ("WHERE " + " AND ".join(w)) if w else "", p


def matching_ids(db, q="", set_code="", location=None, finish="", language="") -> list[int]:
    """Ids of every row matching the filter (for 'select all' without loading the rows)."""
    where, p = _filters(q, set_code, location, finish, language)
    return [r[0] for r in db.execute(f"SELECT c.id FROM collection c JOIN cards k ON k.id=c.scryfall_id {where}", p)]


# group by: (label shown, order, extra join); the label is also what rows of one group share
_COLORS = "CASE WHEN o.colors IS NULL OR json_array_length(o.colors)=0 THEN 'Colorless' WHEN json_array_length(o.colors)>1 THEN 'Multicolor' " \
          "ELSE CASE json_extract(o.colors,'$[0]') WHEN 'W' THEN 'White' WHEN 'U' THEN 'Blue' WHEN 'B' THEN 'Black' WHEN 'R' THEN 'Red' ELSE 'Green' END END"
_TYPE = "COALESCE(o.type_line, k.type_line, '')"
_TYPES = ("Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land")
_TYPE_CASE = "CASE " + " ".join(f"WHEN {_TYPE} LIKE '%{t}%' THEN '{t}'" for t in _TYPES) + " ELSE 'Other' END"
_LETTER = "CASE WHEN UPPER(SUBSTR(k.name,1,1)) BETWEEN 'A' AND 'Z' THEN UPPER(SUBSTR(k.name,1,1)) ELSE '#' END"
_ORACLE = "LEFT JOIN oracle_cards o ON o.oracle_id = k.oracle_id"
GROUPS = {
    "location": ("c.location", "c.location", ""),
    "name": (_LETTER, _LETTER, ""),
    "color": (_COLORS, f"CASE {_COLORS} WHEN 'White' THEN 0 WHEN 'Blue' THEN 1 WHEN 'Black' THEN 2 WHEN 'Red' THEN 3 WHEN 'Green' THEN 4 WHEN 'Multicolor' THEN 5 ELSE 6 END", _ORACLE),
    "rarity": ("k.rarity", "CASE k.rarity WHEN 'mythic' THEN 0 WHEN 'rare' THEN 1 WHEN 'uncommon' THEN 2 WHEN 'common' THEN 3 ELSE 4 END", ""),
    "set": ("k.set_name", "k.set_name", ""),
    "type": (_TYPE_CASE, f"CASE {_TYPE_CASE} " + " ".join(f"WHEN '{t}' THEN {i}" for i, t in enumerate(_TYPES)) + " ELSE 9 END", _ORACLE),
    "none": ("''", "''", ""),
}
_JOIN_KEY = ("scryfall_id", "finish", "condition", "language", "altered", "signed", "misprint", "proxy")  # KEY without the location


def search(db, q="", set_code="", location=None, finish="", language="", sort="name", limit=100, offset=0, group="location"):
    """The rows of the collection, ordered by `group` and then `sort`. Unless grouped by location, rows that differ only by their
    location are one result: it has the first row's fields, `quantity` summed, and `places` (every row: id, location, quantity)."""
    where, p = _filters(q, set_code, location, finish, language)
    label, gorder, gjoin = GROUPS.get(group, GROUPS["location"])
    joined = group in GROUPS and group != "location"
    order = {"name": "k.name, k.set_code", "added": "MAX(c.added_at) DESC" if joined else "c.added_at DESC", "price": f"({_PRICE}) DESC NULLS LAST",
             "set": "k.set_code, CAST(k.collector_number AS INTEGER)"}.get(sort, "k.name")
    base = f"FROM collection c JOIN cards k ON k.id=c.scryfall_id {gjoin} {where}"
    by = " GROUP BY " + ", ".join(f"c.{k}" for k in _JOIN_KEY) if joined else ""
    lead = db.execute(f"SELECT MIN(c.id) AS id, {label} AS grp {base}{by} ORDER BY {gorder}, {order}, MIN(c.id) LIMIT ? OFFSET ?" if joined else
                      f"SELECT c.id, {label} AS grp {base} ORDER BY {gorder}, {order}, c.id LIMIT ? OFFSET ?", p + [limit, offset]).fetchall()
    ids = [r["id"] for r in lead]
    rows = {}
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        for r in db.execute(
                f"SELECT c.*, k.oracle_id, k.name, k.set_code, k.set_name, k.collector_number, k.rarity, k.cardmarket_id, {_PRICE} AS price"
                f" FROM collection c JOIN cards k ON k.id=c.scryfall_id WHERE c.id IN ({','.join('?' * len(chunk))})", chunk):
            rows[r["id"]] = dict(r)
    out = []
    rows_cols = [c[1] for c in db.execute("PRAGMA table_info(collection)")]
    for r in lead:
        row = rows[r["id"]]
        row["group"] = r["grp"]
        out.append(row)
    places = {}
    if joined and out:  # every row (that matches the filters) of the printings on this page
        sids = list({r["scryfall_id"] for r in out})
        w2, p2 = _filters(q, set_code, location, finish, language)
        for r in db.execute(f"SELECT c.* FROM collection c JOIN cards k ON k.id=c.scryfall_id"
                            f" {w2 + (' AND ' if w2 else 'WHERE ')}c.scryfall_id IN ({','.join('?' * len(sids))}) ORDER BY c.location, c.id", p2 + sids):
            places.setdefault(tuple(r[k] for k in _JOIN_KEY), []).append(dict(r))  # the whole row: the editor can switch to it
    held = {}
    for u in decks.users(db, [pl["id"] for r in out for pl in places.get(tuple(r[k] for k in _JOIN_KEY), [])] + ids):  # which decks hold copies of each row
        held.setdefault(u["collection_id"], []).append({"deck_id": u["deck_id"], "name": u["name"], "quantity": u["quantity"]})
    for r in out:
        r["places"] = places.get(tuple(r[k] for k in _JOIN_KEY), []) if joined else [{k: v for k, v in r.items() if k in rows_cols}]
        for pl in r["places"]:
            pl["decks"] = held.get(pl["id"], [])
        r["quantity"] = sum(pl["quantity"] for pl in r["places"])  # a joined result is the total of its places; the places have their own
        summed = {}
        for pl in r["places"]:
            for d in held.get(pl["id"], []):
                s = summed.setdefault(d["deck_id"], {"deck_id": d["deck_id"], "name": d["name"], "quantity": 0})
                s["quantity"] += d["quantity"]
        r["decks"] = list(summed.values())
    if joined:
        tot = db.execute(f"SELECT COUNT(*) AS rows_ FROM (SELECT 1 {base}{by})", p).fetchone()["rows_"]
        agg = db.execute(f"SELECT COALESCE(SUM(c.quantity),0) AS cards, COALESCE(SUM(c.quantity*({_PRICE})),0) AS value {base}", p).fetchone()
    else:
        agg = db.execute(f"SELECT COUNT(*) AS rows_, COALESCE(SUM(c.quantity),0) AS cards, COALESCE(SUM(c.quantity*({_PRICE})),0) AS value {base}", p).fetchone()
        tot = agg["rows_"]
    return {"rows": out, "total_rows": tot, "total_cards": agg["cards"], "total_value": round(agg["value"], 2)}


def record_snapshot(db) -> dict:
    """Today's value of the whole collection (the unfiltered total of `search`: proxies included, unknown prices as 0); a second
    call the same day replaces the first."""
    agg = db.execute(f"SELECT COALESCE(SUM(c.quantity),0) AS cards, COALESCE(SUM(c.quantity*({_PRICE})),0) AS value"
                     " FROM collection c JOIN cards k ON k.id=c.scryfall_id").fetchone()
    today = db.execute("SELECT strftime('%Y-%m-%d','now')").fetchone()[0]
    value = round(agg["value"], 2)
    with db:
        db.execute("INSERT INTO price_snapshots (date, location, total_value, total_cards) VALUES (?, '', ?, ?)"
                   " ON CONFLICT(date, location) DO UPDATE SET total_value=excluded.total_value, total_cards=excluded.total_cards,"
                   " created_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (today, value, agg["cards"]))
    return {"date": today, "total_value": value, "total_cards": agg["cards"]}


def value_history(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT date, total_value, total_cards FROM price_snapshots WHERE location='' ORDER BY date")]


def set_progress(db, location=None, q="", hide_empty=True, group=False) -> list[dict]:
    """Per set: printings you own / total non-digital printings in the bulk.
    group=True: the same card (oracle_id) with different art/frames counts as 1."""
    if db.execute("SELECT 1 FROM set_totals LIMIT 1").fetchone() is None:
        from .scryfall import refresh_set_totals  # database created before this table existed
        refresh_set_totals(db)
    key = "COALESCE(ck.oracle_id,ck.id)" if group else "ck.id"
    w, p = ["1"], []
    locs = _locs(location)
    loc_where = "WHERE c.location IN (" + ",".join("?" * len(locs)) + ")" if locs else ""
    p += locs
    if q:
        w.append("(t.name LIKE ? OR t.code LIKE ?)")
        p += [f"%{q}%", f"{q}%"]
    # CROSS JOIN fixes the order: start from the collection rows instead of scanning every card
    sub = (f"SELECT ck.set_code AS code, COUNT(DISTINCT {key}) AS owned, SUM(c.quantity) AS copies FROM collection c"
           f" CROSS JOIN cards ck ON ck.id=c.scryfall_id {loc_where} GROUP BY ck.set_code")
    rows = db.execute(
        f"SELECT t.code, t.name, t.released_at, {'t.total_grouped' if group else 't.total'} AS total,"
        f" COALESCE(o.owned,0) AS owned, COALESCE(o.copies,0) AS copies, s.icon_svg_uri IS NOT NULL AS has_icon"
        f" FROM set_totals t LEFT JOIN ({sub}) o ON o.code=t.code LEFT JOIN sets s ON s.code=t.code"
        f" WHERE {' AND '.join(w)}" + (" AND o.owned>0" if hide_empty else ""), p).fetchall()
    return [dict(r, percent=round(100 * r["owned"] / r["total"], 1)) for r in rows]


def locations(db) -> list[dict]:
    """Every location with its number of cards: the ones in use, the ones made on purpose (0 cards while empty) and one per deck
    (`deck_id` set; its name is `Deck: <name>`)."""
    deck_of = {loc: i for i, loc in decks.location_names(db).items()}
    rows = db.execute(
        "SELECT location, SUM(quantity) AS cards FROM (SELECT location, quantity FROM collection UNION ALL SELECT name, 0 FROM locations"
        f" UNION ALL SELECT value, 0 FROM json_each(?)) GROUP BY location ORDER BY location", (json.dumps(list(deck_of)),))
    return [dict(r, deck_id=deck_of.get(r["location"])) for r in rows]


def create_location_name(name) -> str:
    """A valid name for a location of your own (trimmed)."""
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 60:
        raise ValueError("a location needs a name of up to 60 characters")
    if name.startswith(decks.LOC_PREFIX):
        raise ValueError(f'"{decks.LOC_PREFIX}" is for the locations of decks: pick another name')
    return name


def create_location(db, name) -> str:
    """Make a location that can be empty, to move cards into later. Returns the name (trimmed)."""
    name = create_location_name(name)
    with db:
        db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (name,))
    return name


def merge_locations(db, names, into) -> dict:
    """Move every card of the locations in `names` to the location `into` (a new name, or one of them), where identical rows join, and
    drop the others. Deck locations stay out of it: a deck keeps its own. Returns the cards moved."""
    names = list(dict.fromkeys(names)) if isinstance(names, list) and all(isinstance(n, str) for n in names) else []
    into = create_location_name(into)
    if len(names) < 2:
        raise ValueError("pick at least two locations to merge")
    deck_locs = set(decks.location_names(db).values())
    if any(n in deck_locs for n in names) or into in deck_locs:
        raise ValueError("a deck's location cannot be merged: it goes with the deck")
    ids = [(r[0], r[1]) for r in db.execute(f"SELECT id, quantity FROM collection WHERE location IN ({','.join('?' * len(names))})", names)]
    with db:
        for i, _ in ids:
            update(db, i, location=into)
        db.executemany("DELETE FROM locations WHERE name=?", [(n,) for n in names if n != into])
        db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (into,))
    return {"moved": sum(q for _, q in ids)}


def delete_location(db, name: str, delete_cards: bool = False, release: bool = False, trash_dir=None) -> dict:
    """Remove a location. Its cards move to "(no location)", or are deleted with `delete_cards` (copies assigned to decks raise
    decks.Conflict unless `release`). The location of a deck goes with the deck. Returns the cards moved or deleted."""
    if not name:
        raise ValueError("(no location) cannot be removed")
    if any(l["location"] == name and l["deck_id"] is not None for l in locations(db)):
        raise ValueError("that is a deck's location: it goes with the deck")
    ids = [r[0] for r in db.execute("SELECT id FROM collection WHERE location=?", (name,))]
    n = sum(r[0] for r in db.execute("SELECT quantity FROM collection WHERE location=?", (name,)))
    with db:
        if delete_cards:
            bulk_delete(db, ids, trash_dir, release)
        else:
            for i in ids:
                update(db, i, location="")
        db.execute("DELETE FROM locations WHERE name=?", (name,))
    return {"deleted" if delete_cards else "moved": n}


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
