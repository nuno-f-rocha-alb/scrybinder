import csv
import gzip
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
    assert c.get("/api/cardmarket").json() == {"enabled": False, "collection": "trend", "deck": "trend", "updated_at": None, "metrics": ["trend", "avg", "low"], "mtgjson": False}
    assert c.post("/api/cardmarket", json={"collection": "cheap"}).status_code == 422
    r = c.post("/api/cardmarket", json={"collection": "low", "deck": "avg"}).json()
    assert (r["collection"], r["deck"], r["enabled"]) == ("low", "avg", False)  # no download until it is turned on


def _catalog(tmp_path, products):
    """products: (id, name, expansion, date added) -> a catalogue file loaded into cm_products."""
    cat = tmp_path / "products.json"
    cat.write_text(json.dumps({"products": [{"idProduct": i, "name": n, "idExpansion": e, "dateAdded": d} for i, n, e, d in products]}), encoding="utf-8")
    return cat


def _picker_data(db, tmp_path):
    """'trek' (no product) and 'known' (Scryfall's product 7001); three products called Bones, the nearest to trek's release first."""
    _card(db, "trek", 'Dr. "Bones"', "zzz", eur=None, num="421")
    db.execute("UPDATE cards SET released_at='2026-11-13' WHERE id='trek'")
    _card(db, "known", 'Dr. "Bones"', "zzz", cm=7001, num="197")
    db.commit()
    cat = _catalog(tmp_path, [(7001, 'Dr. ""Bones""', 1, "2026-11-13 10:00:00"), (7002, 'Dr. ""Bones""', 2, "2026-11-14 10:00:00"),
                              (7003, 'Dr. ""Bones""', 3, "2026-01-02 00:00:00"), (7004, "Bonesaw", 3, None)])
    cardmarket.load_catalog(db, cat)
    _, guide = _files(tmp_path, [], [{"idProduct": 7002, "avg": 1.2, "low": 0.5, "trend": 0.99, "trend-foil": 2.5}])
    cardmarket.load_guide(db, guide)
    return cat


def test_the_picker_searches_the_catalogue_by_name_nearest_release_first(db, tmp_path):
    _picker_data(db, tmp_path)
    found = cardmarket.search_products(db, '"Bones"', "trek")
    assert [r["id_product"] for r in found] == [7001, 7002, 7003]  # 'Bonesaw' has no quote: not a match
    assert found[1]["trend"] == 0.99 and found[1]["trend_foil"] == 2.5 and found[1]["date_added"] == "2026-11-14"
    assert found[0]["used_by"] == ["ZZZ #197"] and found[1]["used_by"] == []  # Scryfall gave 7001 to the other printing
    assert [r["id_product"] for r in cardmarket.search_products(db, "bones%")] == []  # % is a letter here, not a wildcard
    assert cardmarket.search_products(db, "b") == []  # too short to search
    assert [r["id_product"] for r in cardmarket.search_products(db, "7002")] == [7002]  # a pasted id
    assert [r["id_product"] for r in cardmarket.search_products(db, "https://www.cardmarket.com/en/Magic/Products?idProduct=7003")] == [7003]


def test_the_picker_asks_for_the_product_list_first(db):
    try:
        cardmarket.search_products(db, "anything")
    except ValueError as e:
        assert "not loaded" in str(e)
    else:
        raise AssertionError("expected a ValueError")


def test_a_picked_product_prices_the_printing_and_survives_updates(db, tmp_path):
    cat = _picker_data(db, tmp_path)
    _on(db)
    assert cardmarket.product_of(db, "trek") == {"id": None, "source": None}
    cardmarket.set_pick(db, "trek", 7002)
    assert cardmarket.product_of(db, "trek") == {"id": 7002, "source": "manual"}
    assert db.execute("SELECT cm_trend, eur FROM cards WHERE id='trek'").fetchone()[:] == (0.99, 0.99)
    cardmarket.link_list(db, cat)  # the updates that rebuild the guessed links leave the pick alone
    cardmarket.link_printings(db, cat)
    cardmarket.apply(db)
    assert cardmarket.product_of(db, "trek")["source"] == "manual" and db.execute("SELECT eur FROM cards WHERE id='trek'").fetchone()[0] == 0.99
    cardmarket.set_pick(db, "trek", None)
    assert cardmarket.product_of(db, "trek")["id"] is None and db.execute("SELECT eur FROM cards WHERE id='trek'").fetchone()[0] is None


def test_a_pick_is_refused_when_it_cannot_hold(db, tmp_path):
    _picker_data(db, tmp_path)
    for card, product, why in (("known", 7002, "already"), ("trek", 1234567, "no product")):
        try:
            cardmarket.set_pick(db, card, product)
        except ValueError as e:
            assert why in str(e)
        else:
            raise AssertionError("expected a ValueError")
    try:
        cardmarket.set_pick(db, "nobody", 7002)
    except KeyError:
        pass
    else:
        raise AssertionError("expected a KeyError")


def test_a_product_a_pick_holds_is_not_given_to_another_printing_by_name(db, tmp_path):
    products = _set_zzz(db, [("lost", "Lost Card", "zzz"), ("other", "Lost Card", "yyy")])
    cat = _catalog(tmp_path, [(i, n, e, None) for i, n, e in products + [(9001, "Lost Card", MAIN)]])
    cardmarket.load_catalog(db, cat)
    cardmarket.set_pick(db, "other", 9001)
    assert cardmarket.link_printings(db, cat) == 0 and _linked(db) == {}  # 9001 is taken: 'lost' stays unpriced rather than guess


def test_mtgjson_gives_products_that_the_user_can_still_override(db, tmp_path):
    _picker_data(db, tmp_path)
    _card(db, "other", "Elsewhere", "zzz", eur=None)
    db.commit()
    ids = tmp_path / "cardIdentifiers.csv.gz"
    with gzip.open(ids, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uuid", "scryfallId", "mcmId"])
        w.writerows([("u1", "trek", "7003"), ("u2", "known", "7002"), ("u3", "other", "99999"), ("u4", "nobody", "7001"), ("u5", "other", "")])
    assert cardmarket.load_mtgjson(db, ids) == 1  # not 'known' (Scryfall has its product), not an id the catalogue lacks, not a printing we lack
    assert cardmarket.product_of(db, "trek") == {"id": 7003, "source": "mtgjson"}
    cardmarket.set_pick(db, "trek", 7002)  # the user's word beats MTGJSON's, also after the next update
    cardmarket.load_mtgjson(db, ids)
    assert cardmarket.product_of(db, "trek") == {"id": 7002, "source": "manual"}
    cardmarket.set_options(db, True, mtgjson=True)
    assert cardmarket.settings(db)["mtgjson"] is True
    cardmarket.set_options(db, mtgjson=False)
    assert cardmarket.product_of(db, "trek")["source"] == "manual"  # turning MTGJSON off keeps only the user's picks
    cardmarket.set_pick(db, "trek", None)
    assert cardmarket.product_of(db, "trek")["id"] is None


def test_refresh_fetches_mtgjson_only_when_asked_and_fills_an_empty_product_list(db, tmp_path, monkeypatch):
    cat, guide = _files(tmp_path, [(7001, "Alpha", 1)], [{"idProduct": 7001, "trend": 3.0}])
    calls = []

    def fake(url, dest, progress=None):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url == cardmarket.MTGJSON_URL:
            with gzip.open(dest, "wt", encoding="utf-8", newline="") as f:
                f.write("scryfallId,mcmId\nlost,7001\n")
        else:
            dest.write_bytes((cat if "products" in url else guide).read_bytes())
    monkeypatch.setattr(cardmarket, "_download", fake)
    _card(db, "lost", "Alpha", "zzz", eur=None)
    db.commit()
    _on(db)
    assert cardmarket.refresh(db, tmp_path / "data") is True and cardmarket.MTGJSON_URL not in calls
    assert db.execute("SELECT COUNT(*) FROM cm_products").fetchone()[0] == 1
    db.execute("DELETE FROM cm_products")  # a database from before the picker: files kept, list empty
    db.commit()
    assert cardmarket.refresh(db, tmp_path / "data") is True and len(calls) == 2  # loaded again without downloading
    cardmarket.set_options(db, mtgjson=True)
    assert cardmarket.refresh(db, tmp_path / "data") is True and calls[-1] == cardmarket.MTGJSON_URL and len(calls) == 3
    assert cardmarket.product_of(db, "lost") == {"id": 7001, "source": "mtgjson"}
    assert db.execute("SELECT eur FROM cards WHERE id='lost'").fetchone()[0] == 3.0


def test_picker_api(db, tmp_path):
    _picker_data(db, tmp_path)
    _on(db)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    r = c.get("/api/cardmarket/products", params={"q": '"Bones"', "card": "trek"}).json()
    assert [x["id_product"] for x in r] == [7001, 7002, 7003]
    d = c.put("/api/cards/trek/cardmarket", json={"id_product": 7002}).json()
    assert (d["cm_product"], d["cm_source"], d["cm_enabled"], d["cm_trend"]) == (7002, "manual", True, 0.99)
    assert c.put("/api/cards/trek/cardmarket", json={"id_product": 1}).status_code == 422
    assert c.put("/api/cards/known/cardmarket", json={"id_product": 7002}).status_code == 422
    assert c.put("/api/cards/nobody/cardmarket", json={"id_product": 7002}).status_code == 404
    assert c.put("/api/cards/trek/cardmarket", json={"id_product": None}).json()["cm_product"] is None


def test_a_bad_id_is_a_422_and_an_mtgjson_outage_does_not_stop_the_prices(db, tmp_path, monkeypatch):
    _picker_data(db, tmp_path)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    assert c.put("/api/cards/trek/cardmarket", json={"id_product": "abc"}).status_code == 422
    cat, guide = _files(tmp_path, [(7001, "Alpha", 1)], [{"idProduct": 7001, "trend": 3.0}])

    def fake(url, dest, progress=None):
        if url == cardmarket.MTGJSON_URL:
            raise OSError("mtgjson.com is down")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((cat if "products" in url else guide).read_bytes())
    monkeypatch.setattr(cardmarket, "_download", fake)
    _on(db)
    cardmarket.set_options(db, mtgjson=True)
    assert cardmarket.refresh(db, tmp_path / "data") is True
    assert db.execute("SELECT COUNT(*) FROM cm_prices").fetchone()[0] == 1
