import html
import json

import httpx
import pytest

from scrybinder import deckurl, decktext

MOX = {"boards": {"commanders": {"cards": {"a": {"quantity": 1, "finish": "nonfoil", "card": {"name": "Sol Ring", "set": "c21", "cn": "263"}}}},
                  "mainboard": {"cards": {"b": {"quantity": 2, "finish": "foil", "card": {"name": "Island", "set": "thb", "cn": "250"}}}},
                  "sideboard": {"cards": {}}, "maybeboard": {"cards": {"c": {"quantity": 1, "card": {"name": "Opt"}}}}}}
ARCH = {"cards": [{"quantity": 1, "categories": ["Commander"], "modifier": "Normal", "card": {"collectorNumber": "9", "edition": {"editioncode": "tsp"}, "oracleCard": {"name": "Thelon"}}},
                  {"quantity": 3, "categories": None, "modifier": "Etched", "card": {"collectorNumber": "1", "edition": None, "oracleCard": {"name": "Forest"}}},
                  {"quantity": 1, "categories": ["Maybeboard", "Ramp"], "modifier": "Normal", "card": {"oracleCard": {"name": "Cultivate"}}}]}


def test_moxfield_and_archidekt_become_text_lists(monkeypatch):
    asked = []
    monkeypatch.setattr(deckurl, "_get", lambda u, *_: asked.append(u) or (MOX if "moxfield" in u else ARCH))
    p = decktext.parse(deckurl.fetch_text("https://www.moxfield.com/decks/AbCd_12-x"))
    assert [(x["board"], x["quantity"], x["name"], x["set"], x["finish"]) for x in p] == [
        ("commander", 1, "Sol Ring", "c21", None), ("main", 2, "Island", "thb", "foil"), ("maybe", 1, "Opt", None, None)]
    p = decktext.parse(deckurl.fetch_text("https://archidekt.com/decks/42/some-name"))
    assert [(x["board"], x["name"], x["finish"]) for x in p] == [("commander", "Thelon", None), ("main", "Forest", "etched"), ("maybe", "Cultivate", None)]
    assert asked == ["https://api2.moxfield.com/v3/decks/all/AbCd_12-x", "https://archidekt.com/api/decks/42/"]  # the address is ours, not the link's


def test_manabox_reads_the_deck_from_the_page(monkeypatch):
    props = html.escape(json.dumps({"deck": [0, {"name": [0, "X"], "cards": [1, [
        [0, {"quantity": [0, 1], "name": [0, "Cosmic Spider-Man"], "setId": [0, "SPM"], "collectorNumber": [0, "1"], "boardCategory": [0, 0], "variant": [0, "Normal"]}],
        [0, {"quantity": [0, 5], "name": [0, "Island"], "setId": [0, "spm"], "collectorNumber": [0, "9"], "boardCategory": [0, 3], "variant": [0, "Foil"]}],
        [0, {"quantity": [0, 1], "name": [0, "Silkguard"], "boardCategory": [0, 4], "variant": [0, "Normal"]}]]]}]}))
    page = f'<astro-island props="{{&quot;slot&quot;:[0,&quot;x&quot;]}}"></astro-island><astro-island uid="1" props="{props}" ssr></astro-island>'
    monkeypatch.setattr(deckurl, "_page", lambda u: page)
    p = decktext.parse(deckurl.fetch_text("https://manabox.app/decks/AZ8FpLOsebm767SKcd6DSQ"))
    assert [(x["board"], x["quantity"], x["name"], x["set"], x["finish"]) for x in p] == [
        ("commander", 1, "Cosmic Spider-Man", "spm", None), ("main", 5, "Island", "spm", "foil"), ("side", 1, "Silkguard", None, None)]
    monkeypatch.setattr(deckurl, "_page", lambda u: "<html>Unknown deck</html>")
    with pytest.raises(ValueError):
        deckurl.fetch_text("https://manabox.app/decks/AZ8FpLOsebm767SKcd6DSQ")


@pytest.mark.parametrize("url", ["", None, "http://moxfield.com/decks/abcd", "https://evil.com/decks/1", "https://moxfield.com.evil.com/decks/abcd",
                                 "https://archidekt.com/decks/abc", "https://manabox.app/decks/short", "https://moxfield.com/users/x"])
def test_other_links_are_refused(url, monkeypatch):
    monkeypatch.setattr(deckurl, "_get", lambda u, *_: pytest.fail("must not fetch"))
    with pytest.raises(ValueError):
        deckurl.fetch_text(url)


def test_a_deck_in_an_unexpected_shape_is_a_clear_error_not_a_404(monkeypatch):
    monkeypatch.setattr(deckurl, "_get", lambda u, *_: {"boards": {"mainboard": {"cards": {"a": {"quantity": 1}}}}})
    with pytest.raises(ValueError):
        deckurl.fetch_text("https://moxfield.com/decks/abcd1234")


def test_moxfield_403_tells_the_user_to_paste_the_export(monkeypatch):
    monkeypatch.setattr(deckurl.httpx, "get", lambda *a, **k: httpx.Response(403, request=httpx.Request("GET", a[0])))
    with pytest.raises(ValueError, match="paste it below"):
        deckurl.fetch_text("https://moxfield.com/decks/abcd1234")
    with pytest.raises(ValueError, match="private"):  # other sites keep the generic message
        deckurl.fetch_text("https://archidekt.com/decks/42")
