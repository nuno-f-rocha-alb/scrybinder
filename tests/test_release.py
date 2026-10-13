import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import release as rel  # noqa: E402

CHANGELOG = """# Changelog

## [Unreleased]

### Added
- A new thing (#1).

### Fixed
- A bug.

## [0.2.0] — 2026-10-13

### Added
- Older thing.

## [0.1.0] — 2026-10-12

First public release.
"""


EMPTY_UNRELEASED = """# Changelog

## [Unreleased]

## [0.2.0] — 2026-10-13

- x
"""


def _tree(tmp_path, changelog=CHANGELOG):
    (tmp_path / "scrybinder").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "scrybinder"\nversion = "0.2.0"\n', encoding="utf-8")
    (tmp_path / "scrybinder" / "__init__.py").write_text('"""x"""\n__version__ = "0.2.0"\n', encoding="utf-8")
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "numpy"\nversion = "0.2.0"\n\n[[package]]\nname = "scrybinder"\nversion = "0.2.0"\nsource = { editable = "." }\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_the_version_is_bumped_in_every_file_and_only_there(tmp_path):
    root = _tree(tmp_path)
    out = rel.bump_files(root, "0.3.0", "2026-10-14")
    assert 'version = "0.3.0"' in out[root / "pyproject.toml"]
    assert '__version__ = "0.3.0"' in out[root / "scrybinder" / "__init__.py"]
    lock = out[root / "uv.lock"]
    assert 'name = "scrybinder"\nversion = "0.3.0"' in lock and 'name = "numpy"\nversion = "0.2.0"' in lock  # other packages untouched
    log = out[root / "CHANGELOG.md"]
    assert log.index("## [Unreleased]") < log.index("## [0.3.0] — 2026-10-14") < log.index("## [0.2.0]")
    assert "- A new thing (#1)." in log.split("## [0.3.0]")[1].split("## [0.2.0]")[0]      # the entries moved under the new version
    assert "- A new thing" not in log.split("## [0.3.0]")[0]                                # and left Unreleased empty
    assert rel.changelog_section(log, "0.3.0").startswith("### Added")


def test_a_release_needs_a_newer_version_and_something_to_say(tmp_path):
    root = _tree(tmp_path)
    for bad in ("0.2.0", "0.1.9", "banana", "1.2"):
        with pytest.raises(ValueError):
            rel.bump_files(root, bad, "2026-10-14")
    nothing = tmp_path / "nothing"
    nothing.mkdir()
    _tree(nothing, changelog=EMPTY_UNRELEASED)
    with pytest.raises(ValueError, match="empty"):
        rel.bump_files(nothing, "0.3.0", "2026-10-14")


def test_prerelease_and_notes_helpers(tmp_path):
    assert rel.parse("0.3.0-rc1") == (0, 3, 0)
    out = rel.bump_files(_tree(tmp_path), "0.3.0-rc1", "2026-10-14")
    assert 'version = "0.3.0-rc1"' in out[tmp_path / "pyproject.toml"]
    assert rel.changelog_section(CHANGELOG, "0.2.0") == "### Added\n- Older thing.\n"
    with pytest.raises(ValueError):
        rel.changelog_section(CHANGELOG, "9.9.9")


def test_the_real_repository_is_ready_to_be_bumped():
    """The files the script edits exist and carry the version it looks for (so a refactor does not silently break releases)."""
    root = Path(__file__).resolve().parent.parent
    try:
        out = rel.bump_files(root, "99.0.0", "2099-01-01")
    except ValueError as e:
        assert "empty" in str(e)  # right after a release there is nothing in [Unreleased]: that is the only acceptable reason
        return
    assert 'version = "99.0.0"' in out[root / "pyproject.toml"] and '__version__ = "99.0.0"' in out[root / "scrybinder" / "__init__.py"]
