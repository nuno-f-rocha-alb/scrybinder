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
SHARE_API = "https://scrybinder-share.scrybinder-share.workers.dev"
SHARE_VIEWER = "https://nuno-f-rocha-alb.github.io/scrybinder"
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
        for r in db.execute("SELECT k.id, k.name, k.set_code, k.collector_number, k.eur, k.eur_foil, k.eur_etched, k.rarity,"
                            " COALESCE(o.type_line, k.type_line) AS type_line, o.cmc, o.colors FROM cards k LEFT JOIN oracle_cards o ON o.oracle_id = k.oracle_id"
                            f" WHERE k.id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["id"]] = r
    return out


def _line(info: dict, sid: str, qty: int, finish: str = "nonfoil", prices: bool = False, price=None, **extra) -> dict | None:
    c = info.get(sid)
    if c is None or qty < 1:
        return None
    line = {"id": sid, "name": c["name"], "set": (c["set_code"] or "").upper(), "cn": c["collector_number"], "qty": int(qty)}
    if finish in ("foil", "etched"):
        line["finish"] = finish
    # what the viewer groups and sorts by (all optional: a link made before this has none of it)
    if c["type_line"]:
        line["ty"] = c["type_line"][:80]
    if c["cmc"] is not None:
        line["mv"] = c["cmc"]
    if c["colors"] is not None:
        line["co"] = "".join(json.loads(c["colors"] or "[]")) or "C"
    if c["rarity"]:
        line["ra"] = c["rarity"]
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


def deck_doc(db, deck_id: int, prices: bool = False, note: str = "", title: str = "", include=None) -> dict:
    deck = decks._deck(db, deck_id)
    cs = decks.include_only(decks.cards(db, deck_id), include)
    info = _info(db, [c["image_id"] for c in cs if c["image_id"]])
    sections = []
    for board, name in (("commander", "Commander"), ("main", "Main"), ("side", "Sideboard"), ("maybe", "Maybeboard")):
        lines = [_line(info, c["image_id"], c["quantity"], c["finish"] or "nonfoil", prices) for c in cs if c["board"] == board and c["image_id"]]
        sections.append({"name": name, "cards": [l for l in lines if l]})
    return _doc("deck", title or deck["name"], sections, prices, note, {"format": deck["format"]})


def trade_doc(db, trade_id: int, prices: bool = False, note: str = "", title: str = "", cash: bool = False) -> dict:
    t = trades.get(db, trade_id)
    info = _info(db, [l["scryfall_id"] for l in t["out"] + t["in"]])
    side = lambda lines: [l for x in lines for l in [_line(info, x["scryfall_id"], x["quantity"], x["finish"], prices, x["price_each"],
                                                           cond=x["condition"] if x["condition"] != "NM" else "")] if l]
    return _doc("trade", title or "Trade", [{"name": "Giving", "cards": side(t["out"])}, {"name": "Getting", "cards": side(t["in"])}], prices, note,
                {"cash": round(t["cash"], 2)} if cash else None)  # the cash (negative: the sender paid) goes only when asked


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
        return deck_doc(db, spec.get("deck_id"), prices, note, title, spec.get("include"))
    if kind == "trade":
        return trade_doc(db, spec.get("trade_id"), prices, note, title, bool(spec.get("cash")))
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
            if c.get("ty"):
                card["ty"] = _text(c["ty"], "ty", 80)
            if isinstance(c.get("mv"), (int, float)) and not isinstance(c["mv"], bool) and 0 <= c["mv"] <= 1000:
                card["mv"] = c["mv"]
            if isinstance(c.get("co"), str) and re.fullmatch(r"[WUBRGC]{1,5}", c["co"]):
                card["co"] = c["co"]
            if c.get("ra") in ("common", "uncommon", "rare", "mythic", "special", "bonus"):
                card["ra"] = c["ra"]
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
    if doc["kind"] == "trade" and isinstance(meta.get("cash"), (int, float)) and not isinstance(meta["cash"], bool):
        clean.setdefault("meta", {})["cash"] = round(meta["cash"], 2)
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


_SPEC_KEYS = ("kind", "deck_id", "trade_id", "list_id", "ids", "filters", "title", "note", "prices", "locations", "cash", "include")


def _ref(spec: dict) -> str | None:
    """What a link is a link to, when that is one thing that can change (a deck, a trade or a list), so it can be found and updated."""
    for k in ("deck_id", "trade_id", "list_id"):
        if isinstance(spec.get(k), int) and not isinstance(spec.get(k), bool):
            return f"{spec.get('kind')}:{spec[k]}"
    return None


def _failure(r):
    msg = ""
    try:
        msg = r.json().get("error", "")
    except ValueError:
        pass
    if r.status_code in (400, 413, 415, 422):
        return ValueError(msg or "the share service refused this document")
    if r.status_code in (403, 404):
        return ValueError(msg or "that link no longer exists on the share service")
    return Unreachable(msg or f"the share service answered {r.status_code}")


def create_link(db, doc: dict, spec: dict | None = None) -> dict:
    """Send the document to the share service and keep what it answers. `spec` (what to share and how) is kept too, so the link can be updated."""
    base = _api()
    try:
        with _client() as c:
            r = c.post(base + "/api/share", json=doc)
    except httpx.HTTPError as e:
        raise Unreachable(f"the share service could not be reached ({type(e).__name__})")
    if r.status_code != 200:
        raise _failure(r)
    got = r.json()
    if not isinstance(got, dict) or not re.fullmatch(r"[0-9A-Za-z]{12}", str(got.get("id", ""))) or not isinstance(got.get("delete_token"), str):
        raise Unreachable("the share service sent an unexpected answer")
    url = f"{base}/s/{got['id']}"  # a page with the preview tags (title, picture) that sends people on to the viewer
    s = summary(doc)
    with db:
        saved = {k: spec[k] for k in _SPEC_KEYS if k in spec} if spec else None
        db.execute("INSERT INTO shares (id, kind, title, url, delete_token, expires_at, spec, ref) VALUES (?,?,?,?,?,?,?,?)",
                   (got["id"], doc["kind"], doc["title"], url, got["delete_token"], got.get("expires"), json.dumps(saved) if saved else None,
                    _ref(saved) if saved else None))
    return {"id": got["id"], "url": url, "expires": got.get("expires"), **{k: s[k] for k in ("lines", "cards")}}


def link_id(text: str) -> str:
    """The id of a share link (the whole link, `?id=...`, or just the id). Only the id is used: the document is always fetched from the share service
    this app is set up with, never from an address typed in."""
    m = (re.search(r"[?&]id=([0-9A-Za-z]{12})(?![0-9A-Za-z])", text or "") or re.search(r"/s/([0-9A-Za-z]{12})(?![0-9A-Za-z])", text or "")
         or re.fullmatch(r"\s*([0-9A-Za-z]{12})\s*", text or ""))
    if not m:
        raise ValueError("this does not look like a Scrybinder share link")
    return m.group(1)


def fetch_link(text: str) -> str:
    """The share document behind a link, as text (the same text `import_text` reads from a downloaded file)."""
    sid, base = link_id(text), _api()
    try:
        with _client() as c:
            r = c.get(f"{base}/api/share/{sid}")
    except httpx.HTTPError as e:
        raise Unreachable(f"the share service could not be reached ({type(e).__name__})")
    if r.status_code in (404, 410):
        raise ValueError("this link has expired or was deleted: ask the sender for a new one")
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        raise Unreachable(f"the share service answered {r.status_code}")
    return r.text


def listing(db) -> list[dict]:
    out = []
    for r in db.execute("SELECT id, kind, title, url, created_at, expires_at, spec FROM shares ORDER BY created_at DESC, rowid DESC"):
        d = dict(r)
        d["can_update"] = bool(d.pop("spec"))
        out.append(d)
    return out


def existing(db, spec: dict) -> dict | None:
    """The newest link that has not expired for the same deck, trade or list, if there is one."""
    ref = _ref(spec)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = ref and db.execute("SELECT id, url, expires_at FROM shares WHERE ref=? AND spec IS NOT NULL AND (expires_at IS NULL OR expires_at > ?)"
                             " ORDER BY created_at DESC, rowid DESC LIMIT 1", (ref, now)).fetchone()
    return dict(row) if row else None


def update_link(db, share_id: str, spec: dict | None = None) -> dict:
    """Put the current cards under the same link and give it 30 more days. Without a new `spec` the link is rebuilt the way it was made;
    the title, message and options of a new one are used, never a different deck, trade or list."""
    row = db.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    if not row:
        raise KeyError(share_id)
    if not row["spec"]:
        raise ValueError("this link was made by an older version and cannot be updated: make a new one")
    keep = ("kind", "deck_id", "trade_id", "list_id")
    new = {**json.loads(row["spec"]), **{k: spec[k] for k in _SPEC_KEYS if spec and k in spec and k not in keep}}
    doc = build(db, new)
    base = _api()
    try:
        with _client() as c:
            r = c.put(f"{base}/api/share/{share_id}", json=doc, headers={"X-Delete-Token": row["delete_token"]})
    except httpx.HTTPError as e:
        raise Unreachable(f"the share service could not be reached ({type(e).__name__}): the link was not updated")
    if r.status_code != 200:
        raise _failure(r)
    got = r.json()
    with db:
        db.execute("UPDATE shares SET title=?, expires_at=?, spec=? WHERE id=?", (doc["title"], got.get("expires"), json.dumps(new), share_id))
    s = summary(doc)
    return {"id": share_id, "url": row["url"], "expires": got.get("expires"), **{k: s[k] for k in ("lines", "cards")}}


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
