"""Regenerate assets/xai-mark.png from assets/xai-mark.svg (pill icon, 20×20)."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw
from svgpathtools import parse_path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "xai-mark.svg"
OUT = ROOT / "assets" / "xai-mark.png"


def main() -> None:
    root = ET.fromstring(SVG.read_text(encoding="utf-8"))
    path_d = root.find("{http://www.w3.org/2000/svg}path").get("d")
    vx, vy, vw, vh = map(float, root.get("viewBox").split())
    path = parse_path(path_d)
    size = 48
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = min(size / vw, size / vh) * 0.9
    ox = (size - vw * scale) / 2 - vx * scale
    oy = (size - vh * scale) / 2 - vy * scale
    pts = [
        (path.point(i / 500).real * scale + ox, path.point(i / 500).imag * scale + oy)
        for i in range(501)
    ]
    draw.polygon(pts, fill=(0, 0, 0, 255))
    img.resize((20, 20), Image.Resampling.LANCZOS).save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
