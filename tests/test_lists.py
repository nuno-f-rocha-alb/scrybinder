import json

import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks, lists, share
from scrybinder.api import create_app


def _cards(db):
    return [r[0] for r in db.execute("SELECT id FROM cards WHERE id != 'dfc-1' ORDER BY id LIMIT 3")]


def test_list_holds_cards_you_own_and_cards_you_do_not(db):
    a, b, _ = _cards(db)
    row = collection.add(db, scryfall_id=a, quantity=2, location="Box")
    lid = lists.create(db, "Binder", "for the shop")
    assert lists.add_from_collection(db, lid, [row, 999]) == 2  # the missing row is ignored
    lists.add_items(db, lid, [{"scryfall_id": b, "finish": "foil", "quantity": 3}])
    g = lists.get(db, lid)
    by = {i["scryfall_id"]: i for i in g["items"]}
    assert (by[a]["quantity"], by[a]["owned"]) == (2, 2)
    assert (by[b]["quantity"], by[b]["owned"], by[b]["finish"]) == (3, 0, "foil")  # not owned: nothing to match
    assert (g["cards"], g["value"]) == (5, 12.0)  # 2 × 1.50 + 3 foil × 3.00
    assert lists.listing(db)[0]["lines"] == 2


def test_adding_again_sums_and_editing_into_another_line_merges(db):
    a, _, _ = _cards(db)
    lid = lists.create(db, "L")
    lists.add_items(db, lid, [{"scryfall_id": a}, {"scryfall_id": a, "quantity": 2}])
    items = lists.get(db, lid)["items"]
    assert [i["quantity"] for i in items] == [3]
    lists.add_items(db, lid, [{"scryfall_id": a, "finish": "foil"}])
    foil = next(i for i in lists.get(db, lid)["items"] if i["finish"] == "foil")
    lists.edit_item(db, lid, foil["id"], finish="nonfoil")
    assert [(i["finish"], i["quantity"]) for i in lists.get(db, lid)["items"]] == [("nonfoil", 4)]


def test_adding_is_all_or_nothing_and_validated(db):
    a, _, _ = _cards(db)
    lid = lists.create(db, "L")
    for bad in ([{"scryfall_id": "nope"}], [{"scryfall_id": a, "quantity": 0}], [{"scryfall_id": a, "finish": "etched"}],
                [{"scryfall_id": a, "condition": "XX"}], []):
        with pytest.raises(ValueError):
            lists.add_items(db, lid, bad)
    with pytest.raises(ValueError):
        lists.add_items(db, lid, [{"scryfall_id": a}, {"scryfall_id": "nope"}])
    assert lists.get(db, lid)["items"] == []
    with pytest.raises(ValueError, match="needs a name"):
        lists.create(db, "  ")


def test_collection_changes_do_not_touch_a_list(db):
    a, _, _ = _cards(db)
    row = collection.add(db, scryfall_id=a, quantity=2, location="Box")
    lid = lists.create(db, "L")
    lists.add_from_collection(db, lid, [row])
    collection.move(db, row, "Elsewhere")
    collection.delete(db, row)
    g = lists.get(db, lid)
    assert (g["items"][0]["quantity"], g["items"][0]["owned"]) == (2, 0)


def test_list_from_a_location_skips_proxies(db):
    a, b, _ = _cards(db)
    collection.add(db, scryfall_id=a, quantity=2, location="Binder")
    collection.add(db, scryfall_id=b, proxy=1, location="Binder")
    lid = lists.create_from_location(db, "Binder")
    g = lists.get(db, lid)
    assert g["name"] == "Binder" and [(i["scryfall_id"], i["quantity"]) for i in g["items"]] == [(a, 2)]
    with pytest.raises(ValueError, match="no cards"):
        lists.create_from_location(db, "Empty")


def test_exports(db):
    a, _, _ = _cards(db)
    lid = lists.create(db, "L")
    lists.add_items(db, lid, [{"scryfall_id": a, "quantity": 2, "finish": "foil"}])
    g = lists.get(db, lid)
    name, setc, cn = g["items"][0]["name"], g["items"][0]["set_code"].upper(), g["items"][0]["collector_number"]
    assert lists.text(g) == f"2 {name} ({setc}) {cn} *F*\n"
    assert lists.csv_text(g).splitlines()[1].startswith(f"2,{name}") or lists.csv_text(g).splitlines()[1].startswith(f'2,"{name}"')


def test_share_and_import_round_trip(db):
    a, b, _ = _cards(db)
    lid = lists.create(db, "Wants", "please")
    lists.add_items(db, lid, [{"scryfall_id": a, "quantity": 2, "condition": "LP"}, {"scryfall_id": b, "finish": "foil"}])
    doc = share.build(db, {"kind": "list", "list_id": lid, "prices": True})
    assert doc["kind"] == "list" and doc["note"] == "please" and doc["sections"][0]["cards"][0]["cond"] == "LP"
    got = share.import_text(db, json.dumps(doc))
    assert got["kind"] == "list" and got["cards"] == 3
    new = lists.get(db, got["list_id"])
    assert new["name"] == "Wants" and sorted((i["quantity"], i["finish"], i["condition"]) for i in new["items"]) == [(1, "foil", "NM"), (2, "nonfoil", "LP")]


def test_routes(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    a, b, _ = _cards(db)
    row = collection.add(db, scryfall_id=a, quantity=2)
    lid = c.post("/api/lists", json={"name": "Trade binder"}).json()["id"]
    assert c.post(f"/api/lists/{lid}/items", json={"collection_ids": [row]}).json() == {"added": 2}
    assert c.post(f"/api/lists/{lid}/items", json={"items": [{"scryfall_id": b}]}).json() == {"added": 1}
    assert c.post(f"/api/lists/{lid}/items", json={"items": [{"scryfall_id": "x"}]}).status_code == 422
    items = c.get(f"/api/lists/{lid}").json()["items"]
    assert c.patch(f"/api/lists/{lid}/items/{items[0]['id']}", json={"quantity": 5, "list_id": 9}).status_code == 200
    assert c.get(f"/api/lists/{lid}/export").text.startswith("5 ")
    assert c.get(f"/api/lists/{lid}/export?format=csv").text.startswith("Quantity,")
    assert c.patch(f"/api/lists/{lid}", json={"name": "Renamed", "id": 7}).status_code == 200
    assert c.get("/api/lists").json()[0]["name"] == "Renamed"
    assert c.delete(f"/api/lists/{lid}/items/{items[0]['id']}").status_code == 200
    assert c.delete(f"/api/lists/{lid}").status_code == 200 and c.get(f"/api/lists/{lid}").status_code == 404
    assert c.post("/api/lists/from-location", json={"location": "Nowhere"}).status_code == 422
