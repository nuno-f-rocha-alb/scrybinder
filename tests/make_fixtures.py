"""Regenerates the synthetic test fixtures (no personal data).

* fixtures/manabox_sample.csv  — 420 rows / 468 cards in ManaBox export format, random public printings (seeded)
* fixtures/cards/plst_noble_hierarch.png, plst_destroy_evil.png — Scryfall images of The List cards (spark tests)
* fixtures/cards/shadow_destroy_evil.jpg — synthetic photo of The List "Destroy Evil" next to a dark shadow

Needs the Scryfall bulk file (data/bulk/default-cards.jsonl.gz) and network access for the two card images.
Run: python tests/make_fixtures.py
"""
import csv
import gzip
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
BULK = HERE.parent / "data" / "bulk" / "default-cards.jsonl.gz"
HEADERS = {"User-Agent": "Scrybinder-tests/0.1 (fixture generator)"}
COLS = ["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity", "ManaBox ID", "Scryfall ID",
        "Purchase price", "Misprint", "Altered", "Signed", "Condition", "Language", "Proxy", "Purchase price currency", "Added"]
CONDITIONS = ["near_mint"] * 8 + ["lightly_played", "moderately_played"]


def sample_csv(rows=420, cards=468, seed=7):
    rng = random.Random(seed)
    pool, fixed = [], {}
    want = {c["id"] for c in json.loads((FIX / "cards" / "index.json").read_text(encoding="utf-8"))}  # cards the image tests identify
    with gzip.open(BULK, "rt", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c["id"] in want:
                fixed[c["id"]] = c
            elif (c.get("lang") == "en" and not c.get("digital") and c.get("layout") == "normal" and c.get("set") != "isd"  # 'isd' is the tests' own fake set
                  and c.get("rarity") in ("common", "uncommon", "rare", "mythic")):
                pool.append(c)
    assert len(fixed) == len(want), "a fixture card is missing from the bulk file"
    eoe = [c for c in pool if c["set"] == "eoe"]  # the set-progress tests need a few cards of one set
    picks = list(fixed.values()) + rng.sample(eoe, 4)
    rest = [c for c in pool if c not in picks]
    picks += rng.sample(rest, rows - len(picks))
    qty = [1] * rows
    for i in rng.sample(range(rows), cards - rows):
        qty[i] = 2
    base = datetime(2026, 1, 1)
    out = []
    for n, (c, q) in enumerate(zip(picks, qty)):
        foil = "foil" if "foil" in c.get("finishes", []) and rng.random() < 0.15 else "normal"
        price = round(rng.uniform(0.05, 4.0), 2)
        added = (base + timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        out.append([c["name"], c["set"].upper(), c["set_name"], c["collector_number"], foil, c["rarity"], q, 10000 + n, c["id"],
                    str(price), "false", "false", "false", rng.choice(CONDITIONS), "en", "false", "EUR", added])
    with open(FIX / "manabox_sample.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLS)
        w.writerows(out)
    print("csv:", len(out), "rows,", sum(qty), "cards")


def scryfall_image(path_in_api: str, version="png"):
    time.sleep(0.2)
    r = httpx.get(f"https://api.scryfall.com/cards/{path_in_api}", params={"format": "image", "version": version},
                  headers=HEADERS, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)


def shadow_photo(card, size=(2000, 1333), seed=3):
    """Light background; the card (≈512 px wide) lies next to a big dark shadow that touches the right/bottom edges."""
    W, H = size
    rng = np.random.default_rng(seed)
    bg = np.tile(np.linspace(214, 188, W, dtype=np.float32)[None, :], (H, 1))
    img = np.dstack([bg * 0.98, bg, bg * 1.01]).clip(0, 255).astype(np.uint8)
    cw = 512
    ch = int(cw * 88 / 63)
    x0, y0 = 744, 330
    quad_dst = np.float32([[x0, y0], [x0 + cw, y0 - 8], [x0 + cw + 16, y0 + ch], [x0 + 3, y0 + ch + 8]])
    h, w = card.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), quad_dst)
    warped = cv2.warpPerspective(card, M, (W, H), flags=cv2.INTER_AREA)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    shadow = np.zeros((H, W), np.uint8)
    cv2.fillPoly(shadow, [np.int32([[x0 + cw, y0 - 8], [W, 0], [W, H], [x0 + 40, H]])], 255)
    shadow = cv2.GaussianBlur(shadow, (0, 0), 25).astype(np.float32) / 255 * 0.72
    img = (img * (1 - shadow[..., None])).astype(np.uint8)
    img = np.where(mask[..., None] > 0, warped, img)
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    img = np.clip(img.astype(np.float32) + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    return img


if __name__ == "__main__":
    sample_csv()
    noble = scryfall_image("plst/MM2-151")
    cv2.imwrite(str(FIX / "cards" / "plst_noble_hierarch.png"), noble)
    destroy = scryfall_image("plst/DMU-17")
    cv2.imwrite(str(FIX / "cards" / "plst_destroy_evil.png"), destroy)
    cv2.imwrite(str(FIX / "cards" / "shadow_destroy_evil.jpg"), shadow_photo(destroy), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print("images written")
