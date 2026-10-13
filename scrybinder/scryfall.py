"""Scryfall: "Default Cards" bulk data -> SQLite, image cache. Data © Scryfall (scryfall.com)."""
import gzip
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import ijson

from .db import DATA_DIR

from . import __version__  # noqa: E402

HEADERS = {"User-Agent": f"Scrybinder/{__version__} (local collection manager)", "Accept": "application/json;q=0.9,*/*;q=0.8"}
BULK_STALE_DAYS = 7
AUTO_BULK_DAYS = 1  # the app refreshes itself on start-up when the bulk data is older than 1 day (Scryfall only changes prices once a day)
_COLS = ("id oracle_id name set_code set_name collector_number released_at rarity layout lang type_line "
         "full_art border_color frame frame_effects promo_types finishes cardmarket_id eur eur_foil eur_etched "
         "image_small image_normal digital illustration_id image_status").split()
_INSERT = f"INSERT OR REPLACE INTO cards ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})"

_FACE = "INSERT OR REPLACE INTO card_faces (card_id, face, illustration_id, image_normal) VALUES (?,?,?,?)"


def _price(v):
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def card_row(c: dict) -> tuple:
    imgs = c.get("image_uris") or (c.get("card_faces") or [{}])[0].get("image_uris") or {}
    p = c.get("prices") or {}
    return (c["id"], c.get("oracle_id"), c["name"], c.get("set"), c.get("set_name"), c.get("collector_number"),
            c.get("released_at"), c.get("rarity"), c.get("layout"), c.get("lang"), c.get("type_line"),
            int(bool(c.get("full_art"))), c.get("border_color"), c.get("frame"),
            json.dumps(c.get("frame_effects", [])), json.dumps(c.get("promo_types", [])),
            json.dumps(c.get("finishes", [])), c.get("cardmarket_id"),
            _price(p.get("eur")), _price(p.get("eur_foil")), _price(p.get("eur_etched")),
            imgs.get("small"), imgs.get("normal"), int(bool(c.get("digital"))),
            c.get("illustration_id") or (c.get("card_faces") or [{}])[0].get("illustration_id"), c.get("image_status"))


def face_rows(c: dict) -> list[tuple]:
    """Faces with their own image (transform/modal_dfc); single-image cards only have face 0."""
    faces = c.get("card_faces") or []
    if c.get("image_uris") or not faces:
        return [(c["id"], 0, c.get("illustration_id") or (faces[0].get("illustration_id") if faces else None),
                 (c.get("image_uris") or {}).get("normal"))]
    return [(c["id"], i, f.get("illustration_id"), (f.get("image_uris") or {}).get("normal"))
            for i, f in enumerate(faces) if f.get("image_uris")]


_NO_ORACLE = {"token", "double_faced_token", "emblem", "art_series"}  # no rules text worth a deck slot
_ORACLE = ("oracle_id name mana_cost cmc type_line colors color_identity oracle_text keywords produced_mana "
           "legalities game_changer edhrec_rank layout released_at").split()
_ORACLE_INSERT = f"INSERT OR REPLACE INTO oracle_cards ({','.join(_ORACLE)}) VALUES ({','.join('?' * len(_ORACLE))})"


def oracle_row(c: dict) -> tuple | None:
    """Rules data of a printing, or None for tokens/emblems/art cards and entries without an oracle_id."""
    if not c.get("oracle_id") or c.get("layout") in _NO_ORACLE:
        return None
    faces = c.get("card_faces") or []
    f0 = faces[0] if faces else {}
    text = c.get("oracle_text") or " // ".join(f["oracle_text"] for f in faces if f.get("oracle_text"))
    return (c["oracle_id"], c["name"], c.get("mana_cost") or f0.get("mana_cost") or "",
            c.get("cmc") or 0, c.get("type_line") or f0.get("type_line"),
            json.dumps(c.get("colors") or f0.get("colors") or []), json.dumps(c.get("color_identity") or []),
            text, json.dumps(c.get("keywords") or []), json.dumps(c.get("produced_mana") or []),
            json.dumps(c.get("legalities") or {}), int(bool(c.get("game_changer"))), c.get("edhrec_rank"),
            c.get("layout"), c.get("released_at") or "")


def _iter_cards(path: Path):
    with (gzip.open(path, "rb") if path.suffix == ".gz" else open(path, "rb")) as f:
        # .jsonl.gz (formato atual do Scryfall: um objeto por linha) ou .json (array, formato antigo)
        yield from ((json.loads(line) for line in f if line.strip()) if ".jsonl" in path.name else ijson.items(f, "item", use_float=True))


def _keep_newest(rows: dict, r: tuple | None):
    if r and (r[0] not in rows or r[-1] >= rows[r[0]][-1]):
        rows[r[0]] = r


def _store_oracle(db, rows: dict):
    """Replace the oracle rows with `rows` (newest printing per oracle_id) and rebuild the FTS."""
    db.executemany(_ORACLE_INSERT, rows.values())
    db.execute("INSERT INTO oracle_fts(oracle_fts) VALUES('rebuild')")


def backfill_oracle(db, path: Path | str, progress=None) -> int:
    """Fill oracle_cards from a bulk file already on disk (databases created before decks existed)."""
    rows, n = {}, 0
    for c in _iter_cards(Path(path)):
        _keep_newest(rows, oracle_row(c) if "name" in c else None)
        n += 1
        if progress and n % 2000 == 0:
            progress(n)
    with db:
        _store_oracle(db, rows)
    return len(rows)


def import_bulk(db, path: Path | str, progress=None) -> int:
    """Stream-import the bulk JSON. Upserts: never deletes cards (the collection references them)."""
    n = 0
    path = Path(path)
    oracle = {}
    with db:
        batch, faces = [], []
        for c in _iter_cards(path):
            if "id" not in c or "name" not in c:  # ponytail: skip entries without id/name instead of failing the whole import
                continue
            _keep_newest(oracle, oracle_row(c))
            batch.append(card_row(c))
            faces += face_rows(c)
            if len(batch) >= 2000:
                db.executemany(_INSERT, batch)
                db.executemany(_FACE, faces)
                n += len(batch)
                batch.clear()
                faces.clear()
                if progress:
                    progress(n)
        db.executemany(_INSERT, batch)
        db.executemany(_FACE, faces)
        n += len(batch)
        _store_oracle(db, oracle)
        db.execute("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('bulk_updated', ?)",
                   (datetime.now(timezone.utc).isoformat(),))
    refresh_set_totals(db)
    if progress:
        progress(n)
    return n


def refresh_set_totals(db):
    """Pre-computed per-set totals (scanning 118k cards on every request took >1 s)."""
    with db:
        db.execute("DELETE FROM set_totals")
        db.execute("INSERT INTO set_totals SELECT set_code, MAX(set_name), MIN(released_at), COUNT(*),"
                   " COUNT(DISTINCT COALESCE(oracle_id,id)) FROM cards WHERE digital=0 GROUP BY set_code")


def bulk_age_days(db) -> float | None:
    r = db.execute("SELECT value FROM meta WHERE key='bulk_updated'").fetchone()
    if not r:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(r[0])).total_seconds() / 86400


def download_bulk(dest_dir: Path | None = None, progress=None) -> Path:
    """Download "Default Cards" via /bulk-data (JSONL gzip ~80 MB; ~500 MB JSON if the API only offers that)."""
    dest_dir = dest_dir or DATA_DIR / "bulk"
    dest_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as c:
        meta = c.get("https://api.scryfall.com/bulk-data/default-cards").raise_for_status().json()
        uri = meta.get("jsonl_download_uri") or meta["download_uri"]
        dest = dest_dir / ("default-cards.jsonl.gz" if "jsonl" in uri else "default-cards.json")
        tmp = dest.with_name(dest.name + ".part")
        with c.stream("GET", uri) as r, open(tmp, "wb") as out:
            r.raise_for_status()
            done = 0
            for chunk in r.iter_bytes(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, meta.get("compressed_size") or meta.get("size") or 0)
        tmp.replace(dest)
    return dest


def fetch_sets(db) -> int:
    """Sets (name, icon) in a single /sets call."""
    r = httpx.get("https://api.scryfall.com/sets", headers=HEADERS, timeout=30).raise_for_status().json()
    with db:
        db.executemany("INSERT OR REPLACE INTO sets VALUES (?,?,?,?,?)",
                       [(s["code"], s["name"], s.get("icon_svg_uri"), s.get("set_type"), s.get("released_at"))
                        for s in r["data"]])
    return len(r["data"])


def _get_retry(url: str, tries: int = 3):
    """GET with retries: transient failures (429, 5xx, timeout) must not leave a card without an image."""
    for i in range(tries):
        try:
            return httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True).raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (429, 500, 502, 503, 504):
                return None
        except httpx.HTTPError:
            pass
        time.sleep(0.5 * (i + 1))
    return None


def icon_path(db, code: str) -> Path | None:
    if not re.fullmatch(r"[\w-]+", code):
        return None
    f = DATA_DIR / "icons" / f"{code}.svg"
    if f.exists():
        return f
    r = db.execute("SELECT icon_svg_uri FROM sets WHERE code=?", (code,)).fetchone()
    if not r or not r[0]:
        return None
    resp = _get_retry(r[0])
    if resp is None:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.name}.{threading.get_ident()}.part")
    tmp.write_bytes(resp.content)
    tmp.replace(f)
    return f


_img_slots = threading.Semaphore(4)  # ponytail: 4 parallel downloads; the image CDN has no API rate limit


def image_path(db, card_id: str, size: str = "normal") -> Path | None:
    """Cached image; downloaded from the Scryfall CDN the first time (requests spaced 100 ms apart)."""
    if not re.fullmatch(r"[\w-]+", card_id):  # blocks ../ and \ in the file path
        return None
    size = size if size in ("small", "normal", "large") else "normal"
    f = DATA_DIR / "images" / size / f"{card_id}.jpg"
    if f.exists():
        return f
    r = db.execute(f"SELECT image_{'small' if size == 'small' else 'normal'} FROM cards WHERE id=?", (card_id,)).fetchone()
    if not r or not r[0]:
        return None
    if size == "large":  # the bulk only has small/normal; the CDN serves large (672x936) with the same path
        r = (r[0].replace("/normal/", "/large/"),)
    with _img_slots:
        if f.exists():
            return f
        f.parent.mkdir(parents=True, exist_ok=True)
        resp = _get_retry(r[0])
        if resp is None:
            return None
        tmp = f.with_name(f"{f.name}.{threading.get_ident()}.part")
        tmp.write_bytes(resp.content)
        tmp.replace(f)  # atomic: a half-written file is never served
        time.sleep(0.05)
    return f
