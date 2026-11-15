"""描述正文 -> 带字符区间的字段树（唯一解析入口）.

为什么要有这一层：同一段描述现在被 claims / descdiff / header / consistency /
existence / power 各跑一遍正则（checks 里 41 个 re.compile，一份描述至少解析
5–6 次），而**字符位置**只有标注层需要、却拿不到，于是 annotate 只能靠
「问题码 -> 标签表 + 在原文里反查 token」猜该红哪一段。猜不准就是整格染红，
业务看不出到底哪行写错了。

这里把描述摊成一颗树，每个叶子都带绝对字符区间：

    DescDoc
      ├─ clauses[0]  「1.材质：碳钢」        value_span=(5, 9)
      ├─ clauses[1]  「2.台面规格：1200*1200mm」
      └─ ...

只做**结构**（分段 / 序号 / 字段名），不做**语义**（哪个字段是量程、材质怎么规整
成碳钢/不锈钢）。语义在 claims.py，因为那边才有通表口径。分开的好处是加一个
字段不用碰这里，改一次分段规则也不用碰那边。

切分口径按真实单据的写法定：
  · 一级按 `；;\\n` 切（`，,` 不切——「材质：碳钢，花纹钢台面」是一个字段的一句话）；
  · 二级在段内按 `，,` 再切，但只在**看起来像新字段**时才认（「量程：1000kg，
    分度值e=d=0.5kg」里后半截是另一个字段，「碳钢，花纹钢台面」不是）；
  · 序号 `1.` / `1、` / `1）` 剥掉但记住，因为它决定「这是第几条」；
  · 没有冒号的一律当**裸值**（模块第一行的型号串、单独一句「带水平拉杆」）。

md 是这颗树的**一个视图**（to_markdown），不是它的存储——摊平成表格会丢掉
序号语义和字符位置，等于把标注要用的东西扔了再想办法捡回来。
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

__all__ = ["Span", "Clause", "DescDoc", "CellMap", "parse"]


@dataclass(frozen=True)
class Span:
    """原文中的字符区间 [start, end)，左闭右开，可直接切片."""
    start: int
    end: int

    def __post_init__(self):
        if self.start < 0 or self.end < self.start:
            raise ValueError("非法区间 {}..{}".format(self.start, self.end))

    def __len__(self) -> int:
        return self.end - self.start

    def text(self, src: str) -> str:
        return src[self.start:self.end]

    def as_tuple(self) -> Tuple[int, int]:
        return (self.start, self.end)


# 一级分隔：分号、句号与换行。中文逗号**不**切（见模块 docstring）。
# 句号算一级：条目抬头是「…共8套。仪表，Profibus-DP通信，DC24V。防爆环境。」，
# 不切就整段糊成一坨，抬头校验拿不到「仪表/供电/防爆」三段。
_RE_HARD = re.compile(r"[；;。\n]")
# 二级分隔：逗号
_RE_SOFT = re.compile(r"[，,]")
# 序号前缀：1.  1、  1)  1）  一、
_RE_NO = re.compile(r"^\s*((?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*[.、)）])\s*")
# 字段名：冒号前不超过 14 字且不含逗号（「分度值e=d=」这类靠冒号前的内容判）
_RE_KV = re.compile(r"^([^：:，,]{1,14}?)\s*[：:]\s*(.*)$", re.DOTALL)
# 「分度值e=d=0.5kg」：等号型字段，没有冒号也认
_RE_KV_EQ = re.compile(r"^([^：:，,=]{1,14}?)\s*=\s*(.+)$", re.DOTALL)
# 二级切分后，长得像字段名（用于判断逗号后面是不是新字段）。
# 中文不写 \b —— Python 的 \w 含汉字，「量程」后面紧跟「分度值」时没有词边界，
# 加了 \b 反而永远匹配不上（这是第一版切不开的原因）。
_RE_FIELDISH = re.compile(
    r"^(?:量程|台面(?:尺寸|规格)?|材质|分度值|精度(?:等级)?|传感器|仪表|供电|电源"
    r"|防爆(?:等级)?|防护(?:等级)?|通讯|接口|外壳|安装|支架|电池|品牌|型号|规格"
    # 条目抬头那一套（L35–L38）：抬头与描述是同一种文本，用同一套切分才能
    # 拿到「料重：6t」里 6t 的区间——以前 header.py 另开四个正则，
    # 只能算出数值算不出位置。
    r"|料重|总重|皮重|设备自重|自重|标定量程|设备位号|设备名称|显示(?:分度值)?"
    r"|共\s*\d+\s*套|\d+\s*支点|(?:DC|AC)\s*\d+|\d{3}\s*V"
    r"|Profibus|ProfiNet|Modbus|RS\s*-?\s*(?:232|485)|以太网"
    r"|(?:Capacity|Platform|Material|Division|Sensor|Indicator|Power|Battery)(?![A-Za-z]))",
    re.IGNORECASE)

# 无冒号的字段：抬头里常写「总重8t，标定量程6t」，描述里也常见「量程 1000kg」。
# 只认下面这张名单，且字段名后面必须真跟着东西——放开成「两字词+任意值」会把
# 「碳钢，花纹钢台面」这类整句切成假字段。
_BARE_NAMES = (r"设备自重|自重|标定量程|料重|总重|皮重|量程"
               r"|台面尺寸|台面规格|台面|分度值|防爆等级|防护等级|精度等级|供电|电源")
_RE_KV_BARE = re.compile(r"^(" + _BARE_NAMES + r")\s*[:：]?\s*(.+)$", re.DOTALL)


@dataclass
class Clause:
    """描述里的一个「字段段」，带原文区间.

    name 为空表示裸值（型号串 / 一句独立说明），此时 value 即整段。
    """
    name: str                       # 字段名（「材质」），可为空
    value: str                      # 值原文（未规整）
    span: Span                      # value 在整段描述中的区间
    line: int                       # 第几行（0-based）
    no: str = ""                    # 序号原文（「1.」），继承自所在段
    segment: int = -1               # 所属一级段（分号/换行分隔）
    raw: str = ""                   # 整段原文（含字段名与序号）

    def to_row(self) -> Tuple[str, str, str]:
        return (self.no, self.name, self.value)


@dataclass
class DescDoc:
    """一段描述的字段树。fields 由 claims 填入（语义层），这里只管结构."""
    text: str = ""
    clauses: List[Clause] = field(default_factory=list)
    # 语义字段：key -> (规整值, 原文, Span)；claims 负责填，这里留空也能用
    fields: Dict[str, Tuple[str, str, Span]] = field(default_factory=dict)

    # ---- 结构查询 ---------------------------------------------------------
    def named(self, name: str) -> List[Clause]:
        """按字段名取（大小写与空白不敏感），可能多处出现（传感器材质/模块材质）"""
        key = _squash(name)
        return [c for c in self.clauses if c.name and _squash(c.name) == key]

    def first(self, name: str) -> Optional[Clause]:
        hits = self.named(name)
        return hits[0] if hits else None

    def clause_at(self, pos: int) -> Optional[Clause]:
        """哪个字段段盖住了这个字符位置（标注反查用）"""
        for clause in self.clauses:
            if clause.span.start <= pos < clause.span.end:
                return clause
        return None

    def line_span(self, line: int) -> Optional[Span]:
        """整行区间（含该行所有字段段），用于「这一行都不对」的粗标"""
        starts = [c.span.start for c in self.clauses if c.line == line]
        ends = [c.span.end for c in self.clauses if c.line == line]
        if not starts:
            return None
        return Span(min(starts), max(ends))

    def locate(self, snippet: str) -> Optional[Span]:
        """在原文里找一段字（先用精确匹配，再退回去空白匹配）.

        给「手里只有一个原文串、没有 span」的老调用点兜底；新代码请直接用
        claims 给的区间，别再用它——反查就是当初标注乱标的根源。
        """
        snippet = (snippet or "").strip()
        if not snippet:
            return None
        idx = self.text.find(snippet)
        if idx >= 0:
            return Span(idx, idx + len(snippet))
        # 去空白后匹配：单元格里常有全角空格/换行把词拆开
        squashed, index = "", []
        for i, ch in enumerate(self.text):
            if not ch.isspace():
                squashed += ch
                index.append(i)
        target = _squash(snippet)
        pos = squashed.find(target)
        if pos < 0:
            return None
        return Span(index[pos], index[pos + len(target) - 1] + 1)

    def spans_of(self, *names: str) -> List[Span]:
        out: List[Span] = []
        for name in names:
            out.extend(c.span for c in self.named(name))
        return out

    # ---- 视图 -------------------------------------------------------------
    def to_markdown(self, only_named: bool = False) -> str:
        """渲染成 md 表格（给人看/给 LLM 看），不作为存储."""
        rows = [c for c in self.clauses if (c.name or not only_named)]
        if not rows:
            return "（空描述）"
        out = ["| 行 | 序号 | 字段 | 值 |", "|---|---|---|---|"]
        for c in rows:
            out.append("| {} | {} | {} | {} |".format(
                c.line + 1, c.no.rstrip(".") or "", _esc(c.name), _esc(c.value)))
        return "\n".join(out)

    def field_rows(self) -> List[Tuple[str, str]]:
        """(字段名, 值) 二元组列表，便于表格化比对"""
        return [(c.name, c.value) for c in self.clauses if c.name]

    def __iter__(self) -> Iterator[Clause]:
        return iter(self.clauses)

    def __len__(self) -> int:
        return len(self.clauses)


@dataclass
class CellMap:
    """拼接文本 -> 原单元格坐标的映射.

    为什么需要它：条目抬头是「标题格 + 续行各格」拼出来的（reader 用换行连），
    但 Excel 只能染某一个格。有了偏移表，描述层算出的区间才能换算回
    (行, 列, 格内区间)——否则抬头问题只能退回「哪格有这个词就染哪格」，
    一个格子里写了料重又写了总重时就分不清是哪个数错了。

    pieces 按拼接顺序给 (行, 列, 原文)；原文在拼接文本里找不到（空白被改过）
    的那一格跳过，不猜位置。
    """

    text: str = ""
    cells: List[Tuple[int, int, str, int]] = field(default_factory=list)

    @classmethod
    def build(cls, pieces, text: Optional[str] = None,
              delimiter: str = "\n") -> "CellMap":
        """pieces 按拼接顺序给 (行, 列, 原文).

        text 给了就以它为准（在它里面顺序找每一格的位置），没给就自己拼。
        以它为准的原因：reader 拼接时可能改写空白（strip/换行），自己拼出来的
        文本会与真正的 header_text 差几个字符，区间就整体错位。
        """
        if text is None:
            text = delimiter.join(str(p[2] or "") for p in pieces if p[2])
        cells: List[Tuple[int, int, str, int]] = []
        pos = 0
        for row, col, raw in pieces:
            raw = str(raw or "")
            if not raw:
                continue
            at = text.find(raw, pos)
            if at < 0:
                continue                 # 拼接时被改写过：位置不可信，宁可不标
            cells.append((row, col, raw, at))
            pos = at + len(raw)
        return cls(text=text, cells=cells)

    def cell_at(self, pos: int):
        """这个字符位置落在哪一格 -> (row, col, 格内偏移, 该格原文) 或 None"""
        for row, col, text, offset in self.cells:
            if offset <= pos < offset + len(text):
                return row, col, pos - offset, text
        return None

    def locate(self, span):
        """区间 -> (row, col, (格内起, 格内止))；跨格时截到起点那一格.

        抬头里一个字段的值不会跨格（「料重：6t」写在同一格），真跨了说明
        拼接边界切在值中间，这时只标半截也胜过标错格。
        """
        if not span:
            return None
        hit = self.cell_at(span.start)
        if hit is None:
            return None
        row, col, local, text = hit
        end = min(local + len(span), len(text))
        if end <= local:
            return None
        return row, col, (local, end)

    def __len__(self) -> int:
        return len(self.cells)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _esc(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _hard_segments(text: str) -> List[Tuple[int, int, int]]:
    """按 `；;\\n` 切一级段，返回 (start, end, line_no)."""
    out: List[Tuple[int, int, int]] = []
    line = 0
    start = 0
    for m in _RE_HARD.finditer(text):
        out.append((start, m.start(), line))
        if m.group() == "\n":
            line += 1
        start = m.end()
    out.append((start, len(text), line))
    return out


def _soft_split(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    """段内按逗号再切，但只在逗号后确实起了个新字段时才切."""
    bounds = [(start, end)]
    for m in _RE_SOFT.finditer(text, start, end):
        _, right = bounds[-1]
        tail = text[m.end():right].lstrip()
        if tail and _RE_FIELDISH.match(tail):
            bounds[-1] = (bounds[-1][0], m.start())
            bounds.append((m.end(), right))
    return bounds


def _strip(text: str, start: int, end: int) -> Tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def parse(text: str) -> DescDoc:
    """描述 -> DescDoc。不做语义判断，只切结构."""
    src = text or ""
    doc = DescDoc(text=src)
    for seg_start, seg_end, line in _hard_segments(src):
        # 序号属于整段：同一段内的多个逗号子句共用它
        s0, e0 = _strip(src, seg_start, seg_end)
        no = ""
        if s0 < e0:
            m = _RE_NO.match(src[s0:e0])
            if m:
                # 序号只留数字：「1.」「1、」「1）」都是同一件事，标点归格式
                no = m.group(1).rstrip(".、)）").strip()
                s0 = _strip(src, s0 + m.end(), e0)[0]
        seg_index = len({c.segment for c in doc.clauses}) if doc.clauses else 0
        for a, b in _soft_split(src, s0, e0):
            a, b = _strip(src, a, b)
            if a >= b:
                continue
            raw = src[a:b]
            name, value_span = "", Span(a, b)
            m = _RE_KV.match(raw)
            if m and m.group(1).strip():
                vs = a + m.start(2)
                ve = a + m.end(2)
                vs, ve = _strip(src, vs, ve)
                if ve > vs:
                    name, value_span = m.group(1).strip(), Span(vs, ve)
            else:
                m = _RE_KV_EQ.match(raw)
                # 等号型只在左半边像字段名时才认（避免把 1200*1200 当字段）
                if m and _RE_FIELDISH.match(m.group(1).strip()):
                    name = m.group(1).strip()
                    vs, ve = _strip(src, a + m.start(2), a + m.end(2))
                    # 「分度值e=d=0.5kg」：等号前那个 e 属于表达式不属于字段名，
                    # 把值区间左边界拉回 e 所在位置，字段名去掉这个字母
                    if re.search(r"[A-Za-z]$", name):
                        name = name[:-1].strip()
                        vs = a + m.end(1) - 1
                        vs, ve = _strip(src, vs, ve)
                    if ve > vs:
                        name, value_span = name, Span(vs, ve)
            if not name:
                # 兜底：无冒号无等号但有字段名（「总重8t」「量程 1000kg」）
                m = _RE_KV_BARE.match(raw)
                if m:
                    vs, ve = _strip(src, a + m.start(2), a + m.end(2))
                    if ve > vs:
                        name, value_span = m.group(1).strip(), Span(vs, ve)
            doc.clauses.append(Clause(
                name=name, value=value_span.text(src), span=value_span,
                line=line, no=no, segment=seg_index, raw=raw))
    return doc
