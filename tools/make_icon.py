"""生成 AIVerse 应用图标（纯标准库，无需 Pillow）。

输出：
  assets/aiverse.ico   多尺寸 Windows 图标（16/24/32/48/64/128/256）
  assets/logo.png      256x256 透明 PNG（用于 README）

用法：python tools/make_icon.py
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]

C1 = (0x4F, 0x8C, 0xFF)   # 蓝
C2 = (0x7C, 0x5C, 0xFF)   # 紫

SS = 4  # 每个像素 4x4 超采样，得到干净的抗锯齿


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _in_rounded_rect(x, y, w, h, r):
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _sign(p1, p2, p3):
    return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])


def _in_triangle(p, a, b, c):
    d1, d2, d3 = _sign(p, a, b), _sign(p, b, c), _sign(p, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def render(size: int) -> bytearray:
    """返回 size*size*4 的 RGBA 像素（行优先，从上到下）。"""
    w = h = size
    radius = size * 0.22
    # 播放键三角形（略微右移做视觉居中）
    tri = [
        (0.355 * size, 0.265 * size),
        (0.355 * size, 0.735 * size),
        (0.745 * size, 0.500 * size),
    ]
    buf = bytearray(w * h * 4)
    step = 1.0 / SS
    off = step / 2.0

    for y in range(h):
        for x in range(w):
            bg_cov = 0
            tri_cov = 0
            for sy in range(SS):
                for sx in range(SS):
                    px = x + off + sx * step
                    py = y + off + sy * step
                    if _in_rounded_rect(px, py, w, h, radius):
                        bg_cov += 1
                        if _in_triangle((px, py), *tri):
                            tri_cov += 1
            n = SS * SS
            if bg_cov == 0:
                continue
            # 渐变：沿对角线插值
            t = ((x / max(1, w - 1)) + (y / max(1, h - 1))) / 2.0
            base = _lerp(C1, C2, t)
            # 白色播放键叠加
            k = (tri_cov / n) / (bg_cov / n) if bg_cov else 0.0
            r = round(base[0] + (255 - base[0]) * k)
            g = round(base[1] + (255 - base[1]) * k)
            b = round(base[2] + (255 - base[2]) * k)
            a = round(255 * bg_cov / n)
            i = (y * w + x) * 4
            buf[i:i + 4] = bytes((r, g, b, a))
    return buf


# ------------------------------------------------------------------ ICO
def _bmp_entry(size: int, rgba: bytearray) -> bytes:
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    # BGRA，自下而上
    px = bytearray()
    for y in range(size - 1, -1, -1):
        row = rgba[y * size * 4:(y + 1) * size * 4]
        for x in range(size):
            i = x * 4
            px += bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
    # AND 掩码：32bpp 下不使用，但格式要求存在，行按 4 字节对齐
    mask_row = ((size + 31) // 32) * 4
    mask = bytes(mask_row * size)
    return header + bytes(px) + mask


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    count = len(images)
    out = bytearray(struct.pack("<HHH", 0, 1, count))
    offset = 6 + 16 * count
    entries, blobs = bytearray(), bytearray()
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(bytes(out + entries + blobs))


# ------------------------------------------------------------------ PNG
def write_png(path: Path, size: int, rgba: bytearray) -> None:
    raw = b"".join(b"\x00" + bytes(rgba[y * size * 4:(y + 1) * size * 4]) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = []
    png256 = None
    for s in SIZES:
        rgba = render(s)
        images.append((s, _bmp_entry(s, rgba)))
        if s == 256:
            png256 = rgba
        print(f"  rendered {s}x{s}")
    write_ico(ASSETS / "aiverse.ico", images)
    if png256 is not None:
        write_png(ASSETS / "logo.png", 256, png256)
    print(f"\n  -> {ASSETS / 'aiverse.ico'}")
    print(f"  -> {ASSETS / 'logo.png'}")


if __name__ == "__main__":
    main()
