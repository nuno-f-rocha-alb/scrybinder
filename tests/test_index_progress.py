import cv2
import numpy as np

from scrybinder.scan import index as ixmod


class FakeEmbedder:
    """Computes nothing but reports like the real one: `progress(done, total)` after every batch of 2."""
    model_id, dim = "fake", 4

    def __init__(self, stop_after=None):
        self.calls, self.stop_after = 0, stop_after

    def _run(self, n, progress):
        for done in range(0, n, 2):
            self.calls += 1
            if progress and progress(min(done + 2, n), n):
                raise ixmod.Stopped()
        return np.ones((n, 4), np.float32)

    def cards(self, cards, progress=None):
        return self._run(len(cards), progress)

    def arts(self, cards, boxes, progress=None):
        return self._run(len(cards), progress)


def _setup(tmp_path, monkeypatch, n=5):
    monkeypatch.setattr(ixmod, "DATA_DIR", tmp_path)
    (tmp_path / "images" / "normal").mkdir(parents=True)
    d = tmp_path / "index" / "fake"
    rdb = ixmod._rows_db(d)
    for i in range(n):  # the images are in the cache already: nothing is downloaded
        cv2.imwrite(str(tmp_path / "images" / "normal" / f"c{i}.jpg"), np.full((88, 63, 3), 120 + i, np.uint8))
        rdb.execute("INSERT INTO rows (row, card_id, face, illustration_id, box, url) VALUES (?,?,?,?,?,?)", (i + 1, f"c{i}", 0, None, "2015", "http://x/y.jpg"))
    rdb.commit()
    rdb.close()
    return d


def test_progress_covers_downloads_and_vectors_and_never_goes_back(tmp_path, monkeypatch):
    d = _setup(tmp_path, monkeypatch)
    seen, notes = [], []
    res = ixmod.build(FakeEmbedder(), d, progress=lambda i, t: seen.append((i, t)), detail=notes.append)
    assert res["indexed"] == 5 and "stopped" not in res
    assert [a for a, _ in seen] == sorted(a for a, _ in seen) and seen[-1] == (5, 5)          # monotonic, ends complete
    assert any("downloading images" in n for n in notes) and any("computing vectors" in n for n in notes)


def test_stop_works_while_vectors_are_computed(tmp_path, monkeypatch):
    d = _setup(tmp_path, monkeypatch)
    emb = FakeEmbedder()
    res = ixmod.build(emb, d, should_stop=lambda: emb.calls >= 1)                              # stop right after the first batch of vectors
    assert res["stopped"] is True and res["indexed"] == 0
    assert not list(d.glob("card_*.npy"))                                                      # the unfinished block is not kept
    assert (tmp_path / "images" / "normal" / "c0.jpg").exists()                                # the images stay for the next run
