"""Vision: find the card in a frame, correct the perspective and decide when the image is stable."""
import cv2
import numpy as np

CARD_W, CARD_H = 630, 880  # 63x88 mm a 10 px/mm
RATIO = 63 / 88


def order_quad(pts) -> np.ndarray:
    """tl, tr, br, bl."""
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s, d = p.sum(1), np.diff(p, axis=1).ravel()
    return np.array([p[s.argmin()], p[d.argmin()], p[s.argmax()], p[d.argmax()]], dtype=np.float32)


def _aspect_ok(q: np.ndarray, tol=0.14) -> bool:
    w = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    if min(w, h) < 1:
        return False
    r = min(w, h) / max(w, h)
    return abs(r - RATIO) < tol


def _candidates(gray: np.ndarray):
    """Binary masks from several methods: every setup has a different background."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    k = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(cv2.Canny(blur, 40, 120), k, iterations=2)
    yield cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k, iterations=2)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu
    yield 255 - otsu


def _rect_like(q: np.ndarray, lo=62.0, hi=118.0) -> bool:
    """All interior angles close to 90° (the perspective of an overhead stand does not distort them much)."""
    for i in range(4):
        a, b = q[i - 1] - q[i], q[(i + 1) % 4] - q[i]
        cosv = float(a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
        if not lo <= np.degrees(np.arccos(np.clip(cosv, -1, 1))) <= hi:
            return False
    return True


def find_card(frame: np.ndarray, min_area_frac=0.04) -> np.ndarray | None:
    """Quadrilateral (tl,tr,br,bl) of the largest card-shaped contour, in frame coordinates; or None."""
    h, w = frame.shape[:2]
    scale = 720 / max(h, w) if max(h, w) > 720 else 1.0  # ponytail: detection at ≤720 px; the final capture uses the original frame
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    area_min = min_area_frac * gray.shape[0] * gray.shape[1]
    best, best_area = None, 0.0
    loose, loose_area = None, 0.0  # 2nd resort: incomplete contour (glare/foil breaks the mask), only if nothing passes at 0.88
    for mask in _candidates(gray):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:4]:
            area = cv2.contourArea(c)
            x, y, bw, bh = cv2.boundingRect(c)
            m = 3  # the card is fully inside the frame: shapes touching the edges are shadows/background, not the card
            if x <= m or y <= m or x + bw >= gray.shape[1] - m or y + bh >= gray.shape[0] - m:
                continue
            if area < area_min or area <= best_area:
                continue
            hull = cv2.convexHull(c)
            peri = cv2.arcLength(hull, True)
            quad = None
            for eps in (0.02, 0.035, 0.05):
                ap = cv2.approxPolyDP(hull, eps * peri, True)
                if len(ap) == 4:
                    quad = order_quad(ap)
                    break
            if quad is None:  # rounded corners: minimum-area rectangle
                quad = order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
            qa = cv2.contourArea(quad)
            # card aspect ratio, ~90° corners and a contour that hugs the quadrilateral (an "almost rectangular" shadow fails)
            if _aspect_ok(quad) and _rect_like(quad) and qa > 0:
                if area / qa >= 0.88:
                    best, best_area = quad, area
                elif area / qa >= 0.6 and qa > loose_area:
                    loose, loose_area = quad, qa
    best = best if best is not None else loose
    return None if best is None else best / scale


def warp_card(frame: np.ndarray, quad: np.ndarray) -> np.ndarray:
    q = order_quad(quad)
    w = np.linalg.norm(q[1] - q[0])
    h = np.linalg.norm(q[3] - q[0])
    if w > h:  # card lying down: rotate the corner order so it ends up upright
        q = np.roll(q, -1, axis=0)
    dst = np.array([[0, 0], [CARD_W - 1, 0], [CARD_W - 1, CARD_H - 1], [0, CARD_H - 1]], dtype=np.float32)
    return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(q, dst), (CARD_W, CARD_H), flags=cv2.INTER_CUBIC)


def inner_card(card: np.ndarray) -> np.ndarray | None:
    """Card inside a toploader/sleeve: the first quadrilateral catches the outer outline. Look for another, inner one.
    Only use it when the first reading fails: on a normal card this confuses the frame with the margin."""
    inner = find_card(card, min_area_frac=0.35)
    if inner is None or cv2.contourArea(inner) < 0.45 * CARD_W * CARD_H:
        return None
    return warp_card(card, inner)


def card_from_photo(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Photo → rectified card. (image, detection_ok). Without detection, assumes the photo is already just the card."""
    quad = find_card(img)
    if quad is not None:
        return warp_card(img, quad), True
    h, w = img.shape[:2]
    if h < w:  # no contour and landscape: assume it is rotated 90°
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return cv2.resize(img, (CARD_W, CARD_H), interpolation=cv2.INTER_CUBIC), False


class Stability:
    """Fires once when the quadrilateral stays still for `hold` s; re-arms only when the card leaves or moves a lot."""

    def __init__(self, hold=0.4, tol=6.0, gap=0.5):
        self.hold, self.tol, self.gap = hold, tol, gap
        self.anchor = None      # reference position while still
        self.since = None       # since when it has been still
        self.fired = False      # this card was already captured
        self.lost_at = None     # since when there has been no card

    def update(self, quad, now: float) -> bool:
        if quad is None:
            self.anchor = self.since = None
            self.lost_at = self.lost_at if self.lost_at is not None else now
            if self.fired and now - self.lost_at >= self.gap:
                self.fired = False  # the card left: ready for the next one
            return False
        self.lost_at = None
        d = float("inf") if self.anchor is None else float(np.abs(quad - self.anchor).max())
        if d > self.tol:
            if 40 < d < float("inf"):
                self.fired = False  # big jump without the card leaving the field = card swapped
            self.anchor, self.since = quad.copy(), now
            return False
        if not self.fired and now - self.since >= self.hold:
            self.fired = True
            return True
        return False
