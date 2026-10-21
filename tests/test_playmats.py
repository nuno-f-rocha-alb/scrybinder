import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scrybinder import db as dbmod, playmats, scryfall
from scrybinder.api import create_app


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)
    d = tmp_path / "playmats"
    d.mkdir()
    Image.new("RGB", (1600, 900), (10, 80, 40)).save(d / "Green Mat.png")
    Image.new("RGB", (800, 800), (90, 10, 10)).save(d / "red.JPG")
    (d / "notes.txt").write_text("not an image")
    (d / "broken.png").write_bytes(b"not a png")
    (d / "sub").mkdir()
    (d / "sub" / "deep.png").write_bytes(b"x")
    return tmp_path


def test_listing_keeps_only_images_of_the_folder(base):
    assert [f["name"] for f in playmats.files()] == ["broken.png", "Green Mat.png", "red.JPG"]
    assert playmats.file_path("red.JPG") == base / "playmats" / "red.JPG"
    for bad in ("../t.db", "sub/deep.png", "notes.txt", "..\\x.png", "nope.png"):
        assert playmats.file_path(bad) is None


def test_size_cap(base, monkeypatch):
    monkeypatch.setattr(playmats, "MAX_BYTES", 100)
    assert [f["name"] for f in playmats.files()] == ["broken.png"]  # the real images are over the cap


def test_thumbnail_is_small_cached_and_rebuilt_when_the_file_changes(base):
    t = playmats.thumb_path("Green Mat.png")
    with Image.open(t) as im:
        assert max(im.size) == 480 and im.format == "JPEG"
    assert playmats.thumb_path("Green Mat.png") == t
    Image.new("RGB", (1600, 900), (0, 0, 255)).save(base / "playmats" / "Green Mat.png")
    t2 = playmats.thumb_path("Green Mat.png")
    assert t2 != t and not t.exists()  # the old version is removed
    assert playmats.thumb_path("broken.png") is None  # not really an image


def test_setting_is_validated_and_saved(db, base):
    assert playmats.get(db)["kind"] == "none"
    assert playmats.put(db, {"kind": "file", "name": "red.JPG", "dim": 0.5}) == {"kind": "file", "dim": 0.5, "blur": 4, "name": "red.JPG"}
    assert playmats.get(db)["name"] == "red.JPG"
    sid = db.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    assert playmats.put(db, {"kind": "card", "card_id": sid, "blur": 8})["card_id"] == sid
    for bad in ({"kind": "x"}, {"kind": "file", "name": "../t.db"}, {"kind": "card", "card_id": "nope"}, {"kind": "none", "dim": 0.95},
                {"kind": "none", "blur": -1}, {"kind": "none", "dim": True}):
        with pytest.raises(ValueError):
            playmats.put(db, bad)
    assert playmats.get(db)["kind"] == "card"  # a refused change leaves the setting as it was


def test_art_is_fetched_once(db, base, monkeypatch):
    sid = db.execute("SELECT id FROM cards WHERE id != 'dfc-1' LIMIT 1").fetchone()[0]
    db.execute("UPDATE cards SET image_normal='https://cards.scryfall.io/normal/front/a/b/x.jpg' WHERE id=?", (sid,))
    calls = []

    def fake(url, tries=3):
        calls.append(url)
        return httpx.Response(200, content=b"JPEGDATA", request=httpx.Request("GET", url))
    monkeypatch.setattr(scryfall, "_get_retry", fake)
    p = playmats.art_path(db, sid)
    assert p.read_bytes() == b"JPEGDATA" and calls == ["https://cards.scryfall.io/art_crop/front/a/b/x.jpg"]
    assert playmats.art_path(db, sid) == p and len(calls) == 1
    assert playmats.art_path(db, "../x") is None and playmats.art_path(db, "no-such-card") is None


def test_routes(db, base):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    got = c.get("/api/playmat").json()
    assert [f["name"] for f in got["files"]][1] == "Green Mat.png" and got["current"]["kind"] == "none"
    assert c.put("/api/playmat", json={"kind": "file", "name": "red.JPG"}).status_code == 200
    assert c.put("/api/playmat", json={"kind": "file", "name": "../t.db"}).status_code == 422
    assert c.get("/api/playmat/file/red.JPG").status_code == 200
    assert c.get("/api/playmat/file/red.JPG?thumb=true").headers["content-type"] == "image/jpeg"
    assert c.get("/api/playmat/file/notes.txt").status_code == 404
    assert c.get("/api/playmat/file/..%2Ft.db").status_code == 404
    assert c.get("/api/playmat/art/nope").status_code == 404
