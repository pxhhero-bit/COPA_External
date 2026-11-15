"""audit 数据模型：版式无关的报价单结构与问题条目.

设计的核心是把「读出来的东西」和「判出来的东西」分开：
  QuoteDoc  只描述文件里有什么（行、段、型号、描述原文、单元格坐标）
  Issue     只描述哪一条不成立（码、级别、期望值 vs 实际值、建议、定位）

这样检查器是纯函数（QuoteDoc -> [Issue]），导出/染色只消费 Issue.anchor，
新增一个检查项不需要碰读取层，改版式也不需要碰检查器。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re

# ---- 问题级别 -------------------------------------------------------------
LEVEL_RED = "red"
LEVEL_YELLOW = "yellow"

LEVEL_NAMES = {LEVEL_RED: "严重", LEVEL_YELLOW: "提示"}

# ---- 字符区间的参照系 -----------------------------------------------------
# Issue.span 是「原文里的哪几个字」，但「原文」有两个可能的起点：
#   desc：明细行的描述字段。单元格里常常还有型号行，标注时要先找 desc 的落点；
#   cell：锚点单元格本身。抬头是跨格拼出来的，descfield.CellMap 已经把区间
#         换算到某一格了，再平移一次就标到隔壁字上。
# 以前靠「这个码属于哪一类」隐式决定，加了抬头校验后两种混在一起，必须写明。
SPAN_DESC = "desc"
SPAN_CELL = "cell"


# ---- 行类型 ---------------------------------------------------------------
ROW_DETAIL = "detail"              # 明细行
ROW_BLOCK = "block"                # 项目段标题（一/二/三 或 A/B/C）
ROW_SUMMARY = "summary"            # 小计/合计/总价/价税合计
ROW_UNRECOGNIZED = "unrecognized"  # 有内容但归不了类（必须显式报告）

# ---- 品类 -----------------------------------------------------------------
KIND_BENCH = "bench"            # 电子台秤
KIND_PLATFORM = "platform"      # 电子平台秤
KIND_MODULE = "module"          # 称重模块
KIND_TRUCK = "truck"            # 汽车衡
KIND_JBOX = "jbox"              # 接线盒
KIND_INSTRUMENT = "instrument"  # 称重仪表/控制器
KIND_SENSOR = "sensor"          # 传感器
KIND_CABLE = "cable"            # 电缆
KIND_ACCESSORY = "accessory"    # 其他附件（过渡板/立柱等）
KIND_UNKNOWN = "unknown"

KIND_NAMES = {
    KIND_BENCH: "电子台秤",
    KIND_PLATFORM: "电子平台秤",
    KIND_MODULE: "称重模块",
    KIND_TRUCK: "汽车衡",
    KIND_JBOX: "接线盒",
    KIND_INSTRUMENT: "称重仪表",
    KIND_SENSOR: "称重传感器",
    KIND_CABLE: "电缆",
    KIND_ACCESSORY: "附件",
    KIND_UNKNOWN: "未识别",
}

# 需要做「量程/台面/材质/分度值」这四项一致性校验的品类（秤体）
SCALE_KINDS = (KIND_BENCH, KIND_PLATFORM, KIND_TRUCK)

# 型号存在性检查豁免的品类：电缆/附件型号命名自由度高，逐条查库只会制造噪音
EXISTENCE_EXEMPT = (KIND_CABLE, KIND_ACCESSORY)


@dataclass
class Issue:
    """一条问题。expected/actual 必须有值——没有证据就不该标红。"""
    code: str
    level: str
    title: str
    message: str = ""                      # 一句话说明（人话）
    advice: str = ""                       # 建议动作
    expected: str = ""                     # 期望值（库里的/规则要求的）
    actual: str = ""                       # 实际值（单据里写的）
    missing: str = ""                      # L7 专用：缺失的参数名
    anchor: Optional[Tuple[int, int]] = None   # (row, col) 1-based，染色定位用
    mark: str = ""                         # 标注提示：fill_yellow=整格填黄（空缺位无字可标）
    sheet: str = ""                        # 文件级问题用：锚点所在工作表（行号跨表会重）
    ignored: bool = False                  # 本次会话内忽略（沿用 Diagnostic 语义）
    span: Optional[Tuple[int, int]] = None  # 字符区间（起, 止），字符级标红用
    span_scope: str = SPAN_DESC              # 区间相对谁：item.desc / 锚点格本身
    field: str = ""                        # 出问题的字段名（「材质」「量程」），报告用

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, self.level)

    def to_dict(self) -> dict:
        return {
            "code": self.code, "level": self.level, "title": self.title,
            "message": self.message, "advice": self.advice,
            "expected": self.expected, "actual": self.actual,
            "missing": self.missing, "anchor": self.anchor,
            "mark": self.mark, "sheet": self.sheet, "ignored": self.ignored,
            "span": list(self.span) if self.span else None, "field": self.field,
            "span_scope": self.span_scope,
        }


@dataclass
class LineItem:
    """一条明细行。字段名与报价单列语义对齐，不跟任何模板绑定。"""
    sheet: str
    row: int
    seq: str = ""                       # 序号原文
    block: str = ""                     # 所属项目段（一/二/A…）
    name: str = ""                      # 名称列原文
    model_text: str = ""                # 型号（或型号+描述合并列）原文
    model: str = ""                     # 抽取出的型号（模块取系列名）
    model_detail: str = ""              # 模块的详细型号串（系列+材质码+传感器）
    kind: str = KIND_UNKNOWN            # 品类
    hit_level: str = "none"             # 型号命中方式：exact/normalized/typebatch/desc/none
    qty: str = ""
    unit: str = ""
    price: str = ""
    total: str = ""
    desc: str = ""                      # 描述原文（合并列时为整格文本）
    remark: str = ""
    cells: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # 字段 -> 单元格
    issues: List[Issue] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.model or "第{}行".format(self.row)

    def cell_text(self, field: str) -> str:
        """某字段所在单元格的原文。字段与单元格的对应只有这四种，其余不是整格文本"""
        return {"model": self.model_text, "name": self.name,
                "desc": self.desc, "remark": self.remark}.get(field, "")

    def locate_model(self):
        """型号实际写在哪个格、哪几个字 -> ((行, 列), (起, 止)) 或 None.

        型号的来源与它的落点常常不是同一个格：合并版式里「型号」被映射到名称格，
        而真正那一串写在描述格第一行。照着 cells["model"] 去标，红色会落在
        「电子台秤」上——人名不对，改的人也找不到该改哪个字。
        """
        code = (self.model or "").strip()
        if not code:
            return None
        first = None
        for field in ("model", "name", "desc"):
            anchor = self.cells.get(field)
            if not anchor:
                continue
            if first is None:
                first = (anchor, None)
            at = self.cell_text(field).find(code)
            if at < 0:
                # 型号常被规整过（SS 7.5T -> SS 7.5t），逐字找不到就忽略大小写
                match = re.search(re.escape(code), self.cell_text(field), re.IGNORECASE)
                at = match.start() if match else -1
            if at >= 0:
                return anchor, (at, at + len(code))
        return first

    def model_span(self):
        """型号在锚点格里的字符区间（锚点格不是型号格时返回 None）"""
        found = self.locate_model()
        if not found:
            return None
        anchor, span = found
        return span if anchor == self.cells.get("model") else None

    @property
    def active_issues(self) -> List[Issue]:
        return [i for i in self.issues if not i.ignored]

    @property
    def level(self) -> str:
        """行级最高级别：红优先，无问题返回空串"""
        levels = {i.level for i in self.active_issues}
        if LEVEL_RED in levels:
            return LEVEL_RED
        if LEVEL_YELLOW in levels:
            return LEVEL_YELLOW
        return ""


@dataclass
class Block:
    """项目段（多项目报价单里的一/二/三）。单项目单只有一段，key 为空。

    header_text 是「条目抬头」全文：段标题那一格 + 紧跟其后的续行（各家写法
    不同，阿根廷把「3支点，共1套。料重…」单独写一行，样例客户则全塞在标题格里）。
    抬头是这一段的规格声明，L35–L38 拿它当基线，所以原文要完整留着。
    """
    key: str
    title: str
    row: int
    sheet: str = ""
    items: List[LineItem] = field(default_factory=list)
    header_text: str = ""
    # 抬头各格：(行, 列, 原文)。抬头可能跨行（标题行 + 续行），染色要落到
    # 真正写着这个字段的那一格，落在标题上会让人找不到数字在哪
    header_cells: List[Tuple[int, int, str]] = field(default_factory=list)

    @property
    def anchor(self) -> Optional[Tuple[int, int]]:
        if self.header_cells:
            return (self.header_cells[0][0], self.header_cells[0][1])
        return (self.row, 1)


@dataclass
class UnrecognizedRow:
    """有内容但归不了类的行。绝不静默丢弃——这是防「假通过」的底线。"""
    sheet: str
    row: int
    text: str
    reason: str


@dataclass
class SummaryRow:
    """汇总行（小计/合计/总价/价税合计）与费用行（运费/服务费）。

    D 段算术校验的数据来源：amount 解析失败（None）就跳过校验——
    没有证据不报问题。fee 行参与所在区间的金额加和。
    """
    sheet: str
    row: int
    label: str                       # 名称列原文
    kind: str = "grand"              # subtotal / grand / fee
    amount: Optional[float] = None   # 解析出的金额
    amount_col: int = 0              # 金额所在列（1-based，标注定位）
    block: str = ""                  # 归属项目段

    @property
    def label_short(self) -> str:
        text = (self.label or "").splitlines()[0] if self.label else ""
        return text[:20] or self.kind


@dataclass
class QtyTotalRow:
    """数量类合计行（套数合计 / 件数合计 / 台数合计…）.

    它不进「行金额」核对（那一列常常是套数），但它是两条链的关键一环：
      1) 数量链：它是「这一单到底做多少套」的唯一声明——明细行数量是**每套
         用量**，总用量 = 套数 × 单套用量；
      2) 金额链：它的金额列就是「小计 × 套数」的整段价，设备合计 = Σ 段价。
         少了这一层，拿「明细之和」去比设备合计会差出一整个套数倍率
         （样例客户单实测差 5 倍）。
    """
    sheet: str
    row: int
    label: str                       # 名称列原文
    qty: str                         # 数量列原文（套数）
    qty_col: int = 0                 # 数量所在列（1-based，标注定位）
    block: str = ""                  # 归属项目段
    amount: Optional[float] = None   # 金额列（小计×套数），可能为空
    amount_col: int = 0              # 金额所在列（标注定位）


@dataclass
class QuoteDoc:
    path: str
    sheets: List[str] = field(default_factory=list)
    items: List[LineItem] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    summaries: List[SummaryRow] = field(default_factory=list)
    qty_totals: List[QtyTotalRow] = field(default_factory=list)
    unrecognized: List[UnrecognizedRow] = field(default_factory=list)
    header_rows: Dict[str, int] = field(default_factory=dict)
    columns: Dict[str, Dict[str, int]] = field(default_factory=dict)  # sheet -> 字段->列号
    meta: Dict[str, str] = field(default_factory=dict)   # 客户/日期/语言等抬头信息
    project_no: str = ""                    # 报价项目号（COPA{YYMMDD}-{4位}，见 pno.py）
    notes: List[str] = field(default_factory=list)  # 基线/来源说明（不参与判定，只提示）
    file_issues: List[Issue] = field(default_factory=list)  # 文件级问题（表头未识别等）
    # 批阅过程中的联动标记：不是单据数据，不参与快照与构造参数。
    # 显式声明在这里，runner 才能直写而不是靠 setattr 挂临时属性。
    _l10_done: bool = field(default=False, init=False, repr=False, compare=False)
    suspect_template: bool = field(default=False, init=False, repr=False, compare=False)
    _copa_state: Optional[Any] = field(default=None, init=False, repr=False, compare=False)

    @property
    def issues(self) -> List[Issue]:
        out = list(self.file_issues)
        for item in self.items:
            out.extend(item.issues)
        return out

    def sheet_of(self, row) -> str:
        """文件级问题的行号 -> 工作表（未识别行/汇总行/数量合计行都能查）"""
        try:
            row = int(row)
        except (TypeError, ValueError):
            return self.sheets[0] if self.sheets else ""
        for group in (self.unrecognized, self.summaries, self.qty_totals):
            for record in group:
                if record.row == row:
                    return record.sheet
        return self.sheets[0] if self.sheets else ""


@dataclass
class Report:
    doc: QuoteDoc
    rules_version: str = "1.0"

    @property
    def issues(self) -> List[Issue]:
        return self.doc.issues

    @property
    def active_issues(self) -> List[Issue]:
        return [i for i in self.issues if not i.ignored]

    def count(self, level: str) -> int:
        return sum(1 for i in self.active_issues if i.level == level)

    @property
    def item_counts(self) -> Dict[str, int]:
        """行级统计：红行/黄行/干净行（一行多个问题只记最高级）"""
        red = sum(1 for it in self.doc.items if it.level == LEVEL_RED)
        yellow = sum(1 for it in self.doc.items if it.level == LEVEL_YELLOW)
        clean = sum(1 for it in self.doc.items if not it.level)
        return {LEVEL_RED: red, LEVEL_YELLOW: yellow, "clean": clean}

    @property
    def passed(self) -> bool:
        return not self.active_issues
