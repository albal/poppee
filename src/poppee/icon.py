"""Tray/app icon drawn at runtime, so no image assets need packaging."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

BLUE = (26, 115, 232, 255)
RED = (217, 48, 37, 255)
WHITE = (255, 255, 255, 255)
GREY = (128, 134, 139, 255)


def render_icon(count: int = 0, size: int = 64, error: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64

    body = GREY if error else BLUE
    draw.rounded_rectangle((4 * s, 14 * s, 60 * s, 52 * s), radius=6 * s, fill=body)
    draw.line(
        [(8 * s, 18 * s), (32 * s, 36 * s), (56 * s, 18 * s)],
        fill=WHITE,
        width=max(1, round(4 * s)),
        joint="curve",
    )

    if count > 0:
        text = "99+" if count > 99 else str(count)
        radius = 15 * s
        cx, cy = size - radius, radius
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=RED)
        font_size = int((18 if len(text) == 1 else 15 if len(text) == 2 else 11) * s)
        font = ImageFont.load_default(size=max(6, font_size))
        draw.text((cx, cy), text, fill=WHITE, font=font, anchor="mm")
    return img
