"""COPA_com_Commander 主程序(统领 Desk/Parser/Engine) by Hero Pang.
菜单已接：新建/打开(快照)/保存(快照)/关闭当前/关闭所有/默认输入方式/
使用说明/关于COPA/反馈与优化。

左侧工具栏已接：A=新建报价项目(Desk，同菜单「新建」)；B=sDocBuilder
技术方案编排(在 MDI 内新建可拖动子窗口，独立于报价项目)；
C=报价诊断(Audit，同菜单「工具 -> 报价诊断」，上传报价单做一致性
检查并出批阅副本)。

默认输入方式(设置菜单)：选择需求录入窗口默认显示的输入页签(输入框输入/
下拉菜单输入)，QSettings 持久化记忆，对之后新建/打开快照的项目生效。

保存(Ctrl+S)：当前项目完整快照 -> snapshot/ 下 markdown(Desk 录入与
engine 需求格式参数 + Checklist 选型清单，带保存时间戳)。首次保存弹
对话框指定命名，之后覆盖同一文件；文件路径与项目绑定，由 Commander 记忆。

打开(Ctrl+O)：选择快照 markdown(默认 snapshot/ 下，限 .md) -> 新项目
恢复——Desk 条目卡片照快照重建；快照含选型清单时一并恢复清单窗口与
客户信息，直接进入清单确认环节(Desk 隐藏保留，可回退重修)。
"""
import os
import sys
import threading
from datetime import datetime

# 直接以脚本方式运行时，把项目根目录(COPA 包的上一级)加入 sys.path，
# 使 COPA 包可以常规导入
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFileDialog, QGridLayout,
                               QMainWindow, QMdiArea, QMdiSubWindow,
                               QMessageBox, QVBoxLayout)

# Desk 负责采集/解析/发起；Parser 与 engine 由 Desk(解析)与
# EngineService(计算)装载使用；Checklist 为选型确认/报价输出窗口；
# Snapshot 为项目快照(保存菜单)的采集与 markdown 渲染
from COPA.apps import Snapshot, app_icon
from COPA.apps.About import AboutDialog
from COPA.apps.Audit import AuditPanel, audit_icon
from COPA.apps.Checklist import Checklist
from COPA.apps.contract import _failure_reason
from COPA.apps.Desk import (DEFAULT_INPUT_GUI, DEFAULT_INPUT_TEXT, Desk,
                            EngineService, GuiCard, QuoteCard,
                            default_input_mode, set_default_input_mode)
from COPA.apps.Feedback import FeedbackDialog
from COPA.apps.Manual import ManualDialog
from COPA.apps.Ui_commander import Ui_MainWindow

class Commander(QMainWindow, Ui_MainWindow):

    # 选型批次完成信号(project_id, results)：worker线程发出，
    # 跨线程发射自动队列投递，槽在GUI线程执行
    selectionDone = Signal(str, object)

    # 选型未通过的终态：ERROR(异常/缺参) 与 NO_MATCH(数据库无匹配方案)
    _BLOCKING_STATUSES = ("ERROR", "NO_MATCH")

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Ui 在 MainWindow 上遗留了裸 background-color 级联样式：祖先样式表
        # 会迫使全部后代改走样式表渲染(失去 Win11 原生圆角)并压制调色板设置，
        # 且 MDI 区底色已由 setBackground 单独指定，故清除之
        self.setStyleSheet("")

        # 项目表：项目ID -> Desk 控件(插入序即创建序)
        self._projects = {}

        # 当前项目的项目ID(最近创建或最近激活的子窗口)
        self._current_project_id = None

        # 数据接收变量："{项目ID}_{条目ID}" -> engine 选型结果 dict
        self._quote_data = {}

        # 清单子窗口表：项目ID -> Checklist 控件(每项目一个，复用重载)
        self._checklists = {}

        # 各项目最近一次发起选型的条目数据(清单装载数量/复选框状态用)
        self._project_entries = {}

        # 快照状态(保存菜单)：项目ID -> 已保存的 md 文件路径(项目内覆盖保存)
        self._snapshot_paths = {}

        # 项目ID -> 首次保存时间文本(快照头部的「首次保存时间」)
        self._snapshot_created = {}

        # 清单子窗口标题业务名(如 选型清单)，首个 Checklist 创建时提取
        self._checklist_title_base = ""

        # engine 选型计算服务：全局共享(数据库只加载一次)；
        # 批次在后台线程串行执行，GUI 不冻结
        self._engine_service = EngineService()
        self._engine_busy = False

        # 子窗口标题业务名(如 需求录入)，首个 Desk 创建时从其 Ui 标题提取；
        # 初始为空串而非 None，保证类型恒为 str
        self._title_base = ""

        # MDI 子窗口区：每个 Desk 一个子窗口，独立标题栏、可拖动、可关闭；
        # 背景与主窗体同色(rgb(117,117,117))
        self.mdi = QMdiArea(self.centralwidget)
        self.mdi.setBackground(QBrush(QColor(117, 117, 117)))
        layout = QVBoxLayout(self.centralwidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mdi)

        # 使用说明指引窗口：非模态单例，首次触发时创建并复用
        self._manual = None
        self._llm_workflow = None

        # 报价诊断面板(Audit)：与 Desk 一样挂 MDI 子窗口，单例复用；
        # _audit_sub 记住它的子窗口，关掉只是隐藏（批阅线程与结果都保留）
        self._audit = None
        self._audit_sub = None

        # 菜单：新建/打开/保存/关闭当前/关闭所有 + 默认输入方式 +
        # 使用说明/关于COPA + 反馈与优化
        self.actionNew.triggered.connect(self._new_project)
        # 新建技术方案(Shift+O)：与工具栏 B 同槽，新建一个 sDocBuilder
        # 技术方案编排子窗口
        self.actionNSD.triggered.connect(self._new_sdoc)
        self.actionOpen.triggered.connect(self._open_snapshot)
        # 打开与保存同为快照语义，补设标准快捷键(Ui 模板未定义)
        self.actionOpen.setShortcut("Ctrl+O")
        self.actionSave.triggered.connect(self._save_snapshot)
        self.actionCloseCurrent.triggered.connect(self._close_current)
        self.actionCloseAll.triggered.connect(self._close_all)
        self.setWindowIcon(app_icon())
        self.actionDefaultInput.triggered.connect(self._choose_default_input)
        self.actionManual.triggered.connect(self._open_manual)
        self.actionInfo.triggered.connect(self._open_about)
        self.actionFeedback.triggered.connect(self._open_feedback)

        # 左侧工具栏(图标在上文字在下)：选型报价=新建 Desk 报价项目(与
        # 菜单「新建」同一路径)；技术方案=sDocBuilder 编排子窗口(每点
        # 一次新建一个)。Designer 不支持工具栏内嵌 QToolButton(保存即
        # 丢弃)，故按钮用 QAction 结构(actionToolA/B)，图标在 Designer
        # 动作编辑器里设置即可
        self.actionToolA.triggered.connect(self._new_project)
        self.actionToolB.triggered.connect(self._new_sdoc)
        self.actionLlmChat.triggered.connect(self._open_llm_chat)
        # 工具栏 C / 菜单「工具 -> 报价诊断」：图标用人工选好的那个；
        # Designer 里的 theme 图标在 Windows 可能取不到，取不到才回退
        self.actionToolC.triggered.connect(self._open_audit)
        if self.actionToolC.icon().isNull():
            self.actionToolC.setIcon(audit_icon())

        # 激活的子窗口即「当前项目」，供关闭当前定位
        self.mdi.subWindowActivated.connect(self._on_sub_activated)

        # worker 线程完成 -> 队列投递回 GUI 线程归档
        self.selectionDone.connect(self._on_selection_done)

        # 默认创建一个 Desk 控件
        self._new_project()

    # ====项目管理====

    def _open_llm_chat(self):
        """对话选型：与「选型报价」一致，挂成 MDI 子窗口（单例复用）。

        对话选型与手工录入是同一条流水线的两个入口：启动时默认开着的
        那张空白「需求录入」在这里收掉，免得两个入口并排争位置。已经
        录过参数的项目不动——那是正在做的工作，不能替用户丢。
        """
        if self._llm_workflow is None:
            from COPA.apps.LlmWorkflow import LlmQuoteWorkflow
            try:
                self._llm_workflow = LlmQuoteWorkflow(
                    self, mdi=self.mdi, can_start=lambda: not self._engine_busy)
            except Exception as exc:
                # 规则或配置缺失必须显式失败，而不是打开一个空壳窗口。
                QMessageBox.critical(self, "LLM 模块不可用", str(exc))
                return
            self._llm_workflow.statusChanged.connect(self.statusbar.showMessage)
        self._close_empty_desks()
        self._llm_workflow.open()

    @staticmethod
    def _value_is_blank(value):
        if isinstance(value, (list, tuple, dict, set)):
            return len(value) == 0
        return not value

    @classmethod
    def _card_is_blank(cls, card):
        """卡片是否还是空的。两张卡片创建时各带一个空壳（类型下拉有默认
        首项），所以不能按容器条目数判断，要看卡片内容。"""

        if isinstance(card, QuoteCard):
            data = card.getEntryData()
            if str(data.get("description") or "").strip():
                return False
            return not any(data.get(key) for key in (
                "metrology", "high_precision", "Ex_P", "digital"))
        if isinstance(card, GuiCard):
            data = card.getEntryData()
            if any(data.get(key) for key in (
                    "metrology", "high_precision", "Ex_P", "digital")):
                return False
            for key, value in (data.get("structured") or {}).items():
                if key == "item_type":
                    continue
                if not cls._value_is_blank(value):
                    return False
            return True
        return False

    @classmethod
    def _desk_is_empty(cls, desk):
        """需求录入窗是否还是空白：两种录入方式的所有卡片都是空壳。"""

        for name in ("cardContainerLayout", "guiCardContainerLayout"):
            layout = getattr(desk, name, None)
            if layout is None:
                continue
            for index in range(layout.count()):
                item = layout.itemAt(index)
                card = item.widget() if item is not None else None
                if card is None:
                    continue
                if not cls._card_is_blank(card):
                    return False
        return True

    def _close_empty_desks(self):
        for project_id, desk in list(self._projects.items()):
            if not self._desk_is_empty(desk):
                continue
            sub = self._sub_of(desk)
            # 已经隐藏的窗口交给排队中的清理，重复 close 会排两次删除。
            if sub is not None and sub.isVisible():
                # 走 Close 事件 -> _remove_sub_window 的统一清理路径。
                sub.close()

    def _audit_panel_alive(self) -> bool:
        """诊断面板是否还活着。

        面板和子窗口都可能被 Qt 侧销毁（关闭流程、统一清理路径），而
        Python 侧仍握着引用——只剩一层空壳，一碰就
        RuntimeError: Internal C++ object already deleted。凡是触碰
        self._audit / self._audit_sub 的地方都先过这两道。
        """
        return self._audit is not None and shiboken6.isValid(self._audit)

    def _audit_sub_alive(self) -> bool:
        return self._audit_sub is not None and shiboken6.isValid(self._audit_sub)

    def _mount_audit_sub(self, panel):
        """把诊断面板挂成 MDI 子窗口，并钉住「关闭即隐藏」的语义。"""

        sub = self.mdi.addSubWindow(panel)
        sub.setWindowIcon(self._transparent_icon())
        # addSubWindow 默认打开 WA_DeleteOnClose：点一次标题栏 X，子窗口
        # 连面板一起被 deleteLater，之后再点工具栏 C 就只剩空壳
        # （RuntimeError: QMdiSubWindow already deleted）。诊断结果是
        # 「收起还要接着看」的东西，这个属性必须是关的。
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        sub.move(0, 0)
        viewport = self.mdi.viewport().size()
        sub.resize(min(panel.width(), viewport.width()),
                   min(panel.height(), viewport.height()))
        sub.installEventFilter(self)
        panel.show()
        self._audit_sub = sub
        return sub

    def _open_audit(self):
        """工具栏 C / 菜单「工具 -> 报价诊断」：与「选型报价」同一装配路径，
        挂成 MDI 子窗口（单例复用）。批阅线程由面板自治，Commander 只负责
        装配与前置；子窗口被关掉后只是隐藏，再点回来接着看结果。

        自愈：面板或子窗口任一被外部销毁过，就按「能救的救、救不了的
        重建」补回来，保证这个入口永远打得开。"""
        rebuilt = self._audit is not None and not self._audit_panel_alive()
        if not self._audit_panel_alive():
            # 面板已被销毁：里面的批阅结果一起没了，只能重建一份新面板
            self._audit = None
        if not self._audit_sub_alive():
            self._audit_sub = None

        if self._audit is None:
            self._audit = AuditPanel()
            self._mount_audit_sub(self._audit)
        elif self._audit_sub is None:
            # 面板还在、只是子窗口没了：重新挂一次，结果不丢
            self._mount_audit_sub(self._audit)

        if self._audit_sub is not None:
            self._audit_sub.show()
            # 子窗口关闭时会把内部控件一起 close()，控件因此带上「显式隐藏」
            # 标记；只 show 子窗口会得到一个只剩标题栏的空白壳。这里必须把
            # 面板本身也 show 一次，才能真正把内容带回来。
            self._audit.show()
            self._audit_sub.raise_()
            self._audit_sub.setFocus()
        self.statusbar.showMessage(
            "报价诊断已打开（上一次被销毁，已重建面板）" if rebuilt
            else "报价诊断已打开")

    def closeEvent(self, event):
        workflow = self._llm_workflow
        if workflow is not None:
            # 对话窗体可能已被用户点 X 销毁（子窗口带 WA_DeleteOnClose），
            # 直接读 busy 会命中野指针。
            dialog = workflow.dialog
            active = dialog is not None and shiboken6.isValid(dialog) and dialog.busy
            if workflow.busy or active:
                self.statusbar.showMessage("对话或选型正在处理，请完成后关闭COPA")
                event.ignore()
                return
            workflow.close()
        super().closeEvent(event)

    def _next_project_id(self):
        """新项目ID：首个为 Untitled (1)，其后依次 Untitled (2)、Untitled (3)..."""
        if "Untitled (1)" not in self._projects:
            return "Untitled (1)"

        n = 2

        while "Untitled ({})".format(n) in self._projects:
            n += 1

        return "Untitled ({})".format(n)

    def _new_project(self):
        project_id = self._next_project_id()
        self._register_project(project_id, Desk())
        self.statusbar.showMessage("已新建报价项目")

    def _new_sdoc(self):
        """工具栏 B：新建 sDocBuilder 技术方案编排子窗口——与 Desk 同一
        装配路径挂入 MDI(可拖动/可关闭)，但不入项目表(不参与快照/选型，
        点 X 走事件过滤器统一清理)；每点一次新建一个。
        窗体设计尺寸 1120x760 大于 MDI 视口时收缩到视口，可最大化/拉伸"""
        try:
            # 注意：COPA.apps.sDocBuilder 是包，MainWindow 在包内的
            # sDocBuilder.py 入口模块（原名独立项目 main.py）
            from COPA.apps.sDocBuilder.sDocBuilder import MainWindow \
                as SdocMainWindow
        except Exception as err:
            QMessageBox.critical(self, "sDocBuilder",
                                 "sDocBuilder 装载失败：{}".format(err))
            return

        sdoc = SdocMainWindow()
        sub = self.mdi.addSubWindow(sdoc)
        sub.setWindowIcon(self._transparent_icon())
        # 与清单子窗口一致左上顶格；初始尺寸取 sDoc 设计尺寸(.ui resize
        # 1120x760)与 MDI 视口的较小值——QMdiSubWindow.sizeHint 会缩水
        # (实测 1047x379)，不能用它
        sub.move(0, 0)
        viewport = self.mdi.viewport().size()
        sub.resize(min(sdoc.width(), viewport.width()),
                   min(sdoc.height(), viewport.height()))
        sub.installEventFilter(self)
        sdoc.show()
        self.statusbar.showMessage("sDocBuilder 技术方案编排已打开")

    def _register_project(self, project_id, desk):
        """把新 Desk 挂入项目表：标题基名提取、选型信号接线、子窗口装配
        并前置；打开快照恢复项目时复用同一装配路径"""
        if not self._title_base:
            self._title_base = self._strip_title_base(desk.windowTitle())

        # 锁定 Designer 初始尺寸(630x450)：子窗口随之定形，
        # 不随主窗拖拉与子窗边框拖拽改变大小
        desk.setFixedSize(desk.size())

        # Desk 发起选型 -> Commander 后台计算并归档；sid 绑定进默认参数，
        # 避免 lambda 晚绑定读到别的项目
        desk.selectionRequested.connect(
            lambda entries, sid=project_id: self._start_selection(sid, entries)
        )

        self._projects[project_id] = desk
        sub = self.mdi.addSubWindow(desk)
        sub.setWindowIcon(self._transparent_icon())
        sub.setFixedSize(sub.sizeHint())
        # 子窗口点 X 关闭时经事件过滤器走统一清理
        sub.installEventFilter(self)
        desk.show()

        self._current_project_id = project_id
        self._refresh_sub_titles()

    def _close_current(self):
        if self.mdi.activeSubWindow() is None:
            self.statusbar.showMessage("当前没有可关闭的报价项目")
            return

        # 走子窗口统一关闭路径(Close事件 -> _remove_sub_window)
        self.mdi.closeActiveSubWindow()

    def _close_all(self):
        # 逐个触发Close事件，同样经事件过滤器统一清理
        self.mdi.closeAllSubWindows()

    def _open_snapshot(self):
        """打开(Ctrl+O)：选择快照 markdown(默认 snapshot/ 目录，限 .md)->
        解析后恢复为新项目：Desk 条目卡片照快照重建；快照含选型清单时
        一并恢复清单窗口与客户信息，直接进入清单确认环节(Desk 隐藏保留
        可回退)；仅录入阶段的快照(无清单)则恢复 Desk 并保持前置"""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开快照", Snapshot.snapshot_dir(), "Markdown 文件 (*.md)")

        if not path:
            return

        try:
            data = Snapshot.parse_snapshot(path)
        except Exception as err:
            QMessageBox.critical(self, "打开快照", "快照解析失败：{}".format(err))
            return

        entries = data.get("entries") or []
        snapshot = data.get("checklist") or {}
        items = snapshot.get("items") or []

        if not entries and not items:
            QMessageBox.warning(self, "打开快照", "快照中没有可恢复的内容。")
            return

        # 项目ID沿用快照记录名；与现有项目撞名时追加「- 打开」序号区分
        project_id = data.get("project_id") or self._next_project_id()

        if project_id in self._projects:
            base = "{} - 打开".format(project_id)
            n = 2
            candidate = base

            while candidate in self._projects:
                candidate = "{} ({})".format(base, n)
                n += 1

            project_id = candidate

        desk = Desk()
        self._register_project(project_id, desk)
        desk.restore_entries(entries, bool(data.get("onsite_service")))

        if items:
            checklist = self._attach_checklist(project_id)
            checklist.load_snapshot(snapshot, items)

            # 与选型完成后的编排一致：清单接管确认环节，Desk 隐藏保留
            desk_sub = self._sub_of(desk)

            if desk_sub is not None:
                desk_sub.hide()

            cl_sub = self._sub_of(checklist)

            if cl_sub is not None:
                self.mdi.setActiveSubWindow(cl_sub)

        self.statusbar.showMessage(
            "{} 快照已打开：{}".format(project_id, path))

    def _save_snapshot(self):
        """保存(Ctrl+S)：当前项目完整快照 -> snapshot/ 下 markdown。
        首次保存弹对话框指定命名并记忆路径，之后覆盖同一文件；
        每次写入都刷新文档头部的保存时间戳"""
        project_id = self._current_project_id
        desk = self._projects.get(project_id) if project_id else None

        if desk is None:
            self.statusbar.showMessage("当前没有可保存的报价项目")
            return

        path = self._snapshot_paths.get(project_id)

        if path is None:
            # 首次保存：默认落 snapshot/ 下「项目ID_时刻.md」，命名可改
            chosen, _ = QFileDialog.getSaveFileName(
                self, "保存快照", Snapshot.suggest_path(project_id),
                "Markdown 文件 (*.md)",
            )

            if not chosen:
                return

            if not chosen.lower().endswith(".md"):
                chosen += ".md"

            path = chosen

        try:
            path = Snapshot.save_snapshot(
                path, project_id, desk,
                checklist=self._checklists.get(project_id),
                created_at=self._snapshot_created.get(project_id),
            )
        except Exception as err:
            QMessageBox.critical(self, "保存快照", "快照保存失败：{}".format(err))
            return

        # 保存成功才记忆路径/首次时间：本次即首次时，首次时间取当前时刻
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._snapshot_paths[project_id] = path
        self._snapshot_created.setdefault(project_id, now)
        self.statusbar.showMessage("{} 快照已保存：{}".format(project_id, path))

    def _ensure_snapshot_path(self, project_id):
        """出单前确保项目有一份快照，返回路径；失败返回空串。

        静默保存、不弹命名框：用户此刻正在出报价，半路弹「保存快照」会打断
        他。默认名与保存菜单一致（项目ID_时刻.md），之后 Ctrl+S 仍走原来的
        对话框/覆盖逻辑。拿不到路径时这份单就没有基线，不影响出报价。
        """
        if not project_id:
            return ""

        path = self._snapshot_paths.get(project_id)

        if path and os.path.exists(path):
            return path

        desk = self._projects.get(project_id)

        if desk is None:
            return ""

        try:
            saved = Snapshot.save_snapshot(
                path or Snapshot.suggest_path(project_id), project_id, desk,
                checklist=self._checklists.get(project_id),
                created_at=self._snapshot_created.get(project_id),
            )
        except Exception:               # 存不下也只是没基线，别拦住出单
            return ""

        self._snapshot_paths[project_id] = saved
        self._snapshot_created.setdefault(
            project_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return saved

    def _choose_default_input(self):
        """设置 -> 默认输入方式：选择需求录入窗口默认显示的输入页签并
        记忆(QSettings 持久化)；对之后新建/打开快照的项目生效，
        已开窗口的页签不回改"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("默认输入方式")
        box.setText("需求录入窗口默认显示哪种输入页签？")
        box.setInformativeText(
            "当前默认：{}；此设置对之后新开的项目生效。".format(
                default_input_mode()
            )
        )

        # addButton 实际返回 QPushButton，但 clickedButton 契约为
        # QAbstractButton：显式放宽键类型，消除静态检查报错
        mode_buttons: dict[QAbstractButton, str] = {
            box.addButton(mode, QMessageBox.ButtonRole.YesRole): mode
            for mode in (DEFAULT_INPUT_TEXT, DEFAULT_INPUT_GUI)
        }
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        mode = mode_buttons.get(box.clickedButton())

        if mode is None:
            return

        set_default_input_mode(mode)
        self.statusbar.showMessage("默认输入方式已设为：{}".format(mode))

    def _open_feedback(self):
        """反馈与优化：模态对话框收集问题描述，发送时自动附带全部项目
        的选型数据与诊断信息(附件由 Feedback 内部组装，不向用户展示)；
        模态阻塞主窗交互，保证收集期间项目数据不被并发修改"""
        FeedbackDialog(self).exec()

    def _open_manual(self):
        """设置 -> 使用说明：非模态指引窗口(单例复用)，可边看指引边在
        实际窗口操作；重复触发仅前置已有窗口"""
        if self._manual is None:
            self._manual = ManualDialog(self)

        self._manual.show()
        self._manual.raise_()
        self._manual.activateWindow()

    def _open_about(self):
        """设置 -> 关于COPA：模态展示版本/开发者/反馈邮箱等静态信息"""
        AboutDialog(self).exec()

    def eventFilter(self, watched, event):
        # 子窗口关闭：延迟到关闭流程结束后清理，避免在 Close 事件中途拆结构
        if (event.type() == QEvent.Type.Close
                and isinstance(watched, QMdiSubWindow)):
            # 诊断面板收起即隐藏：批阅线程可能还在跑，销毁窗口会崩。
            # 判等同时看子窗口和面板——任一侧引用过期（比如子窗口被外部
            # 重建过）都不会漏判成「可以删」，否则下一次点工具栏 C 直接
            # 撞 Internal C++ object already deleted。
            if watched is self._audit_sub or (
                    self._audit_panel_alive()
                    and watched.widget() is self._audit):
                watched.hide()
                return True
            QTimer.singleShot(0, lambda: self._remove_sub_window(watched))

        return super().eventFilter(watched, event)

    @staticmethod
    def _transparent_icon():
        """16x16 全透明占位图标：子窗口标题栏不显示图标(COPA 图标仅用于
        任务栏/主窗/弹窗；图标为空时会回落 Qt logo，故用透明图占位)"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        return QIcon(pixmap)

    @staticmethod
    def _strip_title_base(title):
        """Ui 窗体标题 -> 标题业务名：兼容模板式「需求录入 - 」(剥尾分隔符)
        与完整式「系统名 - 选型清单」(取末段)；多窗口按「业务名 - 项目ID」还原"""
        title = title.rstrip()

        if title.endswith("-"):
            return title[:-1].rstrip()

        return title.rsplit(" - ", 1)[-1]

    def _remove_sub_window(self, sub):
        # 排队清理期间状态可能变了（窗口被重建/已销毁）：先过一遍有效性，
        # 再挡掉诊断面板——它是单例，只能隐藏不能删，删了入口就失效。
        if not shiboken6.isValid(sub):
            return
        widget = sub.widget()
        if self._audit is not None and widget is self._audit:
            sub.hide()
            return
        project_id = self._project_of(widget)

        if project_id is not None:
            # Desk 项目窗口：清项目与在途条目(已归档的 _quote_data 保留)
            del self._projects[project_id]
            self._project_entries.pop(project_id, None)
            self._snapshot_paths.pop(project_id, None)
            self._snapshot_created.pop(project_id, None)

            # 项目的清单子窗口一并关闭(走同一 Close 路径清理)；
            # 已无窗口则直接回收控件
            checklist = self._checklists.pop(project_id, None)

            if checklist is not None:
                checklist_sub = self._sub_of(checklist)

                if checklist_sub is not None:
                    checklist_sub.close()
                else:
                    checklist.deleteLater()
        else:
            # 清单子窗口关闭，按是否输出过分流：
            # 未输出 -> 视为回退，复显所属Desk继续修改；
            # 已输出 -> 项目完成，连同Desk整体关闭(Desk清理路径统一收尾)
            for sid, cl in list(self._checklists.items()):
                if cl is widget:
                    del self._checklists[sid]
                    desk = self._projects.get(sid)

                    if getattr(widget, "output_completed", False):
                        if desk is not None:
                            desk_sub = self._sub_of(desk)

                            if desk_sub is not None:
                                desk_sub.close()
                    elif desk is not None:
                        desk_sub = self._sub_of(desk)

                        if desk_sub is not None:
                            desk_sub.show()
                            self.mdi.setActiveSubWindow(desk_sub)

                    break

        self.mdi.removeSubWindow(sub)
        sub.deleteLater()

        if widget is not None:
            widget.deleteLater()

        active = self.mdi.activeSubWindow()
        self._current_project_id = (
            self._project_of(active.widget())
            if active is not None else None
        )
        self._refresh_sub_titles()
        self._refresh_checklist_titles()

    def _on_sub_activated(self, sub):
        if sub is None:
            return

        project_id = self._project_of(sub.widget())

        if project_id is not None:
            self._current_project_id = project_id

    def _project_of(self, desk):
        for project_id, d in self._projects.items():
            if d is desk:
                return project_id

        return None

    def _sub_of(self, desk):
        for sub in self.mdi.subWindowList():
            if sub.widget() is desk:
                return sub

        return None

    def _refresh_sub_titles(self):
        """子窗口标题动态刷新：仅一个子窗口时只显示业务名(需求录入)；
        多个子窗口时各自追加「 - 项目ID」区分，关到只剩一个时自动还原"""
        if not self._title_base or not self._projects:
            return

        with_suffix = len(self._projects) > 1

        for project_id, desk in self._projects.items():
            sub = self._sub_of(desk)

            if sub is None:
                continue

            if with_suffix:
                sub.setWindowTitle(
                    "{} - {}".format(self._title_base, project_id))
            else:
                sub.setWindowTitle(self._title_base)

    def _refresh_checklist_titles(self):
        """清单子窗口标题：单个只显示业务名(选型清单)，多个追加项目ID区分，
        关到只剩一个时自动还原"""
        if not self._checklist_title_base or not self._checklists:
            return

        with_suffix = len(self._checklists) > 1

        for project_id, checklist in self._checklists.items():
            sub = self._sub_of(checklist)

            if sub is None:
                continue

            if with_suffix:
                sub.setWindowTitle("{} - {}".format(
                    self._checklist_title_base, project_id))
            else:
                sub.setWindowTitle(self._checklist_title_base)

    def _attach_checklist(self, project_id):
        """创建(或复用)该项目的清单子窗口并前置(可能处于回退后的隐藏态)；
        结果装载由调用方负责(选型结果 load_results / 快照 load_snapshot)"""
        checklist = self._checklists.get(project_id)

        if checklist is None:
            checklist = Checklist()
            # 出单时把「本项目快照在哪」告诉清单：报价成功后基线要追加进去
            checklist.snapshot_provider = (
                lambda sid=project_id: self._ensure_snapshot_path(sid))

            if not self._checklist_title_base:
                self._checklist_title_base = self._strip_title_base(
                    checklist.windowTitle())

            checklist.rollbackRequested.connect(
                lambda sid=project_id: self._rollback_checklist(sid))
            checklist.outputSucceeded.connect(
                lambda sid=project_id: self._on_output_done(sid))
            self._checklists[project_id] = checklist
            sub = self.mdi.addSubWindow(checklist)
            sub.setWindowIcon(self._transparent_icon())
            # 清单不定形(与Desk不同)：条目多时需要拉高滚动查看，
            # 保持独立运行时的自由拉伸，仅初始位置与Desk一致左上顶格
            sub.move(0, 0)
            sub.installEventFilter(self)
            checklist.show()
        else:
            # 复用已开窗口：前置(可能处于回退后的隐藏态)
            sub = self._sub_of(checklist)

            if sub is not None:
                sub.show()
                self.mdi.setActiveSubWindow(sub)

        self._refresh_checklist_titles()
        return checklist

    def _open_checklist(self, project_id, results):
        """打开(或复用)该项目的选型清单子窗口并装载结果，同时隐藏该项目
        Desk(隐藏而非关闭，保留回退重修的基础)；人工确认/输出报价由
        Checklist 自治完成，经信号通知上层编排窗口"""
        checklist = self._attach_checklist(project_id)
        checklist.load_results(results, self._project_entries.get(project_id))

        # 清单接管确认环节：Desk 隐藏保留
        desk = self._projects.get(project_id)

        if desk is not None:
            desk_sub = self._sub_of(desk)

            if desk_sub is not None:
                desk_sub.hide()

        self.statusbar.showMessage("{} 选型清单已就绪".format(project_id))

    def _rollback_checklist(self, project_id):
        """清单回退：隐藏清单、复显该项目 Desk 供修改(项目与数据均不动)"""
        checklist = self._checklists.get(project_id)

        if checklist is not None:
            cl_sub = self._sub_of(checklist)

            if cl_sub is not None:
                cl_sub.hide()

        desk = self._projects.get(project_id)

        if desk is not None:
            desk_sub = self._sub_of(desk)

            if desk_sub is not None:
                desk_sub.show()
                self.mdi.setActiveSubWindow(desk_sub)

        self.statusbar.showMessage("{} 已回退需求录入".format(project_id))

    def _save_snapshot_silent(self, project_id):
        """报价输出完成后的静默快照：不弹对话框，直接落 snapshot/ 下
        「项目ID_时刻.md」。与 Ctrl+S 保存槽共用同一路径/首次时间记忆——
        项目此前手动保存过则覆盖同一文件，未保存过则静默建档，之后
        Ctrl+S 也在同一文件上覆盖，两种入口不产生重复快照。
        返回写入路径；Desk 不存在或写盘失败返回 None(静默，不弹窗)"""
        desk = self._projects.get(project_id)

        if desk is None:
            return None

        path = self._snapshot_paths.get(project_id)

        if path is None:
            path = Snapshot.suggest_path(project_id)

        try:
            path = Snapshot.save_snapshot(
                path, project_id, desk,
                checklist=self._checklists.get(project_id),
                created_at=self._snapshot_created.get(project_id),
            )
        except Exception:
            return None

        # 与 _save_snapshot 同口径记忆：本次即首次时，首次时间取当前时刻
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._snapshot_paths[project_id] = path
        self._snapshot_created.setdefault(project_id, now)
        return path

    def _on_output_done(self, project_id):
        """清单完成一次报价输出：窗口保留(可换抬头再输出)；
        此后关闭清单窗口即连同 Desk 整体收尾。同时静默保存项目快照，
        与 Ctrl+S 保存槽共用同一路径记忆，快照落 snapshot/ 目录"""
        saved = self._save_snapshot_silent(project_id)

        if saved is not None:
            self.statusbar.showMessage(
                "{} 报价输出完成；关闭清单窗口即完成本项目。"
                "项目快照已保存至COPA\\snapshot中，可随时查看。".format(project_id))
        else:
            self.statusbar.showMessage(
                "{} 报价输出完成，但项目快照保存失败，"
                "可稍后 Ctrl+S 手动保存".format(project_id))

    # ====选型计算编排====

    def _start_selection(self, project_id, entries):
        """Desk 发起选型：整批次丢后台线程串行计算，完成经信号回 GUI 线程。
        同一时刻只跑一个批次(engine 服务共享，串行免除并发隐患)"""
        if self._engine_busy or (self._llm_workflow is not None and self._llm_workflow.busy):
            self.statusbar.showMessage("选型计算进行中，请稍候再试")
            return

        self._engine_busy = True
        self.statusbar.showMessage("正在选型计算…")
        # 条目随发起留存：完成后清单按 quote_id 关联数量/复选框状态
        self._project_entries[project_id] = entries
        threading.Thread(
            target=self._selection_worker,
            args=(project_id, entries),
            daemon=True
        ).start()

    def _selection_worker(self, project_id, entries):
        try:
            results = self._engine_service.run_batch(entries)
        except Exception as err:
            # 装载失败等批次级异常：逐条转为 ERROR 结果，不让线程静默死亡
            results = [
                {
                    "quote_id": entry["quote_info"]["quote_id"],
                    "item_type": entry.get("item_type"),
                    "status": "ERROR",
                    "error": "选型计算异常：{}".format(err),
                }
                for entry in entries
            ]

        self.selectionDone.emit(project_id, results)

    def _on_selection_done(self, project_id, results):
        self._engine_busy = False
        self._receive_results(project_id, results)

        failures = [r for r in results
                    if r.get("status") in self._BLOCKING_STATUSES]
        ok = len(results) - len(failures)
        self.statusbar.showMessage(
            "{} 选型完成：共 {} 项（成功 {}，失败 {}）".format(
                project_id, len(results), ok, len(failures)
            )
        )

        if failures:
            self._show_selection_failures(failures)
            return   # 有失败：流程到此终止，不进入清单环节

        # 全部成功 -> 打开该项目的选型清单；Desk 已在计算期间被关闭时
        # 不再开窗(结果仍已归档 _quote_data)
        if project_id in self._projects:
            self._open_checklist(project_id, results)

    def _show_selection_failures(self, failures):
        """选型未通过弹窗：逐条列出 quote_id 与具体原因(缺参/取值非法走
        ERROR 明细，数据库无匹配走诊断里的环节说明)，仅「返回修改」按钮"""
        lines = []

        for r in failures:
            lines.append("条目 {}：{}".format(
                r.get("quote_id") or 0, _failure_reason(r)))

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("选型失败")
        box.setText(
            "以下 {} 个条目选型失败：\n\n{}\n\n请返回修改后重新选型。".format(
                len(failures), "\n".join(lines)))
        box.addButton("返回修改", QMessageBox.ButtonRole.RejectRole)
        # QMessageBox 内部为网格布局，图标默认随首行文字顶对齐；
        # 多行文本时改为相对整个文本块垂直居中。layout() 静态类型为
        # QLayout|None 且基类无 itemAtPosition，isinstance 收窄后调用
        layout = box.layout()

        if isinstance(layout, QGridLayout):
            icon_item = layout.itemAtPosition(0, 0)

            if icon_item is not None:
                icon_item.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        box.exec()

    # ====数据接收====

    def _receive_results(self, project_id, results):
        """engine 经 Desk 回传的全部选型结果 -> 按「项目ID_条目ID」存档"""
        for result in results or []:
            quote_id = (result or {}).get("quote_id") or 0
            self._quote_data["{}_{}".format(project_id, quote_id)] = result


if __name__ == "__main__":
    # 启动序列统一在 COPA.launch 里，打包入口也指向它——那里把业务模块的
    # 导入挪到了启动画面之后。此处保留只为让 `py -m COPA.main` 仍可运行。
    from COPA.launch import main as _launch

    raise SystemExit(_launch())
