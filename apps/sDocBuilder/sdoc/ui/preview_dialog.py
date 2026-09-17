# -*- coding: utf-8 -*-
"""生成预览对话框（布局来自 preview_dialog.ui）。

两种模式：
- pdf 模式（Word 可用）：预览经 Word 渲染的 PDF，所见即文档所得；
- html 模式（回退）：章节/块清单摘要。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QVBoxLayout)

from sdoc.ui.Ui_preview_dialog import Ui_PreviewDialog


class PreviewDialog(QDialog, Ui_PreviewDialog):
    def __init__(self, stats_text, parent=None, pdf_path=None, html=None):
        super().__init__(parent)
        self.setupUi(self)
        # 对话框默认只有关闭键：补最小化/最大化（长文档预览需要放大看）
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint)
        if pdf_path and os.path.exists(pdf_path):
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView

            self._pdf = QPdfDocument(self)
            self._pdf.load(pdf_path)
            self._view = QPdfView()
            self._view.setDocument(self._pdf)
            self._view.setPageMode(QPdfView.PageMode.MultiPage)
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            stats = QLabel(stats_text)
            lay = self.layout()
            lay.insertWidget(0, stats)
            lay.insertWidget(1, self._view, 1)
            self.textBrowser.hide()
            # 关闭即释放 PDF 句柄：否则文件锁会让下一次 Word 导出偶发失败
            self.finished.connect(self._release_pdf)
        else:
            self.textBrowser.setHtml(html or stats_text)
        # 标准按钮自定义文案（.ui 里保持标准键位）
        self.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setText("确认输出")
        self.buttonBox.button(
            QDialogButtonBox.StandardButton.Cancel).setText("返回修改")
        # .ui 的 connections 为空：标准按钮信号必须手动接线，否则点击无反应
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def _release_pdf(self):
        pdf = getattr(self, "_pdf", None)
        if pdf is not None:
            pdf.close()
            self._pdf = None
