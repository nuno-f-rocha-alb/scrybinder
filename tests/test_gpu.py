import hashlib
import importlib
import json
import shutil
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from scrybinder import db as dbmod, gpu
from scrybinder.api import create_app

TOKEN = "tok"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)
    monkeypatch.delenv("SCRYBINDER_NO_GPU", raising=False)
    monkeypatch.setattr(gpu, "ACTIVE", False)
    return tmp_path


def _wheel(path, extra=()):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in {"torch/__init__.py": "", "torch/lib/x.dll": "dll", "torchgen/__init__.py": "", "functorch/__init__.py": "",
                           "torch-2.14.1.dist-info/METADATA": "m", "nvidia/junk.py": "x", **dict.fromkeys(extra, "x")}.items():
            z.writestr(name, text)
    return path


def _fetch_of(path):
    return lambda url: iter([path.read_bytes()])


def _spec(path):
    data = path.read_bytes()
    return {"tag": "cu130", "torch": "2.14.1", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.invalid/x.whl"}


def test_the_wheel_is_chosen_by_the_driver():
    assert gpu.choose_wheel(13040)["tag"] == "cu130"
    assert gpu.choose_wheel(12090)["tag"] == "cu128"
    assert gpu.choose_wheel(12020) is None and gpu.choose_wheel(None) is None


def test_pinned_wheels_look_sane():
    for w in gpu.WHEELS:
        assert len(w["sha256"]) == 64 and w["url"].startswith("https://download.pytorch.org/") and w["tag"] in w["url"] and w["size"] > 1e9


def test_the_gpu_folder_wins_over_the_bundled_package(tmp_path):
    """The import hook must hand out the package AND its submodules from the GPU folder, whatever else is importable."""
    bundled, gpudir = tmp_path / "bundled", tmp_path / "gpu"
    for root, tag in ((bundled, "bundled"), (gpudir, "gpu")):
        (root / "zz_gpu_demo").mkdir(parents=True)
        (root / "zz_gpu_demo" / "__init__.py").write_text(f"WHO = '{tag}'")
        (root / "zz_gpu_demo" / "sub.py").write_text(f"WHO = '{tag}'")
    sys.path.insert(0, str(bundled))
    finder = gpu._Finder(gpudir, names=("zz_gpu_demo",))
    sys.meta_path.insert(0, finder)
    try:
        assert importlib.import_module("zz_gpu_demo").WHO == "gpu"
        assert importlib.import_module("zz_gpu_demo.sub").WHO == "gpu"
    finally:
        sys.meta_path.remove(finder)
        sys.path.remove(str(bundled))
        for m in [m for m in sys.modules if m.startswith("zz_gpu_demo")]:
            del sys.modules[m]


def test_extract_takes_only_pytorch_and_its_siblings(tmp_path):
    whl, out = _wheel(tmp_path / "t.whl"), tmp_path / "out"
    gpu._extract(whl, out)
    assert sorted(p.name for p in out.iterdir()) == ["functorch", "torch", "torchgen"]
    assert (out / "torch" / "lib" / "x.dll").exists()
    empty = tmp_path / "e.whl"
    zipfile.ZipFile(empty, "w").close()
    with pytest.raises(RuntimeError):
        gpu._extract(empty, tmp_path / "o2")


def test_install_ok(data, tmp_path):
    whl = _wheel(tmp_path / "t.whl")
    job = {"state": "idle", "done": 0, "total": 0, "error": None}
    gpu.install(job, _spec(whl), fetch=_fetch_of(whl), selftest=lambda folder: None)
    assert job["state"] == "done" and job["done"] == whl.stat().st_size
    root = data / "gpu"
    assert (root / "torch" / "__init__.py").exists() and json.loads((root / "installed.json").read_text())["tag"] == "cu130"
    assert not (root / ".dl").exists() and not (root / ".new").exists()
    assert gpu.activate() is True  # installed and present: the hook goes in
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, gpu._Finder)]


def test_a_wrong_checksum_installs_nothing(data, tmp_path):
    whl = _wheel(tmp_path / "t.whl")
    spec = {**_spec(whl), "sha256": "0" * 64}
    job = {"state": "idle", "done": 0, "total": 0, "error": None}
    gpu.install(job, spec, fetch=_fetch_of(whl), selftest=lambda folder: pytest.fail("must not be tested"))
    assert job["state"] == "error" and "checksum" in job["error"]
    assert list((data / "gpu").iterdir()) == []


def test_a_failed_self_test_installs_nothing(data, tmp_path):
    whl = _wheel(tmp_path / "t.whl")
    job = {"state": "idle", "done": 0, "total": 0, "error": None}
    gpu.install(job, _spec(whl), fetch=_fetch_of(whl), selftest=lambda folder: "PyTorch loaded but it does not see the GPU")
    assert job["state"] == "error" and "GPU" in job["error"]
    assert list((data / "gpu").iterdir()) == [] and gpu.installed() is None


def test_activate_needs_an_install_and_respects_the_off_switch(data, monkeypatch):
    assert gpu.activate() is False                                   # nothing downloaded
    root = data / "gpu"
    (root / "torch").mkdir(parents=True)
    (root / "torch" / "__init__.py").write_text("")
    assert gpu.activate() is False                                   # a half installed folder (no installed.json)
    (root / "installed.json").write_text("{}")
    monkeypatch.setenv("SCRYBINDER_NO_GPU", "1")
    assert gpu.activate() is False                                   # the way out if a driver update breaks it


def test_removal_waits_for_a_restart_when_windows_keeps_the_files(data, monkeypatch):
    root = data / "gpu"
    (root / "torch").mkdir(parents=True)
    (root / "torch" / "__init__.py").write_text("")
    (root / "installed.json").write_text("{}")
    monkeypatch.setattr(gpu, "ACTIVE", True)                         # PyTorch is loaded from it in this session
    assert gpu.remove() is True and (root / "remove-on-start").exists() and (root / "torch" / "__init__.py").exists()  # nothing deleted yet
    monkeypatch.setattr(gpu, "ACTIVE", False)                        # the next start
    assert gpu.activate() is False and not root.exists()             # deleted before anything is loaded
    (root / "torch").mkdir(parents=True)
    (root / "installed.json").write_text("{}")
    assert gpu.remove() is False and not root.exists()               # installed this session, not loaded: deleted at once


def test_self_test_fails_cleanly_on_an_empty_folder(tmp_path):
    assert gpu.selftest(tmp_path) == 1
    assert json.loads((tmp_path / "selftest.json").read_text())["ok"] is False


def test_gpu_api_outside_the_installed_app(db, data):
    c = TestClient(create_app(db, token=TOKEN, allowed_hosts={"testserver"}))
    c.get(f"/api/status?t={TOKEN}")
    st = c.get("/api/gpu").json()
    assert st["supported"] is False and st["job"]["state"] == "idle"
    assert c.post("/api/gpu/install").status_code == 400            # from source: uv sync --extra vision-cuda
    assert c.post("/api/gpu/remove").json() == {"restart_needed": False}
