"""报价单读取：xlsx/xlsm -> QuoteDoc（版式无关）.

三层解耦，各层都能单独测：
  定位表头  _find_header   按「序号/名称/型号/数量/单价/总价」命中数打分
  列映射    _build_columns 同义词表，中英文都认，合并列表头会展开
  行归类    _classify      明细 / 项目段 / 小计合计 / 未识别

原则：**宁可不认，也不硬塞**。归不了类的行进 doc.unrecognized 并出 L10，
不允许静默跳过——报价单少读一行，批阅就成了假通过。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

from COPA.apps.audit.model import (KIND_ACCESSORY, KIND_BENCH, KIND_CABLE,
                                   KIND_INSTRUMENT, KIND_JBOX, KIND_MODULE,
                                   KIND_PLATFORM, KIND_SENSOR, KIND_TRUCK,
                                   KIND_UNKNOWN, LineItem,
                                   QuoteDoc, QtyTotalRow, SummaryRow,
                                   UnrecognizedRow)
from COPA.apps.audit.naming import in_parens, norm, tokenize_models

# ---------------------------------------------------------------------------
# 表头识别
# ---------------------------------------------------------------------------
# 同义词按「包含」匹配；括号内容先剥掉（单价(元) -> 单价 / Unit Price (USD) -> unitprice）
_HEADER_RULES = {
    "seq": ("序号", "编号", "项次", "no", "no.", "itemno", "s/n"),
    "name": ("名称", "品名", "货物名称", "item", "goods"),
    "model": ("型号", "model", "规格", "spec"),
    "desc": ("描述", "description", "说明"),
    "unit": ("单位", "unit"),
    "qty": ("数量", "qty", "quantity"),
    "price": ("单价", "unitprice", "price"),
    "total": ("总价", "合计", "金额", "totalprice", "amount", "total"),
    "remark": ("备注", "remark", "note"),
}

_REQUIRED_FIELDS = ("qty",)          # 有数量列才算报价明细表
_ANCHOR_FIELDS = ("name", "model")   # 且必须有名称或型号

# 归不了类时的终止词：这些行之后是条款/备注区，不再当明细解析
_STOP_WORDS = ("备注", "说明", "报价说明", "注意事项", "附注", "条款", "注：", "注:",
               "terms", "condition", "remark", "note")

# 汇总行关键词（含在名称/序号列即判定，不做数值解析）
_SUMMARY_WORDS = ("小计", "合计", "总价", "服务费", "运费", "大写金额", "价税合计",
                  "grandtotal", "subtotal", "total")

# 小计类：校验「自上一条汇总以来的明细之和」
_SUBTOTAL_WORDS = ("小计", "subtotal")
# 数量类合计（套数合计/件数合计…）：数字列是数量不是金额，不做金额校验
_QTY_TOTAL_WORDS = ("套数合计", "件数合计", "台数合计", "数量合计", "总数量")
# 费用行：参与所在区间的金额加和（运费小计=明细+运费 是常态）
_FEE_WORDS = ("服务费", "运费", "快递费", "物流费", "安装费", "调试费")

# 英文段号词（ONE/TWO/…）：与 一/二/三 同义
_EN_SEQ_NUMS = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN",
                "EIGHT", "NINE", "TEN")

_CN_NUM = set("一二三四五六七八九十")


def _header_key(text: str) -> str:
    """表头文本归一化：小写、剥括号、去掉空白与标点，只留字母/数字/汉字"""
    if text is None:
        return ""
    s = str(text).lower()
    s = re.sub(r"[\(（][^\)）]*[\)）]", "", s)      # 去掉单位说明：(元)/(USD)
    s = re.sub(r"[\s\.\_\-/:：、，,]+", "", s)
    s = s.replace("&", "").replace("／", "")
    return s


def _classify_header(text: str) -> List[str]:
    """一个表头单元格 -> 它代表的字段列表（可多重，如「名称/型号」）"""
    key = _header_key(text)
    if not key:
        return []
    fields: List[str] = []
    for field, words in _HEADER_RULES.items():
        for word in words:
            token = re.sub(r"[\s\.\-/]", "", word)
            if token and token in key:
                if field == "total" and any(w in key for w in _QTY_TOTAL_WORDS):
                    continue                  # 套数合计≠金额列
                fields.append(field)
                break
    return fields


def _merged_ranges(ws):
    return [r for r in ws.merged_cells.ranges]


def _cell(ws, row: int, col: int, ranges=None):
    """取单元格值；合并区域内返回左上角的值（表头合并列必须这样展开）"""
    value = ws.cell(row, col).value
    if value is not None:
        return value
    for rng in (ranges if ranges is not None else ws.merged_cells.ranges):
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return ws.cell(rng.min_row, rng.min_col).value
    return None


def _s(value) -> str:
    """单元格 -> 文本。数字去掉 .0，None -> 空串"""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def _find_header(ws, ranges) -> Tuple[int, Dict[str, int]]:
    """扫描前 40 行，按字段命中数打分定位表头行。返回 (行号, 字段->列)"""
    best_row, best_map, best_score = 0, {}, 0
    limit = min(ws.max_row, 40)
    for row in range(1, limit + 1):
        colmap: Dict[str, int] = {}
        for col in range(1, ws.max_column + 1):
            for field in _classify_header(_s(_cell(ws, row, col, ranges))):
                colmap.setdefault(field, col)
        score = len(colmap)
        if not all(f in colmap for f in _REQUIRED_FIELDS):
            continue
        if not any(f in colmap for f in _ANCHOR_FIELDS):
            continue
        if score > best_score:
            best_row, best_map, best_score = row, colmap, score
    return best_row, best_map


def _is_summary(*texts: str) -> bool:
    joined = "".join(norm_text(t) for t in texts if t)
    lowered = joined.lower()
    return any(word in lowered for word in _SUMMARY_WORDS)


def _is_stop(*texts: str) -> bool:
    for text in texts:
        t = (text or "").strip().lower().lstrip("：: ")
        if not t:
            continue
        if any(t.startswith(word.lower()) for word in _STOP_WORDS):
            return True
    return False


def norm_text(text: str) -> str:
    """比对用：去空白，其余保持原样（不做大写，避免中文/英文混排时丢信息）"""
    return re.sub(r"\s+", "", str(text or ""))


_RE_NUMBER = re.compile(r"[-+]?[\d,]*\.?\d+")


def _is_number(text: str) -> bool:
    return _RE_NUMBER.fullmatch((text or "").strip()) is not None


_RE_AMOUNT_CLEAN = re.compile(r"[¥￥$€£,\s]|USD|CNY|RMB|元|人民币", re.IGNORECASE)


def parse_amount(value) -> Optional[float]:
    """单元格值 -> 金额数字。解析不出返回 None（调用方跳过校验，不猜）。

    认：数字型、千分位、货币前缀/后缀（¥1,200 / USD 1200 / 1200元）、
    全角数字、括号负数 (1200) -> -1200。
    不认：含其他文字的（「见附件」「面议」）、百分比、日期。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = _RE_AMOUNT_CLEAN.sub("", text)
    text = text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    if not _RE_NUMBER.fullmatch(text):
        return None
    try:
        num = float(text.replace(",", ""))
    except ValueError:
        return None
    return -num if negative else num


_NAME_KIND_RULES = (
    ("汽车衡", KIND_TRUCK), ("地磅", KIND_TRUCK), ("truck", KIND_TRUCK),
    ("称重模块", KIND_MODULE), ("weighingmodule", KIND_MODULE), ("模块", KIND_MODULE),
    ("平台秤", KIND_PLATFORM), ("platform", KIND_PLATFORM),
    ("台秤", KIND_BENCH), ("benchscale", KIND_BENCH),
    ("接线盒", KIND_JBOX), ("junctionbox", KIND_JBOX), ("jbox", KIND_JBOX),
    ("仪表", KIND_INSTRUMENT), ("控制器", KIND_INSTRUMENT),
    ("indicator", KIND_INSTRUMENT), ("controller", KIND_INSTRUMENT),
    ("display", KIND_INSTRUMENT),
    ("传感器", KIND_SENSOR), ("loadcell", KIND_SENSOR), ("sensor", KIND_SENSOR),
    ("电缆", KIND_CABLE), ("cable", KIND_CABLE),
)


def kind_from_name(*texts: str) -> str:
    """名称 -> 品类。顺序有意义：平台秤 必须先于 台秤（前者含后者字样）"""
    joined = norm_text(" ".join(t for t in texts if t)).lower()
    for word, kind in _NAME_KIND_RULES:
        if word in joined:
            return kind
    return KIND_UNKNOWN


def pick_model(text: str, catalog, require_hit: bool = False,
               kind: Optional[str] = None,
               match_kind: bool = False) -> Tuple[str, str, Any]:
    """从「名称/型号」文本里选出真正的具体型号.

    打分而非取第一个：括号内的（行业写具体型号的位置）权重最高，其次查库命中、
    秤体系列、段数；型批型号（TCS-3t / SCS-3t）重罚，让位具体型号。

    require_hit=True 用于「型号列是空的、只能从描述里捞」的场景：此时必须查库
    命中才认，否则会把 17-4PH（不锈钢牌号）、IP68 这类参数当成型号。

    match_kind=True 与 require_hit 一起用：兜底捞上来的型号，品类必须与本行的
    品类相容（见 `_kind_ok`）。描述正文里配件型号一大堆——平台秤模板的
    「5.接线盒AWJ-005*1」，AWJ-005 在通表里是 jbox，命中就算「有型号」，
    整机型号缺失被悄悄盖掉（L1M 再也报不出来）。但反过来，行本身就是仪表
    或接线盒时（阿根廷「Controller (Indicator) / FAB3306DREX1AG00D」），
    必须允许取到本行该有的配件型号，不能一律只认整机。

    kind=KIND_MODULE 时走模块铁律：型号 = 模块系列（可带变体尾缀），
    52-30ML CS SB14-1134kg-BH-C3 的型号是 52-30ML，后面的传感器串只是配置——
    按用户拍板口径，模块型号从模块通表的系列校验（52-30ML -> 52-30M）。
    """
    candidates = tokenize_models(text)
    if not candidates:
        return "", "none", catalog.lookup("")

    if kind == KIND_MODULE:
        for token in candidates:
            if catalog.module_series_hit(token):
                return token, "series", catalog.lookup(token)

    best = None
    for token in candidates:
        hit = catalog.lookup(token)
        if require_hit and not hit.found:
            # 通表没收录、但编码结构合法的具体型号（AWPD-C-010-1212）仍算型号：
            # 后面判出 L1U「系列存在、具体型号未收录」比 L1M「没写型号」准确。
            # 编码表很严，17-4PH / IP68 / 400-500 这些噪声一律解不出来。
            if catalog.codes.decode(token) is None:
                continue
        if match_kind and not _kind_ok(kind, hit.kind):
            continue
        # 纯数字多段（55-30 系列 / 400-500 尺寸）：只有查库命中才是型号，
        # 否则就是量程、台面这类数字——绝不选它当型号
        if re.fullmatch(r"[\d./\-]+", norm(token)) and not hit.found:
            continue
        score = 0
        if hit.found:
            score += 5
        if in_parens(text, token):
            score += 8
        if hit.kind in _WHOLE_KINDS:
            score += 4
        if hit.level == "typebatch":
            score -= 12
        score += min(len(token.split("-")), 5)
        if best is None or score > best[0]:
            best = (score, token, hit)

    if best is None:
        return "", "none", catalog.lookup("")
    return best[1], best[2].level, best[2]


# 整机品类：一台机器。其余（接线盒/仪表/传感器/电缆/附件）都是配件。
_WHOLE_KINDS = (KIND_BENCH, KIND_PLATFORM, KIND_MODULE, KIND_TRUCK)


def _kind_ok(name_kind: Optional[str], hit_kind: str) -> bool:
    """兜底抽型号时的品类相容判断。

    整机行（或品类不明的行）不能被配件型号顶上；配件行（仪表/接线盒/电缆）
    则应该取到自己的品类。描述通表命中但没标品类的（kind=unknown，如
    M30-C-AWB-1t-BH-C3-X 这类 desc 级命中）一律放行。
    """

    if hit_kind in (KIND_UNKNOWN, "", None):
        return True
    if name_kind in (None, KIND_UNKNOWN) or name_kind in _WHOLE_KINDS:
        return hit_kind in _WHOLE_KINDS
    return hit_kind == name_kind


# 描述正文里的「配件行」：编号 + 配件名打头。整机型号不会写在这种行里，
# 从描述兜底捞型号时要先剔掉，免得把「5.接线盒AWJ-005」的接线盒当成整机。
_RE_PART_ROW = re.compile(
    r"^\s*(?:\d+\s*[.、)）]?|[-•·])\s*"
    r"(?:接线盒|称重传感器|传感器|称重仪表|仪表|控制器|显示仪表|电缆|信号电缆|信号线|"
    r"立柱|拉杆|过渡板|限位|护罩|盖板)")


def _without_part_rows(text: str) -> str:
    """剔除配件行，只留整机相关的行，供兜底抽型号用。"""

    lines = [ln for ln in str(text or "").splitlines()
             if not _RE_PART_ROW.match(ln)]
    return "\n".join(lines)


def _head(text: str, lines: int = 2) -> str:
    """型号通常在第一两行（名称/型号），描述正文在后面。取太多会误抓描述里的配件型号"""
    parts = [p for p in str(text or "").splitlines() if p.strip()]
    return "\n".join(parts[:lines])


def _is_review_diag(ws) -> bool:
    """批阅副本自带的诊断页（annotate.py 生成）：A1 是固定标题。

    重新批阅一份批阅副本时要跳过它，否则会被当成一张没有明细表头的工作表。
    """
    try:
        return _s(ws.cell(1, 1).value) == "报价单批阅结果"
    except Exception:
        return False


def read_quote(path: str, catalog=None) -> QuoteDoc:
    """读一份报价单 -> QuoteDoc。不做任何判定，只做结构化。"""
    from COPA.apps.audit.db import Catalog
    from COPA.apps.audit.errors import wrap

    catalog = catalog or Catalog.get()
    doc = QuoteDoc(path=path)
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:                    # noqa: BLE001 统一转中文提示
        raise wrap(path, exc) from exc
    doc.sheets = [n for n in wb.sheetnames
                  if not n.startswith("_COPA")]
    try:
        from COPA.apps.audit import pno
        doc.project_no = pno.find(wb)      # 白字项目号：批阅取快照基线的钥匙
    except Exception:                      # noqa: BLE001 号码读不到不影响批阅
        doc.project_no = ""

    for ws in wb.worksheets:
        if ws.title.startswith("_COPA"):
            continue          # 我们自己的快照表（mark.py），不是报价内容
        if _is_review_diag(ws):
            doc.sheets = [n for n in doc.sheets if n != ws.title]
            continue          # 批阅副本的诊断页，同样不是报价内容
        ranges = _merged_ranges(ws)
        header_row, colmap = _find_header(ws, ranges)
        if not header_row:
            # 认不出表头就整页跳过，不再报 L11：表头被人改坏的概率低到突兀，
            # 报出来也只是给每份文件添一条噪音（用户明确要求不做表头校验）。
            continue
        doc.header_rows[ws.title] = header_row
        doc.columns[ws.title] = dict(colmap)
        doc.meta.setdefault("sheet", ws.title)
        _read_sheet(ws, ranges, header_row, colmap, doc, catalog)

    if not doc.items:
        doc.meta.setdefault("empty", "1")
    return doc


def _read_sheet(ws, ranges, header_row: int, colmap: Dict[str, int],
                doc: QuoteDoc, catalog):
    seq_col = colmap.get("seq", 0)
    name_col = colmap.get("name", 0)
    model_col = colmap.get("model", 0) or name_col
    desc_col = colmap.get("desc", 0)
    unit_col = colmap.get("unit", 0)
    qty_col = colmap.get("qty", 0)
    price_col = colmap.get("price", 0)
    total_col = colmap.get("total", 0)
    remark_col = colmap.get("remark", 0)

    block = ""
    block_title = ""
    stopped = False
    fresh = False                    # 刚起一段、还没读到明细：抬头续行只认这种位置

    for row in range(header_row + 1, ws.max_row + 1):
        # 明细行**不展开合并单元格**：项目段标题行常把 B:G 合并成一整句，
        # 若按合并展开，数量/单价列都会被这句覆盖，标题行就会被误认成明细。
        # 合并展开只用于表头定位（表头是「名称/型号」跨列的真实写法）。
        seq = _s(_cell(ws, row, seq_col, ())) if seq_col else ""
        name = _s(_cell(ws, row, name_col, ())) if name_col else ""
        model_text = _s(_cell(ws, row, model_col, ())) if model_col else ""
        desc = _s(_cell(ws, row, desc_col, ())) if desc_col else ""
        unit = _s(_cell(ws, row, unit_col, ())) if unit_col else ""
        qty = _s(_cell(ws, row, qty_col, ())) if qty_col else ""
        price = _s(_cell(ws, row, price_col, ())) if price_col else ""
        total = _s(_cell(ws, row, total_col, ())) if total_col else ""
        remark = _s(_cell(ws, row, remark_col, ())) if remark_col else ""

        texts = [t for t in (seq, name, model_text, desc, unit, qty, price, total, remark)
                 if t and not t.startswith("=")]
        if not texts:
            continue

        if stopped:
            continue

        # 1) 条款/备注区：本次解析到此为止（后面都是免责条款，不是明细）
        if _is_stop(seq, name, model_text, desc):
            stopped = True
            continue

        # 2) 汇总行：小计/合计/总价/价税合计记录下来给 D 段算术校验；
        #    数量类合计（套数合计，数字列是套数）单独记，交给数量校验用
        if _is_summary(seq, name, model_text):
            joined = norm_text(" ".join(t for t in (seq, name, model_text) if t))
            lowered = joined.lower()
            if any(w in joined for w in _QTY_TOTAL_WORDS):
                # 金额列不是套数，但这行的金额是「小计×套数」的整段价，
                # 设备合计那一层要用它累加（见 arith._segment_totals）
                qty_amount, qty_amount_col = _row_amount(
                    ws, row, total_col, qty_col, ranges)
                doc.qty_totals.append(QtyTotalRow(
                    sheet=ws.title, row=row, label=name or model_text,
                    qty=qty, qty_col=qty_col, block=block,
                    amount=qty_amount, amount_col=qty_amount_col))
                continue
            if "大写金额" in lowered or "totalinword" in lowered:
                continue
            kind = "fee" if any(w in joined for w in _FEE_WORDS) else (
                "subtotal" if any(w in lowered for w in _SUBTOTAL_WORDS) else
                "equipment" if "设备" in joined else "grand")
            amount, amount_col = _row_amount(ws, row, total_col, qty_col, ranges)
            doc.summaries.append(SummaryRow(
                sheet=ws.title, row=row, label=name or model_text,
                kind=kind, amount=amount, amount_col=amount_col, block=block))
            continue

        # 3) 项目段标题：序号是一/二/三/ONE/TWO（可能带「、」）或 A/B/C，且没有数量
        seq_key = re.sub(r"[、.．，,）)\s]", "", seq.strip())
        if not qty and (seq_key in _CN_NUM
                        or seq_key.upper() in _EN_SEQ_NUMS
                        or re.fullmatch(r"[A-Za-z]{1,2}", seq_key)):
            if name or desc:
                # 段号会重复（枧洋同一页有两段都叫「四」：设备段 + 4 通道仪表段），
                # key 撞了就会把两段的明细/电缆并成一段，下游按段校验全乱。
                block = seq.strip()
                if any(b.key == block and b.sheet == ws.title for b in doc.blocks):
                    index = 2
                    while any(b.key == "{}#{}".format(block, index) and b.sheet == ws.title
                              for b in doc.blocks):
                        index += 1
                    block = "{}#{}".format(block, index)
                block_title = name or desc
                blk = _new_block(block, block_title, row, ws.title,
                                 (row, (name_col if name else desc_col) or 1),
                                 block_title)
                doc.blocks.append(blk)
                fresh = True
            continue

        # 4) 明细行：有名称或型号，且能看出是报价项（有序号/数量/单价/总价且为数字）
        #    总价列写「见附件」这类文字的不是明细，进未识别，交给人工看
        if (name or model_text) and (seq.isdigit() or _is_number(qty)
                                     or _is_number(price) or _is_number(total)):
            item = LineItem(sheet=ws.title, row=row, seq=seq, block=block,
                            name=name, model_text=model_text,
                            qty=qty, unit=unit, price=price, total=total,
                            remark=remark)
            item.desc = desc or (model_text if model_col == desc_col or not desc_col else "")
            item.cells = {k: (row, v) for k, v in (
                ("seq", seq_col), ("name", name_col), ("model", model_col),
                ("desc", desc_col or model_col), ("unit", unit_col),
                ("qty", qty_col), ("price", price_col), ("total", total_col),
                ("remark", remark_col)) if v}
            _resolve(item, catalog)
            doc.items.append(item)
            if doc.blocks:
                doc.blocks[-1].items.append(item)
            fresh = False
            continue

        # 5) 条目抬头续行：段标题下一行只写了抬头文字（「3支点，共1套。设备自重…
        #    料重…，标定量程…」），没有序号/数量/单价。它不是未识别行，是抬头的
        #    另一半——阿根廷把标题和规格分两行写，只认标题格会丢掉全部数值。
        if fresh and doc.blocks:
            # 同一格可能被当成 name/model/desc 读三遍（没有型号列时 model_col
            # 会回退到 name_col），按列去重，否则抬头文本会自我重复两遍
            parts, seen_cols = [], set()
            for col, text in ((name_col, name), (desc_col, desc), (model_col, model_text)):
                if text and col not in seen_cols:
                    parts.append(text)
                    seen_cols.add(col)
            continuation = " ".join(parts)
            if _looks_like_header(continuation):
                blk = doc.blocks[-1]
                blk.header_text = "{}\n{}".format(blk.header_text, continuation).strip()
                blk.header_cells.append(
                    (row, (name_col or desc_col or model_col or 1), continuation))
                continue

        # 6) 归不了类：显式记录，绝不静默丢弃
        if not (name or model_text):
            # 只有序号/数字的残留行（空模板里常见），没有信息量，不算"内容"
            continue
        doc.unrecognized.append(UnrecognizedRow(
            sheet=ws.title, row=row,
            text=" | ".join(t.replace("\n", " ") for t in texts)[:160],
            reason="不属于明细/项目段/汇总行"))


def _row_amount(ws, row: int, total_col: int, qty_col: int,
                ranges) -> Tuple[Optional[float], int]:
    """汇总行的金额定位：优先总价列；为空再从右往左找第一个数字格
    （合计行常把金额写在跨列合并的格里）。数量列排除——套数不是钱。"""
    if total_col:
        value = parse_amount(_cell(ws, row, total_col, ()))
        if value is not None:
            return value, total_col
    for col in range(ws.max_column, 0, -1):
        if col in (qty_col,):
            continue
        value = parse_amount(_cell(ws, row, col, ()))
        if value is not None:
            return value, col
    return None, (total_col or 0)


def _new_block(key: str, title: str, row: int, sheet: str = "",
               cell: Optional[Tuple[int, int]] = None, text: str = ""):
    from COPA.apps.audit.model import Block
    block = Block(key=key, title=title, row=row, sheet=sheet)
    block.header_text = title or ""
    block.header_cells = [(cell[0], cell[1], text or title or "")] if cell \
        else [(row, 1, text or title or "")]
    return block


# 抬头续行的识别词：只认这些字段名，避免把「备注：」区或零星说明吞成抬头
_RE_HEADER_HINT = re.compile(
    r"支点|套数|标定量程|料重|总重|皮重|设备自重|自重|分度值")

# 详细型号的截断点：汉字/全角标点之后都是人话（品牌、描述），不是型号
_RE_MODEL_CUT = re.compile(r"[\u4e00-\u9fa5，,；;：:|｜、]")


def _looks_like_header(text: str) -> bool:
    return bool(text) and _RE_HEADER_HINT.search(text) is not None


_RE_PLATE = re.compile(r"(CS|SS)\s*(\d+(?:\.\d+)?)\s*[tT](?![a-zA-Z])")


def _plate_spec(name: str) -> str:
    """过渡板规格：命名规则里过渡板只有「材质 + 典型量程段」两段（CS 2t / SS 5t）。

    报价单里它没有型号列，规格写在名称第二行（「上安装过渡板\\nSS 7.5T」）。
    这里把规格提成 model，后续按「与同段模块是否匹配」校验，而不是当型号查库。
    返回空串 = 名称里没写规格，照旧走「未填型号」。
    """
    match = _RE_PLATE.search(name or "")
    if not match:
        return ""
    return "{} {}t".format(match.group(1).upper(), match.group(2))


def _detail_model(text: str, series: str) -> str:
    """型号列 -> 模块的「详细型号」串（系列 + 材质码 + 传感器型号 [+ 防爆位]）。

    模块的材质不由系列决定：「52-30ML SS SB14-454kg-BH-C6 EX」里 SS 才是材质，
    同一个 52-30ML 既有 CS（模块附件材质：合金钢镀镍）也有 SS（304不锈钢）。
    描述通表按**详细型号**逐行收录，所以取快照必须用这一整串，只拿系列名会
    取到同系列的任意一行——这就是 L26「材质与型号不符」误报的根源。

    截断规则：只认含系列名的那一行，遇到汉字或标点即止（型号后面常紧跟
    「品牌：…」或描述正文）；保留 EX / -X，因为通表里防爆变体自成一行。
    """
    if not series:
        return ""
    for line in str(text or "").splitlines()[:3]:
        if series not in line:
            continue
        cut = _RE_MODEL_CUT.search(line)
        head = (line[:cut.start()] if cut else line).strip()
        start = head.find(series)
        if start < 0:
            continue
        cand = re.sub(r"\s+", " ", head[start:]).strip(" .-_/、")
        if len(cand) > len(series):
            return cand
    return ""


def _resolve(item: LineItem, catalog):
    """补上 item.model / item.kind / hit_level 三个字段"""
    if "过渡板" in (item.name or ""):
        # 规格可能写在名称第二行（「上安装过渡板\nSS 7.5T」），也可能单独占
        # 型号列（「SS 5T」）——两种版式都认
        spec = _plate_spec("{} {}".format(item.name or "", item.model_text or ""))
        if spec:
            item.model = spec
            item.hit_level = "accessory"
            item.kind = KIND_ACCESSORY
            return
    source = item.model_text or item.name
    name_kind = kind_from_name(item.name, item.model_text)
    model, level, hit = pick_model(_head(source), catalog, kind=name_kind)
    if not model:
        # 型号列本身没写型号时，才退到描述里找。兜底比首行严两条：
        # ① 必须查库命中（否则 17-4PH、IP68 这类参数会被当型号）；
        # ② 只认整机品类，且先剔掉配件行——平台秤描述的
        #    「5.接线盒AWJ-005*1」会把接线盒型号顶成整机型号，
        #    整机缺失（L1M）就再也报不出来了。
        loose = _without_part_rows(item.desc)
        model, level, hit = pick_model(loose, catalog, require_hit=True,
                                       kind=name_kind, match_kind=True)
        if not model and loose != (item.desc or ""):
            # 配件行之外没有，再退一步：原文里捞，品类同样要对得上
            model, level, hit = pick_model(item.desc, catalog, require_hit=True,
                                           kind=name_kind, match_kind=True)
    item.model = model
    item.hit_level = level
    item.kind = name_kind if name_kind != KIND_UNKNOWN else (hit.kind or KIND_UNKNOWN)
    if item.kind == KIND_MODULE and model:
        item.model_detail = _detail_model(_head(source), model)
