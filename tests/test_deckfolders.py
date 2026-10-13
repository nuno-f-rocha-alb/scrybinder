import sqlite3

import pytest
from fastapi.testclient import TestClient

from scrybinder import db as dbmod, decks
from scrybinder.api import create_app


def test_folders_hold_decks_and_deleting_one_keeps_them(db):
    f1, f2 = decks.create_folder(db, "  Commander   pods "), decks.create_folder(db, "Brews")
    a = decks.create(db, "A", "commander", folder_id=f1)
    b = decks.create(db, "B")
    assert [(f["name"], f["decks"]) for f in decks.folders(db)] == [("Brews", 0), ("Commander pods", 1)]  # by name, with their decks
    assert {d["id"]: d["folder_id"] for d in decks.listing(db)} == {a: f1, b: None}
    decks.update(db, b, folder_id=f2)
    decks.update(db, a, name="A2")  # other changes leave the folder alone
    assert {d["id"]: d["folder_id"] for d in decks.listing(db)} == {a: f1, b: f2}
    decks.update(db, a, folder_id=None)  # null takes it out of its folder
    assert decks.get(db, a)["folder_id"] is None
    decks.delete_folder(db, f2)
    assert decks.get(db, b)["folder_id"] is None and decks.get(db, b)["name"] == "B"  # the deck stays
    assert [f["name"] for f in decks.folders(db)] == ["Commander pods"]
    with pytest.raises(KeyError):
        decks.delete_folder(db, f2)


def test_folder_names_and_ids_are_validated(db):
    f = decks.create_folder(db, "Brews")
    for bad in ("", "   ", None, 5, "x" * 61):
        with pytest.raises(ValueError):
            decks.create_folder(db, bad)
    with pytest.raises(ValueError):  # unique, whatever the case
        decks.create_folder(db, "brews")
    other = decks.create_folder(db, "Other")
    with pytest.raises(ValueError):
        decks.rename_folder(db, other, "BREWS")
    decks.rename_folder(db, f, "BREWS")  # its own name in another case is fine
    assert "BREWS" in [x["name"] for x in decks.folders(db)]
    with pytest.raises(KeyError):
        decks.rename_folder(db, 999, "x")
    d = decks.create(db, "D")
    for bad in (999, "1", True, 1.5):
        with pytest.raises(ValueError):
            decks.update(db, d, folder_id=bad)
    for bad in (999, True, "1"):
        with pytest.raises(ValueError):
            decks.create(db, "E", folder_id=bad)


def test_an_older_database_gets_the_folder_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)  # a decks table as the first builds made it
    old.execute("CREATE TABLE decks (id INTEGER PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL DEFAULT 'casual',"
                " description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')")
    old.execute("INSERT INTO decks (name) VALUES ('Old')")
    old.commit()
    old.close()
    d = dbmod.connect(path)
    assert d.execute("SELECT name, folder_id FROM decks").fetchone()[:] == ("Old", None)
    f = decks.create_folder(d, "New")
    decks.update(d, 1, folder_id=f)
    decks.delete_folder(d, f)
    assert d.execute("SELECT folder_id FROM decks").fetchone()[0] is None


def test_folder_api(db):
    c = TestClient(create_app(db, token="t", allowed_hosts={"testserver"}))
    c.get("/api/status?t=t")
    fid = c.post("/api/deck-folders", json={"name": "Pods"}).json()["id"]
    assert c.post("/api/deck-folders", json={"name": "pods"}).status_code == 422
    assert c.post("/api/deck-folders", json={}).status_code == 422
    did = c.post("/api/decks", json={"name": "A", "folder_id": fid}).json()["id"]
    assert c.post("/api/decks", json={"name": "B", "folder_id": 999}).status_code == 422
    assert c.get("/api/deck-folders").json() == [{"id": fid, "name": "Pods", "decks": 1}]
    assert [d["folder_id"] for d in c.get("/api/decks").json()] == [fid]
    assert c.patch(f"/api/decks/{did}", json={"folder_id": None}).status_code == 200
    assert c.get(f"/api/decks/{did}").json()["folder_id"] is None
    assert c.patch(f"/api/decks/{did}", json={"folder_id": fid}).status_code == 200
    assert c.patch(f"/api/decks/{did}", json={"folder_id": "x"}).status_code == 422
    assert c.patch(f"/api/deck-folders/{fid}", json={"name": "Brews"}).status_code == 200
    assert c.patch("/api/deck-folders/999", json={"name": "x"}).status_code == 404
    assert c.delete(f"/api/deck-folders/{fid}").status_code == 200
    assert c.delete(f"/api/deck-folders/{fid}").status_code == 404
    assert c.get(f"/api/decks/{did}").json()["folder_id"] is None
