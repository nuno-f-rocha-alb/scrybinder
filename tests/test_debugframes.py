import json

import numpy as np
from fastapi.testclient import TestClient

from scrybinder.api import create_app
from scrybinder.scan import session

QUAD = np.array([[100, 50], [500, 60], [490, 700], [90, 690]], np.float32)


def frame():
    return np.full((720, 1280, 3), 90, np.uint8)


def test_a_debug_frame_has_the_whole_frame_the_outline_and_the_corners(db, tmp_path):
    s = session.Scanner(db, tmp_path / "captures", debug_dir=tmp_path / "debug")
    assert s.save_debug("manual") is None  # no camera frame yet
    path = s.save_debug("fired", frame(), QUAD)
    assert path.name.endswith("-fired.jpg") and path.parent == tmp_path / "debug"
    raw = session.cv2.imread(str(path))
    outline = session.cv2.imread(str(path).replace(".jpg", "-outline.jpg"))
    assert raw.shape == (720, 1280, 3) and outline.shape == raw.shape
    assert np.abs(outline.astype(int) - raw.astype(int)).max() > 60  # the outline is drawn on the second one only
    info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert info["reason"] == "fired" and info["shape"] == [720, 1280, 3] and info["quad"][0] == [100.0, 50.0]
    none = s.save_debug("lost", frame(), None)  # no card found: still saved, with an empty outline
    assert json.loads(none.with_suffix(".json").read_text(encoding="utf-8"))["quad"] is None


def test_only_the_latest_debug_frames_are_kept(db, tmp_path):
    s = session.Scanner(db, tmp_path / "captures", debug_dir=tmp_path / "debug")
    for i in range(s.DEBUG_KEEP + 5):
        s.save_debug(f"r{i}", frame(), QUAD)
    files = sorted(p.name for p in (tmp_path / "debug").iterdir())
    assert len(files) == 3 * s.DEBUG_KEEP  # raw, outline and json for each
    assert not any("-r0" in n or "-r4." in n for n in files) and any(n.endswith("-r34.json") for n in files)


def test_the_camera_saves_a_debug_frame_each_time_it_fires(db, tmp_path, monkeypatch):
    class Cap:
        reads = 0

        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def set(self, *a):
            pass

        def get(self, p):
            return 1280.0

        def getBackendName(self):
            return "FAKE"

        def read(self):
            Cap.reads += 1
            if Cap.reads > 2:
                s._stop.set()
            return True, frame()

        def release(self):
            pass

    class Fires:
        def __init__(self, hold=0.4):
            self.fired = False

        def update(self, quad, now, signature=None):
            return True

    s = session.Scanner(db, tmp_path / "captures", debug_dir=tmp_path / "debug")
    monkeypatch.setattr(session.cv2, "VideoCapture", Cap)
    monkeypatch.setattr(session, "find_card", lambda f: QUAD)
    monkeypatch.setattr(session, "Stability", Fires)
    monkeypatch.setattr(session, "warp_card", lambda f, q: frame())
    monkeypatch.setattr(s, "process", lambda *a, **k: None)
    s._run_webcam(0)
    names = [p.name for p in (tmp_path / "debug").glob("*-fired.jpg")]
    assert len(names) >= 1
    assert s._frame is None and s.save_debug("manual") is None  # the camera is off: nothing to save
    assert s.preview_jpeg() is None  # and no stale picture for the next start


def test_debug_frame_route(db, tmp_path):
    app = create_app(db, token="t", allowed_hosts={"testserver"})
    c = TestClient(app)
    c.get("/api/status?t=t")
    assert c.post("/api/scan/debug-frame").status_code == 409  # the camera is not running
    s = app.state.scanner
    s.debug_dir = tmp_path / "debug"
    s._frame, s._quad = frame(), QUAD
    r = c.post("/api/scan/debug-frame").json()
    assert r["path"].endswith("-manual.jpg") and r["folder"] == str(tmp_path / "debug")


def test_the_preview_is_one_jpeg_per_request_not_a_stream(db):
    app = create_app(db, token="t", allowed_hosts={"testserver"})
    c = TestClient(app)
    c.get("/api/status?t=t")
    assert c.get("/api/scan/frame").status_code == 404  # no camera picture yet
    app.state.scanner._preview = b"\xff\xd8jpeg\xff\xd9"
    r = c.get("/api/scan/frame")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    assert r.content == b"\xff\xd8jpeg\xff\xd9"
    assert c.get("/api/scan/preview").status_code in (404, 405)  # the continuous stream is gone
