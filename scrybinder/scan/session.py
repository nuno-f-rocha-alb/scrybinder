"""Scan session: pending queue, sources (photos / folder / webcam), the temporary read list, confirmation and logging."""
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .. import collection
from ..db import DATA_DIR
from .identify import Identifier
from .vision import Stability, card_from_photo, card_signature, find_card, find_cards, inner_card, warp_card

log = logging.getLogger(__name__)

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_SIDE_PAGE = 4500  # a page holds up to 9 cards: more pixels are needed for each one
SAME_CARD_NOTICE = "Same card as the previous one: not counted. If it is a foil, press N (next card is foil) before showing it."
MAX_SIDE = 3000  # larger photos are downscaled: bounds memory and OCR time


def decode(data: bytes, max_side: int = MAX_SIDE) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    s = max_side / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


def identify_image(ident: Identifier, img: np.ndarray, warped: bool = False):
    """Photo (or already rectified card) → (630x880 card, card detected?, identification result)."""
    card, detected = (img, True) if warped else card_from_photo(img)
    res = ident.identify(card)
    if res["ocr"]["name_match"] < 85:  # weak reading: the card may be in a toploader; try the inner quadrilateral
        alt = inner_card(card)
        if alt is not None:
            res2 = ident.identify(alt)
            if res2["ocr"]["name_match"] > res["ocr"]["name_match"]:
                card, res = alt, res2
    return card, detected, res


def _topk(item: dict) -> str:
    """Top-5 with each candidate's signals (data for re-tuning weights with scrybinder-eval)."""
    keys = ("id", "score", "name_score", "art", "card", "prior", "total")
    return json.dumps({"confidence": item.get("confidence"), "visual": item.get("visual"),
                       "top": [{k: c.get(k) for k in keys} for c in item.get("candidates", [])[:5]]})


class Scanner:
    def __init__(self, db, captures_dir: Path | None = None, hold=0.4, debug_dir: Path | None = None):
        self.db = db
        self.ident = Identifier(db)
        self.dir = captures_dir or DATA_DIR / "captures"
        self.debug_dir = debug_dir or self.dir.parent / "debug"  # whole camera frames with the detected outline (see save_debug)
        self.hold = hold
        self.pending: list[dict] = []
        self.beep = 0                      # increments on every capture: the UI plays a sound
        self.message = ""
        self.notice = ""                   # a passing remark for the UI (e.g. a read ignored as the card still on the stand); cleared by the next capture
        self.split_next = False            # the next capture opens a new entry (e.g. the foil among identical regular cards)
        self.page_mode = False             # photos are binder pages (up to 3x3 cards) instead of one card each
        self.list_mode = False             # True: reads go to the temporary list (reads) and only enter the collection in commit_reads()
        self._cards: dict[str, dict | None] = {}
        self.reads: list[dict] = self._load_reads()
        self.source: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._preview: bytes | None = None
        self._frame: np.ndarray | None = None  # the latest camera frame and the card outline found in it
        self._quad: np.ndarray | None = None
        self._seen: set[str] = set()
        self._next_id = int(db.execute("SELECT COALESCE(MAX(id),0) FROM scan_log").fetchone()[0]) + 1
        threading.Thread(target=self.ident.vis, daemon=True).start()  # warm up the index/model before the first card

    # --- temporary read list (list mode) ---
    def _load_reads(self) -> list[dict]:
        try:
            return json.loads((self.dir / "reads.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save_reads(self):  # called with the lock held; the list survives an unexpected app exit
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "reads.json.part"
        tmp.write_text(json.dumps(self.reads, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "reads.json")

    def card_info(self, cid: str) -> dict | None:
        if cid in self._cards:  # the state is polled every 0.7 s: without this it would be N queries per request
            return self._cards[cid]
        r = self.db.execute("SELECT id, name, set_code, set_name, collector_number, released_at, finishes, eur, eur_foil,"
                            " eur_etched, cardmarket_id FROM cards WHERE id=?", (cid,)).fetchone()
        self._cards[cid] = dict(r) if r else None
        return self._cards[cid]

    @staticmethod
    def _finish_for(finishes, want: str) -> str:
        fs = json.loads(finishes or "[]") or ["nonfoil"]
        return want if want in fs else fs[0]

    def _add_read(self, item: dict, live: bool = False) -> dict:
        cands, pid = item["candidates"], item["predicted_id"]
        with self._lock:  # check and append in the same block: simultaneous captures (webcam) do not duplicate the entry
            foil = self.split_next
            self.split_next = False
            fin = self._finish_for(cands[0].get("finishes") if cands else None, "foil" if foil else "nonfoil")
            last = self.reads[-1] if self.reads else None  # only the card right before: another card in between starts a new entry
            same = last if last and not foil and (pid or live) and last["scryfall_id"] == pid and last["finish"] == fin else None  # live: an unreadable card on the stand repeats too
            if same and live:  # the camera read the card that is still on the stand: not a new copy (the entry has - / +)
                self.notice = SAME_CARD_NOTICE
                return same
            self.notice = ""
            self.beep += 1
            if same:
                same["qty"] += 1
            else:
                self.reads.append({"id": item["id"], "label": item["label"], "confidence": item["confidence"], "ocr": item["ocr"],
                                   "visual": item.get("visual"), "predicted_id": pid, "scryfall_id": pid, "candidates": cands[:12],
                                   "finish": fin, "qty": 1, "condition": "NM", "language": "en"})
            self._save_reads()
            return same or self.reads[-1]

    def read_edit(self, rid: int, **ch) -> dict:
        with self._lock:
            r = next((x for x in self.reads if x["id"] == rid), None)
            if r is None:
                raise KeyError(rid)
            if "scryfall_id" in ch:
                info = self.card_info(ch["scryfall_id"])
                if info is None:
                    raise ValueError("unknown printing")
                r["scryfall_id"] = info["id"]
                r["finish"] = self._finish_for(info["finishes"], r["finish"])
                if all(c["id"] != info["id"] for c in r["candidates"]):
                    r["candidates"].insert(0, info)
            if ch.get("finish") in ("nonfoil", "foil", "etched"):
                r["finish"] = ch["finish"]
            if "qty" in ch:
                r["qty"] = max(1, int(ch["qty"]))
            if ch.get("condition") in ("NM", "LP", "MP", "HP", "DMG"):
                r["condition"] = ch["condition"]
            if ch.get("language"):
                r["language"] = str(ch["language"])[:6]
            self._save_reads()
            return r

    def read_delete(self, rid: int):
        with self._lock:
            self.reads = [x for x in self.reads if x["id"] != rid]
            self._save_reads()
        (self.dir / f"{rid}.jpg").unlink(missing_ok=True)

    def commit_reads(self, location: str = "") -> dict:
        # add the list to the collection (one row per entry) and log each one in scan_log; failing midway keeps the rest
        added, rows = 0, 0
        with self._lock:
            todo = list(self.reads)
        for r in todo:
            done = r["qty"]
            try:
                collection.add(self.db, scryfall_id=r["scryfall_id"], finish=r["finish"], quantity=done,
                               condition=r["condition"], language=r["language"], location=location)
            except Exception as e:  # noqa: BLE001 — what failed stays in the list; return the reason
                return {"added": added, "rows": rows, "error": f"{r['id']}: {e}"}
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO scan_log (id, capture_path, ocr_json, predicted_id, final_id, corrected, location, topk_json)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (r["id"], str(self.dir / f"{r['id']}.jpg"), json.dumps(r["ocr"], ensure_ascii=False), r["predicted_id"],
                     r["scryfall_id"], int(r["predicted_id"] != r["scryfall_id"]), location, _topk(r)))
            added += done
            rows += 1
            with self._lock:  # an identical capture that arrived during the commit adds to the same entry: the surplus stays
                if r["qty"] > done:
                    r["qty"] -= done
                else:
                    self.reads = [x for x in self.reads if x["id"] != r["id"]]
                self._save_reads()
        return {"added": added, "rows": rows}

    # --- processing one image (same for photos, folder and webcam) ---
    def process(self, img: np.ndarray, label: str = "", warped: bool = False, live: bool = False) -> dict:
        """`live`: the capture comes from the camera, where a card read again right after itself is the same card still on the stand."""
        card, detected, res = identify_image(self.ident, img, warped)
        predicted = res["candidates"][0]["id"] if res["candidates"] else None
        with self._lock:
            sid, self._next_id = self._next_id, self._next_id + 1
        self.dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(self.dir / f"{sid}.jpg"), card, [cv2.IMWRITE_JPEG_QUALITY, 92])
        item = {"id": sid, "label": label, "detected": detected, **res, "predicted_id": predicted, "qty": 1}
        if self.list_mode:
            entry = self._add_read(item, live)
            if entry["id"] != sid:  # merged into an existing entry: the new capture is not needed
                (self.dir / f"{sid}.jpg").unlink(missing_ok=True)
            return entry
        with self._lock:  # check and append in the same block: simultaneous captures (webcam) do not duplicate the entry
            last = self.pending[-1] if self.pending else None  # only the card right before: another card in between starts a new entry
            same = last if last and not self.split_next and (predicted or live) and last["predicted_id"] == predicted else None
            self.split_next = False
            if same and live:  # still the card on the stand, not a new copy
                self.notice = SAME_CARD_NOTICE
                (self.dir / f"{sid}.jpg").unlink(missing_ok=True)
                return same
            self.notice = ""
            self.beep += 1
            if same:  # the same printing as the card right before: only the quantity goes up (a foil is opened with split_next)
                same["qty"] += 1
            else:
                self.pending.append(item)
        if same:
            (self.dir / f"{sid}.jpg").unlink(missing_ok=True)
            return same
        return item

    def process_page(self, img: np.ndarray, label: str = "") -> dict:
        """A photo of a binder page: every card found goes through the normal one-card path (list mode: one entry each)."""
        quads = find_cards(img)
        entries = [self.process(warp_card(img, q), f"{label} #{i}" if label else f"#{i}", warped=True) for i, q in enumerate(quads, 1)]
        self.message = f"{len(entries)} cards detected" if entries else "No cards detected"
        return {"detected": len(entries), "entries": entries}

    def state(self) -> dict:
        with self._lock:
            return {"running": bool(self._thread and self._thread.is_alive()), "source": self.source,
                    "message": self.message, "notice": self.notice, "beep": self.beep, "split_next": self.split_next, "list_mode": self.list_mode, "page_mode": self.page_mode,
                    "pending": list(self.pending),
                    "reads": [{k: v for k, v in r.items() if k != "candidates"} | {"card": self.card_info(r["scryfall_id"])}
                              for r in self.reads]}

    # --- confirmation ---
    def _pop(self, pid: int) -> dict:
        with self._lock:
            for i, p in enumerate(self.pending):
                if p["id"] == pid:
                    return self.pending.pop(i)
        raise KeyError(pid)

    def confirm(self, pid: int, scryfall_id: str, location: str = "", **fields) -> int:
        """Write to the collection and log (capture → chosen printing) in scan_log."""
        item = self._pop(pid)
        try:
            row = collection.add(self.db, scryfall_id=scryfall_id, location=location, **fields)
        except Exception:
            with self._lock:
                self.pending.insert(0, item)  # do not lose the pending item if saving fails
            raise
        with self.db:
            self.db.execute(
                "INSERT INTO scan_log (id, capture_path, ocr_json, predicted_id, final_id, corrected, location, topk_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (pid, str(self.dir / f"{pid}.jpg"), json.dumps(item["ocr"], ensure_ascii=False), item["predicted_id"],
                 scryfall_id, int(item["predicted_id"] != scryfall_id), location, _topk(item)))
        return row

    def discard(self, pid: int):
        self._pop(pid)
        (self.dir / f"{pid}.jpg").unlink(missing_ok=True)

    # --- continuous sources ---
    def start(self, kind: str, target: str = "0"):
        self.stop()
        if kind == "folder":
            folder = Path(target)
            if not folder.is_dir():
                raise ValueError("folder does not exist")
            self._seen = {p.name for p in folder.iterdir()}  # only files that appear from now on
            fn = lambda: self._run_folder(folder)  # noqa: E731
        elif kind == "webcam":
            fn = lambda: self._run_webcam(int(target))  # noqa: E731
        else:
            raise ValueError("unknown source")
        self.source, self.message, self.notice = f"{kind}:{target}", "", ""
        self._stop.clear()
        self._thread = threading.Thread(target=fn, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread, self.source = None, None

    def _run_folder(self, folder: Path):
        while not self._stop.is_set():
            for p in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime):
                if self._stop.is_set():
                    return
                if p.name in self._seen or p.suffix.lower() not in IMG_EXT:
                    continue
                if time.time() - p.stat().st_mtime < 1.0:  # still being written
                    continue
                self._seen.add(p.name)
                img = decode(p.read_bytes())
                if img is not None:
                    self.process_page(img, p.name) if self.page_mode else self.process(img, p.name)
            self._stop.wait(1.0)

    def _run_webcam(self, index: int):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)  # DirectShow is Windows-only
        if not cap.isOpened():
            log.warning("Could not open camera %s", index)
            self.message = f"Could not open camera {index}."
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        stab = Stability(hold=self.hold)
        reader = ThreadPoolExecutor(max_workers=1)  # one read at a time, in the order of the captures: parallel reads could finish out of order
        frames = 0
        try:
            log.info("Camera %s opened: asked 1920x1080, got %sx%s, backend %s", index, cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                     cap.get(cv2.CAP_PROP_FRAME_HEIGHT), cap.getBackendName())
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    log.warning("Camera %s stopped sending frames after %s frames", index, frames)
                    self.message = "The camera stopped sending frames."
                    break
                if frames == 0:
                    log.info("Camera %s first frame: shape %s, dtype %s", index, frame.shape, frame.dtype)
                frames += 1
                quad = find_card(frame)
                self._frame, self._quad = frame, quad
                fire = stab.update(quad, time.monotonic(), lambda: card_signature(frame, quad))
                view = frame.copy()
                if quad is not None:
                    cv2.polylines(view, [quad.astype(np.int32)], True, (90, 220, 120) if stab.fired else (60, 180, 255), 4)
                self._preview = cv2.imencode(".jpg", cv2.resize(view, None, fx=0.5, fy=0.5), [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
                if fire:
                    self.save_debug("fired", frame, quad)
                    card = warp_card(frame, quad)  # OCR takes ~1 s: read it in the worker so the preview does not block
                    reader.submit(self.process, card, "webcam", True, True).add_done_callback(
                        lambda f: f.exception() and log.error("Reading a camera capture failed", exc_info=f.exception()))
        except Exception as e:  # a failure here used to end the thread without a word
            log.exception("Camera %s failed after %s frames", index, frames)
            self.message = f"The camera failed: {e}"
        finally:
            reader.shutdown(wait=False, cancel_futures=True)
            cap.release()
            self._frame = self._quad = self._preview = None  # nothing to save or show once the camera is off (a restart must not show the last picture)
            log.info("Camera %s closed after %s frames", index, frames)

    DEBUG_KEEP = 30  # frames kept (each is a raw JPEG, one with the outline drawn and a small JSON)

    def save_debug(self, reason: str, frame=None, quad=None) -> Path | None:
        """Save the whole camera frame, the same with the detected card outline drawn, and the outline's corners, so a card that
        was not found (or a crop of the wrong part) can be looked at later. Returns the raw frame's path (None: no frame yet)."""
        if frame is None:
            frame, quad = self._frame, self._quad
        if frame is None:
            return None
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        now = time.time_ns()  # one reading of the clock: the names sort in the order the frames were taken
        base = self.debug_dir / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now // 10**9))}-{now % 10**9:09d}-{reason}"
        cv2.imwrite(str(base) + ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        view = frame.copy()
        if quad is not None:
            cv2.polylines(view, [np.asarray(quad).astype(np.int32)], True, (60, 180, 255), 4)
        cv2.imwrite(str(base) + "-outline.jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 85])
        Path(str(base) + ".json").write_text(json.dumps({"reason": reason, "shape": list(frame.shape),
                                                         "quad": None if quad is None else np.asarray(quad).round(1).tolist()}), encoding="utf-8")
        for old in sorted(self.debug_dir.glob("*.json"))[:-self.DEBUG_KEEP]:
            stem = str(old)[:-len(".json")]
            for f in (old, Path(stem + ".jpg"), Path(stem + "-outline.jpg")):
                f.unlink(missing_ok=True)
        log.info("Saved debug frame %s (%s, outline %s)", base.name, reason, "found" if quad is not None else "not found")
        return Path(str(base) + ".jpg")

    def preview_jpeg(self) -> bytes | None:
        return self._preview
