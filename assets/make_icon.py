"""Generates the Scrybinder icon (assets/scrybinder.ico, scrybinder.png, scrybinder.svg and ui/public/favicon.svg).

Uma carta (63:88) ligeiramente inclinada, com os cantos de enquadramento do scan por cima, sobre o quadrado escuro do tema.
Uso: .venv\\Scripts\\python.exe assets\\make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
S = 1024
BG_TOP, BG_BOT = "#2a2f4d", "#0d0f14"
ACCENT, ACCENT2, GOLD = "#8b7cf6", "#4f8cff", "#e8b95f"
CARD_W, CARD_H, TILT, K = 430, 600, -8, 1.12   # 430:600 ≈ 63:88; K = scale-up


def vgrad(size, c1, c2):
    top, bot = Image.new("RGB", size, c1), Image.new("RGB", size, c2)
    return Image.composite(bot, top, Image.linear_gradient("L").resize(size))


def rounded_mask(size, r):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), r, fill=255)
    return m


def card_layer():
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0 = (S - CARD_W) // 2, (S - CARD_H) // 2
    d.rounded_rectangle((x0, y0, x0 + CARD_W, y0 + CARD_H), 46, fill="#eef0f6")
    d.rounded_rectangle((x0 + 30, y0 + 28, x0 + CARD_W - 30, y0 + 74), 14, fill="#c9cee0")        # title
    art = vgrad((CARD_W - 60, 270), ACCENT, ACCENT2)
    m = Image.new("L", art.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, art.size[0] - 1, art.size[1] - 1), 16, fill=255)
    layer.paste(art, (x0 + 30, y0 + 92), m)                                                         # arte
    for i, w in enumerate((CARD_W - 90, CARD_W - 140, CARD_W - 190)):                              # texto
        y = y0 + 392 + i * 52
        d.rounded_rectangle((x0 + 30, y, x0 + 30 + w, y + 24), 12, fill="#b9bfd1")
    big = layer.resize((int(S * K), int(S * K)), Image.LANCZOS)  # slightly larger card: reads better at 16 px
    o = (big.width - S) // 2
    return big.crop((o, o, o + S, o + S)).rotate(TILT, resample=Image.BICUBIC, center=(S // 2, S // 2))


def corners(img):
    d = ImageDraw.Draw(img)
    t, ln, lo, hi = 38, 190, 118, S - 118
    for (cx, cy, sx, sy) in ((lo, lo, 1, 1), (hi, lo, -1, 1), (lo, hi, 1, -1), (hi, hi, -1, -1)):
        for (ex, ey) in ((cx + sx * ln, cy), (cx, cy + sy * ln)):
            d.line(((cx, cy), (ex, ey)), fill=GOLD, width=t)
            d.ellipse((ex - t / 2, ey - t / 2, ex + t / 2, ey + t / 2), fill=GOLD)
        d.ellipse((cx - t / 2, cy - t / 2, cx + t / 2, cy + t / 2), fill=GOLD)


def build() -> Image.Image:
    img = vgrad((S, S), BG_TOP, BG_BOT).convert("RGBA")
    card = card_layer()
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.putalpha(card.getchannel("A").point(lambda a: int(a * 0.55)))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)), (0, 18))
    img.alpha_composite(card)
    corners(img)
    img.putalpha(rounded_mask(S, 230))
    return img


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">
<defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOT}"/></linearGradient>
<linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT2}"/></linearGradient></defs>
<rect width="{S}" height="{S}" rx="230" fill="url(#b)"/>
<g transform="rotate({-TILT} 512 512) translate(512 512) scale({K}) translate(-512 -512)"><rect x="{(S - CARD_W) // 2}" y="{(S - CARD_H) // 2}" width="{CARD_W}" height="{CARD_H}" rx="46" fill="#eef0f6"/>
<rect x="{(S - CARD_W) // 2 + 30}" y="{(S - CARD_H) // 2 + 28}" width="{CARD_W - 60}" height="46" rx="14" fill="#c9cee0"/>
<rect x="{(S - CARD_W) // 2 + 30}" y="{(S - CARD_H) // 2 + 92}" width="{CARD_W - 60}" height="270" rx="16" fill="url(#a)"/>
<g fill="#b9bfd1"><rect x="{(S - CARD_W) // 2 + 30}" y="{(S - CARD_H) // 2 + 392}" width="{CARD_W - 90}" height="24" rx="12"/>
<rect x="{(S - CARD_W) // 2 + 30}" y="{(S - CARD_H) // 2 + 444}" width="{CARD_W - 140}" height="24" rx="12"/>
<rect x="{(S - CARD_W) // 2 + 30}" y="{(S - CARD_H) // 2 + 496}" width="{CARD_W - 190}" height="24" rx="12"/></g></g>
<path d="M118 308V118H308M716 118H906V308M118 716V906H308M716 906H906V716" fill="none" stroke="{GOLD}" stroke-width="38" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

if __name__ == "__main__":
    img = build()
    img.save(HERE / "scrybinder.png")
    img.save(HERE / "scrybinder.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    (HERE / "scrybinder.svg").write_text(SVG, encoding="utf-8")
    pub = HERE.parent / "ui" / "public"
    pub.mkdir(exist_ok=True)
    (pub / "favicon.svg").write_text(SVG, encoding="utf-8")
    print("ok")
