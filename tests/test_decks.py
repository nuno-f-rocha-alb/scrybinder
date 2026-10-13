import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks, scryfall
from scrybinder.api import create_app

TOKEN = "t"


def _two_oracles(db):
    return [r[0] for r in db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT 2")]


def test_card_merge_validation_and_tags(db):
    d = decks.create(db, "  Test ", "commander")
    a, b = _two_oracles(db)
    c1 = decks.add_card(db, d, a, 2, tags=["Ramp", " ramp ", "Draw  Cards"])
    assert decks.add_card(db, d, a, 1, tags=["removal"]) == c1  # same card, board and printing: summed
    card = decks.get(db, d)["cards"][0]
    assert card["quantity"] == 3 and card["tags"] == ["draw cards", "ramp", "removal"]
    assert decks.add_card(db, d, a, 1, board="side") != c1  # another board is another card
    for bad in (dict(oracle_id="nope"), dict(oracle_id=a, quantity=0), dict(oracle_id=a, board="x"), dict(oracle_id=a, tags=["x" * 31]),
                dict(oracle_id=a, scryfall_id="dfc-1"), dict(oracle_id=a, tags="ramp"), dict(oracle_id=a, quantity=None)):
        with pytest.raises(ValueError):
            decks.add_card(db, d, **bad)
    with pytest.raises(ValueError):
        decks.create(db, "  ")
    with pytest.raises(ValueError):
        decks.create(db, "x", "nope")
    with pytest.raises(KeyError):
        decks.add_card(db, 999, a)
    # moving onto an existing card merges quantity and tags
    c3 = decks.add_card(db, d, b, 1, board="maybe", tags=["x"])
    sid = db.execute("SELECT id FROM cards WHERE oracle_id=?", (b,)).fetchone()[0]
    assert decks.update_card(db, d, c3, board="main", scryfall_id=sid, quantity=2) == c3
    assert decks.add_card(db, d, b, 1, scryfall_id=sid) == c3
    assert {c["id"]: c["quantity"] for c in decks.get(db, d)["cards"]}[c3] == 3
    other = decks.add_card(db, d, b, 1, board="side", scryfall_id=sid)
    assert decks.update_card(db, d, c3, board="side") == other  # merged into the sideboard card
    assert {c["id"]: c["quantity"] for c in decks.get(db, d)["cards"]}[other] == 4 and c3 not in {c["id"] for c in decks.get(db, d)["cards"]}
    with pytest.raises(KeyError):
        decks.remove_card(db, d + 1, c1)


def test_status_summary_and_proxy(db):
    d = decks.create(db, "D")
    a, b = _two_oracles(db)
    sid_a = db.execute("SELECT id FROM cards WHERE oracle_id=?", (a,)).fetchone()[0]
    sid_b = db.execute("SELECT id FROM cards WHERE oracle_id=?", (b,)).fetchone()[0]
    collection.add(db, scryfall_id=sid_a, quantity=2)
    collection.add(db, scryfall_id=sid_b, quantity=5, proxy=1)  # proxy rows of the collection are not real copies
    ca = decks.add_card(db, d, a, 3)
    cb = decks.add_card(db, d, b, 1)
    cm = decks.add_card(db, d, a, 4, board="maybe")
    st = {c["id"]: c for c in decks.get(db, d)["cards"]}
    assert (st[ca]["status"], st[ca]["owned"], st[ca]["missing"]) == ("partial", 2, 1)
    assert (st[cb]["status"], st[cb]["owned"]) == ("missing", 0)
    s = decks.get(db, d)["summary"]
    assert (s["cards"], s["complete"], s["missing"], s["proxies"]) == (4, 0, 2, 0)  # maybe is ignored
    assert s["cost_to_complete"] == 3.0  # 2 missing x 1.50
    decks.update_card(db, d, cb, tags=["proxy"])
    s = decks.get(db, d)["summary"]
    assert (s["complete"], s["missing"], s["proxies"], s["cost_to_complete"]) == (1, 1, 1, 1.5)
    assert {c["id"]: c["status"] for c in decks.get(db, d)["cards"]}[cb] == "proxy"
    collection.add(db, scryfall_id=sid_a, quantity=1, location="X")
    assert {c["id"]: c["status"] for c in decks.get(db, d)["cards"]}[ca] == "complete"


def test_duplicate_delete_and_rebulk(db, bulk_file):
    d = decks.create(db, "D", "modern", "desc")
    a, _ = _two_oracles(db)
    decks.add_card(db, d, a, 2, tags=["ramp"])
    n = decks.duplicate(db, d)
    cp = decks.get(db, n)
    assert cp["name"] == "D (copy)" and cp["format"] == "modern" and cp["cards"][0]["tags"] == ["ramp"]
    decks.update(db, d, name="E", format="pauper")
    assert decks.get(db, d)["name"] == "E" and decks.get(db, n)["name"] == "D (copy)"
    assert {x["name"] for x in decks.listing(db)} == {"E", "D (copy)"}
    scryfall.import_bulk(db, bulk_file)  # refreshing the oracle rows must not touch decks
    assert decks.get(db, d)["cards"][0]["quantity"] == 2
    decks.delete(db, d)
    assert db.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM deck_card_tags").fetchone()[0] == 1
    with pytest.raises(KeyError):
        decks.get(db, d)


def test_decks_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    a, _ = _two_oracles(db)
    did = c.post("/api/decks", json={"name": "Api", "format": "commander"}).json()["id"]
    assert c.post("/api/decks", json={"name": ""}).status_code == 422
    cid = c.post(f"/api/decks/{did}/cards", json={"oracle_id": a, "quantity": 2, "tags": ["ramp"]}).json()["id"]
    assert c.post(f"/api/decks/{did}/cards", json={"oracle_id": "nope"}).status_code == 422
    assert c.patch(f"/api/decks/{did}/cards/{cid}", json={"quantity": 3}).status_code == 200
    assert c.patch(f"/api/decks/{did}/cards/999", json={"quantity": 3}).status_code == 404
    got = c.get(f"/api/decks/{did}").json()
    assert got["cards"][0]["quantity"] == 3 and got["summary"]["cards"] == 3
    assert c.get("/api/decks").json()[0]["summary"]["cards"] == 3
    assert c.patch(f"/api/decks/{did}", json={"format": "nope"}).status_code == 422
    assert c.post("/api/decks", json={"name": 5}).status_code == 422
    assert c.patch(f"/api/decks/{did}", json={"name": 5}).status_code == 422
    assert c.patch(f"/api/decks/{did}/cards/{cid}", json={"quantity": None}).status_code == 422
    assert c.post(f"/api/decks/{did}/duplicate").status_code == 200
    assert c.delete(f"/api/decks/{did}/cards/{cid}").status_code == 200
    assert c.delete(f"/api/decks/{did}").status_code == 200
    assert c.get(f"/api/decks/{did}").status_code == 404
