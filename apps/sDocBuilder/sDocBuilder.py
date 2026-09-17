# -*- coding: utf-8 -*-
"""sDocBuilder 主入口：技术方案编排与输出工具（2026-09 并入 COPA）。

两种用法：
- COPA 内嵌：Commander 工具栏 B 按钮导入本模块的 MainWindow，以 MDI
  子窗体挂入 COPA 主窗（可拖动/可关闭，与 Desk 子窗口同一装配路径）；
- 独立运行：python sDocBuilder.py（原独立项目入口保留）。

sdoc 包内一律绝对导入（from sdoc...），故本目录（sdoc 的父目录）必须
在 sys.path：独立运行时在此补进；COPA 内嵌时由本模块导入时补进，
保证 COPA 从任意工作目录启动都能找到 sdoc。

库/输出路径已随迁移适配：真实库默认 <COPA>/library（sdoc/ui/main_window
按本目录上两级定位），docx 输出锚定本目录 output/（不再随工作目录漂移）。
"""
import os
import sys

# sdoc 包定位：本文件所在目录即 sdoc 的父目录
_SDOC_ROOT = os.path.dirname(os.path.abspath(__file__))
if _SDOC_ROOT not in sys.path:
    sys.path.insert(0, _SDOC_ROOT)

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from sdoc.ui.main_window import MainWindow

_APP_ICON = os.path.join(_SDOC_ROOT, "assets", "app.ico")


def main():
    app = QApplication([])
    # 图标在代码里设（不用 .ui 的 windowIcon）：ico 相对路径运行时按
    # 工作目录解析，极易失效；assets/app.ico 为多尺寸高清阶梯
    if os.path.exists(_APP_ICON):
        app.setWindowIcon(QIcon(_APP_ICON))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
