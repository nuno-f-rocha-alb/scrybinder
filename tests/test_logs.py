import faulthandler
import logging
import sys
import threading

import numpy as np
import pytest

from scrybinder import logs
from scrybinder.scan import session


@pytest.fixture
def logged(tmp_path, monkeypatch):
    """logs.setup on a temporary folder, with the hooks and handlers put back afterwards."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    path = logs.setup(tmp_path)
    yield path
    for name in ("scrybinder", "uvicorn.error"):
        for h in [h for h in logging.getLogger(name).handlers if h.get_name() == "scrybinder-file"]:
            logging.getLogger(name).removeHandler(h)
            h.close()
    faulthandler.disable()
    logs._crash_file.close()


def text(path):
    for h in logging.getLogger("scrybinder").handlers:
        h.flush()
    return path.read_text(encoding="utf-8")


def test_setup_writes_a_banner_and_arms_the_crash_handler(logged, tmp_path):
    assert logged == tmp_path / "app.log" and "Scrybinder" in text(logged) and "starting" in text(logged)
    assert (tmp_path / "crash.log").exists() and faulthandler.is_enabled()
    logs.setup(tmp_path)  # again: one line per message, not one per call
    assert text(logged).count("starting") == 2


def test_unhandled_exceptions_are_logged_in_the_main_thread_and_in_other_threads(logged, capsys):
    try:
        raise ValueError("boom in main")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    t = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError("boom in thread")), name="worker")
    t.start()
    t.join()
    out = text(logged)
    assert "boom in main" in out and "Traceback" in out
    assert "boom in thread" in out and "thread worker" in out
    capsys.readouterr()


def test_a_thread_that_exits_is_not_a_crash(logged):
    t = threading.Thread(target=lambda: sys.exit(0))
    t.start()
    t.join()
    assert "CRITICAL" not in text(logged)


def test_the_web_servers_errors_land_in_the_same_file(logged):
    logging.getLogger("uvicorn.error").error("Exception in ASGI application")
    assert "Exception in ASGI application" in text(logged)


def test_a_failing_camera_is_logged_and_reported_instead_of_dying_silently(logged, db, tmp_path, monkeypatch):
    class Cap:
        def __init__(self, *a):
            self.reads = 0

        def isOpened(self):
            return True

        def set(self, *a):
            pass

        def get(self, prop):
            return 640.0

        def getBackendName(self):
            return "FAKE"

        def read(self):
            self.reads += 1
            if self.reads > 2:
                raise RuntimeError("driver exploded")
            return True, np.zeros((480, 640, 3), np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(session.cv2, "VideoCapture", Cap)
    scanner = session.Scanner(db, tmp_path)
    scanner._run_webcam(0)  # in the thread of the camera; here called directly
    out = text(logged)
    assert "Camera 0 opened" in out and "first frame: shape (480, 640, 3)" in out
    assert "Camera 0 failed after 2 frames" in out and "driver exploded" in out and "Camera 0 closed" in out
    assert scanner.message == "The camera failed: driver exploded"


def test_a_camera_that_cannot_be_opened_is_logged(logged, db, tmp_path, monkeypatch):
    class Closed:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return False

    monkeypatch.setattr(session.cv2, "VideoCapture", Closed)
    scanner = session.Scanner(db, tmp_path)
    scanner._run_webcam(3)
    assert "Could not open camera 3" in text(logged) and scanner.message == "Could not open camera 3."


STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} "


def test_every_line_of_the_output_log_starts_with_the_time(tmp_path):
    import re
    out = logs.stamped_stream(tmp_path / "scrybinder.log")
    out.write("one\ntwo ")
    out.write("still two\n\n")  # a line written in pieces stays one line; a blank one is dropped
    out.write("bar 10%\rbar 50%\rbar 100%\n")  # a progress bar redrawn with a carriage return
    print("printed", file=out, flush=True)
    out.write("no newline at the end")
    out.flush()
    lines = (tmp_path / "scrybinder.log").read_text(encoding="utf-8").splitlines()
    assert [re.sub(STAMP, "", l) for l in lines] == ["one", "two still two", "bar 10%", "bar 50%", "bar 100%", "printed", "no newline at the end"]
    assert all(re.match(STAMP, l) for l in lines) and not out.isatty()


def test_the_crash_log_marks_when_a_run_started_and_ended(logged, tmp_path):
    import re
    logs._end_of_run()
    lines = (tmp_path / "crash.log").read_text(encoding="utf-8").splitlines()
    assert re.match(STAMP + r"--- Scrybinder .* started \(process \d+\) ---", lines[0]) and re.match(STAMP + r"--- ended normally", lines[-1])


def test_a_visual_index_that_failed_to_open_is_tried_again_and_logged(logged, db, monkeypatch):
    from scrybinder.scan import identify, visual
    calls = []

    class Fake:
        def warm(self):
            pass

    def try_open(**kw):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("zlib: incorrect header check")
        return Fake()

    monkeypatch.setattr(visual.Visual, "try_open", classmethod(lambda cls, emb=None, db=None: try_open()))
    ident = identify.Identifier(db)
    assert ident.vis() is None and ident.vis() is None and len(calls) == 1  # failed; the next call is within the 30 s: no new try
    ident._vis_retry_at = 0
    assert ident.vis() is None and len(calls) == 2
    ident._vis_retry_at = 0
    assert isinstance(ident.vis(), Fake) and len(calls) == 3  # the third try works
    assert ident.vis() is not None and len(calls) == 3  # and it is not opened again
    log = text(logged)
    assert "attempt 1" in log and "it will be tried again" in log and "zlib" in log and "Visual index opened" in log  # in app.log, with the time
