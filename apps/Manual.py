"""COPA_com_Manual v1.2 使用说明指引窗口 by Hero Pang.
Commander「设置 -> 使用说明」：向导式指引窗口，按步骤展示截图与说明
文字。素材与代码分离：步骤标题/说明文字存 manual/manual.json，截图为
manual/ 下的 png。定位：源码运行取项目根；打包后经 COPA.spec 的 datas
进 _internal 内的 manual/，冻结态从 sys._MEIPASS 读取，发布时无需再
手动复制 manual 文件夹(config/data/template 仍照旧手动复制)。

分册结构：manual.json 可配 "guides": [{"title", "pages"}, ...]，每册
独立目录与步序（如 选型报价指南 / 技术方案编排指南），窗口顶部页签切
换、互不混排；兼容旧扁平写法 {"pages": [...]}（归入单册「使用指南」）。

单页截图支持两种写法：单张为字符串("image": "a.png")，多张为数组
("image": ["a.png", "b.png"])，旧的单张写法保持兼容。多张时纵向排列、
各按图片区宽度等比缩放，整区超出可视高度出纵向滚动条；单张仍按可用
空间整体适配不滚动。

窗口为非模态单例(Commander 持引用复用)：读者可边看指引边在实际窗口
照做；左侧目录可直达任意步骤，底部 上一步/下一步 顺序翻页，窗口缩放
时截图按可用空间等比缩放。素材缺失不阻断使用：缺图显示占位图，
manual.json 缺失/损坏时窗口内展示错误信息。
"""
import json
import os
import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QScrollArea,
                               QSizePolicy, QTabBar, QTextBrowser,
                               QVBoxLayout, QWidget)

from COPA.apps import app_icon

# 素材定位：源码运行取项目根；打包后随 datas 进 _internal\manual(不外显
# 在 exe 旁)，冻结态从 sys._MEIPASS 读取——6.x 指向 _internal，5.x 恰为
# exe 目录，getattr 兜底两者兼容。与 config 走 exe 旁的机制不同：config
# 需要用户可改，manual 是只读素材。
if getattr(sys, "frozen", False):
    _ROOT_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_MANUAL_DIR = os.path.join(_ROOT_DIR, "manual")
_MANUAL_JSON = os.path.join(_MANUAL_DIR, "manual.json")


def _parse_pages(raw_pages):
    """pages 数组 -> 标准化页面列表（title/images/text 三键）"""
    pages = []

    for page in raw_pages or []:
        if not isinstance(page, dict):
            continue
        raw = page.get("image")
        raw_list = raw if isinstance(raw, list) else [raw]
        images = [str(item).strip() for item in raw_list
                  if item and str(item).strip()]
        pages.append({
            "title": str(page.get("title") or "未命名步骤"),
            "images": images,
            "text": str(page.get("text") or ""),
        })

    return pages


def load_manual():
    """manual/manual.json -> (窗口标题, 分册列表)。

    两种结构：
    - 分册式：{"title", "guides": [{"title", "pages": [...]}]}，每册
      独立目录与步序（选型报价指南 / 技术方案编排指南互不混排）；
    - 兼容旧扁平式：{"title", "pages": [...]}，归入单册「使用指南」。
    每页含 title/images/text；image 允许字符串(单图)或数组(多图)，统一
    归一为 images 文件名列表。缺失或结构不合规时抛异常，由对话框转为
    错误页展示。"""
    with open(_MANUAL_JSON, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise RuntimeError("manual.json 顶层必须是对象")

    guides = []

    for guide in data.get("guides") or []:
        if not isinstance(guide, dict):
            continue
        pages = _parse_pages(guide.get("pages"))

        if pages:
            guides.append({"title": str(guide.get("title") or "指南"),
                           "pages": pages})

    if not guides:
        pages = _parse_pages(data.get("pages"))

        if not pages:
            raise RuntimeError("manual.json 中没有可用页面")

        guides = [{"title": "使用指南", "pages": pages}]

    return str(data.get("title") or "使用说明"), guides


class ManualDialog(QDialog):
    """使用说明指引窗口：左目录 + 右侧(步骤标题/截图区/说明文字) +
    底部 上一步/下一步 翻页；目录与翻页按钮双向联动"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(app_icon())
        self._guides = []
        self._guide_index = 0
        self._pages = []
        self._pixmaps = {}      # 页号 -> 原始 QPixmap 列表(首次展示时懒加载)
        self._imageLabels = []  # 当前页的图片标签(随页重建)
        self._current = -1

        try:
            title, self._guides = load_manual()
            self.setWindowTitle(title)
        except Exception as err:
            # 素材缺失/损坏不弹窗阻断：直接在指引窗口内说明原因
            self._guides = [{"title": "使用说明", "pages": [{
                "title": "素材加载失败",
                "images": [],
                "text": "未能读取使用说明素材：{}\n\n请检查程序目录下的 "
                        "manual\\manual.json 与截图文件是否完整。".format(err),
            }]}]

        self._pages = self._guides[0]["pages"]

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 10)

        # 分册页签：选型报价 / 技术方案编排 各自独立目录与步序；
        # 只有一册时隐藏页签
        self.guideTabs = QTabBar(self)
        for guide in self._guides:
            self.guideTabs.addTab(guide["title"])
        self.guideTabs.setVisible(len(self._guides) > 1)
        self.guideTabs.currentChanged.connect(self._on_guide_changed)
        root.addWidget(self.guideTabs)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(body, 1)

        # 左侧目录：点击直达任意步骤
        self.tocList = QListWidget(self)
        self.tocList.setFixedWidth(150)
        body.addWidget(self.tocList)

        right = QVBoxLayout()
        body.addLayout(right, 1)

        self.titleLabel = QLabel(self)
        self.titleLabel.setStyleSheet("font-size: 15px; font-weight: bold;")
        right.addWidget(self.titleLabel)

        # 截图区：多张图纵向排列，单张整体适配、多张按宽度适配，
        # 超出可视高度时纵向滚动(横向永不滚动——图片恒按宽度缩放)
        self.imageScroll = QScrollArea(self)
        self.imageScroll.setWidgetResizable(True)
        self.imageScroll.setFrameShape(QFrame.Shape.NoFrame)
        self.imageScroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.imageScroll.setStyleSheet(
            "QScrollArea { border: 1px solid #c9c9c9; }")
        self.imageHost = QWidget(self)
        self.imageHost.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,
                                    True)
        self.imageHost.setStyleSheet("background-color: white;")
        self.imageLayout = QVBoxLayout(self.imageHost)
        self.imageLayout.setContentsMargins(6, 6, 6, 6)
        self.imageLayout.setSpacing(6)
        self.imageScroll.setWidget(self.imageHost)
        # 视口尺寸变化(首次布局/窗口缩放/滚动条出入)经事件过滤器重排截图
        self.imageScroll.viewport().installEventFilter(self)
        right.addWidget(self.imageScroll, 1)

        # 说明文字：只读文本框，内容超长时滚动
        self.textView = QTextBrowser(self)
        self.textView.setOpenExternalLinks(False)
        self.textView.setFixedHeight(200)
        right.addWidget(self.textView)

        nav = QHBoxLayout()
        self.btnPrev = QPushButton("上一步", self)
        self.btnPrev.clicked.connect(self._go_prev)
        self.stepLabel = QLabel(self)
        self.btnNext = QPushButton("下一步", self)
        self.btnNext.clicked.connect(self._go_next)
        btnClose = QPushButton("关闭", self)
        btnClose.clicked.connect(self.close)
        nav.addWidget(self.btnPrev)
        nav.addWidget(self.stepLabel)
        nav.addStretch(1)
        nav.addWidget(self.btnNext)
        nav.addWidget(btnClose)
        right.addLayout(nav)

        self.tocList.currentRowChanged.connect(self._on_toc_changed)

        for index, page in enumerate(self._pages):
            self.tocList.addItem("{}. {}".format(index + 1, page["title"]))

        self.resize(800, 700)
        self.goto(0)

    # ====步骤切换====

    def _on_guide_changed(self, row):
        """切换分册：换页集并重建目录，回到该册第 1 步（图片缓存清空）"""
        if row < 0 or row == self._guide_index:
            return
        self._guide_index = row
        self._pages = self._guides[row]["pages"]
        self._pixmaps.clear()
        self.tocList.clear()
        for index, page in enumerate(self._pages):
            self.tocList.addItem("{}. {}".format(index + 1, page["title"]))
        self.goto(0)

    def goto(self, index):
        """跳到指定步骤：目录选中与页面展示的统一入口(越界自动收敛)"""
        index = max(0, min(index, len(self._pages) - 1))

        if self.tocList.currentRow() != index:
            self.tocList.setCurrentRow(index)   # 经信号回 _on_toc_changed
        else:
            self._show_page(index)

    def _go_prev(self):
        self.goto(self._current - 1)

    def _go_next(self):
        self.goto(self._current + 1)

    def _on_toc_changed(self, row):
        if row >= 0:
            self._show_page(row)

    def _show_page(self, index):
        self._current = index
        page = self._pages[index]
        self.titleLabel.setText("{}. {}".format(index + 1, page["title"]))
        self.textView.setPlainText(page["text"])
        self.stepLabel.setText("第 {} 步 / 共 {} 步".format(
            index + 1, len(self._pages)))
        self.btnPrev.setEnabled(index > 0)
        self.btnNext.setEnabled(index < len(self._pages) - 1)
        self._rebuild_images()

    # ====截图展示====

    def _rebuild_images(self):
        """按当前页图片列表重建图片标签并适配缩放(切页时调用)"""
        while self.imageLayout.count():
            item = self.imageLayout.takeAt(0)

            if item is None:      # takeAt 越界/空槽位返回 None，防御收敛
                break

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._imageLabels = []
        pixmaps = self._page_pixmaps(self._current)

        for pixmap in pixmaps:
            label = QLabel(self.imageHost)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter
                               | Qt.AlignmentFlag.AlignTop)
            self.imageLayout.addWidget(label)
            self._imageLabels.append(label)

        self._apply_image()

    def _apply_image(self):
        """当前页各截图等比缩放(首展与窗口缩放共用)：单张按可用空间
        整体适配(不出滚动条)；多张按图片区宽度适配、纵向可滚动"""
        if self._current < 0:
            return

        viewport = self.imageScroll.viewport()
        avail_w = max(viewport.width() - 18, 1)   # 预留纵向滚动条宽度
        avail_h = max(viewport.height() - 18, 1)
        pixmaps = self._page_pixmaps(self._current)
        single = len(self._imageLabels) == 1

        for label, pixmap in zip(self._imageLabels, pixmaps):
            if single:
                scaled = pixmap.scaled(
                    avail_w, avail_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            else:
                scaled = pixmap.scaled(
                    avail_w, pixmap.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)

            label.setPixmap(scaled)

    def _page_pixmaps(self, index):
        """页号 -> 原始 QPixmap 列表(懒加载并缓存)；缺图逐张以占位图代替，
        整页未配图时给单张占位"""
        if index not in self._pixmaps:
            pixmaps = []

            for name in self._pages[index]["images"]:
                path = os.path.join(_MANUAL_DIR, name) if name else ""
                pixmap = QPixmap(path) if path and os.path.isfile(path) else None

                if pixmap is None or pixmap.isNull():
                    pixmap = self._placeholder(name or "(未配置截图)")

                pixmaps.append(pixmap)

            if not pixmaps:
                pixmaps.append(self._placeholder("(未配置截图)"))

            self._pixmaps[index] = pixmaps

        return self._pixmaps[index]

    @staticmethod
    def _placeholder(name):
        """缺图占位：灰底文字提示，尺寸对齐常见截图比例"""
        pixmap = QPixmap(860, 600)
        pixmap.fill(QColor(245, 245, 245))
        painter = QPainter(pixmap)
        painter.setPen(QColor(136, 136, 136))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                         "缺少截图素材：{}".format(name))
        painter.end()
        return pixmap

    # ====事件====

    def eventFilter(self, watched, event):
        # 图片区视口尺寸真正变化(首次布局/窗口缩放/滚动条出入)时重排
        # 当前页截图。构造期视口尺寸尚是占位值，不能在切页时一次性定死
        if (watched is self.imageScroll.viewport()
                and event.type() == QEvent.Type.Resize):
            self._apply_image()

        return super().eventFilter(watched, event)
