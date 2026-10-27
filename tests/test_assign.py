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
    assert [a["quantity"] for a in _card(db, d1, c1)["assignments"]] == [3]  # both rows moved into the deck's location and merged there
    assert [tuple(r) for r in db.execute("SELECT location, SUM(quantity) FROM collection GROUP BY location")] == [("B", 1), ("Deck: D1", 3)]
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
    row = db.execute("SELECT id FROM collection").fetchone()[0]  # the rows were split and merged on the way
    side = decks.add_card(db, d1, oid, 1, board="side")
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    decks.assign(db, d1, side, [{"collection_id": row, "quantity": 1}])
    assert decks.update_card(db, d1, side, board="main") == c1  # merged: assignments are summed
    assert [a["quantity"] for a in _card(db, d1, c1)["assignments"]] == [2]


def test_collection_changes_respect_assignments(db):
    oid, sid, row, d1, _ = _setup(db, qty=3)
    c1 = decks.add_card(db, d1, oid, 2)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 2}])
    row = db.execute("SELECT collection_id FROM deck_assignments").fetchone()[0]  # the two copies moved to the deck's location
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
    rows = got["rows"]  # assigning split and moved rows: look at the totals, not at ids
    assert got["quantity"] == 2 and 3 not in [r["id"] for r in rows]  # the third row is the proxy
    assert sum(r["here"] for r in rows) == 2 and sum(r["free"] for r in rows) == 1  # 5 copies: 2 here, 2 in D2, 1 free
    assert next(r for r in rows if r["free"])["finish"] == "foil"
    assert {e["name"] for r in rows for e in r["elsewhere"]} == {"D2"}
    assert {e["name"] for r in decks.copies(db, d2, c2)["rows"] for e in r["elsewhere"]} == {"D1"}
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


def test_collection_rows_say_which_decks_hold_them(db):
    oid, sid, row, d1, d2 = _setup(db)
    assert collection.search(db)["rows"][0]["decks"] == []
    decks.assign(db, d1, decks.add_card(db, d1, oid, 1), [{"collection_id": row, "quantity": 1}])
    decks.assign(db, d2, decks.add_card(db, d2, oid, 1), [{"collection_id": row, "quantity": 1}])
    held = sorted((d["name"], d["quantity"]) for r in collection.search(db)["rows"] for d in r["decks"])  # each deck has its own row now
    assert held == [("D1", 1), ("D2", 1)]


def test_add_missing_puts_the_missing_copies_in_the_collection(db):
    oid, sid, row, d1, d2 = _setup(db, qty=1)
    c1 = decks.add_card(db, d1, oid, 3)
    px = decks.add_card(db, d1, oid, 1, board="side", tags=["proxy"])
    mb = decks.add_card(db, d1, oid, 1, board="maybe")
    assert decks.add_missing(db, d1, [px, mb]) == 0  # a proxy and the maybeboard are never added
    assert decks.add_missing(db, d1, location="Box") == 2  # 3 wanted, 1 owned
    assert db.execute("SELECT SUM(quantity) FROM collection WHERE scryfall_id=?", (sid,)).fetchone()[0] == 3
    assert db.execute("SELECT SUM(quantity) FROM collection WHERE location='Deck: D1'").fetchone()[0] == 3  # the new copies went to the deck's location
    a = _card(db, d1, c1)
    assert (a["status"], a["assigned"], a["missing"]) == ("assigned", 3, 0)
    assert decks.add_missing(db, d1) == 0


def test_add_missing_for_chosen_cards_assigns_only_those(db):
    oid, sid, row, d1, d2 = _setup(db, qty=2)
    other = db.execute("SELECT id FROM cards WHERE oracle_id != ? LIMIT 1", (oid,)).fetchone()
    oid2 = db.execute("SELECT oracle_id FROM cards WHERE id=?", (other[0],)).fetchone()[0]
    collection.add(db, scryfall_id=other[0], quantity=1)
    c1, c2 = decks.add_card(db, d1, oid, 3), decks.add_card(db, d1, oid2, 1)
    assert decks.add_missing(db, d1, [c1]) == 1
    assert (_card(db, d1, c1)["assigned"], _card(db, d1, c2)["assigned"]) == (3, 0)  # the other card's free copy is left alone
    with pytest.raises(ValueError):
        decks.add_missing(db, d1, "x")


def test_a_deck_cover_can_be_chosen_from_its_cards(db):
    oid, sid, row, d1, d2 = _setup(db)
    other = db.execute("SELECT id, oracle_id FROM cards WHERE oracle_id != ? AND image_small IS NOT NULL LIMIT 1", (oid,)).fetchone()
    c1, c2 = decks.add_card(db, d1, oid, 1, scryfall_id=sid), decks.add_card(db, d1, other["oracle_id"], 1, scryfall_id=other["id"])
    cover = lambda: next(d for d in decks.listing(db) if d["id"] == d1)["cover"]
    first = cover()
    decks.update(db, d1, cover_card_id=c2 if first == sid else c1)
    assert cover() != first
    decks.update(db, d1, cover_card_id=None)  # back to the default
    assert cover() == first
    with pytest.raises(ValueError):
        decks.update(db, d1, cover_card_id=decks.add_card(db, d2, oid))  # a card of another deck


def test_an_empty_location_can_be_made_and_removed(db):
    oid, sid, row, d1, d2 = _setup(db, qty=2)
    assert collection.create_location(db, "  Box 7 ") == "Box 7"
    collection.create_location(db, "Box 7")  # again: still one
    assert {l["location"]: l["cards"] for l in collection.locations(db)} == {"": 2, "Box 7": 0, "Deck: D1": 0, "Deck: D2": 0}
    collection.move(db, row, "Box 7", 1)  # a card can go there later
    assert {l["location"]: l["cards"] for l in collection.locations(db)} == {"": 1, "Box 7": 1, "Deck: D1": 0, "Deck: D2": 0}
    assert collection.delete_location(db, "Box 7") == {"moved": 1}  # its card goes to "(no location)"
    assert {l["location"]: l["cards"] for l in collection.locations(db)} == {"": 2, "Deck: D1": 0, "Deck: D2": 0}
    collection.create_location(db, "Empty")
    collection.delete_location(db, "Empty")
    assert "Empty" not in [l["location"] for l in collection.locations(db)]
    for bad in ("", "   ", None, "x" * 61):
        with pytest.raises(ValueError):
            collection.create_location(db, bad)


def test_a_deck_card_has_a_finish_of_its_printing(db):
    oid, sid, row, d1, d2 = _setup(db)
    foil, plain = decks.add_card(db, d1, oid, 1, scryfall_id=sid, finish="foil"), decks.add_card(db, d1, oid, 1, scryfall_id=sid, finish="nonfoil")
    assert foil != plain  # the same printing in two finishes: two rows
    assert decks.add_card(db, d1, oid, 1, scryfall_id=sid, finish="foil") == foil  # the same finish adds up
    assert {c["id"]: (c["finish"], c["quantity"]) for c in decks.get(db, d1)["cards"]} == {foil: ("foil", 2), plain: ("nonfoil", 1)}
    for bad in ("shiny", "etched"):  # not a finish / a finish the printing does not have
        with pytest.raises(ValueError):
            decks.add_card(db, d1, oid, 1, scryfall_id=sid, finish=bad)
    with pytest.raises(ValueError):  # a finish needs a printing
        decks.add_card(db, d1, oid, 1, finish="foil")
    assert decks.update_card(db, d1, foil, finish="nonfoil") == plain  # changing the finish onto an existing row merges them
    assert _card(db, d1, plain)["quantity"] == 3
    other = db.execute("SELECT id FROM cards WHERE oracle_id=? AND id != ? LIMIT 1", (oid, sid)).fetchone()
    if other:  # another printing without a finish given drops it
        decks.update_card(db, d1, plain, scryfall_id=other[0])
        assert _card(db, d1, plain)["finish"] is None
    assert decks.duplicate(db, d1) != d1


def test_add_copy_of_the_chosen_printing_even_when_another_is_owned(db):
    oid, sid, row, d1, d2 = _setup(db, qty=1)  # you own one copy of printing `sid`
    cols = [r[1] for r in db.execute("PRAGMA table_info(cards)")]  # a second printing of the same card
    db.execute(f"INSERT INTO cards ({','.join(cols)}) SELECT {','.join(repr('second-print') if k == 'id' else k for k in cols)} FROM cards WHERE id=?", (sid,))
    other = ("second-print",)
    c = decks.add_card(db, d1, oid, 1, scryfall_id=other[0])
    assert _card(db, d1, c)["missing"] == 0  # owned in another printing: nothing is "missing"
    assert decks.add_missing(db, d1) == 0
    assert decks.add_copy(db, d1, c, 1, "Box") == 1
    mine = db.execute("SELECT scryfall_id, location, quantity FROM collection WHERE scryfall_id=?", (other[0],)).fetchone()
    assert (mine["location"], mine["quantity"]) == ("Deck: D1", 1)  # assigned: it is in the deck's location, not the one asked for
    assert _card(db, d1, c)["assigned"] == 1  # and it is assigned to the card
    for bad in (0, 1000, "x"):
        with pytest.raises(ValueError):
            decks.add_copy(db, d1, c, bad)
    anyc = decks.add_card(db, d1, oid, 1, "side")  # no printing chosen
    with pytest.raises(ValueError):
        decks.add_copy(db, d1, anyc)
    with pytest.raises(KeyError):
        decks.add_copy(db, d2, c)  # not a card of that deck


def test_a_card_can_have_several_lines_each_with_its_own_printing(db):
    oid, sid, row, d1, d2 = _setup(db)
    cols = [r[1] for r in db.execute("PRAGMA table_info(cards)")]  # a second printing of the same card
    db.execute(f"INSERT INTO cards ({','.join(cols)}) SELECT {','.join(repr('art-2') if k == 'id' else k for k in cols)} FROM cards WHERE id=?", (sid,))
    a = decks.add_card(db, d1, oid, 4, "main")
    assert decks.add_card(db, d1, oid, 1, "main") == a  # by default it sums into the line
    b = decks.add_card(db, d1, oid, 1, "main", new_line=True)  # or it gets a line of its own
    assert b != a and _card(db, d1, a)["quantity"] == 5
    c = decks.duplicate_line(db, d1, a)  # one more copy as a new line, same board and tags
    assert c not in (a, b) and _card(db, d1, c)["quantity"] == 1 and decks.get(db, d1)["summary"]["cards"] == 7
    decks.update_card(db, d1, b, quantity=3)  # editing a line does not merge it into its twin
    assert (_card(db, d1, a)["quantity"], _card(db, d1, b)["quantity"]) == (5, 3)
    decks.update_card(db, d1, c, scryfall_id="art-2")  # another art for that line
    assert _card(db, d1, c)["scryfall_id"] == "art-2"
    decks.update_card(db, d1, b, scryfall_id="art-2")  # onto a line that already has that art: they merge
    assert _card(db, d1, c)["quantity"] == 4 and not any(x["id"] == b for x in decks.get(db, d1)["cards"])
    with pytest.raises(KeyError):
        decks.duplicate_line(db, d2, a)


def test_a_deck_card_shows_the_printing_and_finish_of_its_assigned_copies(db):
    oid, sid, row, d1, d2 = _setup(db, qty=2)
    foil = collection.add(db, scryfall_id=sid, quantity=1, finish="foil")
    c = decks.add_card(db, d1, oid, 3)  # no printing chosen
    assert _card(db, d1, c)["owned_prints"] == []
    decks.assign(db, d1, c, [{"collection_id": row, "quantity": 2}, {"collection_id": foil, "quantity": 1}])
    got = _card(db, d1, c)
    assert [(p["scryfall_id"], p["finish"], p["quantity"]) for p in got["owned_prints"]] == [(sid, "nonfoil", 2), (sid, "foil", 1)]  # the most copies first
    assert got["image_id"] == sid and got["assignments"] == [{"collection_id": row, "quantity": 2}, {"collection_id": foil, "quantity": 1}]
    decks.assign(db, d1, c, [])  # nothing assigned: nothing to show again
    assert _card(db, d1, c)["owned_prints"] == []

def test_default_printing_and_filling_the_lines_without_one(db):
    oid, sid, row, d1, d2 = _setup(db, qty=2)
    cols = [r[1] for r in db.execute("PRAGMA table_info(cards)")]  # a second printing, cheaper than the one you own
    db.execute(f"INSERT INTO cards ({','.join(cols)}) SELECT {','.join(repr('cheap') if k == 'id' else k for k in cols)} FROM cards WHERE id=?", (sid,))
    db.execute("UPDATE cards SET eur=0.01 WHERE id='cheap'")
    assert decks.default_printing(db, oid) == (sid, "nonfoil")  # you own it: that one, whatever it costs
    other = db.execute("SELECT id, oracle_id FROM cards WHERE oracle_id != ? AND image_small IS NOT NULL LIMIT 1", (oid,)).fetchone()
    assert decks.default_printing(db, other["oracle_id"])[0] == other["id"]  # not owned: the cheapest (the only one here)
    assert decks.default_printing(db, "no-such-card") == (None, None)
    a, b = decks.add_card(db, d1, oid, 1), decks.add_card(db, d1, other["oracle_id"], 1)  # two lines without a printing
    foil = collection.add(db, scryfall_id="cheap", quantity=1, finish="foil")
    decks.assign(db, d1, a, [{"collection_id": foil, "quantity": 1}])  # a is assigned a foil copy of the cheap printing
    assert decks.fill_printings(db, d1) == 2
    assert (_card(db, d1, a)["scryfall_id"], _card(db, d1, a)["finish"]) == ("cheap", "foil")  # it follows its assigned copy
    assert _card(db, d1, b)["scryfall_id"] == other["id"]
    assert decks.fill_printings(db, d1) == 0  # nothing left to fill


def _location(db, row_id):
    return db.execute("SELECT location FROM collection WHERE id=?", (row_id,)).fetchone()[0]


def test_take_a_copy_from_another_deck(db):
    oid, sid, row, d1, d2 = _setup(db, qty=1)
    c1, c2 = decks.add_card(db, d1, oid, 1), decks.add_card(db, d2, oid, 1)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    assert _location(db, row) == "Deck: D1" and _card(db, d2, c2)["status"] == "elsewhere"
    assert decks.move_copy(db, d2, c2, d1, row, 1) == 1
    assert (_card(db, d2, c2)["status"], _card(db, d1, c1)["status"], _card(db, d1, c1)["missing"]) == ("assigned", "elsewhere", 1)  # D1 asks again: now D2 holds the copy
    assert _location(db, row) == "Deck: D2"  # the copy follows into the new deck's location
    assert decks.get(db, d2)["cards"][0]["assignments"] == [{"collection_id": row, "quantity": 1}]


def test_take_part_of_a_row_splits_it(db):
    oid, sid, row, d1, d2 = _setup(db, qty=3)
    c1, c2 = decks.add_card(db, d1, oid, 2), decks.add_card(db, d2, oid, 2)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 2}])
    held = _card(db, d1, c1)["assignments"][0]["collection_id"]  # assigning split the row: D1's copies are on the new row
    decks.move_copy(db, d2, c2, d1, held, 1)
    a, b = _card(db, d1, c1), _card(db, d2, c2)
    assert (a["assigned"], b["assigned"]) == (1, 1)
    locs = {r["location"]: r["quantity"] for r in db.execute("SELECT location, quantity FROM collection WHERE scryfall_id=?", (sid,))}
    assert locs == {"Deck: D1": 1, "Deck: D2": 1, "": 1}  # one copy per deck, one free


def test_take_is_refused_when_it_does_not_add_up(db):
    oid, sid, row, d1, d2 = _setup(db, qty=2)
    c1, c2 = decks.add_card(db, d1, oid, 1), decks.add_card(db, d2, oid, 1)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    held = _card(db, d1, c1)["assignments"][0]["collection_id"]
    for args in ((d2, c2, d2, held, 1), (d2, c2, d1, held, 2), (d2, c2, d1, held, 0), (d2, c2, d1, 999, 1), (d2, 999, d1, held, 1)):
        with pytest.raises((ValueError, KeyError)):
            decks.move_copy(db, *args)
    free = next(r["id"] for r in decks.copies(db, d2, c2)["rows"] if r["free"])
    decks.assign(db, d2, c2, [{"collection_id": free, "quantity": 1}])  # D2 is full now
    held = _card(db, d1, c1)["assignments"][0]["collection_id"]
    with pytest.raises(ValueError, match="cannot assign"):
        decks.move_copy(db, d2, c2, d1, held, 1)
    assert _card(db, d1, c1)["assigned"] == 1  # nothing changed


def test_take_route(db):
    oid, sid, row, d1, d2 = _setup(db, qty=1)
    c1, c2 = decks.add_card(db, d1, oid, 1), decks.add_card(db, d2, oid, 1)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    assert c.post(f"/api/decks/{d2}/cards/{c2}/take", json={"from_deck_id": d1, "collection_id": row}).json() == {"moved": 1}
    assert c.post(f"/api/decks/{d2}/cards/{c2}/take", json={"from_deck_id": d1, "collection_id": row}).status_code == 422


def _second_printing(db, sid, new_id, finishes='["nonfoil"]'):
    cols = [r[1] for r in db.execute("PRAGMA table_info(cards)")]
    db.execute(f"INSERT INTO cards ({','.join(cols)}) SELECT {','.join(repr(new_id) if k == 'id' else k for k in cols)} FROM cards WHERE id=?", (sid,))
    db.execute("UPDATE cards SET finishes=? WHERE id=?", (finishes, new_id))


def test_collection_row_changes_printing_and_keeps_its_deck_assignment(db):
    oid, sid, row, d1, _ = _setup(db, qty=2)
    _second_printing(db, sid, "second-print", '["nonfoil", "foil"]')
    c1 = decks.add_card(db, d1, oid, 1)
    decks.assign(db, d1, c1, [{"collection_id": row, "quantity": 1}])
    held = _card(db, d1, c1)["assignments"][0]["collection_id"]  # the assigned copy moved to the deck's location: a row of its own
    assert collection.update(db, held, scryfall_id="second-print") == held
    got = db.execute("SELECT scryfall_id, finish, location FROM collection WHERE id=?", (held,)).fetchone()
    assert tuple(got) == ("second-print", "nonfoil", "Deck: D1")
    assert _card(db, d1, c1)["assigned"] == 1  # the assignment is by card, not printing: it followed the row
    foil = collection.add(db, scryfall_id=sid, quantity=1, finish="foil")  # a foil of the first printing
    assert collection.update(db, foil, scryfall_id="second-print", finish="foil") == foil
    twin = collection.add(db, scryfall_id=sid, quantity=3, location="Deck: D1")
    assert collection.update(db, twin, scryfall_id="second-print") == held  # same key as the assigned row: merged into it
    assert db.execute("SELECT quantity FROM collection WHERE id=?", (held,)).fetchone()[0] == 4
    assert _card(db, d1, c1)["assigned"] == 1


def test_collection_printing_must_be_the_same_card_and_finish(db):
    oid, sid, row, *_ = _setup(db)
    _second_printing(db, sid, "second-print")  # nonfoil only
    other_card = db.execute("SELECT id FROM cards WHERE oracle_id != ? AND oracle_id != 'o-dfc' LIMIT 1", (oid,)).fetchone()[0]
    for bad, kw in (("nope", {}), (other_card, {}), ("second-print", {"finish": "foil"})):
        with pytest.raises(ValueError):
            collection.update(db, row, scryfall_id=bad, **kw)
    assert db.execute("SELECT scryfall_id FROM collection WHERE id=?", (row,)).fetchone()[0] == sid  # nothing changed
    foil = collection.add(db, scryfall_id=sid, quantity=1, finish="foil")  # the new printing has no foil: the finish falls back
    collection.update(db, foil, scryfall_id="second-print")
    assert db.execute("SELECT finish FROM collection WHERE id=?", (foil,)).fetchone()[0] == "nonfoil"
