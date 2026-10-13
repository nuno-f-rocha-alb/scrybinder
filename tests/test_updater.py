import hashlib
import io
import json
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from scrybinder import db as dbmod, updater as up
from scrybinder.api import create_app


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    app, data = tmp_path / "app", tmp_path / "data"
    app.mkdir()
    data.mkdir()
    monkeypatch.setattr(dbmod, "DATA_DIR", data)
    monkeypatch.setattr(up, "app_dir", lambda: app)
    monkeypatch.setattr(up, "__version__", "0.3.0")
    return app


def _package(files: dict[str, bytes], old="0.3.0", new="0.3.1", remove=(), zip_files=None, manifest_files=None):
    """(fetch, step): a release that changes `files`; the zip and the manifest can be made to disagree on purpose."""
    manifest = {"version": new, "files": manifest_files if manifest_files is not None else {k: _sha(v) for k, v in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in (zip_files if zip_files is not None else files).items():
            z.writestr(k, v)
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("update.json", json.dumps({"from": old, "to": new, "remove": list(remove)}))
    blob, name = buf.getvalue(), f"Scrybinder-{new}-update-from-{old}.zip"
    urls = {"zip": blob, "man": json.dumps(manifest).encode(), "sums": f"{_sha(blob)}  {name}\n".encode()}

    def fetch(url):
        yield urls[url]
    return fetch, {"from": old, "version": new, "zip": "zip", "zip_name": name, "size": len(blob), "manifest": "man", "sums": "sums"}


def _run(step, fetch):
    job = {"state": "download", "done": 0}
    up.install(job, {"chain": [step]}, fetch)
    return job


def _app_state(app):
    return {str(p.relative_to(app)): p.read_bytes() for p in sorted(app.rglob("*")) if p.is_file()}


def test_installs_changed_files_and_removes_old_ones(env):
    (env / "a.dll").write_bytes(b"a1")
    (env / "gone.txt").write_bytes(b"x")
    fetch, step = _package({"a.dll": b"a2", "sub/new.js": b"n"}, remove=["gone.txt"])
    job = _run(step, fetch)
    assert job["state"] == "done" and job["applied"] == "0.3.1"
    assert (env / "a.dll").read_bytes() == b"a2" and (env / "sub/new.js").read_bytes() == b"n" and not (env / "gone.txt").exists()
    assert (env / "a.dll.old-0.3.1").read_bytes() == b"a1" and (env / "gone.txt.old-0.3.1").exists()  # still there: the running app may have them open
    assert not list(env.rglob("*.new")) and (env / "manifest.json").exists()
    up.cleanup_on_start()  # the next start
    assert not list(env.rglob("*.old")) and not (dbmod.DATA_DIR / "update").exists()


def test_cleanup_keeps_a_file_that_is_still_locked(env, monkeypatch):
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"a.dll": b"2"})
    _run(step, fetch)
    real = up.Path.unlink

    def locked(self, *a, **k):
        if self.name == "a.dll.old-0.3.1":
            raise PermissionError("in use")
        return real(self, *a, **k)
    monkeypatch.setattr(up.Path, "unlink", locked)
    up.cleanup_on_start()
    assert json.loads((dbmod.DATA_DIR / "update" / "old.json").read_text()) == ["a.dll.old-0.3.1"]  # tried again next start


@pytest.mark.parametrize("what", ["zip", "file", "from", "path", "drive", "case", "manifest"])
def test_a_bad_package_changes_nothing(env, what):
    (env / "a.dll").write_bytes(b"a1")
    before = _app_state(env)
    if what == "zip":
        fetch, step = _package({"a.dll": b"a2"})
        step["zip"] = "man"  # not the zip the SHA256SUMS describes
    elif what == "file":
        fetch, step = _package({"a.dll": b"a2"}, manifest_files={"a.dll": _sha(b"other")})
    elif what == "from":
        fetch, step = _package({"a.dll": b"a2"}, old="0.2.0")
        step["from"] = "0.3.0"
    elif what == "path":
        fetch, step = _package({"../evil.dll": b"x"})
    elif what == "drive":
        fetch, step = _package({"C:evil.dll": b"x"})
    elif what == "case":
        fetch, step = _package({"a.dll": b"a2"}, remove=["Data/scrybinder.db"])
    else:
        fetch, step = _package({"a.dll": b"a2"}, manifest_files={})
    job = _run(step, fetch)
    assert job["state"] == "error" and job["error"]
    assert _app_state(env) == before and (env / "a.dll").read_bytes() == b"a1"


def test_a_failure_while_applying_puts_everything_back(env, monkeypatch):
    for n in ("a.dll", "b.dll", "gone.txt"):
        (env / n).write_bytes(b"old-" + n.encode())
    before = _app_state(env)
    fetch, step = _package({"a.dll": b"A", "b.dll": b"B"}, remove=["gone.txt"])
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:  # the second new file cannot be put in place
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)
    monkeypatch.setattr(up.os, "replace", flaky)
    job = _run(step, fetch)
    monkeypatch.setattr(up.os, "replace", real)
    assert job["state"] == "error" and "nothing was changed" in job["error"]
    assert _app_state(env) == before


class _Crash(BaseException):
    """The process dies: nothing in the updater gets to catch it."""


def test_a_crash_in_the_middle_is_undone_at_the_next_start(env, monkeypatch):
    for n in ("a.dll", "b.dll", "gone.txt"):
        (env / n).write_bytes(b"old-" + n.encode())
    before = _app_state(env)
    fetch, step = _package({"a.dll": b"A", "b.dll": b"B", "new.js": b"N"}, remove=["gone.txt"])
    real, calls = os.replace, []

    def die(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise _Crash()
        return real(src, dst)
    monkeypatch.setattr(up.os, "replace", die)
    with pytest.raises(_Crash):
        _run(step, fetch)
    monkeypatch.setattr(up.os, "replace", real)
    up.cleanup_on_start()  # the next start
    assert _app_state(env) == before and not (dbmod.DATA_DIR / "update").exists()


def test_the_running_exe_is_set_aside_when_rolling_back(env, monkeypatch):
    (env / "app.exe").write_bytes(b"1")
    fetch, step = _package({"app.exe": b"2"})
    real = os.replace
    monkeypatch.setattr(up.os, "replace", lambda s, d: (_ for _ in ()).throw(_Crash()) if str(s).endswith("app.exe.new") else real(s, d))
    with pytest.raises(_Crash):
        _run(step, fetch)  # the old exe is app.exe.old-0.3.1, app.exe is gone
    monkeypatch.setattr(up.os, "replace", real)
    (env / "app.exe").write_bytes(b"2")  # the new exe got in and is the one running now
    real_replace = os.replace

    def locked_target(s, d):  # Windows: cannot overwrite a running exe
        if str(d).endswith("app.exe") and (env / "app.exe").exists():
            raise PermissionError("in use")
        return real_replace(s, d)
    monkeypatch.setattr(up.os, "replace", locked_target)
    real_unlink = up.Path.unlink
    monkeypatch.setattr(up.Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("in use")) if self.name == "app.exe.bad" and self.exists() else real_unlink(self, *a, **k))
    up.cleanup_on_start()
    assert (env / "app.exe").read_bytes() == b"1" and (env / "app.exe.bad").read_bytes() == b"2"  # the running one cannot be deleted yet
    monkeypatch.setattr(up.os, "replace", real)
    monkeypatch.setattr(up.Path, "unlink", real_unlink)
    up.cleanup_on_start()  # the next start removes the one that was set aside
    assert not (env / "app.exe.bad").exists()


def test_the_exe_is_replaced_last(env, monkeypatch):
    (env / "app.exe").write_bytes(b"1")
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"app.exe": b"2", "a.dll": b"2", "sub/x.exe": b"2"})
    real, order = os.replace, []
    monkeypatch.setattr(up.os, "replace", lambda s, d: (order.append(os.path.basename(str(d))), real(s, d))[1])
    assert _run(step, fetch)["state"] == "done"
    assert order[-1] == "app.exe" and set(order) == {"app.exe", "a.dll", "x.exe", "manifest.json"}


def test_a_crash_after_everything_was_applied_keeps_the_update(env, monkeypatch):
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"a.dll": b"2"})
    real_unlink = up.Path.unlink

    def die(self, *a, **k):
        if self.name == "pending.json":
            raise _Crash()
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(up.Path, "unlink", die)
    with pytest.raises(_Crash):
        _run(step, fetch)
    monkeypatch.setattr(up.Path, "unlink", real_unlink)
    up.cleanup_on_start()
    assert (env / "a.dll").read_bytes() == b"2"


def _lock(monkeypatch, name):
    """Windows: a file the running process holds open without sharing cannot be renamed (base_library.zip is one)."""
    real = up.Path.rename

    def rename(self, target):
        if self.name == name:
            raise PermissionError(32, "in use", str(self))
        return real(self, target)
    monkeypatch.setattr(up.Path, "rename", rename)


def test_a_locked_file_is_left_for_restart(env, monkeypatch):
    (env / "_internal").mkdir()
    (env / "_internal/base_library.zip").write_bytes(b"old")
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"_internal/base_library.zip": b"new", "a.dll": b"2"})
    _lock(monkeypatch, "base_library.zip")
    job = _run(step, fetch)
    assert job["state"] == "done"
    assert (env / "a.dll").read_bytes() == b"2"  # everything else went in
    assert (env / "_internal/base_library.zip").read_bytes() == b"old"  # the locked one waits
    assert (env / "_internal/base_library.zip.new").read_bytes() == b"new"  # staged and verified
    assert json.loads((dbmod.DATA_DIR / "update" / "deferred.json").read_text()) == ["_internal/base_library.zip"]
    up.cleanup_on_start()  # a start that did not get it in place drops the staged copy
    assert not (env / "_internal/base_library.zip.new").exists()


def test_restart_puts_deferred_files_in_place_first(env, monkeypatch):
    launched = []
    flags = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda cmd, **k: (launched.append(cmd), flags.append(k["creationflags"])))
    monkeypatch.setattr(up.threading, "Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(up.sys, "executable", str(env / "Scrybinder.exe"))
    monkeypatch.setattr(up.sys, "argv", ["Scrybinder.exe"])
    up.restart()
    assert launched == [[str(env / "Scrybinder.exe")]]  # nothing deferred: just start again
    (dbmod.DATA_DIR / "update").mkdir(exist_ok=True)
    (dbmod.DATA_DIR / "update" / "deferred.json").write_text(json.dumps(["_internal/base_library.zip"]))
    up.restart()
    assert launched[1][1] == "/c" and launched[1][2].endswith("finish.cmd")
    assert not flags[1] & 0x8  # DETACHED_PROCESS: the console programs in the script would each open a visible window
    text = open(launched[1][2], encoding="utf-8").read()
    assert "base_library.zip.new" in text and "move /y" in text and text.rstrip().endswith('"' + str(env / "Scrybinder.exe") + '"')


def test_finish_script_escapes_percent_signs(tmp_path):
    s = up.finish_script(tmp_path / "100%", ["a b.dll"], str(tmp_path / "x.exe"), ["--browser"])
    assert "100%%" in s and '"a b.dll.new"' not in s and "a b.dll.new" in s and s.endswith('"--browser"\r\n')


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_finish_script_runs(tmp_path):
    tmp_path = tmp_path / "João – ç"  # accents and a character outside the OEM page
    tmp_path.mkdir()
    (tmp_path / "f.zip").write_bytes(b"old")
    (tmp_path / "f.zip.new").write_bytes(b"new")
    script = tmp_path / "finish.cmd"
    script.write_text(up.finish_script(tmp_path, ["f.zip"], sys.executable, ["-c", "open('started.txt', 'w').write('ok')"]), encoding="utf-8")
    import subprocess
    import time
    subprocess.run(["cmd", "/c", str(script)], check=True, cwd=tmp_path)  # the launched python exits: no console window is left behind
    for _ in range(50):
        if (tmp_path / "started.txt").exists():
            break
        time.sleep(0.1)
    assert (tmp_path / "f.zip").read_bytes() == b"new" and (tmp_path / "started.txt").exists()


def test_a_second_window_does_not_undo_an_update_in_progress(env, monkeypatch):
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"a.dll": b"2"})
    real = os.replace
    monkeypatch.setattr(up.os, "replace", lambda s, d: (_ for _ in ()).throw(_Crash()) if str(d).endswith("a.dll") else real(s, d))
    with pytest.raises(_Crash):
        _run(step, fetch)  # a.dll moved aside, pending.json written: an interrupted update
    monkeypatch.setattr(up.os, "replace", real)
    root = dbmod.DATA_DIR / "update"
    with up._apply_lock(root) as got:  # ...but here another window still holds the lock, so it is not interrupted
        assert got
        up.cleanup_on_start()  # a second window starting
        assert not (env / "a.dll").exists() and (root / "pending.json").exists()  # left alone
        with up._apply_lock(root) as again:
            assert again is False
    up.cleanup_on_start()  # nobody holds it any more: it really was a crash
    assert (env / "a.dll").read_bytes() == b"1"


def test_apply_refuses_while_another_window_applies(env):
    fetch, step = _package({"a.dll": b"2"})
    with up._apply_lock(dbmod.DATA_DIR / "update") as got:
        assert got
        job = _run(step, fetch)
    assert job["state"] == "error" and "another Scrybinder" in job["error"] and not (env / "a.dll").exists()


def test_start_up_keeps_the_old_files_when_it_cannot_undo_yet(env, monkeypatch):
    (env / "a.dll").write_bytes(b"1")
    fetch, step = _package({"a.dll": b"2"})
    real = os.replace
    monkeypatch.setattr(up.os, "replace", lambda s, d: (_ for _ in ()).throw(_Crash()) if str(d).endswith("a.dll") else real(s, d))
    with pytest.raises(_Crash):
        _run(step, fetch)
    monkeypatch.setattr(up.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("locked")))
    up.cleanup_on_start()  # cannot restore a.dll yet
    assert (env / "a.dll.old-0.3.1").read_bytes() == b"1" and (dbmod.DATA_DIR / "update" / "pending.json").exists()
    monkeypatch.setattr(up.os, "replace", real)
    up.cleanup_on_start()
    assert (env / "a.dll").read_bytes() == b"1"


def test_never_touches_the_data_folder(env):
    fetch, step = _package({"data/scrybinder.db": b"x"})
    assert _run(step, fetch)["state"] == "error" and not (env / "data").exists()


def _release(tag, frm, pre=False):
    names = [f"Scrybinder-{tag}-update-from-{f}.zip" for f in frm] + ["manifest.json", "SHA256SUMS"]
    return {"tag_name": "v" + tag, "prerelease": pre, "html_url": "u/" + tag, "body": "notes " + tag,
            "assets": [{"name": n, "browser_download_url": "dl/" + n, "size": 10} for n in names]}


def test_plan_chains_up_to_three_packages():
    r = [_release("0.3.0", ["0.2.0"]), _release("0.3.1", ["0.3.0"]), _release("0.4.0", ["0.3.1"]), _release("0.5.0", ["0.4.0"])]
    p = up.plan(r, "0.3.0")
    assert [s["version"] for s in p["chain"]] == ["0.3.1", "0.4.0", "0.5.0"] and p["latest"] == "0.5.0" and not p["needs_installer"]
    assert up.plan(r, "0.5.0")["up_to_date"] and up.plan(r, "0.5.0")["chain"] == []


def test_plan_asks_for_the_installer_when_it_cannot_chain():
    r = [_release("0.3.1", ["0.3.0"]), _release("0.4.0", ["0.3.1"]), _release("0.5.0", ["0.4.0"]), _release("0.6.0", ["0.5.0"])]
    assert up.plan(r, "0.3.0")["needs_installer"]  # four behind
    assert up.plan(r, "0.2.0")["needs_installer"]  # no package from 0.2.0
    assert up.plan([_release("0.4.0", ["0.3.1"])], "0.3.0")["needs_installer"]  # a gap in the chain


def test_plan_ignores_prereleases_and_drafts():
    r = [_release("0.3.1", ["0.3.0"]), _release("0.4.0-rc1", ["0.3.1"], pre=True), {**_release("0.9.0", ["0.3.1"]), "draft": True}]
    p = up.plan(r, "0.3.0")
    assert p["latest"] == "0.3.1" and len(p["chain"]) == 1


def test_chain_applies_each_package_in_turn(env):
    (env / "a.dll").write_bytes(b"1")
    f1, s1 = _package({"a.dll": b"2"}, "0.3.0", "0.3.1")
    f2, s2 = _package({"a.dll": b"3"}, "0.3.1", "0.3.2")
    pool = {}
    for tag, (f, s) in {"1": (f1, s1), "2": (f2, s2)}.items():  # distinct URLs per package
        for k in ("zip", "man", "sums"):
            pool[tag + k] = b"".join(f(k))
        s.update(zip="%szip" % tag, manifest="%sman" % tag, sums="%ssums" % tag)
    job = {"state": "download", "done": 0}
    up.install(job, {"chain": [s1, s2]}, lambda url: iter([pool[url]]))
    assert job["state"] == "done" and job["applied"] == "0.3.2" and (env / "a.dll").read_bytes() == b"3"
    assert (env / "a.dll.old-0.3.1").read_bytes() == b"1" and (env / "a.dll.old-0.3.2").read_bytes() == b"2"  # the first copy is still locked in a real run


def test_install_refuses_a_stale_plan(env):
    fetch, step = _package({"a.dll": b"2"}, old="0.2.0")
    job = _run(step, fetch)
    assert job["state"] == "error" and "check again" in job["error"]


def test_api_setting_and_unsupported(db, env):
    c = TestClient(create_app(db, token="tok", allowed_hosts={"testserver"}))
    c.get("/api/status?t=tok")
    st = c.get("/api/update").json()
    assert st["supported"] is False and st["check_on_start"] is False and st["job"]["state"] == "idle"
    assert c.post("/api/update/settings", json={"check_on_start": True}).json() == {"check_on_start": True}
    assert c.get("/api/update").json()["check_on_start"] is True
    assert c.post("/api/update/check").status_code == 400    # from source: git pull
    assert c.post("/api/update/install").status_code == 400
    assert c.post("/api/update/restart").status_code == 409
    assert c.get("/api/status").json()["update_available"] is None
