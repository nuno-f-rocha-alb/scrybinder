import json
import time

import pytest
from fastapi.testclient import TestClient

from scrybinder import decks, matchup, pauper
from scrybinder.api import create_app


def _row(text="", typ="Sorcery", kw=(), cmc=2, colors=(), oid="x"):
    return {"oracle_id": oid, "oracle_text": text, "type_line": typ, "keywords": json.dumps(list(kw)), "cmc": cmc, "colors": json.dumps(list(colors)), "name": oid}


@pytest.mark.parametrize("row,want", [
    (_row("{1}, Exile this artifact: Exile all graveyards. Draw a card.", "Artifact"), {"graveyard": 1.0}),
    (_row("{T}: Add {B}.\n{T}, Sacrifice: Exile target player's graveyard.", "Land"), {"graveyard": 1.0}),
    (_row("Counter target spell if it's red.\nDestroy target permanent if it's red."), {"color:R": 1.0}),
    (_row("Destroy target artifact or enchantment."), {"artifact": 1.0, "enchantment": 1.0}),
    (_row("Electrickery deals 1 damage to target creature you don't control.\nOverload {1}{R}", kw=["Overload"]), {"creature": 1.0, "small": 1.0, "tokens": 1.0}),
    (_row("Deals 1 damage to each creature with flying."), {"flying": 1.0, "small": 1.0, "tokens": 1.0}),
    (_row("Destroy target creature."), {"creature": 1.0}),
    (_row("Prevent all combat damage that would be dealt this turn."), {"burn": 1.0, "creature": 0.5}),
    (_row("Armored: prevent all combat damage that would be dealt to it.", "Artifact Vehicle"), {}),  # a card shielding itself is no fog
    (_row("", "Creature — Spider", kw=["Reach"]), {"flying": 0.6}),
    (_row("Counter target spell."), {"combo": 0.7}),
    (_row("Exile a creature card from your graveyard: draw.", "Creature — Ghoul"), {}),  # its own graveyard is no hate
    (_row("Flying", "Creature — Bird", kw=["Flying"]), {}),
])
def test_what_a_card_answers(row, want):
    matchup._ANS.clear()
    assert matchup.answers(row) == want


def test_what_a_card_is():
    assert matchup.traits(_row("Flashback {2}", "Instant")) == {"graveyard"}
    assert matchup.traits(_row("Flying", "Artifact Creature — Thopter", kw=["Flying"], cmc=1, colors=["U"])) == {"creature", "small", "flying", "artifact", "color:U"}
    assert "burn" in matchup.traits(_row("Lightning Bolt deals 3 damage to any target.", "Instant", colors=["R"]))
    assert "graveyard" not in matchup.traits(_row("Exile all graveyards."))  # hate is not dependence


def test_style_follows_the_site_or_a_guess():
    assert matchup.style("Burn", "Control", {}, 1.0) == ("control", False)
    assert matchup.style("Ruby Storm", "", {}, 2.0) == ("combo", True)
    assert matchup.style("Faeries", "", {"counter": 0.2}, 2.5) == ("control", True)
    assert matchup.style("Rally", "", {"creature": 0.6}, 1.8) == ("aggro", True)
    assert matchup.style("Tron", "", {"creature": 0.2}, 3.5) == ("midrange", True)


def test_exposure_scales_to_what_counts_as_fully_exposed():
    prof = {"shares": {"artifact": 0.10}}
    assert matchup.exposure(prof, "aggro", "artifact") == 0.5  # 10% of 20%
    assert matchup.exposure(prof, "aggro", "combo") == 0 and matchup.exposure(prof, "combo", "combo") == 1
    assert matchup.exposure({"shares": {"artifact": 0.9}}, "aggro", "artifact") == 1.0  # never above 1


def _cards(db, n):
    return [tuple(r) for r in db.execute("SELECT oracle_id, name FROM oracle_cards WHERE name NOT LIKE '%//%' ORDER BY name LIMIT ?", (n,))]


def _set(db, oid, text, typ, colors="[]", identity="[]", cmc=2, kw="[]"):
    db.execute("UPDATE oracle_cards SET oracle_text=?, type_line=?, colors=?, color_identity=?, cmc=?, keywords=?, legalities=? WHERE oracle_id=?",
               (text, typ, colors, identity, cmc, kw, json.dumps({"pauper": "legal"}), oid))


def _world(db, tmp_path):
    """A red archetype of artifact creatures with 2 blue hosers in its sideboard, and a blue deck with a green hoser in its main deck."""
    (c0, n0), (c1, n1), (c2, n2), (c3, n3), (c4, n4), (c5, n5), (c6, n6) = _cards(db, 7)
    _set(db, c0, "", "Artifact Creature — Construct", '["R"]', '["R"]')
    _set(db, c1, "Bolt deals 3 damage to any target.", "Instant", '["R"]', '["R"]')
    _set(db, c2, "Counter target spell if it's blue.", "Instant", '["R"]', '["R"]')
    _set(db, c3, "Destroy target artifact.", "Sorcery")
    _set(db, c4, "Exile all graveyards.", "Sorcery")
    _set(db, c5, "", "Creature — Merfolk", '["U"]', '["U"]')
    _set(db, c6, "Destroy target green permanent.", "Instant")
    saved = {"fetched": time.time(), "source": "goldfish", "period": "", "decks": [
        {"id": "arch", "name": "Red Constructs", "meta": 10.0, "cat": "Aggro", "author": "", "event": "", "date": "", "url": "",
         "list": f"4 {n0}\n4 {n1}\nSideboard\n2 {n2}"}]}
    (tmp_path / "pauper").mkdir()
    (tmp_path / "pauper" / "goldfish.json").write_text(json.dumps(saved), encoding="utf-8")
    d = decks.create(db, "Blue", "pauper")
    decks.add_card(db, d, c5, 4)
    decks.add_card(db, d, c6, 2)  # a green hoser the archetype gives no use for
    decks.add_card(db, d, c4, 1, board="side")
    return d, (c0, c1, c2, c3, c4, c5, c6), (n0, n1, n2, n3, n4, n5, n6)


def test_a_matchup_reads_both_decks(db, tmp_path):
    matchup._ANS.clear()
    d, c, n = _world(db, tmp_path)
    r = matchup.analyse(db, d, "goldfish", tmp_path)
    a = r["field"][0]
    assert r["colors"] == "U" and r["deck"]["shares"]["color:U"] == 0.667 and a["style"] == "aggro" and not a["style_estimated"]
    assert a["shares"]["artifact"] == 0.5 and a["shares"]["burn"] == 0.5
    # what they bring against you: the blue hoser, and it hits your blue creatures
    threat = next(t for t in a["threats"] if t["tag"] == "color:U")
    assert (threat["their_side"], threat["their_main"], threat["cards"]) == (2, 0, [{"name": n[2], "quantity": 2}])
    assert round(threat["your_share"], 2) == 0.67
    assert any(e["tag"] == "color:U" and e["label"] == "Hosers for blue cards" for e in a["expect"])
    # what to bring in: artifact hate (they are half artifacts); graveyard hate has nothing to answer; cards already out of room are skipped
    names_in = [x["name"] for x in a["board_in"]]
    assert n[3] in names_in and n[4] not in names_in
    best = a["board_in"][0]
    assert best["oracle_id"] == c[3] and best["rel"] == 1.0 and best["copies"] == 4 and best["reasons"][0]["tag"] == "artifact"
    # what could come out: the green hoser, nothing for it to hit
    assert [(x["name"], x["quantity"]) for x in a["board_out"]] == [(n[6], 2)]
    # the graveyard hate in your sideboard does nothing here, so the field is uncovered and the plan cuts it
    assert a["cover"] == 0
    assert any(p["oracle_id"] == c[3] for p in r["plan"]) and [x["oracle_id"] for x in r["cuts"]] == [c[4]]
    assert all(p["quantity"] <= 4 for p in r["plan"]) and sum(p["quantity"] for p in r["plan"]) <= matchup.SIDE


def test_the_plan_respects_copies_already_in_the_main_deck(db, tmp_path):
    matchup._ANS.clear()
    d, c, n = _world(db, tmp_path)
    decks.add_card(db, d, c[3], 3)  # 3 of the artifact hate in the main deck: one more fits in the sideboard
    r = matchup.analyse(db, d, "goldfish", tmp_path)
    assert next(p for p in r["plan"] if p["oracle_id"] == c[3])["quantity"] == 1
    assert next(x for x in r["field"][0]["board_in"] if x["oracle_id"] == c[3])["copies"] == 1


def test_nothing_saved_and_the_wrong_format(db, tmp_path):
    d = decks.create(db, "Blue", "pauper")
    assert matchup.analyse(db, d, "goldfish", tmp_path)["field"] == []
    with pytest.raises(ValueError, match="Pauper"):
        matchup.analyse(db, decks.create(db, "M", "modern"), "goldfish", tmp_path)


def test_the_api(db, tmp_path, monkeypatch):
    matchup._ANS.clear()
    d, c, n = _world(db, tmp_path)
    monkeypatch.setattr("scrybinder.db.DATA_DIR", tmp_path)
    cl = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    cl.get("/api/status?t=t")
    assert cl.get(f"/api/pauper-meta/goldfish/matchups?deck_id={d}").status_code == 403  # off until enabled
    cl.post("/api/pauper-meta", json={"enabled": True})
    r = cl.get(f"/api/pauper-meta/goldfish/matchups?deck_id={d}").json()
    assert r["field"][0]["name"] == "Red Constructs" and r["labels"]["artifact"] == "Artifacts"
    assert cl.get("/api/pauper-meta/goldfish/matchups?deck_id=9999").status_code == 404
