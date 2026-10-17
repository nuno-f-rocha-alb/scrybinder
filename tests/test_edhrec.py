import json

import httpx
import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks, edhrec, suggest
from scrybinder.api import create_app


@pytest.mark.parametrize("names,want", [
    (["Miirym, Sentinel Wyrm"], "miirym-sentinel-wyrm"),
    (["Atraxa, Praetors' Voice"], "atraxa-praetors-voice"),
    (["The Ur-Dragon"], "the-ur-dragon"),
    (["Esika, God of the Tree // The Prismatic Bridge"], "esika-god-of-the-tree"),
    (["Tymna the Weaver", "Kraum, Ludevic's Opus"], "kraum-ludevics-opus-tymna-the-weaver"),  # partners: sorted
    (["Jirina Kudro"], "jirina-kudro"), (["Lúthien, Queen"], "luthien-queen"),
])
def test_slug(names, want):
    assert edhrec.slug(names) == want


def _page(cards_by_tag, name="Cmd"):
    return {"container": {"json_dict": {"card": {"name": name, "sanitized": "cmd", "num_decks": 100, "salt": 1.0, "rank": 5, "color_identity": []},
            "cardlists": [{"tag": t, "header": t.title(), "cardviews": [{"id": i, "name": "x", "num_decks": n, "potential_decks": 100, "synergy": 0.1, "lift": 1.2} for i, n in cs]}
                          for t, cs in cards_by_tag.items()]}}}


class _R:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body or {}
        self.content = json.dumps(self._b).encode()

    def json(self):
        return self._b


def test_fetch_caches_for_a_day_falls_back_when_offline_and_says_when_there_is_no_page(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(edhrec.httpx, "get", lambda *a, **k: calls.append(1) or _R(200, _page({"creatures": [("id1", 50)]})))
    a = edhrec.fetch("cmd", tmp_path, now=1000.0)
    assert a["stale"] is False and a["lists"][0]["cards"][0]["id"] == "id1" and len(calls) == 1
    assert edhrec.fetch("cmd", tmp_path, now=1000.0 + 3600)["fetched"] == a["fetched"] and len(calls) == 1  # a saved copy under a day old
    monkeypatch.setattr(edhrec.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    late = edhrec.fetch("cmd", tmp_path, now=1000.0 + 3 * 86400)
    assert late["stale"] is True  # offline: the old copy stands in
    with pytest.raises(ValueError, match="could not get"):
        edhrec.fetch("other", tmp_path)  # nothing saved, offline
    monkeypatch.setattr(edhrec.httpx, "get", lambda *a, **k: _R(403))
    with pytest.raises(ValueError, match="no page"):
        edhrec.fetch("nopage", tmp_path)
    with pytest.raises(ValueError):
        edhrec.fetch("../etc/passwd", tmp_path)  # only a slug reaches the URL and the disk


def _fit(db, *oracle_ids):
    for o in oracle_ids:
        db.execute("UPDATE oracle_cards SET legalities='{\"commander\":\"legal\"}', color_identity='[]' WHERE oracle_id=?", (o,))


def _three(db):
    return db.execute("SELECT c.id, c.oracle_id FROM cards c WHERE c.oracle_id != 'o-dfc' GROUP BY c.oracle_id ORDER BY c.oracle_id LIMIT 4").fetchall()


def test_suggestions_from_edhrec_with_what_you_own(db, tmp_path, monkeypatch):
    (c1, o1), (c2, o2), (c3, o3), (c4, o4) = _three(db)
    _fit(db, o1, o2, o3, o4)
    d = decks.create(db, "Cmd deck", "commander")
    decks.add_card(db, d, o1, 1, board="commander")
    decks.add_card(db, d, o3, 1)  # already in the deck: not suggested
    collection.add(db, scryfall_id=c2, quantity=2)
    other = decks.create(db, "Other")
    decks.add_card(db, other, o2, 1)
    decks.assign_free(db, other)  # one of the two copies is in another deck
    db.execute("UPDATE oracle_cards SET legalities='{\"commander\":\"banned\"}' WHERE oracle_id=?", (o4,))  # banned: left out
    page = {"topcards": [(c2, 80), (c3, 70)], "creatures": [(c2, 60), (c4, 10), ("unknown-id", 5)]}
    monkeypatch.setattr(suggest.edhrec, "fetch", lambda slug, dd: {**edhrec._trim(_page(page)), "stale": False})
    r = suggest.suggestions(db, d, tmp_path, True)
    assert r["source"] == "edhrec" and [c["oracle_id"] for c in r["cards"]] == [o2]
    got = r["cards"][0]
    assert (got["category_key"], got["inclusion"], got["owned"], got["free"], got["elsewhere"]) == ("creatures", 0.6, 2, 1, ["Other"])  # listed once, under its type
    assert r["commander"]["names"] == [db.execute("SELECT name FROM oracle_cards WHERE oracle_id=?", (o1,)).fetchone()[0]] and r["slug"] == "cmd"


def test_suggestions_from_the_collection_without_edhrec(db, tmp_path):
    (c1, o1), (c2, o2), (c3, o3), _ = _three(db)
    _fit(db, o1, o2, o3)
    d = decks.create(db, "Cmd deck", "commander")
    decks.add_card(db, d, o1, 1, board="commander")
    collection.add(db, scryfall_id=c2, quantity=1)
    collection.add(db, scryfall_id=c3, quantity=1, proxy=1)  # a proxy is not a copy
    db.execute("UPDATE oracle_cards SET edhrec_rank=10 WHERE oracle_id=?", (o2,))
    r = suggest.suggestions(db, d, tmp_path, False)
    assert r["source"] == "collection" and [c["oracle_id"] for c in r["cards"]] == [o2] and r["cards"][0]["free"] == 1


def test_suggestions_need_a_commander_deck_with_a_commander(db, tmp_path):
    (c1, o1), *_ = _three(db)
    with pytest.raises(ValueError, match="Commander decks"):
        suggest.suggestions(db, decks.create(db, "Casual"), tmp_path, False)
    with pytest.raises(ValueError, match="no commander"):
        suggest.suggestions(db, decks.create(db, "Empty", "commander"), tmp_path, False)


def test_suggestions_api_is_off_until_enabled(db, monkeypatch):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    (c1, o1), *_ = _three(db)
    _fit(db, o1)
    d = decks.create(db, "Cmd deck", "commander")
    decks.add_card(db, d, o1, 1, board="commander")
    assert c.get("/api/edhrec").json() == {"enabled": False}
    assert c.get(f"/api/decks/{d}/suggestions").status_code == 403
    assert c.get(f"/api/decks/{d}/suggestions?source=collection").status_code == 200
    assert c.get(f"/api/decks/{d}/suggestions?source=x").status_code == 422
    assert c.post("/api/edhrec", json={"enabled": True}).json() == {"enabled": True}
    monkeypatch.setattr(suggest.edhrec, "fetch", lambda slug, dd: (_ for _ in ()).throw(ValueError("EDHREC has no page for this commander")))
    assert c.get(f"/api/decks/{d}/suggestions").status_code == 422
