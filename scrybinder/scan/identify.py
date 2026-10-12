"""OCR (Tesseract) of the rectified card + printing identification. With the visual index the artwork picks the
illustrations and card + OCR rank the printings; without it, it falls back to OCR-only matching."""
import os
import re
import sys
import threading
import traceback
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from rapidfuzz import fuzz, process, utils

from . import visual
from .vision import CARD_H, CARD_W

_DEFAULT_TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_BUNDLED = Path(getattr(sys, "_MEIPASS", "/nonexistent")) / "tesseract" / "tesseract.exe"  # Windows release: Tesseract ships inside the app
if _BUNDLED.exists():
    os.environ.setdefault("TESSDATA_PREFIX", str(_BUNDLED.parent / "tessdata"))
pytesseract.pytesseract.tesseract_cmd = os.environ.get("SCRYBINDER_TESSERACT") or (
    str(_BUNDLED) if _BUNDLED.exists() else _DEFAULT_TESS if Path(_DEFAULT_TESS).exists() else "tesseract")

NAME_CUTOFF = 72  # minimum similarity (0-100) between the OCR name and a bulk name
# relative zones (x0, y0, x1, y1) of the 630x880 card, modern frame; ponytail: special frames (flip, saga...) get an
# approximate name zone and rely on manual selection
NAME_ZONES = [(0.05, 0.052, 0.74, 0.118), (0.05, 0.040, 0.74, 0.135), (0.10, 0.125, 0.78, 0.215)]  # 3rd: showcase/borderless; the name text sits between ~7 % and ~11 % of the height
BOTTOM_ZONE = (0.03, 0.912, 0.34, 0.968)  # 2 lines: "103/342 R" / "C15 • EN"; excludes the artist and copyright


def _crop(img, zone):
    x0, y0, x1, y1 = zone
    return img[int(y0 * CARD_H):int(y1 * CARD_H), int(x0 * CARD_W):int(x1 * CARD_W)]


def _ocr(gray: np.ndarray, psm: int, scale: int, invert_try=True) -> tuple[str, float]:
    """Best text across polarities. Returns (text, mean confidence 0-100)."""
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    variants = [cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
    if invert_try:
        variants.append(255 - variants[0])
    best = ("", -1.0)
    for v in variants:
        v = cv2.copyMakeBorder(v, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255 if v.mean() > 127 else 0)
        d = pytesseract.image_to_data(v, lang="eng", config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
        words = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) >= 0]
        if not words:
            continue
        text = " ".join(t for t, _ in words)
        conf = sum(c for _, c in words) / len(words)
        if conf > best[1]:
            best = (text, conf)
    return best


def name_reads(card: np.ndarray):
    """Name readings with several zones/pre-processings (most to least likely); the caller stops at the first good match."""
    for zone in NAME_ZONES:
        gray = cv2.cvtColor(_crop(card, zone), cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        yield _ocr(gray, psm=7, scale=3)  # Otsu, both polarities
        for v in (big, 255 - big):  # plain grey: Tesseract binarises better than Otsu on gradient title bars
            d = pytesseract.image_to_data(cv2.copyMakeBorder(v, 10, 10, 10, 10, cv2.BORDER_REPLICATE), lang="eng",
                                          config="--psm 7", output_type=pytesseract.Output.DICT)
            w = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) >= 0]
            if w:
                yield " ".join(t for t, _ in w), sum(c for _, c in w) / len(w)


_SLASH = re.compile(r"(?<!\d)(\d{1,4})\s*/\s*\d{1,4}(?!\d)")
_DIGITISH = re.compile(r"^[MRUCSLTP]?([0-9oOsSlI!]{3,4})$")  # the rarity letter can be glued to the number: "M0317"
_CONFUSE = str.maketrans("oOsSlI!", "0055111")


def parse_bottom(text: str) -> dict:
    """Possible numbers (by reliability) and set-code candidate tokens from the bottom-strip text."""
    numbers = [m.group(1).lstrip("0") or "0" for m in _SLASH.finditer(text)]
    for tok in re.findall(r"[^\s|]+", text):  # new frame: "R 0155" / "U 0261" (no /total)
        dm = _DIGITISH.match(tok)
        if dm and sum(c.isdigit() for c in dm.group(1)) >= 2:
            n = dm.group(1).translate(_CONFUSE).lstrip("0") or "0"
            if n not in numbers:
                numbers.append(n)
    tokens = [t for t in re.findall(r"[A-Z0-9]{3,5}", text.upper()) if t != "EN" and not t.isdigit()]
    return {"numbers": numbers, "tokens": tokens}


def read_bottom(card: np.ndarray) -> dict:
    gray = cv2.cvtColor(_crop(card, BOTTOM_ZONE), cv2.COLOR_BGR2GRAY)
    texts = []
    for sc in (3, 5):  # plain grey, two scales: Otsu ruins letters this small
        big = cv2.resize(gray, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        texts.append(pytesseract.image_to_string(cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_REPLICATE),
                                                 lang="eng", config="--psm 6"))
    text = "\n".join(texts)
    return {**parse_bottom(text), "text": text.strip()}


SPARK_ZONE = (0.0, 0.930, 0.072, 0.985)  # bottom-left corner, before the number (position varies with the frame)


def has_spark(card: np.ndarray) -> bool:
    """The spark symbol (The List / PLST card): a bright, tall, isolated shape on the dark margin, before the number.
    Isolated = does not touch the zone edges (the light background outside the rounded corner and the digits are excluded)."""
    z = cv2.cvtColor(_crop(card, SPARK_ZONE), cv2.COLOR_BGR2GRAY)
    if z.size == 0:
        return False
    med = float(np.median(z))
    if med > 110:  # light margin (white border): no contrast to decide
        return False
    mask = (z > max(85.0, med + 40)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(mask)
    zh, zw = z.shape
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        # does not touch the left/top/bottom edge (light background outside the rounded corner); the spark is ~13-14 × 14-17 px
        # on a 630x880 card and digits are ≤ 10 px wide. It may touch the right edge of the zone (start of the number).
        if x > 0 and y > 0 and y + h < zh and h >= 13 and w >= 11 and 0.9 <= h / w <= 2.0:
            return True
    return False


def _clean(text: str) -> str:
    """Strip OCR junk at both ends (icons read as 'X', 'f', '|'): 1-character or letterless tokens."""
    toks = text.split()
    while toks and (len(toks[0]) < 2 or not any(c.isalpha() for c in toks[0])):
        toks.pop(0)
    while toks and (len(toks[-1]) < 2 or not any(c.isalpha() for c in toks[-1])):
        toks.pop()
    return " ".join(toks)


def _num(s) -> str | None:
    d = re.sub(r"\D", "", str(s or ""))
    return d.lstrip("0") or ("0" if d else None)


class Identifier:
    def __init__(self, db, use_visual=True):
        self.db = db
        self._names = None
        self._use_visual = use_visual
        self._vis = None
        self._vis_tried = False
        self._vis_lock = threading.Lock()
        self._sets = None

    def reset_vis(self):
        """Forget the cached index decision (e.g. after building it from Settings) so the next scan reopens it."""
        with self._vis_lock:
            self._vis, self._vis_tried = None, False

    def vis(self):
        """The visual index if it exists and the `vision` extra is installed; None = OCR-only mode."""
        with self._vis_lock:  # concurrent threads wait for the first open instead of falling back to OCR-only
            if self._use_visual and not self._vis_tried:
                try:
                    self._vis = visual.Visual.try_open(db=self.db)
                    if self._vis:
                        self._vis.warm()
                except Exception as e:  # noqa: BLE001 — any model/GPU failure must not stop OCR scanning
                    traceback.print_exc()  # includes the original cause (e.g. a missing module in the packaged app)
                    print(f"Visual index unavailable, OCR only: {e!r}", file=sys.stderr, flush=True)
                    self._vis = None
                self._vis_tried = True
        return self._vis

    def by_ids(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            out += [dict(r) for r in self.db.execute(
                "SELECT id, name, set_code, set_name, collector_number, released_at, rarity, finishes, eur, eur_foil,"
                f" eur_etched, promo_types FROM cards WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
        return out

    def _load(self):
        rows = self.db.execute("SELECT DISTINCT name FROM cards WHERE digital=0").fetchall()
        alias: dict[str, list[str]] = {}
        for (n,) in rows:
            if len(utils.default_process(n)) < 3:  # '______' (Unknown Event) etc.: empty after normalising, would match junk
                continue
            alias.setdefault(n, []).append(n)
            if " // " in n:  # double-faced: the physical card shows only the 1st face (the 2nd is on the back)
                for face in n.split(" // "):
                    alias.setdefault(face, []).append(n)
        self._names = alias
        self._choices = list(alias)

    def match_names(self, text: str, limit=3) -> list[tuple[str, float]]:
        if self._names is None:
            self._load()
        q = _clean(text)
        if len(utils.default_process(q)) < 3:
            return []
        hits = process.extract(q, self._choices, scorer=fuzz.ratio, processor=utils.default_process,
                               limit=limit, score_cutoff=NAME_CUTOFF)
        return [(h[0], h[1]) for h in hits]

    def prints(self, names: list[str]) -> list[dict]:
        out: list[dict] = []
        for n in names:
            for full in dict.fromkeys(self._names[n]):
                out += [dict(r) for r in self.db.execute(
                    "SELECT id, name, set_code, set_name, collector_number, released_at, rarity, finishes, eur, eur_foil,"
                    " eur_etched, promo_types FROM cards WHERE UPPER(name)=UPPER(?) AND digital=0 ORDER BY released_at DESC", (full,))]
        return out

    @staticmethod
    def _score(c: dict, bottom: dict, promo_parents: set | None = None) -> int:
        """Points for agreeing with the bottom strip. Exact beats approximate: 'KLD' ≠ 'PKLD', '192' ≠ '192s'.
        Number: 3 exact, 2 digits only, 1 if it is a secondary reading. Set: 3 identical token, 1 similar (1 OCR error).
        The List / compilations store the number as 'MM2-151' = set printed on the card + printed number."""
        raw = str(c["collector_number"] or "").lower().lstrip("0")
        code = c["set_code"].upper()
        m = re.match(r"^([a-z0-9]{2,5})-(\d+)[a-z★]*$", raw)
        if m:
            code, raw = m.group(1).upper(), m.group(2).lstrip("0")
        if promo_parents is not None:  # with visual: promos ('psos', '20p') print the parent set and the number without suffix; OCR cannot tell them apart
            if code.lower().startswith("p") and code[1:].lower() in promo_parents:
                code = code[1:]
            raw = re.sub(r"[a-z★]+$", "", raw) or raw
        pts, nums = 0, bottom["numbers"]
        if c["set_code"] == "plst" and "spark" in bottom:  # The List: the spark decides between it and the original printing
            pts += 3 if bottom["spark"] else -1  # absence is weak evidence: the spark can be missed in a bad photo
        n = _num(raw)
        if n and nums:
            pts += 3 if nums[0] == raw else 2 if nums[0] == n else 1 if n in nums else 0
        if code in bottom["tokens"]:
            pts += 3
        elif bottom["tokens"] and max(fuzz.ratio(t, code) for t in bottom["tokens"]) >= 66:
            pts += 1
        return pts

    def identify(self, card: np.ndarray) -> dict:
        """card = rectified 630x880 image. Also tries 180° if the name reads weakly."""
        if self._names is None:
            self._load()
        best = None
        for rotated in (False, True):
            img = cv2.rotate(card, cv2.ROTATE_180) if rotated else card
            for text, conf in name_reads(img):
                names = self.match_names(text)
                score = names[0][1] if names else 0
                if best is None or score > best[0]:
                    best = (score, img, text, conf, names, rotated)
                if score >= 92:
                    break
            if best[0] >= 92:
                break
        score, img, text, conf, names, rotated = best
        vis = self.vis()
        if vis is None:
            return self._ocr_only(img, text, conf, score, names, rotated)
        return self._with_visual(vis, img, text, conf, score, names, rotated)

    def _set_codes(self) -> set:
        if self._sets is None:
            self._sets = {r[0] for r in self.db.execute("SELECT code FROM sets")}
        return self._sets

    def _priors(self) -> tuple[set, set]:
        """Tie-break between near-identical printings: ones you already own gain a little; memorabilia/oversized (replicas) lose."""
        owned = {r[0] for r in self.db.execute("SELECT DISTINCT scryfall_id FROM collection")}
        memo = {r[0] for r in self.db.execute("SELECT code FROM sets WHERE set_type='memorabilia'")}
        return owned, memo

    def _name_score(self, c: dict, names) -> float:
        return next((s for n, s in names if n == c["name"] or c["name"].startswith(n + " //")
                     or c["name"].endswith("// " + n)), 0)

    def _ocr_only(self, img, text, conf, score, names, rotated) -> dict:
        bottom = read_bottom(img) if names else {"numbers": [], "tokens": [], "text": ""}
        if names:
            bottom["spark"] = has_spark(img)
        cands = self.prints([n for n, _ in names[:2]]) if names else []
        for c in cands:
            c["score"] = self._score(c, bottom)
            c["name_score"] = self._name_score(c, names)
        # final order: best name (in bands of 5) → more set/number points → most recent first
        cands.sort(key=lambda c: (round(c["name_score"] / 5), c["score"], c["released_at"] or ""), reverse=True)
        top = cands[0]["score"] if cands else 0
        unique = sum(1 for c in cands if c["score"] == top) == 1
        confidence = "none" if not cands else "high" if top >= 4 and unique and score >= 85 else "medium" if top >= 2 and unique else "low"
        return self._result(text, conf, score, bottom, cands, top, rotated, confidence)

    @staticmethod
    def _result(text, conf, score, bottom, cands, top, rotated, confidence, **extra) -> dict:
        return {"ocr": {"name": text, "name_conf": round(conf, 1), "name_match": round(score, 1),
                        "number": bottom["numbers"][0] if bottom["numbers"] else None,
                        "set": cands[0]["set_code"] if cands and top >= 2 else None,
                        "bottom_text": bottom["text"], "rotated": rotated, "spark": bottom.get("spark", False)},
                "candidates": cands[:40], "confidence": confidence, **extra}

    def _with_visual(self, vis, img, text, conf, score, names, rotated) -> dict:
        w = visual.weights()
        priors = self._priors()
        scores, top_art, rot = vis.best_orientation(img, w, try_rotated=score < 85)
        if rot is not None:
            img = cv2.rotate(img, rot)
            rotated = rotated != (rot == cv2.ROTATE_180)  # the 'rotated' field still means 180°
        bottom = read_bottom(img)
        bottom["spark"] = has_spark(img)
        cands = self.prints([n for n, _ in names[:2]]) if names else []
        have = {c["id"] for c in cands}
        cands += self.by_ids([i for i in scores if i not in have])
        # OCR-only candidate (outside the illustrations the artwork finds plausible): gets the worst visual score of the shortlist
        # so a misread name cannot beat the artwork; outside the index (pilot) it depends on OCR
        neutral = (min(a for a, _ in scores.values()), min(c for _, c in scores.values())) if scores else (0.0, 0.0)
        for c in cands:
            c["score"] = self._score(c, bottom, self._set_codes())
            c["name_score"] = self._name_score(c, names)
            c["art"], c["card"] = scores.get(c["id"], neutral)
            c["in_index"] = c["id"] in scores
            c["prior"] = (w["owned"] * (c["id"] in priors[0]) + w["memorabilia"] * (c["set_code"] in priors[1])
                          + w["serialized"] * ("serialized" in (c.get("promo_types") or "")))  # serialized (x/500): extremely rare, same artwork
            c["total"] = (w["art"] * c["art"] + w["card"] * c["card"] + w["name"] * c["name_score"] / 100
                          + w["pts"] * c["score"] + c["prior"])
            if top_art < w["rescue_art"] and c["name_score"] >= w["rescue_name"]:  # foil/glare: the artwork is useless, the name read is not
                c["total"] += w["rescue"]
        cands.sort(key=lambda c: (c["total"], c["released_at"] or ""), reverse=True)
        # fine tie-break by stamp (promo vs regular, prerelease vs promo pack): only among nearly tied candidates and
        # only if one is a promo (without a stamp in play the zone is noise)
        parents = self._set_codes()
        top6 = [c for c in cands[:6] if cands[0]["total"] - c["total"] < 0.1]
        st = {}
        if any(c["set_code"].startswith("p") and c["set_code"][1:] in parents for c in top6):
            st = vis.stamp_scores(img, [c["id"] for c in top6])
        if len(st) > 1:
            mean = sum(st.values()) / len(st)
            for c in top6:
                c["stamp"] = st[c["id"]] - mean if c["id"] in st else 0.0
                c["total"] += w["stamp"] * c["stamp"]
            cands.sort(key=lambda c: (c["total"], c["released_at"] or ""), reverse=True)
        margin = cands[0]["total"] - cands[1]["total"] if len(cands) > 1 else 1.0
        confidence = ("none" if not cands else "high" if margin >= w["hi_margin"] and top_art >= w["hi_art"]
                      else "medium" if margin >= w["mid_margin"] else "low")
        top = max((c["score"] for c in cands[:1]), default=0)
        return self._result(text, conf, score, bottom, cands, top, rotated, confidence,
                            visual={"top_art": round(top_art, 3), "margin": round(margin, 3)})
