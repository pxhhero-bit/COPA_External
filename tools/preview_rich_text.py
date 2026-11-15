"""把批阅副本里的字符级标红渲染成 PNG，用于「打开 Excel 之前先看一眼」.

为什么不用截 Excel 的图：批阅是无头跑的（服务端/CI 都可能），而 xlsx 想在
没有 Excel 的机器上出图要么靠 LibreOffice，要么自己画。这里选后者——只渲染
**被标注的那几格**，用原件与副本并排对照，看的是「到底哪几个字红了」，
不需要把整张报价单画出来。

渲染口径尽量贴近 Excel：
  · 单元格字体取原格字体名与字号（宋体 10pt 在 96dpi 下约 13.3px，按 2 倍画）；
  · 保留换行与自动换行；
  · 红/橙 run 用与 annotate 同一套色值（FFC00000 / FFE36C09），不看 run 有没有 b；
  · 只画有红/橙 run 的格，避免出一张看不出重点的大图。
"""
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock

# 与 annotate._FONT_COLORS 同一口径（红色=必须改，橙色=建议确认）
MARK_COLORS = {"FFC00000": (192, 0, 0), "FFE36C09": (227, 108, 9)}

_CJK_FONTS = {
    "simei": "C:/Windows/Fonts/simsun.ttc",
    "宋体": "C:/Windows/Fonts/simsun.ttc",
    "微软雅黑": "C:/Windows/Fonts/msyh.ttc",
    "黑体": "C:/Windows/Fonts/simhei.ttf",
}
_UI_FONT = "C:/Windows/Fonts/msyh.ttc"
_UI_FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

SCALE = 2                      # 画 2 倍再按 1 倍保存，边缘才不糊
PAD = 14
WRAP_PX = 640                  # 单元格文本换行宽度（约为 Excel 里 60 字符宽的列）
BODY_PX = 14                   # 正文字号（px，1x）
TITLE_PX = 15
MONO_PX = 13


@dataclass
class CellView:
    """一格在「原件」与「批阅件」里的样子"""
    sheet: str
    coord: str
    before: List[Tuple[str, Optional[str]]]      # [(文字, 颜色 or None)]
    after: List[Tuple[str, Optional[str]]]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size * SCALE)
    except OSError:
        return ImageFont.truetype(_UI_FONT, size * SCALE)


def _runs(value, colored_only: bool = False) -> List[Tuple[str, Optional[str]]]:
    """单元格值 -> [(文字, 颜色键)]。纯文本格整段 None。"""
    if not isinstance(value, CellRichText):
        return [(str(value or ""), None)]
    out = []
    for part in value:
        if isinstance(part, TextBlock):
            rgb = part.font.color.rgb if part.font and part.font.color else None
            key = str(rgb).upper() if rgb else None
            out.append((part.text, key if key in MARK_COLORS else None))
        else:
            out.append((str(part), None))
    if not colored_only:
        return out
    return [(t, c) for t, c in out if c]


def _has_mark(value) -> bool:
    if not isinstance(value, CellRichText):
        return False
    return any(c for _, c in _runs(value))


def _wrap(runs: Sequence[Tuple[str, Optional[str]]], width_px: int,
          font: ImageFont.FreeTypeFont) -> List[List[Tuple[str, Optional[str]]]]:
    """按像素宽度折行，同时保留颜色分段（中文逐字断，英文按词粗断）"""
    lines: List[List[Tuple[str, Optional[str]]]] = [[]]
    line_w = 0
    for text, color in runs:
        for ch in text:
            if ch == "\n":
                lines.append([])
                line_w = 0
                continue
            w = font.getlength(ch)
            if line_w + w > width_px and lines[-1]:
                lines.append([])
                line_w = 0
            lines[-1].append((ch, color))
            line_w += w
    return [ln for ln in lines] or [[]]


def _draw_runs(draw, x: int, y: int, runs, font, base_color=(0, 0, 0)) -> None:
    for text, color in runs:
        rgb = MARK_COLORS.get(color, base_color) if color else base_color
        draw.text((x, y), text, font=font, fill=rgb)
        x += font.getlength(text)


def _cell_height(runs, font, width_px: int) -> int:
    lines = _wrap(runs, width_px, font)
    return len(lines) * int((font.size or 16) * 1.5) + PAD * 2 * SCALE


def _load(path: str):
    return load_workbook(path, rich_text=True, data_only=False)


def collect(original: str, annotated: str,
            cells: Optional[Iterable[Tuple[str, str]]] = None) -> List[CellView]:
    """找出「批阅件里有红字」的格，配上原件的同一格（不传 cells 就自动找）"""
    wb_a = _load(annotated)
    wb_o = _load(original)
    views: List[CellView] = []
    targets = list(cells) if cells else None
    for ws in wb_a.worksheets:
        if targets is None and ws.title == "诊断":
            continue
        for row in ws.iter_rows():
            for cell in row:
                if targets is not None:
                    if (ws.title, cell.coordinate) not in targets:
                        continue
                elif not _has_mark(cell.value):
                    continue
                before = _runs(wb_o[ws.title][cell.coordinate].value) \
                    if ws.title in wb_o.sheetnames else [("", None)]
                views.append(CellView(ws.title, cell.coordinate,
                                      before, _runs(cell.value)))
    return views


def render(views: List[CellView], out_png: str, width: int = 1080,
           subtitle: str = "", issues: Sequence[str] = (),
           max_cells: int = 2, show_legacy: bool = True) -> str:
    """画图。每格一组：原件框 +（旧做法）+ 批阅框；issues 是诊断表里的原话.

    show_legacy 会多画一个「整格标红」的对照框——以前定位不到区间时就是这么
    干的，方格 7 行全红，看单的人得自己回头找哪一行错了。
    """
    ui = _font(_UI_FONT, BODY_PX)
    ui_b = _font(_UI_FONT_BOLD, BODY_PX)
    title = _font(_UI_FONT_BOLD, TITLE_PX)
    mono = _font(_UI_FONT, MONO_PX)
    cell_font = _font(_CJK_FONTS.get("宋体"), 12)

    views = views[:max_cells]
    body_w = (width - PAD * 2) * SCALE
    text_w = min(body_w - PAD * 2 * SCALE, WRAP_PX * SCALE)

    def legacy_runs(runs):
        text = "".join(t for t, _ in runs)
        return [(text, "FFC00000")]

    # 先量高，再按实际用量裁画布——比估总高可靠（估少了会截掉最后一行）
    blocks = []
    for view in views:
        h1 = _cell_height(view.before, cell_font, text_w)
        h2 = _cell_height(view.after, cell_font, text_w)
        h0 = _cell_height(legacy_runs(view.before), cell_font, text_w) \
            if show_legacy else 0
        blocks.append((view, h1, h0, h2))

    head_h = 78 * SCALE
    per_gap = 30 * SCALE
    canvas_h = head_h + sum(
        28 * SCALE + h1 + (24 * SCALE + 28 * SCALE + h0 if show_legacy else 0)
        + 24 * SCALE + 28 * SCALE + h2 for _, h1, h0, h2 in blocks) \
        + per_gap * len(blocks) + 140 * SCALE + (34 * SCALE * len(issues) if issues else 0)

    img = Image.new("RGB", (width * SCALE, canvas_h), (246, 248, 250))
    draw = ImageDraw.Draw(img)

    draw.text((PAD * SCALE, 20 * SCALE), "批阅副本 · 字符级标红预览",
              font=title, fill=(20, 24, 28))
    if subtitle:
        draw.text((PAD * SCALE, 46 * SCALE), subtitle, font=ui, fill=(90, 98, 108))

    def box(x, y, w, h, border, accent):
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6 * SCALE,
                               fill=(255, 255, 255), outline=border, width=SCALE)
        draw.rectangle([x + 1, y + 7 * SCALE, x + 5 * SCALE, y + h - 7 * SCALE],
                       fill=accent)

    def flow(runs, y):
        ty = y + PAD * SCALE
        for line in _wrap(runs, text_w, cell_font):
            _draw_runs(draw, PAD * SCALE * 2, ty, line, cell_font)
            ty += int(cell_font.size * 1.55)

    y = head_h
    for view, h1, h0, h2 in blocks:
        draw.text((PAD * SCALE, y), "{} · {}".format(view.sheet, view.coord),
                  font=ui_b, fill=(20, 24, 28))
        y += 28 * SCALE

        draw.text((PAD * SCALE, y), "原件（未批阅）", font=mono, fill=(110, 118, 126))
        y += 24 * SCALE
        box(PAD * SCALE, y, body_w, h1, (216, 222, 228), (200, 205, 210))
        flow(view.before, y)
        y += h1 + 10 * SCALE

        if show_legacy:
            draw.text((PAD * SCALE, y), "以前：定位不到就当整格错　7 行全红，还得自己找哪行",
                      font=mono, fill=(150, 120, 40))
            y += 24 * SCALE
            box(PAD * SCALE, y, body_w, h0, (226, 214, 190), (214, 186, 120))
            flow(legacy_runs(view.before), y)
            y += h0 + 10 * SCALE

        draw.text((PAD * SCALE, y), "现在：按解析出的字符区间标　只红那几个字",
                  font=ui_b, fill=(192, 0, 0))
        y += 24 * SCALE
        box(PAD * SCALE, y, body_w, h2, (192, 0, 0), (192, 0, 0))
        flow(view.after, y)
        y += h2 + per_gap

    if issues:
        draw.text((PAD * SCALE, y), "诊断表里的对应记录", font=ui_b, fill=(20, 24, 28))
        y += 32 * SCALE
        for line in issues:
            draw.text((PAD * SCALE, y), line, font=mono, fill=(60, 66, 72))
            y += 34 * SCALE

    y += PAD * SCALE
    img = img.crop((0, 0, width * SCALE, min(canvas_h, y)))
    img = img.resize((width, img.height // SCALE), Image.LANCZOS)
    img.save(out_png)
    return out_png
