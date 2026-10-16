import pytest

from scrybinder import collection, decks


def _setup(db, qty=3):
    oid = db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT 1").fetchone()[0]
    sid = db.execute("SELECT id FROM cards WHERE oracle_id=?", (oid,)).fetchone()[0]
    return oid, sid, collection.add(db, scryfall_id=sid, quantity=qty, location="Box"), decks.create(db, "Mono")


def _where(db):
    return {r[0]: r[1] for r in db.execute("SELECT location, SUM(quantity) FROM collection GROUP BY location")}


def test_assigning_moves_copies_into_the_deck_location_and_removing_moves_them_out(db):
    oid, sid, row, d = _setup(db)
    assert {l["location"]: l["deck_id"] for l in collection.locations(db)}["Deck: Mono"] == d  # a deck is a location from the start
    c = decks.add_card(db, d, oid, 2)
    assert _where(db) == {"Box": 3}  # nothing is moved by adding the card
    decks.assign_free(db, d)
    assert _where(db) == {"Box": 1, "Deck: Mono": 2}  # the row was split
    decks.update_card(db, d, c, quantity=1)
    assert _where(db) == {"Box": 1, "Deck: Mono": 1, "": 1}  # the copy that is no longer needed goes to (no location)
    decks.remove_card(db, d, c)
    assert _where(db) == {"Box": 1, "": 2}


def test_a_copy_taken_by_another_deck_stays_there(db):
    oid, sid, row, d1 = _setup(db, qty=2)
    d2 = decks.create(db, "Other")
    c1 = decks.add_card(db, d1, oid, 2)
    decks.assign_free(db, d1)
    decks.update_card(db, d1, c1, quantity=1)
    decks.add_card(db, d2, oid, 1)
    decks.assign_free(db, d2)  # takes the copy the first deck let go
    assert _where(db) == {"Deck: Mono": 1, "Deck: Other": 1}
    decks.remove_card(db, d1, c1)
    assert _where(db) == {"": 1, "Deck: Other": 1}


def test_renaming_and_deleting_a_deck_follows_its_location(db):
    oid, sid, row, d = _setup(db, qty=1)
    decks.add_card(db, d, oid, 1)
    decks.assign_free(db, d)
    decks.update(db, d, name="Renamed")
    assert _where(db) == {"Deck: Renamed": 1}
    decks.delete(db, d)
    assert _where(db) == {"": 1}
    assert "Deck: Renamed" not in [l["location"] for l in collection.locations(db)]


def test_delete_location_moves_or_deletes_and_refuses_decks(db):
    oid, sid, row, d = _setup(db, qty=2)
    assert collection.delete_location(db, "Box") == {"moved": 2}
    assert _where(db) == {"": 2}
    collection.add(db, scryfall_id=sid, quantity=1, location="Gone")
    assert collection.delete_location(db, "Gone", delete_cards=True) == {"deleted": 1}
    assert _where(db) == {"": 2}
    for bad in ("Deck: Mono", ""):
        with pytest.raises(ValueError):
            collection.delete_location(db, bad)
    with pytest.raises(ValueError):
        collection.create_location(db, "Deck: mine")  # the prefix is for decks
    decks.add_card(db, d, oid, 1)
    decks.assign_free(db, d)
    held = db.execute("SELECT id FROM collection WHERE location='Deck: Mono'").fetchone()[0]
    collection.move(db, held, "Held")  # moved by hand: it is still assigned
    with pytest.raises(decks.Conflict):
        collection.delete_location(db, "Held", delete_cards=True)
    assert collection.delete_location(db, "Held", delete_cards=True, release=True) == {"deleted": 1}
    assert _where(db) == {"": 1}


def test_a_change_only_moves_the_copies_it_touched(db):
    oid, sid, row, d = _setup(db, qty=2)
    c = decks.add_card(db, d, oid, 1)
    db.execute("INSERT INTO deck_assignments VALUES (?,?,1)", (c, row))  # assigned before decks had a location of their own
    other_sid, other = db.execute("SELECT id, oracle_id FROM cards WHERE oracle_id NOT IN (?, 'o-dfc') LIMIT 1", (oid,)).fetchone()
    collection.add(db, scryfall_id=other_sid, quantity=1, location="Shelf")
    decks.add_card(db, d, other, 1)
    decks.assign_free(db, d)  # takes the other card's copy
    assert _where(db) == {"Box": 2, "Deck: Mono": 1}  # the old assignment stays where it was
    decks.update_card(db, d, c, quantity=2)
    decks.assign_free(db, d)  # this card gets its second copy: its assignment changed, so the row moves
    assert _where(db) == {"Deck: Mono": 3}


def test_decks_with_the_same_name_get_a_suffix_and_keep_their_cards(db):
    oid, sid, row, a = _setup(db, qty=2)
    b = decks.create(db, "Mono")
    assert {l["location"]: l["deck_id"] for l in collection.locations(db) if l["deck_id"]} == {"Deck: Mono": a, "Deck: Mono (2)": b}
    for d in (a, b):
        decks.add_card(db, d, oid, 1)
        decks.assign_free(db, d)
    assert _where(db) == {"Deck: Mono": 1, "Deck: Mono (2)": 1}  # not merged
    decks.delete(db, a)  # the second deck moves up to the plain name, with its card
    assert _where(db) == {"": 1, "Deck: Mono": 1}
    decks.update(db, b, name="Other")
    assert _where(db) == {"": 1, "Deck: Other": 1}


def test_merge_locations_joins_rows_and_keeps_deck_locations_out(db):
    oid, sid, row, d = _setup(db, qty=1)
    collection.add(db, scryfall_id=sid, quantity=2, location="B")
    collection.add(db, scryfall_id=sid, quantity=4, location="C")
    collection.create_location(db, "Empty")
    assert collection.merge_locations(db, ["Box", "B", "Empty"], "  Big box ") == {"moved": 3}
    assert _where(db) == {"Big box": 3, "C": 4}  # identical rows joined
    assert "Empty" not in [l["location"] for l in collection.locations(db)] and "Big box" in [l["location"] for l in collection.locations(db)]
    assert collection.merge_locations(db, ["C", "Big box"], "C") == {"moved": 7} and _where(db) == {"C": 7}  # into one of them
    for names, into in ((["C"], "X"), (["C", "Deck: Mono"], "X"), (["C", "x"], "Deck: new"), (["C", "x"], "  "), ("C", "X")):
        with pytest.raises(ValueError):
            collection.merge_locations(db, names, into)
