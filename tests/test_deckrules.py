import pytest
from fastapi.testclient import TestClient

from scrybinder import decks, deckrules as R
from scrybinder.api import create_app

LEGAL = {f: "legal" for f in ("standard", "pioneer", "modern", "legacy", "vintage", "pauper", "commander")}


def card(name, qty=1, board="main", type_line="Creature", text="", kw=(), ci=(), leg=None, gc=False):
    return {"name": name, "quantity": qty, "board": board, "type_line": type_line, "oracle_text": text, "keywords": list(kw),
            "color_identity": list(ci), "legalities": leg or LEGAL, "game_changer": gc}


def rules(res):
    return sorted((p["rule"], p["card"]) for p in res["problems"])


def filler(n, ci=()):
    return [card(f"Card {i}", ci=ci) for i in range(n)]


def test_sixty_card_size_and_copies():
    deck = [card("Bolt", 4)] + filler(56)
    res = R.check("modern", deck + [card("Island", 20, type_line="Basic Land — Island")])
    assert res["legal"] and res["counts"]["main"] == 80  # any number of basics; more than 60 is only a warning
    assert [p["severity"] for p in res["problems"]] == ["warning"]
    res = R.check("modern", [card("Bolt", 5)] + filler(55))
    assert rules(res) == [("copies", "Bolt")] and not res["legal"]
    assert rules(R.check("modern", filler(59))) == [("size", None)]
    assert rules(R.check("modern", filler(60) + [card("Side", 16, board="side")])) == [("copies", "Side"), ("size", None)]
    res = R.check("modern", filler(60) + [card("Maybe", 9, board="maybe")])  # maybe is ignored
    assert res["problems"] == [] and res["counts"]["main"] == 60


def test_banned_restricted_and_not_legal():
    leg = {**LEGAL, "modern": "banned", "vintage": "restricted", "standard": "not_legal"}
    deck = [card("Ban", 1, leg=leg)] + filler(59)
    assert rules(R.check("modern", deck)) == [("banned", "Ban")]
    assert rules(R.check("standard", deck)) == [("not_legal", "Ban")]
    assert R.check("legacy", deck)["legal"]
    two = [card("Rest", 2, leg=leg)] + filler(58)
    assert rules(R.check("vintage", two)) == [("restricted", "Rest")]
    assert R.check("vintage", [card("Rest", 1, leg=leg)] + filler(59))["legal"]
    # casual has no deck rules: only a reference format's per-card legality
    assert R.check("casual", deck)["problems"] == []
    assert rules(R.check("casual", deck, reference="modern")) == [("banned", "Ban")]
    assert R.check("casual", [card("Bolt", 9)] + filler(3), reference="modern")["legal"]


@pytest.mark.parametrize("text,n,ok", [
    ("A deck can have any number of cards named Rats.", 30, True),
    ("A deck can have up to seven cards named Seven Dwarves.", 7, True),
    ("A deck can have up to seven cards named Seven Dwarves.", 8, False),
    ("A deck can have up to nine cards named Nazgûl.", 9, True),
    ("A deck can have only one card named Once.", 2, False),
    ("", 5, False),
])
def test_copy_exceptions(text, n, ok):
    assert R.check("legacy", [card("X", n, text=text)] + filler(60 - min(n, 60)))["legal"] == ok


def _commander_deck(cmd, ci_cards=(), n=None):
    cmds = cmd if isinstance(cmd, list) else [cmd]
    main = list(ci_cards)
    main += filler(100 - len(cmds) - len(main))
    return [dict(c, board="commander") for c in cmds] + main


LEG_CREATURE = "Legendary Creature — Human"


def test_commander_size_singleton_and_identity():
    atraxa = card("Atraxa", type_line=LEG_CREATURE, ci="WUBG", board="commander")
    deck = [atraxa] + filler(99, ci="G")
    assert R.check("commander", deck)["legal"]
    assert rules(R.check("commander", [atraxa] + filler(98))) == [("size", None)]
    assert rules(R.check("commander", deck + [card("Side", board="side")])) == [("size", None)]
    red = card("Red", ci="R")
    res = R.check("commander", [dict(atraxa, color_identity=["G"])] + filler(98, ci="G") + [red])
    assert rules(res) == [("color_identity", "Red")]
    dup = [atraxa, card("Twice", 2)] + filler(97)
    assert rules(R.check("commander", dup)) == [("copies", "Twice")]
    assert rules(R.check("commander", [atraxa, card("Atraxa", 1)] + filler(98))) == [("copies", "Atraxa")]  # commander counts as a copy
    assert rules(R.check("commander", filler(100))) == [("commander", None)]
    colourless = card("Kozilek", type_line=LEG_CREATURE, board="commander")
    assert rules(R.check("commander", [colourless] + filler(98) + [card("Green", ci="G")])) == [("color_identity", "Green")]


def test_commander_eligibility():
    rats = card("Rats", board="commander", type_line="Creature — Rat")
    assert rules(R.check("commander", [rats] + filler(99))) == [("commander", "Rats")]
    walker = card("Minsc", board="commander", type_line="Legendary Planeswalker — Minsc", text="Minsc can be your commander.")
    assert R.check("commander", [walker] + filler(99))["legal"]
    mdfc = card("Front // Back", board="commander", type_line="Legendary Creature — Elf // Land")
    assert R.check("commander", [mdfc] + filler(99))["legal"]
    land = card("Land", board="commander", type_line="Land // Legendary Creature — Elf")  # only the front face counts
    assert rules(R.check("commander", [land] + filler(99))) == [("commander", "Land")]
    vehicle = card("Ship", board="commander", type_line="Legendary Artifact — Vehicle")
    assert R.check("commander", [vehicle] + filler(99))["legal"]


def _pair(a, b):
    return R.check("commander", [a, b] + filler(98))


def test_commander_partners():
    leg = LEG_CREATURE
    tymna, rograkh = (card(n, type_line=leg, kw=["Partner"], text="Partner (...)", board="commander") for n in ("Tymna", "Rograkh"))
    assert _pair(tymna, rograkh)["legal"]
    pako = card("Pako", type_line=leg, kw=["Partner with", "Partner"], text="Partner with Haldan", board="commander")
    haldan = card("Haldan", type_line=leg, kw=["Partner with", "Partner"], text="Partner with Pako", board="commander")
    assert _pair(pako, haldan)["legal"]
    assert rules(_pair(pako, tymna)) == [("commander", None)]  # Partner with only pairs with its partner
    assert rules(_pair(tymna, card("Plain", type_line=leg, board="commander"))) == [("commander", None)]
    assert rules(R.check("commander", [dict(tymna, quantity=2)] + filler(98))) == [("commander", None), ("copies", "Tymna")]
    friend = lambda n: card(n, type_line=leg, text="Friends forever (...)", board="commander")
    assert _pair(friend("A"), friend("B"))["legal"]
    wilson = card("Wilson", type_line=leg, kw=["Choose a background"], board="commander")
    bg = card("Cloak", type_line="Legendary Enchantment — Background", board="commander")
    assert _pair(wilson, bg)["legal"] and _pair(bg, wilson)["legal"]
    assert not _pair(bg, bg)["legal"] and not _pair(wilson, tymna)["legal"]
    rose = card("Rose", type_line=leg, kw=["Doctor's companion"], board="commander")
    doctor = card("Doctor", type_line="Legendary Creature — Time Lord Doctor", board="commander")
    assert _pair(rose, doctor)["legal"] and not _pair(rose, tymna)["legal"]
    third = R.check("commander", [tymna, rograkh, dict(tymna, name="Esior")] + filler(97))
    assert ("commander", None) in rules(third)


def test_game_changers_counted():
    res = R.check("commander", [card("C", type_line=LEG_CREATURE, board="commander", gc=True)] + [card("G", gc=True, ci="")] + filler(98))
    assert res["game_changers"] == 2


def test_legality_from_the_database(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    oid = db.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id != 'o-dfc' LIMIT 1").fetchone()[0]
    did = decks.create(db, "C", "commander")
    decks.add_card(db, did, oid, 2)
    res = c.get(f"/api/decks/{did}/legality").json()
    assert not res["legal"] and {p["rule"] for p in res["problems"]} >= {"size", "commander"}
    assert c.get(f"/api/decks/{did}/legality?reference=nope").status_code == 422
    assert c.get("/api/decks/999/legality").status_code == 404
    casual = decks.create(db, "K")
    assert c.get(f"/api/decks/{casual}/legality").json()["problems"] == []
