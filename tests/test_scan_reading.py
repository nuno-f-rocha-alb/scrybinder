import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scrybinder.api import create_app
from scrybinder.scan import session

QUAD = np.array([[100, 50], [500, 60], [490, 700], [90, 690]], np.float32)
RES = {"ocr": {"name": "x", "name_match": 100, "number": None, "set": None, "rotated": False}, "candidates": [{"id": "A"}], "confidence": "high"}


def card():
    return np.zeros((880, 630, 3), np.uint8)


def drain(s):
    s._reader.submit(lambda: None).result(timeout=10)  # the reads run in order on one thread: when this one runs, the earlier ones are done


def test_a_capture_is_in_the_list_while_it_is_read_and_becomes_the_entry(db, tmp_path, monkeypatch):
    s = session.Scanner(db, tmp_path)
    s.list_mode = True
    started, release = threading.Event(), threading.Event()

    def slow(ident, img, warped=False):
        started.set()
        assert release.wait(10)
        return img, True, dict(RES)

    monkeypatch.setattr(session, "identify_image", slow)
    s.capture(card(), "webcam", True)
    assert started.wait(10)
    st = s.state()
    assert [r["label"] for r in st["reading"]] == ["webcam"] and st["reads"] == [] and st["beep"] == 1  # shown and beeped before the read ends
    sid = st["reading"][0]["id"]
    assert (tmp_path / f"{sid}.jpg").exists()  # the thumbnail is there from the start
    release.set()
    drain(s)
    st = s.state()
    assert st["reading"] == [] and [r["id"] for r in st["reads"]] == [sid] and st["beep"] == 1  # one entry, one beep


def test_a_read_that_adds_to_the_previous_card_leaves_no_row_behind(db, tmp_path, monkeypatch):
    s = session.Scanner(db, tmp_path)
    s.list_mode = True
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(RES)))
    s.capture(card(), "webcam", False)
    s.capture(card(), "webcam", False)
    drain(s)
    st = s.state()
    assert st["reading"] == [] and [r["qty"] for r in st["reads"]] == [2]
    assert len(list(tmp_path.glob("*.jpg"))) == 1  # the capture that was only a copy is not kept


def test_a_read_that_fails_says_so_and_leaves_no_row(db, tmp_path, monkeypatch):
    s = session.Scanner(db, tmp_path)

    def boom(ident, img, warped=False):
        raise RuntimeError("ocr died")

    monkeypatch.setattr(session, "identify_image", boom)
    s.capture(card(), "webcam", True)
    drain(s)
    st = s.state()
    assert st["reading"] == [] and "could not be read" in st["notice"] and not list(tmp_path.glob("*.jpg"))


def test_confirm_mode_reads_fill_the_queue_too(db, tmp_path, monkeypatch):
    s = session.Scanner(db, tmp_path)
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(RES)))
    s.capture(card(), "webcam", True)
    drain(s)
    st = s.state()
    assert st["reading"] == [] and len(st["pending"]) == 1 and st["beep"] == 1


def test_scan_now_needs_a_camera_picture_and_counts_as_a_new_copy(db, tmp_path, monkeypatch):
    s = session.Scanner(db, tmp_path)
    s.list_mode = True
    with pytest.raises(ValueError, match="camera"):  # no picture yet
        s.force_capture()
    monkeypatch.setattr(session, "identify_image", lambda ident, i, warped=False: (i, True, dict(RES)))
    s._frame, s._quad = np.full((720, 1280, 3), 90, np.uint8), QUAD
    s.force_capture()
    s.force_capture()  # not "the card still on the stand": it adds a copy
    drain(s)
    assert [r["qty"] for r in s.state()["reads"]] == [2]
    s._quad = None  # no outline found: the card is looked for in the whole picture
    s.force_capture()
    drain(s)
    assert [r["qty"] for r in s.state()["reads"]] == [3]


def test_scan_now_route(db):
    app = create_app(db, token="t", allowed_hosts={"testserver"})
    c = TestClient(app)
    c.get("/api/status?t=t")
    r = c.post("/api/scan/force")
    assert r.status_code == 409 and "camera" in r.json()["detail"]
    assert c.get("/api/scan/state").json()["reading"] == []
