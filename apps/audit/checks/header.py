"""L35-L38：项目段「条目抬头」的基线校验.

抬头就是每段开头那一两句规格声明，各家写法不同但内容一致：

    设备位号：WT-R1008，3支点，共1套。设备自重：2t，料重：6t，总重8t，
    标定量程6t，显示分度值 kg。仪表FT210，4-20mA模拟量输出，220VAC。防爆环境。
    设备名称：1T模块，3支点，共8套。仪表，Profibus-DP通信，DC24V。防爆环境。

它是这一段对客户的承诺，下面每一行都得跟它对得上。抬头自己写错了，
逐行看型号是看不出来的（行内自洽，整段错），所以要单独拿抬头当基线：

  L35 红 标定量程站不住：低于料重（称不满）/ 等于总重（把皮重算进量程）
  L36 黄 标定量程偏大：超过料重 1.5 倍，分度值被白白放大
  L37 红 总重 ≠ 料重 + 皮重
  L38 红 抬头声明的通讯 / 供电 / 防爆，下方描述对不上

标定量程的口径与 engine 同源（config/selection_rules.json 的
`metrology_rules.rated_range_rule`：`must_ge_W1` + `upper_limit_ratio`），
所以这里只做区间判断，不重算一个具体数字去比——engine 的取整网格会随
料重跳档，硬比数字会把正常报价报成错。

只校验含称重模块的项目段：台秤/平台秤单没有这套「料重-皮重-标定量程」
语义，套过来只会误报。
"""
import re
from typing import Dict, List, Optional, Tuple

from COPA.apps.audit import claims as C
from COPA.apps.audit import descfield
from COPA.apps.audit.checks.consistency import model_ex
from COPA.apps.audit.descfield import Span
from COPA.apps.audit.model import (KIND_INSTRUMENT, KIND_JBOX, KIND_MODULE,
                                  SPAN_CELL)

# 与 selection_rules.json 的 rated_range_rule 同源：标定量程 ≥ 料重，且 ≤ 1.5×料重
RATED_UPPER_RATIO = 1.5
# 重量比对的容差：报价单按 t 写、保留 1~2 位小数，10kg 以内视为相等
_TOL_KG = 10.0

# 抬头字段名 -> 校验用键。重量的取数交给字段树（descfield），这里只做归一：
# 以前是四条正则各扫一遍，只能算出数值算不出位置，抬头问题只能整格染红。
_WEIGHT_NAMES = {
    "料重": "料重",
    "皮重": "皮重", "设备自重": "皮重", "自重": "皮重",
    "总重": "总重",
    "标定量程": "标定",
}
# 值里允许出现的写法：「6t」「15吨」「8000kg」「1.5 t」。
# 用 match 不用 search ——「设备自重及料合共总重3t」这种句子里，皮重的值不是
# 「3t」，3t 是总重的数；只认值开头就是数字才不会把总重读成皮重。
_RE_NUM_UNIT = re.compile(r"^\s*(?:约|大约|为)?\s*([\d.]+)\s*(kg|t|吨|g)(?![a-zA-Z])",
                          re.I)


# 抬头里能点名的通讯接口。DP 只在「DP通讯/DP通信」时认——「DP」单独出现
# 太容易是型号片段（FAB3306HX1DP00D）。
_COMM_DEFS = (
    ("Profibus-DP", re.compile(r"profibus[-\s]?dp|profi[-\s]?bus|(?<![a-z])dp\s*(?:通讯|通信)",
                               re.I)),
    ("ProfiNet", re.compile(r"profinet|profi[-\s]?net", re.I)),
    ("4-20mA", re.compile(r"4\s*[-~～—]\s*20\s*ma|模拟量输出", re.I)),
    ("RS485", re.compile(r"rs\s*[-]?\s*485", re.I)),
    ("RS232", re.compile(r"rs\s*[-]?\s*232", re.I)),
    ("Modbus", re.compile(r"modbus", re.I)),
    ("以太网", re.compile(r"ethernet|以太网", re.I)),
)

_RE_PWR_DC = re.compile(r"dc\s*\d{2,3}|\d{2,3}\s*v\s*dc|直流\s*\d{2,3}", re.I)
_RE_PWR_AC = re.compile(r"ac\s*\d{3}|\d{3}\s*v\s*ac|\d{3}\s*v(?![a-z])|交流", re.I)

_RE_EX_NO = re.compile(r"非防爆")
_RE_EX_YES = re.compile(r"防爆环境|防爆区域|防爆场所|爆炸性环境")
_RE_EX_DESC = re.compile(r"隔爆|防爆|ex\s*(?:d|ia|ib|t)\b", re.I)


def _kg(number: str, unit: str) -> float:
    value = float(number)
    unit = (unit or "").lower()
    if unit in ("t", "吨"):
        return value * 1000.0
    if unit == "g":
        return value / 1000.0
    return value


def header_map(block) -> descfield.CellMap:
    """抬头 -> 拼接文本 + 每格偏移表（区间换算回单元格的唯一依据）"""
    pieces = [(row, col, text) for row, col, text in (block.header_cells or [])]
    if not pieces:
        pieces = [(block.row, 1, block.header_text or block.title or "")]
    return descfield.CellMap.build(pieces, text=block.header_text or block.title or "")


def weight_fields(doc: descfield.DescDoc) -> Dict[str, Tuple[float, Span]]:
    """抬头字段树 -> {料重/皮重/总重/标定: (kg, 值区间)}。没写的字段不出现。

    值区间只盖数值+单位（「6t」），不含「标定量程」这几个字——要红的永远是
    填错的那个数。
    """
    out: Dict[str, Tuple[float, Span]] = {}
    for clause in doc.clauses:
        key = _WEIGHT_NAMES.get(clause.name)
        if not key or key in out:
            continue                    # 同名字段取第一处：抬头先说先算
        match = _RE_NUM_UNIT.match(clause.value)
        if not match:
            continue
        span = Span(clause.span.start + match.start(1),
                    clause.span.start + match.end(2))
        out[key] = (_kg(match.group(1), match.group(2)), span)
    return out


def parse_header(text: str) -> Dict[str, float]:
    """抬头文本 -> {料重/皮重/总重/标定: kg}（只给数值，不带位置）。

    保留这个签名是因为它被单测与外部工具当纯函数用；要位置的走 weight_fields。
    """
    doc = descfield.parse(text or "")
    return {key: kg for key, (kg, _) in weight_fields(doc).items()}



def _close(a: float, b: float) -> bool:
    return abs(a - b) <= _TOL_KG


def _fmt(value: float) -> str:
    """kg -> 人看的口径（整数吨写 6t，带小数写 2.5t）"""
    tons = value / 1000.0
    text = ("%g" % round(tons, 3))
    return "{}t".format(text)


def check_doc(doc, catalog, rules) -> List:
    """整单跑一遍，返回文件级问题（抬头在段上，不在某一行上）"""
    issues: List = []
    for block in doc.blocks:
        items = [it for it in doc.items
                 if it.sheet == block.sheet and it.block == block.key]
        if not any(it.kind == KIND_MODULE for it in items):
            continue
        cmap = header_map(block)
        head = weight_fields(descfield.parse(cmap.text))
        if not head:
            continue
        issues.extend(_rated_range(block, cmap, head, rules))
        issues.extend(_total_weight(block, cmap, head, rules))
        issues.extend(_declared_vs_items(block, head, items, catalog, rules))
    return issues


def _where(block) -> str:
    return "第 {} 段（第 {} 行）".format(block.key or "-", block.row)


def _place(block, cmap, span):
    """值区间 -> (锚点格, 格内区间)。换算不出来就退回标题格、整格标."""
    hit = cmap.locate(span) if span else None
    if hit is None:
        return block.anchor, None
    row, col, local = hit
    return (row, col), local


def _rated_range(block, cmap, head, rules) -> List:
    """L35/L36：标定量程 vs 料重"""
    rated, load, total = head.get("标定"), head.get("料重"), head.get("总重")
    if rated is None or load is None or load[0] <= 0:
        # 只有总重（建泰那种「设备与物料总重12t，标定量程15t」）：没有料重可比，
        # 按用户口径整项跳过，不拿总重顶替
        return []
    rated_kg, rated_span = rated
    load_kg = load[0]
    total_kg = total[0] if total else None
    anchor, cell_span = _place(block, cmap, rated_span)
    sheet = block.sheet

    if rated_kg < load_kg - _TOL_KG:
        return [rules.issue(
            "L35",
            message="{}抬头标定量程 {}，低于料重 {}：满料就超量程".format(
                _where(block), _fmt(rated_kg), _fmt(load_kg)),
            expected="标定量程 ≥ 料重 {}（engine 口径）".format(_fmt(load_kg)),
            actual="{}（料重 {}）".format(_fmt(rated_kg), _fmt(load_kg)),
            anchor=anchor, sheet=sheet, span=cell_span, field="标定量程",
            span_scope=SPAN_CELL)]

    if (total_kg is not None and not _close(load_kg, total_kg)
            and _close(rated_kg, total_kg)):
        return [rules.issue(
            "L35",
            message="{}抬头标定量程 {} 与总重相同（料重 {} + 皮重 {}）："
                    "皮重会被算进量程，分度值白白放大".format(
                        _where(block), _fmt(rated_kg), _fmt(load_kg),
                        _fmt(total_kg - load_kg)),
            expected="按料重定标定量程 {}".format(_fmt(load_kg)),
            actual="{}（= 总重 {}）".format(_fmt(rated_kg), _fmt(total_kg)),
            anchor=anchor, sheet=sheet, span=cell_span, field="标定量程",
            span_scope=SPAN_CELL)]

    if rated_kg > load_kg * RATED_UPPER_RATIO + _TOL_KG:
        return [rules.issue(
            "L36",
            message="{}抬头标定量程 {}，超出上限（料重 {} × {} = {}）".format(
                _where(block), _fmt(rated_kg), _fmt(load_kg), RATED_UPPER_RATIO,
                _fmt(load_kg * RATED_UPPER_RATIO)),
            expected="{} ~ {}（料重 ~ 1.5 倍料重）".format(
                _fmt(load_kg), _fmt(load_kg * RATED_UPPER_RATIO)),
            actual=_fmt(rated_kg),
            anchor=anchor, sheet=sheet, span=cell_span, field="标定量程",
            span_scope=SPAN_CELL)]
    return []


def _total_weight(block, cmap, head, rules) -> List:
    """L37：总重 = 料重 + 皮重（三个都写了才判，缺一个就是没依据）"""
    load, tare, total = head.get("料重"), head.get("皮重"), head.get("总重")
    if load is None or tare is None or total is None:
        return []
    if _close(load[0] + tare[0], total[0]):
        return []
    anchor, cell_span = _place(block, cmap, total[1])
    return [rules.issue(
        "L37",
        message="{}抬头总重 {} ≠ 料重 {} + 皮重 {} = {}".format(
            _where(block), _fmt(total[0]), _fmt(load[0]), _fmt(tare[0]),
            _fmt(load[0] + tare[0])),
        expected=_fmt(load[0] + tare[0]),
        actual=_fmt(total[0]),
        anchor=anchor, sheet=block.sheet, span=cell_span, field="总重",
        span_scope=SPAN_CELL)]


def _comm_features(text: str) -> List[str]:
    return [name for name, regex in _COMM_DEFS if regex.search(text or "")]


def _power_kind(text: str) -> Optional[str]:
    """'ac' / 'dc' / None。同时写了交直流就返回 None（含糊，不判）"""
    ac = bool(_RE_PWR_AC.search(text or ""))
    dc = bool(_RE_PWR_DC.search(text or ""))
    if ac == dc:
        return None
    return "ac" if ac else "dc"


def _item_ex(item, catalog):
    """明细行的防爆位：模块读型号尾段，仪表/接线盒读描述（型号码不统一）"""
    if item.kind == KIND_MODULE:
        info = None
        try:
            info = catalog.codes.decode(item.model)
        except Exception:                    # noqa: BLE001 解不了码不影响读尾段
            info = None
        return model_ex(item, info, catalog)
    if item.kind in (KIND_INSTRUMENT, KIND_JBOX):
        if not item.desc:
            return None
        return bool(_RE_EX_DESC.search(item.desc))
    return None


def _declared_vs_items(block, head, items, catalog, rules) -> List:
    """L38：抬头声明的通讯/供电/防爆，下方描述必须兑现（抬头是基线）"""
    text = block.header_text or block.title
    issues: List = []
    anchor = block.anchor
    sheet = block.sheet

    comm = _comm_features(text)
    power = _power_kind(text)
    if comm or power:
        controllers = [it for it in items if it.kind == KIND_INSTRUMENT and it.desc]
        for item in controllers:
            missing = [name for name in comm if name not in _comm_features(item.desc)]
            if missing:
                issues.append(rules.issue(
                    "L38",
                    message="{}抬头写「{}」，但第 {} 行仪表描述没有此项".format(
                        _where(block), "、".join(missing), item.row),
                    expected="描述中注明 {}".format("、".join(missing)),
                    actual="描述未见该接口",
                    anchor=item.cells.get("desc") or item.cells.get("model"),
                    sheet=sheet))
            if power and _power_kind(item.desc) not in (None, power):
                claim = C.extract(item.desc).get(C.K_POWER)
                issues.append(rules.issue(
                    "L38",
                    message="{}抬头写 {} 供电，第 {} 行仪表描述写的是 {} 供电".format(
                        _where(block),
                        "交流" if power == "ac" else "直流",
                        item.row,
                        "交流" if _power_kind(item.desc) == "ac" else "直流"),
                    expected="{}供电（按抬头）".format("交流" if power == "ac" else "直流"),
                    actual=claim.raw if claim else item.desc[-40:],
                    anchor=item.cells.get("desc") or item.cells.get("model"),
                    sheet=sheet, span=claim.span if claim else None,
                    field="供电方式"))

    if _RE_EX_NO.search(text):
        want_ex = False
    elif _RE_EX_YES.search(text):
        want_ex = True
    else:
        want_ex = None

    if want_ex is not None:
        for item in items:
            if item.kind not in (KIND_MODULE, KIND_INSTRUMENT, KIND_JBOX):
                continue                     # 电缆/过渡板没有防爆位，别硬判
            got = _item_ex(item, catalog)
            if got is None or got == want_ex:
                continue
            issues.append(rules.issue(
                "L38",
                message="{}抬头写「{}」，第 {} 行{}却是{}".format(
                    _where(block), "防爆环境" if want_ex else "非防爆环境",
                    item.row, item.label,
                    "防爆型" if got else "非防爆型"),
                expected="{}（按抬头）".format("防爆型" if want_ex else "非防爆型"),
                actual="{}（{}）".format("防爆型" if got else "非防爆型", item.model or "-"),
                anchor=item.cells.get("model") or anchor,
                sheet=sheet))

    return issues
