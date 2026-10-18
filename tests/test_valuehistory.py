import time

from fastapi.testclient import TestClient

from scrybinder import collection, db as dbmod, scryfall
from scrybinder.api import create_app

TOKEN = "t"


def _sid(db):
    return db.execute("SELECT id FROM cards ORDER BY id LIMIT 1").fetchone()[0]


def test_table_is_added_to_an_old_database_without_touching_the_rest(tmp_path, bulk_file):
    path = tmp_path / "old.db"
    old = dbmod.connect(path)
    scryfall.import_bulk(old, bulk_file)
    collection.add(old, scryfall_id=_sid(old), quantity=2)
    old.execute("DROP TABLE price_snapshots")  # a database from before the history
    old.commit()
    old.close()
    db = dbmod.connect(path)
    assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0
    assert db.execute("SELECT quantity FROM collection").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] > 0


def test_snapshot_equals_the_collection_total_and_is_one_a_day(db):
    sid = _sid(db)
    collection.add(db, scryfall_id=sid, quantity=2)                    # 2 x 1.50
    collection.add(db, scryfall_id=sid, quantity=1, finish="foil")      # 3.00
    collection.add(db, scryfall_id=sid, quantity=1, finish="etched")    # no etched price: counts 0
    collection.add(db, scryfall_id=sid, quantity=1, proxy=1)            # proxies count, like the total in the app
    snap = collection.record_snapshot(db)
    assert (snap["total_value"], snap["total_cards"]) == (7.5, 5)
    assert snap["total_value"] == collection.search(db)["total_value"]
    collection.add(db, scryfall_id=sid, quantity=2, location="Box")     # + 2 x 1.50, same day
    again = collection.record_snapshot(db)
    assert again["total_value"] == 10.5 == collection.search(db)["total_value"]
    assert collection.value_history(db) == [{"date": snap["date"], "total_value": 10.5, "total_cards": 7}]


def test_empty_collection_writes_a_zero_row(db):
    assert collection.record_snapshot(db)["total_value"] == 0
    assert [h["total_cards"] for h in collection.value_history(db)] == [0]


def test_bulk_update_records_a_snapshot_and_a_failed_one_does_not(db, bulk_file, monkeypatch):
    collection.add(db, scryfall_id=_sid(db), quantity=2)
    monkeypatch.setattr(scryfall, "download_bulk", lambda progress=None: bulk_file)
    monkeypatch.setattr(scryfall, "fetch_sets", lambda conn: None)
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")

    def wait():
        for _ in range(200):
            if c.get("/api/status").json()["job"]["state"] in ("done", "error"):
                return c.get("/api/status").json()["job"]["state"]
            time.sleep(0.05)
    assert c.get("/api/collection/value-history").json() == {"snapshots": []}
    c.post("/api/bulk/update")
    assert wait() == "done"
    [snap] = c.get("/api/collection/value-history").json()["snapshots"]
    assert snap["total_cards"] == 2 and snap["total_value"] == 3.0
    db.execute("DELETE FROM price_snapshots")
    db.commit()

    def boom(conn, path, progress=None):
        raise RuntimeError("import failed")
    monkeypatch.setattr(scryfall, "import_bulk", boom)
    c.post("/api/bulk/update")
    assert wait() == "error"
    assert c.get("/api/collection/value-history").json() == {"snapshots": []}
