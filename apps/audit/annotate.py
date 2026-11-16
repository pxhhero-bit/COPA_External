"""批阅副本：把 Report 里的问题标回原表，另存一份 xlsx/xlsm.

设计约束（每条都是踩过的坑，改之前先看这里）：

1. **只读原件、只写新文件**。报价单是能直接发客户的东西，绝不原位改。
2. **以 data_only=False 载入**。data_only=True 会把公式读成缓存值，另存后公式全变常量。
3. **xlsm 用 keep_vba=True**，且另存后缀仍是 .xlsm，否则宏丢、文件打不开。
4. **标注只认 Issue.anchor**，不重新判一遍，否则会出现"报告说 A、文件标 B"。
5. **不打底色，只改字体（唯一例外 L12 空缺位整格填黄）**：整行/整格填色会把
   报价单变成花花绿绿的一块，业务看单反而更慢。现在的口径是「有问题的字段 =
   红字加粗（或橙字加粗）」，其余一律不动。字符级底纹在 SpreadsheetML 里根本
   不存在（rich text 的 run 没有 fill），所以 L7 缺参用「标签 + 两个空格设为
   红字加粗下划线 + 批注」，白底上也看得见。L12 备注缺传感器型号是空格子里
   没字可标的情形，用户拍板整格填黄。
6. **写完重开做保真自检**（sheet / 合并 / 公式 / 图片 / 图表），丢失的写进 warnings，
   调用方必须说出来——掉图的报价单不能直接发客户。
"""
import copy
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.styles.colors import Color

from COPA.apps.audit.model import (LEVEL_RED, LEVEL_YELLOW, SPAN_CELL,
                                   SPAN_DESC, Report)
from COPA.apps.audit.report import annotate_filename
from COPA.apps.audit.desclib import RE_CAP

# 字体色：红=必须改，橙=建议确认。不用底色，报价单本身已经是彩色的。
_FONT_COLORS = {
    LEVEL_RED: "FFC00000",
    LEVEL_YELLOW: "FFE36C09",
}

# 反查用：再标注时把已有的红/橙 run 认回来（红压黄，不能越标越轻）
_LEVEL_BY_RGB = {rgb.upper(): level for level, rgb in _FONT_COLORS.items()}

# 整格填黄仅用于「空缺位」类问题（L12 备注缺传感器型号）：空格子里没有
# 字可红，只能给格子本身上色提示"这里缺东西"（用户拍板的口径）
_FILL_YELLOW = "FFFFFF00"

_PLACEHOLDER_UNDERLINE = "single"   # 占位空格带下划线，白底上才看得见位置

_SHEET_TITLE = "诊断"

# 行首是备注行：中文「备注：」与英文「Remarks:」/「Note:」。L14 只红那一行，
# 型号行与其余参数行不连坐。
_RE_NOTE_START = re.compile(r"^(?:备注|remarks?|notes?)\s*[:：]", re.IGNORECASE)

# 缺参标签：中文模板与英文模板的写法都覆盖，用于把「两个空格」插到正确位置
_MISSING_LABELS = {
    "量程": ("量程", "Capacity", "capacity"),
    "台面尺寸": ("台面规格", "台面尺寸", "台面", "Platform", "platform", "Table Size"),
    "材质": ("材质", "Material", "material"),
    "分度值": ("分度值", "Division", "division"),
}


class AuditExportError(Exception):
    """导出失败（文件被占用 / 旧格式 / 权限），message 直接可展示给用户"""


@dataclass
class AnnotateResult:
    path: str = ""
    issues: int = 0
    red_rows: int = 0
    yellow_rows: int = 0
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)   # 定位不到单元格的问题
    fidelity: Dict[str, Dict[str, int]] = field(default_factory=dict)
    digest: str = ""                                  # 快照摘要（mark.py 写入）

    @property
    def degraded(self) -> bool:
        """保真自检发现丢失（图片/图表/公式/合并），调用方必须在界面提示"""
        return any("丢失" in w or "减少" in w or "不够" in w for w in self.warnings)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _plain(value) -> str:
    """单元格值 -> 纯文本（富文本按段拼回，不丢内容）"""
    if value is None:
        return ""
    if isinstance(value, CellRichText):
        return "".join(str(block) for block in value)
    return str(value)


def _merged_index(ws) -> Dict[Tuple[int, int], object]:
    """(row, col) -> 合并区域。样式只能写在锚点上，写 MergedCell 会丢样式。"""
    index: Dict[Tuple[int, int], object] = {}
    for rng in ws.merged_cells.ranges:
        for row in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                index[(row, col)] = rng
    return index


def _cell_at(ws, row: int, col: int, index):
    """取可写样式的单元格：合并区回落左上角锚点，越界返回 None。"""
    if row < 1 or col < 1:
        return None
    try:
        ws.cell(row, col)
    except (ValueError, IndexError):
        return None
    rng = index.get((row, col))
    target = (rng.min_row, rng.min_col) if rng is not None else (row, col)
    try:
        return ws.cell(target[0], target[1])
    except (ValueError, IndexError):
        return None


def _mark_font(cell, level: str) -> bool:
    """把整格文字改成红/橙加粗，其余字体属性（字号、字体名、斜体）保持原样。"""
    if cell is None:
        return False
    try:
        font = copy.copy(cell.font)
        font.color = Color(rgb=_FONT_COLORS.get(level, _FONT_COLORS[LEVEL_YELLOW]))
        font.bold = True
        cell.font = font
        return True
    except (AttributeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# L7 缺参：两空格占位 + 批注
# ---------------------------------------------------------------------------

def _insert_placeholders(text: str, missing: List[str]) -> Tuple[str, List[Tuple[int, int]]]:
    """在缺参位置插两个空格，返回 (新文本, 需标红区间列表)。

    区间覆盖「参数标签 + 两个空格」——只标空格的话白底上什么都看不见，
    把标签一起标红加粗，读者一眼就知道是这一项没填。

    定位规则：
      1. 描述里有该参数的标签（分度值 / Division …），且标签所在行的剩余部分
         不含数字 —— 值就是空的，空格插在这一行末尾（如「分度值e=d=  」）；
      2. 标签后面已经有数字（说明不是缺在这儿），换下一个标签；
      3. 全都没有，说明整项漏写 —— 追加到文本末尾另起一行。

    先把所有插入点算出来再统一插入，避免多次插入导致前面的下标失效。
    """
    inserts: List[Tuple[int, Optional[int]]] = []      # (插入点, 标签起点)
    tail_needed = False
    for name in missing:
        point = None
        label_start = None
        for label in _MISSING_LABELS.get(name, (name,)):
            match = re.search(re.escape(label), text)
            if not match:
                continue
            line_end = text.find("\n", match.end())
            line_end = len(text) if line_end < 0 else line_end
            if re.search(r"\d", text[match.end():line_end]):
                continue
            # 空格放在行尾标点之前，排版更接近正常写法（「分度值：  ；」）
            point = line_end
            while point > match.end() and text[point - 1] in "；;，, \t":
                point -= 1
            label_start = match.start()
            break
        if point is None:
            tail_needed = True
        else:
            inserts.append((point, label_start))

    out = text
    for point, _ in sorted(inserts, key=lambda item: item[0], reverse=True):
        out = out[:point] + "  " + out[point:]

    def _shifted(pos: int) -> int:
        """插入点严格在 pos 之前的，都会把 pos 往后推 2 格"""
        return pos + 2 * sum(1 for point, _ in inserts if point < pos)

    marks: List[Tuple[int, int]] = []
    for point, label_start in sorted(inserts, key=lambda item: item[0]):
        start = _shifted(point)
        marks.append((_shifted(label_start) if label_start is not None else start,
                      start + 2))

    if tail_needed:
        if out and not out.endswith("\n"):
            out += "\n"
        start = len(out)
        out += "  "
        marks.append((start, start + 2))

    marks.sort()
    return out, marks


def _compose(text: str, ranges: List[Tuple[int, int, str, bool]]):
    """把可能重叠的区间拆成不重叠分段，重叠处取更严重的级别（红压黄）。

    例：一段黄 + 其中一句红 -> [黄段][红段][黄段]，而不是被红整段吞掉。
    """
    points = sorted({0, len(text)} | {s for s, _, _, _ in ranges}
                    | {e for _, e, _, _ in ranges})
    out = []
    for start, end in zip(points, points[1:]):
        if start >= end:
            continue
        level, underline = None, False
        for s, e, lv, ul in ranges:
            if s <= start and end <= e:
                if level is None or (level == LEVEL_YELLOW and lv == LEVEL_RED):
                    level, underline = lv, ul
        out.append((start, end, level, underline))
    return out


def _existing_ranges(cell) -> List[Tuple[int, int, str, bool]]:
    """还原单元格里已经标好的红/橙区间（供二次标注叠加）。

    同一格会先后被行级问题、文件级问题标多轮（兰达 261027 的 C14：先 L6 红
    型号行，再 L31 黄描述行）。每轮都从纯文本重建富文本就会把上一轮的红色
    覆盖掉——红色是「必须改」，不能被黄色提示洗掉，所以先认回旧 run 再叠加。
    """
    if not isinstance(cell.value, CellRichText):
        return []
    out, pos = [], 0
    for part in cell.value:
        if isinstance(part, TextBlock):
            piece = part.text
            color = getattr(part.font, "color", None)
            rgb = getattr(color, "rgb", None) if color is not None else None
            level = _LEVEL_BY_RGB.get(str(rgb).upper()) if rgb else None
            if level and piece:
                out.append((pos, pos + len(piece), level,
                            bool(getattr(part.font, "u", None))))
        else:
            piece = str(part)
        pos += len(piece)
    return out


def _apply_rich(cell, text: str, ranges: List[Tuple[int, int, str, bool]],
                warnings: List[str]) -> None:
    """只把 ranges 指定的片段设为红/橙加粗（占位空格额外加下划线），其余保持原样。

    传进来的 ranges 必须基于 text 计算（调用方负责插入占位后再定位）。
    富文本不可用时退回纯文本：文字内容不变，只是少了这层视觉提示。
    """
    try:
        base_font = cell.font
        base = InlineFont(
            rFont=base_font.name, sz=base_font.sz, b=base_font.b, i=base_font.i,
            strike=base_font.strike, color=copy.copy(base_font.color),
            family=base_font.family, charset=base_font.charset,
            scheme=base_font.scheme, u=base_font.u, vertAlign=base_font.vertAlign,
        )
        marks = {
            LEVEL_RED: InlineFont(rFont=base_font.name, sz=base_font.sz, b=True,
                                  color=Color(rgb=_FONT_COLORS[LEVEL_RED])),
            LEVEL_YELLOW: InlineFont(rFont=base_font.name, sz=base_font.sz, b=True,
                                     color=Color(rgb=_FONT_COLORS[LEVEL_YELLOW])),
        }
        marks_underlined = {
            level: InlineFont(rFont=font.rFont, sz=font.sz, b=True, color=font.color,
                              u=_PLACEHOLDER_UNDERLINE)
            for level, font in marks.items()
        }

        blocks: List[TextBlock] = []
        for start, end, level, underline in _compose(text, ranges):
            piece = text[start:end]
            if not piece:
                continue
            if level is None:
                blocks.append(TextBlock(base, piece))
            else:
                font = (marks_underlined if underline else marks).get(level,
                                                                     marks[LEVEL_RED])
                blocks.append(TextBlock(font, piece))
        cell.value = CellRichText(blocks)
    except Exception as exc:               # 富文本不可用不是致命问题
        cell.value = text
        warnings.append("「{}」无法写入字符级标注（{}），已用纯文本占位".format(
            cell.coordinate, exc))


# 问题码 -> 描述里对应的参数标签。有了它才能只标有问题的那个字段，
# 而不是把「型号 + 十余行描述」整段染红（报价单常见型号与描述同列）。
_FIELD_LABELS = {
    "L3": ("量程", "CAPACITY"),
    "L4": ("台面", "PLATFORM", "TABLE SIZE"),
    "L5": ("材质", "MATERIAL"),
    "L6": ("防爆", "EXPLOSION", "EX-PROOF"),
    "L23": ("电池", "充电", "BATTERY", "CHARGER"),
    "L24": ("仪表", "供电", "电源", "电池", "INDICATOR"),
    "L25": ("材质", "供电", "电源", "防爆", "拉杆", "外壳", "安装"),
}

_SHORT_CELL = 40        # 短文本整格标红就够清楚，不必逐行拆


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).upper()


def _line_ranges(text: str) -> List[Tuple[int, int]]:
    out, start = [], 0
    for line in text.split("\n"):
        out.append((start, start + len(line)))
        start += len(line) + 1
    return out


def _model_line(item, text: str, lines: List[Tuple[int, int]]):
    key = _norm(item.model)
    if not key:
        return None
    for start, end in lines:
        if key in _norm(text[start:end]):
            return (start, end)
    return None


def _model_token_range(item, text: str):
    """型号那一段（只标型号码，不连坐整行「型号：…」）"""
    code = str(getattr(item, "model", "") or "").strip()
    if not code or not text:
        return None
    hit = _model_line(item, text, _line_ranges(text))
    if not hit:
        return None
    seg = text[hit[0]:hit[1]]
    m = re.search(re.escape(code), seg, re.IGNORECASE)
    if not m:
        return None
    return (hit[0] + m.start(), hit[0] + m.end())


def _span_ranges(issue, item, text: str) -> List[Tuple[int, int]]:
    """问题自带字符区间时，直接换算成单元格内坐标.

    这是唯一可靠的定位路径：区间是解析描述时记下的，不靠事后反查标签。
    需要一次换算是因为 Issue.span 相对的是 `item.desc`，而单元格文本可能
    还含「型号」行（型号与描述同格的老版式），所以先找 desc 在格内的起点。
    换算不出来时返回空，交给 _issue_ranges 的老办法兜底。
    """
    span = getattr(issue, "span", None)
    desc = getattr(item, "desc", "") or ""
    if not span or not text or not desc:
        return []
    base = text.find(desc)
    if base < 0:
        stripped = desc.strip()
        base = text.find(stripped) if stripped else -1
        if base < 0:
            return []
    start, end = base + span[0], base + span[1]
    if not (0 <= start < end <= len(text)):
        return []
    if getattr(issue, "code", "") in ("L3", "L4"):
        # 量程/台面这类「型号与描述不符」：两边都是改法的候选（改描述或换型号），
        # 只标描述里的数字会让人以为型号一定对。两处一起标才看得出是哪两边不一致。
        model_hit = _model_token_range(item, text)
        if model_hit:
            return [model_hit, (start, end)]
    return [(start, end)]


def _cell_span_ranges(issue, cell, text: str) -> List[Tuple[int, int]]:
    """文件级问题的字符区间 -> 单元格内区间（直接可用，不做换算）.

    与 _span_ranges 的区别只有一个：这里的 span 是相对**锚点格**的（抬头跨格
    拼接时由 CellMap 换好坐标），行级问题那个是相对 item.desc 的。混着用会把
    坐标二次平移，标到隔壁字上。
    数字格/公式格不碰：写成 CellRichText 会把数字变成文本、把公式变成字符串。
    """
    span = getattr(issue, "span", None)
    if not span or not text:
        return []
    if isinstance(cell.value, (int, float)) or cell.data_type == "f":
        return []
    start, end = span
    if 0 <= start < end <= len(text):
        return [(start, end)]
    return []


def _issue_ranges(issue, item, text: str) -> List[Tuple[int, int]]:
    """这条问题在单元格文本里该标哪一段。返回空 = 定位不到，调用方整格标红。"""
    if not text or (len(text) <= _SHORT_CELL and "\n" not in text):
        return []
    lines = _line_ranges(text)

    if issue.code in ("L13", "L15", "L22", "L26"):
        # 字符级：actual 存的是纯 token（仪表型号 / 分度值段 / 供电字样），
        # 格内原样可寻
        token = str(issue.actual or "").strip()
        if token and "\n" not in token:
            m = re.search(re.escape(token), text, re.IGNORECASE)
            if m:
                return [(m.start(), m.end())]
        return []

    if issue.code == "L14":
        # 行级：只红描述内的备注行，不连坐型号行（含英文 Remarks 行）
        return [(s, e) for s, e in lines
                if _RE_NOTE_START.match(text[s:e].strip())]

    if issue.code in ("L30", "L31"):
        # 电池类只标提到电池/电源/充电器的行。兰达 261027 的教训：型号与描述
        # 同在一格时，整格标红会让「型号」看着像结论有问题（实际型号没判错），
        # 用户会以为是标注 bug。
        hits = [(s, e) for s, e in lines
                if re.search(r"电池|电源|充电器", text[s:e])]
        return hits

    labels = _FIELD_LABELS.get(issue.code)
    if labels:
        if issue.code in ("L24", "L25"):
            # 缺失类：描述里根本不提供电字样（有的话就不会报 L24），字段标签
            # 命中必然为空，只剩型号行——标型号会让人误以为型号写错了，
            # 这里整格标红才对应「整条描述缺一项」。
            return []
        model_hit = _model_line(item, text, lines)
        if issue.code == "L6" and model_hit:
            # 防爆问题要改的就是型号本身（补 -E 尾段）。但整行「型号：TCS-3kg
            # （FTBR-HS-003-2430）」染红会让人以为型号写错了，所以只标型号码。
            token = _model_token_range(item, text)
            return [token] if token else [model_hit]
        hits = [(s, e) for s, e in lines
                if any(label in text[s:e].upper() for label in labels)]
        if issue.code == "L3":
            # 行内收缩到量程值段（如「量程：60kg」标 60kg）——同一行里还有
            # 分度值/精度等级，整行连坐会让人以为它们也有问题
            narrowed = []
            for s, e in hits:
                m2 = RE_CAP.search(text[s:e])
                narrowed.append((s + m2.start(1), s + m2.end(2)) if m2 else (s, e))
            hits = narrowed
        # 量程/台面这类"型号与描述不符"，两处一起标才看得出是哪里不一致
        return ([model_hit] if model_hit else []) + hits

    if issue.code == "L9" or issue.code.startswith("L1"):
        hit = _model_line(item, text, lines)
        return [hit] if hit else []
    return []


def _highlight_tokens(issue) -> List[str]:
    """诊断表「问题」列里该加粗着色的关键词。

    用户口径：一句话太长，眼睛抓不到重点。把「缺的参数」「写错的原文」
    「引号里的具体值」切出来单独上色，其余正文保持常规字重。
    """
    out: List[str] = []
    for token in str(issue.missing or "").split(","):
        token = token.strip()
        if token:
            out.append(token)
    actual = str(issue.actual or "").strip()
    if 0 < len(actual) <= 24 and "\n" not in actual and actual not in ("-", "—"):
        out.append(actual)
    for match in re.finditer(r"「([^」]{1,24})」", issue.message or ""):
        out.append(match.group(1))
    seen, uniq = set(), []
    for token in sorted(out, key=len, reverse=True):   # 长的先占位，避免被短词切开
        if token not in seen:
            seen.add(token)
            uniq.append(token)
    return uniq


def _rich_message(issue):
    """问题列富文本：关键词红/橙加粗，其余正文不动。"""
    message = str(issue.message or "")
    tokens = _highlight_tokens(issue)
    if not message or not tokens:
        return message
    spans: List[Tuple[int, int]] = []
    for token in tokens:
        spans.extend((m.start(), m.end())
                     for m in re.finditer(re.escape(token), message))
    if not spans:
        return message
    spans.sort()
    merged: List[List[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    try:
        color = _FONT_COLORS.get(issue.level, _FONT_COLORS[LEVEL_YELLOW])
        font = InlineFont(rFont="宋体", sz=11, b=True, color=Color(rgb=color))
        blocks: List = []
        pos = 0
        for start, end in merged:
            if start > pos:
                blocks.append(message[pos:start])
            blocks.append(TextBlock(font, message[start:end]))
            pos = end
        if pos < len(message):
            blocks.append(message[pos:])
        return CellRichText(blocks)
    except Exception:
        return message


def _comment_text(issues: List) -> str:
    parts = []
    for issue in issues:
        lines = ["[{}] {} {}".format(issue.level_name, issue.code, issue.title)]
        if issue.message:
            lines.append(issue.message)
        # 不再写「期望/实际」：message 里已经带证据（快照 3 → 现 5、标题写 3 支点
        # 而数量 4 只），再加两行原文只是把批注撑长，用户反而要读三遍。
        if issue.advice:
            lines.append("建议：" + issue.advice)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _attach_comment(cell, text: str) -> None:
    """挂批注。原有批注保留在前面，不覆盖别人写的东西。"""
    if not text:
        return
    existing = cell.comment
    if existing is not None and existing.text:
        text = "{}\n\n—— COPA 批阅 ——\n{}".format(existing.text, text)
    comment = Comment(text, "COPA audit")
    comment.width, comment.height = 360, 180
    cell.comment = comment


# ---------------------------------------------------------------------------
# 追加「诊断」工作表
# ---------------------------------------------------------------------------

_DIAG_HEADERS = ("工作表", "行", "名称 / 型号", "问题码", "级别", "问题", "建议")
_DIAG_WIDTHS = (12, 6, 26, 8, 6, 62, 46)


def _append_sheet(wb, report: Report, when: datetime) -> str:
    title = _SHEET_TITLE
    index = 1
    while title in wb.sheetnames:
        index += 1
        title = "{}{}".format(_SHEET_TITLE, index)

    ws = wb.create_sheet(title)
    counts = report.item_counts
    if report.passed:
        summary = "未发现问题：{} 行明细全部通过".format(len(report.doc.items))
    else:
        summary = "发现 {} 条问题：严重 {} 条 / 提示 {} 条；红行 {}、黄行 {}、通过 {}、未识别行 {}".format(
            len(report.active_issues), report.count(LEVEL_RED), report.count(LEVEL_YELLOW),
            counts[LEVEL_RED], counts[LEVEL_YELLOW], counts["clean"],
            len(report.doc.unrecognized))

    ws["A1"] = "报价单批阅结果"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = "文件"
    ws["B2"] = os.path.basename(report.doc.path)
    ws["A3"] = "项目号"
    # 报告里的项目号必须与快照标题、报价页白字是同一个号，否则三处对不上账
    ws["B3"] = getattr(report.doc, "project_no", "") or "（未编号）"
    ws["A4"] = "批阅时间"
    ws["B4"] = when.strftime("%Y-%m-%d %H:%M:%S")
    ws["A5"] = "结论"
    ws["B5"] = summary
    ws["A6"] = "说明"
    ws["B6"] = ("红色加粗字=必须改，橙色加粗字=建议确认；只标记有问题的字段，不改动表格版式。"
                "描述中「参数名 + 空白」标红下划线的地方表示该参数缺失，详见单元格批注。")
    for row in range(2, 7):
        ws.cell(row, 1).font = Font(bold=True)
        # 抬头几行横跨整表：不合并会被列宽截断，结论那一句尤其明显
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
        ws.cell(row, 2).alignment = Alignment(vertical="center", wrap_text=row in (5, 6))
    ws.row_dimensions[5].height = 30
    ws.row_dimensions[6].height = 30

    header_row = 8
    for col, name in enumerate(_DIAG_HEADERS, 1):
        cell = ws.cell(header_row, col, name)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill(start_color="FF595959", end_color="FF595959",
                                fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    rows = _issue_rows(report)
    for offset, (sheet, item_label, issue) in enumerate(rows, 1):
        row = header_row + offset
        values = (sheet, issue.anchor[0] if issue.anchor else "", item_label,
                  issue.code, issue.level_name, issue.message, issue.advice)
        for col, value in enumerate(values, 1):
            cell = ws.cell(row, col, value)
            cell.alignment = Alignment(vertical="top", wrap_text=col in (3, 6, 7))
        ws.cell(row, 6).value = _rich_message(issue)      # 问题列：关键词单独着色
        level_cell = ws.cell(row, 5)
        level_cell.font = Font(bold=True,
                               color=Color(rgb=_FONT_COLORS.get(issue.level,
                                                                _FONT_COLORS[LEVEL_YELLOW])))
        level_cell.alignment = Alignment(horizontal="center", vertical="top")
        ws.row_dimensions[row].height = _row_height(values)

    for col, width in enumerate(_DIAG_WIDTHS, 1):
        ws.column_dimensions[ws.cell(header_row, col).column_letter].width = width
    if rows:
        ws.auto_filter.ref = "A{}:G{}".format(header_row, header_row + len(rows))
    ws.freeze_panes = ws.cell(header_row + 1, 1)

    # 七列也很宽，不设成一页宽的话打印/导 PDF 会横着切成两页
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = "A1:G{}".format(max(header_row, header_row + len(rows)))
    ws.print_title_rows = "{}:{}".format(header_row, header_row)
    return title


def _row_height(values) -> float:
    """按列宽估算换行行数，给诊断表的行定高。

    openpyxl 写出的行没有 customHeight 时，Excel 导出 PDF 并不会重算自动行高，
    结果是长句被压在 15pt 里、打印出来只剩半句。宁可算粗一点。
    """
    wrap_cols = {3: _DIAG_WIDTHS[2], 6: _DIAG_WIDTHS[5], 7: _DIAG_WIDTHS[6]}
    lines = 1
    for col, width in wrap_cols.items():
        text = str(values[col - 1] or "")
        per_line = max(int(width * 0.45), 8)       # 中文按两个字符宽算，再留点余量
        count = sum(max(1, -(-len(part) // per_line)) for part in text.split("\n"))
        lines = max(lines, count)
    return min(lines, 8) * 14 + 8


def _issue_rows(report: Report):
    """诊断 sheet 的行数据：文件级问题 + 行级问题，按 (sheet, 行, 码) 排"""
    rows = []
    sheet_of_row = {row.row: row.sheet for row in report.doc.unrecognized}
    sheet_of_row.update({s.row: s.sheet for s in report.doc.summaries})
    default_sheet = report.doc.sheets[0] if report.doc.sheets else ""
    for issue in report.doc.file_issues:
        if issue.ignored:
            continue
        row = issue.anchor[0] if issue.anchor else ""
        rows.append((sheet_of_row.get(row, default_sheet) if row else default_sheet,
                     "（文件级）", issue))
    for item in report.doc.items:
        for issue in item.active_issues:
            rows.append((item.sheet, item.label, issue))
    rows.sort(key=lambda r: (str(r[0]), str(r[1]), r[2].code))
    return rows


# ---------------------------------------------------------------------------
# 保真自检
# ---------------------------------------------------------------------------

def _fidelity(wb, exclude=()) -> Dict[str, int]:
    """统计可丢失物。exclude 用于排除我们新增的诊断表（它自带合并，会干扰对比）。"""
    merged = formulas = images = charts = 0
    sheets = 0
    for ws in wb.worksheets:
        if ws.title in exclude:
            continue
        sheets += 1
        merged += len(ws.merged_cells.ranges)
        images += len(getattr(ws, "_images", []))
        charts += len(getattr(ws, "_charts", []))
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    formulas += 1
    return {"sheets": sheets, "merged": merged, "formulas": formulas,
            "images": images, "charts": charts}


def _has_vba(path: str) -> bool:
    """zip 里有没有 vbaProject.bin。openpyxl 的 _fidelity 看不到宏，只能查包。"""
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            return any(name.endswith("vbaProject.bin") for name in z.namelist())
    except Exception:
        return False


def _check_fidelity(before: Dict[str, int], after: Dict[str, int]) -> List[str]:
    warnings: List[str] = []
    if after["images"] < before["images"]:
        warnings.append("图片丢失：原文件 {} 张，批阅副本 {} 张——请勿直接发客户，"
                        "改发原件 + 诊断报告".format(before["images"], after["images"]))
    if after["charts"] < before["charts"]:
        warnings.append("图表丢失：原文件 {} 个，批阅副本 {} 个——请抽查后再使用".format(
            before["charts"], after["charts"]))
    if after["formulas"] < before["formulas"]:
        warnings.append("公式减少：原文件 {} 个，批阅副本 {} 个——部分公式被固化为数值".format(
            before["formulas"], after["formulas"]))
    if after["merged"] < before["merged"]:
        warnings.append("合并单元格减少：{} -> {}（版式可能有细微变化）".format(
            before["merged"], after["merged"]))
    if after["sheets"] != before["sheets"]:
        warnings.append("工作表数量异常：原 {} 个，批阅副本 {} 个（不含诊断表）".format(
            before["sheets"], after["sheets"]))
    return warnings


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def annotate_workbook_ex(report: Report, out_dir: str,
                         when: Optional[datetime] = None) -> AnnotateResult:
    """生成批阅副本，返回详细信息（路径 / 告警 / 定位失败清单 / 保真数据）。"""
    when = when or datetime.now()
    src = report.doc.path
    ext = os.path.splitext(src)[1].lower()
    if ext == ".xls":
        raise AuditExportError("旧版 .xls 无法直接生成批阅副本，请先用 Excel 另存为 .xlsx 再批阅")
    if not os.path.exists(src):
        raise AuditExportError("找不到源文件：{}".format(src))

    try:
        wb = load_workbook(src, data_only=False, keep_vba=(ext == ".xlsm"))
    except PermissionError as exc:
        raise AuditExportError("源文件被占用（可能正在 Excel 中打开）：{}".format(src)) from exc
    except Exception as exc:
        raise AuditExportError("无法打开 {}：{}".format(os.path.basename(src), exc)) from exc

    before = _fidelity(wb)
    result = AnnotateResult()
    sheets = {ws.title: ws for ws in wb.worksheets}
    indexes = {name: _merged_index(ws) for name, ws in sheets.items()}

    # ---- 行级：只标问题字段，不动版式 ------------------------------------
    touched: Dict[Tuple[str, str], str] = {}     # 本轮已着色的格子 -> 级别
    for item in report.doc.items:
        issues = item.active_issues
        if not issues:
            continue
        ws = sheets.get(item.sheet)
        if ws is None:
            result.skipped.append("第 {} 行：工作表「{}」不在文件里".format(item.row, item.sheet))
            continue
        if item.row > ws.max_row:
            result.skipped.append("第 {} 行：超出工作表范围（文件可能已改动）".format(item.row))
            continue
        level = LEVEL_RED if any(i.level == LEVEL_RED for i in issues) else LEVEL_YELLOW
        if level == LEVEL_RED:
            result.red_rows += 1
        else:
            result.yellow_rows += 1

        # 同一格可能挂多条问题：按「该格内最严重」定色，红压黄
        by_cell: Dict[Tuple[int, int], List] = {}
        for issue in issues:
            if not issue.anchor:
                result.skipped.append("第 {} 行 {}：无定位坐标".format(item.row, issue.code))
                continue
            by_cell.setdefault(issue.anchor, []).append(issue)

        for (anchor_row, anchor_col), group in by_cell.items():
            cell_level = (LEVEL_RED
                          if any(i.level == LEVEL_RED for i in group) else LEVEL_YELLOW)
            cell = _cell_at(ws, anchor_row, anchor_col, indexes[item.sheet])
            if cell is None:
                result.skipped.append("第 {} 行：定位单元格越界".format(item.row))
                continue
            text = _plain(cell.value)

            # 数字格/公式格不能走富文本：把 5 写成 CellRichText，数量/单价/总价就
            # 从数字变成了文本（Excel 的 SUM 只对数字求和，下游汇总会静默漏算）；
            # 公式格更严重——富文本会直接把公式替换成字符串，副本丢公式。
            # 这两类没有「哪一段」可标，整格改字体即可（批注照常挂）。
            if (isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
                    or cell.data_type == "f"):
                if not _mark_font(cell, cell_level):
                    result.skipped.append("第 {} 行：无法设置字体".format(item.row))
                touched[(item.sheet, cell.coordinate)] = cell_level
                _attach_comment(cell, _comment_text(group))
                continue

            # 空缺位类问题（L12）：整格填黄——空格子里没字可标，只能给格子
            # 本身上色；其余问题仍走字体标注
            if any(i.mark == "fill_yellow" for i in group):
                try:
                    cell.fill = PatternFill("solid", fgColor=_FILL_YELLOW)
                except (AttributeError, TypeError):
                    result.skipped.append(
                        "第 {} 行：无法设置填充".format(item.row))

            # L7 缺参：先把空格插进去，后面的行定位都基于插入后的文本
            missing_issues = [i for i in group if i.code == "L7" and i.missing]
            ranges: List[Tuple[int, int, str, bool]] = []
            if missing_issues:
                missing = [m for m in str(missing_issues[0].missing).split(",") if m]
                text, marks = _insert_placeholders(text, missing)
                ranges += [(s, e, LEVEL_RED, True) for s, e in marks]

            for issue in group:
                if issue in missing_issues or issue.mark == "fill_yellow":
                    continue                     # 填黄类不走字体标注
                # 有 span 就按 span 标（精确到字）；L7 插过占位后坐标已偏移，
                # 这一轮只能退回标签反查。
                # span_scope=cell 的区间已经相对本格（抬头的跨格拼接换算过），
                # 再按 desc 平移一次就会标到隔壁字上。
                segments = []
                if issue.code == "L14":
                    # 备注行可能中英各一行（双语单），issue.span 只记第一处，
                    # 所以这里按行扫，把两种语言的备注行一起染
                    segments = _issue_ranges(issue, item, text)
                elif not missing_issues:
                    if getattr(issue, "span_scope", SPAN_DESC) == SPAN_CELL:
                        segments = _cell_span_ranges(issue, cell, text)
                    else:
                        segments = _span_ranges(issue, item, text)
                if not segments:
                    segments = _issue_ranges(issue, item, text)
                if not segments:
                    if not text:
                        # 空单元格没有文字可标，只能整格改字体
                        if not _mark_font(cell, issue.level):
                            result.skipped.append(
                                "第 {} 行：无法设置字体".format(item.row))
                        continue
                    # 定位不到就整格——但「型号 + 描述同格」的版式（兰达 261027）
                    # 要先把型号行摘出去：型号本身没判错，染红会被当成标注 bug
                    segments = [(0, len(text))]
                    if (anchor_row, anchor_col) == item.cells.get("model"):
                        lines = _line_ranges(text)
                        model_hit = _model_line(item, text, lines)
                        rest = [seg for seg in lines if seg != model_hit]
                        if rest:
                            segments = rest
                ranges += [(s, e, issue.level, False) for s, e in segments]

            if ranges:
                _apply_rich(cell, text, ranges, result.warnings)
                touched[(item.sheet, cell.coordinate)] = cell_level
            elif (cell_level and not text
                  and not any(i.mark == "fill_yellow" for i in group)
                  and not _mark_font(cell, cell_level)):
                result.skipped.append("第 {} 行：无法设置字体".format(item.row))

            _attach_comment(cell, _comment_text(group))

    # ---- 文件级问题（表头未识别 / 行未归类 / 汇总算术）---------------------
    sheet_of_row = {r.row: r.sheet for r in report.doc.unrecognized}
    sheet_of_row.update({s.row: s.sheet for s in report.doc.summaries})
    sheet_of_row.update({t.row: t.sheet for t in report.doc.qty_totals})
    for issue in report.doc.file_issues:
        if issue.ignored:
            continue
        if not issue.anchor:
            # 表头未识别这类问题本来就没有可标坐标，报告与诊断表里已有记录，
            # 不算"定位失败"，否则界面会把正常情况说成一堆错误。
            continue
        row = issue.anchor[0]
        sheet_name = issue.sheet or sheet_of_row.get(
            row, report.doc.sheets[0] if report.doc.sheets else "")
        ws = sheets.get(sheet_name)
        if ws is None or row > ws.max_row:
            result.skipped.append("{}：第 {} 行定位失败".format(issue.code, row))
            continue
        col = issue.anchor[1] if len(issue.anchor) > 1 and issue.anchor[1] else 1
        cell = _cell_at(ws, row, col, indexes[sheet_name])
        if cell is None:
            result.skipped.append("{}：第 {} 行定位失败".format(issue.code, row))
            continue
        key = (sheet_name, cell.coordinate)
        # 有字符区间就精确到字。参照系分两种：抬头那组（L35–L37）的区间已经由
        # CellMap 换算到锚点格，直接用；L30/L31 这类挂在描述上的，还要先按
        # 所属行把 desc 的落点找出来（型号与描述同格时会差出几行）。
        text = _plain(cell.value)
        if getattr(issue, "span_scope", SPAN_DESC) == SPAN_CELL:
            spanned = _cell_span_ranges(issue, cell, text)
        else:
            owner = next((it for it in report.doc.items
                          if it.sheet == sheet_name and it.row == row), None)
            spanned = _span_ranges(issue, owner, text) if owner is not None else []
        if spanned:
            ranges = _existing_ranges(cell) + [
                (s, e, issue.level, False) for s, e in spanned]
            _apply_rich(cell, text, ranges, result.warnings)
            touched[key] = (LEVEL_RED if issue.level == LEVEL_RED
                            or touched.get(key) == LEVEL_RED else LEVEL_YELLOW)
            _attach_comment(cell, _comment_text([issue]))
            continue
        # 该格可能已经被行级问题标过（型号+描述同格的版式）：这时整格改字体
        # 不生效，而已有的红/橙又要保住（红色=必须改，不能被提示级洗成黄色）。
        # 做法是认回旧 run 再叠加，并继续把型号行排除在外——文件级问题针对
        # 整单/整行，型号本身没判错。
        if isinstance(cell.value, CellRichText) or key in touched:
            text = _plain(cell.value)
            lines = _line_ranges(text)
            owner = next((it for it in report.doc.items
                          if it.sheet == sheet_name and it.row == row), None)
            skip = _model_line(owner, text, lines) if owner is not None else None
            ranges = _existing_ranges(cell) + [
                (s, e, issue.level, False) for s, e in lines if (s, e) != skip]
            if text:
                _apply_rich(cell, text, ranges, result.warnings)
                if issue.level == LEVEL_RED or touched.get(key) == LEVEL_RED:
                    touched[key] = LEVEL_RED
                else:
                    touched[key] = LEVEL_YELLOW
            _attach_comment(cell, _comment_text([issue]))
            continue
        if key in touched and touched[key] == LEVEL_RED and issue.level != LEVEL_RED:
            _attach_comment(cell, _comment_text([issue]))     # 已红，不降级
            continue
        if not _mark_font(cell, issue.level):
            result.skipped.append("{}：第 {} 行无法标注".format(issue.code, row))
            continue
        touched[key] = issue.level
        _attach_comment(cell, _comment_text([issue]))

    result.issues = len(report.active_issues)

    # ---- 诊断工作表 + 保存 ---------------------------------------------
    diag_title = _append_sheet(wb, report, when)
    # 批阅副本不再写入任何快照标记：比对基线只存在项目快照里
    # （snapshot/<项目>.md 的「三、出单记录」），客户文件不承载内部数据。
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, annotate_filename(src, when))
    try:
        wb.save(target)
    except PermissionError as exc:
        raise AuditExportError(
            "无法写入批阅副本：{} 可能正在 Excel 中打开，请关闭后重试".format(
                os.path.basename(target))) from exc
    except OSError as exc:
        raise AuditExportError("写入批阅副本失败：{}".format(exc)) from exc

    # ---- 保真自检 ------------------------------------------------------
    try:
        saved = load_workbook(target, data_only=False, keep_vba=(ext == ".xlsm"))
        after = _fidelity(saved, exclude=(diag_title,))
        if diag_title not in saved.sheetnames:
            result.warnings.append("诊断工作表没写进副本（{}）".format(diag_title))
        saved.close()
        # 诊断 sheet 是纯文本，不应带来合并/公式，自检不受它影响
        result.warnings.extend(_check_fidelity(before, after))
        if ext == ".xlsm" and _has_vba(src) and not _has_vba(target):
            result.warnings.append("宏丢失：原文件的 VBA 工程没有保留下来——请勿直接使用该副本")
        result.fidelity = {"before": before, "after": after}
    except Exception as exc:
        result.warnings.append("批阅副本已生成，但无法完成保真自检（{}）".format(exc))

    result.path = target
    return result


def annotate_workbook(report: Report, out_dir: str,
                      when: Optional[datetime] = None) -> Optional[str]:
    """兼容入口：只返回路径（告警用 warnings 模块抛出，GUI 请用 _ex 版本）"""
    import warnings as _warnings

    result = annotate_workbook_ex(report, out_dir, when)
    for message in result.warnings:
        _warnings.warn(message)
    return result.path or None
