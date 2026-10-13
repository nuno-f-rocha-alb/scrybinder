import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks
from scrybinder.api import create_app

TOKEN = "t"


def _setup(db, qty=2):
    """Two decks, one oracle card with a collection row of `qty` copies."""
    oid = db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT 1").fetchone()[0]
    sid = db.execute("SELECT id FROM cards WHERE oracle_id=?", (oid,)).fetchone()[0]
    return oid, sid, collection.add(db, scryfall_id=sid, quantity=qty), decks.create(db, "D1"), decks.create(db, "D2")


def _card(db, deck, cid):
    return next(c for c in decks.get(db, deck)["cards"] if c["id"] == cid)


def test_assign_status_and_conflicts(db):
    oid, sid, row, d1, d2 = _setup(db)
    c1, c2 = decks.add_card(db, d1, oid, 2), decks.add_card(db, d2, oid, 1)
    assert _card(db, d1, c1)["status"] == "available"
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 2}])
    a = _card(db, d1, c1)
    assert (a["status"], a["assigned"], a["assignments"]) == ("assigned", 2, [{"collection_id": row, "quantity": 2}])
    b = _card(db, d2, c2)  # every copy is in D1
    assert (b["status"], b["missing"], b["elsewhere"]) == ("elsewhere", 1, [{"deck_id": d1, "name": "D1", "quantity": 2}])
    with pytest.raises(decks.Conflict) as e:
        decks.assign(db, d2, c2, [{"collection_id": row, "quantity": 1}])
    assert "D1" in str(e.value) and e.value.decks[0]["deck_id"] == d1
    s = decks.get(db, d1)["summary"]
    assert (s["assigned"], s["missing"]) == (2, 0)
    c3 = decks.add_card(db, d1, oid, 5, board="side")
    with pytest.raises(ValueError):  # the row only has 2 copies and nobody else holds any
        decks.assign(db, d1, c3, [{"collection_id": collection.add(db, scryfall_id=sid, quantity=2, location="Z"), "quantity": 3}])
    for bad in ([{"collection_id": row, "quantity": 3}], [{"collection_id": 999, "quantity": 1}], "x", [{"collection_id": row, "quantity": -1}]):
        with pytest.raises(ValueError):
            decks.assign(db, d1, c1, bad)
    other = db.execute("SELECT id FROM cards WHERE oracle_id != ? LIMIT 1", (oid,)).fetchone()[0]
    with pytest.raises(ValueError):  # a copy of another card
        decks.assign(db, d1, c1, [{"collection_id": collection.add(db, scryfall_id=other), "quantity": 1}])
    prow = collection.add(db, scryfall_id=sid, quantity=1, proxy=1)
    with pytest.raises(ValueError):
        decks.assign(db, d1, c1, [{"collection_id": prow, "quantity": 1}])
    decks.assign(db, d1, c1, [])  # empty list frees the copies
    assert _card(db, d2, c2)["status"] == "available"


def test_free_copies_are_shared_between_boards_of_a_deck(db):
    oid, _, _, d1, _ = _setup(db)
    main, side = decks.add_card(db, d1, oid, 2), decks.add_card(db, d1, oid, 2, board="side")
    st = {c["id"]: c for c in decks.get(db, d1)["cards"]}
    assert (st[main]["status"], st[side]["status"], st[side]["missing"]) == ("available", "missing", 2)
    assert decks.assign_free(db, d1) == 2  # only the copies that exist, never twice
    assert decks.assign_free(db, d1) == 0


def test_assign_free_prefers_printing_and_keeps_manual(db):
    oid, sid, row, d1, d2 = _setup(db, qty=1)
    row2 = collection.add(db, scryfall_id=sid, quantity=3, location="B")
    c1 = decks.add_card(db, d1, oid, 3)
    assert decks.assign_free(db, d1) == 3
    assert sorted((a["collection_id"], a["quantity"]) for a in _card(db, d1, c1)["assignments"]) == [(row, 1), (row2, 2)]
    c2 = decks.add_card(db, d2, oid, 2)
    assert decks.assign_free(db, d2) == 1 and _card(db, d2, c2)["assigned"] == 1  # one copy was left
    assert _card(db, d2, c2)["missing"] == 1


def test_changing_the_deck_trims_or_merges_assignments(db):
    oid, _, row, d1, _ = _setup(db, qty=3)
    c1 = decks.add_card(db, d1, oid, 3)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 3}])
    decks.update_card(db, d1, c1, quantity=1)
    assert _card(db, d1, c1)["assigned"] == 1
    decks.update_card(db, d1, c1, tags=["proxy"])  # a proxy reserves nothing
    c = _card(db, d1, c1)
    assert (c["assigned"], c["status"]) == (0, "proxy")
    with pytest.raises(ValueError):
        decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    decks.update_card(db, d1, c1, tags=[])
    side = decks.add_card(db, d1, oid, 1, board="side")
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    decks.assign(db, d1, side, [{"collection_id": row, "quantity": 1}])
    assert decks.update_card(db, d1, side, board="main") == c1  # merged: assignments are summed
    assert _card(db, d1, c1)["assignments"] == [{"collection_id": row, "quantity": 2}]


def test_collection_changes_respect_assignments(db):
    oid, sid, row, d1, _ = _setup(db, qty=3)
    c1 = decks.add_card(db, d1, oid, 2)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 2}])
    collection.update(db, row, quantity=2, notes="ok")  # still enough
    for call in (lambda: collection.update(db, row, quantity=1), lambda: collection.delete(db, row),
                 lambda: collection.bulk_delete(db, [row]), lambda: collection.bulk_update(db, [row], proxy=1),
                 lambda: collection.update(db, row, proxy=1), lambda: collection.move(db, row, "X", 1)):
        with pytest.raises(decks.Conflict) as e:
            call()
        assert e.value.decks[0]["name"] == "D1"
    assert db.execute("SELECT quantity FROM collection WHERE id=?", (row,)).fetchone()[0] == 2  # nothing half done
    collection.update(db, row, quantity=1, release=True)  # freed from the deck, then changed
    assert _card(db, d1, c1)["assigned"] == 0
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    collection.delete(db, row, release=True)
    assert _card(db, d1, c1)["assigned"] == 0 and not db.execute("SELECT 1 FROM deck_assignments").fetchone()


def test_collection_merge_moves_assignments(db):
    oid, sid, row, d1, _ = _setup(db, qty=1)
    other = collection.add(db, scryfall_id=sid, quantity=2, location="B")
    c1 = decks.add_card(db, d1, oid, 3)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}, {"collection_id": other, "quantity": 1}])
    assert collection.update(db, row, location="B") == other  # same key: merged into the other row
    assert _card(db, d1, c1)["assignments"] == [{"collection_id": other, "quantity": 2}]
    assert collection.move(db, other, "C") == other  # a plain move keeps the row and its assignments
    assert _card(db, d1, c1)["assigned"] == 2


def test_assignment_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    oid, sid, row, d1, d2 = _setup(db)
    c1 = c.post(f"/api/decks/{d1}/cards", json={"oracle_id": oid, "quantity": 2}).json()["id"]
    assert c.post(f"/api/decks/{d1}/assign-free").json() == {"assigned": 2}
    c2 = c.post(f"/api/decks/{d2}/cards", json={"oracle_id": oid}).json()["id"]
    assert c.put(f"/api/decks/{d2}/cards/{c2}/assign", json={"items": [{"collection_id": row, "quantity": 1}]}).status_code == 409
    assert c.put(f"/api/decks/{d2}/cards/{c2}/assign", json={"items": "x"}).status_code == 422
    assert c.put(f"/api/decks/{d2}/cards/999/assign", json={"items": []}).status_code == 404
    r = c.delete(f"/api/collection/{row}")
    assert r.status_code == 409 and r.json()["detail"]["decks"][0]["name"] == "D1"
    assert c.patch(f"/api/collection/{row}", json={"quantity": 1}).status_code == 409
    assert c.post(f"/api/collection/{row}/move", json={"location": "X", "quantity": 1}).status_code == 409
    assert c.post("/api/collection/bulk", json={"ids": [row], "action": "delete"}).status_code == 409
    assert c.patch(f"/api/collection/{row}?release=1", json={"quantity": 1}).status_code == 200
    assert c.get(f"/api/decks/{d1}").json()["cards"][0]["assigned"] == 0
    assert c.delete(f"/api/collection/{row}").status_code == 200


def test_copies_of_a_deck_card_and_who_holds_them(db):
    oid, sid, row, d1, d2 = _setup(db, qty=3)
    other = collection.add(db, scryfall_id=sid, quantity=2, location="B", finish="foil")
    collection.add(db, scryfall_id=sid, quantity=4, proxy=1, location="P")  # a proxy row is not a copy
    c1, c2 = decks.add_card(db, d1, oid, 2, scryfall_id=sid), decks.add_card(db, d2, oid, 3)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 2}])
    decks.assign(db, d2, c2, [{"collection_id": row, "quantity": 1}, {"collection_id": other, "quantity": 1}])
    got = decks.copies(db, d1, c1)
    assert got["quantity"] == 2 and [r["id"] for r in got["rows"]] == [row, other]  # the preferred printing first, no proxy
    a, b = got["rows"]
    assert (a["here"], a["free"], a["elsewhere"]) == (2, 0, [{"deck_id": d2, "name": "D2", "quantity": 1}])  # 3 owned: 2 here, 1 in D2
    assert (b["here"], b["free"], b["finish"]) == (0, 1, "foil") and b["elsewhere"][0]["name"] == "D2"
    assert decks.copies(db, d2, c2)["rows"][0]["elsewhere"] == [{"deck_id": d1, "name": "D1", "quantity": 2}]
    with pytest.raises(KeyError):
        decks.copies(db, d2, c1)  # the card is not in that deck
    empty = decks.create(db, "E")
    free = decks.add_card(db, empty, db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != ? LIMIT 1", (oid,)).fetchone()[0])
    assert decks.copies(db, empty, free)["rows"] == []  # nothing owned


def test_copies_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    oid, sid, row, d1, _ = _setup(db)
    c1 = c.post(f"/api/decks/{d1}/cards", json={"oracle_id": oid, "quantity": 2}).json()["id"]
    r = c.get(f"/api/decks/{d1}/cards/{c1}/copies").json()
    assert r["quantity"] == 2 and r["rows"][0]["id"] == row and r["rows"][0]["free"] == 2
    assert c.get(f"/api/decks/{d1}/cards/999/copies").status_code == 404
