"""Cards that overlap in a photo (fans, columns): each one is found by its title, read with Windows' own text recognition, and
confirmed by matching the picture around the title with the images of the printings of that name (which also picks the printing).
The titles are the part of a card that always shows; the names are a closed list, so a half-read title is enough."""
import base64
import logging
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from .index import _img_file
from .vision import RATIO, card_height

log = logging.getLogger("scrybinder.scan")

# the type line ("Legendary Creature —", "Instant"): never a title, though some cards are named like a type ("Creature Bond")
TYPE_LINE = re.compile(r"^(?:(?:legendary|basic|snow|tribal|kindred|artifact|enchantment|creature|land)\s+)*"
                       r"(?:creature|instant|sorcery|enchantment|artifact|land|planeswalker|battle)\b\s*(?:[\u2014\u2013:.\-]|$)", re.I)
MAX_PRINTS = 250  # printings compared per title
MIN_INLIERS = 20  # matching points that count as "this printing is there" (wrong printings reach ~15)
STRONG_INLIERS = 40
_feats: dict[str, tuple] = {}

_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:SCRYBINDER_OCR_IMG)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $eng) { exit 1 }
$res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
foreach ($l in $res.Lines) {
    $ws = $l.Words
    $x = ($ws | ForEach-Object { $_.BoundingRect.X } | Measure-Object -Minimum).Minimum
    $y = ($ws | ForEach-Object { $_.BoundingRect.Y } | Measure-Object -Minimum).Minimum
    $x2 = ($ws | ForEach-Object { $_.BoundingRect.X + $_.BoundingRect.Width } | Measure-Object -Maximum).Maximum
    $h = ($ws | ForEach-Object { $_.BoundingRect.Height } | Measure-Object -Maximum).Maximum
    "{0}`t{1}`t{2}`t{3}`t{4}" -f [int]$x, [int]$y, [int]($x2 - $x), [int]$h, $l.Text
}
"""


class OcrError(RuntimeError):
    """The text recognition of Windows cannot run (no PowerShell, or no language it supports is installed)."""


def available() -> bool:
    return sys.platform == "win32"


def ocr_lines(img: np.ndarray, scale: float = 1.0) -> list[tuple[str, float, float, float, float]]:
    """Lines of text in the photo: (text, x, y, width, height) in its pixels. Raises OcrError when the recognition cannot run."""
    if not available():
        return []
    if max(img.shape[:2]) * scale > 9000:  # the recogniser's limit is 10000 px
        return []
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else img
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imwrite(path, big)
        enc = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode()
        run = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                             env={**os.environ, "SCRYBINDER_OCR_IMG": path}, capture_output=True, timeout=120,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Text recognition failed: %r", e)
        raise OcrError(str(e)) from e
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if run.returncode != 0 and not run.stdout:
        log.warning("Text recognition failed: %s", run.stderr.decode("utf-8", "replace")[:300])
        raise OcrError("no text recognition language installed in Windows")
    lines = []
    for ln in run.stdout.decode("utf-8", "replace").splitlines():
        p = ln.split("\t")
        if len(p) == 5:
            try:
                lines.append((p[4], int(p[0]) / scale, int(p[1]) / scale, int(p[2]) / scale, int(p[3]) / scale))
            except ValueError:
                pass
    return lines


def _features(card_id: str):
    got = _feats.get(card_id)
    if got is None:  # compared from several threads: a value is kept in a local, another thread may clear the cache meanwhile
        im = cv2.imread(str(_img_file(card_id, 0)), cv2.IMREAD_GRAYSCALE)
        got = (None, None) if im is None else cv2.SIFT_create(nfeatures=1500).detectAndCompute(
            cv2.resize(im, (630, 880), interpolation=cv2.INTER_AREA), None)
        if len(_feats) > 600:
            _feats.clear()
        _feats[card_id] = got
    return got


def _match(kq, dq, card_id: str) -> tuple[int, np.ndarray | None]:
    """Points of the photo's crop that agree on one placement (rotation, scale, shift) on the printing's image, and that placement."""
    kc, dc = _features(card_id)
    if dc is None or len(kc) < 8:
        return 0, None
    ms = [m for m, n in (p for p in cv2.BFMatcher().knnMatch(dq, dc, k=2) if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(ms) < 6:
        return 0, None
    src = np.float32([kq[m.queryIdx].pt for m in ms])
    dst = np.float32([kc[m.trainIdx].pt for m in ms])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=6)
    if M is None or inl is None or not 0.4 < float(np.hypot(M[0, 0], M[1, 0])) < 5:  # all the points collapsed onto one: not a placement
        return 0, None
    return int(inl.sum()), M


def find_cards(img: np.ndarray, ident, lines=None) -> list[dict]:
    """The cards of the photo, one per title found: {name, text, similarity, whole, x, y, box, inliers, verified, prints}. `prints` are the
    printings of the name (the one the picture agrees with first). `lines` is for tests."""
    ch = card_height(img)
    cw = ch * RATIO
    if lines is None:
        seen: dict = {}
        with ThreadPoolExecutor(3) as ex:  # larger passes read the small titles the first one misses
            for found_lines in ex.map(lambda sc: ocr_lines(img, sc), (1, 2, 3)):
                for ln in found_lines:
                    seen[(round(ln[1] / 25), round(ln[2] / 25), ln[0])] = ln
        lines = list(seen.values())
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    sift = cv2.SIFT_create(nfeatures=1500)
    found = []
    for text, x, y, w, h in lines:
        if TYPE_LINE.match(text.strip()):
            continue
        names = ident.title_names(text, limit=30)
        if not names:
            continue
        name, sim, whole = names[0]
        x0, y0 = int(max(0, x - 0.1 * cw)), int(max(0, y - 0.1 * ch))
        x1, y1 = int(min(img.shape[1], x + 1.1 * cw)), int(min(img.shape[0], y + 1.05 * ch))
        prints = [p for n, _, _ in names for p in ident.prints([n])][:600]
        pool = [p["id"] for p in prints if _img_file(p["id"], 0).exists()][:MAX_PRINTS]
        kq, dq = sift.detectAndCompute(gray[y0:y1, x0:x1], None) if x1 - x0 > 30 and y1 - y0 > 30 else (None, None)
        best, inl, M = None, 0, None
        if pool and dq is not None and len(kq) >= 8:
            with ThreadPoolExecutor(8) as ex:
                res = list(ex.map(lambda cid: _match(kq, dq, cid), pool))
            j = max(range(len(pool)), key=lambda i: res[i][0])
            inl, M = res[j]
            best = pool[j] if inl >= MIN_INLIERS else None
        geo = False
        if M is not None and inl >= MIN_INLIERS + 2:  # where this printing has its title, seen through that placement, is where the line is
            p = M @ np.array([x - x0, y + h / 2 - y0, 1.0])
            geo = abs(p[0] - 70) < 120 and abs(p[1] - 75) < 70
        verified = geo or inl >= STRONG_INLIERS
        ok = verified or (whole >= 0.85 and sim >= 88 and len(name) >= 6)
        if not ok:
            continue
        order = ([p for p in prints if p["id"] == best] + [p for p in prints if p["id"] != best]) if best else prints
        if best:  # the picture decides between names that start alike ("Murmuring Mystic" and "Murmuring Bosk")
            name = order[0]["name"]
        found.append({"name": name, "text": text, "similarity": sim, "whole": whole, "x": x, "y": y, "inliers": inl, "verified": verified, "geo": geo,
                      "box": (x0, y0, x1, y1), "prints": order})
    # a card read by two lines (or two passes) counts once: the better confirmed one stays
    found.sort(key=lambda f: (f["geo"], f["verified"], f["inliers"], f["whole"]), reverse=True)
    kept: list[dict] = []
    for f in found:
        if any(abs(f["y"] - k["y"]) < 0.12 * ch and abs(f["x"] - k["x"]) < (0.3 if f["name"] == k["name"] else 0.15) * cw for k in kept):
            continue
        # text that sits inside a confirmed card, below its title, is that card's rules text, not another title
        if not f["geo"] and any(k["geo"] and 0 <= f["x"] - k["x"] < cw and 0.15 * ch < f["y"] - k["y"] < ch for k in kept):
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: (round(f["y"] / (0.5 * ch)), f["x"]))
