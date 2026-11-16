"""报价诊断（Audit）：上传报价单 -> 一致性检查 -> 问题列表 + 批阅副本.

形态：与「选型报价」一样挂成 COPA 主程序内的 MDI 子窗口（AuditPanel），
不再是独立弹窗——用户要在出报价与批阅之间来回切，独立窗会被主窗压住。
关掉子窗口只是隐藏，跑着的批阅线程与结果都保留，再点工具栏就回来。

流程（用户拍板的口径）：
  1. 首页居中一个「选文件 / 开始检查」页，接受拖拽；文件先复制到
     temp/audit/{时间戳}_{原名} 留存，之后一切分析都用留存件，原件不动。
  2. 旧版 .xls 先借本机 Excel 转存成 .xlsx（版式保留），再走同一条链路。
  3. 分析时用字符进度条原位刷新（[■■■□□□] n/5 步骤说明）。
  4. 完成后直接显示问题列表与说明/建议，同时弹窗告知批阅文件位置
     「批阅文件已另存为 {path}」；批阅副本放 output/audit/。

线程模型与 Commander 的 selectionDone 相同：后台 threading.Thread 干活，
Signal 投递回 GUI 线程，线程里绝不碰任何 QWidget。
"""
import os
import shutil
import threading
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog,
                               QMessageBox, QTableWidgetItem, QWidget)

from COPA.apps.Ui_audit import Ui_AuditDialog
from COPA.apps.audit.db import Catalog
from COPA.apps.audit.progress import line as progress_line
from COPA.apps.audit.report import write_annotated_ex
from COPA.apps.audit.runner import (attach_baseline, audit_doc,
                                    is_blank_template, summarize)
from COPA.apps.audit.reader import read_quote

COPA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(COPA_ROOT, "output", "audit")
TEMP_DIR = os.path.join(COPA_ROOT, "temp", "audit")

_LEVEL_COLORS = {"red": "#C00000", "yellow": "#B26B02"}
_LEVEL_NAMES = {"red": "严重", "yellow": "提示"}

_STEPS = 5      # 进度条总步数：留存/载库/解析/判定/副本（诊断内容在副本的诊断页里）

_LEVEL_RANK = {"red": 0, "yellow": 1}   # 排序权重：点「级别」列升序时严重在前


class _LevelItem(QTableWidgetItem):
    """级别列：显示「严重/提示」，排序按严重程度而不是中文拼音序
    （QTableWidget 默认按 DisplayRole 文本排，「提示(ti)」会排在「严重(yan)」前）"""

    def __init__(self, text: str, rank: int):
        super().__init__(text)
        self._rank = rank

    def __lt__(self, other):
        if isinstance(other, _LevelItem):
            return self._rank < other._rank
        return super().__lt__(other)


def audit_icon() -> QIcon:
    """工具栏图标：优先用 Designer/主题里选好的放大镜（edit-find），
    取不到才退回 COPA 应用图标——不再画红字占位图（用户已人工选好图标）"""
    icon = QIcon.fromTheme("edit-find")
    if not icon.isNull():
        return icon
    from COPA.apps import app_icon
    return app_icon()


class AuditPanel(QWidget, Ui_AuditDialog):
    """报价诊断面板：单例，挂在主程序 MDI 里（main 负责装配与前置）"""

    progressChanged = Signal(str)
    auditFinished = Signal(dict)
    auditFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setup_headers()
        # QDialog 的拖拽由窗口自己接；改成内嵌面板后要显式开
        self.setAcceptDrops(True)

        self._src = ""          # 用户选的原件
        self._kept = ""         # temp 留存件（实际参与分析）
        self._worker = None     # threading.Thread
        self._rows = []         # 与表格行对应的 (sheet, row, label, issue)

        self.btnChoose.clicked.connect(self._choose_file)
        self.btnStart.clicked.connect(self._start)
        self.btnAgain.clicked.connect(self._reset)
        self.btnOpenFolder.clicked.connect(self._open_folder)
        self.tableWidget.cellClicked.connect(self._show_detail)
        self.progressChanged.connect(self.progressLabel.setText)
        self.auditFinished.connect(self._on_finished)
        self.auditFailed.connect(self._on_failed)
        # 点步骤标签同步更新提示行，进度条那格显示纯进度
        self.progressChanged.connect(
            lambda text: self.progressHint.setText(" ".join(text.split(" ")[1:])))

    # ====选文件====

    def setup_headers(self):
        """结果表列头与列宽。Ui 编译文件保持纯生成物（只从 audit.ui 生成），
        这类代码级的表格设置放在窗口逻辑里，重编译不再丢"""
        headers = ("工作表", "行", "名称 / 型号", "问题码", "级别", "问题说明")
        widths = (110, 46, 190, 58, 58, 380)
        table = self.tableWidget
        table.setColumnCount(len(headers))
        for col, (text, width) in enumerate(zip(headers, widths)):
            table.setHorizontalHeaderItem(col, QTableWidgetItem(text))
            table.setColumnWidth(col, width)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 允许点列头排序：问题多时先按「级别」升序（严重在前）再逐条看。
        # 填充期间会临时关掉（见 _fill_result），否则 insertRow 会边插边重排。
        table.setSortingEnabled(True)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择报价单", "",
            "报价单 (*.xlsx *.xlsm);;旧版 Excel (*.xls);;所有文件 (*.*)")
        if path:
            self.pick_file(path)

    def pick_file(self, path: str):
        """外部（拖拽 / 未来批量入口）也走这里，保证校验口径一致"""
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".xlsx", ".xlsm", ".xls"):
            QMessageBox.warning(self, "报价诊断", "支持 .xlsx / .xlsm / .xls（旧版）")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "报价诊断", "文件不存在：{}".format(path))
            return
        self._src = path
        self.fileLabel.setText(os.path.basename(path))
        self.btnStart.setEnabled(True)

    # ====拖拽====

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData() else []
        if urls and os.path.splitext(urls[0].toLocalFile())[1].lower() in (
                ".xlsx", ".xlsm", ".xls"):
            event.acceptProposedAction()
            self.dropZone.setProperty("dragOver", True)
            self._refresh_drop_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.dropZone.setProperty("dragOver", False)
        self._refresh_drop_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.dropZone.setProperty("dragOver", False)
        self._refresh_drop_style()
        urls = event.mimeData().urls()
        if urls:
            event.acceptProposedAction()
            self.pick_file(urls[0].toLocalFile())

    def _refresh_drop_style(self):
        # property 变了样式表不会自动重算，unpolish/polish 一遍
        self.dropZone.style().unpolish(self.dropZone)
        self.dropZone.style().polish(self.dropZone)

    # ====开始检查====

    def _start(self):
        if not self._src:
            return
        if self._worker and self._worker.is_alive():
            return
        self.stack.setCurrentIndex(1)
        self.fileTag.setText(os.path.basename(self._src))
        self.progressChanged.emit(progress_line(0, _STEPS, "准备…"))
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    def _work(self):
        """后台线程：留存 -> 载库 -> 解析 -> 判定 -> 批阅副本 -> 报告"""
        try:
            self._emit_step(1, "留存文件副本…")
            kept = self._keep_copy(self._src)
            self._kept = kept

            self._emit_step(2, "载入选型数据库…")
            catalog = Catalog.get()

            self._emit_step(3, "解析表头与明细行…")
            doc = read_quote(kept, catalog)
            # 与 CLI 走同一条装配：项目号 -> 项目快照的出单记录，GUI 少这一步
            # 就永远不会报 L27/L28（人工改动看起来跟没改一样）
            attach_baseline(doc)

            self._emit_step(4, "逐行判定一致性…")
            report = audit_doc(doc, catalog)

            if is_blank_template(report):
                # 空白模板：不生成批阅副本（审阅模板没有意义），结果页仍列结论
                self._emit_step(5, "疑似空白模板，跳过批阅副本…")
                self.auditFinished.emit({
                    "report": report, "annotated": None, "kept": kept,
                })
                return

            self._emit_step(5, "生成批阅副本…")
            annotated = write_annotated_ex(report, OUT_DIR)

            self.auditFinished.emit({
                "report": report,
                "annotated": annotated,
                "kept": kept,
            })
        except Exception as exc:                    # noqa: BLE001 线程里必须兜底
            traceback.print_exc()
            self.auditFailed.emit(str(exc) if str(exc) else repr(exc))

    def _emit_step(self, done: int, label: str):
        self.progressChanged.emit(progress_line(done, _STEPS, label))

    def _keep_copy(self, src: str) -> str:
        """temp 留存：分析全程用留存件，原件只读不动。

        旧版 .xls 在这里顺手转存成 .xlsx——openpyxl 读不了 BIFF，而改格式
        不该让用户自己去另存。借本机 Excel 转（版式/公式/合并都保留），
        转不了就把原因说清楚，不吞。
        """
        os.makedirs(TEMP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(src)
        target = os.path.join(TEMP_DIR, "{}_{}".format(stamp, base))
        if os.path.exists(target):                  # 同秒同名（重试同一文件）
            root, ext = os.path.splitext(target)
            index = 1
            while os.path.exists("{}_{}{}".format(root, index, ext)):
                index += 1
            target = "{}_{}{}".format(root, index, ext)
        shutil.copy2(src, target)
        if os.path.splitext(target)[1].lower() == ".xls":
            return _xls_to_xlsx(target)
        return target

    # ====结果====

    def _on_finished(self, payload: dict):
        report = payload["report"]
        annotated = payload["annotated"]
        self._fill_result(report)
        self.stack.setCurrentIndex(2)

        if annotated is None:
            # 空白模板：没有批阅副本，说明原因即可
            QMessageBox.information(
                self, "报价诊断",
                "该文件疑似空白模板（明细均未填型号与描述），未生成批阅副本。\n"
                "结论已显示在结果页。")
            return

        message = "批阅文件已另存为\n{}".format(annotated.path)
        if annotated.degraded:
            QMessageBox.warning(
                self, "批阅文件已另存为",
                "{}\n\n注意：生成时发现原件部分内容未能完整保留：\n{}".format(
                    message, "\n".join(annotated.warnings)) +
                "\n\n请勿直接把该副本发客户。")
        else:
            QMessageBox.information(self, "批阅文件已另存为", message)

    def _on_failed(self, message: str):
        """批阅失败：回到选文件页，把原因原样给用户（annotate 的中文错误可直接展示）"""
        self.stack.setCurrentIndex(0)
        self.btnStart.setEnabled(True)
        QMessageBox.critical(self, "批阅失败", message)

    def _fill_result(self, report):
        """问题表：文件级问题 + 每条行级问题一行，红/橙着色"""
        entries = []
        for issue in report.doc.file_issues:
            if not issue.ignored:
                row_no = issue.anchor[0] if issue.anchor else ""
                entries.append((issue.sheet or report.doc.sheet_of(row_no),
                                row_no, "（文件级）", issue))
        for item in report.doc.items:
            for issue in item.active_issues:
                entries.append((item.sheet, item.row, item.label, issue))

        table = self.tableWidget
        table.setSortingEnabled(False)          # 填充期间关排序，避免边插边重排
        table.setRowCount(0)
        for sheet, row_no, label, issue in entries:
            r = table.rowCount()
            table.insertRow(r)
            # 行号列存 int 而不是 str：排序时按数值，否则 "100" 会排在 "25" 前面
            values = (sheet, row_no, label, issue.code, issue.level_name,
                      issue.message or issue.title)
            for col, text in enumerate(values):
                if col == 4:
                    cell = _LevelItem(text, _LEVEL_RANK.get(issue.level, 9))
                    cell.setForeground(QColor(_LEVEL_COLORS.get(issue.level, "#333333")))
                else:
                    cell = QTableWidgetItem(text)
                table.setItem(r, col, cell)
            anchor_cell = table.item(r, 0)
            if anchor_cell is not None:
                anchor_cell.setData(Qt.ItemDataRole.UserRole, issue)
                # 位置信息跟着单元格走：排序后 _rows 的索引会错位，详情要用这份
                anchor_cell.setData(Qt.ItemDataRole.UserRole + 1,
                                    "\x1f".join((str(sheet), str(row_no), str(label))))
        table.setSortingEnabled(True)

        if report.passed:
            self.statLabel.setText("{}：未发现问题（未识别行 {}）".format(
                summarize(report), len(report.doc.unrecognized)))
        else:
            self.statLabel.setText("{}（未识别行 {}）".format(
                summarize(report), len(report.doc.unrecognized)))
        self._rows = entries
        if not entries:
            self.detailBrowser.setHtml(
                "<h3 style='color:#1B7E3E'>未发现问题</h3>"
                "<p>全部 {} 行明细都通过了检查。</p>".format(len(report.doc.items)))

    def _show_detail(self, row: int, _col: int):
        anchor_cell = self.tableWidget.item(row, 0)
        if anchor_cell is None:
            return
        issue = anchor_cell.data(Qt.ItemDataRole.UserRole)
        if issue is None:
            return
        # 位置随单元格走（表格可排序，_rows 的下标会错位）
        packed = anchor_cell.data(Qt.ItemDataRole.UserRole + 1) or "\x1f\x1f"
        sheet, row_no, label = packed.split("\x1f", 2)
        color = _LEVEL_COLORS.get(issue.level, "#333333")
        parts = [
            "<h2 style='color:{};margin-bottom:2px'>{} · {} {}</h2>".format(
                color, issue.level_name, issue.code, issue.title),
        ]
        if issue.message:
            parts.append("<p><b>问题：</b>{}</p>".format(_esc(issue.message)))
        if issue.expected:
            parts.append("<p><b>期望：</b>{}</p>".format(_esc(issue.expected)))
        if issue.actual:
            parts.append("<p><b>实际：</b>{}</p>".format(_esc(issue.actual)))
        if issue.advice:
            parts.append("<p><b>建议：</b>{}</p>".format(_esc(issue.advice)))
        parts.append("<p style='color:#888888'>位置：工作表「{}」 第 {} 行 · {}</p>".format(
            _esc(sheet), row_no, _esc(label)))
        self.detailBrowser.setHtml("".join(parts))

    # ====收尾====

    def _open_folder(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        os.startfile(OUT_DIR)                       # noqa: S606 Windows 专用

    def _reset(self):
        self._src = ""
        self._kept = ""
        self._report = None
        self.fileLabel.setText("")
        self.btnStart.setEnabled(False)
        self.tableWidget.setRowCount(0)
        self.detailBrowser.clear()
        self.statLabel.setText("")
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        # 批阅线程还在跑就别关：线程 emit 到已销毁的窗口会崩
        if self._worker and self._worker.is_alive():
            QMessageBox.information(self, "报价诊断", "正在批阅中，请等进度条走完再关闭。")
            event.ignore()
            return
        event.accept()


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _xls_to_xlsx(path: str) -> str:
    """旧版 .xls -> .xlsx（同目录，同名换后缀）。

    只在本机装了 Excel 时可行；没装就抛错，由调用方把原因原样给用户——
    比默默报「读不出来」有用得多。
    """
    out = os.path.splitext(path)[0] + ".xlsx"
    try:
        import win32com.client as win32
    except Exception as exc:                       # noqa: BLE001
        raise RuntimeError(
            "这是旧版 .xls，需要借本机 Excel 转存后才能批阅，但当前环境没有 "
            "pywin32（{}）。请用 Excel 另存为 .xlsx 后再试。".format(exc)) from exc
    excel = None
    workbook = None
    try:
        excel = win32.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Open(os.path.abspath(path), ReadOnly=True)
        workbook.SaveAs(os.path.abspath(out), FileFormat=51)   # 51 = xlsx
    except Exception as exc:                       # noqa: BLE001
        raise RuntimeError(
            "旧版 .xls 转存失败（{}）。请确认本机装了 Excel，或手动另存为 .xlsx。"
            .format(exc)) from exc
    finally:
        try:
            if workbook is not None:
                workbook.Close(False)
        except Exception:                          # noqa: BLE001
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:                          # noqa: BLE001
            pass
    return out
