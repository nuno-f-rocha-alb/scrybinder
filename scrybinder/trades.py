"""Trades: an in-person trade or sale, kept as a draft until confirmed. Confirming takes the outgoing copies out of the collection
and adds the incoming ones; a draft never touches the collection. Outgoing lines name a collection row by its key (row ids change
when rows split or merge) and are looked up again at confirm."""
import datetime
import json

from . import collection, decks

_OUT_KEY = tuple(k for k in collection.KEY if k != "proxy")  # proxies never go out
_IN_KEY = ("scryfall_id", "finish", "condition", "language", "location")
_PRICE = "CASE {t}.finish WHEN 'foil' THEN k.eur_foil WHEN 'etched' THEN k.eur_etched ELSE k.eur END"
_SIDES = {"out": ("trade_out", _OUT_KEY + ("untracked",)), "in": ("trade_in", _IN_KEY)}
# What makes two outgoing lines the same card: the location is not part of it, the copies come from wherever they are free
_SAME = {"out": tuple(c for c in _SIDES["out"][1] if c != "location"), "in": _IN_KEY}
_ANYWHERE = tuple(k for k in _OUT_KEY if k != "location")
TRADE_EDIT = ("who", "note", "cash", "date")
LINE_FIELDS = ("quantity", "price", "finish", "condition", "language", "location")  # what a line edit may carry
_LINE_EDIT = {"out": ("quantity", "price"), "extra": ("quantity", "price", "finish", "condition", "language"), "in": ("quantity", "price", "finish", "condition", "language", "location")}


def _trade(db, trade_id: int, draft: bool = False):
    t = db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t:
        raise KeyError(trade_id)
    if draft and t["status"] != "draft":
        raise ValueError("this trade is already done")
    return t


def _num(v, what: str, minimum=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (minimum is not None and v < minimum):
        raise ValueError(f"{what}: a number" + (f" of {minimum} or more" if minimum is not None else ""))
    return v


def _qty(v):
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise ValueError("quantity: a whole number, 1 or more")
    return v


def _text(v, what: str) -> str:
    if v is not None and not isinstance(v, str):
        raise ValueError(f"{what}: text")
    return (v or "").strip()


def create(db, who="", note="", cash=0) -> int:
    with db:
        return db.execute("INSERT INTO trades (who, note, cash, traded_on) VALUES (?,?,?,date('now','localtime'))",
                          (str(who or "").strip()[:200], str(note or "").strip()[:2000], _num(cash or 0, "cash"))).lastrowid


def update(db, trade_id: int, **fields) -> None:
    _trade(db, trade_id)
    sets, args = [], []
    for k, v in fields.items():
        if k in ("who", "note"):
            sets.append(f"{k}=?"); args.append(str(v or "").strip()[: 200 if k == "who" else 2000])
        elif k == "date":
            try:
                args.append(datetime.date.fromisoformat(v).isoformat() if v else None)
            except (TypeError, ValueError):
                raise ValueError("date: YYYY-MM-DD")
            sets.append("traded_on=?")
        elif k == "cash":
            sets.append("cash=?"); args.append(_num(v or 0, "cash"))
    if sets:
        with db:
            db.execute(f"UPDATE trades SET {','.join(sets)} WHERE id=?", args + [trade_id])


def delete(db, trade_id: int) -> None:
    _trade(db, trade_id)
    with db:
        db.execute("DELETE FROM trades WHERE id=?", (trade_id,))


def add_out(db, trade_id: int, collection_id: int, quantity: int = 1) -> int:
    _trade(db, trade_id, draft=True)
    quantity = _qty(quantity)
    row = db.execute("SELECT * FROM collection WHERE id=?", (collection_id,)).fetchone()
    if not row:
        raise KeyError(collection_id)
    if row["proxy"]:
        raise ValueError("a proxy is not a real copy: it cannot be traded")
    return _add(db, trade_id, "out", {**{k: row[k] for k in _OUT_KEY}, "untracked": 0}, quantity)


def add_extra(db, trade_id: int, scryfall_id: str, quantity: int = 1, price=None, **fields) -> int:
    """A card going out that you own but never put in the collection: it is recorded and valued, nothing is taken out at confirm."""
    _trade(db, trade_id, draft=True)
    key = {"scryfall_id": scryfall_id, **{k: _text(fields.get(k), k) or collection.DEFAULTS[k] for k in ("finish", "condition", "language")}}
    _check_in(db, key)
    key.update(location="", altered=0, signed=0, misprint=0, untracked=1)
    return _add(db, trade_id, "out", key, _qty(quantity), None if price is None else _num(price, "price", 0))


def add_in(db, trade_id: int, scryfall_id: str, quantity: int = 1, price=None, **fields) -> int:
    _trade(db, trade_id, draft=True)
    key = {"scryfall_id": scryfall_id, **{k: _text(fields.get(k), k) or collection.DEFAULTS[k] for k in _IN_KEY[1:]}}
    _check_in(db, key)
    return _add(db, trade_id, "in", key, _qty(quantity), None if price is None else _num(price, "price", 0))


def _check_in(db, key: dict) -> None:
    card = db.execute("SELECT finishes FROM cards WHERE id=?", (key["scryfall_id"],)).fetchone()
    if not card:
        raise ValueError("unknown card")
    if key["finish"] not in (_finishes(card["finishes"]) or ["nonfoil"]):
        raise ValueError(f"this printing does not come in {key['finish']}")
    if key["condition"] not in ("NM", "LP", "MP", "HP", "DMG"):
        raise ValueError("condition: NM, LP, MP, HP or DMG")


def _finishes(text) -> list[str]:
    try:
        return json.loads(text or "[]")
    except ValueError:
        return []


def _add(db, trade_id: int, side: str, key: dict, quantity: int, price=None) -> int:
    table, cols = _SIDES[side]
    same = _SAME[side]
    where = " AND ".join(f"{c}=?" for c in same)
    with db:
        have = db.execute(f"SELECT id FROM {table} WHERE trade_id=? AND {where}", [trade_id] + [key[c] for c in same]).fetchone()
        if have:
            db.execute(f"UPDATE {table} SET quantity=quantity+? WHERE id=?", (quantity, have["id"]))
            return have["id"]
        return db.execute(f"INSERT INTO {table} (trade_id, {','.join(cols)}, quantity, price) VALUES (?,{','.join('?' * len(cols))},?,?)",
                          [trade_id] + [key[c] for c in cols] + [quantity, price]).lastrowid


def edit_line(db, trade_id: int, side: str, line_id: int, **fields) -> None:
    _trade(db, trade_id, draft=True)
    table, cols = _SIDES[side]
    line = db.execute(f"SELECT * FROM {table} WHERE id=? AND trade_id=?", (line_id, trade_id)).fetchone()
    if not line:
        raise KeyError(line_id)
    new = {k: fields[k] for k in _LINE_EDIT["extra" if side == "out" and line["untracked"] else side] if k in fields}
    if "quantity" in new:
        _qty(new["quantity"])
    if "price" in new and new["price"] is not None:
        _num(new["price"], "price", 0)
    if len(new.keys() & {"finish", "condition", "language", "location"}):
        merged = {**dict(line), **new}
        for k in _IN_KEY[1:]:
            merged[k] = _text(merged[k], k) if k == "location" else (_text(merged[k], k) or collection.DEFAULTS[k])
            if k in new:
                new[k] = merged[k]
        _check_in(db, merged)
    if new:
        with db:
            try:
                db.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in new)} WHERE id=?", list(new.values()) + [line_id])
            except Exception as e:  # the edit made it identical to another line of this trade (unique key)
                if "UNIQUE" not in str(e):
                    raise
                raise ValueError("another line of this trade already has that card, finish and condition")


def delete_line(db, trade_id: int, side: str, line_id: int) -> None:
    _trade(db, trade_id, draft=True)
    with db:
        if not db.execute(f"DELETE FROM {_SIDES[side][0]} WHERE id=? AND trade_id=?", (line_id, trade_id)).rowcount:
            raise KeyError(line_id)


def _free_rows(db, line) -> list[dict]:
    """The collection rows an outgoing line takes copies from (the same card in any location; the line's own location first), with how many
    of each are not held by a deck."""
    where = " AND ".join(f"c.{k}=?" for k in _ANYWHERE)
    rows = [dict(r) for r in db.execute(f"SELECT c.id, c.quantity, c.location FROM collection c WHERE c.proxy=0 AND {where} ORDER BY (c.location=?) DESC, c.id",
                                        [line[k] for k in _ANYWHERE] + [line["location"]])]
    held = {}
    for u in decks.users(db, [r["id"] for r in rows]):
        held[u["collection_id"]] = held.get(u["collection_id"], 0) + u["quantity"]
    for r in rows:
        r["free"] = max(r["quantity"] - held.get(r["id"], 0), 0)
    return rows


def get(db, trade_id: int, availability: bool = True) -> dict:
    t = dict(_trade(db, trade_id))
    base = "SELECT l.*, k.name, k.set_code, k.collector_number, k.cardmarket_id, {p} AS market FROM {t} l JOIN cards k ON k.id=l.scryfall_id WHERE l.trade_id=? ORDER BY k.name, l.id"
    for side, (table, _) in _SIDES.items():
        t[side] = [dict(r) for r in db.execute(base.format(p=_PRICE.format(t="l"), t=table), (trade_id,))]
    for line in t["out"] if availability and t["status"] == "draft" else []:
        if line["untracked"]:
            continue
        rows = _free_rows(db, line)
        line["available"] = sum(r["free"] for r in rows)
        line["places"] = [{"location": r["location"], "free": r["free"]} for r in rows if r["free"]]  # where the copies are
    for line in t["out"] + t["in"]:
        line["price_each"] = line["price"] if line["price"] is not None else line["market"]
        line["line_value"] = round(line["quantity"] * (line["price_each"] or 0), 2)
    _totals(t)
    return t


def _totals(t: dict) -> None:
    t["out_cards"], t["in_cards"] = sum(x["quantity"] for x in t["out"]), sum(x["quantity"] for x in t["in"])
    t["out_value"], t["in_value"] = round(sum(x["line_value"] for x in t["out"]), 2), round(sum(x["line_value"] for x in t["in"]), 2)
    t["net"] = round(t["in_value"] - t["out_value"] + t["cash"], 2)


def listing(db) -> list[dict]:
    ids = [r[0] for r in db.execute("SELECT id FROM trades ORDER BY (status='draft') DESC, COALESCE(traded_on, done_at, created_at) DESC, id DESC")]
    out = []
    for i in ids:
        t = get(db, i, availability=False)
        out.append({k: v for k, v in t.items() if k not in ("out", "in")})
    return out


def confirm(db, trade_id: int) -> None:
    """Take the outgoing copies out and add the incoming ones. Every outgoing line is checked before anything changes."""
    t = get(db, trade_id)
    if t["status"] != "draft":
        raise ValueError("this trade is already done")
    if not t["out"] and not t["in"]:
        raise ValueError("the trade has no cards")
    plan = []
    for line in (x for x in t["out"] if not x["untracked"]):  # check every line before changing anything
        rows = _free_rows(db, line)
        free = sum(r["free"] for r in rows)
        if free < line["quantity"]:
            raise ValueError(f"{line['name']} ({line['set_code'].upper()} #{line['collector_number']}, {line['finish']}): "
                             f"{line['quantity']} going out but only {free} free copies (copies in decks cannot be traded)")
        left = line["quantity"]
        for r in rows:
            take = min(left, r["free"])
            if take:
                plan.append((r["id"], r["quantity"], take))
                left -= take
    with db:
        for rid, have, take in plan:
            if take == have:
                collection.delete(db, rid)
            else:
                collection.update(db, rid, quantity=have - take)
        for line in t["in"]:
            collection.add(db, **{k: line[k] for k in _IN_KEY}, quantity=line["quantity"], purchase_price=line["price"])
        for side, (table, _) in _SIDES.items():  # a finished trade keeps the prices it was valued at
            for line in t[side]:
                db.execute(f"UPDATE {table} SET price=? WHERE id=? AND price IS NULL", (line["market"], line["id"]))
        db.execute("UPDATE trades SET status='done', done_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),"
                   " traded_on=COALESCE(traded_on, date('now','localtime')) WHERE id=?", (trade_id,))
