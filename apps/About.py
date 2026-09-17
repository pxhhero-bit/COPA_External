"""COPA_com_About.
Commander「设置 -> 关于COPA」：模态小窗展示软件名称、版本、发布日期、
开发者与联系方式，属静态信息窗。

信息取值分三类：
- 名称/简介/开发者/版权：本文件顶部常量，改这里即可；
- 版本/发布日期：统一取 apps/version.py(About 展示与 Feedback 数据包
  标注共用一处，升级软件只改 version.py)；
- 反馈邮箱：取 config/feedback.json 的 receiver(与「反馈与优化」同一
  收件箱，未配置或读取失败则整行不展示，绝不阻断窗口)；config 不随
  包分发、按 exe 旁定位(同 Feedback 机制)，而图标 COPA.ico 随 datas
  进 _internal(同 Manual 的 _MEIPASS 机制，缺失时隐藏图标不阻断)。
"""
import json
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from COPA.apps.version import APP_RELEASE_DATE, APP_VERSION

# 图标随 datas 进包：定位同 Manual——源码运行取项目根，打包后取
# sys._MEIPASS(6.x 即 _internal)
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    _BUNDLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ICON_PATH = os.path.join(_BUNDLE_DIR, "COPAv2.ico")

# config 不打进包、按 exe 旁定位(同 Feedback 机制，保证运行期可改)
if getattr(sys, "frozen", False):
    _CONFIG_DIR = os.path.dirname(sys.executable)
else:
    _CONFIG_DIR = _BUNDLE_DIR

_FEEDBACK_CONFIG = os.path.join(_CONFIG_DIR, "config", "feedback.json")

# ----窗口展示内容：按需修改，勿动版本号(归 version.py 管)----
APP_NAME = "COPA 选型报价辅助系统"
APP_TAGLINE = "一款面向称重设备选型与报价场景的轻量化业务软件。"
APP_DEVELOPER = "开发者：Hero Pang"
APP_COPYRIGHT = "仅供内部使用，保留所有权利。\nFor Internal use only. All rights reserved."


def _read_receiver():
    """config/feedback.json -> 收件邮箱；缺失/损坏一律返回空串(About
    是静态信息窗，任何读取异常都不该影响展示)"""
    try:
        with open(_FEEDBACK_CONFIG, encoding="utf-8") as f:
            return str((json.load(f) or {}).get("receiver") or "").strip()
    except Exception:
        return ""


class AboutDialog(QDialog):
    """关于对话框：图标 + 名称/版本/简介 + 版权/开发者/反馈邮箱 + 确定；
    模态、固定尺寸、无系统问号键"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QIcon(_ICON_PATH))
        self.setWindowTitle("关于COPA")
        self.setFixedSize(350, 350)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(6)

        # 产品图标：素材缺失时整块隐藏
        if os.path.isfile(_ICON_PATH):
            icon = QIcon(_ICON_PATH)
            icon_label = QLabel(self)
            icon_label.setPixmap(icon.pixmap(72, 72))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        name_label = QLabel(APP_NAME, self)
        name_label.setStyleSheet("font-size: 17px; font-weight: bold;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        version_label = QLabel("版本 {}（{}）".format(
            APP_VERSION, APP_RELEASE_DATE), self)
        version_label.setStyleSheet("color: #666666;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        tagline_label = QLabel(APP_TAGLINE, self)
        tagline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline_label)

        layout.addSpacing(10)
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)
        layout.addSpacing(6)

        info = QLabel("{}\n{}".format(APP_DEVELOPER, APP_COPYRIGHT), self)
        info.setStyleSheet("color: #444444;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        receiver = _read_receiver()

        if receiver:
            email_label = QLabel(
                "反馈邮箱：{}\n（菜单「设置 → 反馈与优化」可直达）".format(
                    receiver), self)
            email_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            email_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(email_label)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_ok = QPushButton("确定", self)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)
