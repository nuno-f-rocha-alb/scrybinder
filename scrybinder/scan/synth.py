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
