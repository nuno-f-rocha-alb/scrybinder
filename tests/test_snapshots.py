import pytest
from fastapi.testclient import TestClient

from scrybinder import db as dbmod, decks, scryfall
from scrybinder.api import create_app

TOKEN = "t"


def _oracles(db, n=3):
    return [r[0] for r in db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT ?", (n,))]


def _deck(db):
    a, b, c = _oracles(db)
    d = decks.create(db, "D")
    decks.add_card(db, d, a, 2)
    decks.add_card(db, d, b, 1)
    decks.add_card(db, d, c, 1, board="side")
    return d, a, b, c


def test_tables_are_added_to_an_old_database(tmp_path, bulk_file):
    path = tmp_path / "old.db"
    old = dbmod.connect(path)
    scryfall.import_bulk(old, bulk_file)
    d, *_ = _deck(old)
    old.execute("DROP TABLE deck_snapshot_cards")
    old.execute("DROP TABLE deck_snapshots")  # a database from before snapshots
    old.commit()
    old.close()
    db = dbmod.connect(path)
    assert db.execute("SELECT COUNT(*) FROM deck_snapshots").fetchone()[0] == db.execute("SELECT COUNT(*) FROM deck_snapshot_cards").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM deck_cards WHERE deck_id=?", (d,)).fetchone()[0] == 3


def test_save_list_and_delete(db):
    d, a, b, c = _deck(db)
    before = decks.get(db, d)["cards"]
    s1 = decks.save_snapshot(db, d, "  first   try ")
    assert db.execute("SELECT name FROM deck_snapshots WHERE id=?", (s1,)).fetchone()[0] == "first try"
    assert db.execute("SELECT COUNT(*) FROM deck_snapshot_cards WHERE snapshot_id=?", (s1,)).fetchone()[0] == 3
    assert decks.get(db, d)["cards"] == before
    decks.add_card(db, d, a, 1)
    s2 = decks.save_snapshot(db, d, "second")
    listed = decks.snapshots(db, d)
    assert [(s["name"], s["cards"], s["value"]) for s in listed] == [("second", 5, 7.5), ("first try", 4, 6.0)]  # newest first; 1.50 a card
    for bad in ("", "  ", "x" * 61, None, 5):
        with pytest.raises(ValueError):
            decks.save_snapshot(db, d, bad)
    with pytest.raises(KeyError):
        decks.save_snapshot(db, 999, "x")
    decks.delete_snapshot(db, d, s1)
    assert [s["id"] for s in decks.snapshots(db, d)] == [s2]
    assert db.execute("SELECT COUNT(*) FROM deck_snapshot_cards WHERE snapshot_id=?", (s1,)).fetchone()[0] == 0
    with pytest.raises(KeyError):
        decks.delete_snapshot(db, d, s1)


def test_compare_added_removed_changed_and_price(db):
    d, a, b, c = _deck(db)
    snap = decks.save_snapshot(db, d, "before")
    line = lambda oid, board="main": next(x for x in decks.get(db, d)["cards"] if x["oracle_id"] == oid and x["board"] == board)
    decks.update_card(db, d, line(a)["id"], quantity=5)       # changed: 2 -> 5
    decks.remove_card(db, d, line(b)["id"])                    # removed: 1 -> 0
    extra = _oracles(db, 4)[3]
    decks.add_card(db, d, extra, 2)                            # added: 0 -> 2
    r = decks.compare(db, d, snap, "current")
    assert [(e["oracle_id"], e["old_qty"], e["new_qty"], e["delta_qty"]) for e in r["changed"]] == [(a, 2, 5, 3)]
    assert [(e["oracle_id"], e["delta_qty"]) for e in r["removed"]] == [(b, -1)]
    assert [(e["oracle_id"], e["delta_qty"]) for e in r["added"]] == [(extra, 2)]
    assert r["price_difference"] == 6.0  # (+3 -1 +2) x 1.50
    assert decks.compare(db, d)["price_difference"] == 6.0  # the default: the newest snapshot against the deck now
    back = decks.compare(db, d, "current", snap)
    assert back["price_difference"] == -6.0 and [e["oracle_id"] for e in back["added"]] == [b]  # the other way round


def test_compare_edge_cases(db):
    d, a, b, c = _deck(db)
    s = decks.save_snapshot(db, d, "s")
    assert decks.compare(db, d, s, s) == {"added": [], "removed": [], "changed": [], "price_difference": 0}
    assert decks.compare(db, d, s, "current")["price_difference"] == 0
    other = decks.create(db, "Other")
    with pytest.raises(ValueError):
        decks.compare(db, other, s, "current")  # a snapshot of another deck
    with pytest.raises(KeyError):
        decks.compare(db, d, 999, "current")
    with pytest.raises(ValueError):
        decks.compare(db, other)  # no snapshots yet
    # a card moved to another board is one removed and one added
    moved = next(x for x in decks.get(db, d)["cards"] if x["oracle_id"] == b)
    decks.update_card(db, d, moved["id"], board="side")
    r = decks.compare(db, d, s, "current")
    assert [(e["board"], e["delta_qty"]) for e in r["removed"]] == [("main", -1)] and [(e["board"], e["delta_qty"]) for e in r["added"]] == [("side", 1)]
    assert r["price_difference"] == 0
    # a card without a price counts as 0
    db.execute("UPDATE cards SET eur=NULL, eur_foil=NULL, eur_etched=NULL WHERE oracle_id=?", (a,))
    db.commit()
    decks.add_card(db, d, a, 1)
    assert next(e for e in decks.compare(db, d, s, "current")["changed"] if e["oracle_id"] == a)["line_delta"] == 0


def test_deleting_the_deck_removes_its_snapshots(db):
    d, *_ = _deck(db)
    decks.save_snapshot(db, d, "s")
    decks.delete(db, d)
    assert db.execute("SELECT COUNT(*) FROM deck_snapshots").fetchone()[0] == db.execute("SELECT COUNT(*) FROM deck_snapshot_cards").fetchone()[0] == 0


def test_snapshots_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    d, a, b, _ = _deck(db)
    assert c.get(f"/api/decks/{d}/snapshots").json() == []
    assert c.get(f"/api/decks/{d}/compare").status_code == 422  # nothing saved yet
    sid = c.post(f"/api/decks/{d}/snapshots", json={"name": "api"}).json()["id"]
    assert c.post(f"/api/decks/{d}/snapshots", json={"name": ""}).status_code == 422
    assert c.get(f"/api/decks/{d}/snapshots").json()[0]["name"] == "api"
    c.post(f"/api/decks/{d}/cards", json={"oracle_id": a, "quantity": 1})
    r = c.get(f"/api/decks/{d}/compare?base={sid}&target=current").json()
    assert [e["delta_qty"] for e in r["changed"]] == [1] and r["price_difference"] == 1.5
    assert c.get(f"/api/decks/{d}/compare").json() == r  # the defaults
    assert c.get(f"/api/decks/{d}/compare?base=x").status_code == 422
    assert c.get(f"/api/decks/{d}/compare?base=999").status_code == 404
    assert c.delete(f"/api/decks/{d}/snapshots/{sid}").status_code == 200
    assert c.delete(f"/api/decks/{d}/snapshots/{sid}").status_code == 404
    assert c.get("/api/decks/999/snapshots").status_code == 404


def test_restore_puts_the_deck_back_and_saves_the_current_one_first(db):
    d, a, b, c = _deck(db)
    snap = decks.save_snapshot(db, d, "good one")
    line = lambda oid, board="main": next(x for x in decks.get(db, d)["cards"] if x["oracle_id"] == oid and x["board"] == board)
    decks.update_card(db, d, line(a)["id"], quantity=7)       # a: 2 -> 7
    decks.remove_card(db, d, line(b)["id"])                    # b gone
    extra = _oracles(db, 4)[3]
    decks.add_card(db, d, extra, 3)                            # a card that was not in it
    r = decks.restore_snapshot(db, d, snap)
    assert (r["restored"], r["skipped"]) == (3, 0)
    now = {(x["oracle_id"], x["board"]): x["quantity"] for x in decks.get(db, d)["cards"]}
    assert now == {(a, "main"): 2, (b, "main"): 1, (c, "side"): 1}  # exactly the snapshot
    assert decks.compare(db, d, snap, "current")["price_difference"] == 0
    safety = next(s for s in decks.snapshots(db, d) if s["name"] == "Before restoring good one")
    assert safety["cards"] == 11 and r["safety_snapshot"] == safety["id"]  # 7 + 1 (c) + 3 extra
    back = decks.restore_snapshot(db, d, safety["id"])  # and the deck from before can be restored too
    assert {(x["oracle_id"], x["board"]): x["quantity"] for x in decks.get(db, d)["cards"]} == {(a, "main"): 7, (c, "side"): 1, (extra, "main"): 3}
    assert back["skipped"] == 0


def test_restore_frees_assigned_copies_and_survives_a_missing_printing(db):
    from scrybinder import collection
    d, a, b, c = _deck(db)
    sid = db.execute("SELECT id FROM cards WHERE oracle_id=?", (a,)).fetchone()[0]
    row = collection.add(db, scryfall_id=sid, quantity=2)
    decks.assign(db, d, next(x for x in decks.get(db, d)["cards"] if x["oracle_id"] == a)["id"], [{"collection_id": row, "quantity": 2}])
    snap = decks.save_snapshot(db, d, "s")
    db.execute("UPDATE deck_snapshot_cards SET scryfall_id='gone' WHERE oracle_id=?", (a,))  # a printing that no longer exists
    db.commit()
    r = decks.restore_snapshot(db, d, snap)
    assert r["skipped"] == 0 and next(x for x in decks.get(db, d)["cards"] if x["oracle_id"] == a)["quantity"] == 2
    assert collection.search(db)["total_cards"] == 2  # the copies are still in the collection


def test_restore_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    d, a, *_ = _deck(db)
    sid = c.post(f"/api/decks/{d}/snapshots", json={"name": "api"}).json()["id"]
    c.post(f"/api/decks/{d}/cards", json={"oracle_id": a, "quantity": 4})
    r = c.post(f"/api/decks/{d}/snapshots/{sid}/restore")
    assert r.status_code == 200 and r.json()["restored"] == 3
    assert next(x for x in c.get(f"/api/decks/{d}").json()["cards"] if x["oracle_id"] == a)["quantity"] == 2
    assert c.post(f"/api/decks/{d}/snapshots/999/restore").status_code == 404
    assert c.post(f"/api/decks/{d}/snapshots/{sid}/restore").status_code == 200
