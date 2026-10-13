import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import make_update as mu  # noqa: E402


def _tree(root: Path, files: dict[str, bytes]):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_update_zip_has_only_what_changed(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _tree(old, {"Scrybinder.exe": b"exe-1", "_internal/torch.dll": b"big", "_internal/ui/a.js": b"a1", "_internal/gone.txt": b"x", "portable.txt": b""})
    _tree(new, {"Scrybinder.exe": b"exe-2", "_internal/torch.dll": b"big", "_internal/ui/a.js": b"a1", "_internal/ui/b.js": b"b1", "data/scrybinder.db": b"mine"})  # data/: a portable install's database
    old_m, new_m = mu.manifest_of_dir(old, "0.1.0"), mu.manifest_of_dir(new, "0.2.0")
    assert "portable.txt" not in old_m["files"] and len(old_m["files"]) == 4
    res = mu.build_update(new, new_m, old_m, tmp_path / "up.zip")
    assert res == {"changed": 2, "removed": 1}
    with zipfile.ZipFile(tmp_path / "up.zip") as z:
        assert sorted(z.namelist()) == ["Scrybinder.exe", "UPDATE.txt", "_internal/ui/b.js", "update.json"]  # the big unchanged file is not in it
        text = z.read("UPDATE.txt").decode()
        assert "0.1.0 -> 0.2.0" in text and "_internal/gone.txt" in text and "NOT an installer" in text
        info = json.loads(z.read("update.json"))
    assert info == {"from": "0.1.0", "to": "0.2.0", "remove": ["_internal/gone.txt"]}


def test_manifest_of_a_portable_zip_matches_the_folder(tmp_path):
    root = tmp_path / "Scrybinder"
    _tree(root, {"Scrybinder.exe": b"exe", "_internal/x.bin": b"123", "portable.txt": b""})
    zp = tmp_path / "portable.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for p in root.rglob("*"):
            if p.is_file():
                z.write(p, f"Scrybinder/{p.relative_to(root).as_posix()}")
    assert mu.manifest_of_zip(zp, "0.1.0") == mu.manifest_of_dir(root, "0.1.0")


def test_cli_roundtrip(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _tree(old, {"a": b"1", "b": b"2"})
    _tree(new, {"a": b"1", "b": b"3"})
    mu.main(["manifest", str(old), str(tmp_path / "old.json"), "--version", "1.0.0"])
    mu.main(["update", str(new), str(tmp_path / "old.json"), str(tmp_path / "u.zip"), "--version", "1.1.0"])
    with zipfile.ZipFile(tmp_path / "u.zip") as z:
        assert sorted(z.namelist()) == ["UPDATE.txt", "b", "update.json"]
