"""Splash 合成脚本：底图 + 品牌文字 + 底部加载栏 -> 1200x800 PNG。

底图由 ImageGen 生成（无文字），文字统一在本脚本里绘制，保证中文字形
与版本号不会乱码。运行：

    QT_QPA_PLATFORM=offscreen python splash/compose_splash.py

生成结果输出到 splash/preview/。底图右下角带生成器水印，用底部渐变压掉。
"""
import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPen, QPixmap)

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1200, 800
FOOTER_H = 104
FOOTER_Y = H - FOOTER_H
GOLD = QColor("#FFC61A")

# 必须显式注册：offscreen 平台下 QFontDatabase.families() 为空，按名字
# 取字体一律落到无字形的兜底字体（中文和英文都会渲染成方框）。
FONT_FILES = [
    ("C:/Windows/Fonts/msyh.ttc", "cn"),
    ("C:/Windows/Fonts/msyhbd.ttc", "cnb"),
    ("C:/Windows/Fonts/bahnschrift.ttf", "tech"),
    ("C:/Windows/Fonts/consolab.ttf", "mono"),
]
FONT_IDS = {}


def register_fonts():
    for path, key in FONT_FILES:
        fid = QFontDatabase.addApplicationFont(path)
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                FONT_IDS[key] = fams[0]


def font(key, size, weight=QFont.Weight.Normal, spacing=0.0):
    f = QFont(FONT_IDS.get(key, ""))
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


VARIANTS = {
    "A_dark_blueprint": dict(
        src="raw/Splash_screen_background_artwo_2026-11-09T05-29-13.png",
        fg="#FFFFFF", sub="#CBCED4", faint="#8A8F99",
        footer=QColor(10, 10, 12), hair=QColor(255, 255, 255, 28),
        mask=QColor(0, 0, 0, 158),
    ),
    "B_light_swiss": dict(
        src="raw/Splash_screen_background_artwo_2026-11-09T05-29-28.png",
        fg="#111214", sub="#4A4F57", faint="#8B9099",
        footer=QColor(247, 248, 249), hair=QColor(0, 0, 0, 22),
        mask=QColor(255, 255, 255, 205),
    ),
    "C_dark_product": dict(
        src="raw/Splash_screen_background_artwo_2026-11-09T05-29-45.png",
        fg="#FFFFFF", sub="#D4D7DC", faint="#93999F",
        footer=QColor(8, 9, 10), hair=QColor(255, 255, 255, 26),
        mask=QColor(0, 0, 0, 150),
    ),
}

EYEBROW = "M E A S U R E  ·  S E L E C T  ·  Q U O T E"
SUBTITLE = "工业称重设备  选型与报价系统"
TAGS = "称重模块 · 台秤 · 平台秤 · 汽车衡"
STATUS = "正在加载产品库与选型规则…"
VERSION = "v1.41 Beta"


def _center_crop(pix, w, h):
    """等比铺满后居中裁切，避免拉伸变形。"""
    if pix.isNull():
        raise SystemExit("底图读取失败")
    scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    x = max(0, (scaled.width() - w) // 2)
    y = max(0, (scaled.height() - h) // 2)
    return scaled.copy(x, y, w, h)


def compose(name, cfg):
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    p.drawPixmap(0, 0, _center_crop(QPixmap(os.path.join(HERE, cfg["src"])), W, H))

    # 左侧压暗/提亮，保证文字对比度
    g = QLinearGradient(0, 0, W * 0.74, 0)
    c0 = QColor(cfg["mask"])
    c1 = QColor(cfg["mask"])
    c1.setAlpha(0)
    g.setColorAt(0.0, c0)
    g.setColorAt(0.60, c0)
    g.setColorAt(1.0, c1)
    p.fillRect(QRectF(0, 0, W, H), g)

    # ---- 文字块 ----
    x = 96
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(GOLD)
    p.drawRect(QRectF(x, 238, 9, 9))

    p.setPen(QColor(cfg["faint"]))
    p.setFont(font("tech", 13, QFont.Weight.Medium, 1.4))
    p.drawText(QRectF(x + 22, 229, 500, 28),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, EYEBROW)

    p.setPen(QColor(cfg["fg"]))
    p.setFont(font("tech", 104, QFont.Weight.DemiBold, 3.0))
    p.drawText(QRectF(x - 5, 262, 560, 126),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "COPA")

    p.fillRect(QRectF(x, 399, 76, 5), GOLD)

    p.setPen(QColor(cfg["sub"]))
    p.setFont(font("cnb", 27, QFont.Weight.Bold, 1.2))
    p.drawText(QRectF(x, 424, 600, 46),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, SUBTITLE)

    p.setPen(QColor(cfg["faint"]))
    p.setFont(font("cn", 15, QFont.Weight.Normal, 0.8))
    p.drawText(QRectF(x, 474, 600, 30),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, TAGS)

    # ---- 底部渐隐 + 信息栏（同时压掉底图右下角水印）----
    fade = QLinearGradient(0, 520, 0, FOOTER_Y + 8)
    fc = QColor(cfg["footer"])
    t0 = QColor(fc)
    t0.setAlpha(0)
    fade.setColorAt(0.0, t0)
    fade.setColorAt(0.72, QColor(fc.red(), fc.green(), fc.blue(), 220))
    fade.setColorAt(1.0, fc)
    p.fillRect(QRectF(0, 520, W, FOOTER_Y + 8 - 520), fade)

    p.fillRect(QRectF(0, FOOTER_Y, W, FOOTER_H), fc)
    p.setPen(QPen(cfg["hair"], 1))
    p.drawLine(0, FOOTER_Y, W, FOOTER_Y)

    cy = FOOTER_Y + FOOTER_H / 2 - 1
    p.setPen(QColor(GOLD))
    p.setFont(font("tech", 14, QFont.Weight.DemiBold, 1.6))
    p.drawText(QRectF(x, cy - 13, 120, 26),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, VERSION)

    p.setPen(QColor(cfg["faint"]))
    p.setFont(font("cn", 13))
    p.drawText(QRectF(x + 96, cy - 13, 480, 26),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, STATUS)

    # 进度条：轨道 + 已经过段 + 末端光点
    tw, th = 236.0, 4.0
    tx = W - 96 - tw
    ty = cy - th / 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 40) if name[0] in "AC" else QColor(0, 0, 0, 30))
    p.drawRoundedRect(QRectF(tx, ty, tw, th), 2, 2)
    p.setBrush(GOLD)
    p.drawRoundedRect(QRectF(tx, ty, tw * 0.46, th), 2, 2)
    p.drawEllipse(QRectF(tx + tw * 0.46 - 3.5, ty - 2.5, 9, 9))

    p.end()
    out_dir = os.path.join(HERE, "preview")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"splash_{name}.png")
    img.save(out)                  # 后缀即 .png，格式由 Qt 自行判定
    return out


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841  QPainter 需要 GUI 上下文
    register_fonts()
    if not FONT_IDS:
        raise SystemExit("字体注册失败")
    for name, cfg in VARIANTS.items():
        print("->", compose(name, cfg))


if __name__ == "__main__":
    main()
