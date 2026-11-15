"""启动瞬间抓窗口：验证 splash 是真画出来了，而不是一个空白窗口。

用法::  python tools/grab_window.py [延迟ms] [输出路径]
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
EXE = PROJECT_DIR / "dist" / "COPA" / "COPA.exe"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

PW_RENDERFULLCONTENT = 0x00000002


def find_window(pid: int):
    hit = []

    def _cb(hwnd, _l):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left > 200:
                hit.append((hwnd, rect))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return hit[0] if hit else None


def grab(hwnd, rect, out: Path) -> None:
    from PIL import Image

    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth, bi.biHeight = w, -h        # 负高度 = 自上而下
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).convert("RGB").save(out)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)


def main() -> int:
    delay = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_DIR / "temp" / "boot_window.png"
    t0 = time.perf_counter()
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    try:
        found = None
        while time.perf_counter() - t0 < 20:
            found = find_window(proc.pid)
            if found:
                break
            time.sleep(0.01)
        if not found:
            return print("!! 没等到窗口") or 1
        appeared = (time.perf_counter() - t0) * 1000
        time.sleep(delay / 1000.0)
        hwnd, rect = found
        grab(hwnd, rect, out)
        print(f"窗口出现 {appeared:.0f} ms，再等 {delay} ms 后抓图 -> {out}")
        return 0
    finally:
        proc.kill()
        proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
