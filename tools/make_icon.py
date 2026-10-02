"""生成应用图标（assets/icon.ico）。

用法：
    python tools/make_icon.py

用超采样绘制再缩小，边缘比直接按小尺寸画平滑得多。
需要 Pillow。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
S = 1024  # 超采样画布
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

TOP = (79, 142, 247)      # #4f8ef7
BOTTOM = (29, 78, 216)    # #1d4ed8
ACCENT = (37, 99, 235)    # #2563eb


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (1, size))
    px = g.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
    return g.resize((size, size), Image.Resampling.NEAREST)


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(gradient(S), (0, 0), rounded_mask(S, int(S * 0.225)))

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)

    # 文件夹标签页
    d.rounded_rectangle(
        [int(S * 0.176), int(S * 0.293), int(S * 0.420), int(S * 0.395)],
        radius=int(S * 0.028), fill=white,
    )
    # 文件夹主体
    d.rounded_rectangle(
        [int(S * 0.176), int(S * 0.342), int(S * 0.824), int(S * 0.742)],
        radius=int(S * 0.054), fill=white,
    )

    # 主体上的三条"文件"，长短不一，暗示分类整理
    bars = [(0.244, 0.586), (0.244, 0.702), (0.244, 0.520)]
    ys = [0.449, 0.535, 0.621]
    for (x0, x1), y in zip(bars, ys):
        d.rounded_rectangle(
            [int(S * x0), int(S * y), int(S * x1), int(S * (y + 0.045))],
            radius=int(S * 0.023), fill=ACCENT,
        )
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = build()

    png_path = OUT_DIR / "icon.png"
    master.resize((256, 256), Image.Resampling.LANCZOS).save(png_path)

    ico_path = OUT_DIR / "icon.ico"
    master.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    print(f"已生成 {png_path}")
    print(f"已生成 {ico_path}  尺寸: {ICO_SIZES}")
    print(f"ICO 体积: {ico_path.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
