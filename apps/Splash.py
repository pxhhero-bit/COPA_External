"""启动画面(Splash)：按 619x363 设计稿原生坐标绘制，底栏状态与进度条实时刷新。

设计来源：Affinity 稿 splash-F.svg / splash.png。不用 QtSvg 直读，原因有二：
SVG 的文本会被 QtSvg 渲染成方框(Tiny 1.2 文本支持不完整)；且该文件导出时
各图层被施加了不一致的缩放，底栏只画了 41px 高。故这里以 619x363 为原生
坐标系用 QPainter 重画，所有坐标/字号取自导出图的实测 bbox：

    强调方点 (39,38,9x9)   英文标语 x62 基线47(12px)
    字标 COPA x40 基线155(103.5px)   黄短线 (39,199,76x5)
    中文标题 x40 基线263(27.5px)     副标题 x39 基线281(15.2px)
    图标 (454,54,122x122)   署名右对齐至615   底栏 320 起、高43
    进度轨 x350 宽240 y341 高4

静态部分缓存在 QPixmap(按 devicePixelRatio 建，HiDPI 不虚)；底栏每帧重绘。
底栏文案固定为「正在初始化」，只有省略号逐字增长再归零循环——启动阶段对
用户没有信息价值，set_progress 才是真实可用的接口。
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import (QElapsedTimer, QEasingCurve, QPointF, QPropertyAnimation,
                            QRectF, Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication,
                           QLinearGradient, QPainter, QPixmap)
from PySide6.QtWidgets import QWidget

from COPA.apps.version import version_text

NATIVE_W, NATIVE_H = 619, 363
FOOTER_TOP = 320
DIVIDER_TOP = 318

GOLD = QColor(238, 192, 42)          # 设计稿 rgb(238,192,42)
BLUE = QColor(42, 120, 238)          # 设计稿进度条 rgb(42,120,238)
INK = QColor(20, 20, 22)             # COPA 字标
TITLE = QColor(74, 76, 81)           # 中文标题
SUB = QColor(144, 145, 149)          # 副标题
MUTED = QColor(133, 133, 138)        # 英文标语
FOOTER_BG = QColor(247, 248, 250)
DIVIDER = QColor(237, 238, 240)
TRACK = QColor(218, 219, 221)
SIGN = QColor(215, 216, 218)         # by Hero Pang

STATUS_TEXT = "正在初始化"              # 固定文案，不反映真实阶段
DOTS_MAX = 6                         # 省略号点数上限
DOT_MS = 220                         # 每加一个点的间隔

EYEBROW = "NIMBLE · ACCURATE · RELIABLE"
WORDMARK = "COPA"
HEADLINE = "工业称重设备　选型协作系统"
SUBHEAD = "选型报价·技术方案·自动化工作流"
SIGNATURE = "by Hero Pang"

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _icon_path() -> str:
    """图标路径：源码态取 apps/assets；冻结态随 spec datas 落在
    _internal/COPA/apps/assets（与 sDocBuilder/assets 同一套机制）。"""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(root, "COPA", "apps", "assets", "splash_icon.png")
    return os.path.join(ASSET_DIR, "splash_icon.png")

TRACK_X, TRACK_Y, TRACK_W, TRACK_H = 350.0, 341.0, 240.0, 4.0
STATUS_X = 214.0

_FAMILIES: dict[str, str] = {}


def _register_fallback_fonts() -> None:
    """字体库为空时(offscreen/精简运行环境)显式加载系统字体文件。

    正常情况下 Windows 平台能直接枚举到 SimHei/Bahnschrift；但离屏渲染
    (截图、自动化预览)下 QFontDatabase.families() 返回空，此时按名字取
    字体必定落到无字形的兜底字体，中英文都会变成方框。这里按需补注册。
    """
    if QFontDatabase.families():
        return
    for path in ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
                 "C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def _resolve_families() -> None:
    """选定实际可用的字体族；缺失则逐级回退，避免出现无字形的方框。"""
    if _FAMILIES:
        return
    _register_fallback_fonts()
    fams = set(QFontDatabase.families())
    cn = next((f for f in ("SimHei", "Microsoft YaHei", "微软雅黑", "SimSun")
               if f in fams), "")
    tech = next((f for f in ("Bahnschrift", "Segoe UI", "Arial") if f in fams), "")
    latin = next((f for f in ("Arial", "Segoe UI", "Helvetica") if f in fams), "")
    _FAMILIES.update(cn=cn, tech=tech, latin=latin)


def _font(key: str, px: float, weight=QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    _resolve_families()
    f = QFont(_FAMILIES.get(key, ""))
    f.setPixelSize(round(px))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


class Splash(QWidget):
    """无边框启动窗：静态版式缓存 + 底栏实时刷新。"""

    MIN_MS = 900          # 最短停留，防止一闪而过
    FADE_MS = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.SplashScreen
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFixedSize(*self._target_size())

        self._dots = 0                          # 当前省略号点数 0~6
        self._progress = 0.06
        self._shown = self._progress           # 进度动画的当前值
        self._cache: QPixmap | None = None
        self._cache_dpr = 0.0
        self._elapsed = QElapsedTimer()
        self._fading = False

        # 用 QVariantAnimation 而非 QPropertyAnimation：后者要求属性注册进
        # Qt 元对象，Python 的 @property 不生效，动画会静默不动。
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_progress_step)

        # 省略号逐字增加：0 点 -> 6 点 后归零循环
        self._tick = QTimer(self)
        self._tick.setInterval(DOT_MS)
        self._tick.timeout.connect(self._on_dot_tick)

    # ---- 尺寸与定位 ----
    @classmethod
    def _target_size(cls) -> tuple[int, int]:
        """原生 619x363；仅在屏幕小到放不下时等比收缩。"""
        w, h = NATIVE_W, NATIVE_H
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            if w > geo.width() * 0.95 or h > geo.height() * 0.9:
                k = min(geo.width() * 0.95 / w, geo.height() * 0.9 / h)
                w, h = round(w * k), round(h * k)
        return w, h

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

    # ---- 对外接口 ----
    def show(self) -> None:                # noqa: D102 - 记录起点并居中后显示
        self._elapsed.start()
        self._center()
        super().show()
        self.raise_()
        self._tick.start()

    def set_progress(self, value: float) -> None:
        """value: 0~1；只增不减，避免视觉回退。"""
        value = max(0.0, min(1.0, float(value)))
        if value <= self._progress:
            return
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(value)
        self._anim.start()
        self._progress = value

    def _on_progress_step(self, value) -> None:
        self._shown = float(value)
        self.update()

    def finish(self, window) -> None:
        """主窗就绪后调用：补足最短停留 -> 淡出 -> 显示主窗。"""
        remain = max(0, self.MIN_MS - self._elapsed.elapsed())
        QTimer.singleShot(remain, lambda: self._fade_out(window))

    def _fade_out(self, window) -> None:
        if self._fading:
            return
        self._fading = True
        self.set_progress(1.0)
        self.update()

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(self.FADE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InQuad)
        fade.finished.connect(self.close)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade = fade                   # 保持引用，避免被 GC
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()

    def _on_dot_tick(self) -> None:
        self._dots = (self._dots + 1) % (DOTS_MAX + 1)
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:    # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.scale(self.width() / NATIVE_W, self.height() / NATIVE_H)

        p.drawPixmap(0, 0, self._static_layer())
        self._paint_footer(p)
        p.end()

    def _static_layer(self) -> QPixmap:
        """背景 + 字标 + 标题 + 图标：仅在 DPR 变化时重建。"""
        dpr = self.devicePixelRatioF()
        if self._cache is not None and abs(self._cache_dpr - dpr) < 1e-6:
            return self._cache

        pix = QPixmap(round(NATIVE_W * dpr), round(NATIVE_H * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.white)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 背景：原稿是一张 619x321 的 JPEG 斜向色块，放大必糊，改用等价的
        # 线性渐变重画（左白 -> 右下极浅灰）
        bg = QLinearGradient(QPointF(0, 0), QPointF(NATIVE_W, NATIVE_H))
        bg.setColorAt(0.0, QColor(255, 255, 255))
        bg.setColorAt(0.55, QColor(250, 250, 251))
        bg.setColorAt(1.0, QColor(241, 242, 244))
        p.fillRect(QRectF(0, 0, NATIVE_W, NATIVE_H), bg)

        # 强调方点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GOLD)
        p.drawRect(QRectF(39, 38, 9, 9))

        # 英文标语
        p.setPen(MUTED)
        p.setFont(_font("latin", 12, QFont.Weight.Normal, 0.6))
        p.drawText(QPointF(62, 47), EYEBROW)

        # 字标
        p.setPen(INK)
        p.setFont(_font("tech", 103.5, QFont.Weight.Normal, 1.2))
        p.drawText(QPointF(40, 155), WORDMARK)

        # 黄短线
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GOLD)
        p.drawRect(QRectF(39, 199, 76, 5))

        # 中文标题 / 副标题
        p.setPen(TITLE)
        p.setFont(_font("cn", 27.5))
        p.drawText(QPointF(39, 261), HEADLINE)

        p.setPen(SUB)
        p.setFont(_font("cn", 15.2))
        p.drawText(QPointF(39, 283), SUBHEAD)

        # 右上角图标
        icon = QPixmap(_icon_path())
        if not icon.isNull():
            p.drawPixmap(QRectF(454, 54, 122, 122), icon, QRectF(icon.rect()))

        # 署名：原稿是几乎不可见的浅灰，作为签名保留
        p.setPen(SIGN)
        p.setFont(_font("cn", 12))
        p.drawText(QRectF(400, 296, 215, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   SIGNATURE)

        p.end()
        self._cache = pix
        self._cache_dpr = dpr
        return pix

    def _paint_footer(self, p: QPainter) -> None:
        # 底栏（原稿该层导出时被压成 41px 高，这里按 320..363 补齐）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FOOTER_BG)
        p.drawRect(QRectF(0, FOOTER_TOP, NATIVE_W, NATIVE_H - FOOTER_TOP))
        p.setBrush(DIVIDER)
        p.drawRect(QRectF(0, DIVIDER_TOP, NATIVE_W, 2))

        base = 347.0

        p.setPen(GOLD)
        p.setFont(_font("latin", 16))
        p.drawText(QPointF(39, base), version_text())

        # 文案固定，只有省略号逐字增长；用户不关心真实阶段。
        # 点用 Arial 画(与设计稿一致)，中文字体的句点间距过散。
        p.setPen(SUB)
        p.setFont(_font("cn", 15.2))
        p.drawText(QPointF(STATUS_X, base), STATUS_TEXT)
        text_w = p.fontMetrics().horizontalAdvance(STATUS_TEXT)
        p.setFont(_font("latin", 16))
        p.drawText(QPointF(STATUS_X + text_w, base), "." * self._dots)

        # 进度轨
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(TRACK_X, TRACK_Y, TRACK_W, TRACK_H), 2, 2)

        ratio = max(0.03, min(1.0, self._shown))
        fill_w = (TRACK_W - 6) * ratio + 6
        p.setBrush(BLUE)
        p.drawRoundedRect(QRectF(TRACK_X, TRACK_Y, fill_w, TRACK_H), 2, 2)

        # 末端圆点：白环 + 金心，压在浅灰轨上更清楚
        cx = TRACK_X + fill_w
        cy = TRACK_Y + TRACK_H / 2
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, cy), 7.0, 7.0)
        p.setBrush(BLUE)
        p.drawEllipse(QPointF(cx, cy), 5.2, 5.2)
