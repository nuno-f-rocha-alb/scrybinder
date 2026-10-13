"""Start-up: local server on a free port + pywebview window. `uv run scrybinder`.

Options: `--serve` prints the URL and waits (development), `--browser` opens your normal browser instead of a window.
If no native web view is available (e.g. missing GTK/Qt on Linux) it falls back to the browser automatically.
"""
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import gpu, updater
from .api import create_app


def _icon() -> str | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))  # PyInstaller unpacks data files to _MEIPASS
    icon = base / "assets" / "scrybinder.ico"
    return str(icon) if icon.exists() else None


class Bridge:
    """Exposed to the page as `window.pywebview.api`: a native Save dialog for CSV and text exports."""

    @staticmethod
    def _save(name: str, text: str, file_types: tuple) -> str | None:
        """Ask where to save, write the file, return its path (None if the dialog was cancelled)."""
        import webview
        got = webview.windows[0].create_file_dialog(webview.FileDialog.SAVE, save_filename=Path(name).name, file_types=file_types)
        if not got:
            return None
        path = Path(got if isinstance(got, str) else got[0])
        path.write_text(text, encoding="utf-8", newline="")
        return str(path)

    def save_csv(self, name: str, text: str) -> str | None:
        return self._save(name, text, ("CSV files (*.csv)",))

    def save_text(self, name: str, text: str) -> str | None:  # a deck list
        return self._save(name, text, ("Text files (*.txt)",))


def _redirect_output_to_log():
    """pythonw / packaged app without a console: uvicorn needs a stderr, so send it to a file."""
    from .db import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(DATA_DIR / "scrybinder.log", "a", encoding="utf-8", buffering=1)


def _wait_forever():
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


def main():
    if "--gpu-selftest" in sys.argv:  # the packaged app tests a downloaded PyTorch (Settings → GPU acceleration)
        sys.exit(gpu.selftest(Path(sys.argv[sys.argv.index("--gpu-selftest") + 1])))
    if sys.stderr is None or getattr(sys, "frozen", False):
        _redirect_output_to_log()
    if getattr(sys, "frozen", False):
        updater.cleanup_on_start()  # the .old files of the last update
        gpu.activate()  # before anything imports torch: use the downloaded CUDA build if there is one
    if sys.platform == "win32":
        try:  # own identity in the taskbar (otherwise it groups with Python and shows its icon)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Scrybinder.App")
        except Exception:  # noqa: BLE001 — cosmetic only
            pass

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = secrets.token_urlsafe(24)
    app = create_app(token=token, auto_bulk=os.environ.get("SCRYBINDER_AUTO_BULK", "1") != "0")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/?t={token}"

    if "--serve" in sys.argv:  # development: just print the URL
        print(url, flush=True)
        return _wait_forever()
    if "--browser" not in sys.argv:
        try:
            import webview  # late import: tests and --serve mode do not need it
            webview.create_window("Scrybinder", url, width=1400, height=900, background_color="#0f1115", js_api=Bridge())
            webview.start(icon=_icon())
            return
        except Exception as e:  # noqa: BLE001 — no native web view available: use the browser instead
            print(f"No native window available ({e}); opening your browser instead.", flush=True)
    webbrowser.open(url)
    print(f"Scrybinder is running at {url}  (Ctrl+C to quit)", flush=True)
    _wait_forever()


if __name__ == "__main__":
    main()
