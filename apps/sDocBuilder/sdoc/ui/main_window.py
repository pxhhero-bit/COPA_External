# -*- coding: utf-8 -*-
"""sDocBuilder 编排工作台（布局来自 main_window.ui，经 pyside6-uic 生成）：

+---------+---------------------------+
| 候选池   |  白底"文档页"大纲树        |
| 分组树   |  1 章节                   |
|  型号    |    1.1 / 块…              |
|         |  2 章节                   |
+---------+---------------------------+
                      [生成预览] → 预览对话框 → 二次确认 → 输出 docx

本类只做数据装配与信号接线；控件布局/菜单/快捷键改 .ui 文件后重跑
pyside6-uic 重新生成，不要手改 Ui_*.py。
"""
import os
import sys

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog,
                               QMainWindow, QMessageBox)

from sdoc.core import arrangement
from sdoc.core.renderer import Renderer
from sdoc.core.snapshot_source import MockSnapshotSource
from sdoc.ui.Ui_main_window import Ui_MainWindow

# docx 输出目录锚定 sDocBuilder 包根（sdoc/ui 上两级）：并入 COPA 后
# 不再随启动工作目录漂移，docx 统一落 apps/sDocBuilder/output/
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "output")

# 兼容旧引用：测试与外部代码从这里取常量
from sdoc.ui.panels import MIME_REF, ROLE_REF  # noqa: F401,E402


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self._init_data()

        # 行为注入与别名（.ui 里控件名为 poolTree/outlineTree）
        self.pool = self.poolTree
        self.outline = self.outlineTree
        self.pool.set_store(self.store)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        # 候选池/大纲树点击 -> 材料预览（第三栏）
        self.pool.itemClicked.connect(self._preview_pool_item)
        self.outline.itemClicked.connect(self._preview_pool_item)
        self.previewBrowser.setHtml(
            "<div style='color:#888'>点击左侧材料查看内容预览</div>")

        # ----编辑历史（快照式，撤回/重做各 5 步）----
        self._undo_stack = []
        self._redo_stack = []
        self.outline.mutate_hook = self._snap_history

        # ----信号接线（动作/快捷键定义在 .ui）----
        self.actionOpenSnapshot.triggered.connect(self._open_snapshot)
        self.actionSaveArrangement.triggered.connect(self._save_arrangement)
        self.actionLoadArrangement.triggered.connect(self._load_arrangement)
        self.actionQuit.triggered.connect(self.close)
        self.actionUndo.triggered.connect(self._undo_op)
        self.actionRedo.triggered.connect(self._redo_op)
        self.actionPromote.triggered.connect(self._promote)
        self.actionDemote.triggered.connect(self._demote)
        self.actionDeleteNode.triggered.connect(self._delete_current)
        self.btnPreview.clicked.connect(self._make_preview)
        self.outline.report_hook = self.statusBar().showMessage
        self._refresh_hist()

        self.statusBar().showMessage(
            "占位数据：左侧型号/块拖入右侧编排；双击重命名；Del 删除；"
            "Ctrl+S 保存编排稿")
        self._prefill()
        self.comboBox.currentTextChanged.connect(self._on_brand_changed)
        self.actionRebuildTemplate.triggered.connect(self._prefill)
        # 项目/客户名称：输入框 <-> 项目对象（封面/文件名即时生效），
        # 反写快照仅项目名称、在输出确认时
        self.editProjectName.setText(self.project.project_id)
        self.editCustomerName.setText(self.project.company)
        self.editProjectName.textEdited.connect(self._on_project_name_edited)
        self.editCustomerName.textEdited.connect(self._on_customer_name_edited)

    def _preview_pool_item(self, item):
        """池/大纲树点击 -> 第三栏材料预览。
        块节点=自身；章节节点=递归收集子树全部块（按顺序）。"""
        from sdoc.ui.panels import ROLE_REF as _ROLE_REF

        def collect(it):
            ref = it.data(0, _ROLE_REF)
            if ref:
                return [ref]
            out = []
            for i in range(it.childCount()):
                out += collect(it.child(i))
            return out

        refs = collect(item)
        html = self.renderer.blocks_html(
            refs, self.project,
            brand=self.comboBox.currentText()) \
            if refs else "<div style='color:#888'>该节点无预览内容</div>"
        self.previewBrowser.setHtml(html)

    def _on_project_name_edited(self, text):
        self.project.project_id = text.strip()

    def _on_customer_name_edited(self, text):
        self.project.company = text.strip()

    def _writeback_project_name(self):
        """把项目名称反写回快照 md 头部「项目名称」行（无则追加）。
        只动这一行，其余内容原样保留；原子写入。"""
        name = self.project.project_id.strip()
        path = self.project.source_path
        if not name or not path or not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        out, done, in_header = [], False, True
        for line in lines:
            s = line.strip()
            if s.startswith("## "):
                in_header = False
            if in_header and s.startswith("# COPA 项目快照："):
                line = "# COPA 项目快照：{}".format(name)   # 文档标题同步
            if in_header and s.startswith("| 项目名称 |"):
                line = "| 项目名称 | {} |".format(name)
                done = True
            out.append(line)
        if not done:                      # 头部无该行：在首张表分隔行后追加
            for i, line in enumerate(out):
                if line.strip() == "| 参数 | 值 |" and i + 1 < len(out) \
                        and out[i + 1].strip().startswith("| ---"):
                    out.insert(i + 2, "| 项目名称 | {} |".format(name))
                    done = True
                    break
        if not done:
            return False
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
        return True

    def _on_brand_changed(self, text):
        self.statusBar().showMessage(
            "公司抬头已切到「{}」：点「文件-重新铺默认模板」可按新抬头重铺，"
            "或从左侧「全局-公司介绍-{}」拖入替换".format(
                text, text if text in ("COPA B", "COPA A", "富林泰克") else "…"))

    def _init_data(self):
        """真实库优先：源码运行默认索引 COPA 根的 library（sDocBuilder 并入
        后位于 apps/ 下，取本目录上两级）；冻结运行按 exe 同目录的
        library 定位（与 config/data/template/snapshot 的手动复制约定
        一致）；SDOC_LIBRARY 环境变量可覆盖。目录不存在或构建失败时
        回退占位库。"""
        from sdoc.core.library_store import MockLibraryStore, RealLibraryStore
        pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))      # sdoc/ui -> sDocBuilder 包根
        if "SDOC_LIBRARY" in os.environ:
            root = os.environ["SDOC_LIBRARY"]
        elif getattr(sys, "frozen", False):
            root = os.path.join(os.path.dirname(sys.executable), "library")
        else:
            root = os.path.join(pkg_root, "..", "..", "library")
        self.library_root = os.path.abspath(root)
        try:
            self.store = RealLibraryStore(self.library_root)
            source = "真实库（{} 型号/全局夹）".format(
                sum(len(f) for _, f in self.store.categories()))
        except Exception as err:
            self.store = MockLibraryStore()
            source = "占位库（真实库加载失败：{}）".format(err)
        self.project = MockSnapshotSource().default_project()
        self.renderer = Renderer(self.store)
        self._data_source = source

    def _prefill(self):
        brand = self.comboBox.currentText() if hasattr(self, "comboBox") \
            else ""
        self.outline.load_items(arrangement.default_template(
            self.store, self.project, brand=brand))
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._refresh_hist()
        self.statusBar().showMessage(
            "已按公司抬头「{}」铺默认模板；{}".format(
                brand or "（默认）", getattr(self, "_data_source", "")))

    # ----预览 -> 二次确认 -> 输出----

    def _default_save_dir(self):
        """技术方案默认保存目录：COPA 根的 output（冻结运行取 exe 同目录
        output）；该目录不存在时建议退回包内 OUTPUT_DIR（选路径时用户
        仍可任意指定，落盘前会按所选创建）"""
        if getattr(sys, "frozen", False):
            d = os.path.join(os.path.dirname(sys.executable), "output")
        else:
            pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))      # sdoc/ui -> sDocBuilder
            d = os.path.join(os.path.dirname(os.path.dirname(pkg_root)),
                             "output")            # apps/.. -> COPA 根
        return d if os.path.isdir(d) else OUTPUT_DIR

    def _make_preview(self):
        import shutil
        from datetime import datetime

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from sdoc.core.word_bridge import docx_to_pdf

        items = self.outline.to_items()
        if not items:
            self.statusBar().showMessage("大纲为空：请先从左侧拖入内容")
            return

        # 1) 先落一份真实 docx（预览与正式输出同一产物，确认即转正）
        preview_dir = os.path.join(OUTPUT_DIR, "_preview")
        os.makedirs(preview_dir, exist_ok=True)
        # 唯一时间戳名：避免上轮预览文件句柄/残留导致本轮锁冲突
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        docx_path = os.path.join(preview_dir,
                                 "技术方案_预览_{}.docx".format(stamp))
        pdf_path = os.path.join(preview_dir,
                                "技术方案_预览_{}.pdf".format(stamp))
        for old in os.listdir(preview_dir):     # 清理上轮残留（容错）
            try:
                os.remove(os.path.join(preview_dir, old))
            except OSError:
                pass
        self.statusBar().showMessage("正在生成预览文档…")
        QApplication.processEvents()
        self.renderer.export_docx(items, self.project, preview_dir,
                                  out_path=docx_path,
                                  brand=self.comboBox.currentText())

        # 2) 办公软件渲染为 PDF（探测链 Word->WPS->LibreOffice，失败回退 HTML 摘要）
        pdf_path = os.path.join(preview_dir, "技术方案_预览.pdf")
        self.statusBar().showMessage("正在用 Word/WPS 渲染预览（首次启动较慢，请耐心等待）…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            pdf_ok = docx_to_pdf(docx_path, pdf_path)
        finally:
            QApplication.restoreOverrideCursor()

        # 3) 预览 -> 二次确认 -> 转正
        from sdoc.ui.preview_dialog import PreviewDialog
        stats = self.renderer.preview_stats(items, self.project)
        dlg = PreviewDialog(stats, self,
                            pdf_path=pdf_path if pdf_ok else None,
                            html=self.renderer.preview_html(items,
                                                            self.project))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 输出确认：弹保存对话框选位置与文件名（默认 COPA\output）；
            # 取消保存视为放弃输出，预览文件一并清理
            default = os.path.join(
                self._default_save_dir(),
                "技术方案_{}.docx".format(self.project.project_id))
            final, _filt = QFileDialog.getSaveFileName(
                self, "保存技术方案", default, "Word 文档 (*.docx)")
            if not final:
                for tmp in (docx_path, pdf_path):
                    if os.path.exists(tmp):
                        os.remove(tmp)
                self.statusBar().showMessage("已取消输出（预览文档已清理）")
                return
            if not final.lower().endswith(".docx"):
                final += ".docx"
            save_dir = os.path.dirname(final)
            if save_dir and not os.path.isdir(save_dir):
                os.makedirs(save_dir, exist_ok=True)
            # 项目名称反写快照（仅头部「项目名称」行，原子写入）：
            # 真正落盘时才反写
            if self._writeback_project_name():
                self.statusBar().showMessage(
                    "项目名称已反写快照：{}".format(self.project.project_id))
            shutil.move(docx_path, final)      # 跨盘符选择也能落
            for tmp in (pdf_path,):
                if os.path.exists(tmp):
                    os.remove(tmp)
            # 目录/域落盘更新（Word 不可用时文档仍有效，仅目录待 F9）
            try:
                from sdoc.core.word_bridge import update_fields
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QApplication.processEvents()
                try:
                    update_fields(final)
                finally:
                    QApplication.restoreOverrideCursor()
            except Exception:
                pass
            QMessageBox.information(
                self, "输出完成", "技术方案已生成：\n{}".format(
                    os.path.abspath(final)))
            self.statusBar().showMessage("已输出：{}".format(final))
        else:
            for tmp in (docx_path, pdf_path):
                if os.path.exists(tmp):
                    os.remove(tmp)
            self.statusBar().showMessage("已取消输出（预览文档已清理）")

    # ----编辑历史：撤回/重做（快照式，各 5 步上限）----

    _HIST_LIMIT = 5

    def _snap_history(self):
        md = arrangement.serialize(self.outline.to_items())
        if self._undo_stack and self._undo_stack[-1] == md:
            return                      # 状态没变（无操作落点）：不入栈
        self._undo_stack.append(md)
        if len(self._undo_stack) > self._HIST_LIMIT:
            self._undo_stack.pop(0)     # 只保留最近 5 步
        self._redo_stack.clear()
        self._refresh_hist()

    def _undo_op(self):
        if not self._undo_stack:
            self.statusBar().showMessage("没有可撤回的操作")
            return
        self._redo_stack.append(arrangement.serialize(self.outline.to_items()))
        if len(self._redo_stack) > self._HIST_LIMIT:
            self._redo_stack.pop(0)
        md = self._undo_stack.pop()
        self.outline.load_items(arrangement.parse(md))
        self._refresh_hist()
        self.statusBar().showMessage(
            "已撤回（还可撤 {} 步）".format(len(self._undo_stack)))

    def _redo_op(self):
        if not self._redo_stack:
            self.statusBar().showMessage("没有可重做的操作")
            return
        self._undo_stack.append(arrangement.serialize(self.outline.to_items()))
        if len(self._undo_stack) > self._HIST_LIMIT:
            self._undo_stack.pop(0)
        md = self._redo_stack.pop()
        self.outline.load_items(arrangement.parse(md))
        self._refresh_hist()
        self.statusBar().showMessage(
            "已重做（还可重做 {} 步）".format(len(self._redo_stack)))

    def _promote(self):
        # 重命名编辑进行中不抢 Shift+Tab 键（state() 为普通枚举，用相等比较）
        if self.outline.state() == QAbstractItemView.State.EditingState:
            return
        msg = self.outline.promote()
        self.statusBar().showMessage(msg if msg else "已升级")

    def _demote(self):
        # 重命名编辑进行中不抢 Tab 键
        if self.outline.state() == QAbstractItemView.State.EditingState:
            return
        msg = self.outline.demote()
        self.statusBar().showMessage(msg if msg else "已降级")

    def _delete_current(self):
        # 树内聚焦时 Del 由 OutlinePanel.keyPressEvent 处理（编辑中不误删）
        it = self.outline.currentItem()
        if it is not None:
            self.outline._delete(it)

    def _refresh_hist(self):
        self.actionUndo.setEnabled(bool(self._undo_stack))
        self.actionRedo.setEnabled(bool(self._redo_stack))

    # ----文件操作----

    def _open_snapshot(self):
        from sdoc.core.snapshot_source import CopaSnapshotSource
        start = os.path.dirname(self.project.source_path) \
            if self.project.source_path else os.path.join(
                os.path.dirname(self.library_root), "snapshot")
        path, _ = QFileDialog.getOpenFileName(
            self, "打开快照", start, "Markdown 文件 (*.md)")
        if not path:
            return
        try:
            project = CopaSnapshotSource().open(path)
        except Exception as err:
            QMessageBox.critical(self, "打开快照", "快照解析失败：{}".format(err))
            return
        if not project.entries:
            QMessageBox.warning(self, "打开快照",
                                "快照中没有可用的选型条目。")
            return
        if hasattr(self.store, "match_entry"):
            for e in project.entries:
                e.families = self.store.match_entry(e)
        self.project = project
        self.editProjectName.setText(project.project_id)
        self.editCustomerName.setText(project.company)
        n_hit = sum(len(e.families) for e in project.entries)
        self.pool.set_store(self.store, project=project)
        self._prefill()
        self.statusBar().showMessage(
            "已打开快照：{}（{} 个条目，命中库内型号 {}；未入库型号按选型配置表呈现）"
            .format(os.path.basename(path), len(project.entries), n_hit))

    def _save_arrangement(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存编排稿", "方案编排.md", "Markdown 文件 (*.md)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(arrangement.serialize(self.outline.to_items()))
        self.statusBar().showMessage("编排稿已保存：{}".format(path))

    def _load_arrangement(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开编排稿", "", "Markdown 文件 (*.md)")
        if not path:
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            self.outline.load_items(arrangement.parse(f.read()))
        self.statusBar().showMessage("编排稿已载入：{}".format(path))
