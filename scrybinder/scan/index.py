"""Local visual index: card and art vectors per (printing, face), in resumable .npy shards.

data/index/<model>-<preproc_hash>/  manifest.json · rows.db (rows, stable ids) · card_00000.npy · art_00000.npy …
A complete shard (expected row count) is never rebuilt; changing the model/pre-processing changes the folder (they never mix).
"""
import json
import sqlite3
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from .. import scryfall
from ..db import DATA_DIR
from .embed import Stopped, art_box_name, normalize_card, prep_hash

SHARD = 2048
# en/pt + printings that only exist in other languages (e.g. Japanese Mystical Archive), with no en equivalent in the same set/number
SCOPE = ("c.digital=0 AND (c.lang IN ('en','pt') OR NOT EXISTS (SELECT 1 FROM cards e WHERE e.set_code=c.set_code"
         " AND e.collector_number=c.collector_number AND e.lang='en'))")
MIN_INTERVAL = 0.1  # seconds between requests to the Scryfall CDN
SKIP_STATUS = ("missing", "placeholder")  # no usable image
_last = [0.0]


def index_dir(emb, root: Path | None = None) -> Path:
    return (root or DATA_DIR / "index") / f"{emb.tag}-{prep_hash()}"


def _rows_db(d: Path) -> sqlite3.Connection:
    d.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(d / "rows.db")
    db.execute("CREATE TABLE IF NOT EXISTS rows (row INTEGER PRIMARY KEY, card_id TEXT NOT NULL, face INTEGER NOT NULL,"
               " illustration_id TEXT, box TEXT NOT NULL, url TEXT, failed INTEGER NOT NULL DEFAULT 0,"
               " UNIQUE (card_id, face))")
    return db


def add_rows(db, d: Path, where: str = "1", params=(), dry_run=False) -> int:
    """Add the faces (non-digital, in scope, with a usable image) matching `where` that are not in the index yet."""
    rdb = _rows_db(d)
    q = ("SELECT c.id, f.face, COALESCE(f.illustration_id, c.illustration_id), c.frame, c.border_color, f.image_normal"
         " FROM cards c JOIN card_faces f ON f.card_id=c.id WHERE " + SCOPE +
         " AND f.image_normal IS NOT NULL AND COALESCE(c.image_status,'') NOT IN (?,?) AND (" + where + ") ORDER BY c.id, f.face")
    before = rdb.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
    new = [(r[0], r[1], r[2], art_box_name(r[3], r[4]), r[5]) for r in db.execute(q, (*SKIP_STATUS, *params))]
    if dry_run:
        have = set(rdb.execute("SELECT card_id, face FROM rows"))
        rdb.close()
        return sum(1 for r in new if (r[0], r[1]) not in have)
    with rdb:
        rdb.executemany("INSERT OR IGNORE INTO rows (card_id, face, illustration_id, box, url) VALUES (?,?,?,?,?)", new)
    n = rdb.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
    rdb.close()
    return n - before


def _img_file(card_id: str, face: int) -> Path:
    return DATA_DIR / "images" / "normal" / (f"{card_id}.jpg" if face == 0 else f"{card_id}_{face}.jpg")


def _fetch(client: httpx.Client, url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    for i in range(3):
        wait = MIN_INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = client.get(url)
            if r.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                return True
            if r.status_code not in (429, 500, 502, 503, 504):
                return False
        except httpx.HTTPError:
            pass
        time.sleep(0.5 * (i + 1))
    return False


def _shard_done(d: Path, k: int, expected: int) -> bool:
    f = d / f"card_{k:05d}.npy"
    try:
        return f.exists() and len(np.load(f, mmap_mode="r")) == expected and (d / f"art_{k:05d}.npy").exists()
    except Exception:
        return False


def status(d: Path) -> dict:
    if not (d / "rows.db").exists():
        return {"rows": 0, "indexed": 0, "shards": 0}
    rdb = _rows_db(d)
    total = rdb.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
    rdb.close()
    n_sh = -(-total // SHARD)
    done = [k for k in range(n_sh) if _shard_done(d, k, min(SHARD, total - k * SHARD))]
    return {"rows": total, "indexed": sum(min(SHARD, total - k * SHARD) for k in done), "shards": n_sh,
            "done_shards": len(done)}


def build(emb, d: Path, progress=None, should_stop=None, detail=None) -> dict:
    """Build the missing shards. Resumable: it can be interrupted and continued; images stay in data/images/normal.
    `progress(done, total)`: faces finished (a shard counts half for its downloads and half for its vectors); `detail(text)`: what is
    going on now; `should_stop()` is checked while downloading and between batches of vectors."""
    note = detail or (lambda text: None)
    rdb = _rows_db(d)
    total = rdb.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
    failed = 0
    with httpx.Client(headers=scryfall.HEADERS, timeout=20, follow_redirects=True) as client:
        for k in range(-(-total // SHARD)):
            exp = min(SHARD, total - k * SHARD)
            retry = rdb.execute("SELECT COUNT(*) FROM rows WHERE failed=1 AND row>? AND row<=?", (k * SHARD, k * SHARD + exp)).fetchone()[0]
            if _shard_done(d, k, exp) and not retry:  # failed downloads are retried on the next run
                continue
            rows = rdb.execute("SELECT row, card_id, face, box, url FROM rows ORDER BY row LIMIT ? OFFSET ?",
                               (exp, k * SHARD)).fetchall()
            cards, boxes, ok = [], [], []
            for i, (_, cid, face, box, url) in enumerate(rows):
                img = None
                if _fetch(client, url, _img_file(cid, face)):
                    img = cv2.imread(str(_img_file(cid, face)))
                if img is None:
                    ok.append(False)
                    failed += 1
                    continue
                ok.append(True)
                cards.append(normalize_card(img))
                boxes.append(box)
                if i % 50 == 0:
                    if progress:
                        progress(k * SHARD + i // 2, total)
                    note(f"downloading images {i:,}/{exp:,}")
                    if should_stop and should_stop():  # the unfinished shard is dropped; its images stay cached for the next run
                        rdb.close()
                        return {**status(d), "failed_downloads": failed, "stopped": True}

            def vectors(pass_no):  # two passes (card, then art): the second half of the shard's work
                def tick(done, tot):
                    frac = (pass_no + done / tot) / 2
                    if progress:
                        progress(k * SHARD + exp // 2 + int(frac * (exp - exp // 2)), total)
                    note(f"computing vectors {int(frac * 100)}% of this block (slow on a CPU: minutes per block)")
                    return bool(should_stop and should_stop())
                return tick
            try:
                cv, av = emb.cards(cards, progress=vectors(0)), emb.arts(cards, boxes, progress=vectors(1))
            except Stopped:  # same as above: the block is dropped, the images stay
                rdb.close()
                return {**status(d), "failed_downloads": failed, "stopped": True}
            cmat = np.zeros((exp, cv.shape[1]), np.float16)
            amat = np.zeros_like(cmat)
            idx = np.flatnonzero(ok)
            cmat[idx], amat[idx] = cv, av
            with rdb:
                rdb.executemany("UPDATE rows SET failed=? WHERE row=?", [(int(not o), r[0]) for o, r in zip(ok, rows)])
            np.save(d / f"art_{k:05d}.npy", amat)
            np.save(d / f"card_{k:05d}.npy", cmat)  # 'card' is written last: it marks the shard as complete
            if progress:
                progress((k + 1) * SHARD if (k + 1) * SHARD < total else total, total)
    rdb.close()
    (d / "manifest.json").write_text(json.dumps({"prep": prep_hash(), "model": emb.model_id, "dim": emb.dim,
                                                 **status(d)}), encoding="utf-8")
    return {**status(d), "failed_downloads": failed}


class Index:
    """In-memory matrices (GPU fp16 when CUDA is available, otherwise fp32) + rows. Only complete shards are included."""

    def __init__(self, d: Path):
        rdb = _rows_db(d)
        total = rdb.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
        cards, arts, self.rows = [], [], []
        for k in range(-(-total // SHARD)):
            exp = min(SHARD, total - k * SHARD)
            if not _shard_done(d, k, exp):
                continue
            cards.append(np.load(d / f"card_{k:05d}.npy"))
            arts.append(np.load(d / f"art_{k:05d}.npy"))
            self.rows += [dict(zip(("card_id", "face", "illustration_id", "box"), r)) for r in rdb.execute(
                "SELECT card_id, face, illustration_id, box FROM rows ORDER BY row LIMIT ? OFFSET ?", (exp, k * SHARD))]
        rdb.close()
        self._t = None
        if not cards:
            self.card = self.art = np.zeros((0, 1), np.float32)
            return
        self.card, self.art = np.concatenate(cards), np.concatenate(arts)
        try:
            import torch
            if torch.cuda.is_available():
                self._t = (torch.from_numpy(self.card).cuda(), torch.from_numpy(self.art).cuda())
        except ImportError:
            pass
        if self._t is None:
            self.card, self.art = self.card.astype(np.float32), self.art.astype(np.float32)

    def __len__(self):
        return len(self.rows)

    def scores(self, card_vec: np.ndarray, art_vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(art cosine [max over the candidate boxes], card cosine) for every row."""
        if self._t is not None:
            import torch
            c, a = self._t
            q = torch.from_numpy(np.vstack([art_vecs, card_vec[None]]).astype(np.float16)).cuda()
            art = (a @ q[:-1].T).max(1).values.float().cpu().numpy()
            return art, (c @ q[-1]).float().cpu().numpy()
        return (self.art @ art_vecs.T.astype(np.float32)).max(1), self.card @ card_vec.astype(np.float32)


def load(emb, root: Path | None = None) -> Index | None:
    d = index_dir(emb, root)
    if not (d / "rows.db").exists():
        return None
    ix = Index(d)
    return ix if len(ix) else None
