"""In-app updater for installed builds (issue #19).

A release publishes `Scrybinder-<new>-update-from-<old>.zip` (only the files that changed, plus `update.json`), `manifest.json` (SHA-256 of
every file of the app) and `SHA256SUMS`. Here the app finds the chain of packages from its version to the latest one (at most 3), downloads
them, checks every hash and applies them. Windows will not overwrite or delete a running exe/DLL but it does let you rename it, so each
changed file is renamed to `<name>.old` and the new one takes its place; the `.old` files are deleted at the next start. Anything that goes
wrong undoes the renames: a package is applied completely or not at all, so the app is always on a version that works.

Trust: files are checked against the `manifest.json` and `SHA256SUMS` of the same release, over HTTPS from github.com. That catches a corrupt
download, not a compromised release (the installer is not code-signed).
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path, PureWindowsPath

import httpx

from . import __version__, db as dbmod

REPO = os.environ.get("SCRYBINDER_UPDATE_REPO", "nuno-f-rocha-alb/scrybinder")
MAX_STEPS = 3  # more packages than this behind: the full installer is the better download
KEEP = ("UPDATE.txt", "update.json")  # in the zip but not part of the app
NEVER = ("data/", "portable.txt")  # the user's data is never touched (make_update.py does not ship it either)
HEADERS = {"User-Agent": f"Scrybinder/{__version__} (update check)", "Accept": "application/vnd.github+json"}


def supported() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    return Path(sys.executable).parent


def update_dir() -> Path:
    return dbmod.DATA_DIR / "update"


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split("."))  # ValueError on "0.4.0-rc1": pre-releases are skipped anyway


def _fetch(url: str):
    with httpx.stream("GET", url, headers=HEADERS, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        r.raise_for_status()
        yield from r.iter_bytes(1 << 20)


# --- what is there to install ---

def plan(releases: list[dict], current: str = __version__) -> dict:
    """The chain of update packages from `current` to the newest release, or `needs_installer` when there is none (or it is too long)."""
    good = []
    for r in releases:
        if r.get("draft") or r.get("prerelease"):
            continue
        try:
            good.append((vtuple(r["tag_name"]), r))
        except (ValueError, KeyError):
            continue
    out = {"current": current, "latest": current, "up_to_date": True, "chain": [], "needs_installer": False, "url": None, "notes": ""}
    if not good:
        return out
    latest_v, latest = max(good, key=lambda x: x[0])
    out.update(latest=latest["tag_name"].lstrip("v"), up_to_date=latest_v <= vtuple(current), url=latest.get("html_url"),
               notes=latest.get("body") or "")
    if out["up_to_date"]:
        return out
    cur = current
    for _ in range(MAX_STEPS):
        step = None
        for v, r in good:
            assets = {a["name"]: a for a in r.get("assets", [])}
            ver = r["tag_name"].lstrip("v")
            zip_name = f"Scrybinder-{ver}-update-from-{cur}.zip"
            if v > vtuple(cur) and zip_name in assets and "manifest.json" in assets and "SHA256SUMS" in assets:
                step = {"from": cur, "version": ver, "zip": assets[zip_name]["browser_download_url"], "zip_name": zip_name,
                        "size": assets[zip_name]["size"], "manifest": assets["manifest.json"]["browser_download_url"],
                        "sums": assets["SHA256SUMS"]["browser_download_url"]}
                break
        if step is None:
            break
        out["chain"].append(step)
        cur = step["version"]
        if cur == out["latest"]:
            return out
    out.update(chain=[], needs_installer=True)
    return out


def check(get=None) -> dict:
    def fetch_json(url):
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
        r.raise_for_status()
        return r.json()
    return plan((get or fetch_json)(f"https://api.github.com/repos/{REPO}/releases?per_page=20"))


# --- installing one package ---

def _safe(rel: str) -> str:
    p = PureWindowsPath(rel)  # also catches drive-relative paths such as "C:x"
    if p.anchor or ".." in p.parts or "\\" in rel or rel.lower().startswith(NEVER) or ".old" in rel or rel.endswith(".new"):
        raise RuntimeError(f"the package contains a path it should not: {rel}")
    return rel


def _sums(text: str) -> dict[str, str]:
    return {m.group(2): m.group(1).lower() for m in re.finditer(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", text, re.M)}


def _download(url: str, dest: Path, job: dict, fetch) -> str:
    h = hashlib.sha256()
    with open(dest, "wb") as f:
        for chunk in fetch(url):
            f.write(chunk)
            h.update(chunk)
            job["done"] += len(chunk)
    return h.hexdigest()


def _old(p: Path, tag: str) -> Path:
    return p.with_name(f"{p.name}.old-{tag}")  # one per package: the previous package's copy is the file the running app has open


def _rollback(app: Path, pend: dict) -> list[str]:
    """Put back what `pend` (see _apply) says was moved, and delete what it says was created. Safe to run when nothing happened yet.
    Returns files that had to be set aside (the new exe, when it is the one running): to be deleted at a later start."""
    aside = []
    for rel, old_rel in reversed(pend["moves"]):
        if (app / old_rel).exists():
            try:
                os.replace(app / old_rel, app / rel)
            except PermissionError:  # the file there is in use (a new exe doing its own rollback): rename it away, then put the old one back
                bad = app / (rel + ".bad")
                bad.unlink(missing_ok=True)
                (app / rel).rename(bad)
                os.replace(app / old_rel, app / rel)
                aside.append(rel + ".bad")
    for rel in pend["created"]:
        (app / rel).unlink(missing_ok=True)
    for rel in pend["staged"]:
        (app / (rel + ".new")).unlink(missing_ok=True)
    return aside


@contextlib.contextmanager
def _apply_lock(root: Path):
    """Held while files are being swapped (or undone); yields False if another Scrybinder holds it. The OS drops it if that process dies,
    so a crashed update can be undone while a running one is left alone."""
    root.mkdir(parents=True, exist_ok=True)
    f = open(root / "apply.lock", "a+b")
    got = True
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        got = False
    try:
        yield got
    finally:
        f.close()  # releases the lock


def _apply(app: Path, changed: list[str], removed: list[str], tag: str) -> list[str]:
    with _apply_lock(update_dir()) as got:
        if not got:
            raise RuntimeError("another Scrybinder window is applying an update: wait for it to finish")
        return _apply_locked(app, changed, removed, tag)


def _apply_locked(app: Path, changed: list[str], removed: list[str], tag: str) -> list[str]:
    """Rename-and-replace; the first error puts everything back. Returns the files that could not be renamed because they are open without
    sharing (base_library.zip is): they stay as `<name>.new` and are put in place by `restart()` once this process has exited. `pending.json` says what is in flight, so a crash is undone at the next start."""
    root = update_dir()
    changed = sorted(changed, key=lambda r: "/" not in r and r.lower().endswith(".exe"))  # the exe last: until then the old one still starts and can undo a crash
    moves = [(rel, f"{rel}.old-{tag}") for rel in changed + removed if (app / rel).exists()]
    pend = {"moves": moves, "created": [rel for rel in changed if not (app / rel).exists()], "staged": changed}
    old_json = root / "old.json"
    leftovers = json.loads(old_json.read_text(encoding="utf-8")) if old_json.exists() else []
    old_json.write_text(json.dumps(leftovers + [m[1] for m in moves]), encoding="utf-8")  # before touching anything
    (root / "pending.json").write_text(json.dumps(pend), encoding="utf-8")
    deferred: list[str] = []
    try:
        for rel in changed:
            t = app / rel
            if t.exists():
                old = _old(t, tag)
                old.unlink(missing_ok=True)
                try:
                    t.rename(old)
                except PermissionError:
                    deferred.append(rel)
                    continue
            t.parent.mkdir(parents=True, exist_ok=True)
            os.replace(app / (rel + ".new"), t)
        for rel in removed:
            t = app / rel
            if t.exists():
                old = _old(t, tag)
                old.unlink(missing_ok=True)
                t.rename(old)
    except OSError as e:
        try:
            _rollback(app, pend)
        except OSError:
            pass  # pending.json stays: the next start tries again
        else:
            (root / "pending.json").unlink(missing_ok=True)
        raise RuntimeError(f"could not replace {getattr(e, 'filename', None) or 'a file'}: {e.strerror or e}; nothing was changed") from e
    if deferred:
        dj = root / "deferred.json"
        dj.write_text(json.dumps(sorted(set(json.loads(dj.read_text(encoding="utf-8")) if dj.exists() else []) | set(deferred))), encoding="utf-8")
    (root / "pending.json").write_text(json.dumps({**pend, "done": True}), encoding="utf-8")  # complete: a crash from here on must not undo it
    (root / "pending.json").unlink(missing_ok=True)
    return deferred


def _install_step(job: dict, step: dict, fetch) -> None:
    app, work = app_dir(), update_dir() / step["version"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    staged: list[Path] = []
    keep: set[str] = set()  # staged files that restart() still has to put in place
    try:
        job["state"] = "download"
        sums = _sums(b"".join(fetch(step["sums"])).decode("utf-8", "replace"))
        manifest = json.loads(b"".join(fetch(step["manifest"])))
        zpath = work / step["zip_name"]
        if _download(step["zip"], zpath, job, fetch) != sums.get(step["zip_name"]):
            raise RuntimeError("the downloaded package does not match its checksum")
        job["state"] = "verify"
        with zipfile.ZipFile(zpath) as z:
            info = json.loads(z.read("update.json"))
            if info.get("from") != step["from"] or info.get("to") != step["version"]:
                raise RuntimeError(f"the package is for {info.get('from')} -> {info.get('to')}, not {step['from']} -> {step['version']}")
            names = [_safe(n) for n in z.namelist() if n not in KEEP and not n.endswith("/")]
            removed = [_safe(r) for r in info.get("remove", [])]
            for n in names:
                if n == "manifest.json":
                    if json.loads(z.read(n)) != manifest:
                        raise RuntimeError("the manifest in the package is not the one of the release")
                elif n not in manifest["files"]:
                    raise RuntimeError(f"{n} is not in the release manifest")
            for n in names:  # extract next to the target: a rename on the same volume is atomic
                dest = app / (n + ".new")
                dest.parent.mkdir(parents=True, exist_ok=True)
                staged.append(dest)
                h = hashlib.sha256()
                with z.open(n) as src, open(dest, "wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
                        h.update(chunk)
                if n != "manifest.json" and h.hexdigest() != manifest["files"][n]:
                    raise RuntimeError(f"{n} does not match its checksum")
        job["state"] = "apply"
        keep = {n + ".new" for n in _apply(app, names, removed, step["version"])}
    finally:
        for p in staged:
            if p.relative_to(app).as_posix() not in keep:
                p.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)


def install(job: dict, pl: dict, fetch=None) -> None:
    """Download, verify and apply the chain of `pl`. Runs in a thread and reports through `job`; every package leaves a working version."""
    fetch = fetch or _fetch
    try:
        if pl["chain"][0]["from"] != __version__:
            raise RuntimeError("the version changed since the check: check again")
        job.update(done=0, total=sum(s["size"] for s in pl["chain"]), error=None, step=0, steps=len(pl["chain"]), applied=None)
        for i, step in enumerate(pl["chain"], 1):
            job["step"] = i
            _install_step(job, step, fetch)
            job["applied"] = step["version"]
        job["state"] = "done"
    except Exception as e:  # noqa: BLE001 — shown in Settings; the version that was installed keeps working
        job.update(state="error", error=str(e) or e.__class__.__name__)


# --- start-up and restart ---

def cleanup_on_start() -> None:
    """Undo an update that was cut short, then delete the `.old` files of the last one (they were still in use then) and any download left over."""
    root = update_dir()
    if not root.exists():
        return
    try:
        listed = json.loads((root / "old.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = []
    with _apply_lock(root) as got:
        if not got:
            return  # another Scrybinder window is in the middle of an update: leave everything as it is
        try:  # the app was closed (or crashed) in the middle of an update: put the previous version back first
            pend = json.loads((root / "pending.json").read_text(encoding="utf-8"))
            if not pend.get("done"):
                listed += _rollback(app_dir(), pend)
            (root / "pending.json").unlink()
        except (OSError, ValueError, KeyError):
            pass
    try:  # files restart() should have put in place but that are still staged: drop them
        for rel in json.loads((root / "deferred.json").read_text(encoding="utf-8")):
            (app_dir() / (rel + ".new")).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    if (root / "pending.json").exists():
        return  # it could not be undone yet and the .old files are the only copy of the previous version: keep them, try again next start
    left = []
    for rel in listed:
        try:
            (app_dir() / rel).unlink(missing_ok=True)
        except OSError:
            left.append(rel)
    for p in root.iterdir():
        if p.name not in ("old.json", "pending.json"):
            shutil.rmtree(p, ignore_errors=True)
    if left:
        (root / "old.json").write_text(json.dumps(left), encoding="utf-8")
    else:
        shutil.rmtree(root, ignore_errors=True)


def finish_script(app: Path, deferred: list[str], exe: str, args: list[str]) -> str:
    """cmd script: wait until the app has exited (a `move` onto a file that is still open fails), put the deferred files in place, start the app."""
    q = lambda s: '"' + str(s).replace("%", "%%") + '"'  # noqa: E731
    lines = ["@echo off", "chcp 65001 >nul"]  # the script is UTF-8: user names may have any character
    for i, rel in enumerate(deferred):
        lines += [f"set n=0", f":w{i}", f"move /y {q(app / (rel + '.new'))} {q(app / rel)} >nul 2>&1 && goto d{i}",
                  "set /a n+=1", f"if %n% lss 60 (ping -n 2 127.0.0.1 >nul & goto w{i})", f":d{i}"]
    lines.append(f'start "" {q(exe)} ' + " ".join(q(a) for a in args))
    return "\r\n".join(lines) + "\r\n"


def restart() -> None:
    """Start the app again (a new process, its own port) and close this one. Files that were locked are put in place first, by a cmd script."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}  # the new process must not reuse this one's bootloader state
    try:
        deferred = json.loads((update_dir() / "deferred.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        deferred = []
    if deferred:
        script = update_dir() / "finish.cmd"
        script.write_text(finish_script(app_dir(), deferred, sys.executable, sys.argv[1:]), encoding="utf-8")
        # no DETACHED_PROCESS here: a cmd.exe without a console makes every console program it runs (ping, move) open its own window
        hidden = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/c", str(script)], creationflags=hidden, close_fds=True, cwd=str(app_dir()), env=env)
    else:
        subprocess.Popen([sys.executable, *sys.argv[1:]], creationflags=flags, close_fds=True, cwd=str(app_dir()), env=env)
    threading.Timer(0.5, os._exit, [0]).start()  # after the response has gone out
