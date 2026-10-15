"""Log files in the data folder, so a problem leaves a trace.

- `app.log`: what the app does and every exception, including those of background threads and of the web server (rotated).
- `crash.log`: the Python stack of every thread when the process dies from a native crash (a driver, OpenCV, a DLL), which
  no Python exception can report. Each run writes a line with the time when it starts and one when it ends normally, so a
  stack without an end line belongs to the run that started above it.
- `scrybinder.log`: the program's own stdout and stderr in the packaged app (the web server's lines, what libraries print).
  Every line starts with the time, like the lines of `app.log`.
"""
import atexit
import faulthandler
import io
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
from pathlib import Path

from . import __version__

_crash_file = None  # kept open for the life of the process: faulthandler writes to it from the crash handler


def now() -> str:
    """The time as the log lines write it: 2026-10-15 15:00:08,005 (local time, milliseconds)."""
    t = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + ",%03d" % (t % 1 * 1000)


class Stamped(io.TextIOBase):
    """A text stream that puts the time in front of every line written to it. It stands in for stdout / stderr of the packaged app, so
    nothing that is printed (the web server, a library) lands in the file without one. A progress bar redrawn with a carriage return
    becomes lines; blank lines are dropped."""

    encoding = "utf-8"

    def __init__(self, raw):
        self._raw, self._buf, self._lock = raw, "", threading.Lock()

    def writable(self):
        return True

    def isatty(self):
        return False

    def write(self, s):
        if not s:
            return 0
        with self._lock:
            *lines, self._buf = (self._buf + s.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
            for line in lines:
                if line.strip():
                    self._raw.write(f"{now()} {line}\n")
            if lines:
                self._raw.flush()
        return len(s)

    def flush(self):
        with self._lock:
            if self._buf.strip():
                self._raw.write(f"{now()} {self._buf}\n")
            self._buf = ""
            self._raw.flush()


def stamped_stream(path: Path) -> Stamped:
    """`path` opened for appending, every line written to it starting with the time."""
    return Stamped(open(path, "a", encoding="utf-8", buffering=1))


def _end_of_run():
    """A normal end of the process: a crash dump with no such line after it is the one of the run that ended in the crash."""
    try:
        if _crash_file is not None and not _crash_file.closed:
            _crash_file.write(f"{now()} --- ended normally (process {os.getpid()}) ---\n")
            _crash_file.flush()
    except Exception:  # noqa: BLE001 — at exit there is nobody left to tell
        pass


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
    _crash_file.write(f"{now()} --- Scrybinder {__version__} started (process {os.getpid()}) ---\n")
    _crash_file.flush()
    faulthandler.enable(file=_crash_file, all_threads=True)
    atexit.register(_end_of_run)

    log.info("Scrybinder %s starting: Python %s, %s, frozen=%s", __version__, platform.python_version(), platform.platform(),
             bool(getattr(sys, "frozen", False)))  # no paths: they hold the user name and the log is meant to be shared
    return path
