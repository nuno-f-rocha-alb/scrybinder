import csv
import json
from pathlib import Path

import pytest

from scrybinder import db as dbmod, scryfall

FIX = Path(__file__).parent / "fixtures"
RAR = {"common", "uncommon", "rare", "mythic"}


@pytest.fixture(scope="session")
def bulk_file(tmp_path_factory):
    """Synthetic bulk in Scryfall format: one card per scryfall_id of the sample CSV + one double-faced card."""
    cards, seen = [], set()
    for i, r in enumerate(csv.DictReader(open(FIX / "manabox_sample.csv", encoding="utf-8-sig"))):
        if r["Scryfall ID"] in seen:
            continue
        seen.add(r["Scryfall ID"])
        cards.append({
            "id": r["Scryfall ID"], "oracle_id": f"o-{r['Name']}", "name": r["Name"], "set": r["Set code"].lower(),
            "set_name": r["Set name"], "collector_number": r["Collector number"], "released_at": "2024-01-01",
            "rarity": r["Rarity"] if r["Rarity"] in RAR else "common", "layout": "normal", "lang": "en",
            "full_art": False, "border_color": "black", "frame": "2015", "finishes": ["nonfoil", "foil"],
            "cardmarket_id": 100000 + i, "prices": {"eur": "1.50", "eur_foil": "3.00", "eur_etched": None},
            "image_uris": {"small": "http://x/s.jpg", "normal": "http://x/n.jpg"}, "digital": False})
    cards.append({
        "id": "dfc-1", "oracle_id": "o-dfc", "name": "Delver of Secrets // Insectile Aberration", "set": "isd",
        "set_name": "Innistrad", "collector_number": "51", "released_at": "2011-09-30", "rarity": "common",
        "layout": "transform", "lang": "en", "finishes": ["nonfoil", "foil"], "cardmarket_id": 1,
        "prices": {"eur": "0.10"}, "card_faces": [{"image_uris": {"small": "f-s", "normal": "f-n"}}, {}],
        "frame_effects": ["sunmoondfc"], "promo_types": []})
    p = tmp_path_factory.mktemp("bulk") / "bulk.json"
    p.write_text(json.dumps(cards), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path, bulk_file):
    conn = dbmod.connect(tmp_path / "t.db")
    scryfall.import_bulk(conn, bulk_file)
    return conn


@pytest.fixture(autouse=True)
def no_real_index(monkeypatch):
    """Tests never open the real visual index in data/: they exercise the OCR-only mode, except test_visual."""
    from scrybinder.scan import visual
    monkeypatch.setattr(visual.Visual, "try_open", classmethod(lambda cls, emb=None, db=None: None))
