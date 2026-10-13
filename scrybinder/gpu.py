"""Optional GPU acceleration for installed builds (issue #9).

The installer bundles PyTorch for CPU only. Here the CUDA build is downloaded into the data folder (`<data>/gpu`) and used instead of the
bundled one. Only for the packaged Windows app: from source, `uv sync --extra vision-cuda` does the same.

Starting an installed app: `activate()` puts a small import hook ahead of the bundle's importer so that `torch` comes from `<data>/gpu`.
Anything that goes wrong leaves the app on CPU; `SCRYBINDER_NO_GPU=1` skips the hook (the way out if a driver update breaks it).
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from importlib.machinery import PathFinder
from pathlib import Path

import httpx

from . import db as dbmod

# The wheels are pinned (size and SHA-256 are checked): the newest one the driver accepts. cu130 is the same PyTorch version as the
# bundled CPU build (2.14.1); cu128 is for drivers that stop at CUDA 12.8/12.9.
WHEELS = [
    {"tag": "cu130", "min_driver": 13000, "torch": "2.14.1", "size": 1_990_608_063,
     "sha256": "0a09031e93632d14ef49553acd6211ece3ae9cdc0969a369b8c24e3cc4d15be9",
     "url": "https://download.pytorch.org/whl/cu130/torch-2.14.1%2Bcu130-cp312-cp312-win_amd64.whl"},
    {"tag": "cu128", "min_driver": 12080, "torch": "2.11.0", "size": 2_753_189_216,
     "sha256": "7c78215c3af4f62e63f2b2e360f1722fc719b0853c7ac22666483d9810613a4c",
     "url": "https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-win_amd64.whl"},
]
TOPS = ("torch", "torchgen", "functorch")  # what is taken from the wheel; its Python dependencies already ship in the installer
ACTIVE = False  # the GPU build is what this process imports


def supported() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def gpu_dir() -> Path:
    return dbmod.DATA_DIR / "gpu"


# --- the NVIDIA driver (without importing PyTorch) ---

def _nvcuda():
    if sys.platform != "win32":
        return None
    try:
        return ctypes.WinDLL("nvcuda.dll")
    except OSError:
        return None


def driver_cuda_version() -> int | None:
    """The CUDA version the installed NVIDIA driver supports (12080 = 12.8), or None without a driver."""
    lib = _nvcuda()
    if lib is None:
        return None
    v = ctypes.c_int(0)
    return v.value if lib.cuDriverGetVersion(ctypes.byref(v)) == 0 and v.value else None


def gpu_name() -> str | None:
    lib = _nvcuda()
    if lib is None or lib.cuInit(0) != 0:
        return None
    dev, buf = ctypes.c_int(0), ctypes.create_string_buffer(128)
    if lib.cuDeviceGet(ctypes.byref(dev), 0) != 0 or lib.cuDeviceGetName(buf, 128, dev) != 0:
        return None
    return buf.value.decode(errors="replace")


def choose_wheel(driver: int | None) -> dict | None:
    return next((w for w in WHEELS if driver and driver >= w["min_driver"]), None)


# --- using it ---

class _Finder:
    """Resolves torch and its siblings from the GPU folder. It must come first: the importer of the bundle would also hand out the
    packaged submodules (`torch.nn`...) and mix two PyTorch versions."""

    def __init__(self, root: Path, names=TOPS):
        self.root, self.names = str(root), set(names)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in self.names:
            return None
        return PathFinder.find_spec(fullname, [self.root] if path is None else path)  # a submodule: its parent's folder


def installed() -> dict | None:
    try:
        return json.loads((gpu_dir() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def activate(root: Path | None = None) -> bool:
    """Make this process import PyTorch from the GPU folder. Call it before anything imports torch. An explicit `root` is the
    self-test of a download that is not installed yet."""
    global ACTIVE
    explicit = root is not None
    root = root or gpu_dir()
    if not explicit and (root / "remove-on-start").exists():  # a removal asked for while the DLLs were loaded: now they are not
        shutil.rmtree(root, ignore_errors=True)
        return False
    if os.environ.get("SCRYBINDER_NO_GPU") or not (root / "torch" / "__init__.py").exists():
        return False
    if not explicit and installed() is None:  # a half installed folder
        return False
    sys.meta_path.insert(0, _Finder(root))
    lib = root / "torch" / "lib"
    if lib.is_dir():
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(lib))
        os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    ACTIVE = not explicit
    return True


def selftest(root: Path) -> int:
    """`Scrybinder.exe --gpu-selftest <folder>`: import PyTorch from <folder>, ask for the GPU and compute something on it.
    Exit code 0 = it works. The details go to <folder>/selftest.json."""
    result: dict = {"ok": False}
    try:
        activate(root)
        import torch
        folder = Path(torch.__file__).resolve().parent.parent
        result.update(version=torch.__version__, from_folder=folder == root.resolve(), cuda=bool(torch.cuda.is_available()))
        if result["cuda"]:
            result["device"] = torch.cuda.get_device_name(0)
            result["ok"] = bool(float((torch.ones(8, device="cuda") * 2).sum()) == 16.0) and result["from_folder"]
    except Exception as e:  # noqa: BLE001 — any failure is a failed test
        result["error"] = repr(e)
    try:
        (root / "selftest.json").write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    return 0 if result["ok"] else 1


def device_in_use() -> str | None:
    """What the visual model runs on, once PyTorch is loaded in this process."""
    torch = sys.modules.get("torch")
    if torch is None or not hasattr(torch, "cuda"):
        return None
    return f"GPU: {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else "CPU"


# --- installing and removing ---

def _fetch(url: str):
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        r.raise_for_status()
        yield from r.iter_bytes(1 << 20)


def _extract(wheel: Path, dest: Path) -> None:
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            top = info.filename.split("/", 1)[0]
            if top in TOPS and ".." not in info.filename.split("/"):
                z.extract(info, dest)
    if not (dest / "torch" / "__init__.py").exists():
        raise RuntimeError("the wheel does not contain PyTorch")


def _selftest_in_app(folder: Path) -> str | None:
    """None if the downloaded PyTorch works, else why not. Runs the packaged app itself in self-test mode."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        code = subprocess.run([sys.executable, "--gpu-selftest", str(folder)], timeout=300, creationflags=flags).returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"the test could not run ({e})"
    if code == 0:
        return None
    try:
        r = json.loads((folder / "selftest.json").read_text(encoding="utf-8"))
        return r.get("error") or ("PyTorch loaded but it does not see the GPU" if not r.get("cuda") else "the GPU test failed")
    except (OSError, ValueError):
        return "the GPU test failed"


def install(job: dict, wheel: dict, fetch=None, selftest=None) -> None:
    """Download, verify, extract and test `wheel`, then move it into place. Runs in a thread and reports through `job`."""
    root = gpu_dir()
    work, new = root / ".dl", root / ".new"
    try:
        for p in (work, new):
            shutil.rmtree(p, ignore_errors=True)
        work.mkdir(parents=True)
        job.update(state="download", done=0, total=wheel["size"], error=None)
        part, h = work / "torch.whl", hashlib.sha256()
        with open(part, "wb") as f:
            for chunk in (fetch or _fetch)(wheel["url"]):
                f.write(chunk)
                h.update(chunk)
                job["done"] += len(chunk)
        if h.hexdigest() != wheel["sha256"]:
            raise RuntimeError("the downloaded file does not match its checksum")
        job["state"] = "extract"
        _extract(part, new)
        part.unlink()
        job["state"] = "test"
        why = (selftest or _selftest_in_app)(new)
        if why:
            raise RuntimeError(why)
        for name in TOPS:
            shutil.rmtree(root / name, ignore_errors=True)
            if (new / name).exists():
                shutil.move(str(new / name), str(root / name))
        (root / "installed.json").write_text(json.dumps({"tag": wheel["tag"], "torch": wheel["torch"], "sha256": wheel["sha256"]}), encoding="utf-8")
        job["state"] = "done"
    except Exception as e:  # noqa: BLE001 — shown in Settings; the app stays as it was
        job.update(state="error", error=str(e) or e.__class__.__name__)
        if installed() is None:
            for name in TOPS:
                shutil.rmtree(root / name, ignore_errors=True)
    finally:
        for p in (work, new):
            shutil.rmtree(p, ignore_errors=True)


def remove() -> bool:
    """Delete the GPU folder. True if that has to wait for a restart (PyTorch's DLLs are loaded and Windows keeps them locked)."""
    root = gpu_dir()
    if not root.exists():
        return False
    try:
        shutil.rmtree(root)
        return False
    except OSError:
        root.mkdir(parents=True, exist_ok=True)
        (root / "remove-on-start").write_text("1", encoding="utf-8")
        return True


def status(job: dict) -> dict:
    drv = driver_cuda_version()
    w = choose_wheel(drv)
    return {"supported": supported(), "driver": drv, "gpu": gpu_name() if drv else None,
            "wheel": {k: w[k] for k in ("tag", "torch", "size")} if w else None, "installed": installed(),
            "pending_removal": (gpu_dir() / "remove-on-start").exists(), "active": ACTIVE, "device": device_in_use(), "job": job}
