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
    assert got[b["name"]]["scryfall_id"] == b["id"]  # name only: the default printing of the card (the only one here), case does not matter
    assert "Delver of Secrets // Insectile Aberration" in got  # the front face finds the double-faced card
    T.import_text(db, d, f"1 {a['name']} ({a['set_code']}) {a['collector_number']}\n")  # the same card and printing adds up
    assert {c["name"]: c["quantity"] for c in decks.get(db, d)["cards"]}[a["name"]] == 3


def test_a_printing_of_another_card_is_ignored_and_names_ignore_accents(db):
    a, b, _ = _cards(db)
    d = decks.create(db, "T")
    T.import_text(db, d, f"1 {a['name']} ({b['set_code']}) {b['collector_number']}\n")  # the printing is b's: the name wins
    c = decks.get(db, d)["cards"][0]
    assert (c["name"], c["scryfall_id"]) == (a["name"], a["id"])  # b's printing is ignored: a's default printing
    assert T._norm("Lórien Revealed ’s") == T._norm("Lorien Revealed 's")


def test_set_without_that_number_falls_back_to_the_name(db):
    a = _cards(db)[0]
    d = decks.create(db, "T")
    T.import_text(db, d, f"1 {a['name']} ({a['set_code']}) 99999\n")
    assert decks.get(db, d)["cards"][0]["scryfall_id"] == a["id"]  # no such number: the default printing


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
    decks.fill_printings(db, d)  # the lines exported without a printing got their default one on import
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
    assert out.status_code == 200 and out.text == f"Deck\n2 {a['name']} ({a['set_code'].upper()}) {a['collector_number']}\n" and "attachment" in out.headers["content-disposition"]
    assert c.get("/api/decks/999/export").status_code == 404


def test_export_and_share_leave_out_the_states_not_included(db):
    from scrybinder import collection, share
    a, b, c = _cards(db)
    d = decks.create(db, "T")
    collection.add(db, scryfall_id=a["id"], quantity=1)
    decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"])  # owned: collection
    decks.add_card(db, d, b["oracle_id"], 1, "main", b["id"], ["proxy"])
    decks.add_card(db, d, c["oracle_id"], 1, "main", c["id"])  # not owned: missing
    names = lambda text: [l.split(" (")[0][2:] for l in text.splitlines() if l[:1].isdigit()]
    assert names(T.export_text(db, d)) == [a["name"], b["name"], c["name"]]
    assert names(T.export_text(db, d, include=["proxy"])) == [b["name"]]
    assert names(T.export_text(db, d, include=["collection", "missing"])) == [a["name"], c["name"]]
    doc = share.deck_doc(db, d, include=["proxy", "missing"])
    assert sorted(l["name"] for s in doc["sections"] for l in s["cards"]) == sorted([b["name"], c["name"]])
    with pytest.raises(ValueError):
        share.deck_doc(db, d, include=[])  # nothing left to share
    with pytest.raises(ValueError):
        T.export_text(db, d, include=["nope"])
    cl = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    cl.get("/api/status?t=t")
    assert names(cl.get(f"/api/decks/{d}/export?include=proxy").text) == [b["name"]]
    assert cl.get(f"/api/decks/{d}/export?include=nope").status_code == 422


def test_bad_tags_are_skipped_and_huge_lists_refused(db):
    a = _cards(db)[0]
    d = decks.create(db, "T")
    res = T.import_text(db, d, f"1 {a['name']}\n1 {a['name']} #{'x' * 40}\n")
    assert res["cards"] == 1 and "tag" in res["skipped"][0]["reason"] and res["skipped"][0]["line"] == 2
    with pytest.raises(ValueError):
        T.import_text(db, d, "1 A\n" * 2001)


def test_finish_and_edition_survive_export_and_import(db):
    a, b, _ = _cards(db)
    d = decks.create(db, "F", "commander")
    decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"], finish="foil")  # the fixture cards come in non-foil and foil
    decks.add_card(db, d, b["oracle_id"], 2, "main", b["id"], finish="nonfoil")
    text = T.export_text(db, d)
    assert f"1 {a['name']} ({a['set_code'].upper()}) {a['collector_number']} *F*" in text
    assert "*F*" not in text.split(b["name"])[1]  # a non-foil card carries no mark
    again = decks.create(db, "Copy", "commander")
    T.import_text(db, again, text)
    got = {c["name"]: c["finish"] for c in decks.get(db, again)["cards"]}
    assert got[a["name"]] == "foil" and got[b["name"]] is None  # an unmarked line asks for no finish
    cards = {c["name"]: c for c in decks.get(db, again)["cards"]}
    assert (cards[a["name"]]["set_code"], cards[a["name"]]["collector_number"]) == (a["set_code"], a["collector_number"])
    etched = T.parse("1 X (ABC) 12 *E*\n1 Y *f*")  # Moxfield marks: *F* foil, *E* etched, case does not matter
    assert [i["finish"] for i in etched] == ["etched", "foil"]
    ok, _ = T.resolve(db, T.parse(f"1 {a['name']} ({a['set_code'].upper()}) {a['collector_number']} *E*"))
    assert ok[0]["finish"] is None  # that printing has no etched version: the finish is dropped, the line is kept


def _line(db, d, board, card):
    return next((c for c in decks.get(db, d)["cards"] if c["board"] == board and c["oracle_id"] == card["oracle_id"]), None)


def test_bulk_edit_changes_removes_and_adds(db):
    a, b, c = _cards(db)
    d = decks.create(db, "T")
    decks.add_card(db, d, a["oracle_id"], 2, "main", a["id"], ["ramp"])
    decks.add_card(db, d, b["oracle_id"], 1, "main", b["id"])
    decks.add_card(db, d, b["oracle_id"], 1, "side", b["id"])
    text = T.board_text(db, d, "main")
    assert text == f"2 {a['name']} ({a['set_code'].upper()}) {a['collector_number']} #ramp\n1 {b['name']} ({b['set_code'].upper()}) {b['collector_number']}"
    edited = f"5 {a['name']} ({a['set_code']}) {a['collector_number']} #ramp #draw\n3 {c['name']}\n"  # a up, b gone, c new
    dry = T.replace_board(db, d, "main", edited, dry_run=True)
    assert (dry["applied"], dry["added"], dry["changed"], dry["removed"]) == (
        False, [{"name": c["name"], "quantity": 3}], [{"name": a["name"], "from": 2, "to": 5}], [{"name": b["name"], "quantity": 1}])
    assert _line(db, d, "main", b) is not None  # a dry run writes nothing
    assert T.replace_board(db, d, "main", edited)["applied"] is True
    got = _line(db, d, "main", a)
    assert (got["quantity"], got["tags"]) == (5, ["draw", "ramp"]) and _line(db, d, "main", b) is None
    assert _line(db, d, "main", c)["quantity"] == 3 and _line(db, d, "side", b)["quantity"] == 1  # the other board is untouched
    T.replace_board(db, d, "main", "")  # empty box: the board is emptied
    assert [c for c in decks.get(db, d)["cards"] if c["board"] == "main"] == [] and _line(db, d, "side", b)


def test_bulk_edit_applies_nothing_while_a_line_cannot_be_read(db):
    a, b, _ = _cards(db)
    d = decks.create(db, "T")
    decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"])
    res = T.replace_board(db, d, "main", f"1 {a['name']}x\n2 {b['name']}")  # a misspelt name must not delete the card
    assert res["applied"] is False and res["skipped"][0]["line"] == 1
    assert [(c["name"], c["quantity"]) for c in decks.get(db, d)["cards"]] == [(a["name"], 1)]


def test_bulk_edit_keeps_a_line_when_only_its_printing_changes(db):
    a = _cards(db)[0]
    cols = [r[1] for r in db.execute("PRAGMA table_info(cards)")]
    row = dict(db.execute("SELECT * FROM cards WHERE id=?", (a["id"],)).fetchone())
    row.update(id="alt-print", collector_number="9999")
    db.execute(f"INSERT INTO cards ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
    other = {"id": "alt-print", "set_code": row["set_code"], "collector_number": "9999"}
    d = decks.create(db, "T")
    cid = decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"])
    T.replace_board(db, d, "main", f"1 {a['name']} ({other['set_code']}) {other['collector_number']}")
    got = decks.get(db, d)["cards"]
    assert [(c["id"], c["scryfall_id"]) for c in got] == [(cid, other["id"])]


def test_bulk_edit_api(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    a = _cards(db)[0]
    d = c.post("/api/decks", json={"name": "A"}).json()["id"]
    r = c.post(f"/api/decks/{d}/bulk-edit", json={"board": "side", "text": f"2 {a['name']}"}).json()
    assert r["applied"] and r["added"] == [{"name": a["name"], "quantity": 2}]
    assert c.get(f"/api/decks/{d}/bulk-edit?board=side").json()["text"].startswith(f"2 {a['name']}")
    assert c.post(f"/api/decks/{d}/bulk-edit", json={"board": "nope", "text": ""}).status_code == 422
    assert c.post(f"/api/decks/{d}/bulk-edit", json={"board": "main", "text": 5}).status_code == 422
    assert c.get("/api/decks/999/bulk-edit").status_code == 404


def test_bulk_edit_keeps_a_line_without_a_printing_as_it_is(db):
    a, b, _ = _cards(db)
    d = decks.create(db, "T")
    cid = decks.add_card(db, d, a["oracle_id"], 1, "main")  # no printing chosen
    res = T.replace_board(db, d, "main", f"3 {a['name']}\n1 {b['name']}")
    assert res["changed"] == [{"name": a["name"], "from": 1, "to": 3}] and [x["name"] for x in res["added"]] == [b["name"]]
    line = _line(db, d, "main", a)
    assert (line["id"], line["quantity"], line["scryfall_id"]) == (cid, 3, None)  # still the same line, printing untouched


def test_bulk_edit_keeps_duplicate_lines_and_their_copies(db):
    from scrybinder import collection
    a = _cards(db)[0]
    d = decks.create(db, "T")
    collection.add(db, scryfall_id=a["id"], quantity=2)
    first = decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"])
    second = decks.add_card(db, d, a["oracle_id"], 1, "main", a["id"], new_line=True)
    row = db.execute("SELECT id FROM collection WHERE scryfall_id=?", (a["id"],)).fetchone()["id"]
    decks.assign(db, d, second, [{"collection_id": row, "quantity": 1}])
    same = T.board_text(db, d, "main")
    assert T.replace_board(db, d, "main", same)["changed"] == []  # untouched: nothing to do
    T.replace_board(db, d, "main", same + f"\n1 {a['name']} ({a['set_code']}) {a['collector_number']}")  # one more: the first line takes it
    lines = {c["id"]: c for c in decks.get(db, d)["cards"]}
    assert (lines[first]["quantity"], lines[second]["quantity"], lines[second]["assigned"]) == (2, 1, 1)
    T.replace_board(db, d, "main", f"2 {a['name']} ({a['set_code']}) {a['collector_number']}")  # two in total: the last line gives up its copy
    lines = {c["id"]: c for c in decks.get(db, d)["cards"]}
    assert set(lines) == {first} and lines[first]["quantity"] == 2
