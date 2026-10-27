"""Decks from a link: fetch a public deck from Moxfield, Archidekt or ManaBox and write it as the text list `decktext` reads.
Only these hosts are ever contacted (the API address is built here, never taken from the link) and redirects are not followed."""
import html
import json
import re
from urllib.parse import urlparse

import httpx

from . import __version__

HEADERS = {"User-Agent": f"Scrybinder/{__version__} (local collection manager)", "Accept": "application/json"}
MAX_BYTES = 8_000_000
_MOXFIELD = {"moxfield.com", "www.moxfield.com"}
_ARCHIDEKT = {"archidekt.com", "www.archidekt.com"}
_MANABOX = {"manabox.app", "www.manabox.app"}


def _get(url: str) -> dict:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=False)
    except httpx.HTTPError as e:
        raise ValueError(f"could not reach the site ({e.__class__.__name__}): check your connection") from None
    if r.status_code == 404:
        raise ValueError("the site did not give the deck: is the link right and the deck public?")
    if r.status_code in (401, 403):
        raise ValueError(f"the site refused the request ({r.status_code}): the deck is private, or the site is blocking Scrybinder right now; try again later")
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        raise ValueError(f"the site answered {r.status_code}: try again later")
    try:
        return r.json()
    except ValueError:
        raise ValueError("the site did not answer with a deck") from None


def _page(url: str) -> str:
    try:
        r = httpx.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=30, follow_redirects=False)
    except httpx.HTTPError as e:
        raise ValueError(f"could not reach the site ({e.__class__.__name__}): check your connection") from None
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        raise ValueError("the site did not give the deck: is the link right and the deck public?")
    return r.text


def _unastro(v):
    """Astro serialises island props as [0, value] (plain) and [1, [items]] (list)."""
    if isinstance(v, list) and len(v) == 2 and v[0] in (0, 1):
        return _unastro(v[1]) if v[0] == 0 else [_unastro(x) for x in v[1]]
    return {k: _unastro(x) for k, x in v.items()} if isinstance(v, dict) else v


def _line(qty, name, setc, number, finish) -> str:
    out = f"{qty} {name}"
    if setc and number:
        out += f" ({setc}) {number}"
    return out + {"foil": " *F*", "etched": " *E*"}.get(finish, "")


def moxfield(deck_id: str) -> str:
    boards = _get(f"https://api2.moxfield.com/v3/decks/all/{deck_id}").get("boards") or {}
    out = []
    for key, title in (("commanders", "Commander"), ("mainboard", "Deck"), ("sideboard", "Sideboard"), ("companions", "Sideboard"), ("maybeboard", "Maybeboard")):
        cards = (boards.get(key) or {}).get("cards") or {}
        if cards:
            out += [title] + [_line(c["quantity"], c["card"]["name"], c["card"].get("set"), c["card"].get("cn"), c.get("finish")) for c in cards.values()] + [""]
    return "\n".join(out)


def archidekt(deck_id: str) -> str:
    cards = _get(f"https://archidekt.com/api/decks/{deck_id}/").get("cards") or []
    boards = {"Commander": [], "Deck": [], "Sideboard": [], "Maybeboard": []}
    for c in cards:
        cats = c.get("categories") or []
        card = c["card"]
        title = "Commander" if "Commander" in cats else "Sideboard" if "Sideboard" in cats else "Maybeboard" if "Maybeboard" in cats else "Deck"
        fin = {"Foil": "foil", "Etched": "etched"}.get(c.get("modifier"))
        boards[title].append(_line(c["quantity"], card["oracleCard"]["name"], (card.get("edition") or {}).get("editioncode"), card.get("collectorNumber"), fin))
    return "\n".join(f"{t}\n" + "\n".join(ls) + "\n" for t, ls in boards.items() if ls)


def manabox(deck_id: str) -> str:
    """ManaBox has no public API: the deck page carries the deck in the props of its page component."""
    for m in re.finditer(r'<astro-island[^>]*\sprops="([^"]*)"', _page(f"https://manabox.app/decks/{deck_id}")):
        try:
            deck = _unastro(json.loads(html.unescape(m.group(1)))).get("deck")
        except (ValueError, AttributeError):
            continue
        if isinstance(deck, dict) and isinstance(deck.get("cards"), list):
            break
    else:
        raise ValueError("could not find a deck on that page: is the link right and the deck public?")
    boards = {0: "Commander", 3: "Deck", 4: "Sideboard", 5: "Maybeboard"}  # ManaBox: 1 oathbreaker and 2 signature spell go to the main deck
    out = {t: [] for t in boards.values()}
    for c in deck["cards"]:
        out[boards.get(c.get("boardCategory"), "Deck")].append(_line(c["quantity"], c["name"], (c.get("setId") or "").lower(), c.get("collectorNumber"), {"Foil": "foil", "Etched": "etched"}.get(c.get("variant"))))
    return "\n".join(f"{t}\n" + "\n".join(ls) + "\n" for t, ls in out.items() if ls)


def fetch_text(url: str) -> str:
    """The deck at a link as a text list; a page that is not shaped as expected is a ValueError, never a crash."""
    try:
        return _fetch_text(url)
    except (KeyError, TypeError, AttributeError):
        raise ValueError("the site's deck was not in the expected format") from None


def _fetch_text(url: str) -> str:
    """The deck at a Moxfield, Archidekt or ManaBox link as a text list. Raises ValueError with a message the user can act on."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise ValueError("paste the https link of the deck")
    parts = [p for p in u.path.split("/") if p]
    if u.hostname in _MANABOX and len(parts) >= 2 and parts[0] == "decks" and re.fullmatch(r"[\w-]{10,40}", parts[1]):
        return manabox(parts[1])
    if u.hostname in _MOXFIELD and len(parts) >= 2 and parts[0] == "decks" and re.fullmatch(r"[\w-]{4,40}", parts[1]):
        return moxfield(parts[1])
    if u.hostname in _ARCHIDEKT and len(parts) >= 2 and parts[0] == "decks" and parts[1].isdigit():
        return archidekt(parts[1])
    raise ValueError("only deck links from Moxfield, Archidekt and ManaBox work (e.g. moxfield.com/decks/...)")
