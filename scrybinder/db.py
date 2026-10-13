"""SQLite: connection and schema. Data lives in data/ (not in git)."""
import os
import sqlite3
import sys
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

CREATE TABLE IF NOT EXISTS sets (code TEXT PRIMARY KEY, name TEXT, icon_svg_uri TEXT, set_type TEXT, released_at TEXT);

CREATE TABLE IF NOT EXISTS set_totals (code TEXT PRIMARY KEY, name TEXT, released_at TEXT, total INTEGER, total_grouped INTEGER);

CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    capture_path TEXT, ocr_json TEXT, predicted_id TEXT, final_id TEXT REFERENCES cards(id),
    corrected INTEGER NOT NULL DEFAULT 0, location TEXT NOT NULL DEFAULT ''
);  -- capture → correct printing pairs: training/evaluation data for the matcher

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS card_faces (  -- one row per face that has its own image (visual index)
    card_id TEXT NOT NULL REFERENCES cards(id), face INTEGER NOT NULL, illustration_id TEXT, image_normal TEXT,
    PRIMARY KEY (card_id, face)
);
CREATE INDEX IF NOT EXISTS card_faces_ill ON card_faces(illustration_id);

CREATE TABLE IF NOT EXISTS oracle_cards (  -- one row per oracle_id: the rules data decks need (the latest printing wins)
    oracle_id TEXT PRIMARY KEY, name TEXT NOT NULL, mana_cost TEXT, cmc REAL, type_line TEXT,
    colors TEXT, color_identity TEXT, oracle_text TEXT, keywords TEXT, produced_mana TEXT,
    legalities TEXT, game_changer INTEGER NOT NULL DEFAULT 0, edhrec_rank INTEGER, layout TEXT, released_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS oracle_fts USING fts5(
    name, oracle_text, content='oracle_cards', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');

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
    quantity INTEGER NOT NULL CHECK (quantity > 0), board TEXT NOT NULL DEFAULT 'main' CHECK (board IN ('main','side','commander','maybe'))
);
CREATE UNIQUE INDEX IF NOT EXISTS deck_cards_key ON deck_cards(deck_id, oracle_id, COALESCE(scryfall_id, ''), board);
CREATE TABLE IF NOT EXISTS deck_card_tags (
    deck_card_id INTEGER NOT NULL REFERENCES deck_cards(id) ON DELETE CASCADE, tag TEXT NOT NULL, PRIMARY KEY (deck_card_id, tag)
);
CREATE TABLE IF NOT EXISTS deck_assignments (  -- copies of a collection row reserved for a deck card
    deck_card_id INTEGER NOT NULL REFERENCES deck_cards(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (deck_card_id, collection_id)
);
CREATE INDEX IF NOT EXISTS deck_assignments_coll ON deck_assignments(collection_id);
"""

# additive migrations (never delete or rewrite data): (table, column, definition)
_ADD = [("decks", "folder_id", "INTEGER REFERENCES deck_folders(id) ON DELETE SET NULL"), ("cards", "illustration_id", "TEXT"), ("cards", "image_status", "TEXT"), ("scan_log", "topk_json", "TEXT")]


def _migrate(db):
    for table, col, ddl in _ADD:
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    db.execute("CREATE INDEX IF NOT EXISTS cards_ill ON cards(illustration_id)")


def _adopt_legacy_db(path: Path):
    """The project used to be called Cardex: keep an existing collection by renaming its database files."""
    old = path.with_name("cardex.db")
    if not path.exists() and old.exists():
        for suffix in ("", "-wal", "-shm"):
            if Path(str(old) + suffix).exists():
                Path(str(old) + suffix).rename(Path(str(path) + suffix))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    default = path is None
    path = Path(path) if path else DATA_DIR / "scrybinder.db"
    if default:
        _adopt_legacy_db(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # a bulk update holds the writer for ~1 min: wait instead of failing. The API shares this connection between threads, so no
    # statement cache: a cached statement used by two threads at once raises "API misuse" (tests/test_threads.py)
    db = sqlite3.connect(path, check_same_thread=False, timeout=60, cached_statements=0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    _migrate(db)
    return db
