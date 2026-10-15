"""What the details dialog of a card shows: the printing, the rules of the card, its legalities, and its rulings (fetched once, kept)."""
import json
from datetime import datetime, timedelta, timezone

from . import scryfall

RULINGS_TTL = timedelta(days=30)


def details(db, card_id: str) -> dict:
    """The printing `card_id` with the rules data of its card. KeyError when there is no such printing."""
    r = db.execute(
        "SELECT c.id, c.oracle_id, c.name, c.set_code, c.set_name, c.collector_number, c.released_at, c.rarity, c.layout, c.lang, c.finishes,"
        " c.border_color, c.frame, c.full_art, c.cardmarket_id, c.eur, c.eur_foil, c.eur_etched, c.type_line AS print_type,"
        " o.name AS card_name, o.mana_cost, o.cmc, o.type_line, o.oracle_text, o.keywords, o.colors, o.legalities, o.game_changer, o.edhrec_rank,"
        " (SELECT COALESCE(SUM(quantity), 0) FROM collection WHERE scryfall_id = c.id AND proxy = 0) AS owned"
        " FROM cards c LEFT JOIN oracle_cards o ON o.oracle_id = c.oracle_id WHERE c.id=?", (card_id,)).fetchone()
    if not r:
        raise KeyError(card_id)
    d = dict(r)
    for k in ("finishes", "keywords", "colors", "legalities"):
        d[k] = json.loads(d[k]) if d[k] else ([] if k != "legalities" else {})
    d["game_changer"] = bool(d["game_changer"])
    d["type_line"] = d["type_line"] or d["print_type"]
    d["name"] = d["card_name"] or d["name"]
    del d["card_name"], d["print_type"]
    return d


def rulings(db, card_id: str, fetch=None) -> list[dict]:
    """The rulings of a card: from the cache when it is fresh, else from Scryfall (a stale copy is used when Scryfall cannot be reached;
    without any, the error goes up)."""
    fetch = fetch or scryfall.fetch_rulings
    row = db.execute("SELECT oracle_id FROM cards WHERE id=?", (card_id,)).fetchone()
    if not row:
        raise KeyError(card_id)
    oid = row["oracle_id"] or card_id
    cached = db.execute("SELECT data, fetched FROM rulings WHERE oracle_id=?", (oid,)).fetchone()
    now = datetime.now(timezone.utc)
    if cached and now - datetime.fromisoformat(cached["fetched"]) < RULINGS_TTL:
        return json.loads(cached["data"])
    try:
        data = fetch(card_id)
    except Exception:
        if cached:
            return json.loads(cached["data"])
        raise
    with db:
        db.execute("INSERT OR REPLACE INTO rulings VALUES (?,?,?)", (oid, json.dumps(data), now.isoformat()))
    return data
