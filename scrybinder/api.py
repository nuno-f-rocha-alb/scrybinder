"""Local FastAPI backend. Bound to 127.0.0.1 only; SameSite=Strict session cookie + Host header check."""
import importlib.util
import os
import secrets
import sqlite3
import threading
import webbrowser
from urllib.parse import urlparse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import time

from . import __version__, collection, db as dbmod, decks, decktext, formats, gpu as gpumod, scryfall, updater as updmod
from .scan.session import MAX_SIDE, MAX_SIDE_PAGE, Scanner, decode

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
COOKIE = "scrybinder_session"
CRLF = b"\r\n"


def create_app(db=None, token: str | None = None, allowed_hosts: set[str] | None = None, auto_bulk: bool = False) -> FastAPI:
    db = db or dbmod.connect()
    token = token or os.environ.get("SCRYBINDER_TOKEN") or secrets.token_urlsafe(24)
    app = FastAPI(title="Scrybinder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.allowed_hosts = allowed_hosts if allowed_hosts is not None else set()
    job = {"state": "idle", "done": 0, "total": 0, "error": None, "cards": 0}
    sets_tried = []  # list used as a mutable flag: one /sets attempt per start-up

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost"} | app.state.allowed_hosts:  # anti DNS-rebinding
            return JSONResponse({"detail": "invalid host"}, status_code=403)
        if request.url.path.startswith("/api"):
            if request.query_params.get("t") == token:
                pass
            elif request.cookies.get(COOKIE) != token:
                return JSONResponse({"detail": "no session"}, status_code=401)
            elif request.method != "GET" and request.headers.get("sec-fetch-site", "same-origin") not in (
                    "same-origin", "none"):  # CSRF extra em escritas
                return JSONResponse({"detail": "invalid origin"}, status_code=403)
        resp = await call_next(request)
        if request.query_params.get("t") == token:
            resp.set_cookie(COOKIE, token, httponly=True, samesite="strict")
        return resp

    _ix_cache: dict = {"t": 0.0, "v": None}

    def _index_status():
        """Visual index: faces indexed / eligible. Does not import torch. Cached for 15 s because /api/status is polled."""
        from .scan import index as ixmod
        from .scan.embed import Embedder
        if _ix_cache["v"] is not None and time.monotonic() - _ix_cache["t"] < 15:
            return _ix_cache["v"]
        st = ixmod.status(ixmod.index_dir(Embedder()))
        st["eligible"] = db.execute("SELECT COUNT(*) FROM card_faces f JOIN cards c ON c.id=f.card_id WHERE " + ixmod.SCOPE
                                    + " AND f.image_normal IS NOT NULL").fetchone()[0]
        _ix_cache.update(t=time.monotonic(), v=st)
        return st

    # --- estado / bulk ---
    @app.get("/api/status")
    def status():
        n = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        age = scryfall.bulk_age_days(db)
        return {"cards_in_db": n, "oracle_cards": db.execute("SELECT COUNT(*) FROM oracle_cards").fetchone()[0], "bulk_age_days": age,
                "bulk_stale": age is None or age > scryfall.BULK_STALE_DAYS, "job": job, "index": _index_status(), "index_job": ixjob,
                "credit": "Card data and images © Scryfall — scryfall.com", "version": __version__,
                "update_available": (updstate["plan"] or {}).get("latest") if not (updstate["plan"] or {}).get("up_to_date", True) else None}

    def _run_bulk():
        try:
            job.update(state="download", done=0, total=0, error=None)
            path = scryfall.download_bulk(progress=lambda d, t: job.update(done=d, total=t))
            job.update(state="import", done=0, total=0)
            conn = dbmod.connect(db.execute("PRAGMA database_list").fetchone()[2])  # own connection for this thread
            job["cards"] = scryfall.import_bulk(conn, path, progress=lambda n: job.update(done=n))
            conn.close()
            try:
                scryfall.fetch_sets(db)
            except Exception:  # set icons are optional
                pass
            job["state"] = "done"
        except Exception as e:  # ponytail: mostra o erro na UI em vez de o perder na thread
            job.update(state="error", error=str(e))

    @app.post("/api/bulk/update")
    def bulk_update():
        if job["state"] in ("download", "import"):
            raise HTTPException(409, "an update is already running")
        threading.Thread(target=_run_bulk, daemon=True).start()
        return {"started": True}

    # --- visual index: build from Settings (same work as `scrybinder-index`) ---
    ixjob = {"state": "idle", "mode": None, "done": 0, "total": 0, "error": None, "failed": 0, "detail": ""}
    ix_stop = threading.Event()
    ix_lock = threading.Lock()  # check-and-set of the state: a double click must not start two builds on the same shards

    def _run_index(mode: str):
        from .cli import pilot_where
        from .scan import index as ixmod
        from .scan.embed import Embedder
        conn = None
        try:
            ixjob.update(state="prepare", mode=mode, done=0, total=0, error=None, failed=0)
            conn = dbmod.connect(db.execute("PRAGMA database_list").fetchone()[2])  # own connection for this thread
            emb = Embedder()
            d = ixmod.index_dir(emb)
            ixmod.add_rows(conn, d, *(pilot_where() if mode == "pilot" else ("1", ())))
            ixjob["state"] = "build"
            res = ixmod.build(emb, d, progress=lambda i, t: ixjob.update(done=i, total=t), should_stop=ix_stop.is_set,
                              detail=lambda text: ixjob.update(detail=text))
            ixjob.update(state="stopped" if res.get("stopped") else "done", failed=res["failed_downloads"])
            if res["indexed"]:
                scanner.ident.reset_vis()
        except Exception as e:  # ponytail: show the error in the UI instead of losing it in the thread
            ixjob.update(state="error", error=str(e))
        finally:
            if conn:
                conn.close()
            _ix_cache["v"] = None

    @app.get("/api/index/estimate")
    def index_estimate():
        from .scan import index as ixmod
        from .scan.embed import Embedder
        n = ixmod.add_rows(db, ixmod.index_dir(Embedder()), dry_run=True)
        return {"printings": n, "hours": round(n * 0.1 / 3600, 1), "gb": round(n * 97 / 1e6)}

    @app.post("/api/index/build")
    def index_build(body: dict = Body(...)):
        mode = body.get("mode")
        if mode not in ("pilot", "all"):
            raise HTTPException(422, "mode must be 'pilot' or 'all'")
        if importlib.util.find_spec("torch") is None:
            raise HTTPException(400, "PyTorch is not installed: run `uv sync --extra vision` (the released builds include it)")
        if db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0:
            raise HTTPException(400, "update the card database first")
        with ix_lock:
            if ixjob["state"] in ("prepare", "build"):
                raise HTTPException(409, "the index is already being built")
            ix_stop.clear()
            ixjob["state"] = "prepare"
        threading.Thread(target=_run_index, args=(mode,), daemon=True).start()
        return {"started": True}

    @app.post("/api/index/stop")
    def index_stop():
        ix_stop.set()
        return {"stopping": ixjob["state"] in ("prepare", "build")}

    # --- GPU acceleration for installed builds: download the CUDA build of PyTorch (see gpu.py) ---
    gpujob = {"state": "idle", "done": 0, "total": 0, "error": None}
    gpu_lock = threading.Lock()

    @app.get("/api/gpu")
    def gpu_status():
        return gpumod.status(gpujob)

    @app.post("/api/gpu/install")
    def gpu_install():
        if not gpumod.supported():
            raise HTTPException(400, "GPU acceleration can be added to the installed app on Windows only (from source: uv sync --extra vision-cuda)")
        wheel = gpumod.choose_wheel(gpumod.driver_cuda_version())
        if wheel is None:
            raise HTTPException(400, "no NVIDIA GPU with a driver that supports CUDA 12.8 or newer was found")
        if gpumod.installed() is not None or gpumod.ACTIVE or (gpumod.gpu_dir() / "remove-on-start").exists():
            raise HTTPException(409, "already installed: remove it first (then restart) to install it again")
        with gpu_lock:
            if gpujob["state"] in ("download", "extract", "test"):
                raise HTTPException(409, "it is already being installed")
            gpujob.update(state="download", done=0, total=wheel["size"], error=None)
        threading.Thread(target=gpumod.install, args=(gpujob, wheel), daemon=True).start()
        return {"started": True}

    @app.post("/api/gpu/remove")
    def gpu_remove():
        if gpujob["state"] in ("download", "extract", "test"):
            raise HTTPException(409, "wait for the download to finish")
        gpujob.update(state="idle", error=None)
        return {"restart_needed": gpumod.remove()}

    # --- in-app updater for installed builds: find, download, verify and apply the update packages (see updater.py) ---
    updjob = {"state": "idle", "done": 0, "total": 0, "step": 0, "steps": 0, "applied": None, "error": None}
    updstate = {"plan": None, "error": None, "checking": False}
    upd_lock = threading.Lock()

    def _on_start() -> bool:
        r = db.execute("SELECT value FROM meta WHERE key='update_check_on_start'").fetchone()
        return bool(r and r[0] == "1")

    def _run_check():
        try:
            updstate.update(plan=updmod.check(), error=None)
        except Exception as e:  # noqa: BLE001 — GitHub unreachable, rate limit...: shown in Settings
            updstate["error"] = str(e) or e.__class__.__name__
        finally:
            updstate["checking"] = False

    @app.get("/api/update")
    def update_status():
        return {"supported": updmod.supported(), "version": __version__, **updstate, "job": updjob, "check_on_start": _on_start()}

    @app.post("/api/update/check")
    def update_check():
        if not updmod.supported():
            raise HTTPException(400, "the updater is for the installed Windows app (from source: git pull)")
        with upd_lock:
            if updstate["checking"] or updjob["state"] in ("download", "verify", "apply"):
                raise HTTPException(409, "already running")
            updstate["checking"] = True
        _run_check()
        if updstate["error"]:
            raise HTTPException(502, "could not reach GitHub: " + updstate["error"])
        return updstate["plan"]

    @app.post("/api/update/install")
    def update_install():
        pl = updstate["plan"]
        if not updmod.supported() or not pl or not pl["chain"]:
            raise HTTPException(400, "nothing to install: check for updates first")
        if not os.access(updmod.app_dir(), os.W_OK):
            raise HTTPException(400, f"{updmod.app_dir()} is not writable: use the installer, or move the app to a folder you own")
        with upd_lock:
            if updjob["state"] in ("download", "verify", "apply", "done"):
                raise HTTPException(409, "already running, or done: restart Scrybinder")
            updjob.update(state="download", done=0, total=0, error=None)
        threading.Thread(target=updmod.install, args=(updjob, pl), daemon=True).start()
        return {"started": True}

    @app.post("/api/update/restart")
    def update_restart():
        if updjob["state"] != "done":
            raise HTTPException(409, "there is nothing to restart for")
        updmod.restart()
        return {"restarting": True}

    @app.post("/api/update/settings")
    def update_settings(body: dict = Body(...)):
        with db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('update_check_on_start', ?)", ("1" if body.get("check_on_start") else "0",))
        return {"check_on_start": _on_start()}

    if updmod.supported() and _on_start():
        updstate["checking"] = True
        threading.Thread(target=_run_check, daemon=True).start()

    age = scryfall.bulk_age_days(db)
    if auto_bulk and age is not None and age > scryfall.AUTO_BULK_DAYS:  # daily prices: refresh on start-up when older than 24 h
        threading.Thread(target=_run_bulk, daemon=True).start()  # first run (no bulk yet) stays manual: it is ~80 MB

    def _backfill_oracle():  # databases from before decks: fill oracle_cards from the cached bulk file (no download)
        files = [f for f in (dbmod.DATA_DIR / "bulk").glob("default-cards.json*") if f.suffix != ".part"]
        if files and db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] and not db.execute("SELECT 1 FROM oracle_cards").fetchone():
            def run():
                conn = dbmod.connect(db.execute("PRAGMA database_list").fetchone()[2])
                try:
                    scryfall.backfill_oracle(conn, max(files, key=lambda f: f.stat().st_mtime))
                except Exception:  # ponytail: the Decks page falls back to "Update bulk data"
                    pass
                finally:
                    conn.close()
            threading.Thread(target=run, daemon=True).start()

    if auto_bulk and not (age is not None and age > scryfall.AUTO_BULK_DAYS):  # a refresh above fills oracle_cards itself
        _backfill_oracle()  # real app only: tests must not read the user's bulk file

    # --- cartas ---
    @app.get("/api/cards/search")
    def card_search(q: str = "", limit: int = 20):
        if not collection._fts(q):
            return []
        rows = db.execute(
            "SELECT k.oracle_id, k.name, COUNT(*) AS prints, MIN(k.id) AS sample_id FROM cards k WHERE k.rowid IN "
            "(SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?) AND k.digital=0 "
            "GROUP BY COALESCE(k.oracle_id,k.id) ORDER BY k.name LIMIT ?", (collection._fts(q), min(limit, 50)))
        return [dict(r) for r in rows]

    @app.get("/api/cards/prints")
    def prints(oracle_id: str = "", name: str = ""):
        where, arg = ("oracle_id=?", oracle_id) if oracle_id else ("UPPER(name)=UPPER(?)", name)  # uses the cards_name_upper index
        rows = db.execute(f"SELECT id, name, set_code, set_name, collector_number, released_at, rarity, finishes,"
                          f" frame, full_art, border_color, promo_types, eur, eur_foil, eur_etched, lang, cardmarket_id FROM cards"
                          f" WHERE {where} AND digital=0 ORDER BY released_at DESC", (arg,))
        return [dict(r) for r in rows]

    @app.get("/api/image/{card_id}")
    def image(card_id: str, size: str = "normal"):
        p = scryfall.image_path(db, card_id, size)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=31536000, immutable"})

    @app.post("/api/open-url")
    def open_url(body: dict = Body(...)):
        """Open a link in the system browser (the app window must not navigate away). Scryfall and Cardmarket only."""
        u = urlparse(str(body.get("url", "")))
        if u.scheme != "https" or u.hostname not in ("scryfall.com", "www.cardmarket.com"):
            raise HTTPException(422, "link not allowed")
        webbrowser.open(u.geturl())
        return {"ok": True}

    # --- scan ---
    scanner = Scanner(db)
    app.state.scanner = scanner
    MAX_UPLOAD = 25 * 1024 * 1024

    @app.get("/api/scan/state")
    def scan_state():
        return scanner.state()

    async def _upload_image(request: Request, max_side: int):
        if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
            raise HTTPException(413, "file larger than 25 MB")
        data = await request.body()
        if not data or len(data) > MAX_UPLOAD:
            raise HTTPException(413 if data else 400, "file empty or larger than 25 MB")
        img = await run_in_threadpool(decode, data, max_side)
        if img is None:
            raise HTTPException(415, "not a valid image")
        return img

    @app.post("/api/scan/photo")
    async def scan_photo(request: Request, name: str = ""):
        return await run_in_threadpool(scanner.process, await _upload_image(request, MAX_SIDE), name[:80])

    @app.post("/api/scan/page")
    async def scan_page(request: Request, name: str = ""):
        return await run_in_threadpool(scanner.process_page, await _upload_image(request, MAX_SIDE_PAGE), name[:80])

    @app.post("/api/scan/mode")
    def scan_mode(body: dict = Body(...)):
        if "list" in body:
            scanner.list_mode = bool(body["list"])
        if "page" in body:
            scanner.page_mode = bool(body["page"])
        return {"list_mode": scanner.list_mode, "page_mode": scanner.page_mode}

    @app.get("/api/scan/reads/{rid}/candidates")
    def read_candidates(rid: int):
        r = next((x for x in scanner.reads if x["id"] == rid), None)
        if r is None:
            raise HTTPException(404)
        return r["candidates"]

    @app.patch("/api/scan/reads/{rid}")
    def read_edit(rid: int, body: dict = Body(...)):
        return _wrap(scanner.read_edit, rid, **body)

    @app.delete("/api/scan/reads/{rid}")
    def read_delete(rid: int):
        scanner.read_delete(rid)
        return {"ok": True}

    @app.post("/api/scan/reads/commit")
    def read_commit(body: dict = Body(...)):
        return scanner.commit_reads(str(body.get("location", "")).strip())

    @app.post("/api/scan/split-next")
    def scan_split_next(body: dict = Body(...)):
        scanner.split_next = bool(body.get("on"))
        return {"split_next": scanner.split_next}

    @app.post("/api/scan/start")
    def scan_start(body: dict = Body(...)):
        try:
            scanner.start(str(body.get("kind", "")), str(body.get("target", "0")))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @app.post("/api/scan/stop")
    def scan_stop():
        scanner.stop()
        return {"ok": True}

    @app.get("/api/scan/preview")
    def scan_preview():
        def gen():
            while scanner.state()["running"]:
                jpg = scanner.preview_jpeg()
                if jpg:
                    yield b"--f" + CRLF + b"Content-Type: image/jpeg" + CRLF + CRLF + jpg + CRLF
                time.sleep(0.1)
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=f")

    @app.get("/api/scan/capture/{pid}")
    def scan_capture(pid: int):
        p = scanner.dir / f"{pid}.jpg"
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-store"})

    @app.post("/api/scan/{pid}/confirm")
    def scan_confirm(pid: int, body: dict = Body(...)):
        f = {k: body[k] for k in ("finish", "quantity", "condition", "language") if k in body}
        return {"id": _wrap(scanner.confirm, pid, body.get("scryfall_id", ""), body.get("location", ""), **f)}

    @app.post("/api/scan/{pid}/discard")
    def scan_discard(pid: int):
        _wrap(scanner.discard, pid)
        return {"ok": True}

    # --- sets ---
    @app.get("/api/sets")
    def sets(location: str | None = None, q: str = "", hide_empty: bool = True, group: bool = False):
        if not sets_tried and db.execute("SELECT 1 FROM sets LIMIT 1").fetchone() is None:
            sets_tried.append(1)  # being offline must not block every page load
            try:
                scryfall.fetch_sets(db)
            except Exception:  # the view works without icons
                pass
        return collection.set_progress(db, location, q, hide_empty, group)

    @app.get("/api/seticon/{code}")
    def seticon(code: str):
        p = scryfall.icon_path(db, code)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, media_type="image/svg+xml", headers={
            "Cache-Control": "max-age=31536000, immutable",
            "Content-Security-Policy": "sandbox; default-src 'none'"})  # remote SVG never runs scripts in our origin

    # --- collection ---
    @app.get("/api/collection")
    def coll(q: str = "", set: str = "", location: str | None = None, finish: str = "", language: str = "",
             sort: str = "name", limit: int = 100, offset: int = 0):
        return collection.search(db, q, set, location, finish, language, sort, min(limit, 500), offset)

    @app.get("/api/locations")
    def locs():
        return collection.locations(db)

    def _wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError:
            raise HTTPException(404)
        except decks.Conflict as e:  # copies assigned to decks: the detail lists them so the UI can offer to release
            raise HTTPException(409, {"message": str(e), "decks": e.decks})
        except (ValueError, sqlite3.IntegrityError) as e:  # invalid input; other errors are bugs and should be 500
            raise HTTPException(422, str(e))

    # --- decks ---
    @app.get("/api/decks")
    def decks_list():
        return decks.listing(db)

    @app.post("/api/decks")
    def decks_create(body: dict = Body(...)):
        return {"id": _wrap(decks.create, db, body.get("name"), body.get("format") or "casual", body.get("description") or "")}

    @app.get("/api/decks/{deck_id}")
    def decks_get(deck_id: int):
        return _wrap(decks.get, db, deck_id)

    @app.patch("/api/decks/{deck_id}")
    def decks_update(deck_id: int, body: dict = Body(...)):
        _wrap(decks.update, db, deck_id, **body)
        return {"ok": True}

    @app.delete("/api/decks/{deck_id}")
    def decks_delete(deck_id: int):
        _wrap(decks.delete, db, deck_id)
        return {"ok": True}

    @app.get("/api/decks/{deck_id}/legality")
    def decks_legality(deck_id: int, reference: str | None = None):
        return _wrap(decks.legality, db, deck_id, reference)

    @app.get("/api/decks/{deck_id}/stats")
    def decks_stats(deck_id: int):
        return _wrap(decks.stats, db, deck_id)

    @app.post("/api/decks/{deck_id}/import")
    def decks_import(deck_id: int, body: dict = Body(...)):
        text = body.get("text")
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise HTTPException(422, "text: a deck list of up to 1 MB")
        return _wrap(decktext.import_text, db, deck_id, text, bool(body.get("dry_run")))

    @app.get("/api/decks/{deck_id}/export")
    def decks_export(deck_id: int, maybe: bool = False):
        text = _wrap(decktext.export_text, db, deck_id, maybe)
        return Response(text, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="scrybinder-deck-{deck_id}.txt"'})

    @app.post("/api/decks/{deck_id}/duplicate")
    def decks_duplicate(deck_id: int):
        return {"id": _wrap(decks.duplicate, db, deck_id)}

    @app.post("/api/decks/{deck_id}/cards")
    def decks_add_card(deck_id: int, body: dict = Body(...)):
        return {"id": _wrap(decks.add_card, db, deck_id, body.get("oracle_id"), body.get("quantity", 1),
                            body.get("board", "main"), body.get("scryfall_id"), body.get("tags") or ())}

    @app.patch("/api/decks/{deck_id}/cards/{card_id}")
    def decks_update_card(deck_id: int, card_id: int, body: dict = Body(...)):
        return {"id": _wrap(decks.update_card, db, deck_id, card_id,
                            **{k: v for k, v in body.items() if k in ("quantity", "board", "scryfall_id", "tags")})}

    @app.delete("/api/decks/{deck_id}/cards/{card_id}")
    def decks_remove_card(deck_id: int, card_id: int):
        _wrap(decks.remove_card, db, deck_id, card_id)
        return {"ok": True}

    @app.put("/api/decks/{deck_id}/cards/{card_id}/assign")
    def decks_assign(deck_id: int, card_id: int, body: dict = Body(...)):
        _wrap(decks.assign, db, deck_id, card_id, body.get("items"))
        return {"ok": True}

    @app.post("/api/decks/{deck_id}/assign-free")
    def decks_assign_free(deck_id: int):
        return {"assigned": _wrap(decks.assign_free, db, deck_id)}

    @app.post("/api/collection")
    def coll_add(body: dict = Body(...)):
        return {"id": _wrap(collection.add, db, **{k: v for k, v in body.items() if k in collection.EDITABLE
                                                   or k == "scryfall_id"})}

    @app.patch("/api/collection/{row_id}")
    def coll_edit(row_id: int, release: bool = False, body: dict = Body(...)):
        return {"id": _wrap(collection.update, db, row_id, release=release, **body)}

    @app.delete("/api/collection/{row_id}")
    def coll_del(row_id: int, release: bool = False):
        _wrap(collection.delete, db, row_id, release)
        return {"ok": True}

    @app.get("/api/collection/ids")
    def coll_ids(q: str = "", set: str = "", location: str | None = None, finish: str = "", language: str = ""):
        return {"ids": collection.matching_ids(db, q, set, location, finish, language)}

    @app.post("/api/collection/bulk")
    def coll_bulk(release: bool = False, body: dict = Body(...)):
        ids = body.get("ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 20000 or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise HTTPException(422, "ids: lista de 1 a 20000 inteiros")
        action = body.get("action")
        if action == "delete":
            return {"deleted": _wrap(collection.bulk_delete, db, ids, dbmod.DATA_DIR / "trash", release)}
        if action == "update":
            fields = body.get("fields")
            if not isinstance(fields, dict):
                raise HTTPException(422, "fields: objeto")
            return _wrap(collection.bulk_update, db, ids, **fields)
        raise HTTPException(422, "action: delete ou update")

    @app.post("/api/collection/{row_id}/move")
    def coll_move(row_id: int, release: bool = False, body: dict = Body(...)):
        return {"id": _wrap(collection.move, db, row_id, body.get("location", ""), body.get("quantity"), release)}

    # --- import / export ---
    @app.post("/api/import/{fmt}")
    async def imp(fmt: str, request: Request, location: str = ""):
        if fmt not in formats.IMPORTERS:
            raise HTTPException(404)
        text = (await request.body()).decode("utf-8-sig", errors="replace")
        return _wrap(formats.IMPORTERS[fmt], db, text, location)

    @app.get("/api/export/{fmt}")
    def exp(fmt: str, location: str | None = None):
        if fmt not in formats.EXPORTERS:
            raise HTTPException(404)
        return Response(formats.EXPORTERS[fmt](db, location), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="scrybinder-{fmt}.csv"'})

    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
