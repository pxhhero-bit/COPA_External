"""对话 -> 内存选型 -> 原有 Checklist；不产生网络请求。

窗体形态与「选型报价」一致：对话窗与清单窗都以 MDI 子窗口挂在主窗体里，
不再弹独立对话框。
"""
import copy
import threading
import time

import shiboken6
from PySide6.QtCore import QObject, QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QMdiArea, QMdiSubWindow, QWidget

from COPA import cli_quote
from COPA.apps.Checklist import Checklist
from COPA.apps.LlmChat import LlmChat


def _widget_parent(parent: QObject | None) -> QWidget | None:
    """``QObject.parent()`` 返回 QObject，Qt 控件只接受 QWidget 做父窗口。"""

    return parent if isinstance(parent, QWidget) else None


def _transparent_icon() -> QIcon:
    """标题栏图标留空，和 Desk / Checklist 子窗口保持一致。"""

    pixmap = QPixmap(1, 1)
    pixmap.fill(Qt.GlobalColor.transparent)
    return QIcon(pixmap)


class LlmQuoteWorkflow(QObject):
    selectionFinished = Signal(object)
    statusChanged = Signal(str)

    # 「正在生成选型清单」这句提示至少停留这么久才换窗口。engine 很快时
    # 若立刻切走，用户只看到闪一下，会以为程序卡了或没反应。
    CHECKLIST_MIN_VISIBLE_MS = 1500

    # 清单与对话窗错开这么多像素：两个标题栏都露出来，一眼能看出是叠层。
    CHECKLIST_OFFSET = 24

    def __init__(self, parent=None, *, dialog=None, session_root=None, can_start=None, mdi=None):
        super().__init__(parent)
        self.dialog: LlmChat = dialog or LlmChat(_widget_parent(parent))
        self.mdi: QMdiArea | None = mdi
        self.checklist: Checklist | None = None
        self.run: cli_quote.QuoteRun | None = None
        self.busy = False
        self.session_root = session_root
        self.can_start = can_start or (lambda: True)
        self._chat_sub: QMdiSubWindow | None = None
        self._checklist_sub: QMdiSubWindow | None = None
        self._handoff_at: float | None = None
        # 提示停留计时：默认 QTimer 是 CoarseTimer，1.5s 会被允许提前 ~5%
        # 甚至更多，实测差到 160ms；这里用精确计时器，别让节奏跑偏。
        self._checklist_timer = QTimer(self)
        self._checklist_timer.setSingleShot(True)
        self._checklist_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._checklist_timer.timeout.connect(self._present_checklist)
        self.dialog.payloadConfirmed.connect(self.start_selection)
        self.selectionFinished.connect(self._on_selection_finished)

    # -- 窗体挂载 ---------------------------------------------------------

    def _dialog_alive(self) -> bool:
        """对话窗体是否还活着。

        QMdiArea.addSubWindow 会给子窗口打开 WA_DeleteOnClose：用户点一次
        标题栏 X，子窗口和里面的对话窗体都会被销毁，Python 侧只剩一层空
        壳（libshiboken: Internal C++ object already deleted）。所有触碰
        dialog / _chat_sub 的地方都先过这一道，避免野指针炸到界面上。
        """

        return shiboken6.isValid(self.dialog)

    def _ensure_dialog(self) -> None:
        """窗体被销毁后重建一份空对话，保证「对话选型」入口永远可用。"""

        if self._dialog_alive():
            return
        self.dialog = LlmChat(_widget_parent(self.parent()))
        self.dialog.payloadConfirmed.connect(self.start_selection)
        self._chat_sub = None
        self.statusChanged.emit("对话窗体已重建（上一次关闭时被销毁），可以直接继续提问")

    def _set_processing(self, busy: bool) -> None:
        if self._dialog_alive():
            self.dialog.set_processing(busy)

    def _attach_chat(self):
        """把对话窗挂成 MDI 子窗口（单例）；没有 MDI 时退回独立窗口。"""

        self._ensure_dialog()
        mdi = self.mdi
        if mdi is None:
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        sub = self._chat_sub
        if sub is None or not shiboken6.isValid(sub):
            sub = mdi.addSubWindow(self.dialog)
            self._chat_sub = sub
            sub.setWindowTitle("对话选型")
            sub.setWindowIcon(_transparent_icon())
            # 关键：addSubWindow 默认带 WA_DeleteOnClose，点 X 会连窗体一起
            # 销毁。改成关闭即隐藏，再点「对话选型」还能接着上一轮的对话。
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            sub.move(0, 0)
            # 初始尺寸沿用「报价诊断」的规则：取窗体自身设计尺寸，视口放不下
            # 才压缩。铺满整个 MDI 会显得太压，和 audit 窗也不统一。
            viewport = mdi.viewport().size()
            sub.resize(
                min(self.dialog.width(), viewport.width()),
                min(self.dialog.height(), viewport.height()))
        if sub.isMaximized():
            sub.showNormal()
        sub.show()
        # QMdiSubWindow 关闭时会把内部控件一起 close()，控件因此带上「显式
        # 隐藏」标记；只 show 子窗口会得到一个只剩标题栏的空白壳。这里必须
        # 把窗体本身也 show 一次，才能真正把内容带回来。
        if self._dialog_alive():
            self.dialog.show()
        mdi.setActiveSubWindow(sub)

    def _normalize_chat(self):
        """对话窗保持可见，只把最大化状态还原。

        清单出现时不再收走对话窗，而是让清单叠在它上面：用户核对时还能
        看到自己刚才说了什么，关掉清单也就自然回到对话。
        """

        sub = self._chat_sub
        if sub is not None and shiboken6.isValid(sub):
            # 最大化的子窗口会盖住后来居上的所有窗口，先还原成普通窗。
            if sub.isMaximized():
                sub.showNormal()
        elif self._dialog_alive():
            self.dialog.show()

    def _detach_chat(self):
        sub = self._chat_sub
        if sub is not None and shiboken6.isValid(sub):
            if self.mdi is not None:
                self.mdi.removeSubWindow(sub)
            sub.deleteLater()
        elif self._dialog_alive():
            self.dialog.close()
        self._chat_sub = None

    def open(self):
        """打开（或前置）对话窗。

        清单窗存在时对话窗并不隐藏，两者叠在一起；点「对话选型」就是把
        对话窗提到最上层，而不是先收掉一张再开一张。
        """

        self._ensure_dialog()
        self._attach_chat()

    # -- 选型 -------------------------------------------------------------

    def start_selection(self, payload):
        if self.busy:
            return
        if not self.can_start():
            if self._dialog_alive():
                self.dialog.show_pipeline_error("其他选型正在计算，请稍候再试。")
            return
        self.busy = True
        # 提示从这一刻开始计时：清单窗要等它露脸够久才换。
        self._handoff_at = time.monotonic()
        self._set_processing(True)
        # Copy before leaving the GUI thread. The conversation can never
        # mutate the already-confirmed input while the engine is calculating.
        confirmed = copy.deepcopy(payload)
        # archive() deliberately omits the API key and request headers.
        archive = copy.deepcopy(self.dialog.session.archive())
        self.statusChanged.emit("正在根据对话参数选型…")
        threading.Thread(
            target=self._select, args=(confirmed, archive), daemon=True
        ).start()

    def _select(self, payload, archive):
        try:
            run = cli_quote.run_payload(
                payload,
                session_root=self.session_root,
                llm_events=archive.get("events"),
            )
            if run.session_dir is not None:
                # Settings and API credentials are deliberately not archived.
                cli_quote._write_json(run.session_dir / "chat.json", archive)
                cli_quote._write_manifest(run.session_dir)
            outcome = (run, None)
        except Exception as exc:
            outcome = (None, str(exc))
        self.selectionFinished.emit(outcome)

    def _on_selection_finished(self, outcome):
        run, error = outcome
        if error or run.exit_code != cli_quote.EXIT_OK:
            self.busy = False
            self._set_processing(False)
            message = error or run.error or "选型未完成，请检查参数后重试。"
            if self._dialog_alive():
                self.dialog.show_pipeline_error(message)
            self._attach_chat()
            self.statusChanged.emit("对话选型未完成，已返回对话")
            return
        self.run = run
        # 选型已经算完，但先让「正在生成选型清单」的提示留在屏幕上，够久
        # 再切窗口；engine 慢的时候不用再补等待。
        wait = self._checklist_delay_ms()
        if wait <= 0:
            self._present_checklist()
        else:
            # 编排层先被销毁时，定时器随 self 一起没了，回调自然作废。
            self._checklist_timer.start(wait)

    def _checklist_delay_ms(self) -> int:
        if self._handoff_at is None:
            return 0
        elapsed = (time.monotonic() - self._handoff_at) * 1000.0
        return max(0, int(self.CHECKLIST_MIN_VISIBLE_MS - elapsed))

    def _overlay_position(self) -> "QPoint":
        """清单落在对话窗左上方偏一点的位置。

        完全对齐 (0,0) 会把对话窗的标题栏整个盖住，看着像换了窗口；错开
        一点，两个标题栏都在，拖哪个都行。窗体本身比视口还大时不再错开，
        否则右下角的按钮会被裁到视口外点不到。
        """

        offset = self.CHECKLIST_OFFSET
        if self.mdi is None or self._checklist_sub is None:
            return QPoint(offset, offset)
        viewport = self.mdi.viewport().size()
        size = self._checklist_sub.size()
        x = min(offset, max(0, viewport.width() - size.width() - 8))
        y = min(offset, max(0, viewport.height() - size.height() - 8))
        return QPoint(x, y)

    def _present_checklist(self):
        self._handoff_at = None
        self._set_processing(False)
        # 对话窗留在原地（只还原最大化），清单叠在它上面：核对时还能看见
        # 刚才的对话，关掉清单也直接回到对话。
        self._normalize_chat()
        run = self.run
        if run is None:
            return
        self._discard_checklist()
        checklist = Checklist()
        self.checklist = checklist
        sub = None
        if self.mdi is not None:
            sub = self.mdi.addSubWindow(checklist)
            self._checklist_sub = sub
            sub.setWindowTitle("选型清单")
            sub.setWindowIcon(_transparent_icon())
        else:
            # 没有 MDI 时清单仍是 COPA 的独立窗口，跟随主窗体生命周期。
            checklist.setParent(_widget_parent(self.parent()), Qt.WindowType.Window)
        cli_quote._set_checklist_defaults(checklist, run.payload, run.project)
        checklist.load_results(run.checklist_results, run.entries)
        cli_quote._mark_checklist_warnings(checklist, run.entries, run.checklist_results)
        checklist.rollbackRequested.connect(self.return_to_chat)
        checklist.outputSucceeded.connect(self._save_snapshot)
        checklist.installEventFilter(self)
        checklist.show()
        if sub is not None and self.mdi is not None:
            sub.show()
            # 错开一点叠在对话窗上；位置在 show 之后算，此时子窗口才是
            # 清单的真实尺寸。
            sub.move(self._overlay_position())
            # 激活即前置：清单必须压在对话窗上面，不能只是并排。
            self.mdi.setActiveSubWindow(sub)
            sub.raise_()
        self.busy = False
        self.statusChanged.emit("对话参数已传入选型清单，请人工核对后输出报价")
        QTimer.singleShot(0, self._show_failures)

    def _show_failures(self):
        run = self.run
        if self.checklist is not None and run is not None:
            cli_quote._show_no_match(self.checklist, run.results)

    def _save_snapshot(self):
        run = self.run
        if run is None or run.session_dir is None:
            # 没有归档目录（会话根目录未配置）时只提示，不算失败。
            self.statusChanged.emit("报价已输出，但未配置归档目录，本次不生成快照")
            return
        try:
            path = cli_quote._save_cli_snapshot(
                run.session_dir, run.project, run.entries, self.checklist)
            cli_quote._write_manifest(run.session_dir)
            self.statusChanged.emit("报价已输出，对话及快照已归档：{}".format(path))
        except Exception as exc:
            self.statusChanged.emit("报价已输出，快照保存失败：{}".format(exc))

    def _release_checklist(self, widget, sub):
        """把清单窗体与它的子窗口一起摘掉。

        只 deleteLater 控件会留下一个空壳「选型清单」子窗口（标题还在、
        内容空白），连续选型几次就会叠出好几层，所以子窗口必须显式
        removeSubWindow + deleteLater。
        """

        if widget is not None and shiboken6.isValid(widget):
            widget.removeEventFilter(self)
            widget.hide()
        if sub is not None and shiboken6.isValid(sub):
            # 控件此时仍是子窗口的孩子：删子窗口会把它一起带走，不需要
            # 再单独 deleteLater，否则成了一次悬空调用。
            if self.mdi is not None:
                self.mdi.removeSubWindow(sub)
            sub.deleteLater()
        elif widget is not None and shiboken6.isValid(widget):
            widget.deleteLater()

    def _discard_checklist(self):
        # 待弹出的清单一并取消：回退到对话后不该再冒出一张旧清单。
        self._checklist_timer.stop()
        widget = self.checklist
        sub = self._checklist_sub
        self.checklist = None
        self._checklist_sub = None
        self._release_checklist(widget, sub)

    def return_to_chat(self):
        self._discard_checklist()
        self._attach_chat()
        self.statusChanged.emit("已返回对话，重新选型会重建清单，不保留人工改选")

    def eventFilter(self, watched, event):
        checklist = self.checklist
        if checklist is not None and watched is checklist and event.type() == QEvent.Type.Close:
            completed = bool(checklist.output_completed)
            sub = self._checklist_sub
            self.checklist = None
            self._checklist_sub = None
            if sub is not None and shiboken6.isValid(sub):
                # 先把空壳藏起来，真正摘除推到 Close 流程结束之后。
                sub.hide()
            QTimer.singleShot(0, self, lambda: self._release_checklist(checklist, sub))
            if not completed:
                self._attach_chat()
        return super().eventFilter(watched, event)

    def close(self):
        self._discard_checklist()
        self._detach_chat()
