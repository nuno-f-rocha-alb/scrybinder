"""EDHREC's data for a commander (card suggestions). EDHREC has no official API; its site reads static JSON from json.edhrec.com, which
is what this fetches: one request per commander, kept on disk for a day, with an identified User-Agent. Only the commander's name
(as a slug) leaves the computer. It is opt-in (see the `edhrec_enabled` setting) and fails with a clear message when EDHREC cannot be reached."""
import json
import re
import time
import unicodedata
from pathlib import Path

import httpx

from . import __version__

URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
HEADERS = {"User-Agent": f"Scrybinder/{__version__} (+https://github.com/nuno-f-rocha-alb/scrybinder)", "Accept": "application/json"}
MIN_AGE = 24 * 3600  # a saved copy is used for this long
MAX_BYTES = 5_000_000


def slug(names: list[str]) -> str:
    """EDHREC's slug for a commander (or a pair of partners): ASCII, lower case, apostrophes dropped, other punctuation a hyphen; a
    double-faced card by its front face; partners sorted by slug and joined."""
    parts = []
    for n in names:
        n = unicodedata.normalize("NFKD", n.split(" // ")[0]).encode("ascii", "ignore").decode().lower().replace("'", "")
        parts.append(re.sub(r"[^a-z0-9]+", "-", n).strip("-"))
    return "-".join(sorted(parts))


def _trim(raw: dict, now: float | None = None) -> dict:
    jd = raw["container"]["json_dict"]
    card = jd["card"]
    return {"fetched": time.time() if now is None else now, "slug": card.get("sanitized") or card.get("slug"),
            "card": {k: card.get(k) for k in ("name", "num_decks", "salt", "rank", "color_identity")},
            "lists": [{"tag": l.get("tag"), "header": l.get("header"),
                       "cards": [{k: c.get(k) for k in ("id", "name", "num_decks", "potential_decks", "synergy", "lift")} for c in l.get("cardviews", [])]}
                      for l in jd.get("cardlists", [])]}


def fetch(slug_: str, data_dir: Path | str, now: float | None = None) -> dict:
    """The commander's suggestions as {fetched, stale, slug, card, lists}. A saved copy under a day old is used as it is; EDHREC is asked
    otherwise, and a saved copy of any age stands in when it cannot be reached (`stale`). Raises ValueError with a message to show."""
    if not re.fullmatch(r"[a-z0-9-]{1,160}", slug_):
        raise ValueError("this commander has no usable name for EDHREC")
    path = Path(data_dir) / "edhrec" / f"{slug_}.json"
    now = time.time() if now is None else now
    saved = None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if saved and now - saved["fetched"] < MIN_AGE:
        return {**saved, "stale": False}
    try:
        r = httpx.get(URL.format(slug=slug_), headers=HEADERS, timeout=30, follow_redirects=False)
        if r.status_code in (403, 404):
            raise ValueError("EDHREC has no page for this commander (too few decks, or a new card)")
        if r.status_code != 200 or len(r.content) > MAX_BYTES:
            raise httpx.HTTPError(f"status {r.status_code}")
        data = {**_trim(r.json(), now), "slug": slug_}  # the slug we asked for: it is what the credit link needs
    except ValueError as e:
        if str(e).startswith("EDHREC has no page"):
            raise
        data = None
    except (httpx.HTTPError, KeyError, TypeError):
        data = None
    if data is None:
        if saved:
            return {**saved, "stale": True}
        raise ValueError("could not get the suggestions from EDHREC: check your connection and try again")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return {**data, "stale": False}
