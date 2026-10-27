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


def test_stability_does_not_fire_again_when_the_detector_flips_between_shapes():
    """A card in a dock: the outline found jumps between the whole card and a rectangle inside it. That is not a new card."""
    s = vision.Stability(hold=0.4)
    whole = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)       # 300 x 420
    lower = np.array([[100, 280], [400, 280], [400, 520], [100, 520]], np.float32)       # 300 x 240: the lower half
    text = np.array([[130, 330], [370, 330], [370, 480], [130, 480]], np.float32)        # the text box
    s.update(whole, 0.0)
    assert s.update(whole, 0.5)
    fired = [s.update(q, 1.0 + 0.1 * i) for i, q in enumerate([lower, text, whole, lower, text, whole] * 6)]
    assert not any(fired)  # 3.6 s of flipping and it never captures the same card again
    s.update(None, 5.0)
    s.update(None, 5.5)
    assert not s.update(whole, 5.6)  # a flicker shorter than the gap does not re-arm either
    s.update(None, 6.0)
    s.update(None, 6.9)  # the card really left
    assert not s.update(whole, 7.0) and s.update(whole, 7.5)


def _picture(seed):
    """A card-like texture in a frame: structured noise, different for every seed."""
    rng = np.random.RandomState(seed)
    tex = cv2.GaussianBlur(rng.randint(0, 255, (60, 43), np.uint8), (5, 5), 0)
    frame = np.full((720, 1280, 3), 120, np.uint8)
    frame[100:520, 100:400] = cv2.cvtColor(cv2.resize(tex, (300, 420)), cv2.COLOR_GRAY2BGR)
    return frame


def test_card_signature_tells_the_same_card_from_another_whatever_the_light():
    quad = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)
    a, b = _picture(1), _picture(2)
    same = vision.card_signature(np.clip(a.astype(np.float32) * 1.3 + 15, 0, 255).astype(np.uint8), quad)  # brighter and more contrast
    assert np.abs(vision.card_signature(a, quad) - same).mean() < vision.SWAP_DIFF / 2
    assert np.abs(vision.card_signature(a, quad) - vision.card_signature(b, quad)).mean() > 2 * vision.SWAP_DIFF


def test_stability_a_card_swapped_in_the_same_place_fires_once_it_stops_moving():
    quad = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)
    sig = {n: (lambda f=_picture(n): vision.card_signature(f, quad)) for n in (1, 2, 3)}
    s = vision.Stability(hold=0.4)
    s.update(quad, 0.0, sig[1])
    assert s.update(quad, 0.5, sig[1])                                                # card 1
    assert not any(s.update(quad, 0.6 + 0.1 * i, sig[1]) for i in range(10))          # still card 1: nothing
    # the new card is being slid in: the picture changes every frame, nothing is captured
    assert not any(s.update(quad, 2.0 + 0.1 * i, sig[2 + i % 2]) for i in range(10))
    # it stops: after the hold it is captured, once
    fired = [s.update(quad, 3.0 + 0.1 * i, sig[2]) for i in range(12)]
    assert fired.count(True) == 1 and fired.index(True) >= 4                          # not before ~0.4 s of the new picture
    assert not any(s.update(quad, 4.5 + 0.1 * i, sig[2]) for i in range(10))          # and not again


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
    for _ in range(300):  # up to 30 s: the CI runners are slow (the file must be 1 s old, then OCR)
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


def test_locked_sets_limit_the_printings_the_scan_can_name(db):
    _noble_db(db)
    ident = identify.Identifier(db)
    name = ["Noble Hierarch"]
    assert {p["set_code"] for p in ident.prints(name)} == {"mm2", "plst", "2xm"}
    assert ident.lock_sets([" PLST "]) == {"plst"}
    assert [p["set_code"] for p in ident.prints(name)] == ["plst"]
    assert ident.prints(["Thrill of Possibility"]) == []  # a card that has no printing in the chosen sets is not guessed
    with pytest.raises(ValueError):
        ident.lock_sets(["nope"])
    assert ident.locked == {"plst"}  # a refused change leaves the lock as it was
    ident.lock_sets([])
    assert len(ident.prints(name)) == 3


def test_locked_sets_limit_the_artwork_search(db):
    from scrybinder.scan import visual

    _noble_db(db)

    class Ix:
        rows = [{"card_id": c, "illustration_id": f"ill-{c}"} for c in ("nh-mm2", "nh-plst", "nh-2xm")]
        scores = staticmethod(lambda cv, av: (np.array([0.9, 0.8, 0.7]), np.array([0.9, 0.8, 0.7])))

    class Emb:
        query = staticmethod(lambda card: (None, None))

    v = visual.Visual(Emb(), Ix(), db)
    w = visual.weights()
    card = np.zeros((880, 630, 3), np.uint8)
    assert set(v.query(card, w)[0]) == {"nh-mm2", "nh-plst", "nh-2xm"}
    got, top = v.query(card, w, frozenset({"plst"}))
    assert set(got) == {"nh-plst"} and top == pytest.approx(0.8)  # the better-looking printings of other sets are out
    assert v.query(card, w, frozenset({"2xm"}))[0].keys() == {"nh-2xm"}


def test_scan_sets_endpoint(client, db):
    _noble_db(db)
    assert client.post("/api/scan/sets", json={"sets": ["plst"]}).json() == {"sets": ["plst"]}
    assert client.get("/api/scan/state").json()["sets"] == ["plst"]
    assert client.post("/api/scan/sets", json={"sets": ["nope"]}).status_code == 422
    assert client.post("/api/scan/sets", json={"sets": "plst"}).status_code == 422
    assert client.post("/api/scan/sets", json={"sets": []}).json() == {"sets": []}


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
    scanner.process(img, "4", warped=True)            # not the card right before (the foil): a new entry, not added to the first one
    assert [(r["finish"], r["qty"]) for r in scanner.reads] == [("nonfoil", 2), ("foil", 1), ("nonfoil", 1)]
    again = session.Scanner(db, tmp_path)             # the list survives a restart
    assert [r["qty"] for r in again.reads] == [2, 1, 1]
    scanner.read_edit(scanner.reads[1]["id"], finish="nonfoil", qty=2, condition="LP")
    assert scanner.reads[1]["condition"] == "LP"
    scanner.read_delete(scanner.reads[1]["id"])
    out = scanner.commit_reads("TESTE-lista")         # the identical rows of the list meet again in the collection
    assert out == {"added": 3, "rows": 2} and scanner.reads == []  # two entries of the list...
    assert db.execute("SELECT COUNT(*) FROM collection WHERE location='TESTE-lista'").fetchone()[0] == 1  # ...one row in the collection
    row = db.execute("SELECT quantity, finish, location FROM collection WHERE location='TESTE-lista'").fetchone()
    assert tuple(row) == (3, "nonfoil", "TESTE-lista")
    assert db.execute("SELECT COUNT(*) FROM scan_log WHERE location='TESTE-lista'").fetchone()[0] == 2  # one log line per entry


def test_only_identical_cards_in_a_row_add_up(db, tmp_path, monkeypatch):
    """X, then others, then X again: the second X is a new line, and the list does not change an entry far above. Only when the
    list goes into the collection do the identical rows meet (the collection adds up rows that are exactly the same)."""
    from scrybinder.scan import session
    ids = [r[0] for r in db.execute("SELECT id FROM cards ORDER BY id LIMIT 4")]
    x, others = ids[0], ids[1:]
    res = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False}, "candidates": [], "confidence": "high"}
    scanner = session.Scanner(db, tmp_path)
    scanner.list_mode = True
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    img = np.zeros((880, 630, 3), np.uint8)

    def read(card_id):
        res["candidates"] = [{"id": card_id, "finishes": '["nonfoil"]'}]
        scanner.process(img, "c", warped=True)

    for c in (x, x, x):                  # three X in a row: one entry of 3
        read(c)
    for c in others:                     # then other cards, each its own entry
        read(c)
    read(x)                              # X again after others: a new entry
    assert [(r["scryfall_id"] == x, r["qty"]) for r in scanner.reads] == [(True, 3), (False, 1), (False, 1), (False, 1), (True, 1)]
    read(x)                              # and now it is in a row with the one right before
    assert scanner.reads[-1]["qty"] == 2 and len(scanner.reads) == 5
    out = scanner.commit_reads("TESTE-x")
    assert out["added"] == 8 and out["rows"] == 5  # five entries of the list...
    assert db.execute("SELECT COUNT(*) FROM collection WHERE location='TESTE-x'").fetchone()[0] == 4  # ...four rows in the collection
    assert db.execute("SELECT quantity FROM collection WHERE location='TESTE-x' AND scryfall_id=?", (x,)).fetchone()[0] == 5

    pending = session.Scanner(db, tmp_path / "p")  # the same rule without the list mode
    res["candidates"] = [{"id": x}]
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    for c in (x, others[0], x):
        res["candidates"] = [{"id": c}]
        pending.process(img, "c", warped=True)
    assert [p["qty"] for p in pending.pending] == [1, 1, 1]


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

    def fake_build(emb, d, progress=None, should_stop=None, detail=None):
        progress(2, 3)
        detail("computing vectors 40% of this block")
        return {"indexed": 0, "failed_downloads": 1}
    monkeypatch.setattr(ixmod, "build", fake_build)
    assert client.post("/api/index/build", json={"mode": "nope"}).status_code == 422
    assert client.post("/api/index/build", json={"mode": "pilot"}).json() == {"started": True}
    for _ in range(100):
        job = client.get("/api/status").json()["index_job"]
        if job["state"] not in ("prepare", "build"):
            break
        time.sleep(0.05)
    assert job["state"] == "done" and job["failed"] == 1 and job["done"] == 2 and "vectors" in job["detail"] and "scan_log" in seen["where"]
    assert client.get("/api/index/estimate").json()["printings"] == 3


# --- binder pages (up to 3x3 cards in one photo) ---

def _page(seed, occupied=None, dark=True, gap=0.06, glare=False):
    from scrybinder.scan.synth import binder_page
    paths = sorted(CARDS.glob("*.jpg"))[:9]
    return binder_page(paths, occupied or [True] * 9, seed=seed, dark=dark, gap=gap, glare=glare)


def _iou(a, b, shape):
    ma, mb = np.zeros(shape, np.uint8), np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(ma, a.astype(np.int32), 1)
    cv2.fillConvexPoly(mb, b.astype(np.int32), 1)
    return (ma & mb).sum() / max(1, (ma | mb).sum())


def _found(img, cells):
    """(cells located with IoU >= 0.6, quads that match no cell). The quads include a little of the pocket around the card."""
    quads = vision.find_cards(img)
    hit, used = 0, set()
    for c in cells:
        ious = [_iou(c["quad"], q, img.shape[:2]) for q in quads]
        if ious and max(ious) >= 0.6:
            hit += 1
            used.add(int(np.argmax(ious)))
    return hit, len(quads) - len(used)


def test_binder_page_fixture_is_deterministic():
    a, ca = _page(1)
    b, cb = _page(1)
    assert np.array_equal(a, b) and len(ca) == len(cb) == 9
    assert len(_page(2, [i < 4 for i in range(9)])[1]) == 4


def test_find_cards_full_page_and_nothing():
    img, cells = _page(4)
    quads = vision.find_cards(img)
    assert len(quads) == 9 and _found(img, cells) == (9, 0)
    assert all(vision.warp_card(img, q).shape == (vision.CARD_H, vision.CARD_W, 3) for q in quads)
    assert vision.find_cards(np.full((900, 1200, 3), 40, np.uint8)) == []


def test_find_cards_gaps_reflection_light_binder_and_partial_pages():
    """Black borders on a dark page, tight and wide pockets, a reflection, a light binder, and the last page of a binder."""
    for kw in ({"gap": 0.05}, {"gap": 0.07}, {"gap": 0.07, "glare": True}, {"dark": False, "gap": 0.05}):
        img, cells = _page(5, **kw)
        assert _found(img, cells) == (9, 0), kw
    img, cells = _page(6, [i < 5 for i in range(9)])        # filled row by row: 3 + 2
    assert _found(img, cells) == (5, 0)
    img, cells = _page(7, [i < 2 for i in range(9)])        # two cards
    assert _found(img, cells) == (2, 0)
    img, cells = _page(8, [True, False, True, False, True, False, True, False, True])  # sold cards: holes inside the page
    assert _found(img, cells) == (5, 0)


def test_find_cards_recall_and_no_false_positives_on_empty_pockets():
    """Gate of the feature: >= 95 % of the cards localised (IoU >= 0.6) and no card invented in an empty pocket."""
    rng = np.random.default_rng(0)
    total = hit = fp = 0
    for seed in range(24):
        occ = [True] * 9
        if seed % 4 == 2:
            occ = [i < int(rng.integers(2, 9)) for i in range(9)]
        elif seed % 4 == 3:
            occ = list(rng.random(9) < 0.6)
            occ[0] = occ[8] = True
        dark = seed % 6 != 0                                # light binders are rare: a few pages
        img, cells = _page(seed, occ, dark=dark, gap=[0.05, 0.06, 0.07][seed % 3], glare=dark and seed % 5 == 1)
        h, extra = _found(img, cells)
        total, hit, fp = total + len(cells), hit + h, fp + extra
        if extra or h < len(cells):
            print(f"  seed {seed}: occupied {[int(x) for x in occ]} hit {h}/{len(cells)} extra {extra}")
    print(f"binder pages: recall {hit}/{total}, false positives {fp}")
    assert hit / total >= 0.95 and fp == 0


def test_process_page_adds_one_entry_per_card(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    cid = db.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    res = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False},
           "candidates": [{"id": cid, "finishes": '["nonfoil", "foil"]'}], "confidence": "high"}
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    scanner = session.Scanner(db, tmp_path)
    scanner.list_mode = True
    img, _ = _page(4)
    out = scanner.process_page(img, "page.jpg")
    assert out["detected"] == 9 and scanner.message == "9 cards detected"
    assert sum(r["qty"] for r in scanner.reads) == 9           # identical cards add up in list mode
    empty = scanner.process_page(np.full((900, 1200, 3), 40, np.uint8), "empty.jpg")
    assert empty == {"detected": 0, "entries": []} and scanner.message == "No cards detected"


def test_scan_page_endpoint(client, monkeypatch):
    img, _ = _page(4)
    ok, jpg_bytes = cv2.imencode(".jpg", img)
    assert ok
    seen = {}
    monkeypatch.setattr(client.app.state.scanner, "process_page", lambda i, name="": seen.update(shape=i.shape) or {"detected": 9, "entries": []})
    assert client.post("/api/scan/page", content=jpg_bytes.tobytes()).json()["detected"] == 9 and seen["shape"][2] == 3
    assert client.post("/api/scan/page", content=b"").status_code == 400
    assert client.post("/api/scan/page", content=b"not an image").status_code == 415
    assert client.post("/api/scan/mode", json={"page": True}).json()["page_mode"] is True
    assert client.app.state.scanner.page_mode and client.get("/api/scan/state").json()["page_mode"] is True


@needs_tess
@pytest.mark.skipif(sys.platform != "win32", reason="OCR of the synthetic cards is Tesseract-build dependent")
def test_binder_cells_are_read_or_flagged_never_confidently_wrong(db):
    """Each card of a page is read right, or comes out with low confidence / no candidate: never a confident wrong printing."""
    ident = identify.Identifier(db)
    img, cells = _page(4)
    quads = vision.find_cards(img)
    right = wrong_confident = 0
    for c, q in zip(cells, quads):
        res = ident.identify(vision.warp_card(img, q))
        top = res["candidates"][0]["id"] if res["candidates"] else None
        right += top == Path(c["path"]).stem
        wrong_confident += top not in (None, Path(c["path"]).stem) and res["confidence"] == "high"
    print(f"cells read right: {right}/{len(cells)}; confidently wrong: {wrong_confident}")
    assert wrong_confident == 0 and right >= 3  # OCR only (no visual index in the fixtures) on a synthetic page


def test_live_camera_rereading_the_same_card_does_not_add_a_copy(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    ids = [r[0] for r in db.execute("SELECT id FROM cards ORDER BY id LIMIT 2")]
    res = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False}, "candidates": [], "confidence": "high"}
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    img = np.zeros((880, 630, 3), np.uint8)
    for list_mode in (True, False):
        scanner = session.Scanner(db, tmp_path / str(list_mode))
        scanner.list_mode = list_mode
        items = lambda: scanner.reads if list_mode else scanner.pending  # noqa: E731

        def read(card_id, live=True):
            res["candidates"] = [{"id": card_id, "finishes": '["nonfoil", "foil"]'}]
            scanner.process(img, "c", warped=True, live=live)

        read(ids[0])
        beeps = scanner.beep
        assert scanner.notice == ""
        read(ids[0])
        read(ids[0])                                   # still on the stand: nothing changes, and the UI is told why
        assert "press N" in scanner.state()["notice"]
        assert [r["qty"] for r in items()] == [1] and scanner.beep == beeps
        assert len(list(scanner.dir.glob("*.jpg"))) == 1
        read(ids[1])                                   # a clear swap still opens an entry
        assert scanner.notice == ""
        read(ids[0])                                   # and going back too
        assert [r["qty"] for r in items()] == [1, 1, 1]
        read(ids[0], live=False)                       # photos and folders still add up
        assert [r["qty"] for r in items()] == [1, 1, 2]
        scanner.split_next = True
        read(ids[0])                                   # the foil of the same card is a new entry
        assert len(items()) == 4


def test_live_unreadable_card_on_the_stand_does_not_repeat(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    res = {"ocr": {"name": "", "name_match": 0, "number": None, "set": None, "rotated": False}, "candidates": [], "confidence": "none"}
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(res)))
    img = np.zeros((880, 630, 3), np.uint8)
    for list_mode in (True, False):
        scanner = session.Scanner(db, tmp_path / str(list_mode))
        scanner.list_mode = list_mode
        for _ in range(3):
            scanner.process(img, "c", warped=True, live=True)
        assert len(scanner.reads if list_mode else scanner.pending) == 1


def test_camera_waits_0_3_s_for_a_still_card(db, tmp_path):
    from scrybinder.scan import session
    scanner = session.Scanner(db, tmp_path)
    s = vision.Stability(hold=scanner.hold)
    q = np.array([[100, 100], [400, 100], [400, 520], [100, 520]], np.float32)
    assert not s.update(q, 0.0) and not s.update(q, 0.25)  # too soon
    assert s.update(q, 0.31)                               # still for 0.3 s: fires

def test_identify_reads_the_bottom_strip_once_alongside_the_name(db, monkeypatch):
    from scrybinder.scan import identify as ident_mod
    name = db.execute("SELECT name FROM cards WHERE digital=0 AND LENGTH(name) > 6 LIMIT 1").fetchone()[0]
    calls = []

    def fake_bottom(card):
        calls.append(card)
        return {"numbers": [], "tokens": [], "text": ""}

    monkeypatch.setattr(ident_mod, "read_bottom", fake_bottom)
    monkeypatch.setattr(ident_mod, "name_reads", lambda card: iter([(name, 95.0)]))
    res = ident_mod.Identifier(db, use_visual=False).identify(np.zeros((880, 630, 3), np.uint8))
    assert len(calls) == 1 and res["candidates"] and res["candidates"][0]["name"] == name


# --- overlapping cards (fans and columns): found by their titles ---

def _fixture_cards(n=3):
    meta = json.loads((CARDS / "index.json").read_text(encoding="utf-8"))
    return [m for m in meta if (CARDS / f"{m['id']}.jpg").exists() and m["layout"] == "normal"][:n]


def _fan_photo(cards, step=0.4):
    """Cards laid in a row, each covering the one before it, on a dark table; returns the photo and the (x, y) of each title."""
    cw, ch = 400, 560
    img = np.full((760, 120 + int(step * cw * len(cards)) + cw + 60, 3), (45, 52, 60), np.uint8)
    titles = []
    for i, m in enumerate(cards):
        x, y = 60 + int(i * step * cw), 100
        img[y:y + ch, x:x + cw] = cv2.resize(cv2.imread(str(CARDS / f"{m['id']}.jpg")), (cw, ch))
        titles.append((x + 0.09 * cw, y + 0.06 * ch))
    return img, titles


@pytest.fixture
def local_images(monkeypatch):
    from scrybinder.scan import overlap
    monkeypatch.setattr(overlap, "_img_file", lambda cid, face=0: CARDS / f"{cid}.jpg")
    monkeypatch.setattr(overlap, "card_height", lambda img: 560.0)
    overlap._feats.clear()
    return overlap


def test_title_names_take_the_beginning_of_a_name_and_not_a_sentence(db):
    ident = identify.Identifier(db)
    m = _fixture_cards(1)[0]
    name = m["name"]
    whole = ident.title_names(name)
    assert whole and whole[0][0] == name and whole[0][2] == 1.0
    part = ident.title_names(name[:len(name) - 3])
    assert part and part[0][0] == name and part[0][2] < 1.0
    assert ident.title_names(f"when {name} enters the battlefield, you may") == []  # a sentence that contains a name
    assert ident.title_names("abc") == []


def test_type_lines_are_not_titles():
    from scrybinder.scan import overlap
    for t in ("Creature \u2014 Human Wizard", "Legendary Creature -", "Instant", "Artifact Creature", "Enchantment — Aura", "Sorcery"):
        assert overlap.TYPE_LINE.match(t), t
    for t in ("Creature Bond", "Battle Screech", "Artifact Mutation", "Land Tax", "Instant Ramen"):
        assert not overlap.TYPE_LINE.match(t), t


def test_a_card_is_found_by_its_title_and_its_printing_confirmed_by_the_picture(db, local_images):
    cards = _fixture_cards(3)
    img, titles = _fan_photo(cards)
    lines = [(m["name"], x, y, 180.0, 24.0) for m, (x, y) in zip(cards, titles)]
    found = local_images.find_cards(img, identify.Identifier(db), lines=lines)
    assert [f["name"] for f in found] == [m["name"] for m in cards]
    for f, m in zip(found, cards):
        assert f["prints"][0]["id"] == m["id"] and f["inliers"] >= local_images.MIN_INLIERS  # the covered ones too
    assert any(f["inliers"] >= local_images.STRONG_INLIERS for f in found)


def test_text_that_is_not_a_title_is_left_out(db, local_images):
    cards = _fixture_cards(2)
    img, titles = _fan_photo(cards)
    lines = [(cards[0]["name"], *titles[0], 90.0, 12.0),
             ("Creature \u2014 Human Wizard", titles[1][0], titles[1][1], 90.0, 12.0),                  # a type line
             (f"when {cards[1]['name']} enters", 70.0, 300.0, 90.0, 12.0),                          # a sentence
             (cards[1]["name"], 400.0, 450.0, 90.0, 12.0)]                                          # a name on the table: no card there
    found = local_images.find_cards(img, identify.Identifier(db), lines=lines)
    assert [f["name"] for f in found if f["verified"]] == [cards[0]["name"]]


def test_a_card_read_by_two_lines_counts_once(db, local_images):
    cards = _fixture_cards(1)
    img, titles = _fan_photo(cards)
    x, y = titles[0]
    lines = [(cards[0]["name"], x, y, 90.0, 12.0), (cards[0]["name"], x + 8, y + 3, 90.0, 12.0)]
    assert len(local_images.find_cards(img, identify.Identifier(db), lines=lines)) == 1


def test_rules_text_that_happens_to_be_a_name_is_not_a_card():
    from scrybinder.scan import overlap
    assert overlap.accept(True, "Sacrifice", 80.0, 0.3, 0)                 # confirmed by the picture
    assert overlap.accept(False, "Shambling Ghast", 100.0, 1.0, 6)         # a clean, whole, two-word title
    assert overlap.accept(False, "Miscast", 100.0, 1.0, 26)                # one word, but the picture agrees a little
    assert not overlap.accept(False, "Sacrifice", 89.0, 1.0, 7)            # a misread single word with no support (seen on a real photo)
    assert not overlap.accept(False, "Counters", 100.0, 1.0, 3)            # a single word with no support
    assert not overlap.accept(False, "Shambling Ghast", 90.0, 1.0, 3)      # misread and unsupported
    assert not overlap.accept(False, "Shambling Ghast", 100.0, 0.5, 20)    # half a title and not confirmed


def test_a_degenerate_placement_is_not_a_match(local_images):
    """RANSAC can 'explain' the points by collapsing them onto one: that must count for nothing."""
    from scrybinder.scan import overlap
    cid = _fixture_cards(1)[0]["id"]
    gray = cv2.cvtColor(cv2.imread(str(CARDS / f"{cid}.jpg")), cv2.COLOR_BGR2GRAY)
    kq, dq = cv2.SIFT_create(nfeatures=1500).detectAndCompute(cv2.resize(gray, (630, 880)), None)
    n, M = overlap._match(kq, dq, cid)
    assert n >= overlap.STRONG_INLIERS and 0.4 < np.hypot(M[0, 0], M[1, 0]) < 5
    other = _fixture_cards(2)[1]["id"]
    assert overlap._match(kq, dq, other)[0] < n / 2  # another card shares the frame and text layout: it matches a little, never as well


def test_process_overlap_adds_one_entry_per_card(db, tmp_path, monkeypatch):
    from scrybinder.scan import overlap, session
    monkeypatch.setattr(overlap, "available", lambda: True)
    cards = _fixture_cards(2)
    ident_prints = identify.Identifier(db).prints([cards[0]["name"]])
    found = [{"name": cards[0]["name"], "text": cards[0]["name"], "similarity": 100.0, "whole": 1.0, "x": 10.0, "y": 10.0, "inliers": 55,
              "verified": True, "geo": True, "box": (0, 0, 60, 80), "prints": ident_prints}]
    monkeypatch.setattr(overlap, "find_cards", lambda img, ident: found)
    scanner = session.Scanner(db, tmp_path)
    scanner.list_mode = True
    out = scanner.process_overlap(np.zeros((200, 200, 3), np.uint8), "fan.jpg")
    assert out["detected"] == 1 and out["boxes"][0]["name"] == cards[0]["name"] and out["boxes"][0]["confidence"] == "high"
    assert scanner.reads[0]["scryfall_id"] == ident_prints[0]["id"] and scanner.message == "1 cards detected"
    monkeypatch.setattr(overlap, "find_cards", lambda img, ident: [])
    assert scanner.process_overlap(np.zeros((200, 200, 3), np.uint8))["detected"] == 0 and scanner.message == "No cards detected"
    monkeypatch.setattr(overlap, "available", lambda: False)
    assert scanner.process_overlap(np.zeros((200, 200, 3), np.uint8))["detected"] == 0 and "Windows" in scanner.message


def test_scan_overlap_endpoint(client, monkeypatch):
    ok, jpg = cv2.imencode(".jpg", np.full((200, 300, 3), 80, np.uint8))
    assert ok
    monkeypatch.setattr(client.app.state.scanner, "process_overlap", lambda i, name="": {"detected": 3, "entries": [], "boxes": []})
    assert client.post("/api/scan/overlap", content=jpg.tobytes()).json()["detected"] == 3
    assert client.post("/api/scan/overlap", content=b"").status_code == 400
    assert client.post("/api/scan/mode", json={"overlap": True}).json()["overlap_mode"] is True
    assert client.get("/api/scan/state").json()["overlap_mode"] is True


def test_clean_cell_count_reaches_the_page_threshold_on_binder_pages():
    for seed in (1, 2, 3):
        for kw in ({}, {"gap": 0.02}, {"glare": True}, {"occupied": [True, False, True, True, False, True, True, True, False]}):
            assert vision.clean_cell_count(_page(seed, **kw)[0]) >= vision.MIN_PAGE_CELLS, (seed, kw)
    assert vision.clean_cell_count(np.full((900, 1200, 3), 40, np.uint8)) == 0


def test_process_auto_tells_the_photo_kinds_apart(db, tmp_path, monkeypatch):
    from scrybinder.scan import session
    scanner = session.Scanner(db, tmp_path)
    fan = {"out": {"detected": 5, "entries": []}}
    monkeypatch.setattr(scanner, "process_overlap", lambda i, label="", min_cards=0: fan["out"])
    monkeypatch.setattr(scanner, "process_page", lambda i, label="": {"detected": 9, "entries": []})
    monkeypatch.setattr(scanner, "process", lambda i, label="": {"id": 1})
    monkeypatch.setattr(session.overlap, "available", lambda: True)
    img, _ = _page(4)
    assert scanner.process_auto(img)["kind"] == "page"                                     # whole outlines of many cards
    monkeypatch.setattr(session, "clean_cell_count", lambda i: 3)
    assert scanner.process_auto(img)["kind"] == "overlap"                                  # few outlines and several titles
    fan["out"] = None                                                                      # ... but not two titles: one card
    assert scanner.process_auto(img) == {"detected": 1, "entries": [{"id": 1}], "kind": "photo"}
    fan["out"] = {"detected": 5, "entries": []}
    monkeypatch.setattr(session.overlap, "available", lambda: False)                      # no text recognition: titles cannot be read
    assert scanner.process_auto(img)["kind"] == "photo"
    monkeypatch.setattr(session, "clean_cell_count", lambda i: 0)
    assert scanner.process_auto(img)["kind"] == "photo"
