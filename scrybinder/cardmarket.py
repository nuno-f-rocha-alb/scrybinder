"""Cardmarket prices (opt-in): the public price guide and product catalogue, by cardmarket_id.

Scryfall only passes on one Cardmarket price per card, a day old, and has no product id for many printings (The List, extras, foil twins). With this on,
the app downloads Cardmarket's own files (a day's cache in <data>/cardmarket/) and keeps avg, low and trend per printing and finish
(cards.cm_*). `cards.eur`/`eur_foil` then hold the chosen price for the collection (Scryfall's own stay in sf_eur/sf_eur_foil);
decks use their own choice through `price_sql`. Nothing about the collection is sent."""
import csv
import gzip
import logging
import re
import time
from collections import Counter
from pathlib import Path

import httpx
import ijson

from . import __version__

CATALOG_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
MTGJSON_URL = "https://mtgjson.com/api/v5/csv/cardIdentifiers.csv.gz"  # opt-in: Cardmarket product ids (mcmId) by Scryfall id, MIT licence, ~15 MB
HEADERS = {"User-Agent": f"Scrybinder/{__version__} (local collection manager)"}
METRICS = ("trend", "avg", "low")
STALE_SECONDS = 24 * 3600  # Cardmarket renews the guide once a day
LIST_SET = "plst"  # The List: sold on Cardmarket under several expansions of its own, which Scryfall only partly links
MIN_LIST_CARDS = 20  # an expansion holding this many linked The List cards is one of The List's
MIN_VOTES, OWNER_SHARE = 3, 0.8  # linked printings that must agree on the set of an expansion, and the share of them
MIN_EXPANSION = 10  # fewer product names than this say too little about which set an expansion belongs to
EXPANSION_FIT = 0.5  # with no linked printing, the share of an expansion's names that are its set's cards (and twice any other set's)


def _meta(db, key, default=None):
    r = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def _set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))


def enabled(db) -> bool:
    return _meta(db, "cardmarket_enabled") == "1"


def mtgjson_on(db) -> bool:
    return enabled(db) and _meta(db, "cardmarket_mtgjson") == "1"


def metric(db, scope: str) -> str:
    """The price in use for `scope` ("collection" or "deck")."""
    m = _meta(db, f"price_{scope}", "trend")
    return m if m in METRICS else "trend"


def settings(db) -> dict:
    return {"enabled": enabled(db), "collection": metric(db, "collection"), "deck": metric(db, "deck"),
            "updated_at": _meta(db, "cardmarket_updated"), "metrics": list(METRICS),
            "mtgjson": _meta(db, "cardmarket_mtgjson") == "1"}


def set_options(db, enabled_: bool | None = None, collection: str | None = None, deck: str | None = None, mtgjson: bool | None = None):
    """Save the settings and lay the prices out again. ValueError for an unknown price."""
    for v in (collection, deck):
        if v is not None and v not in METRICS:
            raise ValueError(f"price: one of {', '.join(METRICS)}")
    with db:
        if enabled_ is not None:
            _set_meta(db, "cardmarket_enabled", "1" if enabled_ else "0")
        if collection is not None:
            _set_meta(db, "price_collection", collection)
        if deck is not None:
            _set_meta(db, "price_deck", deck)
        if mtgjson is not None:
            _set_meta(db, "cardmarket_mtgjson", "1" if mtgjson else "0")
            if not mtgjson:
                db.execute("DELETE FROM cm_pick WHERE manual=0")  # MTGJSON's products go with it; the user's own picks stay
    apply(db)


def price_sql(db, scope: str, foil: bool = False, p: str = "") -> str:
    """SQL for the euro price of a printing as `scope` prices it: Cardmarket's chosen price, else Scryfall's. `p` prefixes the columns."""
    suffix = "_foil" if foil else ""
    return f"COALESCE({p}cm_{metric(db, scope)}{suffix}, {p}sf_eur{suffix})"


def finish_price_sql(db, scope: str, finish: str, p: str = "") -> str:
    """`price_sql` for the finish held in the SQL expression `finish` (etched has no Cardmarket price: Scryfall's)."""
    return (f"CASE {finish} WHEN 'foil' THEN {price_sql(db, scope, True, p)} WHEN 'etched' THEN {p}eur_etched"
            f" ELSE {price_sql(db, scope, False, p)} END")


def apply(db, card_id: str | None = None):
    """Set cards.cm_* from the stored guide and cards.eur/eur_foil from the collection's chosen price. Off: Scryfall's prices alone.
    With `card_id`, only that printing (the picker changes one)."""
    m = metric(db, "collection")
    one, arg = (" AND cards.id = ?", (card_id,)) if card_id else ("", ())
    with db:
        db.execute("UPDATE cards SET cm_avg=NULL, cm_low=NULL, cm_trend=NULL, cm_avg_foil=NULL, cm_low_foil=NULL, cm_trend_foil=NULL"
                   " WHERE (cm_avg IS NOT NULL OR cm_low IS NOT NULL OR cm_trend IS NOT NULL OR cm_avg_foil IS NOT NULL"
                   " OR cm_low_foil IS NOT NULL OR cm_trend_foil IS NOT NULL)" + one, arg)
        if enabled(db):
            db.execute("UPDATE cards SET cm_avg=p.avg, cm_low=p.low, cm_trend=p.trend, cm_avg_foil=p.avg_foil, cm_low_foil=p.low_foil,"
                       " cm_trend_foil=p.trend_foil FROM cm_prices p"
                       " WHERE p.id_product = COALESCE(cards.cardmarket_id, (SELECT id_product FROM cm_pick WHERE scryfall_id = cards.id),"
                       " (SELECT id_product FROM cm_link WHERE scryfall_id = cards.id))" + one, arg)
            # a printing with no nonfoil finish (a foil-only twin shares its card's product) has no nonfoil price
            db.execute("UPDATE cards SET cm_avg=NULL, cm_low=NULL, cm_trend=NULL WHERE finishes LIKE '%\"%' AND finishes NOT LIKE '%\"nonfoil\"%'" + one, arg)
        db.execute(f"UPDATE cards SET eur = COALESCE(cm_{m}, sf_eur), eur_foil = COALESCE(cm_{m}_foil, sf_eur_foil)"
                   f" WHERE (eur IS NOT COALESCE(cm_{m}, sf_eur) OR eur_foil IS NOT COALESCE(cm_{m}_foil, sf_eur_foil))" + one, arg)


def _download(url: str, dest: Path, progress=None):
    """Stream `url` to `dest` (written under a temporary name, so a failure leaves no half file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with httpx.stream("GET", url, headers=HEADERS, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        total, done = int(r.headers.get("content-length") or 0), 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    tmp.replace(dest)


def _fresh(path: Path) -> bool:
    return path.exists() and time.time() - path.stat().st_mtime < STALE_SECONDS


def load_guide(db, path: Path):
    """Replace cm_prices with the guide in `path` ({"priceGuides": [{idProduct, avg, low, trend, avg-foil, ...}]})."""
    with open(path, "rb") as f:  # read it all first: the writer lock is only held for the insert, not for the parsing
        rows = [(g["idProduct"], g.get("avg"), g.get("low"), g.get("trend"), g.get("avg-foil"), g.get("low-foil"), g.get("trend-foil"))
                for g in ijson.items(f, "priceGuides.item", use_float=True)]
    with db:
        db.execute("DELETE FROM cm_prices")
        db.executemany("INSERT OR REPLACE INTO cm_prices VALUES (?,?,?,?,?,?,?)", rows)


def link_list(db, catalog: Path) -> int:
    """Give The List's cards that Scryfall has no Cardmarket product for the product of the same name in The List's expansions.
    A name found in exactly one of them is linked. A name in two could be either printing, so it stays without a price, unless one of the
    products already belongs to another The List card of that name (Scryfall linked it): that one is a different printing, which leaves
    the other. That only holds when this card is the only one of its name still without a product."""
    cards = {r["id"]: r["name"] for r in db.execute(
        "SELECT id, name FROM cards WHERE set_code=? AND digital=0 AND cardmarket_id IS NULL AND id NOT IN (SELECT scryfall_id FROM cm_pick)", (LIST_SET,))}
    wanted = {n for name in cards.values() for n in (name, name.split(" // ")[0])}
    linked = {}  # name -> the products Scryfall already gave to The List cards of that name
    for r in db.execute("SELECT name, cardmarket_id FROM cards WHERE set_code=? AND digital=0 AND cardmarket_id IS NOT NULL", (LIST_SET,)):
        linked.setdefault(r["name"], set()).add(r["cardmarket_id"])
    known = {r[0] for r in db.execute("SELECT cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (LIST_SET,))}
    unlinked = {}  # name -> how many The List cards of that name have no product
    for name in cards.values():
        unlinked[name] = unlinked.get(name, 0) + 1
    expansions, found = {}, []  # expansion -> how many known List cards it holds; candidate products for the wanted names
    with open(catalog, "rb") as f:
        for p in ijson.items(f, "products.item", use_float=True):
            if p["idProduct"] in known:
                expansions[p["idExpansion"]] = expansions.get(p["idExpansion"], 0) + 1
            if p["name"] in wanted:
                found.append((p["idProduct"], p["name"], p["idExpansion"]))
    list_exp = {e for e, n in expansions.items() if n >= MIN_LIST_CARDS}
    picked = {r[0] for r in db.execute("SELECT id_product FROM cm_pick")}  # a product a pick holds is some printing's: never a candidate
    by_name = {}
    for pid, name, exp in found:
        if exp in list_exp and pid not in picked:
            by_name.setdefault(name, set()).add(pid)
    links = {}
    for sid, name in cards.items():
        cand = by_name.get(name) or by_name.get(name.split(" // ")[0]) or set()
        if len(cand) > 1 and unlinked[name] == 1:
            cand = cand - linked.get(name, set())
        if len(cand) == 1:
            links[sid] = next(iter(cand))
    with db:
        db.execute("DELETE FROM cm_link")
        db.executemany("INSERT INTO cm_link VALUES (?, ?)", links.items())
    return len(links)


def _faces(name: str) -> set[str]:
    """The names a printing may go by in the catalogue: whole, or its front face; the file doubles the quotes (""Bones"")."""
    name = name.replace('""', '"')
    return {name, name.split(" // ")[0]}


def link_printings(db, catalog: Path) -> int:
    """Link the other printings Scryfall has no Cardmarket product for, by name inside the printing's own expansions.
    The catalogue has no collector number, so an expansion is tied to a set by the printings Scryfall did link (or, with none, by how
    nearly its product names are that set's cards alone). A printing is linked only when it is the only one of its name in its set
    without a product and exactly one product of that name in those expansions is not already some other printing's. Anything else stays
    without a price, never a guessed one."""
    sets, where = {}, {}  # set -> names of its printings; name -> the sets that have it
    for r in db.execute("SELECT set_code, name FROM cards WHERE digital=0"):
        sets.setdefault(r["set_code"], set()).update(_faces(r["name"]))
    for s, names in sets.items():
        for n in names:
            where.setdefault(n, set()).add(s)
    with open(catalog, "rb") as f:
        products = [(p["idProduct"], p["name"].replace('""', '"'), p["idExpansion"]) for p in ijson.items(f, "products.item", use_float=True)]
    expansion_of, names_of, votes = {}, {}, {}  # product -> expansion; expansion -> its product names; expansion -> Counter of the sets of its linked cards
    for pid, name, exp in products:
        expansion_of[pid] = exp
        names_of.setdefault(exp, set()).add(name)
    for r in db.execute("SELECT set_code, cardmarket_id FROM cards WHERE digital=0 AND cardmarket_id IS NOT NULL"):
        if r["cardmarket_id"] in expansion_of:
            votes.setdefault(expansion_of[r["cardmarket_id"]], Counter())[r["set_code"]] += 1
    owner = {}  # expansion -> its set
    for exp, names in names_of.items():
        top = (votes.get(exp) or Counter(s for name in names for s in where.get(name, ()))).most_common(2) + [(None, 0)]
        if exp in votes:  # the printings Scryfall linked say which set it is
            total = sum(votes[exp].values())
            if top[0][1] >= MIN_VOTES and top[0][1] >= OWNER_SHARE * total:
                owner[exp] = top[0][0]
        elif len(names) >= MIN_EXPANSION and top[0][1] >= EXPANSION_FIT * len(names) and top[0][1] >= 2 * top[1][1]:
            owner[exp] = top[0][0]
    taken = {r[0] for r in db.execute("SELECT cardmarket_id FROM cards WHERE cardmarket_id IS NOT NULL UNION SELECT id_product FROM cm_pick")}
    free = {}  # (set, name) -> the products of the set's expansions no printing has
    for pid, name, exp in products:
        if exp in owner and pid not in taken:
            free.setdefault((owner[exp], name), set()).add(pid)
    cards = db.execute("SELECT id, set_code, name, collector_number, finishes FROM cards"
                       " WHERE digital=0 AND cardmarket_id IS NULL AND set_code != ? AND id NOT IN (SELECT scryfall_id FROM cm_pick)", (LIST_SET,)).fetchall()
    unlinked = Counter((c["set_code"], c["name"]) for c in cards)
    product_of = {(r["set_code"], r["collector_number"], r["name"]): r["cardmarket_id"] for r in db.execute(
        "SELECT set_code, collector_number, name, cardmarket_id FROM cards WHERE digital=0 AND cardmarket_id IS NOT NULL")}
    # sets where Scryfall gave a foil-only twin (collector number "N★") a product other than its card's: there the twins are separate products
    split = {k[0] for k, pid in product_of.items() if k[1].endswith("★") and product_of.get((k[0], k[1][:-1], k[2]), pid) != pid}
    claims = {}  # product -> the printings that would take it
    for c in cards:
        cand = next((free[c["set_code"], n] for n in sorted(_faces(c["name"]), key=len, reverse=True) if (c["set_code"], n) in free), set())
        star = product_of.get((c["set_code"], c["collector_number"][:-1], c["name"])) if c["collector_number"].endswith("★") else None
        if star and not cand and c["finishes"] == '["foil"]' and c["set_code"] not in split:
            claims.setdefault(star, []).append(c["id"])  # a foil-only twin takes its card's product, when the set has no other product of that name
        elif unlinked[c["set_code"], c["name"]] == 1 and len(cand) == 1:
            claims.setdefault(next(iter(cand)), []).append(c["id"])
    links = [(sid, pid) for pid, sids in claims.items() if len(sids) == 1 for sid in sids]  # two printings after one product: neither
    with db:
        db.executemany("INSERT OR IGNORE INTO cm_link VALUES (?, ?)", links)
    return len(links)


def load_catalog(db, path: Path):
    """Replace cm_products with the product list in `path`, so the picker can search it by name."""
    with open(path, "rb") as f:
        rows = [(p["idProduct"], p["name"].replace('""', '"'), p["idExpansion"], (p.get("dateAdded") or "")[:10])
                for p in ijson.items(f, "products.item", use_float=True)]
    with db:
        db.execute("DELETE FROM cm_products")
        db.executemany("INSERT OR REPLACE INTO cm_products VALUES (?,?,?,?)", rows)


def load_mtgjson(db, path: Path) -> int:
    """Give the printings Scryfall has no product for the one MTGJSON knows (mcmId in its cardIdentifiers.csv.gz), when the product is in
    cm_products. A pick the user made stays. Returns how many printings got one."""
    want = {r[0] for r in db.execute("SELECT id FROM cards WHERE digital=0 AND cardmarket_id IS NULL")}
    known = {r[0] for r in db.execute("SELECT id_product FROM cm_products")}
    rows = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            mid = r.get("mcmId") or ""
            if mid.isdigit() and int(mid) in known and r.get("scryfallId") in want:
                rows.append((r["scryfallId"], int(mid)))
    with db:
        db.execute("DELETE FROM cm_pick WHERE manual=0")
        db.executemany("INSERT OR IGNORE INTO cm_pick (scryfall_id, id_product) VALUES (?, ?)", rows)
    return len(rows)


def product_of(db, scryfall_id: str) -> dict:
    """Where a printing's Cardmarket product comes from: {"id": product or None, "source": "scryfall" | "manual" | "mtgjson" | "guess" | None}."""
    r = db.execute("SELECT cardmarket_id FROM cards WHERE id=?", (scryfall_id,)).fetchone()
    if r and r[0] is not None:
        return {"id": r[0], "source": "scryfall"}
    p = db.execute("SELECT id_product, manual FROM cm_pick WHERE scryfall_id=?", (scryfall_id,)).fetchone()
    if p:
        return {"id": p[0], "source": "manual" if p[1] else "mtgjson"}
    k = db.execute("SELECT id_product FROM cm_link WHERE scryfall_id=?", (scryfall_id,)).fetchone()
    return {"id": k[0], "source": "guess"} if k else {"id": None, "source": None}


def _product_id(q: str) -> int | None:
    """A Cardmarket product id typed or pasted: bare digits, or a link with idProduct=N."""
    m = re.fullmatch(r"\s*(\d+)\s*", q) or re.search(r"idProduct=(\d+)", q)
    return int(m.group(1)) if m else None


def search_products(db, q: str, scryfall_id: str | None = None, limit: int = 40) -> list[dict]:
    """The products of Cardmarket's list whose name contains `q` (or the one a pasted id / link names), with their prices, expansion and the other
    printings that already use them. With `scryfall_id` the ones added to Cardmarket nearest that printing's release come first.
    ValueError when the list is not loaded."""
    if not db.execute("SELECT 1 FROM cm_products LIMIT 1").fetchone():
        raise ValueError("The Cardmarket product list is not loaded yet: turn on Cardmarket prices in Settings and wait for the update to finish.")
    released = db.execute("SELECT released_at FROM cards WHERE id=?", (scryfall_id,)).fetchone() if scryfall_id else None
    select = ("SELECT p.id_product, p.name, p.id_expansion, p.date_added, g.trend, g.trend_foil FROM cm_products p"
              " LEFT JOIN cm_prices g ON g.id_product = p.id_product")
    pid = _product_id(q)
    if pid is not None:
        rows = db.execute(select + " WHERE p.id_product=?", (pid,)).fetchall()
    elif len(q.strip()) < 2:
        return []
    else:
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = db.execute(select + " WHERE p.name LIKE ? ESCAPE '\\' ORDER BY COALESCE(ABS(julianday(NULLIF(p.date_added, '')) - julianday(?)), 1e9),"
                          " LENGTH(p.name), p.id_product LIMIT ?", (like, released[0] if released else None, limit)).fetchall()
    ids, exps = [r["id_product"] for r in rows], sorted({r["id_expansion"] for r in rows})
    marks = lambda xs: ",".join("?" * len(xs))
    size = dict(db.execute(f"SELECT id_expansion, COUNT(*) FROM cm_products WHERE id_expansion IN ({marks(exps)}) GROUP BY 1", exps).fetchall()) if exps else {}
    sets = {}  # expansion -> {set: how many of its products Scryfall linked to a printing of that set}
    if exps:
        for r in db.execute("SELECT p.id_expansion, c.set_code, COUNT(*) FROM cards c JOIN cm_products p ON p.id_product = c.cardmarket_id"
                            f" WHERE p.id_expansion IN ({marks(exps)}) GROUP BY 1, 2", exps):
            sets.setdefault(r[0], {})[r[1]] = r[2]
    used = {}  # product -> the other printings that hold it
    if ids:
        for r in db.execute("SELECT u.id_product, c.set_code, c.collector_number FROM ("
                            f"SELECT id, cardmarket_id AS id_product FROM cards WHERE cardmarket_id IN ({marks(ids)})"
                            f" UNION SELECT scryfall_id, id_product FROM cm_pick WHERE id_product IN ({marks(ids)})"
                            f" UNION SELECT scryfall_id, id_product FROM cm_link WHERE id_product IN ({marks(ids)})) u JOIN cards c ON c.id = u.id"
                            " WHERE c.id IS NOT ?", ids * 3 + [scryfall_id]):
            used.setdefault(r[0], []).append(f"{r[1].upper()} #{r[2]}")
    out = []
    for r in rows:
        top = max(sets.get(r["id_expansion"], {}).items(), key=lambda kv: kv[1], default=(None, 0))
        out.append({"id_product": r["id_product"], "name": r["name"], "id_expansion": r["id_expansion"], "date_added": r["date_added"] or None,
                    "expansion_size": size.get(r["id_expansion"], 0), "set_hint": top[0] if top[1] >= MIN_VOTES else None,
                    "trend": r["trend"], "trend_foil": r["trend_foil"], "used_by": sorted(used.get(r["id_product"], []))[:4]})
    return out


def set_pick(db, scryfall_id: str, id_product: int | None):
    """Tie a printing Scryfall has no Cardmarket product for to `id_product` (None: undo the user's pick). It survives every update.
    KeyError for an unknown printing, ValueError when Scryfall already has a product for it or Cardmarket has no such product."""
    r = db.execute("SELECT cardmarket_id FROM cards WHERE id=?", (scryfall_id,)).fetchone()
    if not r:
        raise KeyError(scryfall_id)
    if r[0] is not None:
        raise ValueError("Scryfall already gives this printing its Cardmarket product.")
    if id_product is not None and not db.execute("SELECT 1 FROM cm_products WHERE id_product=?", (id_product,)).fetchone():
        raise ValueError("Cardmarket's product list has no product with that id.")
    with db:
        if id_product is None:
            db.execute("DELETE FROM cm_pick WHERE scryfall_id=? AND manual=1", (scryfall_id,))
        else:
            db.execute("INSERT OR REPLACE INTO cm_pick VALUES (?, ?, 1)", (scryfall_id, id_product))
    apply(db, scryfall_id)


def refresh(db, data_dir: Path, force: bool = False, progress=None) -> bool:
    """Download what is a day old, store it and lay the prices out. False when it is off or already fresh."""
    if not enabled(db):
        return False
    folder = Path(data_dir) / "cardmarket"
    guide, catalog, ids = folder / "price_guide_1.json", folder / "products_singles_1.json", folder / "cardIdentifiers.csv.gz"
    files = [(GUIDE_URL, guide), (CATALOG_URL, catalog)] + ([(MTGJSON_URL, ids)] if mtgjson_on(db) else [])
    todo = [(u, p) for u, p in files if force or not _fresh(p)]
    if not todo and db.execute("SELECT 1 FROM cm_products LIMIT 1").fetchone():  # an empty list (a version before the picker) loads from the files kept
        return False
    use_ids = mtgjson_on(db)
    for u, p in todo:
        try:
            _download(u, p, progress)
        except (httpx.HTTPError, OSError):
            if p != ids:
                raise
            use_ids = False  # the optional source being down must not stop the prices; the products it gave before stay
            logging.getLogger("scrybinder").warning("MTGJSON could not be downloaded; its Cardmarket products were not updated", exc_info=True)
    load_guide(db, guide)
    load_catalog(db, catalog)
    if use_ids:
        try:
            load_mtgjson(db, ids)  # before the links: a printing with a product of its own is not matched by name
        except (OSError, EOFError, csv.Error):  # a damaged file: drop it so the next update fetches it again
            ids.unlink(missing_ok=True)
            logging.getLogger("scrybinder").warning("MTGJSON's file could not be read", exc_info=True)
    link_list(db, catalog)
    link_printings(db, catalog)  # after link_list, which replaces cm_link
    with db:
        _set_meta(db, "cardmarket_updated", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    apply(db)
    return True
