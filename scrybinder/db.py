"""SQLite: connection and schema. Data lives in data/ (not in git)."""
import os
import logging
import sqlite3
import sys
import time
from pathlib import Path



def default_data_dir() -> Path:
    """Where the database, images and index live.

    From source: ./data in the repository. Packaged app: a per-user folder (Program Files is not writable), or ./data next to
    the executable for the portable zip (a `data` folder or a `portable.txt` file beside it). SCRYBINDER_DATA overrides all of it.
    """
    if env := os.environ.get("SCRYBINDER_DATA"):
        return Path(env)
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent / "data"
    exe_dir = Path(sys.executable).parent
    if (exe_dir / "data").is_dir() or (exe_dir / "portable.txt").exists():
        return exe_dir / "data"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Scrybinder"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Scrybinder"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "scrybinder"


DATA_DIR = default_data_dir()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY, oracle_id TEXT, name TEXT NOT NULL, set_code TEXT, set_name TEXT,
    collector_number TEXT, released_at TEXT, rarity TEXT, layout TEXT, lang TEXT, type_line TEXT,
    full_art INTEGER, border_color TEXT, frame TEXT, frame_effects TEXT, promo_types TEXT, finishes TEXT,
    cardmarket_id INTEGER, eur REAL, eur_foil REAL, eur_etched REAL,
    image_small TEXT, image_normal TEXT, digital INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cards_oracle ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS cards_set ON cards(set_code, collector_number);
DROP INDEX IF EXISTS cards_name;
CREATE INDEX IF NOT EXISTS cards_name_upper ON cards(UPPER(name));  -- case-insensitive name search
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, content='cards', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');

CREATE TABLE IF NOT EXISTS collection (
    id INTEGER PRIMARY KEY,
    scryfall_id TEXT NOT NULL REFERENCES cards(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    finish TEXT NOT NULL DEFAULT 'nonfoil' CHECK (finish IN ('nonfoil','foil','etched')),
    condition TEXT NOT NULL DEFAULT 'NM' CHECK (condition IN ('NM','LP','MP','HP','DMG')),
    language TEXT NOT NULL DEFAULT 'en',
    location TEXT NOT NULL DEFAULT '',
    altered INTEGER NOT NULL DEFAULT 0, signed INTEGER NOT NULL DEFAULT 0,
    misprint INTEGER NOT NULL DEFAULT 0, proxy INTEGER NOT NULL DEFAULT 0,
    purchase_price REAL, purchase_currency TEXT DEFAULT 'EUR', purchase_date TEXT,
    notes TEXT NOT NULL DEFAULT '', manabox_id INTEGER,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (scryfall_id, finish, condition, language, location, altered, signed, misprint, proxy)
);
CREATE INDEX IF NOT EXISTS collection_loc ON collection(location);
CREATE TABLE IF NOT EXISTS locations (name TEXT PRIMARY KEY);  -- locations made on purpose: they exist while empty

CREATE TABLE IF NOT EXISTS sets (code TEXT PRIMARY KEY, name TEXT, icon_svg_uri TEXT, set_type TEXT, released_at TEXT);

CREATE TABLE IF NOT EXISTS set_totals (code TEXT PRIMARY KEY, name TEXT, released_at TEXT, total INTEGER, total_grouped INTEGER);

CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    capture_path TEXT, ocr_json TEXT, predicted_id TEXT, final_id TEXT REFERENCES cards(id),
    corrected INTEGER NOT NULL DEFAULT 0, location TEXT NOT NULL DEFAULT ''
);  -- capture → correct printing pairs: training/evaluation data for the matcher

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS price_snapshots (  -- the collection's value after each price refresh, one row a day ('' = the whole collection)
    date TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', total_value REAL NOT NULL, total_cards INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), PRIMARY KEY (date, location)
);

CREATE TABLE IF NOT EXISTS card_faces (  -- one row per face that has its own image (visual index)
    card_id TEXT NOT NULL REFERENCES cards(id), face INTEGER NOT NULL, illustration_id TEXT, image_normal TEXT,
    PRIMARY KEY (card_id, face)
);
CREATE INDEX IF NOT EXISTS card_faces_ill ON card_faces(illustration_id);

CREATE TABLE IF NOT EXISTS oracle_cards (  -- one row per oracle_id: the rules data decks need (the latest printing wins)
    oracle_id TEXT PRIMARY KEY, name TEXT NOT NULL, mana_cost TEXT, cmc REAL, type_line TEXT,
    colors TEXT, color_identity TEXT, oracle_text TEXT, keywords TEXT, produced_mana TEXT,
    legalities TEXT, game_changer INTEGER NOT NULL DEFAULT 0, edhrec_rank INTEGER, power TEXT, toughness TEXT, layout TEXT, released_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS oracle_fts USING fts5(
    name, oracle_text, content='oracle_cards', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');

CREATE TABLE IF NOT EXISTS oracle_tokens (  -- the tokens a card makes (Scryfall's all_parts); token_id is a printing in cards
    oracle_id TEXT NOT NULL, token_id TEXT NOT NULL, PRIMARY KEY (oracle_id, token_id)
);

CREATE TABLE IF NOT EXISTS rulings (  -- Scryfall rulings, fetched when a card's details are opened and kept for a while
    oracle_id TEXT PRIMARY KEY, data TEXT NOT NULL, fetched TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deck_folders (  -- one level: a deck is in a folder or in none
    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL DEFAULT 'casual', description TEXT NOT NULL DEFAULT '',
    folder_id INTEGER REFERENCES deck_folders(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS deck_cards (  -- scryfall_id is the preferred printing (NULL = any)
    id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    oracle_id TEXT NOT NULL REFERENCES oracle_cards(oracle_id), scryfall_id TEXT REFERENCES cards(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0), board TEXT NOT NULL DEFAULT 'main' CHECK (board IN ('main','side','commander','maybe')),
    finish TEXT  -- the finish of the preferred printing (NULL = not chosen)
);
CREATE TABLE IF NOT EXISTS deck_snapshots (  -- a saved copy of a deck's card list, to compare later
    id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE, name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS deck_snapshot_cards (
    snapshot_id INTEGER NOT NULL REFERENCES deck_snapshots(id) ON DELETE CASCADE, oracle_id TEXT NOT NULL, scryfall_id TEXT, finish TEXT,
    board TEXT NOT NULL, quantity INTEGER NOT NULL, name TEXT NOT NULL, price REAL
);
CREATE INDEX IF NOT EXISTS deck_snapshot_cards_snap ON deck_snapshot_cards(snapshot_id);
CREATE TABLE IF NOT EXISTS deck_card_tags (
    deck_card_id INTEGER NOT NULL REFERENCES deck_cards(id) ON DELETE CASCADE, tag TEXT NOT NULL, PRIMARY KEY (deck_card_id, tag)
);
CREATE TABLE IF NOT EXISTS deck_assignments (  -- copies of a collection row reserved for a deck card
    deck_card_id INTEGER NOT NULL REFERENCES deck_cards(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (deck_card_id, collection_id)
);
CREATE INDEX IF NOT EXISTS deck_assignments_coll ON deck_assignments(collection_id);

CREATE TABLE IF NOT EXISTS trades (  -- an in-person trade or sale: a draft until confirmed; cash = euros received (negative = paid)
    id INTEGER PRIMARY KEY, who TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', cash REAL NOT NULL DEFAULT 0, traded_on TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','done')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), done_at TEXT
);
CREATE TABLE IF NOT EXISTS trade_out (  -- copies leaving, named by collection row key (row ids change); price NULL = market price
    id INTEGER PRIMARY KEY, trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE, scryfall_id TEXT NOT NULL REFERENCES cards(id),
    finish TEXT NOT NULL, condition TEXT NOT NULL, language TEXT NOT NULL, location TEXT NOT NULL,
    altered INTEGER NOT NULL DEFAULT 0, signed INTEGER NOT NULL DEFAULT 0, misprint INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL CHECK (quantity > 0), price REAL,
    untracked INTEGER NOT NULL DEFAULT 0,  -- 1: a card you own that is not in the collection: recorded, nothing is taken out at confirm
    UNIQUE (trade_id, scryfall_id, finish, condition, language, location, altered, signed, misprint, untracked)
);
CREATE TABLE IF NOT EXISTS lists (  -- a named set of cards picked to look at and to share; not a location
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS list_items (  -- copies of what was picked, not links to collection rows
    id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE, scryfall_id TEXT NOT NULL REFERENCES cards(id),
    finish TEXT NOT NULL DEFAULT 'nonfoil', condition TEXT NOT NULL DEFAULT 'NM', language TEXT NOT NULL DEFAULT 'en',
    quantity INTEGER NOT NULL CHECK (quantity > 0), note TEXT NOT NULL DEFAULT '',
    UNIQUE (list_id, scryfall_id, finish, condition, language)
);
CREATE TABLE IF NOT EXISTS shares (  -- links made with the share service; delete_token is the secret that lets this app remove one
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, delete_token TEXT NOT NULL, expires_at TEXT, spec TEXT, ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS cm_prices (  -- Cardmarket's price guide, by product (cards.cardmarket_id); see cardmarket.py
    id_product INTEGER PRIMARY KEY, avg REAL, low REAL, trend REAL, avg_foil REAL, low_foil REAL, trend_foil REAL
);
CREATE TABLE IF NOT EXISTS cm_link (scryfall_id TEXT PRIMARY KEY, id_product INTEGER NOT NULL);  -- The List cards Scryfall has no product for
CREATE TABLE IF NOT EXISTS trade_in (
    id INTEGER PRIMARY KEY, trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE, scryfall_id TEXT NOT NULL REFERENCES cards(id),
    finish TEXT NOT NULL, condition TEXT NOT NULL, language TEXT NOT NULL, location TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL CHECK (quantity > 0), price REAL,
    UNIQUE (trade_id, scryfall_id, finish, condition, language, location)
);
"""

# additive migrations (never delete or rewrite data): (table, column, definition)
_ADD = [("decks", "folder_id", "INTEGER REFERENCES deck_folders(id) ON DELETE SET NULL"),
        ("decks", "cover_card_id", "INTEGER REFERENCES deck_cards(id) ON DELETE SET NULL"), ("deck_cards", "finish", "TEXT"), ("cards", "illustration_id", "TEXT"), ("cards", "image_status", "TEXT"), ("scan_log", "topk_json", "TEXT"),
        ("oracle_cards", "power", "TEXT"), ("oracle_cards", "toughness", "TEXT"), ("trades", "traded_on", "TEXT"), ("shares", "spec", "TEXT"), ("shares", "ref", "TEXT"),
        # sf_*: Scryfall's own prices (eur/eur_foil may hold Cardmarket's instead); cm_*: the Cardmarket price guide of the printing
        ("cards", "sf_eur", "REAL"), ("cards", "sf_eur_foil", "REAL"), ("cards", "cm_avg", "REAL"), ("cards", "cm_low", "REAL"),
        ("cards", "cm_trend", "REAL"), ("cards", "cm_avg_foil", "REAL"), ("cards", "cm_low_foil", "REAL"), ("cards", "cm_trend_foil", "REAL")]


def _migrate(db):
    for table, col, ddl in _ADD:
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    db.execute("CREATE INDEX IF NOT EXISTS cards_ill ON cards(illustration_id)")
    db.execute("DROP INDEX IF EXISTS deck_cards_key")  # replaced: the same card in two finishes are two rows
    db.execute("DROP INDEX IF EXISTS deck_cards_key2")  # a deck may have several lines of the same card (one per art)
    db.execute("CREATE INDEX IF NOT EXISTS deck_cards_find ON deck_cards(deck_id, oracle_id)")


def _seed_scryfall_prices(db):
    """Once, keep Scryfall's prices apart (nothing has overwritten them yet): later imports fill sf_* themselves."""
    if db.execute("SELECT 1 FROM meta WHERE key='sf_prices_seeded'").fetchone():
        return
    with db:
        db.execute("UPDATE cards SET sf_eur = eur, sf_eur_foil = eur_foil")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('sf_prices_seeded', '1')")


def _fix_reversible(db):
    """Reversible cards were stored without an oracle_id, so no printing list found them. Once, give them the oracle_id of the card
    named like their first face (a later bulk import does it from the faces)."""
    if db.execute("SELECT 1 FROM meta WHERE key='reversible_fixed'").fetchone():
        return
    with db:
        db.execute("UPDATE cards SET oracle_id = (SELECT k.oracle_id FROM cards k WHERE UPPER(k.name) = UPPER(substr(cards.name, 1, instr(cards.name, ' // ') - 1))"
                   " AND k.oracle_id IS NOT NULL LIMIT 1) WHERE oracle_id IS NULL AND layout = 'reversible_card' AND instr(name, ' // ') > 0")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('reversible_fixed', '1')")


def _adopt_legacy_db(path: Path):
    """The project used to be called Cardex: keep an existing collection by renaming its database files."""
    old = path.with_name("cardex.db")
    if not path.exists() and old.exists():
        for suffix in ("", "-wal", "-shm"):
            if Path(str(old) + suffix).exists():
                Path(str(old) + suffix).rename(Path(str(path) + suffix))


RESTORE_WAIT_TRIES, RESTORE_WAIT_STEP = 60, 0.5  # up to 30 s for the previous instance to let go of the database
REQUIRED_TABLES = ("cards", "collection", "decks", "deck_cards", "deck_assignments", "oracle_cards")


def backup(src, dest) -> dict:
    """A consistent single-file copy of a database (a connection or a path) with SQLite's online backup, safe while the app is
    using it. Written under a temporary name and renamed, so a failure leaves no half file at `dest`."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    own = None
    here = Path(src.execute("PRAGMA database_list").fetchone()[2]) if isinstance(src, sqlite3.Connection) else Path(src)
    if here.exists() and dest.exists() and here.resolve() == dest.resolve():
        raise ValueError("the backup cannot be written over the database it is a copy of")
    try:
        if not isinstance(src, sqlite3.Connection):
            src = own = sqlite3.connect(f"file:{Path(src).as_posix()}?mode=ro", uri=True)
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if own:
            own.close()
    return {"path": str(dest), "bytes": dest.stat().st_size}


def validate_backup(path) -> dict:
    """Is this file a Scrybinder database that can be restored? Never raises: `{ok, reason, cards, collection}`."""
    bad = lambda why: {"ok": False, "reason": why, "cards": 0, "collection": 0}
    try:
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return bad(f"cannot open the file: {e}")
    try:
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return bad("the database is damaged (integrity check failed)")
            have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t in REQUIRED_TABLES if t not in have]
            if missing:
                return bad("not a Scrybinder database (missing: " + ", ".join(missing) + ")")
            return {"ok": True, "reason": "", "cards": con.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                    "collection": con.execute("SELECT COUNT(*) FROM collection").fetchone()[0]}
        except sqlite3.Error as e:
            return bad(f"not a usable database: {e}")
    finally:
        con.close()


def stage_restore(db_path, src) -> dict:
    """Check a backup and put it beside the database as `<db>.restore-pending`; it replaces the database at the next start
    (`_apply_pending_restore`), because the running app holds the database open."""
    info = validate_backup(src)
    if not info["ok"]:
        raise ValueError(info["reason"])
    pending = Path(str(db_path) + ".restore-pending")
    tmp = pending.with_name(pending.name + ".tmp")
    try:
        backup(src, tmp)  # a clean single file, even if the chosen one still has a -wal beside it
        os.replace(tmp, pending)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return info


def _apply_pending_restore(path: Path):
    """At start-up, before the database is opened: a staged restore replaces it. The database it replaces stays as `<db>.before-restore`."""
    pending = Path(str(path) + ".restore-pending")
    if not pending.exists():
        return
    before = Path(str(path) + ".before-restore")
    if path.exists():
        try:  # fold the journal into the file first: what was written but not yet checkpointed must survive in the kept copy
            con = sqlite3.connect(path)
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except sqlite3.Error:
            pass
        for attempt in range(RESTORE_WAIT_TRIES):  # the Scrybinder that was just closed may still be shutting down and holding the file
            try:
                before.unlink(missing_ok=True)
                os.replace(path, before)
                break
            except OSError:
                if attempt == RESTORE_WAIT_TRIES - 1:  # really in use: start with the database as it is; the restore stays staged
                    logging.getLogger("scrybinder").warning("restore waiting: %s is in use (is another Scrybinder still open?)", path.name)
                    return
                time.sleep(RESTORE_WAIT_STEP)
    for suffix in ("-wal", "-shm"):  # the journal of the old database must not be replayed onto the restored one
        Path(str(path) + suffix).unlink(missing_ok=True)
    try:
        os.replace(pending, path)
    except OSError:
        if before.exists() and not path.exists():
            os.replace(before, path)  # put the old database back rather than start with none
        raise


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    default = path is None
    path = Path(path) if path else DATA_DIR / "scrybinder.db"
    if default:
        _apply_pending_restore(path)
        _adopt_legacy_db(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # a bulk update holds the writer for ~1 min: wait instead of failing. The API shares this connection between threads, so no
    # statement cache: a cached statement used by two threads at once raises "API misuse" (tests/test_threads.py)
    db = sqlite3.connect(path, check_same_thread=False, timeout=60, cached_statements=0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in db.execute("PRAGMA table_info(trade_out)")}
    if cols and "untracked" not in cols:  # ponytail: the table of a build that was never released: recreated, it holds nothing worth keeping
        db.execute("DROP TABLE trade_out")
    db.executescript(SCHEMA)
    _migrate(db)
    _seed_scryfall_prices(db)
    _fix_reversible(db)
    return db
