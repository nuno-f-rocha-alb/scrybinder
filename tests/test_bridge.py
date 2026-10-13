"""The native Save dialog behind CSV export (pywebview bridge)."""
import sys
import types

from scrybinder.app import Bridge


def _fake_webview(monkeypatch, answer):
    seen = {}

    class Win:
        def create_file_dialog(self, kind, save_filename="", file_types=()):
            seen["name"] = save_filename
            return answer

    mod = types.SimpleNamespace(windows=[Win()], FileDialog=types.SimpleNamespace(SAVE="save"))
    monkeypatch.setitem(sys.modules, "webview", mod)
    return seen


def test_save_csv_writes_exact_text(tmp_path, monkeypatch):
    target = tmp_path / "out.csv"
    seen = _fake_webview(monkeypatch, str(target))
    text = "a,b\r\n1,é\r\n"
    assert Bridge().save_csv("../x/scrybinder-cardmarket.csv", text) == str(target)
    assert seen["name"] == "scrybinder-cardmarket.csv"  # directory part stripped
    assert target.read_bytes() == text.encode("utf-8")  # no newline translation


def test_save_csv_cancelled_writes_nothing(tmp_path, monkeypatch):
    _fake_webview(monkeypatch, None)
    assert Bridge().save_csv("x.csv", "data") is None


def test_save_text_writes_a_deck_list(tmp_path, monkeypatch):
    target = tmp_path / "deck.txt"
    seen = _fake_webview(monkeypatch, [str(target)])  # some versions answer with a list
    assert Bridge().save_text("../x/deck.txt", "Deck\n1 Sol Ring\n") == str(target)
    assert seen["name"] == "deck.txt" and target.read_bytes() == b"Deck\n1 Sol Ring\n"
