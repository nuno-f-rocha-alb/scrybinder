import csv
import io

from fastapi.testclient import TestClient

from scrybinder import collection, decks
from scrybinder.api import create_app

TOKEN = "t"


def _oracles(db):
    return [r[0] for r in db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' ORDER BY oracle_id LIMIT 2")]


def test_sums_missing_across_decks(db):
    a, _ = _oracles(db)
    d1, d2 = decks.create(db, "Beta"), decks.create(db, "Alpha")
    decks.add_card(db, d1, a, 2)
    decks.add_card(db, d2, a, 1)
    sl = decks.shopping_list(db)
    [it] = sl["items"]
    assert (it["oracle_id"], it["needed"], sl["total_needed"]) == (a, 3, 3)
    assert [(x["name"], x["needed"]) for x in it["decks"]] == [("Alpha", 1), ("Beta", 2)]  # decks in name order
    collection.add(db, scryfall_id=db.execute("SELECT id FROM cards WHERE oracle_id=?", (a,)).fetchone()[0], quantity=2)
    assert decks.shopping_list(db)["items"] == []  # each deck is covered by the owned copies (they are not shared out between decks)


def test_boards_and_proxies(db):
    a, b = _oracles(db)
    d = decks.create(db, "D")
    decks.add_card(db, d, a, 1, board="maybe")
    assert decks.shopping_list(db)["items"] == []
    decks.add_card(db, d, a, 1, board="side")
    assert decks.shopping_list(db)["items"] == []
    assert len(decks.shopping_list(db, include_side=True)["items"]) == 1
    cb = decks.add_card(db, d, b, 1)
    decks.update_card(db, d, cb, tags=["proxy"])
    assert [i["oracle_id"] for i in decks.shopping_list(db, include_side=True)["items"]] == [a]


def test_total_and_exports(db):
    a, b = _oracles(db)
    d = decks.create(db, "D")
    decks.add_card(db, d, a, 2)
    decks.add_card(db, d, b, 1)
    sl = decks.shopping_list(db)
    by = {i["oracle_id"]: i for i in sl["items"]}
    assert sl["total_value"] == round(sum(i["needed"] * (i["price"] or 0) for i in sl["items"]), 2)
    by[b]["price"] = None  # an unknown price adds nothing to the total
    by[a]["price"], by[a]["line_total"], by[b]["line_total"] = 1.5, 3.0, 0
    assert decks.shopping_text(sl) == "".join(f"{i['needed']} {i['name']}\n" for i in sorted(sl["items"], key=lambda i: i["name"].lower()))
    rows = list(csv.DictReader(io.StringIO(decks.shopping_csv(sl))))
    assert [r["quantity"] for r in rows] == [str(i["needed"]) for i in sl["items"]]
    assert next(r for r in rows if r["name"] == by[b]["name"])["price_eur"] == ""
    assert next(r for r in rows if r["name"] == by[a]["name"])["price_eur"] == "1.5"
    assert decks.shopping_csv({"items": []}) == "quantity,name,price_eur,cardmarket_id\n"
    assert decks.shopping_text({"items": []}) == ""


def test_shopping_list_api(db):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    assert c.get("/api/decks/shopping-list").json() == {"items": [], "total_needed": 0, "total_value": 0}
    a, _ = _oracles(db)
    did = c.post("/api/decks", json={"name": "Api"}).json()["id"]
    c.post(f"/api/decks/{did}/cards", json={"oracle_id": a, "quantity": 2})
    js = c.get("/api/decks/shopping-list").json()
    assert js["total_needed"] == 2 and js["items"][0]["decks"][0]["name"] == "Api"
    t = c.get("/api/decks/shopping-list?format=text")
    assert t.text.startswith("2 ") and "attachment" in t.headers["content-disposition"]
    v = c.get("/api/decks/shopping-list?format=csv")
    assert v.text.startswith("quantity,name,price_eur,cardmarket_id\n2,") and "attachment" in v.headers["content-disposition"]
