"""测量 COPA.exe 从进程启动到出现第一个可见窗口的耗时(启动前摇)。

用法::

    python tools/measure_startup.py [次数]

原理：subprocess 起 exe 后按 20ms 轮询 EnumWindows，找到属于该 pid 的
第一个可见窗口即停止计时。这测的正是用户体感的「双击后多久有画面」，
而不是进程创建耗时。
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
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid: int) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def _cb(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            found.append((hwnd, f"{buf.value or '(无标题)'} [{cls.value}]"))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return found


def run_once() -> tuple[float, str]:
    t0 = time.perf_counter()
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    seen = ""
    try:
        while time.perf_counter() - t0 < 20.0:
            if proc.poll() is not None:
                return time.perf_counter() - t0, "进程提前退出"
            wins = windows_of(proc.pid)
            if wins:
                seen = wins[0][1]
                return time.perf_counter() - t0, seen
            time.sleep(0.02)
        return time.perf_counter() - t0, "20s 内无窗口"
    finally:
        proc.kill()
        proc.wait(timeout=10)
        time.sleep(0.8)          # 让文件缓存/句柄回收，避免下一次被上次干扰


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if not EXE.is_file():
        return print(f"!! 找不到 {EXE}") or 1
    results = []
    for i in range(rounds):
        dt, title = run_once()
        results.append(dt)
        print(f"  第 {i + 1} 次: {dt * 1000:7.0f} ms  首个窗口: {title}")
    print(f"\n首次(冷) {results[0] * 1000:.0f} ms | "
          f"后续中位数 {sorted(results[1:] or results)[len(results[1:] or results) // 2] * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
