"""D 段算术校验，按用户拍板的两层实现：

  a 层（check_formulas / L18·L19·L20）：检查 Excel 公式本身——
        L18 公式作用域/引用错位（红）：
          1) 汇总行 =SUM(金额列 x:y) 的范围漏了它语义上应覆盖的明细行
          2) 明细行总价公式引用的行号不是本行（拖拽/复制错位）
        L19 公式形态不一致（红）：同一金额列里主流公式形态是 A，
          个别行却是 B（如整齐的 =SUM(...) 里混进 =SUM(...)+123 藏系数）。
          签名归一（行号数字化为占位符）后比对；主流不足 2 行证据不足，不硬判。
        L20 公式形态未识别（黄，跳过说明）：带系数、跨表、区间混算等
          不把握的形态，按用户要求**不静默跳过**——逐形态（去重收敛）产出
          黄色提示，说明因形态未识别而跳过了公式校验，数值核算仍然有效。

  b 层（check / check_summary / L16·L17）：有价格才做独立数值核算——
      总价 = 数量×单价；小计 = 区间明细之和；设备合计 = 明细之和；
      合计/总价 = 明细之和 + 费用行（服务费/运费）。报价单合计行常直接
      引用汇总表，先核本表、对不上再核其他表的明细池。
      没有价格（单价空/零、送审稿）不猜不报。

两条铁律不变：
  只在证据齐全时校验——任何一端解析不出就跳过，绝不拿半截证据报问题；
  容差只吸收「按分舍入」的累计误差，不吸收真实算错。
"""
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from COPA.apps.audit.reader import parse_amount
from COPA.apps.audit.model import QtyTotalRow, QuoteDoc, SummaryRow

# 单价舍入到分：每件最多差 0.005；总价再舍一次 0.005
_ROW_TOL_PER_UNIT = 0.005
_ROW_TOL_BASE = 0.005
# 汇总加和：每条明细最多贡献 0.005 的舍入差
_SUM_TOL_BASE = 0.011


def _sum_opt(values: Iterable[Optional[float]]) -> float:
    """加总可空金额：解析不出的项按 0 计。

    调用点上的集合都已按「金额可解析」筛过一遍（见 ``items`` / ``fees``
    的构造），这里只是把 Optional 收窄，不会真的把半截证据算进去。
    """

    return sum(value for value in values if value is not None)

_RE_SUM = re.compile(
    r"^=\s*SUM\(\s*(\$?)([A-Za-z]{1,3})(\$?)(\d+)\s*:\s*(\$?)([A-Za-z]{1,3})(\$?)(\d+)\s*\)\s*$",
    re.IGNORECASE)
_RE_REF = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)")


def item_amounts(item) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """明细行 -> (qty, price, total)，任一端不是纯数字返回 None"""
    return (parse_amount(item.qty), parse_amount(item.price),
            parse_amount(item.total))


def check(item, catalog, rules):
    """b 层行核算（L16）：总价 ≠ 数量 × 单价（红）。有价格才核算。"""
    issues = []
    qty, price, total = item_amounts(item)
    if qty is None or price is None or total is None or qty <= 0:
        return issues
    if price == 0:
        return issues                          # 没有价格（送审稿/占位），不猜
    expected = qty * price
    tol = _ROW_TOL_PER_UNIT * qty + _ROW_TOL_BASE
    if abs(total - expected) <= tol:
        return issues
    fmt = lambda n: "{:g}".format(round(n, 4))
    anchor = item.cells.get("total") or (item.row, 1)
    issues.append(rules.issue(
        "L16",
        message="总价 {} 与 数量 {} × 单价 {} = {} 不符".format(
            fmt(total), fmt(qty), fmt(price), fmt(expected)),
        expected="{} × {} = {}".format(fmt(qty), fmt(price), fmt(expected)),
        actual=fmt(total), anchor=anchor))
    return issues


def _segment_totals(doc: QuoteDoc, sheet: str) -> List[Tuple["SummaryRow", Optional["QtyTotalRow"]]]:
    """段金额链：小计（单套价）→ 套数合计（小计 × 套数）= 该段整段价。

    报价单的金额是分层的，明细行金额只是**单套**用量×单价：
        明细 ══ 小计 ══×套数══ 套数合计 ══Σ══ 设备合计
    少了中间那层，拿「明细之和」比设备合计会整整差一个套数倍率
    （枧洋单 5 套：97,930 vs 489,650，误报 2 条 L17）。

    返回 [(小计行, 该段套数合计行或 None)]，按行序；每段以「下一个小计」为界。
    """
    subs = [s for s in doc.summaries
            if s.sheet == sheet and s.kind == "subtotal" and s.amount is not None]
    qts = [q for q in doc.qty_totals if q.sheet == sheet and q.amount is not None]
    subs.sort(key=lambda s: s.row)
    qts.sort(key=lambda q: q.row)

    out = []
    for index, sub in enumerate(subs):
        nxt = subs[index + 1].row if index + 1 < len(subs) else 10 ** 9
        between = [q for q in qts if sub.row < q.row < nxt]
        out.append((sub, between[-1] if between else None))
    return out


def check_summary(doc: QuoteDoc, rules) -> List:
    """b 层汇总核算（L17）：汇总行与明细金额之和不符（红，文件级）。

    口径（枧洋单教训后的语义版）：
      subtotal（小计）    = 自上一条汇总行以来的区间明细之和（+区间内费用行）
      equipment（设备合计）= 明细金额之和（不含费用行）。先核本表，对不上再核
                            其他表的明细池——报价单的设备合计常直接引用汇总表
      grand（合计/总价/价税合计/Grand Total）= 明细金额之和 + 费用行
                            （合计=设备合计+服务费 是常态语义，用户拍板）；
                            同样先本表后他表
      amount 解析不出、全库没有任何可加金额 -> 跳过，不报。
    """
    issues = []
    formulas = _formula_map(doc.path) if doc.path else {}
    sheet_items: Dict[str, List[float]] = {}     # 各表可加的明细金额池
    sheet_fees: Dict[str, List[float]] = {}      # 各表费用行金额池
    for it in doc.items:
        v = parse_amount(it.total)
        if v is not None:
            sheet_items.setdefault(it.sheet, []).append(v)
    for s in doc.summaries:
        if s.kind == "fee" and s.amount is not None:
            sheet_fees.setdefault(s.sheet, []).append(s.amount)
    if not any(sheet_items.values()):
        return issues                            # 全库没有可加金额，不猜

    for sheet in {s.sheet for s in doc.summaries}:
        sheet_formulas = formulas.get(sheet, {})
        items = [it for it in doc.items if it.sheet == sheet
                 and parse_amount(it.total) is not None]
        fees = [s for s in doc.summaries if s.sheet == sheet and s.kind == "fee"
                and s.amount is not None]
        checks = [s for s in doc.summaries if s.sheet == sheet and s.kind != "fee"]
        checks.sort(key=lambda s: s.row)
        prev_row = 0
        fmt = lambda n: "{:,.2f}".format(round(n, 2))

        # 本表金额层级：有「小计/套数合计」就按段累加，没有才退回明细池。
        # 两者不能并列当候选——否则设备合计错写成「明细之和」也会被放过。
        segments = _segment_totals(doc, sheet)
        seg_sum = 0.0
        for sub, qty_total in segments:
            sub_amount = sub.amount
            if sub_amount is None:              # 小计金额解析不出：本段不参与加总
                continue
            if qty_total is None:
                seg_sum += sub_amount           # 本段没展开套数
                continue
            qty_amount = qty_total.amount
            if qty_amount is None:              # 套数合计金额缺失：按未展开处理
                seg_sum += sub_amount
                continue
            seg_sum += qty_amount
            seg_tol = _SUM_TOL_BASE + _ROW_TOL_PER_UNIT * 2
            qty = parse_amount(qty_total.qty)
            looks_single = abs(qty_amount - sub_amount) <= seg_tol
            if qty and abs(qty_amount - sub_amount * qty) > seg_tol \
                    and not looks_single:
                issues.append(rules.issue(
                    "L17",
                    message="小计 × 套数 ≠ 套数合计：小计 {} × {} 套 = {}，行内写 {}".format(
                        fmt(sub_amount), fmt(qty),
                        fmt(sub_amount * qty), fmt(qty_amount)),
                    expected="{} × {} = {}".format(
                        fmt(sub_amount), fmt(qty), fmt(sub_amount * qty)),
                    actual=fmt(qty_amount),
                    anchor=(qty_total.row, qty_total.amount_col or 1)))

        for summary in checks:
            if summary.amount is None:
                continue

            # ---- 小计：区间明细之和（+区间费用行）；公式形态没把握不硬算 --
            if summary.kind == "subtotal":
                f = sheet_formulas.get((summary.row, summary.amount_col or 0))
                if f and _sum_span(f) is None:
                    prev_row = summary.row
                    continue
                bucket = [it for it in items if prev_row < it.row < summary.row]
                bucket_fees = [x for x in fees if prev_row < x.row < summary.row]
                prev_row = summary.row
                if not bucket and not bucket_fees:
                    continue
                expected = (_sum_opt(parse_amount(it.total) for it in bucket)
                            + _sum_opt(x.amount for x in bucket_fees))
                tol = _SUM_TOL_BASE + _ROW_TOL_PER_UNIT * len(bucket)
                if abs(summary.amount - expected) <= tol:
                    continue
                issues.append(rules.issue(
                    "L17",
                    message="{}（小计）与区间明细金额之和不符：应为 {}，行内写 {}".format(
                        summary.label_short, fmt(expected), fmt(summary.amount)),
                    expected="明细合计 {}".format(fmt(expected)),
                    actual=fmt(summary.amount),
                    anchor=(summary.row, summary.amount_col or 1)))
                continue

            # ---- 设备合计 / 合计：Σ段价（有段）或 Σ明细（无段）；grand 再加费用行 ----
            # 先核本表，对不上再核其他表的池（跨表引用：报价单!总价 = 汇总!明细+服务费）
            add_fees = summary.kind == "grand"
            fee_sum = _sum_opt(x.amount for x in fees) if add_fees else 0.0
            local_sum = seg_sum if segments else _sum_opt(
                parse_amount(it.total) for it in items)
            candidates = [local_sum + fee_sum]
            for other, amounts in sheet_items.items():
                if other == sheet:
                    continue
                other_fee = (sum(sheet_fees.get(other, [])) if add_fees else 0.0)
                candidates.append(sum(amounts) + other_fee)
            prev_row = summary.row
            tol = _SUM_TOL_BASE + _ROW_TOL_PER_UNIT * max(
                len(items), max(len(v) for v in sheet_items.values()))
            if any(abs(summary.amount - c) <= tol for c in candidates):
                continue
            if segments:
                base_desc = ("各段金额之和（小计×套数，含费用行）" if add_fees
                             else "各段金额之和（小计×套数）")
            else:
                base_desc = "明细金额之和（含费用行）" if add_fees else "明细金额之和"
            issues.append(rules.issue(
                "L17",
                message="{}与{}不符：明细合计 {}，行内写 {}".format(
                    summary.label_short, base_desc,
                    fmt(candidates[0]), fmt(summary.amount)),
                expected="{} {}".format(base_desc, fmt(candidates[0])),
                actual=fmt(summary.amount),
                anchor=(summary.row, summary.amount_col or 1)))
    return issues


# ---------------------------------------------------------------------------
# a 层：公式校验（L18 作用域/错位 + L19 形态一致性 + L20 跳过说明）
# ---------------------------------------------------------------------------

def _formula_map(path: str) -> Dict[str, Dict[Tuple[int, int], str]]:
    """workbook -> {sheet: {(row, col): 公式原文}}。只关心公式格。"""
    out: Dict[str, Dict[Tuple[int, int], str]] = {}
    try:
        wb = load_workbook(path, data_only=False)
    except Exception:
        return out
    for ws in wb.worksheets:
        cells: Dict[Tuple[int, int], str] = {}
        for row in ws.iter_rows():
            for cell in row:
                row_index, col_index = cell.row, cell.column
                if row_index is None or col_index is None:
                    continue
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cells[(row_index, col_index)] = cell.value
        if cells:
            out[ws.title] = cells
    return out


def _sum_span(formula: str) -> Optional[Tuple[int, int, int]]:
    """纯 =SUM(G3:G5) -> (col, first_row, last_row)；其余形态返回 None"""
    m = _RE_SUM.match(formula.strip())
    if not m:
        return None
    col = column_index_from_string(m.group(2).upper())
    if col != column_index_from_string(m.group(6).upper()):
        return None
    first, last = int(m.group(4)), int(m.group(8))
    return col, min(first, last), max(first, last)


_RE_SUMIF = re.compile(
    r"SUMIF\(\s*\$?([A-Z]{1,2})\$?(\d+)\s*:\s*\$?([A-Z]{1,2})\$?(\d+)\s*,"
    r"\s*\"[^\"]*\"\s*,\s*\$?([A-Z]{1,2})\$?(\d+)\s*:\s*\$?([A-Z]{1,2})\$?(\d+)\s*\)",
    re.I)
_RE_PAIR = re.compile(r"^=\$?([A-Z]{1,2})\$?(\d+)\s*\+\s*\$?([A-Z]{1,2})\$?(\d+)$", re.I)
# 汇总行「小计 × 套数」：=G17*E18（设备合计/套数合计的常见写法）。
# 这也是标准形态，不能当「未识别」报 L20。
_RE_MUL = re.compile(
    r"^=\$?([A-Z]{1,3})\$?(\d+)\s*\*\s*\$?([A-Z]{1,3})\$?(\d+)$", re.I)


def _summary_times_qty(formula: str, summary, summaries, qty_col: int):
    """公式是不是「某个汇总行金额 × 本行数量」。

    命中返回 (因子列, 因子行)，供调用方跳过 L20；不是这个形态返回 None。

    为什么单独认：设备合计写成 =G17*E18（上一行小计 × 本行套数）在报价单里
    很常见，业务上也对。以前落到 else 分支，被描述成「复合形态（明细+费用/
    跨表引用）」——文案与事实相反，用户会以为公式错了。
    """

    if not qty_col:
        return None
    match = _RE_MUL.match(str(formula or "").replace(" ", ""))
    if not match:
        return None
    col_a, row_a = match.group(1).upper(), int(match.group(2))
    col_b, row_b = match.group(3).upper(), int(match.group(4))
    rows = {s.row for s in summaries}
    for factor_col, factor_row, other_col, other_row in (
            (col_a, row_a, col_b, row_b), (col_b, row_b, col_a, row_a)):
        if other_row != summary.row:
            continue
        if column_index_from_string(other_col) != qty_col:
            continue
        if factor_row not in rows:
            continue
        return factor_col, factor_row
    return None


def _sumif_span(formula: str):
    """SUMIF(条件区,"标签",求和区) -> (条件列, 求和列, 起始行, 结束行)。

    套数合计/设备合计这类行就是用它把各段的「套数合计」行加起来的，
    形态固定，完全可以校验区间——以前一律当「复合公式」跳过是漏检
    （珠海锐进就是从 12 行加到 75 行，漏一行也没人知道）。
    """
    match = _RE_SUMIF.search(str(formula or "").replace(" ", ""))
    if not match:
        return None
    cond_col = column_index_from_string(match.group(1).upper())
    sum_col = column_index_from_string(match.group(5).upper())
    first = min(int(match.group(2)), int(match.group(6)))
    last = max(int(match.group(4)), int(match.group(8)))
    return cond_col, sum_col, first, last


def _pair_rows(formula: str):
    """=F75+F76 -> (75, 76)；不是「两项相加」返回 None。"""
    match = _RE_PAIR.match(str(formula or "").replace(" ", ""))
    if not match:
        return None
    return int(match.group(2)), int(match.group(4))


def _signature(formula: str) -> str:
    """公式形态签名：去掉 $/空白、行号与常量数字化为 {r}，再比结构。

    =E3*F3            -> =E{R}*F{R}
    =SUM(E3:E6)       -> =SUM(E{R}:E{R})
    =SUM(E3:E6)+123   -> =SUM(E{R}:E{R})+{R}   （藏了加项，形态不同，L19 可抓）
    =ROUND(E3*F3,2)   -> =ROUND(E{R}*F{R},{R})
    """
    s = re.sub(r"\s+", "", str(formula or "")).upper().replace("$", "")
    return re.sub(r"\d+", "{R}", s)


class _Notice:
    """L20 收集器：按 (sheet, col, 签名) 归并同类跳过，一个形态一条提示。"""

    def __init__(self):
        self.groups: Dict[Tuple[str, int, str], dict] = {}

    def add(self, sheet: str, row: int, col: int, formula: str, why: str):
        key = (sheet, col, _signature(formula))
        g = self.groups.setdefault(key, {
            "rows": [], "col": col, "sheet": sheet,
            "sample": formula, "why": why})
        g["rows"].append(row)

    def issues(self, rules) -> List:
        out = []
        for g in self.groups.values():
            rows = g["rows"]
            shown = "、".join(str(r) for r in rows[:3])
            if len(rows) > 3:
                shown += " 等 {} 处".format(len(rows))
            out.append(rules.issue(
                "L20",
                message="第 {} 行公式 {} {}，因形态未识别已跳过公式校验（金额仍按数值独立核算）".format(
                    shown, g["sample"], g["why"]),
                expected="公式形态可识别并完成作用域校验",
                actual="跳过公式校验：" + g["why"],
                anchor=(rows[0], g["col"] or 1)))
        return out


def _consistency(entries: List[Tuple[int, str]], col: int, rules, label: str):
    """同列同组公式的形态一致性（L19）。

    返回 (issues, main_signature)。主流形态 >= 2 行且存在少数派 -> 报；
    公式互相都不同（没有基准）-> 返回 main=None，由调用方记 L20。
    """
    sigs: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for row, f in entries:
        sigs[_signature(f)].append((row, f))
    if len(sigs) < 2:
        main = next(iter(sigs.values())) if sigs else []
        return [], (main[0][1] if main else None)
    main_sig, main_list = max(sigs.items(), key=lambda kv: len(kv[1]))
    if len(main_list) < 2:
        return [], None                        # 没有主流，不硬判
    issues = []
    for sig, lst in sigs.items():
        if sig == main_sig:
            continue
        rows_text = "、".join("第 {} 行".format(r) for r, _ in lst[:3])
        if len(lst) > 3:
            rows_text += " 等 {} 处".format(len(lst))
        issues.append(rules.issue(
            "L19",
            message="{}公式形态与主流不一致：{} 写的是 {}，主流是 {}".format(
                label, rows_text, lst[0][1], main_list[0][1]),
            expected="与主流形态一致（{}）".format(main_list[0][1]),
            actual=lst[0][1],
            anchor=(lst[0][0], col)))
    return issues, main_list[0][1]


def check_formulas(doc: QuoteDoc, rules) -> List:
    """a 层：公式作用域（L18）+ 形态一致性（L19）+ 跳过说明（L20），文件级。

    L18：汇总 SUM 漏行 / 明细公式行号错位。
    L19：同列公式形态不一致（少数派藏系数/换写法）。
    L20：所有因形态没把握而跳过校验的位置，逐形态去重后给出黄色说明——
         不静默（用户要求），数值核算（b 层）对这些行仍然有效。
    """
    issues: List = []
    if not doc.path:
        return issues
    formulas = _formula_map(doc.path)
    if not formulas:
        return issues

    for sheet, cells in formulas.items():
        cols = doc.columns.get(sheet, {})
        qty_col = cols.get("qty", 0)
        price_col = cols.get("price", 0)
        total_col = cols.get("total", 0)
        items = [it for it in doc.items if it.sheet == sheet]
        summaries = [s for s in doc.summaries if s.sheet == sheet]
        notices = _Notice()
        item_rows = sorted(it.row for it in items)

        # ---- 明细行：L19 一致性 + L18 错位 --------------------------------
        if total_col:
            entries = [(r, cells[(r, total_col)]) for r in item_rows
                       if (r, total_col) in cells]
            if entries:
                l19, main_sig = _consistency(
                    entries, total_col, rules, "总价列")
                issues.extend(l19)
                for item in items:
                    formula = cells.get((item.row, total_col))
                    if not formula:
                        continue
                    if _sum_span(formula) is not None:
                        notices.add(sheet, item.row, total_col, formula,
                                    "明细行使用区间求和公式")
                        continue
                    refs = [(column_index_from_string(c.upper()), int(r))
                            for c, r in _RE_REF.findall(formula)]
                    if not refs:
                        notices.add(sheet, item.row, total_col, formula,
                                    "不含单元格引用")
                        continue
                    if any(r != item.row for _, r in refs):
                        issues.append(rules.issue(          # 行号错位：离群必错
                            "L18",
                            message="第 {} 行总价公式 {} 引用错位".format(
                                item.row, formula),
                            expected="引用本行数量列与单价列",
                            actual=formula,
                            anchor=(item.row, total_col)))
                        continue
                    wrong_cols = {c for c, _ in refs} - {qty_col, price_col}
                    if wrong_cols:
                        if main_sig and _signature(formula) == main_sig:
                            # 整列统一形态但列对不上：疑似表头列识别偏差，不硬判
                            notices.add(sheet, item.row, total_col, formula,
                                        "引用列与识别出的数量/单价列不符")
                        else:
                            issues.append(rules.issue(
                                "L18",
                                message="第 {} 行总价公式 {} 引用错位".format(
                                    item.row, formula),
                                expected="引用本行数量列与单价列",
                                actual=formula,
                                anchor=(item.row, total_col)))

        # ---- 汇总行：只做 L18 SUM 作用域，不做 L19 一致性 -----------------
        # 汇总行角色各不相同（小计=SUM、套价=SUM×套数、服务费=数量×单价），
        # 形态本来就该不同，放一组比「一致性」全是噪音（枧洋单教训）。
        last_row = 0
        for summary in sorted(summaries, key=lambda s: s.row):
            if summary.kind == "fee":
                continue
            formula = None
            for col_try in filter(None, (summary.amount_col, total_col)):
                formula = cells.get((summary.row, col_try))
                if formula:
                    break
            if not formula:
                last_row = summary.row
                continue
            span = _sum_span(formula)
            if span is None:
                sumif = _sumif_span(formula)
                if sumif is not None:
                    cond_col, sum_col, first, last = sumif
                    target = [it.row for it in items if it.row < summary.row]
                    low = min(target) if target else first
                    if first > low or last < summary.row - 1:
                        issues.append(rules.issue(
                            "L18",
                            message="{}的统计区间 {}~{} 未覆盖全部明细行（第 {}~{} 行）".format(
                                summary.label_short, first, last, low, summary.row - 1),
                            expected="区间从第 {} 行开始、到第 {} 行结束".format(low, summary.row - 1),
                            actual=formula,
                            anchor=(summary.row, summary.amount_col or total_col or 1)))
                    elif total_col and sum_col != total_col:
                        issues.append(rules.issue(
                            "L18",
                            message="{}的 SUMIF 求和列与金额列不一致".format(summary.label_short),
                            expected="对第 {} 列求和".format(total_col),
                            actual=formula,
                            anchor=(summary.row, summary.amount_col or total_col)))
                    last_row = summary.row
                    continue            # SUMIF 形态已校验，不再当「未识别」报 L20

                pair = _pair_rows(formula)
                if pair is not None:
                    equipment = {s.row for s in summaries
                                 if s.kind in ("equipment", "qty_total")}
                    if equipment & set(pair):
                        last_row = summary.row
                        continue        # 设备合计 + 服务费用，形态正确
                    issues.append(rules.issue(
                        "L18",
                        message="{}的公式 {} 不是「设备合计 + 服务费用」".format(
                            summary.label_short, formula),
                        expected="引用设备合计行与服务费用行相加",
                        actual=formula,
                        anchor=(summary.row, summary.amount_col or total_col or 1)))
                    last_row = summary.row
                    continue

                scaled = _summary_times_qty(formula, summary, summaries, qty_col)
                if scaled is not None:
                    last_row = summary.row
                    continue        # 小计 × 套数：形态正确，数值由 L17 核算

                why = ("非纯区间求和（含附加项或系数）" if summary.kind == "subtotal"
                       else "为复合形态（明细+费用/跨表引用）")
                notices.add(sheet, summary.row, summary.amount_col or total_col,
                            formula, why)
                last_row = summary.row
                continue                # 非纯 SUM 形态（带系数/多区间），不猜
            col, first, last = span
            if summary.amount_col and col not in (summary.amount_col, total_col or 0):
                notices.add(sheet, summary.row, summary.amount_col or col,
                            formula, "求和列与金额列不一致")
                last_row = summary.row
                continue                # 求和列不是金额列，语义不明，不猜
            if summary.kind == "subtotal":
                scope = [it for it in items if last_row < it.row < summary.row]
            else:
                scope = items
            missed = [it for it in scope
                      if it.cells.get("total")
                      and not (first <= it.cells["total"][0] <= last)]
            last_row = summary.row
            if missed:
                rows_text = "{}~{}".format(missed[0].row, missed[-1].row) \
                    if len(missed) > 1 else str(missed[0].row)
                issues.append(rules.issue(
                    "L18",
                    message="{}的公式 {} 漏了第 {} 行的金额".format(
                        summary.label_short, formula, rows_text),
                    expected="求和覆盖第 {} 行".format(rows_text),
                    actual=formula,
                    anchor=(summary.row, summary.amount_col or total_col or 1)))

        # ---- L20：跳过说明（逐形态去重后追加）------------------------------
        issues.extend(notices.issues(rules))
    return issues
