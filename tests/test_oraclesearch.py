import json

import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, db as dbmod, decks, oracle, scryfall
from scrybinder.api import create_app

LEG = {"commander": "legal", "modern": "legal"}


def _card(i, oid, name, **kw):
    base = {"id": i, "oracle_id": oid, "name": name, "set": "x", "set_name": "X", "collector_number": i, "released_at": "2024-01-01",
            "rarity": "common", "layout": "normal", "lang": "en", "finishes": ["nonfoil"], "prices": {"eur": "1.00"}, "digital": False,
            "image_uris": {"small": f"http://x/{i}s.jpg", "normal": f"http://x/{i}n.jpg"}, "mana_cost": "{1}", "cmc": 1.0,
            "type_line": "Creature — Elf", "colors": [], "color_identity": [], "oracle_text": "", "keywords": [], "legalities": LEG}
    return {**base, **kw}


@pytest.fixture
def odb(tmp_path):
    cards = [
        _card("g1", "g", "Llanowar Elves", colors=["G"], color_identity=["G"], oracle_text="{T}: Add {G}.", edhrec_rank=10),
        _card("r1", "r", "Lightning Bolt", type_line="Instant", colors=["R"], color_identity=["R"], cmc=1.0,
              oracle_text="Lightning Bolt deals 3 damage to any target.", edhrec_rank=2),
        _card("gu", "gu", "Gold Wizard", type_line="Legendary Creature — Human Wizard", colors=["G", "U"], color_identity=["G", "U"], cmc=4.0,
              oracle_text="Draw a card.", legalities={"commander": "legal", "modern": "banned"}),
        _card("art", "art", "Sol_Ring", type_line="Artifact", cmc=1.0, oracle_text="{T}: Add {C}{C}.", legalities={"commander": "legal", "modern": "not_legal"}),
        _card("big", "big", "Big Thing", cmc=7.0, colors=["G"], color_identity=["G"]),
        _card("dig", "dig", "Alchemy Only", digital=True, colors=["R"], color_identity=["R"]),
        _card("tok", "tok", "A Token", layout="token"),
        _card("old", "r", "Lightning Bolt", type_line="Instant", released_at="2010-01-01", image_uris={"small": "http://x/old.jpg", "normal": "n"})]
    f = tmp_path / "b.json"
    f.write_text(json.dumps(cards), encoding="utf-8")
    d = dbmod.connect(tmp_path / "t.db")
    scryfall.import_bulk(d, f)
    return d


def names(res):
    return [r["name"] for r in res["rows"]]


def test_name_text_type_cmc_and_colours(odb):
    assert names(oracle.search(odb)) == ["Big Thing", "Gold Wizard", "Lightning Bolt", "Llanowar Elves", "Sol_Ring"]  # no digital, no token
    assert names(oracle.search(odb, q="lla elv")) == ["Llanowar Elves"] and oracle.search(odb, q="!!")["total"] == 5
    assert names(oracle.search(odb, text="3 damage")) == ["Lightning Bolt"]
    assert names(oracle.search(odb, q="bolt", text="elf")) == []  # name AND text
    assert names(oracle.search(odb, type="legendary wizard")) == ["Gold Wizard"] and names(oracle.search(odb, type="artifact")) == ["Sol_Ring"]
    assert oracle.search(odb, type="_")["total"] == 0  # "_" is not a wildcard (only the name Sol_Ring has one)
    assert names(oracle.search(odb, cmc_min=4)) == ["Big Thing", "Gold Wizard"] and names(oracle.search(odb, cmc_min="4", cmc_max="4")) == ["Gold Wizard"]
    assert names(oracle.search(odb, colors="gu")) == ["Gold Wizard"] and names(oracle.search(odb, colors="G")) == ["Big Thing", "Gold Wizard", "Llanowar Elves"]
    assert names(oracle.search(odb, colors="C")) == ["Sol_Ring"]
    for bad in (dict(colors="X"), dict(colors="CG"), dict(cmc_min="a"), dict(sort="x"), dict(legal=True)):
        with pytest.raises(ValueError):
            oracle.search(odb, **bad)


def test_rows_paging_sort_and_owned(odb):
    bolt = oracle.search(odb, q="bolt")["rows"][0]
    assert bolt["image_small"] == "http://x/r1s.jpg" and bolt["price"] == 1.0 and bolt["color_identity"] == ["R"]  # the newest printing
    assert bolt["owned"] == 0 and bolt["in_deck"] == 0
    page = oracle.search(odb, limit=2, offset=1)
    assert page["total"] == 5 and names(page) == ["Gold Wizard", "Lightning Bolt"]
    assert names(oracle.search(odb, sort="cmc")) == ["Lightning Bolt", "Llanowar Elves", "Sol_Ring", "Gold Wizard", "Big Thing"]
    assert names(oracle.search(odb, sort="popularity"))[:2] == ["Lightning Bolt", "Llanowar Elves"]  # EDHREC rank, unranked last
    collection.add(odb, scryfall_id="g1", quantity=2)
    collection.add(odb, scryfall_id="r1", quantity=1, proxy=1)  # a proxy is not a copy
    assert names(oracle.search(odb, owned=True)) == ["Llanowar Elves"]
    assert oracle.search(odb, q="llanowar")["rows"][0]["owned"] == 2


def test_legal_filter_by_format_and_commander_identity(odb):
    modern = decks.create(odb, "M", "modern")
    assert names(oracle.search(odb, deck=modern, legal=True)) == ["Big Thing", "Lightning Bolt", "Llanowar Elves"]
    assert oracle.search(odb, deck=modern)["total"] == 5  # without `legal` nothing is filtered
    cmd = decks.create(odb, "C", "commander")
    assert oracle.search(odb, deck=cmd, legal=True)["total"] == 5  # no commander yet: no colour limit
    decks.add_card(odb, cmd, "g", 1, "commander")
    decks.add_card(odb, cmd, "g", 2)
    res = oracle.search(odb, deck=cmd, legal=True)
    assert names(res) == ["Big Thing", "Llanowar Elves", "Sol_Ring"]  # green and colourless only
    assert [r["in_deck"] for r in res["rows"]] == [0, 3, 0]
    decks.add_card(odb, cmd, "gu", 1, "maybe")
    assert next(r for r in oracle.search(odb, deck=cmd)["rows"] if r["name"] == "Gold Wizard")["in_deck"] == 0  # maybe does not count
    assert oracle.search(odb, deck=decks.create(odb, "K"), legal=True)["total"] == 5  # casual has no format
    with pytest.raises(KeyError):
        oracle.search(odb, deck=999)


def test_oracle_search_api(odb):
    c = TestClient(create_app(odb, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    r = c.get("/api/oracle/search", params={"q": "elves", "owned": "false"}).json()
    assert r["total"] == 1 and r["rows"][0]["name"] == "Llanowar Elves"
    assert c.get("/api/oracle/search", params={"legal": "true"}).status_code == 422
    assert c.get("/api/oracle/search", params={"deck": 999}).status_code == 404
    assert c.get("/api/oracle/search", params={"limit": 1, "offset": 4}).json()["rows"][0]["name"] == "Sol_Ring"
