"""Playmats for the Playtest: images the user drops in `<data>/playmats`, or the art of a card (Scryfall's art_crop, shown dimmed and
blurred because it is small). The choice is kept in meta.playmat."""
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from . import db as dbmod
from . import scryfall

EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
MAX_BYTES = 50 * 1024 * 1024
THUMB = 480
DIM_MAX, BLUR_MAX = 0.8, 12
DEFAULT = {"kind": "none", "dim": 0.35, "blur": 4}
_lock = threading.Lock()


def folder(base: Path | None = None) -> Path:
    return (base or dbmod.DATA_DIR) / "playmats"


def files(base: Path | None = None) -> list[dict]:
    """The images of the folder (no subfolders, no links, nothing over 50 MB), by name."""
    d = folder(base)
    out = []
    if d.is_dir():
        for p in sorted(d.iterdir(), key=lambda p: p.name.lower()):
            if p.suffix.lower() in EXTENSIONS and p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= MAX_BYTES:
                out.append({"name": p.name, "size": p.stat().st_size})
    return out


def file_path(name: str, base: Path | None = None) -> Path | None:
    """The path of a listed image: the name must be one the folder listing has, so no path can get out of the folder."""
    return folder(base) / name if any(f["name"] == name for f in files(base)) else None


def thumb_path(name: str, base: Path | None = None) -> Path | None:
    """A JPEG of at most 480 px for the settings grid, made once per file version."""
    src = file_path(name, base)
    if src is None:
        return None
    from PIL import Image
    st = src.stat()
    key = re.sub(r"[^\w.-]", "_", name)
    dest = (base or dbmod.DATA_DIR) / "cache" / "playmats" / f"{key}.{st.st_mtime_ns}.{st.st_size}.jpg"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(f"{key}.*.jpg"):  # earlier versions of this file
        old.unlink(missing_ok=True)
    try:
        with Image.open(src) as im:
            im.thumbnail((THUMB, THUMB))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=82)
    except (OSError, ValueError, Image.DecompressionBombError):  # a file that is not really an image
        return None
    tmp = dest.with_name(f"{dest.name}.{threading.get_ident()}.part")
    tmp.write_bytes(buf.getvalue())
    tmp.replace(dest)
    return dest


def art_path(db, card_id: str, base: Path | None = None) -> Path | None:
    """The art_crop of a card, fetched once from the Scryfall CDN (the same host as the card images)."""
    if not re.fullmatch(r"[\w-]+", card_id):
        return None
    f = (base or dbmod.DATA_DIR) / "images" / "art" / f"{card_id}.jpg"
    if f.exists():
        return f
    r = db.execute("SELECT image_normal FROM cards WHERE id=?", (card_id,)).fetchone()
    if not r or not r[0] or "/normal/" not in r[0]:
        return None
    with scryfall._img_slots:
        if f.exists():
            return f
        resp = scryfall._get_retry(r[0].replace("/normal/", "/art_crop/"))
        if resp is None:
            return None
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{threading.get_ident()}.part")
        tmp.write_bytes(resp.content)
        tmp.replace(f)
        time.sleep(0.05)
    return f


def get(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key='playmat'").fetchone()
    try:
        cur = json.loads(row[0]) if row else {}
    except ValueError:
        cur = {}
    return {**DEFAULT, **cur} if isinstance(cur, dict) else dict(DEFAULT)


def _num(v, what: str, lo: float, hi: float):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{what}: a number from {lo} to {hi}")
    return v


def put(db, body: dict, base: Path | None = None) -> dict:
    kind = body.get("kind")
    if kind not in ("none", "file", "card"):
        raise ValueError("kind: none, file or card")
    new = {"kind": kind, "dim": _num(body.get("dim", DEFAULT["dim"]), "dim", 0, DIM_MAX), "blur": _num(body.get("blur", DEFAULT["blur"]), "blur", 0, BLUR_MAX)}
    if kind == "file":
        name = body.get("name")
        if not isinstance(name, str) or file_path(name, base) is None:
            raise ValueError("that image is not in the playmats folder")
        new["name"] = name
    elif kind == "card":
        cid = body.get("card_id")
        if not isinstance(cid, str) or not db.execute("SELECT 1 FROM cards WHERE id=?", (cid,)).fetchone():
            raise ValueError("unknown card")
        new["card_id"] = cid
    with db:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('playmat', ?)", (json.dumps(new),))
    return new


def open_folder(base: Path | None = None) -> str:
    d = folder(base)
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        raise ValueError(f"put your images in {d}")
    os.startfile(d)  # Explorer on the folder; nothing is run
    return str(d)
