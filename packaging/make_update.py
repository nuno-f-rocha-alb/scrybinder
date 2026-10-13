"""Update packages: the files that changed between two Scrybinder releases, so that nobody has to download the whole 1 GB again.

PyTorch and the DINOv2 weights are most of the app and almost never change; the app code and the UI are a few tens of MB.

    python packaging/make_update.py manifest dist/Scrybinder dist/Scrybinder/manifest.json --version 0.2.0
    python packaging/make_update.py manifest-from-zip old-portable.zip old-manifest.json --version 0.1.0
    python packaging/make_update.py update dist/Scrybinder old-manifest.json out/update.zip --version 0.2.0

Formats (an in-app updater can rely on them):
  manifest.json  {"version": "0.2.0", "files": {"relative/posix/path": "<sha256>", ...}}. It ships inside the app folder and as a release asset.
  update zip     the changed and new files, at their path relative to the app folder, plus `UPDATE.txt` (instructions for people) and `update.json`:
                 {"from": "0.1.0", "to": "0.2.0", "remove": ["files that no longer exist"]}
                 To apply: close Scrybinder, extract over the app folder, delete the files in "remove". `data/` (the user's database in a
                 portable install) is never touched.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

SKIP = {"manifest.json", "portable.txt"}  # not application files
USER_DATA = "data/"  # a portable install keeps the user's database here: never part of an update


def _sha256(stream) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def manifest_of_dir(root: Path, version: str) -> dict:
    files = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and rel not in SKIP and not rel.startswith(USER_DATA):
            with open(p, "rb") as f:
                files[rel] = _sha256(f)
    return {"version": version, "files": files}


def manifest_of_zip(zip_path: Path, version: str) -> dict:
    """Manifest of a portable zip (whose files sit under one top folder), without extracting it."""
    files = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else info.filename
            if rel not in SKIP and not rel.startswith(USER_DATA):
                with z.open(info) as f:
                    files[rel] = _sha256(f)
    return {"version": version, "files": dict(sorted(files.items()))}


INSTRUCTIONS = r"""Scrybinder update: {old} -> {new}

This is NOT an installer: it holds only the files that changed since version {old}.
It only works on top of version {old}. For any other version, use the full installer from the release page.

1. Close Scrybinder completely (also check the system tray / Task Manager).
2. Find the app folder:
     - installed with the setup program: %LOCALAPPDATA%\Programs\Scrybinder
     - portable zip: the folder you extracted it to (the one with Scrybinder.exe)
3. Extract this zip INTO that folder and choose "Replace the files in the destination" when asked.
4. {removal}
5. Start Scrybinder. Settings shows the new version number.

Your collection and the card images are not touched: they live in the data folder
(%LOCALAPPDATA%\Scrybinder, or the "data" folder next to Scrybinder.exe in the portable version).
"""


def build_update(root: Path, new: dict, old: dict, out_zip: Path) -> dict:
    """Zip of what changed since `old`; returns {"changed": n, "removed": n}."""
    changed = [rel for rel, h in new["files"].items() if old["files"].get(rel) != h]
    removed = sorted(rel for rel in old["files"] if rel not in new["files"])
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in changed:
            z.write(root / rel, rel)
        sep = "\n       "
        removal = ("Delete these files from the app folder (they are no longer part of the app):" + sep + sep.join(removed)
                   if removed else "Nothing to delete in this update.")
        text = INSTRUCTIONS.format(old=old["version"], new=new["version"], removal=removal)
        z.writestr("UPDATE.txt", text.replace("\n", "\r\n"))  # Windows line endings: opens right in any Notepad
        z.writestr("update.json", json.dumps({"from": old["version"], "to": new["version"], "remove": removed}, indent=2))
    return {"changed": len(changed), "removed": len(removed)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("manifest", "manifest-from-zip"):
        s = sub.add_parser(name)
        s.add_argument("source", type=Path)
        s.add_argument("out", type=Path)
        s.add_argument("--version", required=True)
    u = sub.add_parser("update")
    u.add_argument("root", type=Path)
    u.add_argument("old_manifest", type=Path)
    u.add_argument("out", type=Path)
    u.add_argument("--version", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "update":
        res = build_update(a.root, manifest_of_dir(a.root, a.version), json.loads(a.old_manifest.read_text(encoding="utf-8")), a.out)
        print(f"{a.out}: {res['changed']} files changed or new, {res['removed']} removed, {a.out.stat().st_size / 1e6:.1f} MB")
    else:
        m = (manifest_of_dir if a.cmd == "manifest" else manifest_of_zip)(a.source, a.version)
        a.out.write_text(json.dumps(m, indent=1), encoding="utf-8")
        print(f"{a.out}: {len(m['files'])} files")


if __name__ == "__main__":
    main()
