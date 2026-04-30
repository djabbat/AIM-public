"""scripts/desktop/build_icons.py — generate AIM launcher icons in PNG/ICO format.

Produces two icon families, each at 16/32/64/128/256/512:
    aim_<size>.png       — full AIM (medical cross + ring)
    aim_ai_<size>.png    — AIM AI assistant (brain + spark)
plus combined .ico bundles for Windows (aim.ico, aim_ai.ico).

macOS .icns bundles are produced by install_icons_mac.sh on the user's Mac
(via iconutil; not available on Linux/Win). This script writes the source
PNGs that iconutil consumes.

Pure Pillow — no cairosvg / Inkscape / external rasterizer.

Usage:
    python3 scripts/desktop/build_icons.py [out_dir]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 32, 64, 128, 256, 512]


def _circle_bg(size: int, color: tuple, ring_color: tuple,
               ring_thickness: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 32)
    d.ellipse((pad, pad, size - pad, size - pad), fill=color)
    if ring_thickness > 0:
        d.ellipse((pad, pad, size - pad, size - pad),
                  outline=ring_color, width=ring_thickness)
    return img


def _aim_icon(size: int) -> Image.Image:
    """AIM: medical green disc + white cross + thin gold ring."""
    img = _circle_bg(size,
                     color=(31, 78, 89, 255),       # deep teal
                     ring_color=(244, 196, 48, 255), # gold ring
                     ring_thickness=max(2, size // 32))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    arm = size * 0.28      # half-length of cross arm
    thick = size * 0.10    # cross arm thickness
    # vertical bar
    d.rectangle((cx - thick, cy - arm, cx + thick, cy + arm),
                fill=(255, 255, 255, 255))
    # horizontal bar
    d.rectangle((cx - arm, cy - thick, cx + arm, cy + thick),
                fill=(255, 255, 255, 255))
    return img


def _aim_ai_icon(size: int) -> Image.Image:
    """AIM AI: deep purple disc + neural-net silhouette + spark."""
    img = _circle_bg(size,
                     color=(40, 32, 90, 255),         # deep indigo
                     ring_color=(120, 200, 255, 255),  # ice-blue ring
                     ring_thickness=max(2, size // 32))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2

    # Three nodes (input / hidden / output) with connecting edges → suggests an MLP
    r = max(2, size // 18)        # node radius
    nx = size * 0.25              # input column x
    mx = size * 0.50              # hidden column x
    ox = size * 0.75              # output column x
    rows_in  = [cy - size * 0.18, cy + size * 0.18]
    rows_mid = [cy - size * 0.20, cy, cy + size * 0.20]
    rows_out = [cy - size * 0.10, cy + size * 0.10]

    edge_color = (180, 220, 255, 200)
    edge_w = max(1, size // 96)

    # edges: input → hidden
    for yi in rows_in:
        for ym in rows_mid:
            d.line((nx, yi, mx, ym), fill=edge_color, width=edge_w)
    # edges: hidden → output
    for ym in rows_mid:
        for yo in rows_out:
            d.line((mx, ym, ox, yo), fill=edge_color, width=edge_w)

    # nodes
    node_fill = (255, 255, 255, 255)
    accent    = (244, 196, 48, 255)   # gold
    for x, ys in [(nx, rows_in), (mx, rows_mid), (ox, rows_out)]:
        for y in ys:
            d.ellipse((x - r, y - r, x + r, y + r), fill=node_fill)

    # spark / lightning bolt overlay (gold, top-right) — small badge
    bolt = [
        (size * 0.74, size * 0.18),
        (size * 0.62, size * 0.42),
        (size * 0.70, size * 0.42),
        (size * 0.62, size * 0.66),
        (size * 0.86, size * 0.36),
        (size * 0.76, size * 0.36),
        (size * 0.85, size * 0.18),
    ]
    d.polygon(bolt, fill=accent)
    return img


def _save_set(builder, prefix: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pngs: list[Image.Image] = []
    for s in SIZES:
        img = builder(s)
        path = out_dir / f"{prefix}_{s}.png"
        img.save(path, "PNG")
        pngs.append(img)
        print(f"  wrote {path.name}  ({s}×{s})")
    # The "primary" PNG that .desktop files / Mac iconutil consume
    pngs[-1].save(out_dir / f"{prefix}.png", "PNG")
    # Multi-resolution .ico for Windows
    ico_sizes = [(s, s) for s in (16, 32, 48, 64, 128, 256)]
    pngs[-1].save(out_dir / f"{prefix}.ico", "ICO", sizes=ico_sizes)
    print(f"  wrote {prefix}.png  +  {prefix}.ico (multi-res)")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
              Path(__file__).parent / "icons"
    out_dir = out_dir.expanduser()
    print(f"[icons] output → {out_dir}")
    print("[icons] building AIM icon set …")
    _save_set(_aim_icon, "aim", out_dir)
    print("[icons] building AIM AI icon set …")
    _save_set(_aim_ai_icon, "aim_ai", out_dir)
    print(f"[icons] done.  Use {out_dir}/aim.png + aim_ai.png on Linux,")
    print(f"               {out_dir}/aim.ico + aim_ai.ico on Windows.")
    print(f"               run install_icons_mac.sh on macOS to make .icns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
