"""Generate the bundled `Image Not Available` placeholder PNG.

Run once at build time (or whenever you want to refresh the asset):

    uv run python -m lmfetch.assets.generate_placeholder

This is intentionally a script, not a runtime fallback — the PNG it produces
is checked into the repo so that lmfetch can serve it without a Pillow render
step on every miss.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(out_path: Path, *, size: tuple[int, int] = (512, 512)) -> None:
    img = Image.new("RGB", size, color=(32, 32, 32))
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    title = "Image Not Available"
    subtitle = "served by lmfetch"

    w, h = size
    tb = draw.textbbox((0, 0), title, font=font_large)
    sb = draw.textbbox((0, 0), subtitle, font=font_small)

    draw.text(
        ((w - (tb[2] - tb[0])) / 2, (h - (tb[3] - tb[1])) / 2 - 24),
        title,
        fill=(220, 220, 220),
        font=font_large,
    )
    draw.text(
        ((w - (sb[2] - sb[0])) / 2, (h - (sb[3] - sb[1])) / 2 + 28),
        subtitle,
        fill=(160, 160, 160),
        font=font_small,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)


if __name__ == "__main__":
    target = Path(__file__).parent / "not_available.png"
    render(target)
    print(f"wrote {target} ({target.stat().st_size} bytes)")
