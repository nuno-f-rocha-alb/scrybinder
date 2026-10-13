import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from scrybinder import db as dbmod, scryfall  # noqa: E402
from scrybinder.scan import embed, identify, index, visual  # noqa: E402

CARDS = Path(__file__).parent / "fixtures" / "cards"
META = json.loads((CARDS / "index.json").read_text(encoding="utf-8"))[:6]


class FakeEmb(embed.Embedder):
    """Vector = 8x8 grey thumbnail minus its mean (no torch): identical images → cosine 1."""
    dim = 64

    def __init__(self):
        super().__init__("fake/model")
        self.calls = 0

    def embed_raw(self, imgs, size, batch=64, progress=None):
        self.calls += len(imgs)
        v = np.stack([cv2.resize(cv2.cvtColor(i, cv2.COLOR_BGR2GRAY), (8, 8), interpolation=cv2.INTER_AREA).ravel()
                      .astype(np.float32) for i in imgs])
        if progress and imgs and progress(len(imgs), len(imgs)):
            raise embed.Stopped()
        return embed._unit(v - v.mean(1, keepdims=True))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "DATA_DIR", tmp_path)
    monkeypatch.setattr(index, "SHARD", 4)
    monkeypatch.setattr(visual, "DATA_DIR", tmp_path)
    (tmp_path / "images" / "normal").mkdir(parents=True)
    db = dbmod.connect(tmp_path / "t.db")
    with db:
        for i, m in enumerate(META):
            db.execute("INSERT INTO cards (id, oracle_id, name, set_code, set_name, collector_number, released_at, frame,"
                       " lang, digital, illustration_id, image_normal, layout) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,'normal')",
                       (m["id"], f"o{i}", m["name"], m["set_code"], m["set_code"], m["collector_number"], "2020-01-01",
                        m["frame"], "en", f"ill{i}", "http://invalid/x.jpg"))
            db.execute("INSERT INTO card_faces VALUES (?,0,?,?)", (m["id"], f"ill{i}", "http://invalid/x.jpg"))
            shutil.copy(CARDS / f"{m['id']}.jpg", tmp_path / "images" / "normal" / f"{m['id']}.jpg")
    return tmp_path, db


def test_migration_and_faces(tmp_path, bulk_file):
    db = dbmod.connect(tmp_path / "t.db")
    cols = {r[1] for r in db.execute("PRAGMA table_info(cards)")}
    assert {"illustration_id", "image_status"} <= cols
    assert "topk_json" in {r[1] for r in db.execute("PRAGMA table_info(scan_log)")}
    scryfall.import_bulk(db, bulk_file)
    assert db.execute("SELECT COUNT(*) FROM card_faces WHERE card_id='dfc-1'").fetchone()[0] == 1
    dbmod.connect(tmp_path / "t.db")  # idempotent migration


def test_build_resume_and_search(env):
    root, db = env
    emb = FakeEmb()
    d = index.index_dir(emb, root / "index")
    assert index.add_rows(db, d) == 6 and index.add_rows(db, d) == 0  # idempotente
    assert index.build(emb, d)["indexed"] == 6 and index.status(d)["done_shards"] == 2
    n = emb.calls
    index.build(emb, d)
    assert emb.calls == n  # tudo completo: nada refeito
    (d / "card_00001.npy").unlink()  # incomplete shard → only that one is rebuilt
    index.build(emb, d)
    assert emb.calls == n + 2 * 2 and index.status(d)["indexed"] == 6
    ix = index.load(emb, root / "index")
    img = embed.normalize_card(cv2.imread(str(CARDS / f"{META[4]['id']}.jpg")))
    cv, av = emb.query(img)
    art, card = ix.scores(cv, av)
    assert ix.rows[int(art.argmax())]["card_id"] == META[4]["id"] and card.max() == pytest.approx(1.0, abs=1e-2)


def test_prep_change_changes_dir(monkeypatch, tmp_path):
    a = index.index_dir(FakeEmb(), tmp_path)
    monkeypatch.setitem(embed.BOXES, "2015", (0.1, 0.1, 0.9, 0.5))
    assert index.index_dir(FakeEmb(), tmp_path) != a  # the old index is never reused


def test_visual_ranking_and_degraded(env, monkeypatch):
    root, db = env
    emb = FakeEmb()
    d = index.index_dir(emb, root / "index")
    index.add_rows(db, d)
    index.build(emb, d)
    monkeypatch.setattr(index, "load", lambda e, r=None: index.Index(d))
    ident = identify.Identifier(db)
    monkeypatch.setattr(visual.Embedder, "__init__", lambda self, *a: FakeEmb.__init__(self))
    monkeypatch.setattr(visual.Embedder, "embed_raw", FakeEmb.embed_raw)
    monkeypatch.setattr(visual.Embedder, "dim", 64)
    vis = visual.Visual(emb, index.Index(d))
    ident._vis, ident._vis_tried = vis, True
    img = embed.normalize_card(cv2.imread(str(CARDS / f"{META[2]['id']}.jpg")))
    scores, top_art, flipped = vis.best_orientation(img, visual.weights(), try_rotated=True)
    assert flipped is None and top_art == pytest.approx(1.0, abs=1e-2) and max(scores, key=lambda k: scores[k][0]) == META[2]["id"]
    # no index / no torch → OCR-only mode, no error
    assert identify.Identifier(db, use_visual=False).vis() is None
    monkeypatch.setattr(visual.Visual, "try_open", classmethod(lambda cls, emb=None, db=None: None))
    assert identify.Identifier(db).vis() is None


def test_rotated_query_detected(env, monkeypatch):
    root, db = env
    emb = FakeEmb()
    d = index.index_dir(emb, root / "index")
    index.add_rows(db, d)
    index.build(emb, d)
    vis = visual.Visual(emb, index.Index(d))
    img = embed.normalize_card(cv2.imread(str(CARDS / f"{META[1]['id']}.jpg")))
    up = cv2.rotate(img, cv2.ROTATE_180)
    scores, _, flipped = vis.best_orientation(up, visual.weights(), try_rotated=True)
    assert flipped == cv2.ROTATE_180 and max(scores, key=lambda k: scores[k][0]) == META[1]["id"]


def test_topk_logged(env):
    from scrybinder.scan import session
    item = {"confidence": "high", "visual": {"top_art": 0.9}, "candidates": [{"id": "a", "total": 1.2, "art": .9}]}
    assert json.loads(session._topk(item))["top"][0]["id"] == "a"


def _built(env):
    root, db = env
    emb = FakeEmb()
    d = index.index_dir(emb, root / "index")
    index.add_rows(db, d)
    index.build(emb, d)
    return emb, d, db


def test_split_layout_has_no_art_match_and_null_ill_isolated(env):
    root, db = env
    with db:
        db.execute("UPDATE cards SET layout='split' WHERE id=?", (META[2]["id"],))
        db.execute("UPDATE card_faces SET illustration_id=NULL WHERE card_id IN (?,?)", (META[0]["id"], META[1]["id"]))
        db.execute("UPDATE cards SET illustration_id=NULL WHERE id IN (?,?)", (META[0]["id"], META[1]["id"]))
    emb, d, db = _built(env)
    vis = visual.Visual(emb, index.Index(d), db)
    assert all(len(v) == 1 for k, v in vis.by_ill().items() if k.startswith("row"))  # no illustration id: every row is its own
    img = embed.normalize_card(cv2.imread(str(CARDS / f"{META[2]['id']}.jpg")))
    scores, _ = vis.query(img, visual.weights())
    assert META[2]["id"] not in scores or scores[META[2]["id"]][0] < 0.99  # a split card never wins by art


def test_failed_downloads_retried_and_dry_run(env, monkeypatch):
    root, db = env
    emb = FakeEmb()
    d = index.index_dir(emb, root / "index")
    assert index.add_rows(db, d, dry_run=True) == 6 and index.status(d)["rows"] == 0  # dry-run does not write
    index.add_rows(db, d)
    (root / "images" / "normal" / f"{META[0]['id']}.jpg").rename(root / "images" / "normal" / "x.bak")
    assert index.build(emb, d)["failed_downloads"] == 1  # invalid URL: fails
    (root / "images" / "normal" / "x.bak").rename(root / "images" / "normal" / f"{META[0]['id']}.jpg")
    assert index.build(emb, d)["failed_downloads"] == 0  # shard with failures rebuilt
    assert index.Index(d).card[0].any()


def test_promo_prints_score_like_parent_when_visual_on():
    b = identify.parse_bottom("20/276 R\nSOS • EN")
    normal = {"set_code": "sos", "collector_number": "20"}
    promo = {"set_code": "psos", "collector_number": "20p"}
    assert identify.Identifier._score(normal, b) > identify.Identifier._score(promo, b)  # OCR-only: the regular one wins
    parents = {"sos"}
    assert identify.Identifier._score(normal, b, parents) == identify.Identifier._score(promo, b, parents)  # with visual: tie


def test_find_card_loose_fallback_on_broken_mask():
    import numpy as np
    from scrybinder.scan import vision
    frame = np.full((720, 1280, 3), 200, np.uint8)
    cv2.rectangle(frame, (500, 150), (780, 570), (30, 30, 30), -1)
    frame[150:300, 500:640] = 200  # reflexo: parte da carta parece fundo, o contorno fica incompleto
    q = vision.find_card(frame)
    assert q is not None and 250 < (q[:, 0].max() - q[:, 0].min()) < 330


def test_import_corrections_and_resolve(env, monkeypatch, tmp_path):
    from scrybinder import evalcli
    root, db = env
    m = META[0]
    monkeypatch.setattr(evalcli, "TRUTH", tmp_path / "truth.json")
    assert evalcli._resolve(db, f"{m['name']} {m['set_code']} #{m['collector_number']}") == m["id"]
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"f": "a.jpg", "pred": "X", "bad": False}, {"f": "b.jpg", "pred": "Y", "bad": True, "truth_id": None,
                 "text": f"{m['name']} {m['set_code']} {m['collector_number']}"}, {"f": "c.jpg", "pred": None, "bad": False}]))
    evalcli.import_corrections(db, p)
    truth = json.loads((tmp_path / "truth.json").read_text())
    assert truth == {"a.jpg": "X", "b.jpg": m["id"]}  # no prediction and no correction: left out of the truth
