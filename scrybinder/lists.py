"""Lists: named sets of cards the user picks (a trade binder, cards for sale, a wants list) to look at and to share. A list is not a
location: it does not say where copies are, a card can be in many lists, and it can hold cards you do not own. Items are copies
of what was picked (printing, finish, condition, language, quantity), not links to collection rows, so editing or moving
collection rows never breaks a list."""
import csv
import io
import json

from . import collection, decks

KEY = ("scryfall_id", "finish", "condition", "language")
MAX_ITEMS = 20000
_PRICE = "CASE i.finish WHEN 'foil' THEN k.eur_foil WHEN 'etched' THEN k.eur_etched ELSE k.eur END"


def _list(db, list_id):
    row = db.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
    if not row:
        raise KeyError(list_id)
    return row


def _name(name) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("a list needs a name")
    return name[:100]


def _touch(db, list_id):
    db.execute("UPDATE lists SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (list_id,))


def create(db, name, note="") -> int:
    if not isinstance(note, str):
        raise ValueError("note: text")
    with db:
        return db.execute("INSERT INTO lists (name, note) VALUES (?,?)", (_name(name), note.strip()[:1000])).lastrowid


def update(db, list_id: int, **fields) -> None:
    _list(db, list_id)
    sets, args = [], []
    if "name" in fields:
        sets.append("name=?"); args.append(_name(fields["name"]))
    if "note" in fields:
        if not isinstance(fields["note"], str):
            raise ValueError("note: text")
        sets.append("note=?"); args.append(fields["note"].strip()[:1000])
    if sets:
        with db:
            db.execute(f"UPDATE lists SET {','.join(sets)}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", args + [list_id])


def delete(db, list_id: int) -> None:
    _list(db, list_id)
    with db:
        db.execute("DELETE FROM lists WHERE id=?", (list_id,))


def _owned(db, sid: str, finish: str) -> int:
    return db.execute("SELECT COALESCE(SUM(quantity),0) FROM collection WHERE scryfall_id=? AND finish=? AND proxy=0", (sid, finish)).fetchone()[0]


def get(db, list_id: int) -> dict:
    out = dict(_list(db, list_id))
    rows = [dict(r) for r in db.execute(
        f"SELECT i.*, k.name, k.set_code, k.collector_number, k.cardmarket_id, ({_PRICE}) AS price FROM list_items i JOIN cards k ON k.id=i.scryfall_id"
        " WHERE i.list_id=? ORDER BY k.name, k.set_code, i.finish, i.id", (list_id,))]
    own = {(r["scryfall_id"], r["finish"]): r["n"] for r in db.execute(
        "SELECT scryfall_id, finish, SUM(quantity) AS n FROM collection WHERE proxy=0 AND scryfall_id IN (SELECT scryfall_id FROM list_items WHERE list_id=?)"
        " GROUP BY scryfall_id, finish", (list_id,))}
    for r in rows:
        r["owned"] = own.get((r["scryfall_id"], r["finish"]), 0)
        r["line_value"] = round(r["quantity"] * (r["price"] or 0), 2)
    out["items"] = rows
    out["cards"] = sum(r["quantity"] for r in rows)
    out["value"] = round(sum(r["line_value"] for r in rows), 2)
    return out


def listing(db) -> list[dict]:
    return [{k: v for k, v in get(db, r[0]).items() if k != "items"} | {"lines": db.execute("SELECT COUNT(*) FROM list_items WHERE list_id=?", (r[0],)).fetchone()[0]}
            for r in db.execute("SELECT id FROM lists ORDER BY updated_at DESC, id DESC")]


def _clean(db, it: dict) -> dict:
    sid = it.get("scryfall_id")
    row = db.execute("SELECT finishes FROM cards WHERE id=?", (sid,)).fetchone() if isinstance(sid, str) else None
    if not row:
        raise ValueError("unknown card")
    q = it.get("quantity", 1)
    if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 9999:
        raise ValueError("quantity: 1 to 9999")
    finish = it.get("finish") or "nonfoil"
    if finish not in (json.loads(row["finishes"] or "[]") or ["nonfoil"]):
        raise ValueError(f"this printing does not come in {finish}")
    cond = it.get("condition") or "NM"
    if cond not in ("NM", "LP", "MP", "HP", "DMG"):
        raise ValueError("condition: NM, LP, MP, HP or DMG")
    lang = it.get("language") or "en"
    note = it.get("note") or ""
    if not isinstance(lang, str) or not isinstance(note, str):
        raise ValueError("language and note: text")
    return {"scryfall_id": sid, "finish": finish, "condition": cond, "language": lang[:6], "quantity": q, "note": note.strip()[:200]}


def add_items(db, list_id: int, items: list[dict]) -> int:
    """Add cards; one that is already in the list adds to its quantity. Returns how many copies were added. All or nothing."""
    _list(db, list_id)
    if not isinstance(items, list) or not items:
        raise ValueError("nothing to add")
    clean = [_clean(db, it) for it in items]
    with db:
        for c in clean:
            have = db.execute("SELECT id FROM list_items WHERE list_id=? AND scryfall_id=? AND finish=? AND condition=? AND language=?",
                              [list_id] + [c[k] for k in KEY]).fetchone()
            if have:
                db.execute("UPDATE list_items SET quantity=MIN(quantity+?, 9999) WHERE id=?", (c["quantity"], have["id"]))
            else:
                if db.execute("SELECT COUNT(*) FROM list_items WHERE list_id=?", (list_id,)).fetchone()[0] >= MAX_ITEMS:
                    raise ValueError(f"a list has at most {MAX_ITEMS} lines")
                db.execute("INSERT INTO list_items (list_id, scryfall_id, finish, condition, language, quantity, note) VALUES (?,?,?,?,?,?,?)",
                           (list_id, c["scryfall_id"], c["finish"], c["condition"], c["language"], c["quantity"], c["note"]))
        _touch(db, list_id)
    return sum(c["quantity"] for c in clean)


def add_from_collection(db, list_id: int, row_ids: list[int]) -> int:
    """Add collection rows with their own quantity (a proxy is not a real copy: it is left out). Rows that no longer exist are ignored."""
    if not isinstance(row_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in row_ids):
        raise ValueError("ids: a list of numbers")
    items = []
    for k in range(0, len(row_ids), 500):
        chunk = row_ids[k:k + 500]
        items += [{"scryfall_id": r["scryfall_id"], "finish": r["finish"], "condition": r["condition"], "language": r["language"], "quantity": r["quantity"]}
                  for r in db.execute(f"SELECT * FROM collection WHERE proxy=0 AND id IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk)]
    return add_items(db, list_id, items)


def create_from_location(db, location: str, name: str = "") -> int:
    """A new list with the cards of a location (a binder, a box or a deck), to trim and share."""
    if not isinstance(location, str):
        raise ValueError("location: text")
    ids = [r[0] for r in db.execute("SELECT id FROM collection WHERE location=? AND proxy=0", (location,))]
    if not ids:
        raise ValueError("that location has no cards")
    list_id = create(db, name or (location.removeprefix(decks.LOC_PREFIX) if location else "No location"))
    add_from_collection(db, list_id, ids)
    return list_id


def edit_item(db, list_id: int, item_id: int, **fields) -> None:
    _list(db, list_id)
    cur = db.execute("SELECT * FROM list_items WHERE id=? AND list_id=?", (item_id, list_id)).fetchone()
    if not cur:
        raise KeyError(item_id)
    merged = {**dict(cur), **{k: v for k, v in fields.items() if k in ("quantity", "finish", "condition", "language", "note")}}
    c = _clean(db, merged)
    other = db.execute("SELECT id, quantity FROM list_items WHERE list_id=? AND scryfall_id=? AND finish=? AND condition=? AND language=? AND id<>?",
                       [list_id] + [c[k] for k in KEY] + [item_id]).fetchone()
    with db:
        if other:  # the edit made it the same card as another line: they become one
            db.execute("UPDATE list_items SET quantity=MIN(quantity+?, 9999) WHERE id=?", (c["quantity"], other["id"]))
            db.execute("DELETE FROM list_items WHERE id=?", (item_id,))
        else:
            db.execute("UPDATE list_items SET finish=?, condition=?, language=?, quantity=?, note=? WHERE id=?",
                       (c["finish"], c["condition"], c["language"], c["quantity"], c["note"], item_id))
        _touch(db, list_id)


def delete_item(db, list_id: int, item_id: int) -> None:
    _list(db, list_id)
    with db:
        if not db.execute("DELETE FROM list_items WHERE id=? AND list_id=?", (item_id, list_id)).rowcount:
            raise KeyError(item_id)
        _touch(db, list_id)


def text(lst: dict) -> str:
    """`N Name (SET) number [*F*|*E*]` per line: what Moxfield, Archidekt and Scrybinder's deck import read."""
    out = []
    for i in lst["items"]:
        out.append(f"{i['quantity']} {i['name']} ({i['set_code'].upper()}) {i['collector_number']}" + {"foil": " *F*", "etched": " *E*"}.get(i["finish"], ""))
    return "\n".join(out) + "\n"


def csv_text(lst: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Quantity", "Name", "Set", "Collector number", "Finish", "Condition", "Language", "Price (EUR)", "Owned", "Note"])
    for i in lst["items"]:
        w.writerow([i["quantity"], i["name"], i["set_code"].upper(), i["collector_number"], i["finish"], i["condition"], i["language"], i["price"] if i["price"] is not None else "", i["owned"], i["note"]])
    return buf.getvalue()


# --- sharing ---

def doc(db, list_id: int, prices: bool = False, note: str = "", title: str = "") -> dict:
    from . import share
    lst = get(db, list_id)
    info = share._info(db, [i["scryfall_id"] for i in lst["items"]])
    lines = [share._line(info, i["scryfall_id"], i["quantity"], i["finish"], prices, cond=i["condition"] if i["condition"] != "NM" else "",
                         lang=i["language"] if i["language"] != "en" else "") for i in lst["items"]]
    return share._doc("list", title or lst["name"], [{"name": "Cards", "cards": [l for l in lines if l]}], prices, note or lst["note"])


def import_doc(db, d: dict, info: dict) -> dict:
    """A shared list becomes a new list (cards this card base does not know are left out; the caller reports them)."""
    list_id = create(db, d["title"], d.get("note", ""))
    items = [{"scryfall_id": c["id"], "finish": c.get("finish", "nonfoil"), "condition": c.get("cond", "NM"), "language": c.get("lang", "en"), "quantity": c["qty"]}
             for s in d["sections"] for c in s["cards"] if c["id"] in info]
    n = 0
    for it in items:  # one by one: a printing that lacks the finish of the shared line is added as non-foil rather than failing the import
        try:
            n += add_items(db, list_id, [it])
        except ValueError:
            n += add_items(db, list_id, [{**it, "finish": "nonfoil"}])
    return {"list_id": list_id, "cards": n}
