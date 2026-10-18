import csv
import io

import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks
from scrybinder.api import create_app

TOKEN = "t"


def _card(db):
    oid = db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT 1").fetchone()[0]
    return oid, db.execute("SELECT id FROM cards WHERE oracle_id=?", (oid,)).fetchone()[0]


def _assign(db, oid, row, q, name="D"):
    d = decks.create(db, name)
    c = decks.add_card(db, d, oid, q)
    decks.assign(db, d, c, [{"collection_id": row, "quantity": q}])
    return d


def _spare(db, **kw):
    return {(i["location"], i["finish"]): i["spare"] for i in collection.spare(db, **kw)["items"]}


def test_spare_is_quantity_minus_assigned_and_skips_proxies(db):
    oid, sid = _card(db)
    row = collection.add(db, scryfall_id=sid, quantity=4)
    collection.add(db, scryfall_id=sid, quantity=5, proxy=1)
    assert collection.spare(db)["total_spare"] == 4
    _assign(db, oid, row, 1)
    sp = collection.spare(db)
    assert sp["total_spare"] == 3 and sp["total_value"] == 4.5  # 3 x 1.50
    _assign(db, oid, row, 3, "D2")
    assert collection.spare(db) == {"items": [], "total_spare": 0, "total_value": 0}


def test_assignments_across_decks_are_summed(db):
    oid, sid = _card(db)
    row = collection.add(db, scryfall_id=sid, quantity=3)
    _assign(db, oid, row, 2, "A")
    _assign(db, oid, row, 1, "B")
    assert collection.spare(db)["items"] == []


def test_keep_holds_back_copies_newest_rows_first(db):
    oid, sid = _card(db)
    old = collection.add(db, scryfall_id=sid, quantity=2, location="Old")
    new = collection.add(db, scryfall_id=sid, quantity=2, location="New")
    assert new > old
    assert _spare(db, keep=0) == {("Old", "nonfoil"): 2, ("New", "nonfoil"): 2}
    assert _spare(db, keep=3) == {("Old", "nonfoil"): 1}
    assert _spare(db, keep=4) == {} and _spare(db, keep=9) == {}
    for bad in (-1, 1.5, True, "1"):
        with pytest.raises(ValueError):
            collection.spare(db, keep=bad)


def test_exports(db):
    _, sid = _card(db)
    collection.add(db, scryfall_id=sid, quantity=2, location="Box")
    collection.add(db, scryfall_id=sid, quantity=1, finish="etched", location="Box")  # no etched price
    sp = collection.spare(db)
    k = db.execute("SELECT name, set_code, collector_number, cardmarket_id FROM cards WHERE id=?", (sid,)).fetchone()
    assert collection.spare_text(sp) == f"2 {k['name']} ({k['set_code'].upper()} #{k['collector_number']}, nonfoil)\n1 {k['name']} ({k['set_code'].upper()} #{k['collector_number']}, etched)\n"
    rows = list(csv.DictReader(io.StringIO(collection.spare_csv(sp))))
    assert [(r["quantity"], r["finish"], r["price_eur"]) for r in rows] == [("2", "nonfoil", "1.5"), ("1", "etched", "")]
    assert collection.spare_csv({"items": []}) == ",".join(collection.SPARE_COLS) + "\n" and collection.spare_text({"items": []}) == ""


def test_spare_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    assert c.get("/api/collection/spare").json() == {"items": [], "total_spare": 0, "total_value": 0}
    _, sid = _card(db)
    collection.add(db, scryfall_id=sid, quantity=3)
    assert c.get("/api/collection/spare").json()["total_spare"] == 3
    assert c.get("/api/collection/spare?keep=1").json()["total_spare"] == 2
    assert c.get("/api/collection/spare?keep=-1").status_code == 422
    t = c.get("/api/collection/spare?format=text")
    assert t.text.startswith("3 ") and "attachment" in t.headers["content-disposition"]
    v = c.get("/api/collection/spare?format=csv")
    assert v.text.startswith("quantity,name,") and "attachment" in v.headers["content-disposition"]
