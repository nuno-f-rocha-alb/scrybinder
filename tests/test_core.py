import csv
import json
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, formats, scryfall
from scrybinder.api import create_app

CSV = (Path(__file__).parent / "fixtures" / "manabox_sample.csv").read_text(encoding="utf-8-sig")
TOKEN = "tok"


def test_bulk_import_fields_and_fts(db):
    assert db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] > 100
    dfc = db.execute("SELECT * FROM cards WHERE id='dfc-1'").fetchone()
    assert dfc["image_normal"] == "f-n" and dfc["eur"] == 0.10  # imagem da face 0
    hits = db.execute("SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?", (collection._fts("delver"),)).fetchall()
    assert len(hits) == 1
    assert collection._fts('a"b') == '"a"* "b"*'  # no FTS syntax injection


def test_bulk_import_jsonl_gz(tmp_path, bulk_file):
    import gzip, json
    from scrybinder import db as dbmod
    gz = tmp_path / "default-cards.jsonl.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.writelines(json.dumps(c) + "\n" for c in json.loads(bulk_file.read_text(encoding="utf-8")))
    d = dbmod.connect(tmp_path / "g.db")
    assert scryfall.import_bulk(d, gz) == d.execute("SELECT COUNT(*) FROM cards").fetchone()[0] > 100


def test_reimport_keeps_collection(db, bulk_file):
    collection.add(db, scryfall_id="dfc-1")
    scryfall.import_bulk(db, bulk_file)
    assert db.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 1


def test_add_merges_and_locations_split(db):
    a = collection.add(db, scryfall_id="dfc-1", quantity=1, location="A")
    assert collection.add(db, scryfall_id="dfc-1", quantity=2, location="A") == a
    b = collection.add(db, scryfall_id="dfc-1", quantity=1, location="B")  # mesma carta, outra caixa
    assert b != a
    assert collection.search(db)["total_cards"] == 4
    assert collection.add(db, scryfall_id="dfc-1", finish="foil", location="A") not in (a, b)
    with pytest.raises(ValueError):
        collection.add(db, scryfall_id="dfc-1", quantity=0)


def test_move_merges_and_partial(db):
    a = collection.add(db, scryfall_id="dfc-1", quantity=3, location="A")
    b = collection.add(db, scryfall_id="dfc-1", quantity=1, location="B")
    assert collection.move(db, a, "B", 2) == b  # parcial junta no destino
    q = {r["location"]: r["quantity"] for r in collection.search(db)["rows"]}
    assert q == {"A": 1, "B": 3}
    assert collection.move(db, a, "B") == b  # total: a linha desaparece
    assert [r["location"] for r in collection.search(db)["rows"]] == ["B"]
    with pytest.raises(ValueError):
        collection.move(db, b, "C", 99)


def test_update_collision_merges(db):
    a = collection.add(db, scryfall_id="dfc-1", quantity=1, condition="NM")
    b = collection.add(db, scryfall_id="dfc-1", quantity=2, condition="LP")
    assert collection.update(db, b, condition="NM") == a
    assert collection.search(db)["rows"][0]["quantity"] == 3


def test_search_filters_and_value(db):
    collection.add(db, scryfall_id="dfc-1", quantity=2, location="A")
    r = collection.search(db, q="delv", location="A")
    assert r["total_cards"] == 2 and r["total_value"] == 0.20
    assert collection.search(db, q="nada")["rows"] == []
    assert collection.search(db, location="")["rows"] == []


def test_manabox_roundtrip_real_csv(db):
    res = formats.import_manabox(db, CSV, location="Red Boxes")
    assert res["imported"] == 420 and res["cards"] == 468 and not res["skipped"]
    assert collection.search(db)["total_cards"] == 468
    out = {r["Scryfall ID"] + r["Foil"] + r["Language"]: r
           for r in csv.DictReader(io.StringIO(formats.export_manabox(db)))}
    src = list(csv.DictReader(io.StringIO(CSV)))
    assert len(out) == len({r["Scryfall ID"] + r["Foil"] + r["Language"] for r in src})
    for r in src:  # round trip without losing any comparable field
        o = out[r["Scryfall ID"] + r["Foil"] + r["Language"]]
        for k in ("Name", "Set code", "Collector number", "Foil", "Condition", "Language", "Purchase price",
                  "Purchase price currency", "ManaBox ID", "Misprint", "Altered", "Signed", "Proxy", "Added"):
            assert o[k] == r[k], (k, o[k], r[k])


def test_manabox_unknown_ids_and_bad_file(db):
    res = formats.import_manabox(db, "Name,Quantity,Scryfall ID\nX,1,nao-existe\n")
    assert res["imported"] == 0 and len(res["skipped"]) == 1
    with pytest.raises(ValueError):
        formats.import_manabox(db, "a,b\n1,2\n")


def test_exports_reference(db):
    collection.add(db, scryfall_id="dfc-1", quantity=2, finish="foil", condition="LP", language="pt",
                   location="Box 1", purchase_price=0.5)
    assert formats.export_moxfield(db).splitlines()[1].split(",")[:7] == [
        "2", "0", "Delver of Secrets // Insectile Aberration", "isd", "Good (Lightly Played)", "Portuguese", "foil"]
    cm = list(csv.DictReader(io.StringIO(formats.export_cardmarket(db))))[0]
    assert (cm["cardmarketId"], cm["quantity"], cm["condition"], cm["language"], cm["isFoil"], cm["price"]) == (
        "1", "2", "EX", "8", "true", "")  # no eur_foil in the test bulk -> empty price, not invented
    assert formats.export_manabox(db, location="outra").count("\n") == 1  # header only


@pytest.fixture
def client(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    return c


def test_api_security(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"host": "evil.com"}).status_code == 403
    assert client.get(f"/api/status?t={TOKEN}").status_code == 200  # define cookie
    assert client.get("/api/status").status_code == 200
    r = client.post("/api/collection", json={"scryfall_id": "dfc-1"}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_api_flow(client):
    client.get(f"/api/status?t={TOKEN}")
    s = client.get("/api/cards/search", params={"q": "delver"}).json()
    assert s[0]["name"].startswith("Delver")
    assert client.get("/api/cards/prints", params={"oracle_id": s[0]["oracle_id"]}).json()[0]["id"] == "dfc-1"
    assert client.get("/api/cards/prints", params={"oracle_id": s[0]["oracle_id"]}).json()[0]["owned"] == 0
    rid = client.post("/api/collection", json={"scryfall_id": "dfc-1", "quantity": 2, "location": "A"}).json()["id"]
    assert client.get("/api/cards/prints", params={"oracle_id": s[0]["oracle_id"]}).json()[0]["owned"] == 2  # the copies you own
    assert client.get("/api/collection").json()["rows"][0]["oracle_id"] == s[0]["oracle_id"]  # the menus add a row's card to a deck
    assert client.get("/api/cards/prints", params={"oracle_id": s[0]["oracle_id"]}).json()[0]["free"] == 2  # none held by a deck
    assert client.post("/api/collection", json={"scryfall_id": "nao"}).status_code == 422
    assert client.patch(f"/api/collection/{rid}", json={"notes": "x"}).status_code == 200
    assert client.post(f"/api/collection/{rid}/move", json={"location": "B", "quantity": 1}).status_code == 200
    assert {x["location"] for x in client.get("/api/locations").json()} == {"A", "B"}
    assert client.get("/api/export/moxfield").status_code == 200
    assert client.get("/api/export/nope").status_code == 404
    imp = client.post("/api/import/manabox?location=Z", content=CSV.encode()).json()
    assert imp["cards"] == 468
    assert client.delete(f"/api/collection/{rid}").status_code == 200


def test_punctuation_query_and_empty_location(client, db):
    client.get(f"/api/status?t={TOKEN}")
    assert client.get("/api/cards/search", params={"q": "!!"}).json() == []
    collection.add(db, scryfall_id="dfc-1", location="")
    collection.add(db, scryfall_id="dfc-1", location="A")
    assert client.get("/api/collection", params={"q": "-"}).status_code == 200
    only = client.get("/api/collection?location=").json()["rows"]
    assert [r["location"] for r in only] == [""]  # '' really filters: no location


def test_image_id_traversal_rejected(db, tmp_path, monkeypatch):
    monkeypatch.setattr(scryfall, "DATA_DIR", tmp_path)
    (tmp_path / "secret.jpg").write_bytes(b"x")
    for bad in (r"..\..\secret", "../secret", "a/b", ""):
        assert scryfall.image_path(db, bad) is None


def test_download_bulk_both_api_shapes(tmp_path, monkeypatch):
    import httpx
    real = httpx.Client

    def make(shape):
        def handler(req):
            if req.url.path.startswith("/bulk-data"):
                return httpx.Response(200, json=shape)
            return httpx.Response(200, content=b"data")
        monkeypatch.setattr(scryfall.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    make({"jsonl_download_uri": "https://data.scryfall.io/x.jsonl.gz", "compressed_size": 4})
    assert scryfall.download_bulk(tmp_path / "a").name == "default-cards.jsonl.gz"
    make({"download_uri": "https://data.scryfall.io/x.json", "size": 4})  # formato antigo
    assert scryfall.download_bulk(tmp_path / "b").name == "default-cards.json"


def test_set_progress(db):
    a = db.execute("SELECT id, set_code FROM cards WHERE set_code='eoe' LIMIT 2").fetchall()
    total = db.execute("SELECT COUNT(*) FROM cards WHERE set_code='eoe'").fetchone()[0]
    collection.add(db, scryfall_id=a[0]["id"], quantity=2, location="A")
    collection.add(db, scryfall_id=a[0]["id"], quantity=1, location="B")  # same printing: counts once
    collection.add(db, scryfall_id=a[1]["id"], quantity=1, location="B")
    s = {r["code"]: r for r in collection.set_progress(db)}
    assert list(s) == ["eoe"] and s["eoe"]["owned"] == 2 and s["eoe"]["copies"] == 4 and s["eoe"]["total"] == total
    assert s["eoe"]["percent"] == round(100 * 2 / total, 1)
    assert collection.set_progress(db, location="A")[0]["owned"] == 1
    assert collection.set_progress(db, location="Z") == []
    assert len(collection.set_progress(db, hide_empty=False)) > 1  # includes sets without cards
    assert collection.set_progress(db, q="edge")[0]["code"] == "eoe"


def test_sets_api_and_icon_id(client, db, monkeypatch):
    monkeypatch.setattr(scryfall, "fetch_sets", lambda d: (_ for _ in ()).throw(OSError("sem rede")))
    client.get(f"/api/status?t={TOKEN}")
    collection.add(db, scryfall_id="dfc-1")
    r = client.get("/api/sets").json()  # fetch_sets falha -> a vista continua a responder
    assert r[0]["code"] == "isd" and r[0]["owned"] == 1
    assert scryfall.icon_path(db, r"..\x") is None and client.get("/api/seticon/isd").status_code == 404


def test_group_printings(db):
    base = db.execute("SELECT * FROM cards WHERE id='dfc-1'").fetchone()
    db.execute("INSERT INTO cards SELECT 'dfc-2', oracle_id, name, set_code, set_name, '999', released_at, rarity, layout,"
               " lang, type_line, 1, border_color, frame, frame_effects, promo_types, finishes, cardmarket_id, eur, eur_foil,"
               " eur_etched, image_small, image_normal, digital, NULL, NULL FROM cards WHERE id='dfc-1'")  # variante: mesma carta, outra arte
    scryfall.refresh_set_totals(db)  # the bulk import does this; here we insert the variant by hand
    collection.add(db, scryfall_id="dfc-1")
    collection.add(db, scryfall_id="dfc-2")
    isd = lambda g: next(r for r in collection.set_progress(db, group=g) if r["code"] == "isd")
    assert (isd(False)["owned"], isd(False)["total"]) == (2, 2)
    assert (isd(True)["owned"], isd(True)["total"]) == (1, 1)  # agrupadas contam como 1
    assert base["oracle_id"]


def test_get_retry_on_transient_errors(monkeypatch):
    import httpx
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, content=b"ok")

    monkeypatch.setattr(scryfall.time, "sleep", lambda s: None)
    monkeypatch.setattr(scryfall.httpx, "get", lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).get(url).raise_for_status())
    assert scryfall._get_retry("https://x/y.jpg").content == b"ok" and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(scryfall.httpx, "get", lambda url, **kw: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))).get(url).raise_for_status())
    assert scryfall._get_retry("https://x/y.jpg") is None  # a 404 is not retried


def test_prints_by_name_case_insensitive_uses_index(client, db):
    client.get(f"/api/status?t={TOKEN}")
    assert client.get("/api/cards/prints", params={"name": "dElVeR oF sEcReTs // insectile aberration"}).json()[0]["id"] == "dfc-1"
    plan = " ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN SELECT id FROM cards WHERE UPPER(name)=UPPER(?)", ("x",)))
    assert "cards_name_upper" in plan


def _rows3(db):
    ids = db.execute("SELECT id FROM cards WHERE id<>'dfc-1' LIMIT 3").fetchall()
    return [collection.add(db, scryfall_id=r[0], quantity=2, location="A", purchase_price=1.5) for r in ids]


def test_bulk_update_changes_only_chosen_fields(db):
    a, b, c = _rows3(db)
    out = collection.bulk_update(db, [a, b], location="B", condition="LP", notes="lote")
    assert out == {"updated": 2, "merged": 0, "skipped": 0}
    rows = {r["id"]: r for r in collection.search(db)["rows"]}
    assert (rows[a]["location"], rows[a]["condition"], rows[a]["notes"], rows[a]["quantity"], rows[a]["purchase_price"]) == ("B", "LP", "lote", 2, 1.5)
    assert rows[c]["location"] == "A" and rows[c]["condition"] == "NM"           # the unselected one is unchanged


def test_bulk_update_merges_collisions_and_skips_missing(db):
    cid = db.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    x = collection.add(db, scryfall_id=cid, quantity=1, condition="NM")
    y = collection.add(db, scryfall_id=cid, quantity=2, condition="LP")
    out = collection.bulk_update(db, [y, 99999], condition="NM")                 # y becomes identical to x; 99999 does not exist
    assert out == {"updated": 1, "merged": 1, "skipped": 0}
    rows = collection.search(db)["rows"]
    assert len(rows) == 1 and rows[0]["quantity"] == 3 and rows[0]["id"] == x


def test_bulk_update_validates_before_touching_anything(db):
    a, b, _ = _rows3(db)
    for bad in ({"condition": "XX"}, {"finish": "gold"}, {"id": 5}, {}, {"purchase_price": "abc"}, {"purchase_price": -1},
                {"purchase_price": True}, {"language": ""}, {"language": {"x": 1}}, {"location": "x" * 201}, {"proxy": 2}):
        with pytest.raises(ValueError):
            collection.bulk_update(db, [a, b], **bad)
    assert {r["location"] for r in collection.search(db)["rows"]} == {"A"}


def test_bulk_delete_writes_trash_backup(db, tmp_path):
    a, b, c = _rows3(db)
    assert collection.bulk_delete(db, [a, b, 99999, a], trash_dir=tmp_path) == 2
    assert [r["id"] for r in collection.search(db)["rows"]] == [c]
    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert {r["id"] for r in saved} == {a, b} and saved[0]["location"] == "A"
    assert collection.bulk_delete(db, [12345], trash_dir=tmp_path) == 0 and len(list(tmp_path.glob("*.json"))) == 1


def test_matching_ids_follow_the_same_filters_as_search(db):
    _rows3(db)
    collection.add(db, scryfall_id="dfc-1", location="Z")
    assert len(collection.matching_ids(db)) == 4
    assert len(collection.matching_ids(db, location="A")) == 3 and len(collection.matching_ids(db, q="delver")) == 1
    assert collection.matching_ids(db, q="!!") == collection.matching_ids(db)    # punctuation only = no filter


def test_bulk_api(client, db, monkeypatch, tmp_path):
    from scrybinder import db as dbmod
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)
    client.get(f"/api/status?t={TOKEN}")
    a, b, c = _rows3(db)
    assert set(client.get("/api/collection/ids?location=A").json()["ids"]) == {a, b, c}
    r = client.post("/api/collection/bulk", json={"ids": [a, b], "action": "update", "fields": {"location": "N", "proxy": 1}})
    assert r.json() == {"updated": 2, "merged": 0, "skipped": 0}
    assert client.post("/api/collection/bulk", json={"ids": [a], "action": "update", "fields": {"condition": "??"}}).status_code == 422
    for bad in ({"ids": [], "action": "delete"}, {"ids": ["1"], "action": "delete"}, {"ids": [True], "action": "delete"},
                {"ids": [a], "action": "x"}, {"ids": [a], "action": "update"}, {"action": "delete"}):
        assert client.post("/api/collection/bulk", json=bad).status_code == 422, bad
    assert client.post("/api/collection/bulk", json={"ids": [a, b], "action": "delete"}).json() == {"deleted": 2}
    assert list((tmp_path / "trash").glob("*.json")) and [x["id"] for x in client.get("/api/collection").json()["rows"]] == [c]
    assert TestClient(client.app).post("/api/collection/bulk", json={"ids": [c], "action": "delete"},
                                       headers={"host": "testserver"}).status_code == 401


def test_image_sizes_and_large_url(db, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(scryfall, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scryfall, "_get_retry", lambda url, tries=3: seen.append(url) or type("R", (), {"content": b"jpg"})())
    db.execute("UPDATE cards SET image_normal='https://cards.scryfall.io/normal/front/a/b/x.jpg?1', image_small='https://cards.scryfall.io/small/front/a/b/x.jpg?1' WHERE id='dfc-1'")
    for size in ("small", "normal", "large", "lixo"):
        assert scryfall.image_path(db, "dfc-1", size).exists()
    assert seen == ["https://cards.scryfall.io/small/front/a/b/x.jpg?1", "https://cards.scryfall.io/normal/front/a/b/x.jpg?1",
                    "https://cards.scryfall.io/large/front/a/b/x.jpg?1"]   # 'junk' falls back to normal (already cached)
    assert {p.parent.name for p in tmp_path.rglob("*.jpg")} == {"small", "normal", "large"}


def test_bulk_finish_skips_printings_without_that_finish(db):
    a, b, _ = _rows3(db)
    db.execute("UPDATE cards SET finishes='[\"nonfoil\"]' WHERE id=(SELECT scryfall_id FROM collection WHERE id=?)", (a,))
    out = collection.bulk_update(db, [a, b], finish="foil")           # a only exists as nonfoil: stays as it is
    assert out == {"updated": 1, "merged": 0, "skipped": 1}
    rows = {r["id"]: r["finish"] for r in collection.search(db)["rows"]}
    assert rows[a] == "nonfoil" and rows[b] == "foil"


def test_auto_bulk_only_when_older_than_a_day(db, monkeypatch):
    import time
    from datetime import datetime, timedelta, timezone
    from scrybinder import scryfall
    from scrybinder.api import create_app
    calls = []

    def fake_download(*a, **k):
        calls.append(1)
        raise RuntimeError("sem rede (teste)")
    monkeypatch.setattr(scryfall, "download_bulk", fake_download)

    def set_age(days):
        with db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('bulk_updated', ?)",
                       ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),))
    set_age(0.2)
    create_app(db, token="t", auto_bulk=True)
    set_age(3)
    create_app(db, token="t", auto_bulk=False)  # only when the app really starts (app.py)
    time.sleep(0.3)
    assert calls == []
    app = create_app(db, token="t", auto_bulk=True)
    for _ in range(50):
        if calls:
            break
        time.sleep(0.1)
    assert calls == [1]


def test_legacy_cardex_database_is_adopted(tmp_path, monkeypatch):
    from scrybinder import db as dbmod
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)
    dbmod.connect(tmp_path / "cardex.db").close()  # database created by the old version
    (tmp_path / "cardex.db-wal").write_bytes(b"")
    conn = dbmod.connect()                         # normal start-up: adopts the old one
    conn.close()
    assert (tmp_path / "scrybinder.db").exists() and not (tmp_path / "cardex.db").exists()


def test_default_data_dir_per_platform(tmp_path, monkeypatch):
    import sys
    from scrybinder import db as dbmod
    monkeypatch.delenv("SCRYBINDER_DATA", raising=False)
    assert dbmod.default_data_dir().name == "data"                 # from source: ./data
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "scrybinder.exe"))
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert dbmod.default_data_dir() == tmp_path / "local" / "Scrybinder"        # installed: per-user folder
    (tmp_path / "app" / "portable.txt").write_text("")
    assert dbmod.default_data_dir() == tmp_path / "app" / "data"                # portable: next to the exe
    monkeypatch.setenv("SCRYBINDER_DATA", str(tmp_path / "x"))
    assert dbmod.default_data_dir() == tmp_path / "x"


MOX = ('"Count","Tradelist Count","Name","Edition","Condition","Language","Foil","Tags","Last Modified",'
       '"Collector Number","Alter","Proxy","Purchase Price"\n'
       '"2","2","Delver of Secrets // Insectile Aberration","isd","Good (Lightly Played)","Portuguese","foil","",'
       '"2024-01-20 23:09:50.153000","51","True","False","1.50"\n'
       '"1","1","Delver of Secrets // Insectile Aberration","isd","Near Mint","English","","","","51","False","False",""\n'
       '"1","1","Nope","zzz","Near Mint","English","","","","1","False","False",""\n'
       '"1","1","Delver of Secrets // Insectile Aberration","isd","Near Mint","Klingon","","","","51","False","False",""\n')


def test_moxfield_import_and_roundtrip(db):
    res = formats.import_moxfield(db, MOX, location="Box")
    assert (res["imported"], res["cards"], [s[0] for s in res["skipped"]]) == (2, 3, [4, 5])
    rows = {(r["finish"], r["condition"], r["language"]): r for r in collection.search(db)["rows"]}
    foil = rows[("foil", "LP", "pt")]
    assert (foil["quantity"], foil["altered"], foil["purchase_price"], foil["location"]) == (2, 1, 1.5, "Box")
    assert ("nonfoil", "NM", "en") in rows
    out = formats.export_moxfield(db)
    assert "Portuguese" in out and "Klingon" not in out
    again = formats.import_moxfield(db, out, location="Box")
    assert again["skipped"] == [] and collection.search(db)["total_cards"] == 6  # quantities add up
    with pytest.raises(ValueError):
        formats.import_moxfield(db, "a,b\n1,2\n")

    row = '"1","1","D","isd","Near Mint","English","%s","","","51","","",""\n'
    bad = formats.import_moxfield(db, MOX.splitlines()[0] + "\n" + row % "holo" + row.replace('"1"', '"x"', 1) % "")
    assert [s[0] for s in bad["skipped"]] == [2, 3] and bad["imported"] == 0


def test_import_route_formats(client):
    client.get(f"/api/status?t={TOKEN}")
    assert client.post("/api/import/nope", content=b"x").status_code == 404
    assert client.post("/api/import/moxfield?location=Z", content=MOX.encode()).json()["cards"] == 3


def test_reversible_cards_belong_to_the_card_of_their_first_face(db, tmp_path):
    """Scryfall gives a reversible card no oracle_id of its own (only its faces have one): it must still be a printing of that card."""
    import json
    from scrybinder import scryfall
    face = {"name": "Blood Crypt", "oracle_id": "o-bc", "oracle_text": "Pay 2 life.", "type_line": "Land — Swamp Mountain", "mana_cost": "",
            "image_uris": {"small": "s", "normal": "n"}}
    card = lambda i, n: {"id": i, "oracle_id": "o-bc", "name": "Blood Crypt", "set": "xxx", "set_name": "X", "collector_number": n, "released_at": "2026-01-01",
                         "rarity": "rare", "layout": "normal", "lang": "en", "finishes": ["nonfoil"], "type_line": "Land — Swamp Mountain", "oracle_text": "Pay 2 life.", "prices": {}}
    rev = {**card("rev-1", "349"), "layout": "reversible_card", "name": "Blood Crypt // Blood Crypt", "type_line": "Land — Swamp Mountain // Land — Swamp Mountain",
           "card_faces": [face, face]}
    del rev["oracle_id"]
    f = tmp_path / "b.json"
    f.write_text(json.dumps([card("n-1", "262"), rev]), encoding="utf-8")
    scryfall.import_bulk(db, f)
    assert db.execute("SELECT oracle_id FROM cards WHERE id='rev-1'").fetchone()[0] == "o-bc"
    assert db.execute("SELECT name FROM oracle_cards WHERE oracle_id='o-bc'").fetchone()[0] == "Blood Crypt"  # not "Blood Crypt // Blood Crypt"
    assert {r[0] for r in db.execute("SELECT id FROM cards WHERE oracle_id='o-bc'")} == {"n-1", "rev-1"}


def test_old_databases_get_their_reversible_cards_fixed_once(db):
    from scrybinder import db as dbmod
    db.execute("INSERT INTO cards (id, oracle_id, name, layout, digital) VALUES ('base', 'o-x', 'Xyz', 'normal', 0)")
    db.execute("INSERT INTO cards (id, oracle_id, name, layout, digital) VALUES ('rev', NULL, 'Xyz // Xyz', 'reversible_card', 0)")
    db.execute("DELETE FROM meta WHERE key='reversible_fixed'")
    dbmod._fix_reversible(db)
    assert db.execute("SELECT oracle_id FROM cards WHERE id='rev'").fetchone()[0] == "o-x"


def test_card_details_and_cached_rulings(client, db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from scrybinder import carddetails, scryfall
    client.get(f"/api/status?t={TOKEN}")
    d = client.get("/api/cards/dfc-1/details").json()
    assert d["set_code"] == "isd" and d["collector_number"] == "51" and d["finishes"] == ["nonfoil", "foil"] and d["owned"] == 0
    assert isinstance(d["legalities"], dict) and d["name"].startswith("Delver")
    assert client.get("/api/cards/nope/details").status_code == 404
    calls = []
    fake = lambda cid: calls.append(cid) or [{"published_at": "2011-01-01", "comment": "x", "source": "wotc"}]
    assert carddetails.rulings(db, "dfc-1", fake)[0]["comment"] == "x"
    assert carddetails.rulings(db, "dfc-1", fake) and calls == ["dfc-1"]  # the second time it comes from the cache
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    db.execute("UPDATE rulings SET fetched=?", (old,))
    def down(cid):
        raise OSError("offline")
    assert carddetails.rulings(db, "dfc-1", down)[0]["comment"] == "x"  # stale beats nothing when Scryfall cannot be reached
    db.execute("DELETE FROM rulings")
    with pytest.raises(OSError):
        carddetails.rulings(db, "dfc-1", down)
    monkeypatch.setattr(scryfall, "fetch_rulings", down)
    assert client.get("/api/cards/dfc-1/rulings").status_code == 502
    monkeypatch.setattr(scryfall, "fetch_rulings", fake)
    assert client.get("/api/cards/dfc-1/rulings").json()[0]["source"] == "wotc"
