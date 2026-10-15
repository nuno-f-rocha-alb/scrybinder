"""Visual embeddings (DINOv2) of the whole card and its artwork. Torch is only imported when the model loads (`vision` extra).

Index and capture go through the SAME code: normalised 630x880 card → card vector + art-crop vectors.
The per-frame-era crops were calibrated against Scryfall's `art_crop` images (template matching, 4 cards per era).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

from .vision import CARD_H, CARD_W

_BUNDLED_HF = Path(getattr(sys, "_MEIPASS", "/nonexistent")) / "hf"  # release builds ship the DINOv2 weights (offline use)
_HF_KW = {"cache_dir": str(_BUNDLED_HF), "local_files_only": True} if _BUNDLED_HF.is_dir() else {}  # bundled weights: never hit the network
MODEL_ID = os.environ.get("SCRYBINDER_MODEL", "facebook/dinov2-base")
CARD_SIZE = (224, 308)   # (width, height): 16x22 patches of 14, no distortion of the 0.716 aspect ratio
ART_SIZE = (308, 224)    # 22x16 patches; the art box has an aspect ratio of ~1.4

# art boxes (x0, y0, x1, y1) as fractions of the 630x880 card, per frame era
BOXES = {
    "1993": (0.111, 0.093, 0.897, 0.544),
    "1997": (0.116, 0.099, 0.886, 0.543),
    "2003": (0.088, 0.120, 0.914, 0.553),
    "2015": (0.077, 0.114, 0.922, 0.555),   # also 'future' and showcase
    "wide": (0.003, 0.108, 0.997, 0.553),   # borderless
}


def art_box_name(frame: str | None, border_color: str | None) -> str:
    if border_color == "borderless":
        return "wide"
    return frame if frame in ("1993", "1997", "2003") else "2015"


class Stopped(Exception):
    """The caller asked to stop while vectors were being computed."""


def prep_hash() -> str:
    """Changes if any pre-processing parameter changes: the old index is then no longer reused."""
    blob = json.dumps({"boxes": BOXES, "card": CARD_SIZE, "art": ART_SIZE, "v": 1}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def normalize_card(img: np.ndarray) -> np.ndarray:
    """Any card image → 630x880 BGR (INTER_AREA when shrinking, CUBIC when enlarging)."""
    if img.shape[:2] == (CARD_H, CARD_W):
        return img
    interp = cv2.INTER_AREA if img.shape[1] > CARD_W else cv2.INTER_CUBIC
    return cv2.resize(img, (CARD_W, CARD_H), interpolation=interp)


def crop_art(card: np.ndarray, box: str) -> np.ndarray:
    x0, y0, x1, y1 = BOXES[box]
    return card[int(y0 * CARD_H):int(y1 * CARD_H), int(x0 * CARD_W):int(x1 * CARD_W)]


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


class Embedder:
    """DINOv2: normalised CLS token. `embed_raw` is the only method that touches torch (replaceable in tests)."""
    dim = 768

    def __init__(self, model_id: str = MODEL_ID):
        self.model_id, self._model, self._dev = model_id, None, None

    @property
    def tag(self) -> str:
        return self.model_id.replace("/", "_")

    def _load(self):
        import logging
        import time
        import torch
        from transformers import AutoModel
        from transformers.utils import logging as hf_logging
        hf_logging.disable_progress_bar()  # "Loading weights" bars, a line per redraw in the log, every time the model is loaded
        t0 = time.monotonic()
        self._dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = AutoModel.from_pretrained(self.model_id, **_HF_KW).eval().to(self._dev)
        if self._dev == "cuda":
            self._model.half()
        logging.getLogger("scrybinder.scan").info("Visual model loaded on %s in %.1f s", self._dev, time.monotonic() - t0)

    def embed_raw(self, imgs: list[np.ndarray], size: tuple[int, int], batch=64, progress=None) -> np.ndarray:
        """`progress(done, total)` is called after every batch; if it returns True the work is abandoned (`Stopped`)."""
        import torch
        if self._model is None:
            self._load()
        mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
        out = []
        for i in range(0, len(imgs), batch):
            arr = np.stack([(cv2.cvtColor(cv2.resize(im, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                             .astype(np.float32) / 255 - mean) / std for im in imgs[i:i + batch]])
            x = torch.from_numpy(arr).permute(0, 3, 1, 2).to(self._dev)
            with torch.no_grad():
                o = self._model(pixel_values=x.half() if self._dev == "cuda" else x).pooler_output
            out.append(o.float().cpu().numpy())
            if progress and progress(min(i + batch, len(imgs)), len(imgs)):
                raise Stopped()
        return _unit(np.concatenate(out)) if out else np.zeros((0, self.dim), np.float32)

    def cards(self, cards: list[np.ndarray], progress=None) -> np.ndarray:
        return self.embed_raw(cards, CARD_SIZE, progress=progress)

    def arts(self, cards: list[np.ndarray], boxes: list[str], progress=None) -> np.ndarray:
        return self.embed_raw([crop_art(c, b) for c, b in zip(cards, boxes)], ART_SIZE, progress=progress)

    def query(self, card: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """630x880 capture → (card vector [d], art vectors per candidate box [len(BOXES), d])."""
        card = normalize_card(card)
        return self.cards([card])[0], self.arts([card] * len(BOXES), list(BOXES))
