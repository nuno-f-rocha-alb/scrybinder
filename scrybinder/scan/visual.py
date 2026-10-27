"""Glue between the visual index and identification: the art picks the illustrations, card + OCR rank the printings."""
import json
import sys
import threading

import numpy as np

from ..db import DATA_DIR
from . import index as ixmod
from .embed import Embedder, normalize_card

# weights (cosine ~0.3–1.0 for the visual part; OCR enters as points). Tunable in data/scan_weights.json.
WEIGHTS = {"art": 1.0, "card": 1.0, "name": 0.15, "pts": 0.05, "owned": 0.05, "memorabilia": -0.03, "serialized": -0.1, "stamp": 0.5, "rescue": 0.5, "rescue_art": 0.75, "rescue_name": 90, "shortlist": 8,
           "hi_margin": 0.06, "hi_art": 0.70, "mid_margin": 0.02}


def weights() -> dict:
    p = DATA_DIR / "scan_weights.json"
    if p.exists():
        try:
            return {**WEIGHTS, **json.loads(p.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            pass
    return dict(WEIGHTS)


class Visual:
    """Embedder + index, loaded on first use. `None` from `Visual.try_open()` = OCR-only mode."""

    NO_ART_LAYOUTS = ("split", "aftermath", "flip")  # there is no art box: the vectors are generic and attract everything

    def __init__(self, emb, ix, db=None):
        self.emb, self.ix = emb, ix
        self._by_ill: dict | None = None
        self._lock = threading.Lock()
        bad = {r[0] for r in db.execute(f"SELECT id FROM cards WHERE layout IN ({','.join('?' * len(self.NO_ART_LAYOUTS))})",
                                        self.NO_ART_LAYOUTS)} if db is not None else set()
        self._no_art = np.array([r["card_id"] in bad for r in ix.rows], dtype=bool)
        self._db = db
        self._locks: dict[frozenset, np.ndarray] = {}  # sets -> which index rows belong to them

    @classmethod
    def try_open(cls, emb=None, db=None):
        try:
            emb = emb or Embedder()
            import torch  # noqa: F401  (extra 'vision' em falta → degradado)
            ix = ixmod.load(emb)
        except ImportError as e:
            print(f"Visual index unavailable (missing dependency): {e!r}", file=sys.stderr, flush=True)
            return None
        return cls(emb, ix, db) if ix else None

    STAMP_ZONE = (0.74, 0.43, 0.96, 0.585)  # promo stamp (prerelease/promo pack), bottom-right of the art

    def stamp_scores(self, card: np.ndarray, ids: list[str]) -> dict[str, float]:
        """Similarity of the stamp zone between the capture (already oriented) and each cached printing: separates promo from regular."""
        import cv2
        z = self.STAMP_ZONE

        def crop(c):
            h, w = c.shape[:2]
            return c[int(z[1] * h):int(z[3] * h), int(z[0] * w):int(z[2] * w)]
        refs = {}
        for i in ids:
            im = cv2.imread(str(DATA_DIR / "images" / "normal" / f"{i}.jpg"))
            if im is not None:
                refs[i] = crop(normalize_card(im))
        if not refs:
            return {}
        with self._lock:
            v = self.emb.embed_raw([crop(normalize_card(card))] + list(refs.values()), (126, 126))
        return dict(zip(refs, (v[1:] @ v[0]).tolist()))

    def warm(self):
        """Load the model now (the first query takes ~20 s to initialise CUDA and weights)."""
        with self._lock:
            self.emb.query(np.zeros((880, 630, 3), np.uint8))

    def by_ill(self) -> dict:
        if self._by_ill is None:
            m: dict[str, list[int]] = {}
            for i, r in enumerate(self.ix.rows):
                m.setdefault(r["illustration_id"] or f"row{i}", []).append(i)  # no illustration id: every row is its own
            self._by_ill = m
        return self._by_ill

    def _in_sets(self, sets: frozenset) -> np.ndarray:
        if sets not in self._locks:
            ids = {r[0] for r in self._db.execute(f"SELECT id FROM cards WHERE set_code IN ({','.join('?' * len(sets))})", tuple(sets))}
            self._locks[sets] = np.array([r["card_id"] in ids for r in self.ix.rows], dtype=bool)
        return self._locks[sets]

    def query(self, card: np.ndarray, w: dict, sets: frozenset = frozenset()):
        """Visual scores per card (scryfall_id) for the given orientation: {id: (art, card)}, best art. `sets` limits it to those sets."""
        with self._lock:
            cv, av = self.emb.query(normalize_card(card))
            art, cardsc = self.ix.scores(cv, av)
        art = np.where(self._no_art, -1.0, art)
        if sets:
            art = np.where(self._in_sets(sets), art, -1.0)
        order = np.argsort(-art)
        shortlist: list = []
        for i in order[:400]:
            if art[i] <= -1.0:  # masked out (no art box, or outside the chosen sets): not a candidate
                break
            ill = self.ix.rows[i]["illustration_id"] or f"row{i}"
            if ill not in shortlist:
                shortlist.append(ill)
            if len(shortlist) >= int(w["shortlist"]):
                break
        out: dict[str, list[float]] = {}
        for ill in shortlist:
            for i in self.by_ill().get(ill, ()):
                cid = self.ix.rows[i]["card_id"]
                a, c = out.setdefault(cid, [-1.0, -1.0])
                out[cid] = [max(a, float(art[i])), max(c, float(cardsc[i]))]
        top = float(art[order[0]]) if len(order) else 0.0
        return {k: tuple(v) for k, v in out.items()}, top

    def best_orientation(self, card: np.ndarray, w: dict, try_rotated: bool, sets: frozenset = frozenset()):
        """Returns (scores, top_art, cv2 rotation or None). Only tries 180° when the name reading did not settle it.
        (Detection already forces the card upright: 90° makes no sense.)"""
        import cv2
        best = (*self.query(card, w, sets), None)
        if try_rotated:
            res = self.query(cv2.rotate(card, cv2.ROTATE_180), w, sets)
            if res[1] > best[1]:
                best = (*res, cv2.ROTATE_180)
        return best
