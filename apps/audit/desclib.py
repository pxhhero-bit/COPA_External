"""描述正文的参数抽取（量程 / 台面 / 分度值 / 材质 / 防爆）.

单独成模块的原因：L3-L7 与 L9 都要从同一段自然语言里取参数。抽两套正则的
后果是「一致性检查说 60kg、命名建议按 6kg 算」这种自相矛盾的输出。

抽取只认模板里真实存在的写法（中文 1.材质：… / 2.台面规格：… 与英文
1.Material: … / 2.Platform: …），取不到就是 None，交给调用方决定是「跳过」
还是「判缺项」，不在这里猜。

材质不直接比字符串：中文写「全304不锈钢」、英文写 carbon steel、型号段写 C/S，
三者要能对上，所以统一收敛成「碳钢 / 不锈钢」两个语义值。
"""
import re
from typing import List, Optional

RE_CAP = re.compile(r"(?:量程|capacity)[^0-9\n]{0,8}([\d.]+)\s*(kg|t|吨)", re.IGNORECASE)
RE_FACE = re.compile(
    r"(?:台面(?:尺寸|规格|尺寸规格)?|platform|table\s*size|pan\s*size)"
    r"[^0-9\n]{0,8}(\d{2,5})\s*[*xX×✕]\s*(\d{2,5})", re.IGNORECASE)
RE_DIV = re.compile(r"(?:分度值|e\s*=\s*d\s*=|division)[^0-9\n]{0,8}([\d.]+)\s*(kg|g)",
                    re.IGNORECASE)
RE_NOTE_LINE = re.compile(r"^[ \t]*备注[:：]", re.MULTILINE)
RE_MTL = re.compile(r"(?:材质|material)[:：]\s*([^，,；;\n）)]*)", re.IGNORECASE)
RE_EX = re.compile(r"防爆|Ex\s|explosion\s*proof|[（(]\s*E\s*[）)]", re.IGNORECASE)

# 材质段 -> 中文（与 Writer._MATERIAL_NAMES 同一口径）
MTL_TEXT = {"C": "碳钢", "HC": "碳钢", "S": "不锈钢", "HS": "不锈钢",
            "CS": "混合材质", "HCS": "混合材质"}

_STEEL_WORDS = ("不锈钢", "stainless", "sus304", "sus316", "304", "316")
_CARBON_WORDS = ("碳钢", "carbon", "碳素")


def desc_capacity(desc: str):
    """描述 -> 量程(kg)。'量程：3000kg' / 'Capacity: 3t'"""
    info = desc_capacity_span(desc)
    return info[0] if info else None


def desc_capacity_span(desc: str):
    """描述 -> (量程kg, 起, 止, 原文) 或 None.

    区间只覆盖**值本身**（'1000kg'），不含「量程：」这几个字——标注要红的
    是值，把字段名一起染了会让人以为字段名写错。
    """
    m = RE_CAP.search(desc or "")
    if not m:
        return None
    value = float(m.group(1))
    kg = value * 1000 if m.group(2).lower() in ("t", "吨") else value
    return kg, m.start(1), m.end(2), desc[m.start(1):m.end(2)]


def desc_face(desc: str):
    """描述 -> 台面尺寸 (w, h) mm"""
    info = desc_face_span(desc)
    return (info[0], info[1]) if info else None


def desc_face_span(desc: str):
    """描述 -> (宽, 高, 起, 止, 原文) 或 None"""
    m = RE_FACE.search(desc or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), m.start(1), m.end(2),
            desc[m.start(1):m.end(2)])


def desc_division(desc: str):
    """描述 -> 分度值原文（只判有无，不参与量值校验）"""
    m = RE_DIV.search(desc or "")
    return "{} {}".format(m.group(1), m.group(2)) if m else None


def desc_division_kv(desc: str):
    """描述 -> (数值, 单位) 或 None。L15 单位建议用（kg 建议换算 g）"""
    info = desc_division_span(desc)
    return (info[0], info[1]) if info else None


def desc_division_span(desc: str):
    """描述 -> (数值, 单位, 起, 止, 原文) 或 None"""
    m = RE_DIV.search(desc or "")
    if not m:
        return None
    return (float(m.group(1)), m.group(2).lower(), m.start(1), m.end(2),
            desc[m.start(1):m.end(2)])


def desc_note_lines(desc: str) -> List[str]:
    """描述内以「备注：」开头的行原文列表。
    台秤默认仪表一体安装，描述内不应有备注行（L14 判据）"""
    return [text for text, _, _ in desc_note_line_spans(desc)]


def desc_note_line_spans(desc: str) -> List[tuple]:
    """描述内「备注：」行 -> [(原文, 起, 止)]。L14 要标的是那一整行"""
    out: List[tuple] = []
    text = desc or ""
    for m in RE_NOTE_LINE.finditer(text):
        end = text.find("\n", m.start())
        end = end if end > 0 else len(text)
        raw = text[m.start():end].strip()
        if raw:
            start = text.index(raw, m.start())
            out.append((raw, start, start + len(raw)))
    return out


def desc_material(desc: str) -> str:
    """描述 -> 第一个「材质：」的值。取第一个是因为模板第一行就是秤体材质，
    后面的（传感器材质：）/（台面材质：）不是同一个对象。"""
    info = desc_material_span(desc)
    return info[0] if info else ""


def desc_material_span(desc: str):
    """描述 -> (材质原文, 起, 止) 或 None。区间只盖值，不盖「材质：」"""
    m = RE_MTL.search(desc or "")
    if not m:
        return None
    start, end = m.start(1), m.end(1)
    text = desc or ""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return None
    return text[start:end], start, end



def material_kind(text: str) -> str:
    """材质文本 -> 碳钢 / 不锈钢 / 混合材质 / 空串（判不出来）"""
    value = (text or "").lower()
    if not value:
        return ""
    steel = any(word in value for word in _STEEL_WORDS)
    carbon = any(word in value for word in _CARBON_WORDS)
    if steel and carbon:
        return "混合材质"
    if steel:
        return "不锈钢"
    if carbon:
        return "碳钢"
    return ""


def desc_ex(desc: str) -> bool:
    return RE_EX.search(desc or "") is not None
