import sqlite3

from scrybinder import db as dbmod, decks, scryfall
from test_oracle import _bulk, _card


def test_power_toughness_imported_front_face_and_returned_with_deck_cards(tmp_path):
    d = dbmod.connect(tmp_path / "t.db")
    scryfall.import_bulk(d, _bulk(tmp_path, [
        _card("a1", "o1", "Bear", "2020-01-01", power="2", toughness="2"),
        _card("a2", "o2", "Star", "2020-01-01", power="*", toughness="1+*"),
        _card("a3", "o3", "Aura", "2020-01-01", type_line="Enchantment — Aura"),
        _card("m1", "o4", "Front // Back", "2023-01-01", layout="transform", mana_cost=None, oracle_text=None, type_line=None, colors=None,
              card_faces=[{"mana_cost": "{G}", "type_line": "Creature — Human", "oracle_text": "x", "colors": ["G"], "power": "1", "toughness": "3"},
                          {"mana_cost": "", "type_line": "Creature — Wolf", "oracle_text": "y", "power": "4", "toughness": "4"}])]))
    rows = {r["oracle_id"]: (r["power"], r["toughness"]) for r in d.execute("SELECT * FROM oracle_cards")}
    assert rows == {"o1": ("2", "2"), "o2": ("*", "1+*"), "o3": (None, None), "o4": ("1", "3")}
    deck_id = decks.create(d, "T")
    decks.add_card(d, deck_id, "o1", 1, "main")
    card = decks.cards(d, deck_id)[0]
    assert (card["power"], card["toughness"]) == ("2", "2")


def test_migration_adds_the_columns_to_an_older_database_and_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE oracle_cards (oracle_id TEXT PRIMARY KEY, name TEXT NOT NULL, mana_cost TEXT, cmc REAL, type_line TEXT, colors TEXT,"
                " color_identity TEXT, oracle_text TEXT, keywords TEXT, produced_mana TEXT, legalities TEXT, game_changer INTEGER NOT NULL DEFAULT 0,"
                " edhrec_rank INTEGER, layout TEXT, released_at TEXT)")
    old.commit()
    old.close()
    for _ in range(2):  # opening it again must not fail
        d = dbmod.connect(path)
        cols = {r[1] for r in d.execute("PRAGMA table_info(oracle_cards)")}
        assert {"power", "toughness"} <= cols
        d.close()
