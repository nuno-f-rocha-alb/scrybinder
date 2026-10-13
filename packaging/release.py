"""Make a release with one command.

    python packaging/release.py prepare 0.4.0 [--dry-run]   bump the version everywhere, move CHANGELOG [Unreleased] to it, open a PR
    python packaging/release.py version                      print the version in pyproject.toml
    python packaging/release.py notes 0.4.0                  print the CHANGELOG section of a version (the release notes)

The whole flow:

1. `prepare` (here, on an up-to-date `main`): branch `release/X.Y.Z` with the version bump and the changelog, pushed, and a pull request opened.
2. You merge that PR when CI is green (`main` is protected).
3. `.github/workflows/tag-release.yml` sees the version change on `main`, creates the tag `vX.Y.Z` and starts `release.yml`, which builds, tests and
   publishes the installer, the portable zip, the update package, `manifest.json` and `SHA256SUMS`, with the changelog section as the notes.
"""
import argparse
import datetime
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.]+)?$")


def parse(version: str) -> tuple[int, int, int]:
    m = SEMVER.match(version)
    if not m:
        raise ValueError(f"{version!r} is not a version like 1.2.3 (or 1.2.3-rc1)")
    return int(m[1]), int(m[2]), int(m[3])


def current_version(pyproject_text: str) -> str:
    m = re.search(r'^version = "([^"]+)"', pyproject_text, re.M)
    if not m:
        raise ValueError("no version in pyproject.toml")
    return m[1]


def release_changelog(text: str, version: str, today: str) -> str:
    """CHANGELOG with the [Unreleased] entries moved under `## [version] — today`, and a new empty [Unreleased]."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[)", text, re.S | re.M)
    if not m:
        raise ValueError("CHANGELOG.md has no [Unreleased] section followed by a released one")
    body = m.group(1).strip("\n")
    if not body.strip():
        raise ValueError("The [Unreleased] section of CHANGELOG.md is empty: write what changed first")
    return text[:m.start()] + f"## [Unreleased]\n\n## [{version}] — {today}\n\n{body}\n\n" + text[m.end():]


def changelog_section(text: str, version: str) -> str:
    m = re.search(r"^## \[" + re.escape(version) + r"\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip() + "\n"


def bump_files(root: Path, version: str, today: str) -> dict[Path, str]:
    """New text of every file that carries the version (nothing is written)."""
    py = root / "pyproject.toml"
    old = current_version(py.read_text(encoding="utf-8"))
    if parse(version)[:3] < parse(old)[:3] or (parse(version)[:3] == parse(old)[:3] and version == old):
        raise ValueError(f"{version} is not newer than the current version {old}")
    out: dict[Path, str] = {}

    def sub(path: Path, pattern: str, repl: str) -> None:
        text = path.read_text(encoding="utf-8")
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n != 1:
            raise ValueError(f"could not find the version in {path.name}")
        out[path] = new

    sub(py, r'^version = "[^"]+"', f'version = "{version}"')
    sub(root / "scrybinder" / "__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{version}"')
    sub(root / "uv.lock", r'(name = "scrybinder"\nversion = )"[^"]+"', rf'\g<1>"{version}"')
    out[root / "CHANGELOG.md"] = release_changelog((root / "CHANGELOG.md").read_text(encoding="utf-8"), version, today)
    return out


def _run(*cmd: str, check=True, capture=False) -> str:
    r = subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=capture)
    return (r.stdout or "").strip() if capture else ""


def prepare(version: str, dry_run: bool) -> None:
    today = datetime.date.today().isoformat()
    changes = bump_files(ROOT, version, today)  # validates the version and the changelog before touching anything
    notes = changelog_section(changes[ROOT / "CHANGELOG.md"], version)
    print(f"Release {version} ({today}); the notes will be:\n\n{notes}")
    if dry_run:
        print("Dry run: nothing was changed. Files that would change:", ", ".join(p.name for p in changes))
        return
    if _run("git", "status", "--porcelain", capture=True):
        sys.exit("The working tree is not clean: commit or stash first.")
    if _run("git", "branch", "--show-current", capture=True) != "main":
        sys.exit("Run this on the main branch.")
    _run("git", "fetch", "-q", "origin", "main")
    if _run("git", "rev-parse", "HEAD", capture=True) != _run("git", "rev-parse", "origin/main", capture=True):
        sys.exit("main is not up to date with origin/main: git pull first.")
    branch = f"release/{version}"
    _run("git", "switch", "-q", "-c", branch)
    for path, text in changes.items():
        path.write_text(text, encoding="utf-8", newline="")
    _run("git", "add", *[str(p) for p in changes])
    _run("git", "commit", "-q", "-m", f"chore(release): {version}")
    _run("git", "push", "-q", "-u", "origin", branch)
    body = (f"Version {version}: `pyproject.toml`, `scrybinder/__init__.py`, `uv.lock` and the changelog.\n\n{notes}\n"
            f"Merge when CI is green. The tag `v{version}` is then created automatically and the release is built and published.\n")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    _run("gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Release {version}", "--body-file", f.name)
    Path(f.name).unlink(missing_ok=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("version")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("version")
    n = sub.add_parser("notes")
    n.add_argument("version")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            prepare(a.version, a.dry_run)
        elif a.cmd == "version":
            print(current_version((ROOT / "pyproject.toml").read_text(encoding="utf-8")))
        else:
            print(changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), a.version), end="")
    except ValueError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # the Windows console (cp1252) can't print the "→" in notes
    main()
