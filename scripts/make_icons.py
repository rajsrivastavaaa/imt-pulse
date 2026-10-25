"""Draw the app icons (navy tile with an amber 'pulse' line) as PNGs, using only the standard library.

Usage: python3 scripts/make_icons.py   -> frontend/icons/*.png
"""
import math
import os
import struct
import zlib

NAVY = (20, 33, 61)
AMBER = (252, 163, 17)
# Heartbeat polyline in unit coordinates (0..1).
LINE = [(0.12, 0.55), (0.36, 0.55), (0.44, 0.36), (0.54, 0.74), (0.62, 0.30), (0.70, 0.55), (0.88, 0.55)]


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def draw(size, radius_frac, scale):
    """scale < 1 shrinks the line toward the centre (safe zone for maskable icons)."""
    pts = [(0.5 + (x - 0.5) * scale, 0.5 + (y - 0.5) * scale) for x, y in LINE]
    half_w = 0.045 * scale
    r = radius_frac
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in (0.25, 0.75):            # 2x2 supersampling
                for sx in (0.25, 0.75):
                    x, y = (i + sx) / size, (j + sy) / size
                    # rounded-square mask
                    cx, cy = min(max(x, r), 1 - r), min(max(y, r), 1 - r)
                    inside = r == 0 or math.hypot(x - cx, y - cy) <= r
                    if not inside:
                        continue
                    d = min(seg_dist(x, y, *pts[k], *pts[k + 1]) for k in range(len(pts) - 1))
                    col = AMBER if d <= half_w else NAVY
                    acc[0] += col[0]; acc[1] += col[1]; acc[2] += col[2]; acc[3] += 255
            row += bytes(int(v / 4) for v in acc)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


out = os.path.join(os.path.dirname(__file__), "..", "frontend", "icons")
os.makedirs(out, exist_ok=True)
for name, size, radius, scale in [("icon-192.png", 192, 0.22, 1.0), ("icon-512.png", 512, 0.22, 1.0),
                                  ("icon-maskable-512.png", 512, 0.0, 0.72), ("apple-touch-icon.png", 180, 0.0, 0.85)]:
    with open(os.path.join(out, name), "wb") as f:
        f.write(draw(size, radius, scale))
    print("wrote", name)
