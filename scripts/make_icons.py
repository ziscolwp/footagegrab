#!/usr/bin/env python3
"""Generate extension icons: dark rounded square with green [ and amber ] brackets.

No image libraries needed — writes RGBA PNGs directly. Regenerate with:
    python3 scripts/make_icons.py
"""

import struct
import zlib
from pathlib import Path

BG = (16, 16, 18, 255)
GREEN = (23, 201, 100, 255)
AMBER = (245, 165, 36, 255)
CLEAR = (0, 0, 0, 0)

OUT_DIR = Path(__file__).resolve().parents[1] / "extension" / "icons"


def write_png(path, size, pixels):
    def chunk(tag, data):
        raw = tag + data
        return struct.pack(">I", len(data)) + raw + struct.pack(">I", zlib.crc32(raw))

    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def in_rect(x, y, x0, x1, y0, y1):
    return x0 <= x < x1 and y0 <= y < y1


def make_icon(size):
    r = size * 0.22  # corner radius
    n = max(1, round(size * 0.08))  # bracket stroke thickness

    # bracket geometry (pixel units)
    bar_top, bar_bot = round(size * 0.30), round(size * 0.70)
    stub = round(size * 0.16)
    in_x = round(size * 0.24)
    out_x = size - in_x

    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            # rounded-corner mask
            px, py = x + 0.5, y + 0.5
            corners = [(r, r), (size - r, r), (r, size - r), (size - r, size - r)]
            outside = False
            for cx, cy in corners:
                in_corner_box = ((px < r or px > size - r) and (py < r or py > size - r))
                if in_corner_box and (px - cx) ** 2 + (py - cy) ** 2 > r * r:
                    near = min(((px - cx) ** 2 + (py - cy) ** 2) for cx, cy in corners)
                    if near > r * r:
                        outside = True
                    break
            if outside:
                row.append(CLEAR)
                continue

            color = BG
            # "[" bracket
            if in_rect(x, y, in_x, in_x + n, bar_top, bar_bot) \
               or in_rect(x, y, in_x, in_x + stub, bar_top, bar_top + n) \
               or in_rect(x, y, in_x, in_x + stub, bar_bot - n, bar_bot):
                color = GREEN
            # "]" bracket
            elif in_rect(x, y, out_x - n, out_x, bar_top, bar_bot) \
                    or in_rect(x, y, out_x - stub, out_x, bar_top, bar_top + n) \
                    or in_rect(x, y, out_x - stub, out_x, bar_bot - n, bar_bot):
                color = AMBER
            row.append(color)
        pixels.append(row)
    return pixels


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        write_png(OUT_DIR / f"icon{size}.png", size, make_icon(size))
        print(f"wrote icon{size}.png")


if __name__ == "__main__":
    main()
