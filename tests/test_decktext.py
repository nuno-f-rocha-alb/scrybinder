import pytest
from fastapi.testclient import TestClient

from scrybinder import decks, decktext as T
from scrybinder.api import create_app


def _cards(db, n=3):
    return [dict(r) for r in db.execute(
        "SELECT c.id, c.oracle_id, c.name, c.set_code, c.collector_number FROM cards c JOIN oracle_cards o ON o.oracle_id = c.oracle_id"
        " WHERE c.id != 'dfc-1' GROUP BY c.oracle_id ORDER BY c.name LIMIT ?", (n,))]


def _deck_cards(db, deck):
    return sorted((c["name"], c["board"], c["quantity"], c["scryfall_id"], tuple(c["tags"])) for c in decks.get(db, deck)["cards"])


def test_parse_lines_sections_and_tags():
    got = T.parse("""// a comment
Commander
1 Atraxa, Praetors' Voice (CM2) 46 *F* #commander

Deck
4x Sol Ring (C21) 263 #ramp ^Fast Mana^ [Artifacts]
Island
SB: 2 Negate
Maybeboard:
3 Lightning Bolt
Sideboard (15)
1 Duress (M21) 097
""")
    rows = [(g["board"], g["quantity"], g["name"], g["set"], g["number"], g["tags"]) for g in got]
    assert rows == [
        ("commander", 1, "Atraxa, Praetors' Voice", "cm2", "46", ["commander"]),
        ("main", 4, "Sol Ring", "c21", "263", ["fast mana", "ramp"]),
        ("main", 1, "Island", None, None, []),
        ("side", 2, "Negate", None, None, []),
        ("maybe", 3, "Lightning Bolt", None, None, []),
        ("side", 1, "Duress", "m21", "097", [])]
    assert [g["line"] for g in got][:2] == [3, 6]
    assert T.parse("4 Xenagos, God of Revels")[0]["name"] == "Xenagos, God of Revels"  # the x of 4x is not taken from the name


def test_parse_blank_line_starts_the_sideboard_when_there_are_no_headers():
    got = T.parse("2 A\n1 B\n\n3 C\n\n4 D\n")
    assert [(g["name"], g["board"]) for g in got] == [("A", "main"), ("B", "main"), ("C", "side"), ("D", "side")]
    assert [g["board"] for g in T.parse("\n\n2 A\n")] == ["main"]  # leading blank lines do not


def test_resolve_by_printing_and_by_name(db):
    a, b, c = _cards(db)
    d = decks.create(db, "T")
    text = f"2 {a['name']} ({a['set_code'].upper()}) {a['collector_number']}\n1 {b['name'].upper()}\n1 Delver of Secrets\n1 Nope Card\n0 {c['name']}\n"
    res = T.import_text(db, d, text, dry_run=True)
    assert (res["lines"], res["cards"]) == (5, 4) and decks.get(db, d)["cards"] == []  # dry run writes nothing
    assert [(s["line"], s["reason"]) for s in res["skipped"]] == [(4, "unknown card: Nope Card"), (5, "quantity must be at least 1")]
    res = T.import_text(db, d, text)
    got = {c["name"]: c for c in decks.get(db, d)["cards"]}
    assert got[a["name"]]["scryfall_id"] == a["id"] and got[a["name"]]["quantity"] == 2  # printing from (SET) number
    assert got[b["name"]]["scryfall_id"] is None  # name only: any printing, case does not matter
    assert "Delver of Secrets // Insectile Aberration" in got  # the front face finds the double-faced card
    T.import_text(db, d, f"1 {a['name']} ({a['set_code']}) {a['collector_number']}\n")  # the same card and printing adds up
    assert {c["name"]: c["quantity"] for c in decks.get(db, d)["cards"]}[a["name"]] == 3


def test_a_printing_of_another_card_is_ignored_and_names_ignore_accents(db):
    a, b, _ = _cards(db)
    d = decks.create(db, "T")
    T.import_text(db, d, f"1 {a['name']} ({b['set_code']}) {b['collector_number']}\n")  # the printing is b's: the name wins
    c = decks.get(db, d)["cards"][0]
    assert (c["name"], c["scryfall_id"]) == (a["name"], None)
    assert T._norm("Lórien Revealed ’s") == T._norm("Lorien Revealed 's")


def test_set_without_that_number_falls_back_to_the_name(db):
    a = _cards(db)[0]
    d = decks.create(db, "T")
    T.import_text(db, d, f"1 {a['name']} ({a['set_code']}) 99999\n")
    assert decks.get(db, d)["cards"][0]["scryfall_id"] is None


def test_export_and_round_trip(db):
    a, b, c = _cards(db)
    d = decks.create(db, "T", "commander")
    decks.add_card(db, d, a["oracle_id"], 1, "commander", a["id"])
    decks.add_card(db, d, b["oracle_id"], 3, "main", b["id"], ["ramp", "Draw Cards"])
    decks.add_card(db, d, c["oracle_id"], 2, "side")
    decks.add_card(db, d, a["oracle_id"], 1, "maybe")
    text = decktext_export = T.export_text(db, d)
    assert text == (f"Commander\n1 {a['name']} ({a['set_code'].upper()}) {a['collector_number']}\n\n"
                    f"Deck\n3 {b['name']} ({b['set_code'].upper()}) {b['collector_number']} ^draw cards^ #ramp\n\n"
                    f"Sideboard\n2 {c['name']}\n")
    again = decks.create(db, "Copy", "commander")
    T.import_text(db, again, T.export_text(db, d, maybe=True))
    assert _deck_cards(db, again) == _deck_cards(db, d) and decktext_export


def test_deck_text_api(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    a = _cards(db)[0]
    d = c.post("/api/decks", json={"name": "A"}).json()["id"]
    r = c.post(f"/api/decks/{d}/import", json={"text": f"2 {a['name']}\n9 Nope", "dry_run": True}).json()
    assert r["cards"] == 2 and r["skipped"][0]["reason"].startswith("unknown card")
    assert c.post(f"/api/decks/{d}/import", json={"text": f"2 {a['name']}"}).json()["cards"] == 2
    assert c.post(f"/api/decks/{d}/import", json={"text": 5}).status_code == 422
    assert c.post("/api/decks/999/import", json={"text": "1 A"}).status_code == 404
    out = c.get(f"/api/decks/{d}/export")
    assert out.status_code == 200 and out.text == f"Deck\n2 {a['name']}\n" and "attachment" in out.headers["content-disposition"]
    assert c.get("/api/decks/999/export").status_code == 404


def test_bad_tags_are_skipped_and_huge_lists_refused(db):
    a = _cards(db)[0]
    d = decks.create(db, "T")
    res = T.import_text(db, d, f"1 {a['name']}\n1 {a['name']} #{'x' * 40}\n")
    assert res["cards"] == 1 and "tag" in res["skipped"][0]["reason"] and res["skipped"][0]["line"] == 2
    with pytest.raises(ValueError):
        T.import_text(db, d, "1 A\n" * 2001)
