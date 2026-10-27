"""Local FastAPI backend. Bound to 127.0.0.1 only; SameSite=Strict session cookie + Host header check."""
import importlib.util
import logging
import os
import secrets
import sqlite3
import threading
import webbrowser
from urllib.parse import urlparse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import time

from . import __version__, carddetails, collection, db as dbmod, decks, decktext, deckurl, formats, gpu as gpumod, lists, oracle, playmats, scryfall, share, suggest, trades, updater as updmod
from .scan.session import MAX_SIDE, MAX_SIDE_PAGE, Scanner, decode

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
COOKIE = "scrybinder_session"


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
                                    + " AND f.image_normal IS NOT NULL AND COALESCE(c.image_status,'') NOT IN (?,?)",  # the ones add_rows can index
                                    ixmod.SKIP_STATUS).fetchone()[0]
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
                "restore_pending": Path(str(_db_path()) + ".restore-pending").exists(),
                "update_available": (updstate["plan"] or {}).get("latest") if not (updstate["plan"] or {}).get("up_to_date", True) else None}

    def _rm_db(path):  # a temporary database and the -wal/-shm files that checking it may leave
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

    def _db_path() -> Path:
        return Path(db.execute("PRAGMA database_list").fetchone()[2])

    def _run_bulk():
        try:
            job.update(state="download", done=0, total=0, error=None)
            path = scryfall.download_bulk(progress=lambda d, t: job.update(done=d, total=t))
            job.update(state="import", done=0, total=0)
            conn = dbmod.connect(db.execute("PRAGMA database_list").fetchone()[2])  # own connection for this thread
            job["cards"] = scryfall.import_bulk(conn, path, progress=lambda n: job.update(done=n))
            try:
                collection.record_snapshot(conn)  # prices just changed: note the collection's value for the history
            except Exception:  # the history is optional: it must not fail the update
                logging.getLogger("scrybinder").exception("could not record the value snapshot")
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
        ilog = logging.getLogger("scrybinder.index")
        try:
            ilog.info("Visual index build started (%s)", mode)
            ixjob.update(state="prepare", mode=mode, done=0, total=0, error=None, failed=0)
            conn = dbmod.connect(db.execute("PRAGMA database_list").fetchone()[2])  # own connection for this thread
            emb = Embedder()
            d = ixmod.index_dir(emb)
            ixmod.add_rows(conn, d, *(pilot_where() if mode == "pilot" else ("1", ())))
            ixjob["state"] = "build"
            res = ixmod.build(emb, d, progress=lambda i, t: ixjob.update(done=i, total=t), should_stop=ix_stop.is_set,
                              detail=lambda text: ixjob.update(detail=text))
            ixjob.update(state="stopped" if res.get("stopped") else "done", failed=res["failed_downloads"])
            ilog.info("Visual index build %s: %s faces indexed of %s, %s downloads failed", "stopped" if res.get("stopped") else "finished",
                      res.get("indexed"), res.get("rows"), res["failed_downloads"])
            if res["indexed"]:
                scanner.ident.reset_vis()
        except Exception as e:  # ponytail: show the error in the UI instead of losing it in the thread
            ilog.exception("Visual index build failed")
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
            "SELECT k.oracle_id, k.name, COUNT(*) AS prints, k.id AS sample_id, MAX(CASE WHEN k.image_normal IS NOT NULL THEN COALESCE(k.released_at, '0') ELSE '' END) FROM cards k WHERE k.rowid IN "
            "(SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?) AND k.digital=0 "
            "GROUP BY COALESCE(k.oracle_id,k.id) ORDER BY k.name LIMIT ?", (collection._fts(q), min(limit, 50)))
        return [dict(r) for r in rows]

    @app.get("/api/oracle/search")
    def oracle_search(q: str = "", text: str = "", colors: str = "", type: str = "", cmc_min: str = "", cmc_max: str = "",
                      owned: bool = False, legal: bool = False, deck: int | None = None, sort: str = "name",
                      limit: int = 50, offset: int = 0):
        return _wrap(oracle.search, db, q, text, colors, type, cmc_min, cmc_max, owned, legal, deck, sort, limit, offset)

    @app.post("/api/ui-log")
    def ui_log(body: dict = Body(...)):
        """The interface leaves a short note in app.log (what happened when a menu closed by itself): a few fields of text and numbers."""
        note = {str(k)[:20]: (v if isinstance(v, (int, float, bool)) else str(v)[:80]) for k, v in list(body.items())[:14]}
        logging.getLogger("scrybinder.ui").info("%s", note)
        return {"ok": True}

    @app.get("/api/cards/{card_id}/details")
    def card_details(card_id: str):
        return _wrap(carddetails.details, db, card_id)

    @app.get("/api/cards/{card_id}/rulings")
    def card_rulings(card_id: str):
        try:
            return _wrap(carddetails.rulings, db, card_id)
        except HTTPException:
            raise
        except Exception:  # Scryfall could not be reached and there is no copy of the rulings yet
            raise HTTPException(502, "The rulings could not be loaded (is there a connection to Scryfall?)")

    @app.get("/api/cards/prints")
    def prints(oracle_id: str = "", name: str = "", deck: int | None = None):
        where, arg = ("oracle_id=?", oracle_id) if oracle_id else ("UPPER(name)=UPPER(?)", name)  # uses the cards_name_upper index
        rows = db.execute(f"SELECT id, oracle_id, name, set_code, set_name, collector_number, released_at, rarity, finishes,"
                          f" frame, full_art, border_color, promo_types, eur, eur_foil, eur_etched, lang, cardmarket_id,"
                          f" (SELECT COALESCE(SUM(quantity), 0) FROM collection WHERE scryfall_id=cards.id AND proxy=0) AS owned,"
                          f" (SELECT COALESCE(SUM(c.quantity), 0) - COALESCE(SUM((SELECT SUM(a.quantity) FROM deck_assignments a"
                          f" JOIN deck_cards dc ON dc.id=a.deck_card_id WHERE a.collection_id=c.id AND dc.deck_id IS NOT ?)), 0)"
                          f" FROM collection c WHERE c.scryfall_id=cards.id AND c.proxy=0) AS free FROM cards"  # free: not held by another deck
                          f" WHERE {where} AND digital=0 ORDER BY released_at DESC", (deck, arg))
        out = [dict(r) for r in rows]
        owned = {}  # per printing and finish, so the list can say "1 non-foil"
        for sid, fin, q in db.execute("SELECT scryfall_id, finish, SUM(quantity) FROM collection WHERE proxy=0 AND scryfall_id IN"
                                      f" ({','.join('?' * len(out)) or 'NULL'}) GROUP BY scryfall_id, finish", [r["id"] for r in out]):
            owned.setdefault(sid, {})[fin] = q
        for r in out:
            r["owned_finish"] = owned.get(r["id"], {})
        return out

    @app.get("/api/image/{card_id}")
    def image(card_id: str, size: str = "normal"):
        p = scryfall.image_path(db, card_id, size)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=31536000, immutable"})

    # --- playmats ---
    @app.get("/api/playmat")
    def playmat_get():
        return {"folder": str(playmats.folder()), "files": playmats.files(), "current": playmats.get(db)}

    @app.put("/api/playmat")
    def playmat_put(body: dict = Body(...)):
        return _wrap(playmats.put, db, body)

    @app.get("/api/playmat/file/{name}")
    def playmat_file(name: str, thumb: bool = False):
        p = playmats.thumb_path(name) if thumb else playmats.file_path(name)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-cache", "Content-Disposition": "inline"})

    @app.get("/api/playmat/art/{card_id}")
    def playmat_art(card_id: str):
        p = playmats.art_path(db, card_id)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=31536000, immutable"})

    @app.post("/api/playmat/open-folder")
    def playmat_open():
        return {"folder": _wrap(playmats.open_folder)}

    def _viewer_hosts():  # the share viewer, so a link just made can be opened
        hosts = [urlparse(u).hostname for u in (share._viewer(), os.environ.get("SCRYBINDER_SHARE_API") or share.SHARE_API)]
        return tuple(h for h in hosts if h)

    @app.post("/api/open-url")
    def open_url(body: dict = Body(...)):
        """Open a link in the system browser (the app window must not navigate away). Scryfall, Cardmarket and EDHREC (its credit link) only."""
        u = urlparse(str(body.get("url", "")))
        if u.scheme != "https" or u.hostname not in ("scryfall.com", "www.cardmarket.com", "edhrec.com") + _viewer_hosts():
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

    @app.post("/api/scan/overlap")
    async def scan_overlap(request: Request, name: str = ""):
        return await run_in_threadpool(scanner.process_overlap, await _upload_image(request, MAX_SIDE_PAGE), name[:80])

    @app.post("/api/scan/auto")
    async def scan_auto(request: Request, name: str = ""):
        return await run_in_threadpool(scanner.process_auto, await _upload_image(request, MAX_SIDE_PAGE), name[:80])

    @app.post("/api/scan/mode")
    def scan_mode(body: dict = Body(...)):
        if "list" in body:
            scanner.list_mode = bool(body["list"])
        if "page" in body:
            scanner.page_mode = bool(body["page"])
        if "overlap" in body:
            scanner.overlap_mode = bool(body["overlap"])
        if "auto" in body:
            scanner.auto_mode = bool(body["auto"])
        return {"list_mode": scanner.list_mode, "page_mode": scanner.page_mode, "overlap_mode": scanner.overlap_mode, "auto_mode": scanner.auto_mode}

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

    @app.post("/api/scan/debug-frame")
    def scan_debug_frame():
        """Save the camera's current whole frame with the outline the app found (for reports about cards that are not detected)."""
        path = scanner.save_debug("manual")
        if path is None:
            raise HTTPException(409, "start the camera first: there is no frame yet")
        return {"path": str(path), "folder": str(path.parent)}

    @app.get("/api/scan/frame")
    def scan_frame():
        """The latest camera frame as one JPEG. The page asks for it a few times a second: a continuous multipart stream in an
        <img> crashed the page of the packaged app (WebView2, STATUS_BREAKPOINT) when the camera was stopped."""
        jpg = scanner.preview_jpeg()
        if not jpg:
            raise HTTPException(404)
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

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
    def sets(location: list[str] | None = Query(None), q: str = "", hide_empty: bool = True, group: bool = False):
        if not sets_tried and db.execute("SELECT 1 FROM sets LIMIT 1").fetchone() is None:
            sets_tried.append(1)  # being offline must not block every page load
            try:
                scryfall.fetch_sets(db)
            except Exception:  # the view works without icons
                pass
        return collection.set_progress(db, location, q, hide_empty, group)

    @app.get("/api/sets/{code}/missing")
    def set_missing(code: str, group: bool = False, location: list[str] | None = Query(None), format: str = "json"):
        sm = _wrap(collection.set_missing, db, code, group, location)
        if format == "text":
            return Response(collection.set_missing_text(sm), media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="scrybinder-missing-{sm["set_code"]}.txt"'})
        if format == "csv":
            return Response(collection.set_missing_csv(sm), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="scrybinder-missing-{sm["set_code"]}.csv"'})
        return sm

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
    def coll(q: str = "", set: str = "", location: list[str] | None = Query(None), finish: str = "", language: str = "",
             sort: str = "name", limit: int = 100, offset: int = 0, group: str = "location"):
        return collection.search(db, q, set, location, finish, language, sort, min(limit, 100000), offset, group)

    @app.get("/api/collection/spare")
    def collection_spare(format: str = "json", keep: int = 0):
        sp = _wrap(collection.spare, db, keep)
        if format == "text":
            return Response(collection.spare_text(sp), media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="scrybinder-spare-cards.txt"'})
        if format == "csv":
            return Response(collection.spare_csv(sp), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="scrybinder-spare-cards.csv"'})
        return sp

    @app.get("/api/collection/value-history")
    def value_history():
        return {"snapshots": collection.value_history(db)}

    @app.get("/api/backup")
    def backup_download():
        """A fresh consistent copy of the database as a download (plain browser; the app window saves through its own dialog)."""
        import tempfile
        from starlette.background import BackgroundTask
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=_db_path().parent)
        os.close(fd)
        try:
            dbmod.backup(db, tmp)
        except Exception as e:
            _rm_db(tmp)
            raise HTTPException(500, f"the backup failed: {e}")
        return FileResponse(tmp, media_type="application/vnd.sqlite3", filename=time.strftime("scrybinder-backup-%Y%m%d-%H%M%S.db"),
                            background=BackgroundTask(lambda: _rm_db(tmp)))

    @app.post("/api/restore")
    async def restore_upload(request: Request):
        """Check an uploaded backup and stage it: it replaces the database at the next start."""
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=_db_path().parent)
        try:
            size = 0
            with os.fdopen(fd, "wb") as f:
                async for chunk in request.stream():  # a big database is not held in memory
                    size += len(chunk)
                    f.write(chunk)
            if not size:
                raise ValueError("no file")
            info = await run_in_threadpool(dbmod.stage_restore, _db_path(), tmp)
        except ValueError as e:
            raise HTTPException(422, str(e))
        finally:
            _rm_db(tmp)
        return {"staged": True, "restart_required": True, "cards": info["cards"], "collection": info["collection"]}

    @app.get("/api/locations")
    def locs():
        return collection.locations(db)

    @app.post("/api/locations")
    def locs_create(body: dict = Body(...)):
        return {"location": _wrap(collection.create_location, db, body.get("name"))}

    @app.post("/api/locations/merge")
    def locs_merge(body: dict = Body(...)):
        return _wrap(collection.merge_locations, db, body.get("names"), body.get("into"))

    @app.delete("/api/locations")
    def locs_delete(name: str, cards: str = "move", release: bool = False):
        if cards not in ("move", "delete"):
            raise HTTPException(422, "cards: move or delete")
        return _wrap(collection.delete_location, db, name, cards == "delete", release, dbmod.DATA_DIR / "trash")

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
        return {"id": _wrap(decks.create, db, body.get("name"), body.get("format") or "casual", body.get("description") or "", body.get("folder_id"))}

    @app.get("/api/deck-folders")
    def deck_folders():
        return decks.folders(db)

    @app.post("/api/deck-folders")
    def deck_folder_create(body: dict = Body(...)):
        return {"id": _wrap(decks.create_folder, db, body.get("name"))}

    @app.patch("/api/deck-folders/{folder_id}")
    def deck_folder_rename(folder_id: int, body: dict = Body(...)):
        _wrap(decks.rename_folder, db, folder_id, body.get("name"))
        return {"ok": True}

    @app.delete("/api/deck-folders/{folder_id}")
    def deck_folder_delete(folder_id: int):
        _wrap(decks.delete_folder, db, folder_id)
        return {"ok": True}

    @app.get("/api/decks/shopping-list")  # before /api/decks/{deck_id}: that route would take "shopping-list" for an id
    def decks_shopping_list(format: str = "json", include_side: bool = False):
        sl = _wrap(decks.shopping_list, db, include_side)
        if format == "text":
            return Response(decks.shopping_text(sl), media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="scrybinder-shopping-list.txt"'})
        if format == "csv":
            return Response(decks.shopping_csv(sl), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="scrybinder-shopping-list.csv"'})
        return sl

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

    @app.get("/api/decks/{deck_id}/snapshots")
    def deck_snapshots(deck_id: int):
        return _wrap(decks.snapshots, db, deck_id)

    @app.post("/api/decks/{deck_id}/snapshots")
    def deck_snapshot_create(deck_id: int, body: dict = Body(...)):
        return {"id": _wrap(decks.save_snapshot, db, deck_id, body.get("name"))}

    @app.delete("/api/decks/{deck_id}/snapshots/{snapshot_id}")
    def deck_snapshot_delete(deck_id: int, snapshot_id: int):
        _wrap(decks.delete_snapshot, db, deck_id, snapshot_id)
        return {"ok": True}

    @app.post("/api/decks/{deck_id}/snapshots/{snapshot_id}/restore")
    def deck_snapshot_restore(deck_id: int, snapshot_id: int):
        return _wrap(decks.restore_snapshot, db, deck_id, snapshot_id)

    @app.get("/api/decks/{deck_id}/compare")
    def deck_compare(deck_id: int, base: str = "latest", target: str = "current"):
        if not all(v in ("latest", "current") or v.isdigit() for v in (base, target)):
            raise HTTPException(422, "base and target: current, latest or a snapshot id")
        pick = lambda v: int(v) if v.isdigit() else v
        return _wrap(decks.compare, db, deck_id, pick(base), pick(target))

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

    @app.post("/api/decks/{deck_id}/import-url")
    def decks_import_url(deck_id: int, body: dict = Body(...)):
        text = _wrap(deckurl.fetch_text, body.get("url"))
        return _wrap(decktext.import_text, db, deck_id, text, bool(body.get("dry_run")))

    @app.get("/api/decks/{deck_id}/export")
    def decks_export(deck_id: int, maybe: bool = False, include: str | None = None):  # include: comma-separated states, none = all
        text = _wrap(decktext.export_text, db, deck_id, maybe, include.split(",") if include else None)
        return Response(text, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="scrybinder-deck-{deck_id}.txt"'})

    @app.post("/api/decks/{deck_id}/duplicate")
    def decks_duplicate(deck_id: int):
        return {"id": _wrap(decks.duplicate, db, deck_id)}

    @app.post("/api/decks/{deck_id}/cards")
    def decks_add_card(deck_id: int, body: dict = Body(...)):
        sid, fin = body.get("scryfall_id"), body.get("finish")
        if sid is None and isinstance(body.get("oracle_id"), str):  # every card gets a printing: the one you own, else the cheapest
            sid, fin = decks.default_printing(db, body["oracle_id"])
        return {"id": _wrap(decks.add_card, db, deck_id, body.get("oracle_id"), body.get("quantity", 1),
                            body.get("board", "main"), sid, body.get("tags") or (), fin,
                            bool(body.get("new_line")))}

    @app.post("/api/decks/{deck_id}/fill-printings")
    def decks_fill_printings(deck_id: int):
        return {"filled": _wrap(decks.fill_printings, db, deck_id)}

    @app.patch("/api/decks/{deck_id}/cards/{card_id}")
    def decks_update_card(deck_id: int, card_id: int, body: dict = Body(...)):
        return {"id": _wrap(decks.update_card, db, deck_id, card_id,
                            **{k: v for k, v in body.items() if k in ("quantity", "board", "scryfall_id", "tags", "finish")})}

    @app.delete("/api/decks/{deck_id}/cards/{card_id}")
    def decks_remove_card(deck_id: int, card_id: int):
        _wrap(decks.remove_card, db, deck_id, card_id)
        return {"ok": True}

    def _edhrec_on() -> bool:
        r = db.execute("SELECT value FROM meta WHERE key='edhrec_enabled'").fetchone()
        return bool(r and r[0] == "1")

    @app.get("/api/edhrec")
    def edhrec_status():
        return {"enabled": _edhrec_on()}

    @app.post("/api/edhrec")
    def edhrec_settings(body: dict = Body(...)):
        with db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('edhrec_enabled', ?)", ("1" if body.get("enabled") else "0",))
        return {"enabled": _edhrec_on()}

    @app.get("/api/decks/{deck_id}/suggestions")
    def decks_suggestions(deck_id: int, source: str = "edhrec"):
        if source not in ("edhrec", "collection"):
            raise HTTPException(422, "source: edhrec or collection")
        if source == "edhrec" and not _edhrec_on():
            raise HTTPException(403, "EDHREC suggestions are off: turn them on first")
        return _wrap(suggest.suggestions, db, deck_id, dbmod.DATA_DIR, source == "edhrec")

    @app.get("/api/decks/{deck_id}/cards/{card_id}/copies")
    def decks_copies(deck_id: int, card_id: int):
        return _wrap(decks.copies, db, deck_id, card_id)

    @app.put("/api/decks/{deck_id}/cards/{card_id}/assign")
    def decks_assign(deck_id: int, card_id: int, body: dict = Body(...)):
        _wrap(decks.assign, db, deck_id, card_id, body.get("items"))
        return {"ok": True}

    @app.post("/api/decks/{deck_id}/cards/{card_id}/take")
    def decks_take(deck_id: int, card_id: int, body: dict = Body(...)):
        return {"moved": _wrap(decks.move_copy, db, deck_id, card_id, body.get("from_deck_id"), body.get("collection_id"), body.get("quantity", 1))}

    @app.post("/api/decks/{deck_id}/assign-free")
    def decks_assign_free(deck_id: int, body: dict = Body(default={})):
        ids = body.get("card_ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
            raise HTTPException(422, "card_ids: a list of ids")
        return {"assigned": _wrap(decks.assign_free, db, deck_id, None if ids is None else set(ids))}

    @app.post("/api/decks/{deck_id}/add-missing")
    def decks_add_missing(deck_id: int, body: dict = Body(default={})):
        return {"added": _wrap(decks.add_missing, db, deck_id, body.get("card_ids"), str(body.get("location") or ""))}

    @app.post("/api/decks/{deck_id}/cards/{card_id}/duplicate")
    def decks_duplicate_line(deck_id: int, card_id: int):
        return {"id": _wrap(decks.duplicate_line, db, deck_id, card_id)}

    @app.post("/api/decks/{deck_id}/cards/{card_id}/add-copy")
    def decks_add_copy(deck_id: int, card_id: int, body: dict = Body(default={})):
        return {"added": _wrap(decks.add_copy, db, deck_id, card_id, body.get("quantity", 1), str(body.get("location") or ""))}

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
    def coll_ids(q: str = "", set: str = "", location: list[str] | None = Query(None), finish: str = "", language: str = ""):
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

    # --- trades ---
    @app.get("/api/trades")
    def trades_list():
        return trades.listing(db)

    @app.post("/api/trades")
    def trades_create(body: dict = Body(default={})):
        return {"id": _wrap(trades.create, db, body.get("who"), body.get("note"), body.get("cash"))}

    @app.get("/api/trades/{trade_id}")
    def trades_get(trade_id: int):
        return _wrap(trades.get, db, trade_id)

    @app.patch("/api/trades/{trade_id}")
    def trades_edit(trade_id: int, body: dict = Body(...)):
        _wrap(trades.update, db, trade_id, **{k: v for k, v in body.items() if k in trades.TRADE_EDIT})
        return {"ok": True}

    @app.delete("/api/trades/{trade_id}")
    def trades_delete(trade_id: int):
        _wrap(trades.delete, db, trade_id)
        return {"ok": True}

    @app.post("/api/trades/{trade_id}/out")
    def trades_add_out(trade_id: int, body: dict = Body(...)):
        return {"id": _wrap(trades.add_out, db, trade_id, body.get("collection_id"), body.get("quantity", 1))}

    @app.post("/api/trades/{trade_id}/extra")
    def trades_add_extra(trade_id: int, body: dict = Body(...)):
        return {"id": _wrap(trades.add_extra, db, trade_id, str(body.get("scryfall_id") or ""), body.get("quantity", 1), body.get("price"),
                            **{k: body.get(k) for k in ("finish", "condition", "language")})}

    @app.post("/api/trades/{trade_id}/in")
    def trades_add_in(trade_id: int, body: dict = Body(...)):
        return {"id": _wrap(trades.add_in, db, trade_id, str(body.get("scryfall_id") or ""), body.get("quantity", 1), body.get("price"),
                            **{k: body.get(k) for k in ("finish", "condition", "language", "location")})}

    @app.patch("/api/trades/{trade_id}/{side}/{line_id}")
    def trades_edit_line(trade_id: int, side: str, line_id: int, body: dict = Body(...)):
        if side not in ("out", "in"):
            raise HTTPException(404)
        _wrap(trades.edit_line, db, trade_id, side, line_id, **{k: v for k, v in body.items() if k in trades.LINE_FIELDS})
        return {"ok": True}

    @app.delete("/api/trades/{trade_id}/{side}/{line_id}")
    def trades_delete_line(trade_id: int, side: str, line_id: int):
        if side not in ("out", "in"):
            raise HTTPException(404)
        _wrap(trades.delete_line, db, trade_id, side, line_id)
        return {"ok": True}

    @app.post("/api/trades/{trade_id}/confirm")
    def trades_confirm(trade_id: int):
        _wrap(trades.confirm, db, trade_id)
        return {"ok": True}

    # --- lists ---
    @app.get("/api/lists")
    def lists_all():
        return lists.listing(db)

    @app.post("/api/lists")
    def lists_create(body: dict = Body(...)):
        return {"id": _wrap(lists.create, db, body.get("name"), body.get("note") or "")}

    @app.post("/api/lists/from-location")  # before /api/lists/{list_id}
    def lists_from_location(body: dict = Body(...)):
        return {"id": _wrap(lists.create_from_location, db, body.get("location", ""), body.get("name") or "")}

    @app.get("/api/lists/{list_id}")
    def lists_get(list_id: int):
        return _wrap(lists.get, db, list_id)

    @app.patch("/api/lists/{list_id}")
    def lists_edit(list_id: int, body: dict = Body(...)):
        _wrap(lists.update, db, list_id, **{k: v for k, v in body.items() if k in ("name", "note")})
        return {"ok": True}

    @app.delete("/api/lists/{list_id}")
    def lists_delete(list_id: int):
        _wrap(lists.delete, db, list_id)
        return {"ok": True}

    @app.post("/api/lists/{list_id}/items")
    def lists_add(list_id: int, body: dict = Body(...)):
        if "collection_ids" in body:
            return {"added": _wrap(lists.add_from_collection, db, list_id, body["collection_ids"])}
        return {"added": _wrap(lists.add_items, db, list_id, body.get("items"))}

    @app.patch("/api/lists/{list_id}/items/{item_id}")
    def lists_edit_item(list_id: int, item_id: int, body: dict = Body(...)):
        _wrap(lists.edit_item, db, list_id, item_id, **{k: v for k, v in body.items() if k in ("quantity", "finish", "condition", "language", "note")})
        return {"ok": True}

    @app.delete("/api/lists/{list_id}/items/{item_id}")
    def lists_delete_item(list_id: int, item_id: int):
        _wrap(lists.delete_item, db, list_id, item_id)
        return {"ok": True}

    @app.get("/api/lists/{list_id}/export")
    def lists_export(list_id: int, format: str = "text"):
        lst = _wrap(lists.get, db, list_id)
        if format == "csv":
            return Response(lists.csv_text(lst), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="scrybinder-list.csv"'})
        return Response(lists.text(lst), media_type="text/plain; charset=utf-8")

    # --- share links ---
    def _share_wrap(fn, *a, **k):
        try:
            return _wrap(fn, *a, **k)
        except share.Unreachable as e:
            raise HTTPException(502, str(e))

    @app.post("/api/share/preview")
    def share_preview(body: dict = Body(...)):
        return _wrap(lambda: {**share.summary(share.build(db, body)), "existing": share.existing(db, body)})

    @app.post("/api/share")
    def share_create(body: dict = Body(...)):
        return _share_wrap(lambda: share.create_link(db, share.build(db, body), body))

    @app.put("/api/shares/{share_id}")
    def shares_update(share_id: str, body: dict = Body(default={})):
        return _share_wrap(share.update_link, db, share_id, body)

    @app.get("/api/shares")
    def shares_list():
        return share.listing(db)

    @app.delete("/api/shares/{share_id}")
    def shares_delete(share_id: str):
        _share_wrap(share.delete_link, db, share_id)
        return {"ok": True}

    @app.post("/api/import-share")
    async def import_share(request: Request, location: str = ""):
        text = (await request.body()).decode("utf-8-sig", errors="replace")
        return _wrap(share.import_text, db, text, location)

    @app.post("/api/import-share-link")
    def import_share_link(body: dict = Body(...)):
        """Import what a share link points to, as if its file had been downloaded and chosen."""
        def run():
            return share.import_text(db, share.fetch_link(str(body.get("url") or "")), str(body.get("location") or ""))
        return _share_wrap(run)

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
