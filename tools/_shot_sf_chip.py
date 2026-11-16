# -*- coding: utf-8 -*-
"""安全系数色块效果截图脚本(临时)：4 个样例 -> COPA/output/sf_chip/"""
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication([])

# 离屏平台的字体库为空(中文全成方块)，显式挂系统雅黑；正式运行走 windows
# 平台不触发这段
for _font_path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
    _fid = QFontDatabase.addApplicationFont(_font_path)

    if _fid >= 0 and QFontDatabase.applicationFontFamilies(_fid):
        _family = QFontDatabase.applicationFontFamilies(_fid)[0]
        app.setFont(QFont(_family, 9))
        break

from COPA.apps.Checklist import QuoteListItem, sf_zone
from COPA.apps.Desk import EngineService
from COPA.apps.Parser import Parser

OUT_DIR = os.path.join(_ROOT, "COPA", "output", "sf_chip")
os.makedirs(OUT_DIR, exist_ok=True)

DESC = "FT模块，碳钢，4支点，料重5吨，皮重450公斤。仪表3306，PN通讯。"
parser = Parser()
parsed = parser.parse_quote_text(DESC)
data = parsed["data"]
data["req_com1"] = data.get("req_com1") or parser.default_req_com1()
entry = {
    "description": DESC, "item_type": "称重模块",
    "quote_info": {"quote_id": 1, "quantity": 1}, "onsite_service": False,
    "parsed": parsed, "Ex_P": False, "high_precision": False,
    "metrology": False, "digital": False,
}
buf, so = io.StringIO(), sys.stdout
sys.stdout = buf
try:
    result = EngineService().run_batch([entry])[0]
finally:
    sys.stdout = so

# (标题, 传感器型号, 说明) —— 全部是数据表里真实存在的型号，
# 后两个因 SF 越界不在候选下拉里，靠人工改选(下拉可编辑)触发
CASES = [
    ("样例1  默认推荐", "SLB-2268kg-BH-C3"),
    ("样例2  改选大容量", "SLB-3000kg-BH-C3"),
    ("样例3  误选小容量", "SLB-1134kg-BH-C3"),
    ("样例4  误选过大容量", "SB14-4536kg-BH-C3 Y=11500"),
]

CARD_W, CARD_H, CAP_H, GAP, MARGIN = 596, 230, 26, 14, 24
shots = []

for idx, (caption, sensor) in enumerate(CASES, 1):
    item = QuoteListItem()
    item.load_result(result, quantity=1, params=data)
    item.resize(CARD_W, CARD_H)
    item.sensorComBox.setCurrentText(sensor)
    item.show()
    app.processEvents()

    sf = item._resolve_sf(item.sensorComBox.currentText())
    color, desc = sf_zone(sf)
    chip_text = item.sfChip.text()

    pix = item.grab()
    path = os.path.join(OUT_DIR, "sample{}_{}.png".format(idx, chip_text))
    pix.save(path)

    shots.append((caption, sf, chip_text, color, desc, pix))
    print("{}: {} -> SF={:.2f} 色块={} 底色={} ({})".format(
        caption, sensor, sf, chip_text, color, desc))

total_h = MARGIN * 2 + len(shots) * (CAP_H + CARD_H) + (len(shots) - 1) * GAP
canvas = QImage(CARD_W + MARGIN * 2, total_h, QImage.Format.Format_ARGB32)
canvas.fill(QColor("#FFFFFF"))

painter = QPainter(canvas)
painter.setFont(QFont("Microsoft YaHei", 9))
y = MARGIN

for idx, (caption, sf, chip_text, color, desc, pix) in enumerate(shots, 1):
    painter.setPen(QColor("#555555"))
    painter.drawText(MARGIN, y + 18, "{}    SF={:.2f}    色块：{}".format(
        caption, sf, desc))
    y += CAP_H
    painter.drawPixmap(MARGIN, y, pix)
    y += CARD_H + GAP

painter.end()
combined = os.path.join(OUT_DIR, "sf_chip_4cases.png")
canvas.save(combined)
print("合并图:", combined)
