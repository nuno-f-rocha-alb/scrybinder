import json

from fastapi.testclient import TestClient

from scrybinder import cardmarket, decks
from scrybinder.api import create_app

LIST_EXP, OTHER_EXP, SECOND_LIST_EXP = 5911, 5173, 3494
MAIN, EXTRAS, ELSEWHERE = 900, 902, 950  # expansions of the set 'zzz': its main one, one with no linked card, and another set's


def _card(db, cid, name, set_code="plst", cm=None, eur=1.0, num=None, finishes='["nonfoil"]'):
    db.execute("INSERT INTO cards (id, name, set_code, set_name, collector_number, digital, cardmarket_id, eur, sf_eur, finishes)"
               " VALUES (?, ?, ?, 'x', ?, 0, ?, ?, ?, ?)", (cid, name, set_code, num or cid, cm, eur, eur, finishes))


def _files(tmp_path, products, guides):
    cat, guide = tmp_path / "products.json", tmp_path / "guide.json"
    cat.write_text(json.dumps({"products": [{"idProduct": i, "name": n, "idExpansion": e} for i, n, e in products]}), encoding="utf-8")
    guide.write_text(json.dumps({"priceGuides": guides}), encoding="utf-8")
    return cat, guide


def _on(db):
    cardmarket.set_options(db, True)


def test_prices_follow_the_chosen_metric_and_switch_off(db, tmp_path):
    _card(db, "a", "Alpha", "zzz", cm=7001, eur=9.0)
    _card(db, "b", "Beta", "zzz", cm=None, eur=2.0)  # no Cardmarket product: Scryfall's price stays
    db.commit()
    guide = [{"idProduct": 7001, "avg": 2.5, "low": 1.0, "trend": 3.0, "avg-foil": 5.0, "low-foil": 4.0, "trend-foil": 6.0}]
    _, g = _files(tmp_path, [], guide)
    cardmarket.load_guide(db, g)
    cardmarket.apply(db)  # off: nothing changes
    assert db.execute("SELECT eur FROM cards WHERE id='a'").fetchone()[0] == 9.0
    _on(db)
    row = db.execute("SELECT eur, eur_foil, cm_low, cm_avg, cm_trend, cm_low_foil FROM cards WHERE id='a'").fetchone()
    assert tuple(row) == (3.0, 6.0, 1.0, 2.5, 3.0, 4.0)  # trend by default, all three kept
    assert db.execute("SELECT eur, cm_trend FROM cards WHERE id='b'").fetchone()[:] == (2.0, None)
    cardmarket.set_options(db, collection="low")
    assert tuple(db.execute("SELECT eur, eur_foil FROM cards WHERE id='a'").fetchone()) == (1.0, 4.0)
    cardmarket.set_options(db, enabled_=False)
    assert tuple(db.execute("SELECT eur, cm_trend FROM cards WHERE id='a'").fetchone()) == (9.0, None)  # Scryfall's own again


def test_decks_use_their_own_metric(db, tmp_path):
    _card(db, "a", "Alpha", "zzz", cm=7001, eur=9.0)
    db.execute("INSERT INTO oracle_cards (oracle_id, name) VALUES ('o-a', 'Alpha')")
    db.execute("UPDATE cards SET oracle_id='o-a' WHERE id='a'")
    db.commit()
    guide = [{"idProduct": 7001, "avg": 2.5, "low": 1.0, "trend": 3.0}]
    _, g = _files(tmp_path, [], guide)
    cardmarket.load_guide(db, g)
    _on(db)
    cardmarket.set_options(db, collection="trend", deck="avg")
    d = decks.create(db, "D")
    decks.add_card(db, d, "o-a", 1, scryfall_id="a")
    assert decks.get(db, d)["cards"][0]["price"] == 2.5  # the deck's choice, not the collection's
    assert db.execute("SELECT eur FROM cards WHERE id='a'").fetchone()[0] == 3.0


def test_list_cards_without_a_product_are_linked_by_name(db, tmp_path):
    for i in range(2 * cardmarket.MIN_LIST_CARDS):  # known List cards make LIST_EXP and SECOND_LIST_EXP count as The List's
        _card(db, f"k{i}", f"Known {i}", cm=100 + i)
    _card(db, "volcano", "Urborg Volcano")  # Scryfall has no product for it
    _card(db, "twice", "In Two Lists")
    _card(db, "nowhere", "Only Elsewhere")
    db.commit()
    products = [(100 + i, f"Known {i}", LIST_EXP if i % 2 else SECOND_LIST_EXP) for i in range(2 * cardmarket.MIN_LIST_CARDS)]
    products += [(793224, "Urborg Volcano", LIST_EXP), (689234, "Urborg Volcano", OTHER_EXP),  # the other one is not in a List expansion
                 (1, "In Two Lists", LIST_EXP), (2, "In Two Lists", SECOND_LIST_EXP), (3, "Only Elsewhere", OTHER_EXP)]
    cat, guide = _files(tmp_path, products, [{"idProduct": 793224, "avg": 0.19, "low": 0.03, "trend": 0.24}])
    assert cardmarket.link_list(db, cat) == 1  # the volcano alone: a name in two List expansions could be either printing
    cardmarket.load_guide(db, guide)
    _on(db)
    row = db.execute("SELECT eur, cm_low, cm_avg, cm_trend FROM cards WHERE id='volcano'").fetchone()
    assert tuple(row) == (0.24, 0.03, 0.19, 0.24)
    assert [r[0] for r in db.execute("SELECT cm_trend FROM cards WHERE id IN ('twice', 'nowhere')")] == [None, None]


def test_a_product_another_list_card_already_has_is_not_this_ones(db, tmp_path):
    for i in range(2 * cardmarket.MIN_LIST_CARDS):
        _card(db, f"k{i}", f"Known {i}", cm=100 + i)
    _card(db, "shift-a", "Reality Shift", cm=1)  # Scryfall linked this printing to product 1 (second List expansion)
    _card(db, "shift-b", "Reality Shift")  # so this one is product 2
    _card(db, "geist-a", "Vile Requiem")  # two printings without a product, two products: which is which is unknown
    _card(db, "geist-b", "Vile Requiem")
    _card(db, "rebuff", "Rebuff the Wicked")  # one printing, two products, none taken
    db.commit()
    products = [(100 + i, f"Known {i}", LIST_EXP if i % 2 else SECOND_LIST_EXP) for i in range(2 * cardmarket.MIN_LIST_CARDS)]
    products += [(1, "Reality Shift", SECOND_LIST_EXP), (2, "Reality Shift", LIST_EXP), (3, "Vile Requiem", LIST_EXP), (4, "Vile Requiem", SECOND_LIST_EXP),
                 (5, "Rebuff the Wicked", LIST_EXP), (6, "Rebuff the Wicked", SECOND_LIST_EXP)]
    cat, _ = _files(tmp_path, products, [])
    assert cardmarket.link_list(db, cat) == 1
    assert dict(db.execute("SELECT scryfall_id, id_product FROM cm_link").fetchall()) == {"shift-b": 2}


def _set_zzz(db, extra=()):
    """12 printings Scryfall linked (products 200+i of MAIN) make MAIN the expansion of 'zzz'; `extra` printings come without a product."""
    for i in range(12):
        _card(db, f"k{i}", f"Known {i}", "zzz", cm=200 + i)
    for args in extra:
        _card(db, *args[:3], **(args[3] if len(args) > 3 else {}))
    db.commit()
    return [(200 + i, f"Known {i}", MAIN) for i in range(12)] + [(500 + i, f"Other {i}", ELSEWHERE) for i in range(12)]


def _linked(db):
    return dict(db.execute("SELECT scryfall_id, id_product FROM cm_link").fetchall())


def test_printings_without_a_product_are_linked_inside_their_own_expansions(db, tmp_path):
    products = _set_zzz(db, [("lost", "Lost Card", "zzz"), ("quote", 'Dr. "Bones"', "zzz"), ("both", "Front Face // Back Face", "zzz"),
                             ("twice-a", "Printed Twice", "zzz"), ("twice-b", "Printed Twice", "zzz"), ("two", "Two Products", "zzz"),
                             ("land", "Plains", "zzz"), ("none", "No Product", "zzz"), ("away", "Other Set Only", "zzz"),
                             ("extra", "In The Extras", "zzz")])
    for i in range(12):  # the other set's expansion: its linked printings say whose it is
        _card(db, f"o{i}", f"Other {i}", "yyy", cm=500 + i)
    products += [(9001, "Lost Card", MAIN), (9002, "Lost Card", ELSEWHERE),  # the second is another set's reprint
                 (9003, 'Dr. ""Bones""', MAIN),  # the file doubles the quotes
                 (9004, "Front Face", MAIN), (9005, "Printed Twice", MAIN), (9006, "Printed Twice", MAIN), (9007, "Two Products", MAIN), (9008, "Two Products", MAIN),
                 (9009, "Plains", MAIN), (9010, "Plains", MAIN), (9011, "Plains", MAIN), (9012, "Other Set Only", ELSEWHERE)]
    products += [(300 + i, f"Known {i}", EXTRAS) for i in range(10)] + [(9013, "In The Extras", EXTRAS)]  # no printing linked there: its names say 'zzz'
    cat, _ = _files(tmp_path, products, [])
    assert cardmarket.link_printings(db, cat) == 4
    assert _linked(db) == {"lost": 9001, "quote": 9003, "both": 9004, "extra": 9013}


def test_a_foil_only_twin_takes_its_cards_product_unless_the_set_splits_them(db, tmp_path):
    products = _set_zzz(db, [("c1", "Twin One", "zzz", {"cm": 600, "num": "5"}), ("t1", "Twin One", "zzz", {"num": "5★", "finishes": '["foil"]'}),
                             ("c2", "Twin Two", "zzz", {"cm": 601, "num": "6"}), ("t2", "Twin Two", "zzz", {"num": "6★", "finishes": '["foil"]'}),
                             ("nf", "Twin Three", "zzz", {"cm": 602, "num": "7"}), ("t3", "Twin Three", "zzz", {"num": "7★"})])
    cat, _ = _files(tmp_path, products + [(600, "Twin One", MAIN), (601, "Twin Two", MAIN), (602, "Twin Three", MAIN)], [])
    assert _linked(db) == {} and cardmarket.link_printings(db, cat) == 2
    assert _linked(db) == {"t1": 600, "t2": 601}  # not t3: it has a nonfoil finish, so it is not just the card's foil
    _card(db, "c4", "Twin Four", "zzz", cm=603, num="8")  # a twin Scryfall linked to a product of its own: this set keeps them apart
    _card(db, "t4", "Twin Four", "zzz", cm=604, num="8★", finishes='["foil"]')
    _card(db, "c5", "Twin Five", "zzz", cm=605, num="9")
    _card(db, "t5", "Twin Five", "zzz", num="9★", finishes='["foil"]')
    db.commit()
    db.execute("DELETE FROM cm_link")
    assert cardmarket.link_printings(db, cat) == 0


def test_linked_printings_get_the_cardmarket_price(db, tmp_path):
    products = _set_zzz(db, [("lost", "Lost Card", "zzz", {"eur": None})])
    cat, guide = _files(tmp_path, products + [(9001, "Lost Card", MAIN)], [{"idProduct": 9001, "avg": 0.9, "low": 0.5, "trend": 0.99}])
    cardmarket.load_guide(db, guide)
    cardmarket.link_printings(db, cat)
    _on(db)
    assert db.execute("SELECT eur, cm_low FROM cards WHERE id='lost'").fetchone()[:] == (0.99, 0.5)


def test_a_foil_only_printing_gets_no_nonfoil_price(db, tmp_path):
    _card(db, "f", "Foil Only", "zzz", cm=7002, eur=None, finishes='["foil"]')
    db.commit()
    _, g = _files(tmp_path, [], [{"idProduct": 7002, "avg": 2.0, "low": 1.0, "trend": 3.0, "avg-foil": 5.0, "low-foil": 4.0, "trend-foil": 6.0}])
    cardmarket.load_guide(db, g)
    _on(db)
    assert tuple(db.execute("SELECT eur, eur_foil, cm_trend, cm_trend_foil FROM cards WHERE id='f'").fetchone()) == (None, 6.0, None, 6.0)


def test_refresh_downloads_once_a_day_and_survives_a_new_bulk(db, tmp_path, monkeypatch):
    _card(db, "a", "Alpha", "zzz", cm=7001, eur=9.0)
    db.commit()
    cat, guide = _files(tmp_path, [(7001, "Alpha", 1)], [{"idProduct": 7001, "trend": 3.0, "avg": 2.0, "low": 1.0}])
    calls = []
    monkeypatch.setattr(cardmarket, "_download", lambda url, dest, progress=None: (calls.append(url), dest.parent.mkdir(parents=True, exist_ok=True),
                                                                               dest.write_bytes((cat if "products" in url else guide).read_bytes())))
    assert cardmarket.refresh(db, tmp_path / "data") is False and not calls  # off: no request
    _on(db)
    assert cardmarket.refresh(db, tmp_path / "data") is True and len(calls) == 2
    assert cardmarket.refresh(db, tmp_path / "data") is False and len(calls) == 2  # a day's cache
    assert db.execute("SELECT eur FROM cards WHERE id='a'").fetchone()[0] == 3.0
    bulk = tmp_path / "bulk.json"  # a Scryfall import puts its own prices back; Cardmarket's go over them again
    bulk.write_text(json.dumps([{"id": "a", "name": "Alpha", "set": "zzz", "cardmarket_id": 7001, "prices": {"eur": "9.00"}}]), encoding="utf-8")
    from scrybinder import scryfall
    scryfall.import_bulk(db, bulk)
    assert tuple(db.execute("SELECT eur, sf_eur FROM cards WHERE id='a'").fetchone()) == (3.0, 9.0)


def test_cardmarket_api(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    assert c.get("/api/cardmarket").json() == {"enabled": False, "collection": "trend", "deck": "trend", "updated_at": None, "metrics": ["trend", "avg", "low"]}
    assert c.post("/api/cardmarket", json={"collection": "cheap"}).status_code == 422
    r = c.post("/api/cardmarket", json={"collection": "low", "deck": "avg"}).json()
    assert (r["collection"], r["deck"], r["enabled"]) == ("low", "avg", False)  # no download until it is turned on
