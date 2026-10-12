"""Smoke test of a PACKAGED build (CI runs it on the PyInstaller output; not collected by pytest).
Usage: python tests/smoke_packaged.py <exe> <work-dir>   (run with the project's environment: it prepares the data with the source code)
Builds a tiny database + visual index from the fixture cards, starts the packaged app on it, uploads a synthetic photo and checks
that the artwork index was really used (in_index/art/card signals), not just OCR."""
import csv
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import cv2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console is cp1252; the app log is not
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
exe, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
data = work / "data"
fix = root / "tests" / "fixtures"
CARD = "060f9675-4921-4cbb-bae2-54c85c679fd4"

import os  # noqa: E402
os.environ["SCRYBINDER_DATA"] = str(data)
from scrybinder import db as dbmod, scryfall  # noqa: E402
from scrybinder.cli import index_main  # noqa: E402
from scrybinder.scan import synth  # noqa: E402

ids = {p.stem for p in (fix / "cards").glob("*.jpg")}
cards = []
for i, r in enumerate(csv.DictReader(open(fix / "manabox_sample.csv", encoding="utf-8-sig"))):
    if r["Scryfall ID"] in ids and all(c["id"] != r["Scryfall ID"] for c in cards):
        cards.append({"id": r["Scryfall ID"], "oracle_id": f"o-{r['Name']}", "name": r["Name"], "set": r["Set code"].lower(),
                      "set_name": r["Set name"], "collector_number": r["Collector number"], "released_at": "2024-01-01",
                      "rarity": "common", "layout": "normal", "lang": "en", "full_art": False, "border_color": "black",
                      "frame": "2015", "finishes": ["nonfoil"], "cardmarket_id": 1000 + i, "prices": {"eur": "1.00"},
                      "image_uris": {"small": "http://127.0.0.1:9/s.jpg", "normal": "http://127.0.0.1:9/n.jpg"}, "digital": False})
data.mkdir(parents=True, exist_ok=True)
(data / "bulk.json").write_text(json.dumps(cards), encoding="utf-8")
conn = dbmod.connect(data / "scrybinder.db")
scryfall.import_bulk(conn, data / "bulk.json")
conn.close()
(data / "images" / "normal").mkdir(parents=True, exist_ok=True)
for c in cards:
    shutil.copy(fix / "cards" / f"{c['id']}.jpg", data / "images" / "normal" / f"{c['id']}.jpg")
index_main(["--pilot"])
cv2.imwrite(str(work / "photo.jpg"), synth.photo(fix / "cards" / f"{CARD}.jpg", seed=3))

proc = subprocess.Popen([str(exe), "--serve"], env={**os.environ, "SCRYBINDER_AUTO_BULK": "0", "HF_HUB_OFFLINE": "1"})
log = data / "scrybinder.log"
try:
    for _ in range(120):
        time.sleep(1)
        if log.exists() and log.read_text(encoding="utf-8", errors="replace").startswith("http"):
            break
    url = log.read_text(encoding="utf-8").splitlines()[0]
    base = url.split("?")[0]
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    op.open(url).read()
    time.sleep(20)  # the model warms up in the background
    req = urllib.request.Request(base + "api/scan/photo?name=photo.jpg", data=(work / "photo.jpg").read_bytes(),
                                 headers={"Content-Type": "image/jpeg"})
    res = json.load(op.open(req, timeout=120))
    top = res["candidates"][0]
    print("top:", top["name"], top["id"], "in_index:", top.get("in_index"), "art:", top.get("art"), "confidence:", res["confidence"])
    ok = top["id"] == CARD and top.get("in_index") is True and top.get("art") is not None
finally:
    proc.terminate()
    print("--- app log ---")
    print(log.read_text(encoding="utf-8", errors="replace")[-9000:])
sys.exit(0 if ok else 1)
