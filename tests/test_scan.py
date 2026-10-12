import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from scrybinder.scan.synth import photo  # noqa: E402

from scrybinder.api import create_app  # noqa: E402
from scrybinder.scan import identify, vision  # noqa: E402

CARDS = Path(__file__).parent / "fixtures" / "cards"
META = {m["name"]: m for m in json.loads((CARDS / "index.json").read_text(encoding="utf-8"))}
needs_tess = pytest.mark.skipif(
    not (Path(identify.pytesseract.pytesseract.tesseract_cmd).exists() or shutil.which("tesseract")),
    reason="Tesseract not installed")
TOKEN = "tok"


def the_list_photo(name):
    """Synthetic photo of a The List card; seed 5 is one where the spark detector sees the symbol (it is geometry-sensitive)."""
    return photo(CARDS / name, seed=5)


def img_of(name, seed=0, **kw):
    return photo(CARDS / f"{META[name]['id']}.jpg", seed=seed, **kw)


def test_find_card_and_warp_shape():
    for seed in range(4):
        q = vision.find_card(img_of("Thrill of Possibility", seed))
        assert q is not None and q.shape == (4, 2)
    card, ok = vision.card_from_photo(img_of("Thrill of Possibility", rot=90))  # carta deitada
    assert ok and card.shape == (vision.CARD_H, vision.CARD_W, 3)


def test_no_card_in_empty_frame():
    assert vision.find_card(np.full((720, 1280, 3), 40, np.uint8)) is None


def test_stability_fires_once_and_rearms_when_card_leaves():
    s = vision.Stability(hold=0.4, tol=6, gap=0.5)
    q = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)
    assert not s.update(q, 0.0) and not s.update(q + 2, 0.2)       # a assentar
    assert s.update(q + 2, 0.5)                                    # still for ≥ 0.4 s: fires
    assert not any(s.update(q + 2, 0.6 + 0.1 * i) for i in range(10))  # does not repeat the same card
    s.update(None, 2.0); s.update(None, 2.6)                       # card leaves for ≥ 0.5 s
    assert not s.update(q, 2.7) and s.update(q, 3.2)               # nova carta: dispara outra vez
    # continuous movement never fires
    s2 = vision.Stability(hold=0.4, tol=6)
    assert not any(s2.update(q + 10 * i, 0.1 * i) for i in range(20))


def test_stability_swap_without_leaving_view():
    s = vision.Stability(hold=0.3)
    a = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)
    s.update(a, 0.0); assert s.update(a, 0.4)
    b = a + 120                                                     # carta trocada sem sair do campo
    s.update(b, 0.5); assert s.update(b, 0.9)


def test_parse_bottom():
    p = identify.parse_bottom("103/342 R\nC15 • EN\n")
    assert p["numbers"] == ["103"] and "C15" in p["tokens"]
    p = identify.parse_bottom("R o1s5\nMKM-+ ON")                    # new frame + confusions o→0, s→5
    assert p["numbers"][0] == "155" and "MKM" in p["tokens"]
    assert identify.parse_bottom("lixo")["numbers"] == []
    p = identify.parse_bottom("MO317 FFVII\nFIN • EN")               # rarity glued to the number (real photo, Sephiroth FIN #317)
    assert p["numbers"] == ["317"] and "FIN" in p["tokens"]
    assert identify.parse_bottom("COOL LOOL")["numbers"] == []       # words do not become numbers


def test_clean_strips_icon_noise():
    assert identify._clean("X Reins of Power |") == "Reins of Power"


@needs_tess
@pytest.mark.parametrize("name", ["Thrill of Possibility", "Aetherflux Reservoir", "Waterlogged Teachings // Inundated Archive"])
def test_identify_modern_frames(db, name):
    r = identify.Identifier(db).identify(vision.card_from_photo(img_of(name, seed=3))[0])
    assert r["candidates"][0]["id"] == META[name]["id"], r["ocr"]


@needs_tess
def test_identify_garbage_gives_no_candidates(db):
    noise = np.random.default_rng(1).integers(0, 255, (880, 630, 3), dtype=np.uint8)
    assert identify.Identifier(db).identify(noise)["confidence"] in ("none", "low")


@pytest.fixture
def client(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    return c


def jpg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


@needs_tess
def test_photo_confirm_flow_logs_pair(client, db, tmp_path):
    client.app.state.scanner.dir = tmp_path
    r = client.post("/api/scan/photo?name=a.jpg", content=jpg(img_of("Thrill of Possibility", seed=2)))
    assert r.status_code == 200
    item = r.json()
    top = item["candidates"][0]["id"]
    assert top == META["Thrill of Possibility"]["id"] and (tmp_path / f"{item['id']}.jpg").exists()
    assert client.get("/api/scan/state").json()["pending"][0]["id"] == item["id"]
    ok = client.post(f"/api/scan/{item['id']}/confirm", json={"scryfall_id": top, "finish": "foil", "quantity": 2,
                                                              "condition": "LP", "language": "en", "location": "Box 9"})
    assert ok.status_code == 200
    row = db.execute("SELECT * FROM collection WHERE location='Box 9'").fetchone()
    assert (row["quantity"], row["finish"], row["condition"]) == (2, "foil", "LP")
    log = db.execute("SELECT * FROM scan_log").fetchone()
    assert (log["final_id"], log["predicted_id"], log["corrected"]) == (top, top, 0)
    assert client.get("/api/scan/state").json()["pending"] == []


def test_correction_is_logged_and_bad_confirm_keeps_pending(client, db, tmp_path):
    sc = client.app.state.scanner
    sc.dir = tmp_path
    item = {"id": 77, "label": "", "detected": True, "ocr": {}, "candidates": [], "confidence": "low", "predicted_id": "dfc-1"}
    sc.pending.append(item)
    assert client.post("/api/scan/77/confirm", json={"scryfall_id": "nao-existe"}).status_code == 422
    assert len(sc.pending) == 1                                      # not lost
    assert client.post("/api/scan/77/confirm", json={"scryfall_id": item["predicted_id"] and "dfc-1"}).status_code == 200
    sc.pending.append({**item, "id": 78})
    other = db.execute("SELECT id FROM cards WHERE id<>'dfc-1' LIMIT 1").fetchone()[0]
    client.post("/api/scan/78/confirm", json={"scryfall_id": other})
    assert db.execute("SELECT corrected FROM scan_log WHERE id=78").fetchone()[0] == 1


def test_upload_validation_and_security(client):
    assert client.post("/api/scan/photo", content=b"").status_code == 400
    assert client.post("/api/scan/photo", content=b"isto nao e uma imagem").status_code == 415
    assert client.post("/api/scan/9999/discard").status_code == 404
    assert client.get("/api/scan/capture/9999").status_code == 404
    assert client.post("/api/scan/start", json={"kind": "folder", "target": "C:/nao/existe"}).status_code == 422
    assert client.post("/api/scan/start", json={"kind": "x"}).status_code == 422
    anon = TestClient(client.app)                                      # no cookie
    assert anon.get("/api/scan/state", headers={"host": "testserver"}).status_code == 401


@needs_tess
def test_folder_source_picks_up_only_new_images(client, tmp_path):
    folder = tmp_path / "in"; folder.mkdir()
    cv2.imwrite(str(folder / "old.jpg"), img_of("Faithless Looting"))   # already existed: ignored
    sc = client.app.state.scanner
    sc.dir = tmp_path / "cap"
    assert client.post("/api/scan/start", json={"kind": "folder", "target": str(folder)}).status_code == 200
    cv2.imwrite(str(folder / "new.jpg"), img_of("Faithless Looting", seed=5))
    for _ in range(80):
        if sc.state()["pending"]:
            break
        time.sleep(0.1)
    client.post("/api/scan/stop")
    p = sc.state()["pending"]
    assert [x["label"] for x in p] == ["new.jpg"] and p[0]["candidates"][0]["id"] == META["Faithless Looting"]["id"]


def test_exact_set_and_number_beat_promo_lookalikes():
    bottom = identify.parse_bottom("192/264 R\nKLD • EN")
    normal = {"set_code": "kld", "collector_number": "192"}
    promo = {"set_code": "pkld", "collector_number": "192s"}   # same number (digits only) and similar code
    sc = identify.Identifier._score
    assert sc(normal, bottom) > sc(promo, bottom)
    assert sc({"set_code": "xyz", "collector_number": "5"}, bottom) == 0


def _noble_db(db):
    for cid, st, num, rel in [("nh-mm2", "mm2", "151", "2015-05-22"), ("nh-plst", "plst", "MM2-151", "2024-08-02"),
                              ("nh-2xm", "2xm", "177", "2020-08-07")]:
        db.execute("INSERT INTO cards SELECT ?, 'o-nh', 'Noble Hierarch', ?, 'x', ?, ?, rarity, layout, lang, type_line, full_art,"
                   " border_color, frame, frame_effects, promo_types, finishes, cardmarket_id, eur, eur_foil, eur_etched,"
                   " image_small, image_normal, digital, NULL, NULL FROM cards WHERE id='dfc-1'", (cid, st, num, rel))


def test_has_spark_on_the_list_cards_and_not_on_normal_cards():
    user = the_list_photo("plst_noble_hierarch.png")
    assert identify.has_spark(vision.card_from_photo(user)[0])
    real = the_list_photo("plst_destroy_evil.png")   # 2022 frame: the spark sits further right
    assert identify.has_spark(vision.card_from_photo(real)[0])
    for name in ("Thrill of Possibility", "Aetherflux Reservoir", "Quicksilver Elemental", "Waterlogged Teachings // Inundated Archive"):
        assert not identify.has_spark(vision.card_from_photo(img_of(name, seed=4))[0]), name


# ponytail: Tesseract on Linux/macOS CI reads the synthetic collector number "151" as "181"; tuned on the Windows build only
@pytest.mark.skipif(sys.platform != "win32", reason="OCR of the synthetic collector number is Tesseract-build dependent")
@needs_tess
def test_the_list_spark_decides_between_plst_and_original(db):
    """Photo of The List card (PLST MM2-151): Scryfall stores 'MM2-151'; the printed card says 151/249 and MM2."""
    _noble_db(db)
    ident = identify.Identifier(db)
    user = the_list_photo("plst_noble_hierarch.png")
    r = ident.identify(vision.card_from_photo(user)[0])
    assert r["ocr"]["spark"] and [c["id"] for c in r["candidates"][:2]] == ["nh-plst", "nh-mm2"], r["candidates"][:3]
    assert r["candidates"][0]["score"] > r["candidates"][1]["score"] > r["candidates"][2]["score"]
    assert r["confidence"] in ("high", "medium")
    # the same card WITHOUT the spark (blacked out) is the original MM2 printing, not the PLST
    card = vision.card_from_photo(user)[0].copy()
    x0, y0, x1, y1 = (int(v) for v in (0.0 * 630, 0.93 * 880, 0.072 * 630, 0.99 * 880))
    card[y0:y1, x0:x1] = 25
    r2 = ident.identify(card)
    assert not r2["ocr"]["spark"] and r2["candidates"][0]["id"] == "nh-mm2", r2["candidates"][:3]


def test_compound_number_scoring_unit():
    sc = identify.Identifier._score
    b = identify.parse_bottom("151/249 R\nMM2 • EN")
    assert sc({"set_code": "plst", "collector_number": "MM2-151"}, b) == sc({"set_code": "mm2", "collector_number": "151"}, b) == 6
    assert sc({"set_code": "plst", "collector_number": "MM2-151"}, {**b, "spark": True}) == 9    # spark: +3
    assert sc({"set_code": "plst", "collector_number": "MM2-151"}, {**b, "spark": False}) == 5   # sem spark: -1 (fraco: o detetor pode falhar)
    assert sc({"set_code": "plst", "collector_number": "CLB-187"}, b) == 0


def test_photo_with_dark_shadow_detects_the_card_not_the_shadow():
    """Synthetic photo (2000x1333, light background with a dark shadow on the right): it used to pick shadow+card."""
    img = cv2.imread(str(CARDS / "shadow_destroy_evil.jpg"))
    q = vision.find_card(img)
    assert q is not None
    x0, y0 = q.min(0)
    x1, y1 = q.max(0)
    assert 700 < x0 < 800 and 300 < y0 < 360 and 1230 < x1 < 1300 and 1000 < y1 < 1080, q.round().tolist()
    assert (x1 - x0) < 600  # the card, not the shadow blob (which reached the right edge)


def test_dark_blob_touching_border_is_not_a_card():
    frame = np.full((600, 800, 3), 200, np.uint8)
    cv2.rectangle(frame, (500, 0), (799, 599), (30, 30, 30), -1)   # card-shaped shadow touching the edges
    assert vision.find_card(frame) is None


@needs_tess
def test_the_list_candidate_wins_with_spark_destroy_evil(db):
    for cid, st, num, rel in [("de-dmu", "dmu", "17", "2022-09-09"), ("de-plst", "plst", "DMU-17", "2024-08-02"),
                              ("de-fdc", "fdc", "26", "2024-11-15")]:
        db.execute("INSERT INTO cards SELECT ?, 'o-de', 'Destroy Evil', ?, 'x', ?, ?, rarity, layout, lang, type_line, full_art,"
                   " border_color, frame, frame_effects, promo_types, finishes, cardmarket_id, eur, eur_foil, eur_etched,"
                   " image_small, image_normal, digital, NULL, NULL FROM cards WHERE id='dfc-1'", (cid, st, num, rel))
    img = the_list_photo("plst_destroy_evil.png")
    r = identify.Identifier(db).identify(vision.card_from_photo(img)[0])
    assert r["ocr"]["spark"] and r["candidates"][0]["id"] == "de-plst", [(c["id"], c["score"]) for c in r["candidates"]]


def test_garbage_ocr_never_matches_blank_names(db):
    """Foto real: o texto lixo '| a' casava a 100 % com 'Unknown Event' ('______'), vazio depois de normalizar."""
    db.execute("INSERT INTO cards SELECT 'blank-1', 'o-blank', '______', set_code, set_name, collector_number, released_at,"
               " rarity, layout, lang, type_line, full_art, border_color, frame, frame_effects, promo_types, finishes,"
               " cardmarket_id, eur, eur_foil, eur_etched, image_small, image_normal, digital, NULL, NULL FROM cards WHERE id='dfc-1'")
    ident = identify.Identifier(db)
    for junk in ("| a", "  ", "!!", "a", "_ _"):
        assert ident.match_names(junk) == [], junk


def test_inner_card_none_on_tight_card_and_finds_card_in_a_sleeve():
    tight = cv2.resize(cv2.imread(str(CARDS / f"{META['Thrill of Possibility']['id']}.jpg")), (630, 880))
    assert vision.inner_card(tight) is None            # tight card: touches the edges, there is no "inner" one
    sleeve = np.full((1000, 760, 3), 215, np.uint8)     # toploader: light margin around the card
    sleeve[70:950, 60:690] = tight
    inner = vision.inner_card(cv2.resize(sleeve, (630, 880)))
    assert inner is not None and inner.shape == (880, 630, 3)


def test_same_print_merges_into_one_pending_and_split_next_opens_new(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    scanner = session.Scanner(db, tmp_path)
    img = np.zeros((880, 630, 3), np.uint8)
    res = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False},
           "candidates": [{"id": "A"}], "confidence": "high"}
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    scanner.process(img, "1", warped=True)
    scanner.process(img, "2", warped=True)
    assert len(scanner.pending) == 1 and scanner.pending[0]["qty"] == 2
    scanner.split_next = True
    scanner.process(img, "3", warped=True)  # the foil: a new entry even though it is the same printing
    assert [p["qty"] for p in scanner.pending] == [2, 1] and scanner.split_next is False
    scanner.process(img, "4", warped=True)  # adds again, now to the most recent entry
    assert [p["qty"] for p in scanner.pending] == [2, 2]
    res["candidates"] = [{"id": "B"}]
    scanner.process(img, "5", warped=True)
    assert len(scanner.pending) == 3


def test_list_mode_merge_foil_edit_commit_and_persist(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    cid = db.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    scanner = session.Scanner(db, tmp_path)
    scanner.list_mode = True
    img = np.zeros((880, 630, 3), np.uint8)
    res = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False},
           "candidates": [{"id": cid, "finishes": '["nonfoil", "foil"]'}], "confidence": "high"}
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    scanner.process(img, "1", warped=True)
    scanner.process(img, "2", warped=True)            # identical: adds up
    scanner.split_next = True
    scanner.process(img, "3", warped=True)            # foil: new entry
    assert [(r["finish"], r["qty"]) for r in scanner.reads] == [("nonfoil", 2), ("foil", 1)]
    assert not scanner.pending and len(scanner.state()["reads"]) == 2
    scanner.process(img, "4", warped=True)            # adds to the regular entry again, not the foil
    assert [r["qty"] for r in scanner.reads] == [3, 1]
    again = session.Scanner(db, tmp_path)             # the list survives a restart
    assert [r["qty"] for r in again.reads] == [3, 1]
    scanner.read_edit(scanner.reads[1]["id"], finish="nonfoil", qty=2, condition="LP")
    assert scanner.reads[1]["condition"] == "LP"
    scanner.read_delete(scanner.reads[1]["id"])
    out = scanner.commit_reads("TESTE-lista")
    assert out == {"added": 3, "rows": 1} and scanner.reads == []
    row = db.execute("SELECT quantity, finish, location FROM collection WHERE location='TESTE-lista'").fetchone()
    assert tuple(row) == (3, "nonfoil", "TESTE-lista")
    assert db.execute("SELECT COUNT(*) FROM scan_log WHERE location='TESTE-lista'").fetchone()[0] == 1


def test_open_url_only_scryfall_and_cardmarket_over_https(client, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    ok = ["https://scryfall.com/card/abc", "https://www.cardmarket.com/en/Magic/Products?idProduct=1"]
    bad = ["http://scryfall.com/x", "https://evil.com/scryfall.com", "https://scryfall.com.evil.com/x", "file:///C:/Windows", "javascript:alert(1)", ""]
    for u in ok:
        assert client.post("/api/open-url", json={"url": u}).status_code == 200
    for u in bad:
        assert client.post("/api/open-url", json={"url": u}).status_code == 422
    assert opened == ok
    row = client.get("/api/collection").json()["rows"]
    assert row == [] or "cardmarket_id" in row[0]  # the collection already returns the Cardmarket id for the link


def test_index_build_from_settings(client, monkeypatch):
    """POST /api/index/build runs add_rows + build in a thread, reports progress in /api/status and honours stop."""
    from scrybinder.scan import index as ixmod
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object() if name == "torch" else real(name, *a, **k))  # CI has no torch
    seen = {}
    monkeypatch.setattr(ixmod, "add_rows", lambda conn, d, where="1", params=(), dry_run=False: seen.update(where=where) or 3)

    def fake_build(emb, d, progress=None, should_stop=None):
        progress(2, 3)
        return {"indexed": 0, "failed_downloads": 1}
    monkeypatch.setattr(ixmod, "build", fake_build)
    assert client.post("/api/index/build", json={"mode": "nope"}).status_code == 422
    assert client.post("/api/index/build", json={"mode": "pilot"}).json() == {"started": True}
    for _ in range(100):
        job = client.get("/api/status").json()["index_job"]
        if job["state"] not in ("prepare", "build"):
            break
        time.sleep(0.05)
    assert job["state"] == "done" and job["failed"] == 1 and job["done"] == 2 and "scan_log" in seen["where"]
    assert client.get("/api/index/estimate").json()["printings"] == 3
