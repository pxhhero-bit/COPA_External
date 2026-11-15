"""COPA 启动引导，PyInstaller 的入口脚本。

存在的唯一理由：让启动画面尽可能早出现。

``main.py`` 顶层 import 了 Desk / Checklist / Audit / sDocBuilder / contract
等重模块，本机实测 491ms，慢机更高。这些导入原先全部发生在 Splash 之前，
用户双击后只能盯着空桌面等。这里把顺序倒过来：

    1. 只加载 Qt 基础(约 0.18s) → 立刻 show 出启动画面并推到屏幕上
    2. 再 import COPA.main(重模块) → 建主窗 → finish() 淡出

源码运行 ``py -m COPA.main`` 仍可用(转到本模块的 main())，但要看到优化
后的启动顺序请用 ``py -m COPA.launch``。
"""
from __future__ import annotations

import os
import sys

# 直接以脚本方式运行时(冻结态同理)，把 COPA 包的上一级加入 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _set_app_user_model_id() -> None:
    """Windows 任务栏图标：显式声明 AppUserModelID，否则窗口被按
    python.exe / COPA.exe 进程分组，任务栏显示的是宿主图标。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "COPA.Commander.1")
    except Exception:
        pass


def main() -> int:
    _set_app_user_model_id()

    # ---- 第一阶段：只碰 Qt 基础，尽早出画面 ----
    from PySide6.QtWidgets import QApplication

    from COPA.apps import app_icon

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())          # 应用级默认：全部弹窗继承

    # 启动画面属于锦上添花，任何异常都不该拦住程序启动
    splash = None
    try:
        from COPA.apps.Splash import Splash
        splash = Splash()
        splash.show()
        app.processEvents()                # 把第一帧推上屏，不等事件循环
    except Exception:
        splash = None

    if splash is not None:
        splash.set_progress(0.35)

    # ---- 第二阶段：重模块与主窗（此刻画面已在屏幕上了）----
    from COPA.main import Commander

    window = Commander()

    if splash is not None:
        splash.set_progress(0.82)
        app.processEvents()
        splash.finish(window)              # 内部负责 window.show() 与淡出
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
