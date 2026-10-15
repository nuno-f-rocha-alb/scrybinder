"""Log files in the data folder, so a problem leaves a trace.

- `app.log`: what the app does and every exception, including those of background threads and of the web server (rotated).
- `crash.log`: the Python stack of every thread when the process dies from a native crash (a driver, OpenCV, a DLL), which
  no Python exception can report. `scrybinder.log` stays what it was: the program's own stderr in the packaged app.
"""
import faulthandler
import logging
import logging.handlers
import platform
import sys
import threading
from pathlib import Path

from . import __version__

_crash_file = None  # kept open for the life of the process: faulthandler writes to it from the crash handler


def setup(data_dir: Path) -> Path:
    """Start logging to `<data_dir>/app.log` and the crash handler. Safe to call again. Returns the log path."""
    global _crash_file
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "app.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.set_name("scrybinder-file")
    for name in ("scrybinder", "uvicorn.error"):  # the web server logs its unhandled errors here
        lg = logging.getLogger(name)
        for old in [h for h in lg.handlers if h.get_name() == "scrybinder-file"]:
            lg.removeHandler(old)
            old.close()
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    log = logging.getLogger("scrybinder")

    def on_exception(kind, value, tb):
        log.critical("Unhandled exception", exc_info=(kind, value, tb))
        sys.__excepthook__(kind, value, tb)

    def on_thread_exception(args):
        if args.exc_type is SystemExit:  # a thread may end that way, as threading's own hook allows
            return
        log.critical("Unhandled exception in thread %s", getattr(args.thread, "name", "?"), exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception

    if _crash_file is None or _crash_file.closed:
        _crash_file = open(data_dir / "crash.log", "a", encoding="utf-8")
    faulthandler.enable(file=_crash_file, all_threads=True)

    log.info("Scrybinder %s starting: Python %s, %s, frozen=%s", __version__, platform.python_version(), platform.platform(),
             bool(getattr(sys, "frozen", False)))  # no paths: they hold the user name and the log is meant to be shared
    return path
