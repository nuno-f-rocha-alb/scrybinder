import json

import httpx
import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks, share, trades
from scrybinder.api import create_app

ID = "AbCdEfGhIjKl"


def _cards(db):
    return [r[0] for r in db.execute("SELECT id FROM cards WHERE id != 'dfc-1' ORDER BY id LIMIT 3")]


def _oracle(db, sid):
    return db.execute("SELECT oracle_id FROM cards WHERE id=?", (sid,)).fetchone()[0]


class Worker:
    """A stand-in for the share Worker: keeps what it is sent."""

    def __init__(self):
        self.store, self.requests = {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            self.store[ID] = json.loads(request.content)
            return httpx.Response(200, json={"id": ID, "delete_token": "secret", "expires": "2026-11-20T00:00:00Z"})
        if request.method == "DELETE":
            if request.headers.get("x-delete-token") != "secret":
                return httpx.Response(403)
            self.store.pop(request.url.path.rsplit("/", 1)[1], None)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


@pytest.fixture
def worker(monkeypatch):
    w = Worker()
    monkeypatch.setattr(share, "SHARE_API", "https://w.example")
    monkeypatch.setattr(share, "SHARE_VIEWER", "https://v.example/share")
    monkeypatch.setattr(share, "TRANSPORT", httpx.MockTransport(w))
    return w


def _deck(db):
    a, b, c = _cards(db)
    d = decks.create(db, "Test deck", "commander")
    decks.add_card(db, d, _oracle(db, a), 1, "commander", a)
    decks.add_card(db, d, _oracle(db, b), 3, "main", b, finish="foil")
    decks.add_card(db, d, _oracle(db, c), 1, "maybe", c)
    return d, (a, b, c)


def test_deck_document_has_boards_prices_only_when_asked(db):
    d, (a, b, c) = _deck(db)
    doc = share.deck_doc(db, d)
    assert [s["name"] for s in doc["sections"]] == ["Commander", "Main", "Maybeboard"]  # empty sideboard is left out
    main = doc["sections"][1]["cards"][0]
    assert (main["id"], main["qty"], main["finish"]) == (b, 3, "foil") and "price" not in main
    assert doc["meta"] == {"format": "commander"} and not doc["prices"]
    priced = share.deck_doc(db, d, prices=True)
    assert priced["sections"][1]["cards"][0]["price"] == 3.0  # the foil price of the fixture card


def test_trade_document_never_carries_who_cash_or_note(db):
    a, b, _ = _cards(db)
    row = collection.add(db, scryfall_id=a)
    t = trades.create(db, "Secret Rui", "private note", 12.5)
    trades.add_out(db, t, row)
    trades.add_in(db, t, b, 2)
    doc = share.trade_doc(db, t, prices=True)
    text = json.dumps(doc)
    assert "Secret Rui" not in text and "private note" not in text and "12.5" not in text
    assert [s["name"] for s in doc["sections"]] == ["Giving", "Getting"]
    assert doc["sections"][1]["cards"][0]["qty"] == 2 and doc["sections"][1]["cards"][0]["price"] == 1.5


def test_collection_document_merges_locations_and_never_sends_private_fields(db):
    a, b, _ = _cards(db)
    r1 = collection.add(db, scryfall_id=a, quantity=2, location="Box", purchase_price=9.99, notes="mine")
    r2 = collection.add(db, scryfall_id=a, quantity=1, location="Bin")
    collection.add(db, scryfall_id=b, proxy=1)
    doc = share.collection_doc(db, ids=[r1, r2, 999])
    cards = doc["sections"][0]["cards"]
    assert [(c["id"], c["qty"]) for c in cards] == [(a, 3)]  # merged, the proxy and the missing id left out
    text = json.dumps(doc)
    assert "9.99" not in text and "mine" not in text and "Box" not in text
    assert {c.get("loc") for c in share.collection_doc(db, ids=[r1, r2], locations=True)["sections"][0]["cards"]} == {"Box", "Bin"}
    assert share.collection_doc(db, filters={"location": ["Bin"]})["sections"][0]["cards"][0]["qty"] == 1
    with pytest.raises(ValueError, match="nothing to share"):
        share.collection_doc(db, ids=[])


def test_too_many_lines_is_refused(db, monkeypatch):
    a, b, _ = _cards(db)
    monkeypatch.setattr(share, "MAX_LINES", 1)
    ids = [collection.add(db, scryfall_id=a), collection.add(db, scryfall_id=b)]
    with pytest.raises(ValueError, match="too many"):
        share.collection_doc(db, ids=ids)


def test_parse_rejects_bad_documents():
    ok = {"format": "scrybinder-share", "v": 1, "kind": "deck", "title": "t", "sections": [{"name": "Main", "cards": [{"id": "x", "qty": 1}]}]}
    assert share.parse(ok)["sections"][0]["cards"][0]["qty"] == 1
    for bad in (None, {}, {**ok, "v": 2}, {**ok, "kind": "x"}, {**ok, "sections": []},
                {**ok, "sections": [{"cards": [{"id": "x", "qty": 0}]}]}, {**ok, "sections": [{"cards": [{"id": "x", "qty": 1, "finish": "gold"}]}]},
                {**ok, "sections": [{"cards": [{"id": 5, "qty": 1}]}]}, {**ok, "sections": [{"cards": [{"id": "x", "qty": 1, "price": -1}]}]}):
        with pytest.raises(ValueError):
            share.parse(bad)


def test_deck_round_trip_through_import(db):
    d, (a, b, c) = _deck(db)
    text = json.dumps(share.deck_doc(db, d))
    got = share.import_text(db, text)
    assert got["kind"] == "deck" and got["cards"] == 5 and got["skipped"] == []
    new = decks.get(db, got["deck_id"])
    assert new["format"] == "commander"
    assert {(c["board"], c["quantity"], c["finish"]) for c in new["cards"]} == {("commander", 1, None), ("main", 3, "foil"), ("maybe", 1, None)}


def test_collection_import_into_a_location_and_unknown_cards_skipped(db):
    a, b, _ = _cards(db)
    doc = {"format": "scrybinder-share", "v": 1, "kind": "collection", "title": "c", "sections": [{"cards": [
        {"id": a, "name": "A", "qty": 2, "finish": "foil", "cond": "LP"}, {"id": "no-such-card", "name": "Ghost", "qty": 1}]}]}
    got = share.import_text(db, json.dumps(doc), "From Rui")
    assert got["cards"] == 2 and got["skipped"] == ["Ghost"]
    row = db.execute("SELECT quantity, finish, condition, location FROM collection WHERE scryfall_id=?", (a,)).fetchone()
    assert tuple(row) == (2, "foil", "LP", "From Rui")
    with pytest.raises(ValueError, match="reserved"):
        share.import_text(db, json.dumps(doc), "Deck: X")
    doc["kind"] = "trade"
    with pytest.raises(ValueError, match="only for looking"):
        share.import_text(db, json.dumps(doc))
    with pytest.raises(ValueError, match="not JSON"):
        share.import_text(db, "just text")


def test_create_and_delete_a_link(db, worker):
    d, _ = _deck(db)
    got = share.create_link(db, share.deck_doc(db, d))
    assert got["url"] == "https://v.example/share/?id=" + ID and got["cards"] == 5
    assert worker.store[ID]["kind"] == "deck"
    assert "secret" not in json.dumps(share.listing(db))  # the delete token never leaves the app
    share.delete_link(db, ID)
    assert share.listing(db) == [] and ID not in worker.store
    assert worker.requests[-1].headers["x-delete-token"] == "secret"


def test_unreachable_worker_keeps_the_row(db, monkeypatch, worker):
    d, _ = _deck(db)
    share.create_link(db, share.deck_doc(db, d))

    def boom(request):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(share, "TRANSPORT", httpx.MockTransport(boom))
    with pytest.raises(share.Unreachable):
        share.delete_link(db, ID)
    assert len(share.listing(db)) == 1
    with pytest.raises(share.Unreachable):
        share.create_link(db, share.deck_doc(db, d))


def test_not_configured(db, monkeypatch):
    monkeypatch.setattr(share, "SHARE_API", "")
    monkeypatch.delenv("SCRYBINDER_SHARE_API", raising=False)
    d, _ = _deck(db)
    with pytest.raises(share.NotConfigured):
        share.create_link(db, share.deck_doc(db, d))


def test_share_routes(db, worker):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    d, _ = _deck(db)
    pre = c.post("/api/share/preview", json={"kind": "deck", "deck_id": d}).json()
    assert (pre["lines"], pre["cards"]) == (3, 5)
    made = c.post("/api/share", json={"kind": "deck", "deck_id": d, "title": "Mine", "prices": True}).json()
    assert made["url"].endswith("?id=" + ID) and worker.store[ID]["title"] == "Mine"
    assert [s["id"] for s in c.get("/api/shares").json()] == [ID]
    assert c.post("/api/share", json={"kind": "nope"}).status_code == 422
    assert c.delete("/api/shares/" + ID).status_code == 200 and c.delete("/api/shares/" + ID).status_code == 404
    got = c.post("/api/import-share", content=json.dumps(share.deck_doc(db, d)))
    assert got.status_code == 200 and got.json()["cards"] == 5


def test_a_worker_answer_with_a_odd_id_is_refused(db, monkeypatch):
    monkeypatch.setattr(share, "SHARE_API", "https://w.example")
    monkeypatch.setattr(share, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "../../x", "delete_token": "t"})))
    d, _ = _deck(db)
    with pytest.raises(share.Unreachable, match="unexpected"):
        share.create_link(db, share.deck_doc(db, d))
    assert share.listing(db) == []


def test_card_search_sample_is_a_printing_with_an_image(db):
    a = db.execute("SELECT id FROM cards WHERE id != 'dfc-1' LIMIT 1").fetchone()[0]
    oid = db.execute("SELECT oracle_id FROM cards WHERE id=?", (a,)).fetchone()[0]
    row = dict(db.execute("SELECT * FROM cards WHERE id=?", (a,)).fetchone())
    row.update(id="newer-no-image", released_at="2030-01-01", image_normal=None, image_small=None)
    db.execute(f"INSERT INTO cards ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    db.execute("INSERT INTO cards_fts(rowid, name) SELECT rowid, name FROM cards WHERE id='newer-no-image'")
    name = db.execute("SELECT name FROM cards WHERE id=?", (a,)).fetchone()[0]
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    hits = c.get("/api/cards/search", params={"q": name.split()[0]}).json()
    assert next(h for h in hits if h["oracle_id"] == oid)["sample_id"] == a  # not the newest printing, which has no picture
