"""Cardmarket prices (opt-in): the public price guide and product catalogue, by cardmarket_id.

Scryfall only passes on one Cardmarket price per card, a day old, and has no product id for many printings (The List, extras, foil twins). With this on,
the app downloads Cardmarket's own files (a day's cache in <data>/cardmarket/) and keeps avg, low and trend per printing and finish
(cards.cm_*). `cards.eur`/`eur_foil` then hold the chosen price for the collection (Scryfall's own stay in sf_eur/sf_eur_foil);
decks use their own choice through `price_sql`. Nothing about the collection is sent."""
import time
from collections import Counter
from pathlib import Path

import httpx
import ijson

from . import __version__

CATALOG_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
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


def metric(db, scope: str) -> str:
    """The price in use for `scope` ("collection" or "deck")."""
    m = _meta(db, f"price_{scope}", "trend")
    return m if m in METRICS else "trend"


def settings(db) -> dict:
    return {"enabled": enabled(db), "collection": metric(db, "collection"), "deck": metric(db, "deck"),
            "updated_at": _meta(db, "cardmarket_updated"), "metrics": list(METRICS)}


def set_options(db, enabled_: bool | None = None, collection: str | None = None, deck: str | None = None):
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
    apply(db)


def price_sql(db, scope: str, foil: bool = False, p: str = "") -> str:
    """SQL for the euro price of a printing as `scope` prices it: Cardmarket's chosen price, else Scryfall's. `p` prefixes the columns."""
    suffix = "_foil" if foil else ""
    return f"COALESCE({p}cm_{metric(db, scope)}{suffix}, {p}sf_eur{suffix})"


def finish_price_sql(db, scope: str, finish: str, p: str = "") -> str:
    """`price_sql` for the finish held in the SQL expression `finish` (etched has no Cardmarket price: Scryfall's)."""
    return (f"CASE {finish} WHEN 'foil' THEN {price_sql(db, scope, True, p)} WHEN 'etched' THEN {p}eur_etched"
            f" ELSE {price_sql(db, scope, False, p)} END")


def apply(db):
    """Set cards.cm_* from the stored guide and cards.eur/eur_foil from the collection's chosen price. Off: Scryfall's prices alone."""
    m = metric(db, "collection")
    with db:
        db.execute("UPDATE cards SET cm_avg=NULL, cm_low=NULL, cm_trend=NULL, cm_avg_foil=NULL, cm_low_foil=NULL, cm_trend_foil=NULL"
                   " WHERE cm_avg IS NOT NULL OR cm_low IS NOT NULL OR cm_trend IS NOT NULL OR cm_avg_foil IS NOT NULL"
                   " OR cm_low_foil IS NOT NULL OR cm_trend_foil IS NOT NULL")
        if enabled(db):
            db.execute("UPDATE cards SET cm_avg=p.avg, cm_low=p.low, cm_trend=p.trend, cm_avg_foil=p.avg_foil, cm_low_foil=p.low_foil,"
                       " cm_trend_foil=p.trend_foil FROM cm_prices p"
                       " WHERE p.id_product = COALESCE(cards.cardmarket_id, (SELECT id_product FROM cm_link WHERE scryfall_id = cards.id))")
            # a printing with no nonfoil finish (a foil-only twin shares its card's product) has no nonfoil price
            db.execute("UPDATE cards SET cm_avg=NULL, cm_low=NULL, cm_trend=NULL WHERE finishes LIKE '%\"%' AND finishes NOT LIKE '%\"nonfoil\"%'")
        db.execute(f"UPDATE cards SET eur = COALESCE(cm_{m}, sf_eur), eur_foil = COALESCE(cm_{m}_foil, sf_eur_foil)"
                   f" WHERE eur IS NOT COALESCE(cm_{m}, sf_eur) OR eur_foil IS NOT COALESCE(cm_{m}_foil, sf_eur_foil)")


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
        "SELECT id, name FROM cards WHERE set_code=? AND digital=0 AND cardmarket_id IS NULL", (LIST_SET,))}
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
    by_name = {}
    for pid, name, exp in found:
        if exp in list_exp:
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
    taken = {r[0] for r in db.execute("SELECT cardmarket_id FROM cards WHERE cardmarket_id IS NOT NULL")}
    free = {}  # (set, name) -> the products of the set's expansions no printing has
    for pid, name, exp in products:
        if exp in owner and pid not in taken:
            free.setdefault((owner[exp], name), set()).add(pid)
    cards = db.execute("SELECT id, set_code, name, collector_number, finishes FROM cards"
                       " WHERE digital=0 AND cardmarket_id IS NULL AND set_code != ?", (LIST_SET,)).fetchall()
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


def refresh(db, data_dir: Path, force: bool = False, progress=None) -> bool:
    """Download what is a day old, store it and lay the prices out. False when it is off or already fresh."""
    if not enabled(db):
        return False
    folder = Path(data_dir) / "cardmarket"
    guide, catalog = folder / "price_guide_1.json", folder / "products_singles_1.json"
    if not force and _fresh(guide) and _fresh(catalog):
        return False
    _download(GUIDE_URL, guide, progress)
    _download(CATALOG_URL, catalog, progress)
    load_guide(db, guide)
    link_list(db, catalog)
    link_printings(db, catalog)  # after link_list, which replaces cm_link
    with db:
        _set_meta(db, "cardmarket_updated", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    apply(db)
    return True
