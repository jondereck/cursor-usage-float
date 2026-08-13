"""Visual check against the on-screen composited pill (what the user sees)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tkinter as tk

from theme import BAR_BG, CARD, CRITICAL, DOT_OK, PACE_STOP_BG, PACE_STOP_FG
from win_clickthrough import (
    TRANSPARENT_KEY,
    clear_window_region,
    set_color_key,
    toplevel_hwnd,
)


def draw_capsule(c: tk.Canvas, x1: float, y1: float, x2: float, y2: float, fill: str) -> None:
    diam = y2 - y1
    r = diam / 2.0
    c.create_oval(x1, y1, x1 + diam, y2, fill=fill, outline="")
    c.create_oval(x2 - diam, y1, x2, y2, fill=fill, outline="")
    c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")


def grab_screen_bmp(path: Path, left: int, top: int, w: int, h: int) -> bytes:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, left, top, 0x00CC0020)  # SRCCOPY

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 24
    bmi.biCompression = 0
    row = ((w * 3 + 3) // 4) * 4
    buf = (ctypes.c_ubyte * (row * h))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)

    pixel_size = row * h
    with path.open("wb") as f:
        f.write(b"BM")
        f.write((54 + pixel_size).to_bytes(4, "little"))
        f.write((0).to_bytes(4, "little"))
        f.write((54).to_bytes(4, "little"))
        f.write((40).to_bytes(4, "little"))
        f.write(w.to_bytes(4, "little"))
        f.write(h.to_bytes(4, "little"))
        f.write((1).to_bytes(2, "little"))
        f.write((24).to_bytes(2, "little"))
        f.write((0).to_bytes(4, "little"))
        f.write(pixel_size.to_bytes(4, "little"))
        f.write((0).to_bytes(16, "little"))
        f.write(bytes(buf))

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    return bytes(buf)


def px(buf: bytes, w: int, x: int, y: int) -> tuple[int, int, int]:
    stride = ((w * 3 + 3) // 4) * 4
    i = y * stride + x * 3
    b, g, r = buf[i], buf[i + 1], buf[i + 2]
    return r, g, b


def near_red(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > 180 and g < 140 and b < 140


def near_cream(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > 200 and g > 200 and b > 190


def main() -> int:
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    key = "#%02X%02X%02X" % TRANSPARENT_KEY
    w, h = 168, 36
    root.geometry(f"{w}x{h}+100+100")
    root.configure(bg=key)

    # Mirror real chrome: outer → card (pad 0) → canvas (no expand).
    outer = tk.Frame(root, bg=key)
    outer.pack()
    card = tk.Frame(outer, bg=key, padx=0, pady=0)
    card.pack()
    c = tk.Canvas(card, width=w, height=h, bg=key, highlightthickness=0, bd=0)
    c.pack()

    c.create_rectangle(0, 0, w + 1, h + 1, fill=key, outline="")
    x2, y2 = float(w - 1), float(h - 1)
    bw = 2.0
    draw_capsule(c, 0, 0, x2, y2, CRITICAL)
    draw_capsule(c, bw, bw, x2 - bw, y2 - bw, CARD)
    rad = y2 / 2.0
    c.create_rectangle(rad, 0, x2 - rad, bw, fill=CRITICAL, outline="")
    c.create_rectangle(rad, y2 - bw, x2 - rad, y2, fill=CRITICAL, outline="")
    cx, cy, r_out = 8 + 10, h / 2, 8
    c.create_arc(
        cx - r_out, cy - r_out, cx + r_out, cy + r_out,
        start=90, extent=-359.9, style="arc", outline=BAR_BG, width=2,
    )
    c.create_arc(
        cx - r_out, cy - r_out, cx + r_out, cy + r_out,
        start=90, extent=-300, style="arc", outline=CRITICAL, width=2,
    )
    c.create_oval(cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5, fill=DOT_OK, outline="")
    c.create_text(34, cy, text="3.5%/2.9%", fill=CRITICAL, font=("Segoe UI", 11, "bold"), anchor="w")
    bx = 118
    c.create_oval(bx, cy - 9, bx + 12, cy + 9, fill=PACE_STOP_BG, outline="")
    c.create_oval(bx + 28, cy - 9, bx + 40, cy + 9, fill=PACE_STOP_BG, outline="")
    c.create_rectangle(bx + 6, cy - 9, bx + 34, cy + 9, fill=PACE_STOP_BG, outline="")
    c.create_text(bx + 20, cy, text="STOP", fill=PACE_STOP_FG, font=("Segoe UI", 8, "bold"))

    root.update_idletasks()
    root.update()
    hwnd = toplevel_hwnd(root)
    clear_window_region(hwnd)
    set_color_key(hwnd, TRANSPARENT_KEY)
    root.update()
    root.after(50, lambda: None)
    root.update()

    out = Path(__file__).resolve().parents[1] / "docs" / "images" / "pill-stop-verify.bmp"
    buf = grab_screen_bmp(out, 100, 100, w, h)

    samples = {
        "left": px(buf, w, 1, h // 2),
        "right": px(buf, w, w - 2, h // 2),
        "top": px(buf, w, w // 2, 1),
        "bottom_mid": px(buf, w, w // 2, h - 2),
        "bottom_l": px(buf, w, w // 3, h - 2),
        "bottom_r": px(buf, w, (2 * w) // 3, h - 2),
        "center": px(buf, w, w // 2, h // 2),
    }
    for name, rgb in samples.items():
        print(name, rgb)

    ok = (
        near_red(samples["left"])
        and near_red(samples["right"])
        and near_red(samples["top"])
        and near_red(samples["bottom_mid"])
        and near_red(samples["bottom_l"])
        and near_red(samples["bottom_r"])
        and near_cream(samples["center"])
    )
    print("saved", out)
    root.destroy()
    if not ok:
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
