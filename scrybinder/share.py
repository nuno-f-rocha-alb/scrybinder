"""Share links: a deck, a trade, a list or (part of) the collection is turned into a small JSON document, sent to the share Worker
(a Cloudflare Worker that keeps it for 30 days) and opened through the static viewer. The link carries only an id; what is sent is
cards, quantities, finishes and, if asked, prices. Never locations (unless asked), notes, purchase prices, a trade's counterparty or its cash.
The same document can be downloaded from the viewer and imported again."""
import datetime
import json
import os
import re

import httpx

from . import collection, decks, trades
from .scryfall import HEADERS

FORMAT, VERSION = "scrybinder-share", 1
KINDS = ("deck", "list", "trade", "collection")
FINISHES = ("nonfoil", "foil", "etched")
CONDITIONS = ("NM", "LP", "MP", "HP", "DMG")
MAX_LINES, MAX_BYTES = 20000, 2 * 1024 * 1024
MAX_QTY, MAX_TEXT = 9999, 200
# Where the Worker and the viewer are deployed (the README says how); SCRYBINDER_SHARE_API / SCRYBINDER_SHARE_VIEWER override them.
SHARE_API = ""
SHARE_VIEWER = ""
TRANSPORT = None  # tests plug an httpx transport in here


class NotConfigured(ValueError):
    pass


class Unreachable(Exception):
    """The Worker could not be reached or refused the request (HTTP 502 for the UI)."""


def _api() -> str:
    url = (os.environ.get("SCRYBINDER_SHARE_API") or SHARE_API).rstrip("/")
    if not url:
        raise NotConfigured("Sharing is not set up in this build: the share service has not been deployed yet")
    return url


def _viewer() -> str:
    return (os.environ.get("SCRYBINDER_SHARE_VIEWER") or SHARE_VIEWER).rstrip("/")


def _text(v, what: str, limit: int = MAX_TEXT) -> str:
    if v is not None and not isinstance(v, str):
        raise ValueError(f"{what}: text")
    return (v or "").strip()[:limit]


# --- building a document ---


def _info(db, ids) -> dict:
    out, ids = {}, list(dict.fromkeys(ids))
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        for r in db.execute(f"SELECT id, name, set_code, collector_number, eur, eur_foil, eur_etched FROM cards WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["id"]] = r
    return out


def _line(info: dict, sid: str, qty: int, finish: str = "nonfoil", prices: bool = False, price=None, **extra) -> dict | None:
    c = info.get(sid)
    if c is None or qty < 1:
        return None
    line = {"id": sid, "name": c["name"], "set": (c["set_code"] or "").upper(), "cn": c["collector_number"], "qty": int(qty)}
    if finish in ("foil", "etched"):
        line["finish"] = finish
    if prices:
        p = price if price is not None else {"foil": c["eur_foil"], "etched": c["eur_etched"]}.get(finish, c["eur"])
        if p is not None:
            line["price"] = round(p, 2)
    line.update({k: v for k, v in extra.items() if v})
    return line


def _doc(kind: str, title: str, sections: list[dict], prices: bool, note: str = "", meta: dict | None = None) -> dict:
    sections = [s for s in sections if s["cards"]]
    n = sum(len(s["cards"]) for s in sections)
    if not n:
        raise ValueError("there is nothing to share")
    if n > MAX_LINES:
        raise ValueError(f"too many cards to share ({n}); the limit is {MAX_LINES} lines")
    doc = {"format": FORMAT, "v": VERSION, "kind": kind, "title": _text(title, "title") or kind.capitalize(), "created": datetime.date.today().isoformat(),
           "prices": bool(prices), "sections": sections}
    if note:
        doc["note"] = _text(note, "note", 1000)
    if meta:
        doc["meta"] = meta
    if len(json.dumps(doc, separators=(",", ":")).encode()) > MAX_BYTES:
        raise ValueError("this is too big to share")
    return doc


def deck_doc(db, deck_id: int, prices: bool = False, note: str = "", title: str = "") -> dict:
    deck = decks._deck(db, deck_id)
    cs = decks.cards(db, deck_id)
    info = _info(db, [c["image_id"] for c in cs if c["image_id"]])
    sections = []
    for board, name in (("commander", "Commander"), ("main", "Main"), ("side", "Sideboard"), ("maybe", "Maybeboard")):
        lines = [_line(info, c["image_id"], c["quantity"], c["finish"] or "nonfoil", prices) for c in cs if c["board"] == board and c["image_id"]]
        sections.append({"name": name, "cards": [l for l in lines if l]})
    return _doc("deck", title or deck["name"], sections, prices, note, {"format": deck["format"]})


def trade_doc(db, trade_id: int, prices: bool = False, note: str = "", title: str = "") -> dict:
    t = trades.get(db, trade_id)
    info = _info(db, [l["scryfall_id"] for l in t["out"] + t["in"]])
    side = lambda lines: [l for x in lines for l in [_line(info, x["scryfall_id"], x["quantity"], x["finish"], prices, x["price_each"])] if l]
    return _doc("trade", title or "Trade", [{"name": "Giving", "cards": side(t["out"])}, {"name": "Getting", "cards": side(t["in"])}], prices, note)


def collection_doc(db, ids=None, filters=None, prices: bool = False, locations: bool = False, note: str = "", title: str = "") -> dict:
    """The rows `ids` (or those matching `filters`: q, set, location, finish, language). Proxies are left out. Equal cards in
    several locations are one line unless `locations` is on."""
    if ids is None:
        f = filters or {}
        ids = collection.matching_ids(db, f.get("q", ""), f.get("set", ""), f.get("location"), f.get("finish", ""), f.get("language", ""))
    ids = list(dict.fromkeys(ids))
    rows = []
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        rows += [dict(r) for r in db.execute(f"SELECT * FROM collection WHERE proxy=0 AND id IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk)]
    info = _info(db, [r["scryfall_id"] for r in rows])
    merged = {}
    for r in rows:
        key = (r["scryfall_id"], r["finish"], r["condition"], r["language"]) + ((r["location"],) if locations else ())
        merged[key] = merged.get(key, 0) + r["quantity"]
    lines = []
    for key, q in sorted(merged.items(), key=lambda kv: ((info[kv[0][0]]["name"] if kv[0][0] in info else ""), kv[0])):
        l = _line(info, key[0], q, key[1], prices, cond=key[2] if key[2] != "NM" else "", lang=key[3] if key[3] != "en" else "",
                  loc=key[4] if locations and len(key) > 4 else "")
        if l:
            lines.append(l)
    return _doc("collection", title or "Collection", [{"name": "Cards", "cards": lines}], prices, note)


def build(db, spec: dict) -> dict:
    """The document for a share request: {kind, deck_id | trade_id | list_id | ids | filters, title, note, prices, locations}."""
    kind, prices, note, title = spec.get("kind"), bool(spec.get("prices")), _text(spec.get("note"), "note", 1000), _text(spec.get("title"), "title")
    if kind == "deck":
        return deck_doc(db, spec.get("deck_id"), prices, note, title)
    if kind == "trade":
        return trade_doc(db, spec.get("trade_id"), prices, note, title)
    if kind == "collection":
        ids = spec.get("ids")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
            raise ValueError("ids: a list of numbers")
        if ids is None and not isinstance(spec.get("filters") or {}, dict):
            raise ValueError("filters: an object")
        return collection_doc(db, ids, spec.get("filters"), prices, bool(spec.get("locations")), note, title)
    if kind == "list":
        from . import lists
        return lists.doc(db, spec.get("list_id"), prices, note, title)
    raise ValueError("kind: deck, trade, list or collection")


def summary(doc: dict) -> dict:
    return {"configured": bool(os.environ.get("SCRYBINDER_SHARE_API") or SHARE_API), "kind": doc["kind"], "title": doc["title"], "lines": sum(len(s["cards"]) for s in doc["sections"]),
            "cards": sum(c["qty"] for s in doc["sections"] for c in s["cards"]), "bytes": len(json.dumps(doc, separators=(",", ":")).encode())}


# --- reading a document (the same checks the Worker makes) ---

def parse(doc) -> dict:
    """Check a share document and return it cleaned; ValueError says what is wrong."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("this is not a Scrybinder share file")
    if doc.get("v") != VERSION:
        raise ValueError("this share file comes from a newer version of Scrybinder")
    if doc.get("kind") not in KINDS:
        raise ValueError("unknown kind of share")
    secs = doc.get("sections")
    if not isinstance(secs, list) or not 1 <= len(secs) <= 20:
        raise ValueError("sections: 1 to 20")
    out, n = [], 0
    for s in secs:
        if not isinstance(s, dict) or not isinstance(s.get("cards"), list):
            raise ValueError("a section needs cards")
        cards = []
        for c in s["cards"]:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not 0 < len(c["id"]) <= 64:
                raise ValueError("a card needs an id")
            q = c.get("qty")
            if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= MAX_QTY:
                raise ValueError("qty: 1 to %d" % MAX_QTY)
            fin = c.get("finish", "nonfoil")
            if fin not in FINISHES:
                raise ValueError("finish: nonfoil, foil or etched")
            cond = c.get("cond", "NM")
            if cond not in CONDITIONS:
                raise ValueError("condition: NM, LP, MP, HP or DMG")
            card = {"id": c["id"], "name": _text(c.get("name"), "name"), "set": _text(c.get("set"), "set", 10), "cn": _text(c.get("cn"), "cn", 12),
                    "qty": q}
            if fin != "nonfoil":
                card["finish"] = fin
            if cond != "NM":
                card["cond"] = cond
            if c.get("lang") not in (None, "", "en"):
                card["lang"] = _text(c["lang"], "lang", 6)
            if c.get("loc"):
                card["loc"] = _text(c["loc"], "loc")
            p = c.get("price")
            if p is not None:
                if isinstance(p, bool) or not isinstance(p, (int, float)) or p < 0:
                    raise ValueError("price: a number")
                card["price"] = round(p, 2)
            cards.append(card)
        n += len(cards)
        if n > MAX_LINES:
            raise ValueError(f"too many cards (the limit is {MAX_LINES} lines)")
        out.append({"name": _text(s.get("name"), "section") or "Cards", "cards": cards})
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    clean = {"format": FORMAT, "v": VERSION, "kind": doc["kind"], "title": _text(doc.get("title"), "title") or doc["kind"].capitalize(),
             "created": _text(doc.get("created"), "created", 10), "prices": bool(doc.get("prices")), "sections": out}
    if doc.get("note"):
        clean["note"] = _text(doc["note"], "note", 1000)
    if isinstance(meta.get("format"), str):
        clean["meta"] = {"format": meta["format"][:20]}
    return clean


def import_text(db, text: str, location: str = "") -> dict:
    """Bring a share file into the app: a deck becomes a new deck, a collection is added to the collection (in `location`), a list
    becomes a new list; a trade is only for looking at. Cards this card base does not know are skipped and listed."""
    try:
        doc = parse(json.loads(text))
    except json.JSONDecodeError:
        raise ValueError("this is not a Scrybinder share file (the text is not JSON)")
    kind = doc["kind"]
    if kind == "trade":
        raise ValueError("a trade is only for looking at: it cannot be imported")
    cards = [c for s in doc["sections"] for c in s["cards"]]
    info = {r["id"]: r for r in db.execute(f"SELECT id, oracle_id, finishes FROM cards WHERE id IN ({','.join('?' * len(cards))})", [c["id"] for c in cards])} if cards else {}
    skipped = [c["name"] or c["id"] for c in cards if c["id"] not in info]
    result = {"kind": kind, "title": doc["title"], "skipped": skipped, "cards": 0}
    if kind == "deck":
        fmt = doc.get("meta", {}).get("format")
        did = decks.create(db, doc["title"], fmt if fmt in decks.FORMATS else "casual")
        board = {"Commander": "commander", "Main": "main", "Sideboard": "side", "Maybeboard": "maybe"}
        for s in doc["sections"]:
            for c in s["cards"]:
                row = info.get(c["id"])
                if row and row["oracle_id"]:
                    fin = c.get("finish") if c.get("finish") in json.loads(row["finishes"] or "[]") else None
                    decks.add_card(db, did, row["oracle_id"], c["qty"], board.get(s["name"], "main"), c["id"], (), fin)
                    result["cards"] += c["qty"]
        result["deck_id"] = did
    elif kind == "collection":
        loc = _text(location, "location")
        if loc.startswith(decks.LOC_PREFIX):
            raise ValueError("that location name is reserved for decks")
        for c in cards:
            if c["id"] in info:
                collection.add(db, scryfall_id=c["id"], quantity=c["qty"], finish=c.get("finish", "nonfoil"), condition=c.get("cond", "NM"),
                               language=c.get("lang", "en"), location=loc)
                result["cards"] += c["qty"]
    else:
        from . import lists
        result.update(lists.import_doc(db, doc, info))
    return result


# --- talking to the Worker ---

def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30, transport=TRANSPORT)


def create_link(db, doc: dict) -> dict:
    base = _api()
    try:
        with _client() as c:
            r = c.post(base + "/api/share", json=doc)
    except httpx.HTTPError as e:
        raise Unreachable(f"the share service could not be reached ({type(e).__name__})")
    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except ValueError:
            pass
        if r.status_code in (400, 413, 415, 422):
            raise ValueError(msg or "the share service refused this document")
        raise Unreachable(msg or f"the share service answered {r.status_code}")
    got = r.json()
    if not isinstance(got, dict) or not re.fullmatch(r"[0-9A-Za-z]{12}", str(got.get("id", ""))) or not isinstance(got.get("delete_token"), str):
        raise Unreachable("the share service sent an unexpected answer")
    viewer = _viewer()
    url = f"{viewer}/?id={got['id']}" if viewer else f"{base}/api/share/{got['id']}"
    s = summary(doc)
    with db:
        db.execute("INSERT INTO shares (id, kind, title, url, delete_token, expires_at) VALUES (?,?,?,?,?,?)",
                   (got["id"], doc["kind"], doc["title"], url, got["delete_token"], got.get("expires")))
    return {"id": got["id"], "url": url, "expires": got.get("expires"), **{k: s[k] for k in ("lines", "cards")}}


def listing(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT id, kind, title, url, created_at, expires_at FROM shares ORDER BY created_at DESC, rowid DESC")]


def delete_link(db, share_id: str) -> None:
    row = db.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    if not row:
        raise KeyError(share_id)
    base = _api()
    try:
        with _client() as c:
            r = c.delete(f"{base}/api/share/{share_id}", headers={"X-Delete-Token": row["delete_token"]})
    except httpx.HTTPError as e:
        raise Unreachable(f"the share service could not be reached ({type(e).__name__}): the link was not deleted")
    if r.status_code not in (200, 404, 410):  # already gone counts as deleted
        raise Unreachable(f"the share service answered {r.status_code}: the link was not deleted")
    with db:
        db.execute("DELETE FROM shares WHERE id=?", (share_id,))
