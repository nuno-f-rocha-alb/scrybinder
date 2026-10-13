import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="console windows are a Windows thing")


def test_every_pytesseract_subprocess_call_hides_the_console(monkeypatch):
    import pytesseract

    from scrybinder.scan import identify  # noqa: F401  (installs the wrapper)

    seen = []
    for name in ("check_output", "run", "Popen"):
        monkeypatch.setattr(subprocess, name, lambda *a, _n=name, **k: seen.append((_n, k.get("creationflags"))))
    sp = pytesseract.pytesseract.subprocess
    sp.check_output(["tesseract", "--version"])  # what get_tesseract_version() does on the first scan
    sp.run(["tesseract", "--list-langs"])
    sp.Popen(["tesseract"], creationflags=0x200)  # a caller's own flags are kept
    assert [f & subprocess.CREATE_NO_WINDOW for _, f in seen] == [subprocess.CREATE_NO_WINDOW] * 3
    assert seen[2][1] == 0x200 | subprocess.CREATE_NO_WINDOW
    assert sp.TimeoutExpired is subprocess.TimeoutExpired and sp.PIPE is subprocess.PIPE  # everything else passes through
