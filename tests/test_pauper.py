import httpx
import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, decks, pauper
from scrybinder.api import create_app

GOLDFISH_INDEX = """<div class='archetype-tile' id='28645'>
<a href="/archetype/pauper-mono-red-madness#online">Mono Red Madness</a>
<a href="/archetype/pauper-mono-red-madness#paper">Mono Red Madness</a>
<div class='archetype-tile-statistic-name'>
META%
</div>
<div class='archetype-tile-statistic-value'>
13.2%
<span class='archetype-tile-statistic-value-extra-data'>(371)</span>
</div>
<div class='archetype-tile' id='28646'>
<a href="/archetype/pauper-blue-terror-2b4f#paper">Blue &amp; Terror</a>
META%
</div>
<div class='archetype-tile-statistic-value'>
7.6%
"""
GOLDFISH_DECK = """<h1 class='title'>Mono-Red Madness Burn
<span class='author'>by StefanLebtag</span></h1>
<p class='deck-container-information'>
Format: Pauper
<br>
Event: <a href="/tournament/67032">Common Island 2 – A Tournament</a>,  5-1-1
<br>
Deck Source:
<a href="https://melee.gg/Tournament/View/473064">melee.gg</a>
<br>
Deck Date: Oct 3, 2026
</p>
<input type="hidden" name="deck_input[deck]" id="deck_input_deck" value="4 Alpha &amp; Omega
2 Beta
sideboard
1 Gamma" />"""
TOP8_INDEX = """<div class=S14 align=center>896 decks</div>
<div class=meta_arch align=center style="margin:10px;">AGGRO 57%</div>
<div class=S14><a href=archetype?a=536&meta=299&f=PAU>Burn</a></div>
<div style="display:inline-block;width:48%;" class=S14>12 %</div>
<div class=meta_arch align=center style="margin:10px;">CONTROL 30%</div>
<div class=S14><a href=archetype?a=600&meta=299&f=PAU>Mono-Blue Delver</a></div>
<div style="display:inline-block;width:48%;" class=S14>7 %</div>
<div onclick="ToggleMetaList();"><div style="padding:3px;" class=S14>Last 2 Weeks</div></div>"""
TOP8_ARCH = """<tr class=hover_tr>
  <td><input type=checkbox name=deck_check[1] value=1 checked><input type=hidden name=deck_ref[1] value=905798></td>
  <td><a href=/event?e=92898&d=905798&f=PAU>Madness Burn</a></td>
  <td><a class=player href=/search?player=ziofrancone>ziofrancone</a></td>
  <td><a href=/event?e=92898&f=PAU>MTGO Challenge 16</a></td>
  <td class=O16><img src=/graph/star.png></td>
  <td>5-8</td>
  <td>27/10/26</td>
</tr>"""


def test_the_parsers_read_the_pages():
    assert pauper.goldfish_index(GOLDFISH_INDEX) == [{"slug": "pauper-mono-red-madness", "name": "Mono Red Madness", "meta": 13.2},
                                                      {"slug": "pauper-blue-terror-2b4f", "name": "Blue & Terror", "meta": 7.6}]
    assert pauper.goldfish_deck(GOLDFISH_DECK) == {"list": "4 Alpha & Omega\n2 Beta\nsideboard\n1 Gamma", "author": "StefanLebtag",
                                                    "event": "Common Island 2 – A Tournament, 5-1-1", "date": "2026-10-03"}
    assert pauper.goldfish_deck("<html></html>") is None
    assert [pauper._iso(pauper._en_month(t), ("%m %d, %Y",)) for t in ("Oct 3, 2026", "Dec 25, 2025", "nonsense")] == ["2026-10-03", "2025-12-25", ""]
    idx, period = pauper.top8_index(TOP8_INDEX)
    assert idx == [{"a": "536", "meta": "299", "name": "Burn", "meta_pct": 12.0, "cat": "Aggro"},
                   {"a": "600", "meta": "299", "name": "Mono-Blue Delver", "meta_pct": 7.0, "cat": "Control"}]
    assert period == "Last 2 Weeks, 896 decks"
    assert pauper.top8_row(TOP8_ARCH) == {"event_id": "92898", "deck_id": "905798", "author": "ziofrancone", "event": "MTGO Challenge 16, 5-8", "date": "2026-10-27"}
    assert pauper.top8_row("nothing") is None


def _pages(monkeypatch, names, fail=()):
    calls = []

    def get(url):
        calls.append(url)
        if any(f in url for f in fail):
            raise httpx.ConnectError("down")
        if url.endswith("/metagame/pauper/full"):
            return GOLDFISH_INDEX
        if "/archetype/pauper-mono-red" in url:
            return GOLDFISH_DECK.replace("Alpha &amp; Omega", names[0]).replace("2 Beta", f"2 {names[1]}").replace("1 Gamma", f"1 {names[2]}")
        if "format?f=PAU" in url:
            return TOP8_INDEX
        if "archetype?a=536" in url:
            return TOP8_ARCH
        if "mtgo?d=" in url:
            return f"4 {names[0]}\n\nSIDEBOARD:\n1 {names[1]}\n"
        raise httpx.HTTPError("status 404")  # the other archetype: skipped
    monkeypatch.setattr(pauper, "_get", get)
    return calls


def _names(db):
    return [r[0] for r in db.execute("SELECT name FROM oracle_cards WHERE name NOT LIKE '%//%' ORDER BY name LIMIT 3")]


def test_fetch_saves_the_lists_that_could_be_read_and_keeps_the_old_copy_when_nothing_can(db, tmp_path, monkeypatch):
    names = _names(db)
    _pages(monkeypatch, names)
    seen = []
    g = pauper.fetch("goldfish", tmp_path, progress=lambda d, t: seen.append((d, t)))
    assert [d["id"] for d in g["decks"]] == ["pauper-mono-red-madness"] and g["decks"][0]["meta"] == 13.2  # the second page 404s: skipped
    assert seen[0] == (0, 2) and seen[-1] == (2, 2)
    t = pauper.fetch("top8", tmp_path)
    assert t["decks"][0]["url"] == "https://www.mtgtop8.com/event?e=92898&d=905798&f=PAU" and t["decks"][0]["cat"] == "Aggro" and t["period"].startswith("Last 2 Weeks")
    assert pauper.load("goldfish", tmp_path)["fetched"] == g["fetched"]
    _pages(monkeypatch, names, fail=("mtggoldfish",))
    with pytest.raises(ValueError, match="could not reach MTGGoldfish"):
        pauper.fetch("goldfish", tmp_path)
    assert pauper.load("goldfish", tmp_path)["fetched"] == g["fetched"]  # untouched
    with pytest.raises(ValueError, match="source"):
        pauper.fetch("../x", tmp_path)
    assert pauper.stale(None) and pauper.stale(g, g["fetched"] + 86400) and not pauper.stale(g, g["fetched"] + 3600)


def test_get_only_talks_to_the_two_sites(monkeypatch):
    monkeypatch.setattr(pauper.httpx, "get", lambda *a, **k: pytest.fail("no request"))
    with pytest.raises(ValueError):
        pauper._get("https://example.com/")


def _setup(db, tmp_path, monkeypatch):
    names = _names(db)
    _pages(monkeypatch, names)
    pauper.fetch("goldfish", tmp_path)
    ids = [db.execute("SELECT oracle_id FROM oracle_cards WHERE name=?", (n,)).fetchone()[0] for n in names]
    return names, ids


def test_meta_says_what_you_own_and_the_colours(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    db.execute("UPDATE oracle_cards SET color_identity='[\"R\"]', type_line='Creature' WHERE oracle_id=?", (ids[0],))
    db.execute("UPDATE oracle_cards SET produced_mana='[\"R\"]', type_line='Basic Land — Mountain' WHERE oracle_id=?", (ids[1],))
    sid = db.execute("SELECT id FROM cards WHERE oracle_id=?", (ids[0],)).fetchone()[0]
    collection.add(db, scryfall_id=sid, quantity=3)
    m = pauper.meta(db, "goldfish", tmp_path)
    d = m["decks"][0]
    assert d["colors"] == "R" and (d["owned_main"], d["total_main"]) == (3, 6)  # plays 4 + 2, owns 3 of the 4
    assert [c["name"] for c in d["side"]] == [names[2]] and d["main"][0]["owned"] == 3
    assert pauper.meta(db, "top8", tmp_path)["decks"] == []  # nothing saved for it
    with pytest.raises(ValueError):
        pauper.meta(db, "nope", tmp_path)


def test_popular_cards_for_a_pauper_deck(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    pauper.fetch("top8", tmp_path)  # a second source does not mix in
    d = decks.create(db, "Mine", "pauper")
    decks.add_card(db, d, ids[1], 1)  # already in the deck: left out
    r = pauper.cards(db, d, "goldfish", tmp_path)
    assert [(c["name"], c["share"], c["archetypes"], c["avg"]) for c in r["cards"]] == [(names[0], 13.2, 1, 4.0), (names[2], 13.2, 1, 0)]
    assert r["cards"][0]["image_id"]
    with pytest.raises(ValueError, match="Pauper"):
        pauper.cards(db, decks.create(db, "Other", "modern"), "goldfish", tmp_path)


def test_create_a_deck_from_a_saved_list(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    deck_id = pauper.create_deck(db, "goldfish", "pauper-mono-red-madness", tmp_path)
    d = decks.get(db, deck_id)
    assert d["format"] == "pauper" and d["name"] == "Mono Red Madness"
    assert sum(c["quantity"] for c in decks.cards(db, deck_id) if c["board"] == "main") == 6
    with pytest.raises(ValueError, match="refresh"):
        pauper.create_deck(db, "goldfish", "nope", tmp_path)


def test_the_api_is_off_until_enabled(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    monkeypatch.setattr("scrybinder.db.DATA_DIR", tmp_path)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    assert c.get("/api/pauper-meta").json() == {"enabled": False}
    assert c.get("/api/pauper-meta/goldfish").status_code == 403
    assert c.post("/api/pauper-meta", json={"enabled": True}).json() == {"enabled": True}
    assert c.get("/api/pauper-meta/nope").status_code == 422
    r = c.get("/api/pauper-meta/goldfish").json()
    assert r["decks"][0]["name"] == "Mono Red Madness" and r["job"]["state"] == "idle"
    d = decks.create(db, "Mine", "pauper")
    assert len(c.get(f"/api/pauper-meta/goldfish/cards?deck_id={d}").json()["cards"]) == 3
    assert c.get("/api/pauper-meta/goldfish/cards?deck_id=9999").status_code == 404
    made = c.post("/api/pauper-meta/goldfish/create-deck", json={"id": "pauper-mono-red-madness"}).json()["id"]
    assert decks.get(db, made)["format"] == "pauper"
    assert c.post("/api/pauper-meta/goldfish/create-deck", json={"id": "x"}).status_code == 422
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert c.post("/api/open-url", json={"url": "https://www.mtgtop8.com/event?e=1"}).status_code == 200 and len(opened) == 1
    assert c.post("/api/open-url", json={"url": "https://www.mtgtop8.com.evil.test/"}).status_code == 422


def test_refresh_runs_in_the_background_and_reports_an_error(db, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr("scrybinder.db.DATA_DIR", tmp_path)
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    c.post("/api/pauper-meta", json={"enabled": True})
    monkeypatch.setattr(pauper, "_get", lambda url: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert c.post("/api/pauper-meta/goldfish/refresh").json()["state"] in ("running", "error")
    for _ in range(50):
        job = c.get("/api/pauper-meta/goldfish").json()["job"]
        if job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "error" and "could not reach MTGGoldfish" in job["error"]


def test_colours_are_the_ones_the_lands_make(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    db.execute("UPDATE oracle_cards SET color_identity='[\"U\",\"B\"]', type_line='Creature' WHERE oracle_id=?", (ids[0],))  # 4 off-colour spells
    db.execute("UPDATE oracle_cards SET color_identity='[\"R\"]', produced_mana='[\"R\"]', type_line='Basic Land — Mountain' WHERE oracle_id=?", (ids[1],))
    assert pauper.meta(db, "goldfish", tmp_path)["decks"][0]["colors"] == "R"  # no mana for the UB spells: not their colours
    db.execute("UPDATE oracle_cards SET produced_mana='[\"U\"]', type_line='Land' WHERE oracle_id=?", (ids[0],))
    assert pauper.meta(db, "goldfish", tmp_path)["decks"][0]["colors"] == "UR"  # a land of another colour is a splash


def test_the_deck_is_compared_with_the_archetypes_and_sideboard_cards_are_ranked(db, tmp_path, monkeypatch):
    names, ids = _setup(db, tmp_path, monkeypatch)
    for o, ci in zip(ids, ('["R"]', '["R"]', '["U"]')):
        db.execute("UPDATE oracle_cards SET color_identity=?, type_line='Creature' WHERE oracle_id=?", (ci, o))
    d = decks.create(db, "Mine", "pauper")
    decks.add_card(db, d, ids[0], 2)
    a = pauper.meta(db, "goldfish", tmp_path, d)["decks"][0]
    assert (a["match"], a["main"][0]["in_deck"], a["main"][1]["in_deck"]) == (33, 2, 0)  # 2 of its 6 main copies
    assert pauper.meta(db, "goldfish", tmp_path)["decks"][0]["match"] == 0  # no deck: nothing to compare
    r = pauper.cards(db, d, "goldfish", tmp_path)
    assert r["colors"] == "R"
    by = {c["name"]: c for c in r["cards"]}
    assert (by[names[1]]["main_share"], by[names[1]]["side_share"], by[names[1]]["fits"]) == (13.2, 0, True)
    assert (by[names[2]]["main_share"], by[names[2]]["side_share"], by[names[2]]["fits"]) == (0, 13.2, False)  # a sideboard card, but blue
