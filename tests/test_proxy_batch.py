from fastapi.testclient import TestClient

from scrybinder import collection, decks
from scrybinder.api import create_app


def _setup(db):
    d = decks.create(db, "D", "commander")
    out = []
    for oid, sid in db.execute("SELECT oracle_id, id FROM cards WHERE oracle_id != 'o-dfc' GROUP BY oracle_id LIMIT 3").fetchall():
        collection.add(db, scryfall_id=sid, quantity=2)
        out.append(decks.add_card(db, d, oid, 1, "main", sid, ["ramp"]))
    decks.assign_free(db, d)
    return d, out


def test_a_locked_database_answers_busy_not_500(db, monkeypatch):
    import sqlite3

    d, cards = _setup(db)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}), raise_server_exceptions=False)
    c.get("/api/status?t=t")

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(decks, "update_card", locked)
    r = c.patch(f"/api/decks/{d}/cards/{cards[0]}", json={"tags": ["proxy"]})
    assert r.status_code == 503 and "busy" in r.json()["detail"]


def test_marking_assigned_cards_as_proxy_one_after_another(db):
    d, cards = _setup(db)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    for cid in cards:
        r = c.patch(f"/api/decks/{d}/cards/{cid}", json={"tags": ["proxy", "ramp"]})
        assert r.status_code == 200, r.text
    assert {x["status"] for x in decks.get(db, d)["cards"]} == {"proxy"}
