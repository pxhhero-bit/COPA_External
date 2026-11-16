"""描述 -> 规整声明集（claim set）。快照比对的两端共用这一套抽取器.

为什么需要这一层：报价单描述与型谱描述是同一件事的两种写法——
  「220VAC无电源线」  vs 「220V / 交流供电」
  「台面尺寸：400*500mm」 vs 「台面 400x500」
直接对文本 diff 会被写法差异淹没。所以两边先折叠成

    键 -> Claim(规整值, 原文片段, 在描述中的位置)

再比键值。这样「有缺」和「对不上」都能干净定位；新增一个字段只要加一条
抽取规则，不必为它写一个检查器、再为检查器对齐一遍话术（这正是本轮要
摆脱的维护方式）。

抽取口径与旧检查器一致的地方故意复用 desclib（量程/台面/分度值/材质/防爆），
保证过渡期两套引擎对同一份描述得到同一个结论。
"""
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from COPA.apps.audit import descfield
from COPA.apps.audit.desclib import (desc_capacity_span, desc_division_span,
                                     desc_ex, desc_face_span)

# ---- 规范键 ---------------------------------------------------------------
K_SENSOR_MTL = "sensor_material"        # 传感器材质（模块行）
K_MODULE_MTL = "module_material"        # 模块附件材质
K_SCALE_MTL = "scale_material"          # 秤体材质（碳钢/不锈钢）
K_CAPACITY = "capacity"
K_FACE = "face"
K_DIVISION = "division"
K_POWER = "power"                       # ac / dc / bat
K_BATTERY = "battery"                   # 电池配置（8.4V锂电池 / 无电池）
K_EX = "explosion"                      # 防爆
K_PULL_ROD = "pull_rod"                 # 水平拉杆
K_BRAND = "brand"
K_HOUSING = "housing"
K_MOUNT = "mount"
K_BRACKET = "bracket"
K_PROTOCOL = "protocol"
K_DISPLAY = "display"
K_LANG = "language"

KEY_NAMES = {
    K_SENSOR_MTL: "传感器材质", K_MODULE_MTL: "模块附件材质",
    K_SCALE_MTL: "秤体材质", K_CAPACITY: "量程", K_FACE: "台面尺寸",
    K_DIVISION: "分度值", K_POWER: "供电方式", K_BATTERY: "电池配置",
    K_EX: "防爆等级", K_PULL_ROD: "水平拉杆", K_BRAND: "品牌",
    K_HOUSING: "外壳", K_MOUNT: "安装方式", K_BRACKET: "支架",
    K_PROTOCOL: "通讯接口", K_DISPLAY: "显示", K_LANG: "语言",
}

# 数值类（量程/台面/分度值）继续由 L3/L4/L15 把关——它们的判据带业务口径
# （分度值单位、台面码换算、建议型号），走快照反而更粗。快照只负责描述性配置。
NUMERIC_KEYS = (K_CAPACITY, K_FACE, K_DIVISION)

# ---- 抽取正则 -------------------------------------------------------------
_RE_SENSOR_MTL = re.compile(r"传感器材质\s*[:：]\s*([^；;，,。\n]+)")
_RE_MODULE_MTL = re.compile(r"模块(?:附件)?材质\s*[:：]\s*([^；;，,。\n]+)")
_RE_SCALE_MTL = re.compile(r"(?<!传感器)(?<!模块)(?<!附件)材质\s*[:：]\s*([^；;，,。\n]+)")
# 配件类的写法是「碳钢材质，表面处理后镀锌」——材质在前，没有冒号
# （描述通表里过渡板两句话就是这么写的）
_RE_MTL_PREFIXED = re.compile(r"^(碳钢|不锈钢|304\s*不锈钢|316\s*不锈钢)\s*材质")
_RE_BATTERY = re.compile(r"(\d+(?:\.\d+)?\s*V\s*锂?电池|锂电池|无电池|干电池)")
def _ex_tokens(text: str) -> Tuple[str, ...]:
    """防爆标记 -> 分类记号。'Ex ia ⅡC T6 Ga' / '二区IICT5' / 'IICT6' 都能解析.

    只保留有排斥力的维度（气体组别 GAS、温度组别 TEMP），其余进 PROOF/EPL
    仅作展示——写法差异（Ex ia vs 本安）不该判冲突。
    """
    t = (text or "").upper()
    t = t.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    t = t.replace("Ｉ", "I").replace("Ⅱ", "II")
    t = re.sub(r"EX\s*[A-Z]{1,2}(?![A-Z])", " ", t)     # 保护型式不参与气体组别
    out = []
    for gas in re.findall(r"II[ABC]|(?<![A-Z])I[ABC](?![A-Z])", t):
        out.append("GAS:" + gas)
    for temp in re.findall(r"T\s*(\d)", t):
        out.append("TEMP:T" + temp)
    for proof in re.findall(r"EX\s*(IA|IB|IC|D|E|N|T)\b", t):
        out.append("PROOF:" + proof)
    for epl in re.findall(r"\b(G[ABC]|D[ABC])\b", t):
        out.append("EPL:" + epl)
    for zone in re.findall(r"([12])\s*区|ZONE\s*([12])", t):
        out.append("ZONE:" + (zone[0] or zone[1]))
    if not out and ("防爆" in (text or "") or "EX" in t):
        out.append("EX")
    return tuple(sorted(set(out)))


def _battery_kind(text: str) -> str:
    """电池声明 -> 'none' / 'has'。'无电池' 与 '8.4V锂电池' 是互斥的两类。"""
    s = text or ""
    if "无电池" in s or "不含电池" in s:
        return "none"
    if re.search(r"电池|BATTERY", s, re.IGNORECASE):
        return "has"
    return ""


_RE_EX_LEVEL = re.compile(r"防爆等级\s*[:：]\s*([^；;，,。\n]+)")
_RE_PULL_ROD = re.compile(r"(?:带)?水平拉杆|拉杆")
_RE_BRAND = re.compile(r"品牌\s*[:：]\s*([A-Za-z\u4e00-\u9fff]+)")
_RE_HOUSING = re.compile(r"((?:不锈钢|塑料|铝合金|铸铝|ABS|碳钢)\s*外壳)", re.IGNORECASE)
_RE_MOUNT = re.compile(r"(面板式|防尘式|导轨式|壁挂式|台式|便携式|立柱式)")
_RE_BRACKET = re.compile(r"(立杆支架|壁挂支架|无支架)")
_RE_PROTOCOL = re.compile(r"(RS\s*232|RS\s*485|RS\s*422|USB|以太网|Ethernet|4[-~]20\s*mA"
                          r"|0[-~]10\s*V|MODBUS[- ]?RTU|MODBUS[- ]?TCP|PROFINET|PROFIBUS"
                          r"|蓝牙|WIFI|WI-FI|CAN)", re.IGNORECASE)
_RE_DISPLAY = re.compile(r"(LCD|LED|彩屏|触摸屏|数码管|无显示|点阵)", re.IGNORECASE)
_RE_LANG = re.compile(r"(中英文|中文|英文|多语言)", re.IGNORECASE)

_RE_AC = re.compile(r"AC\s*\d{3}\s*V?|\d{3}\s*V\s*AC|220\s*V|380\s*V|110\s*V|交流",
                    re.IGNORECASE)
_RE_DC = re.compile(r"DC\s*\d{2,3}\s*V?|\d{2,3}\s*V\s*DC|直流\s*\d{2,3}\s*V?",
                    re.IGNORECASE)
_RE_BAT = re.compile(r"电池供电|内置电池|锂电池|充电电池|干电池|带电池|含电池|电池另配"
                     r"|另配电池|防爆电源|本安电源|battery", re.IGNORECASE)


@dataclass
class Claim:
    key: str
    value: str                    # 规整值（用于比对）
    raw: str = ""                 # 原文片段（报告里给人看）
    pos: int = -1                 # 在描述中的起点，批阅端字符定位用
    tokens: Tuple[str, ...] = ()  # 多值类字段（协议/显示/防爆标记）的集合
    end: int = -1                 # 值在描述中的终点（左闭右开）
    line: int = -1                # 落在描述的第几行（0-based，-1=未知）
    name: str = ""                # 字段名原文（「材质」「分度值」）

    @property
    def span(self) -> Optional[Tuple[int, int]]:
        """(起, 止)。标注要红的就是这一段；None 表示只知值不知位置。"""
        if self.pos < 0 or self.end <= self.pos:
            return None
        return (self.pos, self.end)


def _mk(key, value, raw, pos, tokens=(), end=-1) -> Claim:
    raw = raw.strip()
    if pos >= 0 and end <= pos:
        end = pos + len(raw)      # 兜底：给了起点没给终点，按原文长度推
    return Claim(key=key, value=value, raw=raw, pos=pos, tokens=tokens, end=end)


def _mtl_tokens(text: str) -> Tuple[str, ...]:
    """材质文本 -> 可比较的记号集合。'17-4PH不锈钢' -> {'17-4PH','不锈钢'}"""
    out = []
    low = text.lower()
    if "17-4" in low:
        out.append("17-4PH")
    if "不锈钢" in low or "stainless" in low:
        out.append("不锈钢")
    if "碳钢" in low or "carbon" in low:
        out.append("碳钢")
    if "合金钢" in low:
        out.append("合金钢")
    if "镀镍" in low:
        out.append("镀镍")
    if "镀锌" in low:
        out.append("镀锌")
    if "喷塑" in low:
        out.append("喷塑")
    if "塑料" in low or "abs" in low:
        out.append("塑料")
    if "铝合金" in low or "铸铝" in low:
        out.append("铝合金")
    return tuple(out)


def _supply(text: str) -> Optional[Claim]:
    """供电声明 -> ac / dc / bat。多类同时命中视为含糊（交直流两用），不猜。"""
    hits = []
    for kind, regex in (("bat", _RE_BAT), ("dc", _RE_DC), ("ac", _RE_AC)):
        m = regex.search(text)
        if m:
            hits.append((kind, m))
    if len(hits) != 1:
        return None
    kind, m = hits[0]
    return _mk(K_POWER, kind, m.group(0), m.start())


def extract(text: str, doc: Optional[descfield.DescDoc] = None) -> Dict[str, Claim]:
    """描述 -> {键: Claim}。只抽认得的字段，认不出的原样不碰（不猜）。

    每条 Claim 都带字符区间（pos/end）。区间是**标注层的唯一依据**：
    annotate 以前靠「问题码 -> 标签表 + 在原文里反查 token」猜该红哪一段，
    猜不中就整格染红；现在直接拿区间切片，错一个字都不会标偏。

    doc 可传入已解析好的 DescDoc（一次描述要被多个检查器读时省一次切分）。
    """
    if not text:
        return {}
    doc = doc or descfield.parse(text)
    out: Dict[str, Claim] = {}

    for key, regex, conv in (
        (K_SENSOR_MTL, _RE_SENSOR_MTL, _mtl_tokens),
        (K_MODULE_MTL, _RE_MODULE_MTL, _mtl_tokens),
        (K_SCALE_MTL, _RE_SCALE_MTL, _mtl_tokens),
    ):
        m = regex.search(text)
        if m:
            raw = m.group(1)
            out[key] = _mk(key, raw, raw, m.start(1), conv(raw), end=m.end(1))

    prefixed = _RE_MTL_PREFIXED.search(text.lstrip())
    if prefixed and K_SCALE_MTL not in out:
        offset = len(text) - len(text.lstrip())
        raw = prefixed.group(1)
        out[K_SCALE_MTL] = _mk(K_SCALE_MTL, raw, raw, offset + prefixed.start(1),
                               _mtl_tokens(raw), end=offset + prefixed.end(1))

    # 量程 / 台面：区间只覆盖值（'1000kg' / '1200*1200'），不含字段名
    info = desc_capacity_span(text)
    if info:
        kg, start, end, raw = info
        out[K_CAPACITY] = _mk(K_CAPACITY, str(kg), raw, start, end=end)

    info = desc_face_span(text)
    if info:
        width, height, start, end, raw = info
        out[K_FACE] = _mk(K_FACE, "{:g}x{:g}".format(width, height), raw, start, end=end)

    info = desc_division_span(text)
    if info:
        num, unit, start, end, raw = info
        out[K_DIVISION] = _mk(K_DIVISION, "{}{}".format(num, unit), raw, start, end=end)

    power = _supply(text)
    if power is not None:
        out[K_POWER] = power

    m = _RE_BATTERY.search(text)
    if m:
        out[K_BATTERY] = _mk(K_BATTERY, _battery_kind(m.group(1)) or m.group(1),
                             m.group(1), m.start(1), end=m.end(1))

    # 防爆：等级串优先，其次散落的 Ex 标记或「防爆」二字
    m = _RE_EX_LEVEL.search(text)
    if m:
        raw = m.group(1)
        out[K_EX] = _mk(K_EX, raw, raw, m.start(1), _ex_tokens(raw) or ("EX",),
                        end=m.end(1))
    elif desc_ex(text):
        mm = re.search(r"Ex\s*[a-zA-Z]{1,2}[^；;，,。\n]{0,20}", text) or \
            re.search(r"防爆", text)
        raw = mm.group(0) if mm else "防爆"
        out[K_EX] = _mk(K_EX, raw, raw, mm.start() if mm else -1,
                        _ex_tokens(raw) or ("EX",),
                        end=mm.end() if mm else -1)

    m = _RE_PULL_ROD.search(text)
    if m:
        out[K_PULL_ROD] = _mk(K_PULL_ROD, "1", m.group(0), m.start(), end=m.end())

    m = _RE_BRAND.search(text)
    if m:
        out[K_BRAND] = _mk(K_BRAND, m.group(1).lower(), m.group(1), m.start(1),
                           end=m.end(1))

    for key, regex in ((K_HOUSING, _RE_HOUSING), (K_MOUNT, _RE_MOUNT),
                       (K_BRACKET, _RE_BRACKET), (K_LANG, _RE_LANG)):
        m = regex.search(text)
        if m:
            out[key] = _mk(key, _squash(m.group(1)), m.group(1), m.start(1),
                           end=m.end(1))

    for key, regex in ((K_PROTOCOL, _RE_PROTOCOL), (K_DISPLAY, _RE_DISPLAY)):
        matches = list(regex.finditer(text))
        tokens = tuple(_squash(m.group(0)) for m in matches)
        if tokens:
            first = matches[0]
            # 区间只取第一处命中：协议可能在不同行各写一次，取 min..max 会把
            # 中间整段描述都圈进来，标注就成了「整格标红」的老样子
            out[key] = _mk(key, "|".join(sorted(set(tokens))),
                           "、".join(sorted(set(tokens))), first.start(),
                           tuple(sorted(set(tokens))), end=first.end())

    _fill_from_doc(out, doc)
    return out


def _fill_from_doc(claims: Dict[str, Claim], doc: descfield.DescDoc) -> None:
    """把区间接上字段树：补 line 与字段名（报告里写「材质」比写 key 好读）"""
    for claim in claims.values():
        if claim.pos < 0:
            continue
        clause = doc.clause_at(claim.pos)
        if clause is None:
            continue
        claim.line = clause.line
        claim.name = clause.name or claim.name


def parse_doc(text: str) -> descfield.DescDoc:
    """描述 -> 字段树 + 语义字段（一次解析，结构给标注、语义给校验）.

    这是「统一解析层」的对外入口：需要字段位置的调用方走这里，只需要
    `{键: 值}` 的继续用 extract（它会复用同一套规则，结论一致）。
    """
    doc = descfield.parse(text)
    for key, claim in extract(text, doc).items():
        doc.fields[key] = (claim.value, claim.raw,
                           descfield.Span(claim.pos, claim.end) if claim.span else None)
    return doc


def _squash(text: str) -> str:
    """对齐写法：去空白、统一乘号与大小写"""
    s = re.sub(r"\s+", "", text or "")
    s = s.replace("×", "x").replace("*", "x").replace("X", "x")
    return s.lower()


def _is_ex(claim: Claim) -> bool:
    """是否防爆。等级组别不比——同一型号常并列多套认证，逐字比只会误报。"""
    if claim.value in ("0", "", "非防爆"):
        return False
    return bool(claim.tokens) or bool(claim.value)


def compatible(expected: Claim, got: Claim) -> bool:
    """快照声明 vs 报价声明是否相容（而非逐字相等）。

    宽容口径：型号侧写法更完整（'17-4PH不锈钢' vs '不锈钢'）、协议多写少写
    都能过；只有互相排斥才算冲突——宁可漏判，不制造噪音。
    """
    if expected.key in (K_SENSOR_MTL, K_MODULE_MTL, K_SCALE_MTL):
        a, b = set(expected.tokens), set(got.tokens)
        if not a or not b:
            return _squash(expected.value) in _squash(got.value) or \
                _squash(got.value) in _squash(expected.value)
        return bool(a & b)
    if expected.key == K_POWER:
        return expected.value == got.value
    if expected.key == K_BATTERY:
        return not expected.value or not got.value or expected.value == got.value
    if expected.key == K_HOUSING:
        a, b = set(_mtl_tokens(expected.value)), set(_mtl_tokens(got.value))
        if not a or not b:
            return _squash(expected.value) in _squash(got.value) or \
                _squash(got.value) in _squash(expected.value)
        return bool(a & b)
    if expected.key == K_EX:
        return _is_ex(expected) == _is_ex(got)
    if expected.key in (K_PROTOCOL, K_DISPLAY):
        a, b = set(expected.tokens), set(got.tokens)
        if not a or not b:
            return True
        return bool(a & b)
    a, b = _squash(expected.value), _squash(got.value)
    return a in b or b in a


def describe(claim: Claim) -> str:
    """报告里的「实际写的是」：优先给原文"""
    return claim.raw or claim.value


__all__ = ["Claim", "KEY_NAMES", "NUMERIC_KEYS", "extract", "parse_doc",
           "compatible", "describe",
           "K_BATTERY", "K_BRAND", "K_BRACKET", "K_CAPACITY", "K_DISPLAY",
           "K_DIVISION", "K_EX", "K_FACE", "K_HOUSING", "K_LANG", "K_MODULE_MTL",
           "K_MOUNT", "K_POWER", "K_PROTOCOL", "K_PULL_ROD", "K_SCALE_MTL",
           "K_SENSOR_MTL"]
