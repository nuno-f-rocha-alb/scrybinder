"""The Pauper metagame, from MTGGoldfish and MTGTop8 (opt-in, see the `pauper_meta_enabled` setting). Neither site has an API, so this reads
their pages: one for the list of archetypes with their share of the metagame, then one sample list per archetype (the most recent
one for the archetype). A source is fetched in the background, with a pause between pages, and kept on disk for a day; nothing from your
collection is sent, only page requests. If a site changes its pages the parsers find nothing and the tab says so."""
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import __version__, decks, decktext, suggest

SOURCES = {"goldfish": "MTGGoldfish", "top8": "MTGTop8"}
HOSTS = ("www.mtggoldfish.com", "www.mtgtop8.com")
HEADERS = {"User-Agent": f"Scrybinder/{__version__} (+https://github.com/nuno-f-rocha-alb/scrybinder)"}
MIN_AGE = 24 * 3600  # a saved copy is used for this long
MAX_BYTES = 3_000_000
PAUSE = 1.2  # seconds between pages: be gentle with the sites
MAX_ARCHETYPES = 30  # the biggest ones by share: bounds the number of requests (and the time) of a refresh
_CAT = {"AGGRO": "Aggro", "CONTROL": "Control", "COMBO": "Combo"}


def _get(url: str) -> str:
    if urlparse(url).hostname not in HOSTS:
        raise ValueError("host not allowed")
    time.sleep(PAUSE)
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=False)
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        raise httpx.HTTPError(f"status {r.status_code}")
    return r.text


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _en_month(text: str) -> str:
    """'Oct 3, 2026' -> '10 3, 2026': strptime's %b follows the process locale, the sites are always English."""
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    head, _, rest = text.strip().partition(" ")
    return f"{months.index(head[:3].lower()) + 1} {rest}" if head[:3].lower() in months else text


def _iso(text: str, fmts: tuple[str, ...]) -> str:
    for f in fmts:
        try:
            return datetime.strptime(text.strip(), f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


# --- MTGGoldfish ---
def goldfish_index(page: str) -> list[dict]:
    """[{slug, name, meta}] from /metagame/pauper/full, in the order of the page (biggest first)."""
    out = []
    for tile in page.split("<div class='archetype-tile' id=")[1:]:
        m = re.search(r'href="/archetype/([\w-]+)#paper">([^<]+)</a>', tile)
        if not m:
            continue
        share = re.search(r"META%\s*</div>\s*<div class='archetype-tile-statistic-value'>\s*([\d.]+)%", tile)
        out.append({"slug": m.group(1), "name": html.unescape(m.group(2)).strip(), "meta": float(share.group(1)) if share else 0.0})
    return out


def goldfish_deck(page: str) -> dict | None:
    """The sample list of an archetype page: {list, author, event, date}, or None when the page has none."""
    m = re.search(r'id="deck_input_deck" value="([^"]*)"', page)
    if not m:
        return None
    info = _text((re.search(r"(?s)<p class='deck-container-information'>(.*?)</p>", page) or [None, ""])[1])
    event = re.search(r"Event: (.*?)(?: Deck Source:|$)", info)
    date = re.search(r"Deck Date: (.*)$", info)
    author = re.search(r"(?s)<span class='author'>\s*by\s*(.*?)</span>", page)
    return {"list": html.unescape(m.group(1)).strip(), "author": _text(author.group(1)) if author else "",
            "event": re.sub(r"\s+,", ",", event.group(1)).strip() if event else "",
            "date": _iso(_en_month(date.group(1)), ("%m %d, %Y",)) if date else ""}


# --- MTGTop8 ---
def top8_index(page: str) -> tuple[list[dict], str]:
    """([{a, meta, name, meta_pct, cat}], period) from /format?f=PAU."""
    out = []
    for block in re.split(r"class=meta_arch[^>]*>", page)[1:]:
        cat = _CAT.get((re.match(r"[A-Z]+", block) or [""])[0], "")
        for m in re.finditer(r"(?s)archetype\?a=(\d+)&meta=(\d+)&f=PAU>([^<]+)</a>.*?class=S14>(\d+) %", block):
            out.append({"a": m.group(1), "meta": m.group(2), "name": html.unescape(m.group(3)).strip(), "meta_pct": float(m.group(4)), "cat": cat})
    period = re.search(r'onclick="ToggleMetaList\(\);"><div style="padding:3px;" class=S14>([^<]+)</div>', page)
    decks_n = re.search(r"<div class=S14 align=center>(\d+) decks</div>", page)
    return out, ", ".join(x for x in (period.group(1) if period else "", f"{decks_n.group(1)} decks" if decks_n else "") if x)


def top8_row(page: str) -> dict | None:
    """The first deck listed on an archetype page: {event_id, deck_id, author, event, date}, or None."""
    m = re.search(r"(?s)<tr class=hover_tr>.*?<a href=/event\?e=(\d+)&d=(\d+)&f=PAU>[^<]+</a></td>\s*<td><a class=player[^>]*>([^<]+)</a></td>"
                  r"\s*<td><a [^>]*>([^<]+)</a></td>\s*<td[^>]*>.*?</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>", page)
    if not m:
        return None
    rank = m.group(5).strip()
    event = html.unescape(m.group(4)).strip()
    return {"event_id": m.group(1), "deck_id": m.group(2), "author": html.unescape(m.group(3)).strip(),
            "event": f"{event}, {rank}" if rank else event, "date": _iso(m.group(6), ("%d/%m/%y",))}


# --- fetching and the saved copy ---
def _path(source: str, data_dir) -> Path:
    return Path(data_dir) / "pauper" / f"{source}.json"


def load(source: str, data_dir) -> dict | None:
    try:
        return json.loads(_path(source, data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stale(saved: dict | None, now: float | None = None) -> bool:
    return not saved or (time.time() if now is None else now) - saved["fetched"] >= MIN_AGE


def fetch(source: str, data_dir, progress=lambda done, total: None) -> dict:
    """Read a source's pages and save the result as {fetched, source, period, decks:[{id, name, meta, cat, author, event, date, url, list}]}.
    A page that fails is skipped; with nothing at all the saved copy is left alone and ValueError says why."""
    if source not in SOURCES:
        raise ValueError("source: goldfish or top8")
    found, period = [], ""
    try:
        if source == "goldfish":
            index = sorted(goldfish_index(_get("https://www.mtggoldfish.com/metagame/pauper/full")), key=lambda a: -a["meta"])[:MAX_ARCHETYPES]
            period = "current metagame"
        else:
            index, period = top8_index(_get("https://www.mtgtop8.com/format?f=PAU"))
            index = sorted(index, key=lambda a: -a["meta_pct"])[:MAX_ARCHETYPES]
    except (httpx.HTTPError, ValueError):
        raise ValueError(f"could not reach {SOURCES[source]}: check your connection and try again") from None
    if not index:
        raise ValueError(f"{SOURCES[source]} returned no archetypes: its pages may have changed")
    progress(0, len(index))
    for n, a in enumerate(index, start=1):
        try:
            if source == "goldfish":
                url = f"https://www.mtggoldfish.com/archetype/{a['slug']}"
                d = goldfish_deck(_get(url))
                item = d and {"id": a["slug"], "name": a["name"], "meta": a["meta"], "cat": "", "url": url, **d}
            else:
                row = top8_row(_get(f"https://www.mtgtop8.com/archetype?a={a['a']}&meta={a['meta']}&f=PAU"))
                text = row and _get(f"https://www.mtgtop8.com/mtgo?d={row['deck_id']}").strip()
                item = row and text and {"id": a["a"], "name": a["name"], "meta": a["meta_pct"], "cat": a["cat"], "author": row["author"], "event": row["event"],
                                         "date": row["date"], "url": f"https://www.mtgtop8.com/event?e={row['event_id']}&d={row['deck_id']}&f=PAU", "list": text}
        except (httpx.HTTPError, ValueError):
            item = None
        if item and item["list"]:
            found.append(item)
        progress(n, len(index))
    if not found:
        raise ValueError(f"no deck list could be read from {SOURCES[source]}: try again later")
    data = {"fetched": time.time(), "source": source, "period": period, "decks": found}
    path = _path(source, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return data


# --- the saved copy against your database ---
def _resolved(db, saved: dict) -> list[list[dict]]:
    """Each saved list as resolved cards ({oracle_id, name, quantity, board}); unknown cards are left out."""
    items = [{**it, "k": k} for k, d in enumerate(saved["decks"]) for it in decktext.parse(d["list"])]
    ok, _ = decktext.resolve(db, items)
    out = [[] for _ in saved["decks"]]
    for it in ok:
        if it["board"] in ("main", "side"):
            out[it["k"]].append(it)
    return out


def _rows(db, oids) -> dict:
    oids = list(oids)
    rows = {}
    for k in range(0, len(oids), 400):
        mark = ",".join("?" * len(oids[k:k + 400]))
        rows.update({r["oracle_id"]: r for r in db.execute(
            f"SELECT o.oracle_id, o.name, o.mana_cost, o.cmc, o.type_line, o.colors, o.color_identity, o.produced_mana, o.legalities FROM oracle_cards o WHERE o.oracle_id IN ({mark})", oids[k:k + 400])})
    return rows


def _deck_qty(db, deck_id) -> dict:
    """{(oracle_id, board): copies} of a deck."""
    return {(o, b): q for o, b, q in db.execute("SELECT oracle_id, board, SUM(quantity) FROM deck_cards WHERE deck_id=? GROUP BY oracle_id, board", (deck_id,))}


def _colors(lines, rows) -> str:
    """The colours of an archetype: those its lands can make, with at least 2 land copies each (one Bojuka Bog is not a colour). Lands
    that make 4 or more colours (Hidden Grotto) are left out, they say nothing about the deck. A spell of another colour played without
    the mana for it (a Mono Red list with an off-colour 4-of) does not count."""
    count = {}
    for it in lines:
        r = rows[it["oracle_id"]]
        if it["board"] == "main" and "Land" in (r["type_line"] or ""):
            made = set(json.loads(r["produced_mana"] or "[]")) & set("WUBRG")
            if len(made) < 4:
                for c in made:
                    count[c] = count.get(c, 0) + it["quantity"]
    return "".join(c for c in "WUBRG" if count.get(c, 0) >= 2)


def meta(db, source: str, data_dir, deck_id: int | None = None) -> dict:
    """The saved copy of a source: {fetched, stale, period, decks:[{... , colors, main:[{oracle_id, name, quantity, owned, in_deck}], side:[...],
    owned_main, total_main, match}]}. `owned_main` counts the copies of the main deck you own (up to what the list plays). With `deck_id`, `in_deck`
    is what that deck holds of each line and `match` the share of the main deck (0-100) it already has."""
    if source not in SOURCES:
        raise ValueError("source: goldfish or top8")
    saved = load(source, data_dir)
    if not saved:
        return {"fetched": None, "stale": True, "period": "", "decks": []}
    lists = _resolved(db, saved)
    oids = {it["oracle_id"] for ls in lists for it in ls}
    rows, have = _rows(db, oids), suggest._have(db, list(oids))
    mine = _deck_qty(db, deck_id) if deck_id is not None else {}
    out = []
    for d, ls in zip(saved["decks"], lists):
        side = {"main": [], "side": []}
        for it in ls:
            side[it["board"]].append({"oracle_id": it["oracle_id"], "name": rows[it["oracle_id"]]["name"], "quantity": it["quantity"],
                                      "owned": have[it["oracle_id"]]["owned"], "in_deck": mine.get((it["oracle_id"], it["board"]), 0)})
        total = sum(c["quantity"] for c in side["main"])
        out.append({k: d[k] for k in ("id", "name", "meta", "cat", "author", "event", "date", "url", "list")} | {
            "colors": _colors(ls, rows), "main": side["main"], "side": side["side"],
            "owned_main": sum(min(c["quantity"], c["owned"]) for c in side["main"]), "total_main": total,
            "match": round(100 * sum(min(c["quantity"], c["in_deck"]) for c in side["main"]) / total) if total else 0})
    return {"fetched": saved["fetched"], "stale": stale(saved), "period": saved["period"], "decks": out}


def cards(db, deck_id: int, source: str, data_dir) -> dict:
    """The cards the archetypes of a source play, for a Pauper deck. `main_share` / `side_share` are the sum of the metagame share of the
    archetypes that play the card in the main deck / the sideboard, `archetypes` how many play it, `avg` its average copies in the main deck of
    those that play it there. `fits` says whether the card is inside the colours of the deck's spells (true for every card while the deck has
    none). Cards the deck already has and basic lands are left out; most played first."""
    deck = decks._deck(db, deck_id)
    if deck["format"] != "pauper":
        raise ValueError("the metagame is for Pauper decks")
    saved = load(source, data_dir)
    if not saved:
        return {"fetched": None, "cards": []}
    stats = {}
    for d, ls in zip(saved["decks"], _resolved(db, saved)):
        seen = {}
        for it in ls:
            s = seen.setdefault(it["oracle_id"], [0, 0])
            s[it["board"] == "side"] += it["quantity"]
        for oid, (m, sb) in seen.items():
            st = stats.setdefault(oid, {"main_share": 0.0, "side_share": 0.0, "archetypes": 0, "main": 0, "in_main": 0})
            st["archetypes"] += 1
            if m:
                st["main_share"] += d["meta"]
                st["main"] += m
                st["in_main"] += 1
            if sb:
                st["side_share"] += d["meta"]
    identity = set()
    for r in db.execute("SELECT o.oracle_id, o.type_line, o.color_identity FROM deck_cards d JOIN oracle_cards o ON o.oracle_id = d.oracle_id WHERE d.deck_id=? AND d.board='main'", (deck_id,)):
        if "Land" not in (r[1] or ""):
            identity |= set(json.loads(r[2] or "[]"))
    in_deck = {r[0] for r in db.execute("SELECT oracle_id FROM deck_cards WHERE deck_id=?", (deck_id,))}
    rows = {o: r for o, r in _rows(db, stats).items() if o not in in_deck and "Basic Land" not in (r["type_line"] or "")}
    have = suggest._have(db, list(rows))
    return {"fetched": saved["fetched"], "colors": "".join(c for c in "WUBRG" if c in identity), "cards": sorted((
        suggest._card(r, have, image_id=suggest.newest_print(db, o), main_share=round(stats[o]["main_share"], 1), side_share=round(stats[o]["side_share"], 1),
                      share=round(stats[o]["main_share"] + stats[o]["side_share"], 1), archetypes=stats[o]["archetypes"],
                      avg=round(stats[o]["main"] / stats[o]["in_main"], 1) if stats[o]["in_main"] else 0,
                      fits=not identity or set(json.loads(r["color_identity"] or "[]")) <= identity) for o, r in rows.items()),
        key=lambda c: (-c["share"], c["name"]))}


def create_deck(db, source: str, deck_ref: str, data_dir) -> int:
    """A new Pauper deck from the saved list of an archetype."""
    saved = load(source, data_dir)
    d = next((x for x in (saved or {"decks": []})["decks"] if x["id"] == deck_ref), None)
    if not d:
        raise ValueError("this list is not in the saved metagame: refresh it")
    deck_id = decks.create(db, d["name"], "pauper", f"{SOURCES[source]}: {d['event']}".strip(": "))
    try:
        decktext.import_text(db, deck_id, d["list"])
    except Exception:
        decks.delete(db, deck_id)  # no empty deck left behind
        raise
    return deck_id
