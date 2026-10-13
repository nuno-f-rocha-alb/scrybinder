from fastapi.testclient import TestClient

from scrybinder import decks, deckstats as S
from scrybinder.api import create_app


def card(name, qty=1, board="main", type_line="Creature — Elf", mana="", cmc=0, produced=(), tags=(), ci=(), price=None, gc=False):
    return {"name": name, "quantity": qty, "board": board, "type_line": type_line, "mana_cost": mana, "cmc": cmc,
            "produced_mana": list(produced), "tags": list(tags), "color_identity": list(ci), "price": price, "game_changer": gc}


def test_pips_count_coloured_symbols_only():
    assert S.pips("{2}{W}{W}") == {"W": 2}
    assert S.pips("{X}{R}{G}") == {"R": 1, "G": 1}
    assert S.pips("{W/U}{2/B}{G/P}{C}{S}") == {"W": 1, "U": 1, "B": 1, "G": 1, "C": 1}  # hybrid counts for each colour
    assert S.pips("") == S.pips(None) == {}


def test_primary_type_uses_the_front_face_and_priority():
    kinds = {"Artifact Creature — Golem": "creature", "Land Creature — Forest Dryad": "land", "Legendary Enchantment": "enchantment",
             "Sorcery // Land": "sorcery", "Basic Land — Forest": "land", "Instant": "instant", "Kindred Sorcery — Elf": "sorcery",
             "Legendary Planeswalker — Jace": "planeswalker", "Battle — Siege": "battle", "Conspiracy": "other", None: "other"}
    assert {t: S.primary_type({"type_line": t}) for t in kinds} == kinds


def test_curve_averages_types_and_sources():
    deck = [card("Bear", 4, mana="{1}{G}", cmc=2, ci="G", price=1.0, tags=["creature"]),
            card("Bolt", 2, type_line="Instant", mana="{R}", cmc=1, ci="R", price=0.5, tags=["removal", "creature"]),
            card("Rocks", 1, type_line="Artifact", mana="{2}", cmc=2, produced="C", ci=""),
            card("Titan", 1, mana="{6}{G}{G}", cmc=8, ci="G"),
            card("Forest", 5, type_line="Basic Land — Forest", produced="G", ci="G"),
            card("Mountain", 1, type_line="Basic Land — Mountain", produced="R", ci="R"),
            card("Gilded", 1, type_line="Land", produced="GR", ci="GR"),
            card("Cmd", 1, board="commander", type_line="Legendary Creature — Elf", mana="{G}", cmc=1, ci="G", gc=True),
            card("Side", 9, board="side", mana="{W}", cmc=1), card("Maybe", 9, board="maybe")]
    s = S.compute(deck)
    assert s["totals"] == {"main": 15, "side": 9, "commander": 1, "maybe": 9}
    assert [(b["cmc"], b["permanents"], b["spells"]) for b in s["curve"]] == [
        (0, 0, 0), (1, 1, 2), (2, 5, 0), (3, 0, 0), (4, 0, 0), (5, 0, 0), (6, 0, 0), (7, 1, 0)]  # Titan lands in the 7+ bucket
    assert s["types"] == {"land": 7, "creature": 6, "artifact": 1, "instant": 2} and s["lands"] == 7
    c = s["cmc"]  # spells: 4x2, 2x1, 1x2, 1x8, 1x1 = 21 over 9 cards
    assert (c["average"], c["median"]) == (round(21 / 9, 2), 2) and c["average_with_lands"] == round(21 / 16, 2)
    assert c["median_with_lands"] == 1
    assert s["pips"] == {"W": 0, "U": 0, "B": 0, "R": 2, "G": 4 + 2 + 1, "C": 0}  # 4x{G}, Titan {G}{G}, commander {G}
    assert s["sources"]["G"] == 6 and s["land_sources"] == {"W": 0, "U": 0, "B": 0, "R": 2, "G": 6, "C": 0} and s["sources"]["C"] == 1
    assert s["tags"] == {"creature": 6, "removal": 2}
    assert s["color_identity"] == ["G"] and s["game_changers"] == 1  # a commander decides the identity
    assert s["price"] == 4 * 1.0 + 2 * 0.5


def test_identity_without_commander_is_the_union_and_empty_deck():
    s = S.compute([card("A", ci="W"), card("B", ci="UB"), card("Side", board="side", ci="R")])
    assert s["color_identity"] == ["W", "U", "B"]  # WUBRG order
    e = S.compute([])
    assert e["cmc"]["average"] == 0 and e["color_identity"] == [] and e["tags"] == {} and e["price"] == 0
    assert all(b["permanents"] == b["spells"] == 0 for b in e["curve"])


def test_colour_warning_when_pips_outrun_sources():
    heavy = [card("Red", 8, mana="{R}{R}", cmc=2), card("Green", 2, mana="{G}", cmc=1)]
    lands = [card("Forest", 15, type_line="Basic Land — Forest", produced="G"), card("Mountain", 2, type_line="Basic Land — Mountain", produced="R")]
    w = S.compute(heavy + lands)["color_warnings"]
    assert [x["color"] for x in w] == ["R"] and w[0]["pips_share"] > 0.8 and w[0]["sources_share"] < 0.2
    fixed = [card("Forest", 4, type_line="Basic Land — Forest", produced="G"), card("Mountain", 12, type_line="Basic Land — Mountain", produced="R")]
    assert S.compute(heavy + fixed)["color_warnings"] == []  # green has 17% of the symbols and 25% of the sources


def test_stats_from_the_database(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    oid = db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' LIMIT 1").fetchone()[0]
    did = decks.create(db, "S", "commander")
    decks.add_card(db, did, oid, 3, tags=["ramp"])
    decks.add_card(db, did, oid, 5, board="side")
    r = c.get(f"/api/decks/{did}/stats").json()
    assert r["totals"]["main"] == 3 and r["totals"]["side"] == 5 and r["tags"] == {"ramp": 3}
    assert r["cost_to_complete"] == 4.5 and r["price"] == 4.5  # 3 x 1.50, none owned
    assert c.get("/api/decks/999/stats").status_code == 404
