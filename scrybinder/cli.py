"""Command line tools: `scrybinder-index` (pilot / full visual index)."""
import argparse
import sys

from . import db as dbmod
from .scan import index
from .scan.embed import Embedder

PILOT_DISTRACTORS = 2000


def pilot_where() -> tuple[str, tuple]:
    """Collection and scan_log cards + every printing with the same name or illustration + arbitrary distractors."""
    seed = ("SELECT scryfall_id FROM collection UNION SELECT final_id FROM scan_log WHERE final_id IS NOT NULL")
    return (f"c.name IN (SELECT name FROM cards WHERE id IN ({seed}))"
            f" OR c.illustration_id IN (SELECT illustration_id FROM cards WHERE id IN ({seed}) AND illustration_id IS NOT NULL)"
            f" OR c.id IN (SELECT id FROM cards WHERE digital=0 AND lang='en' ORDER BY id LIMIT {PILOT_DISTRACTORS})", ())  # ids are UUIDs: an arbitrary sample


def index_main(argv=None):
    ap = argparse.ArgumentParser(prog="scrybinder-index")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true", help="~5k printings: your collection + reprints + distractors (minutes)")
    g.add_argument("--all", action="store_true", help="every non-digital en/pt printing (hours, several GB)")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm --all without asking")
    a = ap.parse_args(argv)
    db, emb = dbmod.connect(), Embedder()
    d = index.index_dir(emb)
    if a.status:
        print(d, index.status(d))
        return
    if a.pilot:
        w, p = pilot_where()
        print(f"+{index.add_rows(db, d, w, p)} linhas no piloto")
    else:
        n = index.add_rows(db, d, dry_run=True)  # rows are only recorded after you confirm
        print(f"{n} linhas novas; ~{n * 0.1 / 3600:.1f}+ h de descargas (<=10 pedidos/s), ~{n * 97 / 1e6:.0f} GB em data/images")
        if not a.yes and input("Continuar? [s/N] ").strip().lower() not in ("s", "sim", "y"):
            return
        index.add_rows(db, d)
    res = index.build(emb, d, progress=lambda i, t: print(f"\r{i}/{t}", end="", file=sys.stderr))
    print("\n", res)
