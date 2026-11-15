"""COPA 内置的对话选型窗体。

界面只做三件事：显示对话、接收需求（可拖入文件）、把通过校验的参数交给
engine。模型地址与口令完全不进入界面，能从 ``llm/providers.json`` 读到的
只有「用哪个模型」和一句简介。

交互约定：

- 用户输入自由文本，模型按契约翻译；缺项由模型继续追问。
- 一旦候选通过契约校验，程序**自动**确认并交下游（不需要用户点按钮）；
  需要人工核对的内容都在 Checklist 里，本模块不重复展示参数。
- 参数列表、缺项清单只作为后台状态存在（归档在 chat.json），不渲染给用户。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QIcon,
    QInputMethodEvent,
    QKeyEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .Ui_llmChat import Ui_LlmChat

# 输入框里一次显示的最大字数：导入的长文档只显示开头，全文照样发给模型。
_USER_TEXT_LIMIT = 600

# 展示脚本在 ``llm_chat`` 里（DEMO_CASE_TURNS）：那是真跑过的一轮对话，
# 模型的两次追问按原样记录，夹在中间那句澄清按人说话的口吻补全。


# ---------------------------------------------------------------------------
# 工作线程：只碰会话与文件，不碰控件
# ---------------------------------------------------------------------------


class _SendWorker(QObject):
    """在工作线程调用 ChatSession.send；绝不触碰 Qt 控件。"""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, session: Any, text: str, parent: QObject | None = None):
        super().__init__(parent)
        self._session = session
        self._text = text

    @Slot()
    def run(self) -> None:
        try:
            result = self._session.send(self._text)
        except Exception as exc:  # provider/core 错误交回 UI 显示
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished.emit(result)


class _IngestWorker(QObject):
    """在工作线程本地读取文件；绝不触碰 Qt 控件。"""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, parent: QObject | None = None):
        super().__init__(parent)
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            from .doc_ingest import ingest

            result = ingest(self._path)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished.emit(result)


def _default_session() -> Any:
    """用本地配置创建会话；配置缺失属于部署错误，由调用方提示。"""

    from .llm_chat import ChatSession, load_provider_config

    return ChatSession(settings=load_provider_config())


def _as_text(value: Any) -> str:
    """把消息安全转换为纯文本，避免把模型内容当 HTML 渲染。"""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# 模型列表：界面只认识「标签 + 一句简介」，不认识地址与口令
# ---------------------------------------------------------------------------

_FALLBACK_INTRO = "文本对话模型，由 llm/providers.json 提供。"

# 下拉弹窗是独立的顶层窗口，不在 #LlmChat 这个 widget 级样式表的作用域里，
# 所以它一条规则都吃不到，直接落到系统 palette：深色模式下就是黑底黑字，
# 看起来像一块黑色方块。这里单独给弹窗补一套浅色样式。
_POPUP_QSS = """
QListView {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    outline: none;
    color: #1f2329;
    padding: 4px;
}
QListView::item {
    min-height: 26px;
    padding: 2px 8px;
    border-radius: 6px;
}
QListView::item:hover {
    background-color: #f3f4f6;
}
QListView::item:selected {
    background-color: #eef3ff;
    color: #2f6fed;
}
"""


def model_entries() -> list[dict[str, Any]]:
    """读取 providers.json 里可展示的字段；读不到返回空列表（界面仍可用）。

    顺序由 ``ui.order`` 决定（越小越靠前），没配的排在最后、按标签排。
    不用 ``active`` 排序：默认选中项由 active 决定，列表顺序则要能单独指定。
    """

    from .llm_chat import DEFAULT_PROVIDERS_PATH

    try:
        document = json.loads(Path(DEFAULT_PROVIDERS_PATH).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    providers = document.get("providers") if isinstance(document, dict) else None
    if not isinstance(providers, dict):
        return []
    entries: list[dict[str, Any]] = []
    for key, config in providers.items():
        if not isinstance(config, dict):
            continue
        raw_ui = config.get("ui")
        ui: dict[str, Any] = raw_ui if isinstance(raw_ui, dict) else {}
        if ui.get("hidden"):
            continue
        raw_order = ui.get("order")
        try:
            order = int(raw_order) if isinstance(raw_order, (int, str)) else 100
        except ValueError:
            order = 100
        entries.append({
            "key": str(key),
            "label": str(ui.get("label") or config.get("model") or key),
            "intro": str(ui.get("intro") or ui.get("description") or _FALLBACK_INTRO),
            "order": order,
        })
    entries.sort(key=lambda entry: (entry["order"], entry["label"]))
    return entries


# ---------------------------------------------------------------------------
# 图标：两个方形按钮的图形都在这里画，不依赖外部资源文件
# ---------------------------------------------------------------------------


def _plus_icon(color: str = "#4b5563") -> QIcon:
    pixmap = QPixmap(44, 44)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(3.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(14, 22), QPointF(30, 22))
    painter.drawLine(QPointF(22, 14), QPointF(22, 30))
    painter.end()
    return QIcon(pixmap)


def _demo_icon(color: str = "#4b5563") -> QIcon:
    """占位图形：虚线方框 + 播放三角，等正式素材替换。"""

    pixmap = QPixmap(44, 44)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#b8bdc7"))
    pen.setWidthF(1.6)
    pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(7, 7, 30, 30), 7, 7)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([
        QPointF(19, 15), QPointF(30, 22), QPointF(19, 29),
    ]))
    painter.end()
    return QIcon(pixmap)


def _arrow_icon(color: str = "#ffffff") -> QIcon:
    """发送按钮的向上箭头：画出来，避免依赖字体里的箭头字符。"""

    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(QPointF(18, 26), QPointF(18, 11))
    painter.drawPolyline(QPolygonF([
        QPointF(11, 18), QPointF(18, 10), QPointF(25, 18),
    ]))
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# 消息气泡
# ---------------------------------------------------------------------------

# 气泡配色接口：整体换色只改这张表，渲染逻辑不用动。
#   bg / fg 是背景与文字色，border 直接写 CSS 边框（不需要就填 none）。
BUBBLE_THEME: dict[str, dict[str, str]] = {
    "用户": {"bg": "#2f6fed", "fg": "#ffffff", "border": "none"},
    "附件": {"bg": "#eef3fd", "fg": "#2f6fed", "border": "1px solid #d8e3f8"},
    "LLM": {"bg": "#ffffff", "fg": "#1f2329", "border": "1px solid #e5e7eb"},
    "系统": {"bg": "transparent", "fg": "#9aa1ad", "border": "none"},
    # 调用失败不是模型说的话，单独一色，别让它冒充模型回复。
    "错误": {"bg": "#fdf2f2", "fg": "#b00020", "border": "1px solid #f6d5d5"},
}


def bubble_style(role: str) -> str:
    """按 :data:`BUBBLE_THEME` 拼气泡样式；未知角色按系统提示处理。"""

    theme = BUBBLE_THEME.get(role) or BUBBLE_THEME["系统"]
    size = "11px" if role == "系统" else ("12px" if role == "附件" else "13px")
    return (
        "QFrame#msgBubble {{ background-color: {bg}; border: {border};"
        " border-radius: 12px; }}"
        "QLabel {{ color: {fg}; font-size: {size}; }}"
    ).format(size=size, **theme)


class _Bubble(QFrame):
    """一条消息。用户右侧蓝底、模型左侧白底、程序提示居中无底。"""

    MAX_WIDTH = 520

    def __init__(
        self,
        role: str,
        text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("msgBubble")
        self.setStyleSheet(bubble_style(role))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(0)
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.label)
        # 气泡按文本自然宽度定形，超过上限才换行；否则 QLabel 的 sizeHint
        # 会让长句被压成很窄的一条。
        self._role = role
        self._fit_width(text)

    def _fit_width(self, text: str) -> None:
        self.label.ensurePolished()
        metrics = self.label.fontMetrics()
        natural = max(
            (metrics.horizontalAdvance(line) for line in text.splitlines()), default=0)
        width = min(max(natural + 34, 64), self.MAX_WIDTH)
        if self._role == "系统":
            self.setMinimumWidth(width)
        else:
            self.setFixedWidth(width)

    def set_text(self, text: str, *, refit: bool = False) -> None:
        """逐字输出：换文本；``refit`` 时让气泡跟着文字一起长。"""

        self.label.setText(text)
        if refit:
            self._fit_width(text)


class LlmChat(QWidget, Ui_LlmChat):
    """内置的对话选型窗体；参数通过后由 :attr:`payloadConfirmed` 交给下游。"""

    payloadConfirmed = Signal(object)
    statusChanged = Signal(str)

    # 展示模式的节奏（毫秒）。现场演示时这几个停顿决定了「看不看得清」，
    # 测试里覆盖成 0 即可压缩时间。
    # 展示模式的节奏（毫秒）：测试会按实例改这四个值把动画压到最短，
    # 所以显式标 int，别让静态检查当成只读常量。
    DEMO_START_DELAY: int = 1000     # 点击「使用展示」后先停一下再落下需求
    DEMO_REPLY_DELAY: int = 500      # 一句需求落下后停一下再开始「模型」回复
    DEMO_USER_DELAY: int = 700       # 回复播完停一下，再放用户下一句
    DEMO_TYPE_INTERVAL: int = 23     # 逐字输出的间隔，接近常见 AI 的吐字速度
    # 状态行左侧文字的最大宽度：再长就截省略号，右边那句固定提示不能被挤变形。
    STATUS_MAX_WIDTH = 430
    # 距底部多少像素内算「在底部」：留一点余量，避免气泡半行高就判成离开。
    SCROLL_BOTTOM_SLACK = 24
    # 最后一句回复播完立刻交接；清单窗要等「正在生成」提示露个脸才开，那段
    # 停顿在 LlmQuoteWorkflow.CHECKLIST_MIN_VISIBLE_MS 里控制。

    def __init__(self, parent: QWidget | None = None, session: Any = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.setAcceptDrops(True)

        self._session = session if session is not None else _default_session()
        self._thread: QThread | None = None
        self._worker: _SendWorker | None = None
        self._ingest_thread: QThread | None = None
        self._ingest_worker: _IngestWorker | None = None
        self._ingest_generation = 0
        self._busy = False
        self._external_processing = False
        self._generation = 0
        self._send_token = 0
        self._confirmation_sent = False
        self._composing = False
        # 展示模式的播放状态：只影响界面节奏，不改变交接时提交的参数。
        self._demo_running = False
        self._demo_token = 0
        self._demo_steps: tuple[tuple[str, str], ...] = ()
        self._demo_step = 0
        self._demo_text = ""
        self._demo_index = 0
        # 待发附件：原文留在这里，界面上只显示一枚气泡。
        self._attachments: list[dict[str, str]] = []
        # 输入框高度区间（从 .ui 读一次，之后按内容收放）。
        self._composer_min: int | None = None
        self._composer_max: int = 0
        # 界面上的消息序列就是这份列表：程序提示也按真实顺序插进来，
        # 不从 session.messages 反推（那里有 system prompt 和 JSON 信封）。
        self._entries: list[tuple[str, str]] = []
        # 是否跟随最新消息：用户手动上滚后置 False，回到底部再恢复。
        self._follow_bottom = True
        self._status_text = "就绪"
        # 简介原文：标签里只放省略后的版本，按当前宽度重算。
        self._intro_text = ""

        self._build_conversation()
        self._build_scroll_button()
        self._build_rail()
        self._build_demo_pacer()
        self._populate_models()
        self.statusLabel.setMaximumWidth(self.STATUS_MAX_WIDTH)
        self.statusLabel.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self.sendButton.clicked.connect(self._send_message)
        self.attachButton.clicked.connect(self._pick_file)
        self.demoButton.clicked.connect(self._use_demo)
        self.newSessionButton.clicked.connect(self._new_session)
        self.modelCombo.currentIndexChanged.connect(self._on_model_changed)
        self.messageEdit.textChanged.connect(self._update_actions)
        self.messageEdit.installEventFilter(self)
        for target in self._rail_targets():
            target.installEventFilter(self)
        # 拖拽要冒泡到本窗体，而不是被输入框当成文本插入。
        self.messageEdit.setAcceptDrops(False)
        self.conversationArea.setAcceptDrops(False)
        self.conversationArea.viewport().setAcceptDrops(False)

        self._render_conversation()
        self._update_actions()

    # -- 对外状态 ---------------------------------------------------------

    @property
    def busy(self) -> bool:
        """发送 worker、下游选型处理、演示播放中均视为 busy。"""

        return bool(self._busy or self._external_processing or self._demo_running)

    @property
    def session(self) -> Any:
        return self._session

    @property
    def candidate(self) -> Any:
        return getattr(self._session, "candidate", None)

    @property
    def state(self) -> dict[str, Any]:
        """当前 UI 状态快照；不含候选结构，也不含任何口令。"""

        return {
            "busy": self.busy,
            "demo": self._demo_running,
            "exit_state": str(getattr(self._session, "exit_state", "collecting") or "collecting"),
            "confirmation_sent": self._confirmation_sent,
            "model": self.modelCombo.currentText(),
            "messages": len(self._entries),
        }

    # -- 初始化 -----------------------------------------------------------

    def _build_conversation(self) -> None:
        # QWidget 不画样式表背景，要显式打开，否则滚动区会露出默认灰底。
        # Designer 重排时根容器 chatRoot 可能被删掉（.ui 与代码不是同一次提交的），
        # 这里退回窗体本身，别让整窗因为少一个容器起不来。
        root = getattr(self, "chatRoot", None) or self
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail = getattr(self, "actionRail", None)
        if rail is not None:
            rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # 高度全给对话区：Designer 里漏了 stretch 时，QVBoxLayout 会把窗口
        # 对半分，输入卡片凭空多出半屏白块。
        main_layout = getattr(self, "mainLayout", None)
        if main_layout is not None and main_layout.count() >= 2:
            main_layout.setStretch(0, 1)
            main_layout.setStretch(1, 0)
        card = getattr(self, "composerCard", None)
        if card is not None:
            # 卡片只占内容高度，别被上面的伸缩拉长。
            card.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        # Designer 已经在 .ui 里放了滚动内容容器，沿用它，别另建一个把
        # 设计师排的版式丢掉。
        body = getattr(self, "conversationAreaContents", None)
        if body is None:
            body = QWidget()
            self.conversationArea.setWidget(body)
        body.setObjectName("conversationBody")
        body.setStyleSheet("background: transparent;")
        existing = body.layout()
        layout = existing if isinstance(existing, QVBoxLayout) else QVBoxLayout(body)
        layout.setContentsMargins(0, 12, 0, 8)
        layout.setSpacing(4)
        # 顶部留白用 stretch 吸收：消息贴着输入框往上长，和聊天软件一致。
        if layout.count() == 0:
            layout.addStretch(1)
        self._body = body
        self._body_layout = layout
        self.conversationArea.setStyleSheet("background: transparent; border: none;")
        self.conversationArea.viewport().setStyleSheet("background: transparent;")
        # 滚动条范围变化时才说明内容真的长高了：气泡要等布局算完才有正确
        # 高度，光靠 render 之后 singleShot(0) 会抢在几何计算前面，滚不到底。
        bar = self.conversationArea.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        bar.valueChanged.connect(self._on_scroll_value_changed)
        self.conversationArea.viewport().installEventFilter(self)

    def _build_scroll_button(self) -> None:
        """对话区右下角的「回到最新」按钮：不在底部时才浮出来。"""

        button = QToolButton(self.conversationArea.viewport())
        button.setObjectName("scrollToLatestButton")
        button.setText("↓")
        button.setFixedSize(32, 32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("回到最新消息")
        button.setStyleSheet(
            "QToolButton#scrollToLatestButton {"
            " background-color: #ffffff; border: 1px solid #e3e5ea;"
            " border-radius: 16px; color: #4b5563; font-size: 15px; }"
            "QToolButton#scrollToLatestButton:hover {"
            " background-color: #f4f5f7; border-color: #c9ced9; color: #1f2329; }"
        )
        button.hide()
        button.clicked.connect(self._scroll_to_latest)
        self._scrollButton = button
        self._place_scroll_button()

    def _place_scroll_button(self) -> None:
        button = getattr(self, "_scrollButton", None)
        if button is None:
            return
        viewport = self.conversationArea.viewport()
        x = viewport.width() - button.width() - 20
        y = viewport.height() - button.height() - 12
        button.move(max(8, x), max(8, y))
        button.raise_()

    def _on_scroll_range_changed(self, _minimum: int, maximum: int) -> None:
        if self._follow_bottom:
            self.conversationArea.verticalScrollBar().setValue(maximum)
        self._place_scroll_button()
        self._update_scroll_button()

    def _on_scroll_value_changed(self, value: int) -> None:
        bar = self.conversationArea.verticalScrollBar()
        self._follow_bottom = value >= bar.maximum() - self.SCROLL_BOTTOM_SLACK
        self._update_scroll_button()

    def _update_scroll_button(self) -> None:
        button = getattr(self, "_scrollButton", None)
        if button is None:
            return
        bar = self.conversationArea.verticalScrollBar()
        show = bar.maximum() > 0 and not self._follow_bottom
        button.setVisible(show)
        if show:
            button.raise_()

    @Slot()
    def _scroll_to_latest(self) -> None:
        self._follow_bottom = True
        self._scroll_to_bottom()
        self._update_scroll_button()

    def _rail_targets(self):
        """淡出/hover 的作用对象：老版式是容器 actionRail，新版式没有容器
        （两个按钮直接放进 railLayout）。两种版式都要能起窗，别按其中一种写死。"""
        rail = getattr(self, "actionRail", None)
        if rail is not None:
            return [rail]
        return [self.demoButton, self.newSessionButton]

    def _build_rail(self) -> None:
        self.demoButton.setIcon(_demo_icon())
        self.newSessionButton.setIcon(_plus_icon())
        self.sendButton.setIcon(_arrow_icon())
        self.demoButton.setIconSize(QSize(20, 20))
        self.newSessionButton.setIconSize(QSize(20, 20))
        self.sendButton.setIconSize(QSize(16, 16))
        # 平时半透明，鼠标移上来才完全实心。老版式作用在容器 actionRail 上，
        # 新版式没有容器（按钮直接在 railLayout 里），就逐个作用到按钮上。
        self._rail_effects = []
        for target in self._rail_targets():
            effect = QGraphicsOpacityEffect(target)
            effect.setOpacity(0.5)
            target.setGraphicsEffect(effect)
            self._rail_effects.append(effect)

    def _build_demo_pacer(self) -> None:
        # 一个延时器（同一时刻只挂一个回调）+ 一个逐字定时器。
        self._demo_slot = None
        self._demo_delay = QTimer(self)
        self._demo_delay.setSingleShot(True)
        self._demo_delay.timeout.connect(self._demo_step_tick)
        self._demo_typer = QTimer(self)
        # 默认的 CoarseTimer 会被量化到 ~32ms，逐字速度就跟设定值脱钩了；
        # 这里必须用精确计时器，否则调 23ms 实际还是 30+ms 一拍。
        self._demo_typer.setTimerType(Qt.TimerType.PreciseTimer)
        self._demo_typer.timeout.connect(self._demo_type_step)

    def _prepare_model_bar(self) -> None:
        """模型名靠左，简介紧跟其后占一个定宽槽位，弹性留给右侧空白。

        版式文件里简介标签是 Ignored + stretch=1，和 Expanding 的 spacer 一起
        抢剩余宽度：短简介被推到卡片正中、看起来和模型名断开，长简介又会把
        卡片顶高。这里改成「左对齐 + 限宽 + 单行省略」。
        """

        self.modelIntroLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.modelIntroLabel.setMinimumWidth(0)
        self.modelIntroLabel.setWordWrap(False)
        self.modelIntroLabel.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 版式里简介和右侧 spacer 都是 Expanding，两份空白把简介推到卡片中间，
        # 看起来和左边的模型名断成两块。这里把 spacer 收成固定项，剩余宽度
        # 全给简介，文字自然从模型名后面往左排。
        self.toolbarSpacer.changeSize(0, 0, QSizePolicy.Policy.Fixed,
                                      QSizePolicy.Policy.Fixed)
        # 按控件查索引，别写死 2/3：版式文件以后加删控件时不会错位。
        self.toolbarLayout.setStretch(
            self.toolbarLayout.indexOf(self.modelIntroLabel), 1)
        self.toolbarLayout.setStretch(
            self.toolbarLayout.indexOf(self.toolbarSpacer), 0)
        # 简介的宽度要等布局算完才有，单靠构造时那次省略会按初始窄宽度切短；
        # 监听标签自己的 Resize，拿到真实宽度后重算一次。
        self.modelIntroLabel.installEventFilter(self)

    def _populate_models(self) -> None:
        self._prepare_model_bar()
        entries = model_entries()
        settings = getattr(self._session, "settings", None)
        active = str(getattr(settings, "provider_name", "") or "")
        # QComboBox 默认的 AdjustToContentsOnFirstShow 只在第一次显示时算一次
        # 宽度：之后哪怕加进「Nemotron 3.5 Lightning」这种长名字，sizeHint 也
        # 停在空列表时的 89px，模型名就被截成「Nemotron 3.5 L…」。改成按内容
        # 实时自适应，弹窗宽度也才不会比下拉框本身还窄。
        self.modelCombo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.modelCombo.blockSignals(True)
        self.modelCombo.clear()
        for entry in entries:
            self.modelCombo.addItem(entry["label"], entry["key"])
            index = self.modelCombo.count() - 1
            self.modelCombo.setItemData(index, entry["intro"], Qt.ItemDataRole.ToolTipRole)
        if entries:
            index = next(
                (i for i, entry in enumerate(entries) if entry["key"] == active), 0)
            self.modelCombo.setCurrentIndex(index)
        else:
            self.modelCombo.addItem("未配置模型", "")
        self.modelCombo.blockSignals(False)
        self.modelCombo.updateGeometry()
        self.modelCombo.setMinimumWidth(self.modelCombo.sizeHint().width())
        view = self.modelCombo.view()
        if view is not None:
            # 弹窗至少与下拉框同宽，否则最长的那条会在右边缺半个字。
            view.setMinimumWidth(self.modelCombo.sizeHint().width())
        self._style_popup()
        self._show_model_intro()

    def _style_popup(self) -> None:
        """给下拉弹窗补样式：它不在 #LlmChat 的样式表作用域里。

        深色系统 palette 下，弹窗会画成黑底黑字；这里既套浅色 QSS，也把
        palette 的 Window/Base/Text 显式改成浅色，防止某些平台忽略 QSS。
        """

        view = self.modelCombo.view()
        if view is None:
            return
        view.setStyleSheet(_POPUP_QSS)
        popup = view.window() or view.parentWidget()
        if popup is None:
            return
        popup.setStyleSheet(_POPUP_QSS)
        palette = popup.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#1f2329"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#eef3ff"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#2f6fed"))
        popup.setPalette(palette)

    def _show_model_intro(self) -> None:
        index = self.modelCombo.currentIndex()
        intro = self.modelCombo.itemData(index, Qt.ItemDataRole.ToolTipRole) if index >= 0 else ""
        text = str(intro or _FALLBACK_INTRO)
        self._intro_text = text
        self.modelIntroLabel.setToolTip(text)
        self._elide_intro()
        # 刚 setText 时标签还没拿到布局给它的最终宽度，先按旧宽度省略会短一截；
        # 下一轮事件循环再算一次。
        QTimer.singleShot(0, self._elide_intro)

    def _elide_intro(self) -> None:
        """简介只占一行，宽度不够时用省略号收尾，不能把输入卡片撑高。

        原先这个标签是 Ignored + stretch=1，和右边的 Expanding 空白一起去
        抢剩余宽度：长简介会把卡片顶高，短简介又被推到卡片中间、看起来和
        左边的模型名断开了。这里改成左对齐单行 + 手工省略。
        """

        if getattr(self, "_eliding", False):
            return
        text = getattr(self, "_intro_text", "")
        if not text:
            self.modelIntroLabel.setText("")
            return
        available = max(0, self.modelIntroLabel.width())
        metrics = self.modelIntroLabel.fontMetrics()
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available)
        if elided == self.modelIntroLabel.text():
            return
        self._eliding = True
        self.modelIntroLabel.setText(elided)
        self._eliding = False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide_intro()
        self._place_scroll_button()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 首次显示之前文档宽度还是未知，``_fit_composer`` 拿到的行数不可信，
        # 空输入框会停在打开那一刻的高度。布局跑完再算一次，打开时的输入框
        # 才和演示里的空输入框一样是一行高。
        QTimer.singleShot(0, self._fit_composer)

    # -- 事件 -------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.conversationArea.viewport():
            if event.type() == QEvent.Type.Resize:
                self._place_scroll_button()
            return False
        if watched is self.messageEdit:
            if isinstance(event, QInputMethodEvent):
                # 中文输入法候选窗里按 Enter 是上屏，不能当成发送。
                self._composing = bool(event.preeditString())
                return False
            if isinstance(event, QKeyEvent):
                key = event.key()
                modifiers = event.modifiers()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        return False  # Shift+Enter 换行
                    control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
                    if control or not self._composing:
                        self._send_message()
                        return True
        elif watched is self.modelIntroLabel:
            if event.type() == QEvent.Type.Resize:
                self._elide_intro()
        elif any(watched is target for target in self._rail_targets()):
            for effect in self._rail_effects:
                if event.type() == QEvent.Type.Enter:
                    effect.setOpacity(1.0)
                elif event.type() == QEvent.Type.Leave:
                    effect.setOpacity(0.5)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._dropped_file(event) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._dropped_file(event) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        path = self._dropped_file(event)
        if path is None:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        self._ingest_path(path)

    @staticmethod
    def _dropped_file(event) -> str | None:
        from .doc_ingest import TEXT_SUFFIXES

        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in TEXT_SUFFIXES:
                return path
        return None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.busy:
            self._set_status("当前仍在处理，请稍候再关闭", error=True)
            event.ignore()
            return
        event.accept()

    # -- 状态与渲染 -------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False,
                    detail: str | None = None) -> None:
        # 状态行只有一行宽，右边还有固定提示。报错时左侧只放短码（HTTP 500 /
        # 网络异常），完整原因留在气泡里，这里只挂在 tooltip 上备查。
        self._status_text = str(text)
        self.statusLabel.setToolTip(str(detail) if detail else self._status_text)
        self.statusLabel.setText(self._elide_status(self._status_text))
        self.statusLabel.setStyleSheet("color: #b00020;" if error else "")
        self.statusChanged.emit(self._status_text)

    def _elide_status(self, text: str) -> str:
        metrics = self.statusLabel.fontMetrics()
        room = max(120, self.STATUS_MAX_WIDTH - 4)
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, room)

    def _update_actions(self) -> None:
        busy = self.busy
        has_text = bool(self.messageEdit.toPlainText().strip())
        self.messageEdit.setEnabled(not busy)
        self.attachButton.setEnabled(not busy)
        # 只发附件（让模型按清单报价）也是合法的一轮。
        self.sendButton.setEnabled(not busy and (has_text or bool(self._attachments)))
        self.demoButton.setEnabled(not busy)
        self.newSessionButton.setEnabled(not busy)
        self.modelCombo.setEnabled(not busy)
        self._fit_composer()

    def _fit_composer(self) -> None:
        """输入框跟着内容长高，空着时只占一行高。

        .ui 里给的是 56～118 的区间；不跟着内容收放的话，空输入框会一直
        顶着上限，卡片里白白空出一大块。

        行数取 ``document().size().height()``——QPlainTextEdit 的纯文本布局
        这个值是**行数（含软换行）而不是像素**，得乘行距、再补上文档边距和
        边框。直接当像素用的话 ``5 行 + 12`` 也才 17，永远低于下限，输入框
        会卡在最小高度不动。
        """

        edit = self.messageEdit
        if self._composer_min is None:
            self._composer_min = max(edit.minimumHeight(), 1)
            self._composer_max = max(edit.maximumHeight(), self._composer_min)
        doc = edit.document()
        lines = max(1.0, float(doc.size().height()))
        padding = 2 * int(doc.documentMargin()) + 2 * int(edit.frameWidth()) + 4
        wanted = int(lines * edit.fontMetrics().lineSpacing()) + padding
        target = max(self._composer_min, min(self._composer_max, wanted))
        if edit.height() != target:
            edit.setFixedHeight(target)

    def _append(self, role: str, text: str) -> None:
        text = _as_text(text).strip()
        if not text:
            return
        if role == "用户" and len(text) > _USER_TEXT_LIMIT:
            text = text[:_USER_TEXT_LIMIT] + "\n…（完整文本已发送给模型）"
        self._entries.append((role, text))

    def _render_conversation(self) -> None:
        while self._body_layout.count() > 1:  # 索引 0 是顶部 stretch
            item = self._body_layout.takeAt(1)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for role, text in self._entries:
            self._body_layout.addWidget(self._row(role, text))
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _row(self, role: str, text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 3, 18, 3)
        layout.setSpacing(0)
        bubble = _Bubble(role, text, row)
        if role in ("用户", "附件"):
            layout.addStretch(1)
            layout.addWidget(bubble)
        elif role == "系统":
            layout.addStretch(1)
            layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addStretch(1)
        else:
            layout.addWidget(bubble)
            layout.addStretch(1)
        return row

    def _last_bubble(self) -> _Bubble | None:
        """取最后一行的气泡；逐字输出每拍都重新取，避免拿到已销毁的控件。"""

        count = self._body_layout.count()
        if count <= 1:
            return None
        item = self._body_layout.itemAt(count - 1)
        if item is None:
            return None
        row = item.widget()
        return row.findChild(_Bubble) if row is not None else None

    def _scroll_to_bottom(self) -> None:
        self._follow_bottom = True
        bar = self.conversationArea.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._update_scroll_button()

    def _take_exit_notice(self) -> str | None:
        """取走 core 本轮生成的程序提示（一次性，不进模型上下文）。"""

        take = getattr(self._session, "take_exit_notice", None)
        notice = take() if callable(take) else None
        return notice if isinstance(notice, str) else None

    # -- 发送 -------------------------------------------------------------

    def _outbound_text(self, text: str) -> str:
        """真正发给模型的内容：附件原文在前，用户这句话在后。

        附件内容不再倒进输入框——那会逼用户在自己写的要求和整份清单之间
        二选一；界面上只留一枚附件气泡，原文随这句要求一起发出去。
        """

        parts = [item["text"] for item in self._attachments]
        if text:
            parts.append(text)
        return "\n\n".join(part for part in parts if part)

    @Slot()
    def _send_message(self) -> None:
        if self.busy:
            return
        text = self.messageEdit.toPlainText().strip()
        if not text and not self._attachments:
            self._set_status("请输入需求后再发送", error=True)
            self._update_actions()
            return

        self._send_token = self._generation
        self._busy = True
        # 新一轮协商重新开始：上一轮是否已交接过不影响这一轮。
        self._confirmation_sent = False
        self._append("用户", text)
        self._render_conversation()
        self._set_status("正在解析需求…")
        self._update_actions()

        thread = QThread(self)
        worker = _SendWorker(self._session, self._outbound_text(text))
        # 附件已经随这一轮发出，气泡留在记录里，接下来的话是新的补充。
        self._attachments.clear()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._worker_finished)
        worker.failed.connect(self._worker_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _finish_thread(self, thread: QThread) -> None:
        if thread.isRunning():
            thread.quit()
            thread.wait()

    @Slot(object)
    def _worker_finished(self, result: Any) -> None:
        token = self._send_token
        thread = self._thread
        if thread is None:
            return
        self._finish_thread(thread)
        if token != self._generation:
            return
        self._busy = False

        message = result.get("message") if isinstance(result, dict) else getattr(result, "message", "")
        payload = result.get("payload") if isinstance(result, dict) else getattr(result, "payload", None)
        error = getattr(self._session, "last_error", None)
        if payload is not None:
            try:
                self._load_candidate(payload)
            except Exception as exc:
                self._append("系统", f"候选载入失败：{exc}")
        # 失败轮模型并没有说话，别把它塞进模型气泡里。
        self._append("错误" if error else "LLM", message or "")
        notice = self._take_exit_notice()
        if notice:
            self._append("系统", notice)

        # 清空输入框：下一句是新的补充，不必让用户手动删掉上一句。
        self.messageEdit.clear()
        self._render_conversation()
        if error:
            from .llm_chat import error_code

            # 底层已经带了「模型调用失败：」前缀，别再套一层；状态行只留短码。
            text = error if error.startswith("模型调用失败") else f"模型调用失败：{error}"
            self._set_status(error_code(text), error=True, detail=text)
        else:
            self._set_status("已记录")
        self._worker = None
        self._thread = None
        self._update_actions()
        self._maybe_handoff()

    @Slot(str)
    def _worker_failed(self, message: str) -> None:
        token = self._send_token
        thread = self._thread
        if thread is None:
            return
        self._finish_thread(thread)
        if token != self._generation:
            return
        self._busy = False
        self._append("系统", f"发送失败：{message}")
        self._render_conversation()
        self._set_status("发送失败", error=True, detail=f"发送失败：{message}")
        self._worker = None
        self._thread = None
        self._update_actions()

    def _load_candidate(self, payload: Any) -> None:
        loader = getattr(self._session, "load_candidate", None)
        if not callable(loader):
            raise RuntimeError("当前会话不支持载入候选")
        try:
            loader(payload, merge=True)
        except TypeError:
            loader(payload)

    # -- 自动交接 ---------------------------------------------------------

    def _preview_data(self) -> dict[str, Any]:
        try:
            data = self._session.preview()
        except Exception as exc:
            return {"errors": [str(exc)], "count": 0, "ready": False}
        return data if isinstance(data, dict) else {}

    def _maybe_handoff(self) -> None:
        """校验通过即交接给 engine；需要人工确认的事都在 Checklist 里做。"""

        if self.busy or self._confirmation_sent:
            return
        if getattr(self._session, "ex_pending", False):
            # 防爆尚未表态：程序已在请求里注入那一次强制追问，
            # 用户回答前不自动交接，即使候选已通过契约校验。
            return
        data = self._preview_data()
        ready = bool(data.get("ready"))
        allowed = bool(getattr(self._session, "force_quote_allowed", False))
        exit_state = str(getattr(self._session, "exit_state", "collecting") or "collecting")
        # 未通过校验时只有一种例外：用户已明确要求报价，且剩余缺项全在
        # 白名单内（非必须项按中性默认处理并留痕）。
        if not (ready or (allowed and exit_state == "awaiting_confirm")):
            return
        try:
            count = max(0, int(data.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        try:
            payload = (
                self._session.confirm(count) if ready
                else self._session.confirm(count, force_quote=True)
            )
        except Exception as exc:
            self._append("系统", f"参数交接失败：{exc}")
            self._render_conversation()
            self._set_status(f"参数交接失败：{exc}", error=True)
            return

        self._confirmation_sent = True
        self._append("系统", "参数已通过校验，正在生成选型清单…")
        self._render_conversation()
        self._set_status("正在生成选型清单…")
        self._update_actions()
        self.payloadConfirmed.emit(payload)

    # -- 文件 -------------------------------------------------------------

    @Slot()
    def _pick_file(self) -> None:
        if self.busy:
            return
        from .doc_ingest import FILE_FILTER

        path, _ = QFileDialog.getOpenFileName(self, "导入需求文件", "", FILE_FILTER)
        if path:
            self._ingest_path(path)

    def _ingest_path(self, path: str) -> None:
        if self.busy:
            return
        self._ingest_generation = self._generation
        self._busy = True
        self._set_status(f"正在读取《{Path(path).name}》…")
        self._update_actions()

        thread = QThread(self)
        worker = _IngestWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._ingest_finished)
        worker.failed.connect(self._ingest_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._ingest_thread = thread
        self._ingest_worker = worker
        thread.start()

    @Slot(object)
    def _ingest_finished(self, result: Any) -> None:
        thread = self._ingest_thread
        if thread is None:
            return
        self._finish_thread(thread)
        self._busy = False
        self._ingest_worker = None
        self._ingest_thread = None
        if self._ingest_generation != self._generation:
            return

        from .doc_ingest import compose_message, has_requirement

        # 闸口：抽出来的文字里连一个选型要素都没有，就是拖错文件了。这种
        # 时候把原文交给模型，它只会照着文件名瞎猜字段，比直接拒绝更糟。
        if not has_requirement(getattr(result, "text", "")):
            self._reject_ingest(str(getattr(result, "source", "") or "附件"))
            return

        # 附件原文留在内存里，随下一句话一起交给模型；界面上只挂一枚气泡，
        # 用户接着写自己的要求就行，不用在整份清单里找地方插话。
        self._attachments.append({
            "name": str(result.source),
            "text": compose_message(result),
        })
        self._append("附件", "附件：{}".format(result.source))
        self._render_conversation()
        notes = "；".join(str(item) for item in result.warnings)
        self._set_status("已附加《{}》{}，写下要求后发送".format(
            result.source, "：" + notes if notes else ""))
        self._update_actions()

    @Slot(str)
    def _ingest_failed(self, message: str) -> None:
        thread = self._ingest_thread
        if thread is None:
            return
        self._finish_thread(thread)
        self._busy = False
        self._ingest_worker = None
        self._ingest_thread = None
        if self._ingest_generation != self._generation:
            return
        self._append("系统", f"文件读取失败：{message}")
        self._render_conversation()
        self._set_status(f"文件读取失败：{message}", error=True)
        self._update_actions()

    def _reject_ingest(self, source: str) -> None:
        """附件里没有选型要求：提示后中断本轮，不把它交给模型。

        只丢掉这份文件，已经挂上的附件保持原样——用户可能是拖错了文件，
        不该顺带清空他先前选好的东西。流程停在这里，不会再发任何请求。
        """

        message = "传入的《{}》未能解析到选型要求，请重新检查。".format(source)
        self._append("系统", message)
        self._follow_bottom = True
        self._render_conversation()
        self._set_status("附件不含选型要求，已中断", error=True, detail=message)
        self._update_actions()

    # -- 展示 / 新会话 / 模型 ---------------------------------------------

    @Slot()
    def _use_demo(self) -> None:
        """用固定示例走一遍完整对话：不调用模型，按演示节奏交接。

        脚本来自真实跑过的一轮「附件 + FT系列，报价」，模型的两次回复按原样
        记录，中间用户那句澄清按人说话的口吻补全。参数在点击时就已载入，
        随后的停顿只发生在界面上：等一拍再落附件与需求，再半拍后逐字打出
        模型回复；整段播完立刻交接，让「正在生成选型清单」的提示露脸，清单
        窗由编排层延后 1.5s 再弹。
        """

        if self.busy:
            return
        from .llm_chat import demo_case_payload, demo_case_turns

        try:
            try:
                self._session.load_candidate(demo_case_payload(), merge=False)
            except TypeError:
                self._session.load_candidate(demo_case_payload())
        except Exception as exc:
            self._append("系统", f"示例载入失败：{exc}")
            self._render_conversation()
            self._set_status(f"示例载入失败：{exc}", error=True)
            return
        self._cancel_demo()
        self.messageEdit.clear()
        self._attachments.clear()
        self._confirmation_sent = False
        self._demo_running = True
        self._demo_token = self._generation
        self._demo_steps = demo_case_turns()
        self._demo_step = 0
        self._set_status("正在准备演示…")
        self._update_actions()
        self._demo_wait(self.DEMO_START_DELAY, self._demo_next_step)

    # -- 展示模式的时序 ---------------------------------------------------

    def _demo_alive(self) -> bool:
        """新会话或重开窗口后，残留的定时器回调必须自己作废。"""

        return bool(self._demo_running and self._demo_token == self._generation)

    def _demo_wait(self, milliseconds: int, slot) -> None:
        """延时执行下一步；同一时刻只保留一个待执行的步骤。"""

        self._demo_slot = slot
        self._demo_delay.start(max(0, int(milliseconds)))

    @Slot()
    def _demo_step_tick(self) -> None:
        step = getattr(self, "_demo_slot", None)
        self._demo_slot = None
        if step is not None:
            step()

    def _cancel_demo(self) -> None:
        self._demo_running = False
        self._demo_slot = None
        for timer in (getattr(self, "_demo_delay", None), getattr(self, "_demo_typer", None)):
            if timer is None:
                continue
            try:
                timer.stop()
            except RuntimeError:  # 控件已销毁
                pass

    @Slot()
    def _demo_next_step(self) -> None:
        """播下一句：附件/用户直接落屏，模型那句逐字打出来。"""

        if not self._demo_alive():
            return
        if self._demo_step >= len(self._demo_steps):
            self._demo_handoff()
            return
        role, text = self._demo_steps[self._demo_step]
        self._demo_step += 1
        if role == "LLM":
            # 先落一个空壳，再逐字长出来；不然气泡会先按全文宽度撑开。
            self._entries.append(("LLM", ""))
            self._render_conversation()
            self._demo_text = text
            self._demo_index = 0
            self._set_status("演示：模型正在组织回复…")
            self._update_actions()
            self._demo_typer.start(max(0, int(self.DEMO_TYPE_INTERVAL)))
            return
        self._append(role, text)
        self._render_conversation()
        self._set_status(
            "演示：已附上清单…" if role == "附件" else "演示：已发送需求…")
        self._update_actions()
        self._demo_wait(self.DEMO_REPLY_DELAY, self._demo_next_step)

    @Slot()
    def _demo_type_step(self) -> None:
        if not self._demo_alive():
            self._demo_typer.stop()
            return
        self._demo_index += 1
        partial = self._demo_text[: self._demo_index]
        bubble = self._last_bubble()
        if bubble is not None:
            bubble.set_text(partial, refit=True)
        if self._entries:
            self._entries[-1] = ("LLM", partial)
        self._scroll_to_bottom()
        if self._demo_index >= len(self._demo_text):
            self._demo_typer.stop()
            if self._demo_step < len(self._demo_steps):
                # 回复播完停一下，给用户读那句回复的工夫，再放下一句。
                self._demo_wait(self.DEMO_USER_DELAY, self._demo_next_step)
            else:
                # 最后一句播完立刻交接：先让「正在生成选型清单」这句提示
                # 露脸，清单窗由编排层在提示停留够 1.5s 之后再弹。
                self._demo_handoff()

    def _demo_handoff(self) -> None:
        self._demo_running = False
        self._set_status("正在生成选型清单…")
        self._update_actions()
        self._maybe_handoff()

    @Slot()
    def _new_session(self) -> None:
        if self.busy:
            return
        self._cancel_demo()
        self._generation += 1
        try:
            self._session.reset()
        except Exception as exc:
            self._set_status(f"新会话失败：{exc}", error=True)
            return
        self._entries.clear()
        self._confirmation_sent = False
        self._attachments.clear()
        self.messageEdit.clear()
        self._render_conversation()
        self._set_status("已开始新会话")
        self._update_actions()

    @Slot(int)
    def _on_model_changed(self, index: int) -> None:
        self._show_model_intro()
        key = self.modelCombo.itemData(index)
        if not key:
            return
        try:
            from .llm_chat import ChatSession, load_provider_config

            settings = load_provider_config(name=str(key))
            self._session.settings = settings
            self._session.provider = ChatSession._provider_for_settings(settings)
        except Exception as exc:
            self._set_status(f"模型切换失败：{exc}", error=True)
            return
        self._set_status("已切换模型：{}".format(self.modelCombo.itemText(index)))

    # -- 下游状态 ---------------------------------------------------------

    def set_processing(self, busy: bool) -> None:
        """由编排层在 engine 选型期间锁定/解锁窗体。"""

        self._external_processing = bool(busy)
        if busy:
            self._set_status("正在选型，请稍候…")
        elif self._confirmation_sent:
            # 清单已经打开。对话窗不再隐藏，这一行不能一直停在「请稍候」，
            # 否则看着像还在算，用户会等着不敢动清单。
            self._set_status("参数已交入选型清单，请人工核对")
        self._update_actions()

    def show_pipeline_error(self, message: str) -> None:
        """下游失败回到对话：错误以系统气泡呈现，可继续补充需求重试。"""

        self._external_processing = False
        self._confirmation_sent = False
        text = _as_text(message) or "后续选型失败"
        self._append("系统", f"后续选型失败：{text}")
        self._render_conversation()
        # 同上：状态行只标一句「选型失败」，原因在气泡里看全。
        self._set_status("选型失败", error=True, detail=f"后续选型失败：{text}")
        self._update_actions()


__all__ = ["LlmChat", "model_entries"]
