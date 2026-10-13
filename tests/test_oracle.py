import json

from scrybinder import db as dbmod, scryfall

LEG = {"commander": "legal", "modern": "banned"}


def _card(i, oid, name, released, **kw):
    return {"id": i, "oracle_id": oid, "name": name, "set": "x", "set_name": "X", "collector_number": i, "released_at": released,
            "rarity": "common", "layout": "normal", "lang": "en", "finishes": ["nonfoil"], "prices": {}, "digital": False,
            "mana_cost": "{1}{G}", "cmc": 2.0, "type_line": "Creature", "colors": ["G"], "color_identity": ["G"],
            "oracle_text": "Trample", "keywords": ["Trample"], "legalities": LEG, **kw}


def _bulk(tmp_path, cards):
    p = tmp_path / "b.json"
    p.write_text(json.dumps(cards), encoding="utf-8")
    return p


def test_oracle_import_newest_printing_and_fields(tmp_path):
    d = dbmod.connect(tmp_path / "t.db")
    scryfall.import_bulk(d, _bulk(tmp_path, [
        _card("a1", "o1", "Bear", "2020-01-01", oracle_text="old text", edhrec_rank=5),
        _card("a2", "o1", "Bear", "2023-01-01", game_changer=True, produced_mana=["G"]),
        _card("t1", "o2", "Bear Token", "2023-01-01", layout="token"),
        _card("m1", "o3", "Front // Back", "2023-01-01", layout="modal_dfc", mana_cost=None, oracle_text=None, type_line=None,
              colors=None, card_faces=[{"mana_cost": "{R}", "type_line": "Sorcery", "oracle_text": "Burn", "colors": ["R"]},
                                       {"mana_cost": "", "type_line": "Land", "oracle_text": "Tap for R"}])]))
    rows = {r["oracle_id"]: r for r in d.execute("SELECT * FROM oracle_cards")}
    assert set(rows) == {"o1", "o3"}  # token skipped, one row per oracle_id
    b = rows["o1"]
    assert b["released_at"] == "2023-01-01" and b["oracle_text"] == "Trample" and b["game_changer"] == 1
    assert json.loads(b["legalities"]) == LEG and json.loads(b["color_identity"]) == ["G"] and json.loads(b["produced_mana"]) == ["G"]
    m = rows["o3"]
    assert (m["mana_cost"], m["type_line"], m["oracle_text"]) == ("{R}", "Sorcery", "Burn // Tap for R")
    assert d.execute("SELECT name FROM oracle_fts WHERE oracle_fts MATCH 'burn'").fetchone()["name"] == "Front // Back"


def test_backfill_from_cached_file(tmp_path):
    d = dbmod.connect(tmp_path / "t.db")
    path = _bulk(tmp_path, [_card("a1", "o1", "Bear", "2020-01-01"), _card("a2", "o2", "Elk", "2021-01-01")])
    assert scryfall.backfill_oracle(d, path) == 2
    assert d.execute("SELECT COUNT(*) FROM oracle_cards").fetchone()[0] == 2
    assert d.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0  # only the oracle table is touched
