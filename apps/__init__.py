"""COPA apps 包级公共件：全窗口共享的 COPA 应用图标。"""
import os
import sys

from PySide6.QtGui import QIcon

_ICON_NAME = "COPAv2.ico"
_ICON = None


def app_icon_path():
    """COPAv2.ico 路径：源码运行取项目根；打包后同 Manual/About 的
    _MEIPASS 机制(6.x 指向 _internal，spec datas 已随包分发)。"""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, _ICON_NAME)


def app_icon():
    """全窗口共享的 COPA 图标(模块级缓存单例)"""
    global _ICON
    if _ICON is None:
        _ICON = QIcon(app_icon_path())
    return _ICON
