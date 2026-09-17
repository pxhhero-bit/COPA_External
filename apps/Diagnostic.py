"""COPA_com_Diagnostic v1.0 选型诊断控件 by Hero Pang.
与 Writer 同级：读取 engine 回传结果里的选型信息与 diagnostic 结构
(参数项目按 engine 生成的 diagnostic 字段设定)，判定模块业务下
传感器/模块/接线盒/仪表 型号是否有空缺。

有空缺时由本控件整体负责并嵌入 checklist 的 QuoteListItem：
- item 背景置黄；
- item 右下角嵌入 警告icon + 「查看诊断/忽略」两个按钮；
- 鼠标悬停 item 显示提示(不限时，移开鼠标自动隐藏)；
- 「查看诊断」弹出子窗展示带 quote_id 的完整诊断信息，子窗底部「确认」关闭；
- 「忽略」恢复 item 外观并隐藏徽章。
"""
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import (QDialog, QLabel, QPlainTextEdit, QPushButton,
                               QStyle, QToolTip, QVBoxLayout, QWidget)

TOOLTIP_TEXT = "这个项目的选型好像出了点问题。"

# 模块业务四类型号 -> engine结果取值判定是否为空
_MODULE_MODEL_CHECKS = (
    ("传感器", lambda r: r.get("sensor") or []),
    ("模块", lambda r: r.get("module") or []),
    ("接线盒", lambda r: r.get("jbox") and [r["jbox"]] or []),
    ("仪表", lambda r: r.get("controller") or []),
)


def missing_models(result):
    """模块业务下传感器/模块/接线盒/仪表有空缺时返回缺项名列表，否则空列表。
    传感器与模块共用 engine 的 module 组合列表：上游传感器为空则两者皆空。"""
    if not isinstance(result, dict) or result.get("item_type") != "module":
        return []

    missing = []
    sensor_empty = not (result.get("sensor") or {}).get("sensors")

    for name, getter in _MODULE_MODEL_CHECKS:
        if name == "传感器" and sensor_empty:
            missing.append(name)
        elif name == "模块" and not getter(result):
            missing.append(name)
        elif name in ("接线盒", "仪表") and not getter(result):
            missing.append(name)

    return missing


# ---------------------------------------------------------------------------
# 诊断文本整理：选型信息 + engine diagnostic 参数块
# ---------------------------------------------------------------------------

def _walk_block(data, pad, lines):
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            lines.append("{}{}:".format(pad, key))
            _walk_block(value, pad + "  ", lines)
        elif isinstance(value, list):
            lines.append("{}{}: [{} 项]".format(pad, key, len(value)))
        else:
            lines.append("{}{}: {}".format(pad, key, value))


def _section(title, data):
    lines = ["—— {} ——".format(title)]
    _walk_block(data, "  ", lines)
    return "\n".join(lines)


def format_diagnostics(result):
    """engine 结果 -> 可读诊断文本(选型信息 + 各业务 diagnostic 完整参数)"""
    result = result or {}
    quote_id = result.get("quote_id", "?")
    lines = [
        "条目 {} 诊断信息".format(quote_id),
        "条目类型: {}    选型状态: {}".format(
            result.get("item_type", "?"), result.get("status", "?")),
        "",
        "—— 选型信息 ——",
    ]

    if result.get("item_type") == "module":
        combos = result.get("module") or []
        lines += ["  传感器/模块组合: " + (
            "; ".join("{} {} + {}-{}kg {}".format(
                m["module"]["module模块型号"], m["module"]["mtl模块材质"],
                m["sensor"]["family型号"], m["sensor"]["capacity容量"],
                m["sensor"]["AC准确度等级"]) for m in combos) or "无匹配")]
    else:
        rows = result.get("platform") or result.get("bench") or []

        def _row_model(r):
            p = r.get("platform")          # 平台秤行嵌套，台秤行扁平
            src = p or r
            return "{} (量程{}kg 台面{})".format(
                src.get("具体型号", "?"), src.get("量程", "?"),
                src.get("台面尺寸", "?"))

        lines += ["  型号: " + (
            "; ".join(_row_model(r) for r in rows) or "无匹配")]

    jbox = result.get("jbox")
    lines += ["  接线盒: " + (jbox["model型号"] if jbox else "无匹配")]

    controllers = result.get("controller") or []
    lines += ["  仪表: " + (
        "; ".join(c.get("详细型号", "?") for c in controllers) or "无匹配"), ""]

    # diagnostic 参数块：字段名与 engine 生成结构一一对应
    blocks = (
        ("传感器选型诊断", (result.get("sensor") or {}).get("diagnostic")),
        ("模块选型诊断", result.get("module_diagnostic")),
        ("平台秤选型诊断", result.get("platform_diagnostic")),
        ("台秤选型诊断", result.get("bench_diagnostic")),
        ("仪表选型诊断", result.get("controller_diagnostic")),
    )
    lines += [s for s in (_section(t, d) for t, d in blocks) if len(s.splitlines()) > 1]

    if result.get("status") == "ERROR":
        lines += ["", "—— 错误 ——", "  {}".format(result.get("error", ""))]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 徽章控件：警告icon + 查看诊断/忽略按钮，嵌入 QuoteListItem 右下角
# ---------------------------------------------------------------------------

class DiagnosticBadge(QWidget):

    viewRequested = Signal()
    ignored = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        # 放在 item 右下角空白区(避开附件下拉与安装方式行)
        self.setGeometry(510, 192, 90, 54)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        icon = QLabel(self)
        icon.setPixmap(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(16, 16))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_view = QPushButton("查看诊断", self)
        btn_ignore = QPushButton("忽略", self)
        small_font = btn_view.font()
        small_font.setPointSize(8)

        for btn in (btn_view, btn_ignore):
            btn.setFont(small_font)
            btn.setFixedHeight(17)

        layout.addWidget(icon)
        layout.addWidget(btn_view)
        layout.addWidget(btn_ignore)

        btn_view.clicked.connect(self.viewRequested)
        btn_ignore.clicked.connect(self.ignored)
        self.hide()


class DiagnosticDialog(QDialog):
    """条目完整诊断信息子窗：只读文本 + 底部确认按钮"""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle("诊断信息 - 条目 {}".format(
            (result or {}).get("quote_id", "?")))
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(format_diagnostics(result))
        layout.addWidget(self.textEdit)

        btn_confirm = QPushButton("确认", self)
        btn_confirm.setDefault(True)
        btn_confirm.clicked.connect(self.accept)
        layout.addWidget(btn_confirm)


# ---------------------------------------------------------------------------
# 诊断控件主体：挂接 listitem、评估缺项、驱动警告UI
# ---------------------------------------------------------------------------

class Diagnostic(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watching = {}   # id(item) -> item

    def attach(self, item):
        """把徽章嵌入 QuoteListItem 并接好信号"""
        badge = DiagnosticBadge(item)
        item._diag_badge = badge
        badge.viewRequested.connect(lambda: self._show_dialog(item))
        badge.ignored.connect(lambda: self._on_ignore(item))

    def evaluate(self, item):
        """读取 item 的 engine 结果，缺项时亮警告；已手动忽略的不再亮"""
        if getattr(item, "_diag_ignored", False):
            return

        if missing_models(item.result()):
            self._raise_warning(item)
        else:
            self._lower_warning(item)

    def warning_items(self):
        """当前亮着警告(未处理/未忽略)的 item 列表，供输出前预检"""
        return list(self._watching.values())

    # ====警告状态====

    def _raise_warning(self, item):
        badge = getattr(item, "_diag_badge", None)

        if badge is not None:
            badge.show()

        item.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        item.setStyleSheet("QuoteListItem { background-color: #FFF3B2; }")
        self._watch_filters(item, True)

    def _on_ignore(self, item):
        """用户点击忽略：标记后恢复外观，再次 evaluate 不再亮"""
        item._diag_ignored = True
        self._lower_warning(item)

    def _lower_warning(self, item):
        """忽略/无缺项：恢复外观并隐藏徽章"""
        badge = getattr(item, "_diag_badge", None)

        if badge is not None:
            badge.hide()

        item.setStyleSheet("")
        self._watch_filters(item, False)

    # ====悬停5秒提示====

    def _watch_filters(self, item, on):
        widgets = [item] + item.findChildren(QWidget)

        for w in widgets:
            if on:
                w.installEventFilter(self)
            else:
                w.removeEventFilter(self)

        if on:
            self._watching[id(item)] = item
        else:
            self._watching.pop(id(item), None)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            # 不限时：悬停期间一直显示，移开鼠标由 Qt 自动隐藏
            QToolTip.showText(event.globalPos(), TOOLTIP_TEXT)
            return True

        return super().eventFilter(watched, event)

    # ====诊断子窗====

    def _show_dialog(self, item):
        dialog = DiagnosticDialog(item.result(), parent=item.window())
        dialog.exec()
