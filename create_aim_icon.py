#!/usr/bin/env python3
"""Create AIM icon — caduceus (two snakes + staff + wings)"""
from PIL import Image, ImageDraw, ImageFont
import math, os

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
cx, cy = SIZE // 2, SIZE // 2

# ── Background circle ──────────────────────────────────────────
for r in range(cx, 0, -1):
    t = r / cx
    color = (int(8 + 25*t), int(55 + 70*t), int(75 + 95*t), 255)
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=color)

# ── Staff (vertical rod) ──────────────────────────────────────
staff_x = cx
staff_top = 28
staff_bot = 210
staff_w = 7
d.rounded_rectangle(
    [staff_x - staff_w//2, staff_top, staff_x + staff_w//2, staff_bot],
    radius=3, fill=(220, 235, 255, 230)
)

# ── Two snakes ─────────────────────────────────────────────────
# Snake: sinusoidal path winding around the staff
# Left snake goes: top-left → right → left → right → bottom
# Right snake mirrors it (phase shifted by π)

def snake_points(phase: float, n: int = 80):
    """Return list of (x, y) for one snake."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        y = staff_top + 30 + t * (staff_bot - staff_top - 60)
        # Amplitude decreases near top (head) and bottom (tail)
        amp = 28 * math.sin(math.pi * t) * 0.9 + 8
        x = cx + amp * math.sin(2 * math.pi * 2.5 * t + phase)
        pts.append((x, y))
    return pts

# Draw snakes as thick polylines with body segments
def draw_snake(pts, body_color, outline_color, width=9):
    # Outline (slightly wider)
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i+1]], fill=outline_color, width=width + 3)
    # Body
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i+1]], fill=body_color, width=width)
    # Scale pattern (dots along body)
    for i in range(0, len(pts) - 2, 4):
        x, y = pts[i]
        d.ellipse([x-2, y-2, x+2, y+2], fill=outline_color)

# Snake 1: teal-green
s1 = snake_points(0.0)
draw_snake(s1, (60, 200, 160, 220), (20, 120, 90, 230), width=8)

# Snake 2: blue-teal (phase shifted by π → mirror)
s2 = snake_points(math.pi)
draw_snake(s2, (40, 160, 220, 220), (15, 90, 150, 230), width=8)

# Snake heads (ellipses at the top of each snake)
for pts, color in [(s1, (60, 210, 160, 255)), (s2, (40, 170, 230, 255))]:
    hx, hy = pts[0]
    d.ellipse([hx-7, hy-7, hx+7, hy+7], fill=color)
    # Forked tongue
    tx, ty = pts[1]
    dx = hx - tx
    d.line([(hx, hy-5), (hx + dx*0.8, hy-11)], fill=(220, 60, 60, 200), width=2)
    d.line([(hx, hy-5), (hx - dx*0.8, hy-11)], fill=(220, 60, 60, 200), width=2)

# Redraw staff on top of snakes
d.rounded_rectangle(
    [staff_x - staff_w//2, staff_top, staff_x + staff_w//2, staff_bot],
    radius=3, fill=(225, 240, 255, 180)
)

# ── Wings ──────────────────────────────────────────────────────
wing_y = staff_top + 18
wing_color = (180, 220, 255, 200)
wing_outline = (100, 170, 240, 220)

# Left wing
lw = [
    (cx, wing_y),
    (cx - 18, wing_y - 8),
    (cx - 38, wing_y - 4),
    (cx - 46, wing_y + 6),
    (cx - 34, wing_y + 12),
    (cx - 18, wing_y + 8),
    (cx, wing_y + 4),
]
d.polygon(lw, fill=wing_color, outline=wing_outline)

# Right wing (mirror)
rw = [(SIZE - x, y) for x, y in lw]
d.polygon(rw, fill=wing_color, outline=wing_outline)

# ── "AIM" text ─────────────────────────────────────────────────
try:
    font_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    font_sub  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
except Exception:
    font_big = font_sub = ImageFont.load_default()

# Shadow
d.text((cx+1, cy+76), "AIM", font=font_big, fill=(0,0,0,120), anchor="mm")
d.text((cx,   cy+75), "AIM", font=font_big, fill=(255,255,255,255), anchor="mm")
d.text((cx+1, cy+97), "Integrative Medicine", font=font_sub, fill=(0,0,0,80), anchor="mm")
d.text((cx,   cy+96), "Integrative Medicine", font=font_sub, fill=(170,235,255,200), anchor="mm")

# ── Save ──────────────────────────────────────────────────────
out = os.path.expanduser("~/AIM/aim_icon.png")
img.save(out, "PNG")
img.resize((64, 64), Image.LANCZOS).save(
    os.path.expanduser("~/AIM/aim_icon_small.png"), "PNG")
print(f"Saved: {out}")
