import csv
import io

from fastapi.testclient import TestClient

from scrybinder import collection
from scrybinder.api import create_app

TOKEN = "t"

# a made-up set: Alpha has two printings (#2 dearer, #10 cheaper), Beta one with no price, Gamma one digital-only (never counted)
PRINTINGS = [("t-a2", "o-alpha", "Alpha", "2", "common", 5.0, 0), ("t-a10", "o-alpha", "Alpha", "10", "rare", 2.0, 0),
             ("t-b1", "o-beta", "Beta", "1", "uncommon", None, 0), ("t-g3", "o-gamma", "Gamma", "3", "common", 1.0, 1)]


def _set(db):
    for i, (cid, oid, name, num, rar, eur, digital) in enumerate(PRINTINGS):
        db.execute("INSERT INTO cards (id, oracle_id, name, set_code, set_name, collector_number, rarity, released_at, eur, digital)"
                   " VALUES (?, ?, ?, 'tst', 'Test Set', ?, ?, ?, ?, ?)", (cid, oid, name, num, rar, f"2024-01-0{i + 1}", eur, digital))
    db.commit()


def _ids(sm):
    return [m["scryfall_id"] for m in sm["missing"]]


def test_missing_printings_sorted_by_number_and_total(db):
    _set(db)
    sm = collection.set_missing(db, "TST")
    assert _ids(sm) == ["t-b1", "t-a2", "t-a10"] and sm["count"] == 3 and sm["total_price"] == 7.0  # digital printing is not part of the set
    collection.add(db, scryfall_id="t-a2", quantity=1)
    sm = collection.set_missing(db, "tst")
    assert _ids(sm) == ["t-b1", "t-a10"] and sm["set_name"] == "Test Set"
    total = db.execute("SELECT COUNT(*) FROM cards WHERE set_code='tst' AND digital=0").fetchone()[0]
    assert 1 + sm["count"] == total  # owned + missing == the set's total


def test_proxies_do_not_count_and_location_is_respected(db):
    _set(db)
    collection.add(db, scryfall_id="t-b1", quantity=1, proxy=1)
    collection.add(db, scryfall_id="t-a2", quantity=1, location="Box A")
    assert "t-b1" in _ids(collection.set_missing(db, "tst"))
    assert "t-a2" not in _ids(collection.set_missing(db, "tst", location="Box A"))
    assert "t-a2" in _ids(collection.set_missing(db, "tst", location="Box B"))
    assert "t-a2" not in _ids(collection.set_missing(db, "tst", location=["Box A", "Box B"]))


def test_group_collapses_printings_of_one_card(db):
    _set(db)
    sm = collection.set_missing(db, "tst", group=True)
    assert _ids(sm) == ["t-b1", "t-a10"] and sm["total_price"] == 2.0  # Alpha once, as its cheapest printing
    collection.add(db, scryfall_id="t-a2", quantity=1)  # any printing owned: the card is not missing
    assert _ids(collection.set_missing(db, "tst", group=True)) == ["t-b1"]
    assert _ids(collection.set_missing(db, "tst")) == ["t-b1", "t-a10"]  # ungrouped: the other printing still is


def test_exports_and_unknown_set(db):
    _set(db)
    sm = collection.set_missing(db, "tst")
    assert collection.set_missing_text(sm) == "Beta (#1)\nAlpha (#2)\nAlpha (#10)\n"
    rows = list(csv.DictReader(io.StringIO(collection.set_missing_csv(sm))))
    assert rows == [{"name": "Beta", "collector_number": "1", "rarity": "uncommon", "price_eur": "", "set_code": "tst"},
                    {"name": "Alpha", "collector_number": "2", "rarity": "common", "price_eur": "5.0", "set_code": "tst"},
                    {"name": "Alpha", "collector_number": "10", "rarity": "rare", "price_eur": "2.0", "set_code": "tst"}]
    nope = collection.set_missing(db, "zzz")
    assert nope == {"set_code": "zzz", "set_name": "", "missing": [], "count": 0, "total_price": 0}
    assert collection.set_missing_csv(nope) == "name,collector_number,rarity,price_eur,set_code\n"


def test_set_missing_api(db):
    _set(db)
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    assert c.get("/api/sets/tst/missing").json()["count"] == 3
    assert c.get("/api/sets/tst/missing?group=true").json()["count"] == 2
    collection.add(db, scryfall_id="t-a2", quantity=1, location="Box A")
    assert c.get("/api/sets/tst/missing?location=Box+A").json()["count"] == 2
    assert c.get("/api/sets/zzz/missing").json()["count"] == 0
    t = c.get("/api/sets/tst/missing?format=text")
    assert t.text.startswith("Beta (#1)") and "attachment" in t.headers["content-disposition"]
    v = c.get("/api/sets/tst/missing?format=csv")
    assert v.text.startswith("name,collector_number,") and "scrybinder-missing-tst.csv" in v.headers["content-disposition"]
