"""Synthetic photos: a Scryfall image warped in perspective onto a background, with blur/noise/brightness."""
import cv2
import numpy as np


def photo(card_path, seed=0, size=(1920, 1080), rot=None, bg=(38, 52, 66), noise=4, blur=1.2):
    rng = np.random.default_rng(seed)
    card = cv2.imread(str(card_path))
    h, w = card.shape[:2]
    W, H = size
    scale = rng.uniform(0.62, 0.78) * H / h  # the card takes ~70 % of the height (overhead stand)
    cw, ch = w * scale, h * scale
    cx, cy = W / 2 + rng.uniform(-80, 80), H / 2 + rng.uniform(-40, 40)
    ang = np.deg2rad(rng.uniform(-6, 6) if rot is None else rot)
    base = np.array([[-cw / 2, -ch / 2], [cw / 2, -ch / 2], [cw / 2, ch / 2], [-cw / 2, ch / 2]])
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    jit = rng.uniform(-0.012, 0.012, (4, 2)) * [cw, ch]  # leve perspetiva
    dst = (base + jit) @ R.T + [cx, cy]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst.astype(np.float32))
    img = np.full((H, W, 3), bg, np.uint8)
    grad = np.linspace(0.8, 1.15, W)[None, :, None]  # uneven lighting
    img = np.clip(img * grad, 0, 255).astype(np.uint8)
    warped = cv2.warpPerspective(card, M, (W, H), flags=cv2.INTER_AREA)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    out = np.where(mask[..., None] > 0, warped, img)
    out = cv2.GaussianBlur(out, (0, 0), blur)
    out = np.clip(out.astype(np.float32) + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    return out


def binder_page(card_paths, occupied, seed=0, size=(3000, 2250), dark=True, gap=0.05, glare=False, noise=4, blur=1.2):
    """A binder page photo: 3x3 pockets (`occupied` = 9 flags, row-major) filled from `card_paths` in order.
    Returns (image, cells) where cells = [{"index": 0..8, "path": ..., "quad": 4x2 tl,tr,br,bl in image coordinates}].
    Pockets have a plastic edge and the empty ones show a soft reflection of the room, as a real binder does.
    `dark`: black binder (usual); otherwise a light grey one. `gap`: spacing between cards as a fraction of the card width."""
    rng = np.random.default_rng(seed)
    cw, ch = 488, 680
    gx, gy = int(cw * gap), int(ch * gap)
    pad = int(cw * 0.12)
    ppad = int(cw * min(0.04, gap * 0.45))  # the pocket is a little bigger than the card
    PW, PH = 3 * cw + 2 * gx + 2 * pad, 3 * ch + 2 * gy + 2 * pad
    cover, pocket, edge = ((20, 20, 20), (46, 46, 46), (96, 96, 96)) if dark else ((200, 196, 190), (176, 174, 170), (120, 120, 120))
    page = np.full((PH, PW, 3), cover, np.uint8)
    paths = iter(card_paths)
    cells = []
    for k in range(9):
        r, c = divmod(k, 3)
        x, y = pad + c * (cw + gx), pad + r * (ch + gy)
        cv2.rectangle(page, (x - ppad, y - ppad), (x + cw + ppad, y + ch + ppad), pocket, -1)
        cv2.rectangle(page, (x - ppad, y - ppad), (x + cw + ppad, y + ch + ppad), edge, 4)
        if not occupied[k]:
            blob = np.zeros((ch + 2 * ppad, cw + 2 * ppad), np.float32)  # soft reflection on the plastic
            cv2.circle(blob, (int(rng.uniform(0.2, 0.8) * cw), int(rng.uniform(0.2, 0.8) * ch)), int(0.35 * cw), 1.0, -1)
            blob = cv2.GaussianBlur(blob, (0, 0), 0.12 * cw) * rng.uniform(15, 45)
            roi = page[y - ppad:y + ch + ppad, x - ppad:x + cw + ppad].astype(np.float32) + blob[..., None]
            page[y - ppad:y + ch + ppad, x - ppad:x + cw + ppad] = np.clip(roi, 0, 255).astype(np.uint8)
            continue
        p = next(paths)
        page[y:y + ch, x:x + cw] = cv2.resize(cv2.imread(str(p)), (cw, ch), interpolation=cv2.INTER_AREA)
        cells.append({"index": k, "path": p, "quad": np.float32([[x, y], [x + cw, y], [x + cw, y + ch], [x, y + ch]])})
    W, H = size
    s = 0.92 * min(W / PW, H / PH)
    ang = np.deg2rad(rng.uniform(-3, 3))
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    corners = np.float32([[0, 0], [PW, 0], [PW, PH], [0, PH]])
    dst = ((corners - [PW / 2, PH / 2]) * s + rng.uniform(-0.01, 0.01, (4, 2)) * [PW * s, PH * s]) @ R.T + [W / 2, H / 2]
    M = cv2.getPerspectiveTransform(corners, dst.astype(np.float32))
    desk = np.full((H, W, 3), (150, 156, 164), np.uint8)  # a desk with some texture, as in a real photo
    desk = np.clip(desk.astype(np.float32) + cv2.GaussianBlur(rng.normal(0, 30, (H, W, 1)).astype(np.float32), (0, 0), 25)[..., None].repeat(3, 2) * 1.5, 0, 255).astype(np.uint8)
    warped = cv2.warpPerspective(page, M, (W, H), flags=cv2.INTER_AREA)
    mask = cv2.warpPerspective(np.full((PH, PW), 255, np.uint8), M, (W, H))
    out = np.where(mask[..., None] > 0, warped, desk)
    if glare:  # a soft bright band across the page, like a reflection on the plastic (measured on real photos: empty pockets vary up to ~75, this adds about that)
        yy, xx = np.mgrid[0:H, 0:W]
        d = (xx * 0.6 + yy) - rng.uniform(0.9, 1.5) * H
        out = np.clip(out.astype(np.float32) + 35 * np.exp(-(d / (0.07 * H)) ** 2)[..., None], 0, 255).astype(np.uint8)
    out = cv2.GaussianBlur(out, (0, 0), blur)
    out = np.clip(out.astype(np.float32) + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    for cell in cells:
        cell["quad"] = cv2.perspectiveTransform(cell["quad"][None], M)[0]
    return out, cells
