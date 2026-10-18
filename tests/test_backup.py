import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scrybinder import collection, db as dbmod, decks, scryfall
from scrybinder.api import create_app

TOKEN = "t"


def _populate(db):
    sid = db.execute("SELECT id FROM cards ORDER BY id LIMIT 1").fetchone()[0]
    oid = db.execute("SELECT oracle_id FROM cards WHERE id=?", (sid,)).fetchone()[0]
    collection.add(db, scryfall_id=sid, quantity=3)
    decks.add_card(db, decks.create(db, "D"), oid, 2)


def _counts(path):
    con = sqlite3.connect(path)
    try:
        return [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("collection", "decks", "deck_cards", "cards")]
    finally:
        con.close()


def _db(tmp_path, bulk_file, name="live.db"):
    db = dbmod.connect(tmp_path / name)
    scryfall.import_bulk(db, bulk_file)
    _populate(db)
    return db


def test_backup_is_a_consistent_copy_and_the_source_keeps_working(tmp_path, bulk_file):
    db = _db(tmp_path, bulk_file)
    out = dbmod.backup(db, tmp_path / "b.db")
    assert out["bytes"] > 0 and not list(tmp_path.glob("*.tmp"))
    assert _counts(tmp_path / "b.db") == _counts(tmp_path / "live.db")
    assert db.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 1
    assert dbmod.backup(tmp_path / "live.db", tmp_path / "from-path.db")["bytes"] > 0  # a path works as the source too
    assert _counts(tmp_path / "from-path.db") == _counts(tmp_path / "b.db")


def test_validate_accepts_a_backup_and_rejects_the_rest(tmp_path, bulk_file):
    db = _db(tmp_path, bulk_file)
    dbmod.backup(db, tmp_path / "b.db")
    ok = dbmod.validate_backup(tmp_path / "b.db")
    assert ok["ok"] and ok["collection"] == 1 and ok["cards"] > 0
    (tmp_path / "junk.db").write_bytes(bytes(range(256)) * 40)
    assert not dbmod.validate_backup(tmp_path / "junk.db")["ok"]
    other = sqlite3.connect(tmp_path / "other.db")
    other.execute("CREATE TABLE cards (id TEXT)")
    other.commit()
    other.close()
    res = dbmod.validate_backup(tmp_path / "other.db")
    assert not res["ok"] and "collection" in res["reason"]
    assert not dbmod.validate_backup(tmp_path / "missing.db")["ok"]


def test_stage_then_apply_restores_and_keeps_the_old_database(tmp_path, bulk_file):
    live = _db(tmp_path, bulk_file, "scrybinder.db")
    dbmod.backup(live, tmp_path / "old.db")  # the backup holds 1 collection row
    sid = live.execute("SELECT id FROM cards ORDER BY id DESC LIMIT 1").fetchone()[0]
    collection.add(live, scryfall_id=sid, quantity=1, location="Later")  # now 2 rows: newer than the backup
    live.commit()
    path = tmp_path / "scrybinder.db"
    pending = tmp_path / "scrybinder.db.restore-pending"
    with pytest.raises(ValueError):
        dbmod.stage_restore(path, tmp_path / "missing.db")
    assert not pending.exists()
    dbmod.stage_restore(path, tmp_path / "old.db")
    assert pending.exists() and dbmod.validate_backup(pending)["ok"]
    assert _counts(path)[0] == 2  # nothing changes until the next start
    live.close()
    dbmod._apply_pending_restore(path)
    assert not pending.exists() and (tmp_path / "scrybinder.db.before-restore").exists()
    assert _counts(path)[0] == 1 and _counts(tmp_path / "scrybinder.db.before-restore")[0] == 2
    dbmod.connect(path).close()  # opens and migrates cleanly
    dbmod._apply_pending_restore(path)  # no pending file: nothing happens
    assert _counts(path)[0] == 1 and _counts(tmp_path / "scrybinder.db.before-restore")[0] == 2


def test_apply_without_a_current_database_and_stale_wal(tmp_path, bulk_file):
    src = _db(tmp_path, bulk_file, "src.db")
    path = tmp_path / "scrybinder.db"
    dbmod.stage_restore(path, tmp_path / "src.db")
    (tmp_path / "scrybinder.db-wal").write_bytes(b"stale")  # leftovers of a database that is not there any more
    dbmod._apply_pending_restore(path)
    assert not (tmp_path / "scrybinder.db.before-restore").exists() and not (tmp_path / "scrybinder.db-wal").exists()
    assert _counts(path)[0] == 1
    src.close()


def test_connect_without_a_pending_file_changes_nothing(tmp_path, bulk_file):
    db = _db(tmp_path, bulk_file, "plain.db")
    db.close()
    dbmod.connect(tmp_path / "plain.db").close()
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("plain.db")) == ["plain.db"]


def test_backup_and_restore_api(tmp_path, bulk_file):
    db = _db(tmp_path, bulk_file, "api.db")
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    r = c.get("/api/backup")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3\x00") and "attachment" in r.headers["content-disposition"]
    assert not list(tmp_path.glob("tmp*"))  # the temporary copy is removed after the download
    ok = c.post("/api/restore", content=r.content)
    assert ok.status_code == 200 and ok.json() == {"staged": True, "restart_required": True, "cards": ok.json()["cards"], "collection": 1}
    assert (tmp_path / "api.db.restore-pending").exists()
    bad = c.post("/api/restore", content=b"not a database " * 100)
    assert bad.status_code == 422 and bad.json()["detail"]
    assert c.post("/api/restore", content=b"").status_code == 422
    assert not list(tmp_path.glob("tmp*"))


def test_the_kept_database_has_what_was_still_in_its_journal(tmp_path, bulk_file):
    import shutil
    src = _db(tmp_path, bulk_file, "src.db")
    dbmod.backup(src, tmp_path / "b.db")
    live = dbmod.connect(tmp_path / "live.db")
    scryfall.import_bulk(live, bulk_file)
    live.execute("PRAGMA wal_autocheckpoint=0")
    collection.add(live, scryfall_id=live.execute("SELECT id FROM cards LIMIT 1").fetchone()[0], quantity=4)  # only in the -wal so far
    collection.add(live, scryfall_id=live.execute("SELECT id FROM cards LIMIT 1").fetchone()[0], quantity=1, location="X")
    crashed = tmp_path / "crashed"  # what is left on disk if the app dies now: the file and its journal
    crashed.mkdir()
    for suffix in ("", "-wal", "-shm"):
        if (tmp_path / f"live.db{suffix}").exists():
            shutil.copy(tmp_path / f"live.db{suffix}", crashed / f"scrybinder.db{suffix}")
    live.close()
    assert (crashed / "scrybinder.db-wal").stat().st_size > 0
    dbmod.stage_restore(crashed / "scrybinder.db", tmp_path / "b.db")
    dbmod._apply_pending_restore(crashed / "scrybinder.db")
    assert _counts(crashed / "scrybinder.db.before-restore")[0] == 2  # the rows that lived in the journal are kept
    assert _counts(crashed / "scrybinder.db")[0] == 1


def test_a_backup_cannot_overwrite_its_own_source(tmp_path, bulk_file):
    db = _db(tmp_path, bulk_file)
    with pytest.raises(ValueError):
        dbmod.backup(db, tmp_path / "live.db")
    with pytest.raises(ValueError):
        dbmod.backup(tmp_path / "live.db", tmp_path / "live.db")
    assert db.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 1 and _counts(tmp_path / "live.db")[0] == 1


def test_apply_waits_for_the_previous_instance_to_let_go(tmp_path, bulk_file, monkeypatch):
    live = _db(tmp_path, bulk_file, "scrybinder.db")
    dbmod.backup(live, tmp_path / "b.db")
    live.close()
    path = tmp_path / "scrybinder.db"
    dbmod.stage_restore(path, tmp_path / "b.db")
    real, locked = dbmod.os.replace, {"n": 0}

    def replace(src, dst):  # the database is "in use" for the first three tries
        if Path(src) == path and locked["n"] < 3:
            locked["n"] += 1
            raise PermissionError("in use")
        return real(src, dst)
    monkeypatch.setattr(dbmod.os, "replace", replace)
    monkeypatch.setattr(dbmod.time, "sleep", lambda s: None)
    dbmod._apply_pending_restore(path)
    assert locked["n"] == 3 and not (tmp_path / "scrybinder.db.restore-pending").exists() and (tmp_path / "scrybinder.db.before-restore").exists()


def test_apply_gives_up_when_the_database_stays_in_use(tmp_path, bulk_file, monkeypatch):
    live = _db(tmp_path, bulk_file, "scrybinder.db")
    dbmod.backup(live, tmp_path / "b.db")
    live.close()
    path = tmp_path / "scrybinder.db"
    dbmod.stage_restore(path, tmp_path / "b.db")
    real = dbmod.os.replace
    monkeypatch.setattr(dbmod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("in use")) if Path(s) == path else real(s, d))
    monkeypatch.setattr(dbmod.time, "sleep", lambda s: None)
    dbmod._apply_pending_restore(path)  # no error: the app starts with what it has
    assert (tmp_path / "scrybinder.db.restore-pending").exists() and not (tmp_path / "scrybinder.db.before-restore").exists() and _counts(path)[0] == 1
