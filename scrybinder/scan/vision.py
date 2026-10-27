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


def _fit_quad(hull: np.ndarray) -> np.ndarray:
    """Convex hull → quadrilateral (tl,tr,br,bl): polygon approximation (keeps the perspective), or the minimum-area rectangle for
    rounded corners and for polygons that stray from it (an irregular outline bends them)."""
    rect = order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.035, 0.05):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            quad = order_quad(ap)
            if abs(cv2.contourArea(quad) / max(cv2.contourArea(rect), 1.0) - 1) <= 0.08:
                return quad
            break
    return rect


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
            quad = _fit_quad(hull)
            qa = cv2.contourArea(quad)
            # card aspect ratio, ~90° corners and a contour that hugs the quadrilateral (an "almost rectangular" shadow fails)
            if _aspect_ok(quad) and _rect_like(quad) and qa > 0:
                if area / qa >= 0.88:
                    best, best_area = quad, area
                elif area / qa >= 0.6 and qa > loose_area:
                    loose, loose_area = quad, qa
    best = best if best is not None else loose
    return None if best is None else best / scale


def _page_candidates(gray: np.ndarray) -> list[np.ndarray]:
    """Card-shaped quads (any number) from several masks; erosion separates cards fused through narrow gaps."""
    H, W = gray.shape
    k = np.ones((5, 5), np.uint8)
    out = []
    for mask in _candidates(gray):
        for er in (0, 2, 4):
            m = cv2.erode(mask, k, iterations=er) if er else mask
            cnts, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                area = cv2.contourArea(c)
                if not 0.006 * H * W <= area <= 0.2 * H * W:
                    continue
                if er:  # grow the eroded blob back to its real outline
                    blob = cv2.dilate(cv2.drawContours(np.zeros_like(mask), [c], -1, 255, -1), k, iterations=er)
                    c = max(cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea)
                x, y, bw, bh = cv2.boundingRect(c)
                if x <= 3 or y <= 3 or x + bw >= W - 3 or y + bh >= H - 3:
                    continue
                hull = cv2.convexHull(c)
                quad = _fit_quad(hull)
                qa = cv2.contourArea(quad)
                if qa > 0 and cv2.contourArea(hull) / qa >= 0.88 and _aspect_ok(quad) and _rect_like(quad):
                    out.append(quad)
    return out


def _consistent(quads: list[np.ndarray]) -> list[np.ndarray]:
    """The cards of one page: among the groups of quads of a similar area (±35 %), deduplicated by centre, the one that covers the
    most area. Pockets beat the art and text boxes inside them (which are many, but small)."""
    if not quads:
        return []
    areas = np.array([cv2.contourArea(q) for q in quads])
    best, best_score = [], -1.0
    for ref in range(len(quads)):
        w = np.sqrt(areas[ref] * RATIO)
        out: list[np.ndarray] = []
        for i in np.argsort(-areas):
            if abs(areas[i] / areas[ref] - 1) < 0.35 and all(np.linalg.norm(quads[i].mean(0) - o.mean(0)) > 0.5 * w for o in out):
                out.append(quads[i])
        score = sum(cv2.contourArea(q) for q in out)
        if score > best_score:
            best, best_score = out, score
    return best


def _same_size_upright(quads: list[np.ndarray]) -> list[np.ndarray]:
    """Drop what is not an upright card of the size most of them have: a block of a dark card's art and text can pass for a card
    (even lying down, as the shape test ignores orientation) but its width or height is off. The lattice then recovers that pocket."""
    if len(quads) < 3:
        return quads
    wh = np.array([((np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2,
                    (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2) for q in quads])
    mw, mh = np.median(wh, axis=0)
    keep = [q for q, (w, h) in zip(quads, wh) if w < h and abs(w / mw - 1) < 0.2 and abs(h / mh - 1) < 0.2]
    return keep if len(keep) >= 2 else quads


def _groups(vals: np.ndarray, size: float) -> list[list[int]]:
    """Indices of `vals` grouped into rows/columns: a new group starts after a gap of more than half a card."""
    order = np.argsort(vals)
    groups = [[int(order[0])]]
    for a, b in zip(order, order[1:]):
        if vals[b] - vals[a] > 0.5 * size:
            groups.append([])
        groups[-1].append(int(b))
    return groups


def _axis(vals: np.ndarray, size: float) -> tuple[np.ndarray, float, float]:
    """Integer lattice index of every value plus (origin, pitch): the pitch is fitted when two or more rows/columns exist."""
    gs = _groups(vals, size)
    means = np.array([vals[g].mean() for g in gs])
    pitch = 1.06 * size
    idx = np.round((means - means[0]) / pitch).astype(int)
    if len(set(idx)) >= 2:
        pitch, _ = np.polyfit(idx, means, 1)
    idx = np.round((means - means[0]) / pitch).astype(int)
    origin = means[0] - idx[0] * pitch
    out = np.zeros(len(vals), int)
    for g, i in zip(gs, idx):
        out[g] = i
    return out, float(origin), float(pitch)


def _card_present(frame: np.ndarray, quad: np.ndarray, min_banding=100.0) -> bool:
    """Is there a card in this pocket? A card is banded from top to bottom (title bar, art, text box) so its rows change a lot;
    an empty pocket is dark and smooth, and a glossy one only reflects the room softly. Measured on real binder photos: cards
    >= 130 (typically 250-450), empty pockets <= 72."""
    c = quad.mean(0)
    patch = cv2.resize(warp_card(frame, c + (quad - c) * 0.9), (315, 440), interpolation=cv2.INTER_AREA)
    rows = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)[:, 40:-40].mean(1)
    return float(np.abs(np.diff(cv2.GaussianBlur(rows[:, None], (1, 0), 3)[:, 0])).sum()) >= min_banding


def _clean_cells(frame: np.ndarray) -> tuple[np.ndarray, float, list[np.ndarray]]:
    """(gray image, scale, the card-shaped contours of the same size that are really in the photo, not recovered from the lattice)."""
    h, w = frame.shape[:2]
    scale = 1000 / max(h, w) if max(h, w) > 1000 else 1.0
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    # a card or pocket never takes more than a fifth of a page photo: the page itself (card-shaped, too) is not one of them
    found = _consistent([q for q in _page_candidates(gray) if cv2.contourArea(q) <= 0.2 * gray.shape[0] * gray.shape[1]])
    return gray, scale, _same_size_upright(found)


MIN_PAGE_CELLS = 4  # a binder page shows at least this many cards with a clean outline (4-9 measured); a fan only its top cards (2-3), a single card 0-2


def clean_cell_count(frame: np.ndarray) -> int:
    """Whole card outlines in a photo. Cards that cover each other give few (the page detector then invents the rest of the lattice)."""
    return len(_clean_cells(frame)[2])


def find_cards(frame: np.ndarray, max_cards=9) -> list[np.ndarray]:
    """Quadrilaterals (tl,tr,br,bl, frame coordinates) of the cards on a binder page, row by row. The cards found fix a
    3x3 lattice; the cells with no clean contour (touching borders, glare) are recovered from it. Empty pockets give no card."""
    gray, scale, found = _clean_cells(frame)
    if len(found) < 2:  # one card (or none): not a page, same detector as the single-card scan
        one = find_card(frame)
        return [] if one is None else [one]
    ref = max(found, key=cv2.contourArea)
    cw = float((np.linalg.norm(ref[1] - ref[0]) + np.linalg.norm(ref[2] - ref[3])) / 2)
    ch = float((np.linalg.norm(ref[3] - ref[0]) + np.linalg.norm(ref[2] - ref[1])) / 2)
    if cw > ch:
        cw, ch = ch, cw
    tops = [np.arctan2(*(q[1] - q[0])[::-1]) for q in found]
    th = float(np.median(np.where(np.abs(tops) > np.pi / 4, np.array(tops) - np.sign(tops) * np.pi / 2, tops)))
    Rm = np.array([[np.cos(th), np.sin(th)], [-np.sin(th), np.cos(th)]])  # frame → page axes
    cen = np.array([q.mean(0) for q in found]) @ Rm.T
    ci, x0, px = _axis(cen[:, 0], cw)
    ri, y0, py = _axis(cen[:, 1], ch)
    cells: dict[tuple[int, int], np.ndarray] = {}
    for q, i, j in zip(found, ci, ri):
        if (i, j) not in cells or cv2.contourArea(q) > cv2.contourArea(cells[(i, j)]):
            cells[(i, j)] = q
    gh, gw = gray.shape

    def recover(i, j):
        near = min(cells, key=lambda k: abs(k[0] - i) + abs(k[1] - j))
        q = cells[near]
        shift = (np.array([x0 + i * px, y0 + j * py]) - np.array([x0 + near[0] * px, y0 + near[1] * py])) @ Rm
        q = q + shift
        if q[:, 0].min() < 3 or q[:, 1].min() < 3 or q[:, 0].max() > gw - 3 or q[:, 1].max() > gh - 3:
            return None
        return q
    seen: dict[tuple[int, int], bool] = {}

    def present(key, q):
        if key not in seen:
            seen[key] = _card_present(frame, q / scale)
        return seen[key]
    ci_min, ci_max, ri_min, ri_max = min(ci), max(ci), min(ri), max(ri)
    best = None
    for a in range(min(ci_max - 2, ci_min), max(ci_min, ci_max - 2) + 1):  # 3-wide windows that hold the cards found
        for b in range(min(ri_max - 2, ri_min), max(ri_min, ri_max - 2) + 1):
            got = {(i, j): cells[(i, j)] if (i, j) in cells else recover(i, j) for i in range(a, a + 3) for j in range(b, b + 3)}
            got = {k: v for k, v in got.items() if v is not None and present(k, v)}
            if best is None or len(got) > len(best):
                best = got
    ordered = [best[k] for k in sorted(best, key=lambda k: (k[1], k[0]))]
    return [q / scale for q in ordered[:max_cards]]


def _edge_lines(img: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """Near-vertical straight lines (centre, unit direction pointing down, length): LSD segments of every colour channel
    (neighbouring cards often differ in hue and not in brightness), the collinear ones merged."""
    H, W = img.shape[:2]
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    chans = list(cv2.split(img)) if img.ndim == 3 else [img]
    found = [lsd.detect(cv2.GaussianBlur(c, (3, 3), 0))[0] for c in chans + ([cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)] if img.ndim == 3 else [])]
    items = []
    for x1, y1, x2, y2 in np.concatenate([f.reshape(-1, 4) for f in found if f is not None] or [np.zeros((0, 4), np.float32)]):
        if y2 < y1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        L = float(np.hypot(x2 - x1, y2 - y1))
        if L >= 0.03 * max(H, W) and abs(np.degrees(np.arctan2(x2 - x1, y2 - y1))) <= 20:
            items.append((L, np.array([[x1, y1], [x2, y2]], np.float32)))
    items.sort(key=lambda t: -t[0])
    clusters: list[list[np.ndarray]] = []
    fits: list[tuple[np.ndarray, np.ndarray, float, float]] = []  # centre, direction, min and max position along it
    gap = 0.02 * max(H, W)
    for _, pts in items:
        mid, d = pts.mean(0), pts[1] - pts[0]
        d /= np.linalg.norm(d)
        for k, (c, u, lo, hi) in enumerate(fits):
            t = [float((p - c) @ u) for p in pts]
            if (abs(d @ u) > np.cos(np.radians(5)) and abs(float((mid - c) @ np.array([u[1], -u[0]]))) <= 0.004 * max(H, W)
                    and min(t) <= hi + gap and max(t) >= lo - gap):
                clusters[k].append(pts)
                allp = np.concatenate(clusters[k])
                vx, vy, x0, y0 = cv2.fitLine(allp, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
                u2 = np.array([vx, vy]) * (1 if vy >= 0 else -1)
                c2 = np.array([x0, y0])
                ts = (allp - c2) @ u2
                fits[k] = (c2, u2, float(ts.min()), float(ts.max()))
                break
        else:
            clusters.append([pts])
            fits.append((mid, d, float(min((p - mid) @ d for p in pts)), float(max((p - mid) @ d for p in pts))))
    return [(c + u * (lo + hi) / 2, u, hi - lo) for c, u, lo, hi in fits]


def _e_candidates(lines, size: int) -> list[float]:
    """Likely edge lengths: the lengths many lines share (the most numerous and longest first), at least 15 % apart."""
    lens = np.array([L for _, _, L in lines])
    scored = []
    for L in lens:
        near = lens[np.abs(lens / L - 1) < 0.12]
        if len(near) >= 2 and L >= 0.05 * size:
            scored.append((len(near) * L ** 3, float(np.percentile(near, 75))))
    out: list[float] = []
    for _, e in sorted(scored, reverse=True):
        if all(abs(e / o - 1) > 0.15 for o in out):
            out.append(e)
    return out[:3]


def card_height(img: np.ndarray) -> float:
    """Height of a card in the photo, in pixels: the long straight edges that many cards share (the largest length that
    still repeats: the shorter ones are the frames inside the border). A quarter of the photo when nothing repeats."""
    s = 1000 / max(img.shape[:2])
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
    es = _e_candidates(_edge_lines(small), 1000)
    return (max(es) if es else 0.25 * 1000) / min(s, 1.0)


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


SIG_W, SIG_H = 32, 44
SWAP_DIFF = 0.35  # mean difference of two signatures; measured on real frames: the same card 0.10, different cards 0.60 to 0.95


def card_signature(frame: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """A tiny normalised picture of what is inside the outline (grey, 32x44, zero mean and unit variance): two views of the same card
    are close whatever the light, two different cards are far apart. Used to tell a swapped card from the same one."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    dst = np.array([[0, 0], [SIG_W - 1, 0], [SIG_W - 1, SIG_H - 1], [0, SIG_H - 1]], np.float32)
    small = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(np.asarray(quad, np.float32), dst), (SIG_W, SIG_H), flags=cv2.INTER_AREA)
    small = small.astype(np.float32)
    return (small - small.mean()) / (small.std() + 1e-3)


class Stability:
    """Fires once when the quadrilateral stays still for `hold` s. It re-arms when the card leaves for `gap` s, or when the outline now
    has the size of the captured card and holds a different picture (a card swapped in the same place or without leaving the view).
    An outline of another size is the detector changing its mind (the text box, the lower half of the same card), not a new card."""

    def __init__(self, hold=0.4, tol=6.0, gap=0.8):
        self.hold, self.tol, self.gap = hold, tol, gap
        self.anchor = None      # reference position while still
        self.since = None       # since when it has been still
        self.fired = False      # this card was already captured
        self.fired_area = 0.0   # the area of the quadrilateral that was captured: every card has the same size
        self.fired_sig = None   # what was inside it (card_signature)
        self.new_sig = None     # a different picture seen in the same place, and since when: it must stop changing before it counts
        self.new_since = None
        self.lost_at = None     # since when there has been no card

    def update(self, quad, now: float, signature=None) -> bool:
        """`signature` is a function returning card_signature of the current outline (computed only when it is needed)."""
        if quad is None:
            self.anchor = self.since = None
            self.lost_at = self.lost_at if self.lost_at is not None else now
            if self.fired and now - self.lost_at >= self.gap:
                self.fired = False  # the card left: ready for the next one
            return False
        self.lost_at = None
        d = float("inf") if self.anchor is None else float(np.abs(quad - self.anchor).max())
        if d > self.tol:
            if 40 < d < float("inf") and 0.75 <= float(cv2.contourArea(quad)) / max(self.fired_area, 1.0) <= 1.33:
                self.fired = False  # big jump to a card-sized quadrilateral without the card leaving the field = card swapped
            self.anchor, self.since = quad.copy(), now
            return False
        area = float(cv2.contourArea(quad))
        if self.fired and signature is not None and self.fired_sig is not None and 0.75 <= area / max(self.fired_area, 1.0) <= 1.33:
            sig = signature()
            if float(np.abs(sig - self.fired_sig).mean()) <= SWAP_DIFF:
                self.new_sig = self.new_since = None  # still the card that was captured
            elif self.new_sig is None or float(np.abs(sig - self.new_sig).mean()) > SWAP_DIFF / 2:
                self.new_sig, self.new_since = sig, now  # another picture, still changing (a hand, a card sliding in): wait
            elif now - self.new_since >= self.hold:
                self.fired = False  # the same place and size, another picture, and it stopped: the card was swapped without a gap
        if not self.fired and now - self.since >= self.hold:
            self.fired, self.fired_area = True, area
            self.fired_sig = signature() if signature is not None else None
            self.new_sig = self.new_since = None
            return True
        return False
