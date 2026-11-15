"""报价快照比对：把「这份文件当时是什么样」跟基线比，判定哪一行被人改动过.

基线只有一处来源：出报价时 pno.py 把逐行快照写进**项目快照**（snapshot/
<项目>.md 的「三、出单记录」）；批阅时按报价单 A 列白字里的项目号回项目快照
取基线。报价单文件本身不再携带任何快照——内部数据不该写在发给客户的文件里。

  比对口径
    - 型号与数量全一致：没人动过，照常逐条校验；
    - 型号变了：只对这一行放行选型校验，报告里给一条说明（L27），金额仍照常核算。
      这就是「人工确认过」的自动化：不需要弹窗问，快照本身就是凭证；
    - 数量变了：型号没变，选型结论不受影响，照常校验，另给一条 L28
      （数量与报价快照不符）。数量本身也是一项要核对的事实，不该因为
      「人改过」就被整体豁免——这正是「数量校验」的判据：跟快照里的数量直接 diff。
    - 新增行：快照里没有基线，按新行照常全量校验。

为什么只认型号/数量：批阅副本经 openpyxl 重存后公式会丢缓存值，L7 还会往
描述里插占位符——单价、总价、描述的变化不一定是人改的。选型是否被动过，
看型号最准；数量是否被动过，看数量。

历史沿革：v1–v4 把基线塞在批阅副本的隐藏表里，v5 改塞自定义文档属性；两条
老路都已废弃（属性会被误删、隐藏表可能随打印带出去，且都不该由客户文件承载
内部数据）。自 v6 起只从项目快照取，本模块只做比对。
"""
import hashlib
import json
from typing import Dict, List, Optional, Tuple


def _num_text(value) -> str:
    """金额/数量统一成文本比对：Excel 存数字，读回来可能是 2260 / 2260.0"""
    if value is None:
        return ""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number == int(number) else str(number)


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def row_signatures_doc(doc) -> List[list]:
    """逐行签名：[工作表, 行号, 型号, 描述摘要, 数量, 单价, 总价, 类型]

    item = 明细行；sum = 数量合计行（套数合计）。套数也要存——它是「一共做
    多少套」的唯一声明，改套数会改总价而行内算术照样成立，只能靠快照看出来。
    """
    rows = [[item.sheet, item.row, item.model or item.model_text or "",
             _hash(item.desc), item.qty, item.price, item.total, "item"]
            for item in doc.items]
    rows += [[total.sheet, total.row, "", "", total.qty, "", "", "sum"]
             for total in getattr(doc, "qty_totals", ())]
    return rows


def row_signatures(report) -> List[list]:
    return row_signatures_doc(report.doc)


def digest_doc(doc) -> str:
    """整份报价的选型摘要：只取「型号 + 数量」（明细行与套数合计行都算）"""
    payload = json.dumps(
        [["item", item.sheet, item.row, item.model or item.model_text or "",
          _num_text(item.qty)] for item in doc.items]
        + [["sum", total.sheet, total.row, _num_text(total.qty)]
           for total in getattr(doc, "qty_totals", ())],
        ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def digest(report) -> str:
    return digest_doc(report.doc)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def snapshot_title(project_no: str, stamp: str) -> str:
    """快照标题：项目号 + 时间戳。

    对外开放的原始单没有项目号（不是本系统出的报价），这时只写时间戳，
    不拿文件名或「未编号」凑——标题是用来对账的，宁可短也不要错。
    """
    code = (project_no or "").strip()
    return "{} · {}".format(code, stamp) if code else stamp


# ---------------------------------------------------------------------------
# 基线数据结构
# ---------------------------------------------------------------------------
class State:
    def __init__(self, digest_value: str = "", built_at: str = "",
                 rows: Optional[List[list]] = None, source: str = "",
                 pno: str = ""):
        self.digest = digest_value
        self.built_at = built_at
        self.rows = rows or []
        self.source = source
        self.pno = pno

    def __bool__(self) -> bool:
        return bool(self.digest or self.rows)

    @property
    def title(self) -> str:
        """快照的自述标题：项目号 · 时间戳（没有就退回时间戳）"""
        return snapshot_title(self.pno, self.built_at) if self.built_at else (self.pno or "")


# ---------------------------------------------------------------------------
# 比对
# ---------------------------------------------------------------------------
CHANGE_MODEL = "型号"
CHANGE_QTY = "数量"
CHANGE_PRICE = "金额"
CHANGE_DESC = "描述"
CHANGE_NEW = "新增"


class RowChange:
    """一行相对快照的变动.

    型号与数量分开记：型号变了才放行选型校验（L27）；数量变了型号没变，
    选型结论不受影响，照常校验并另报一条 L28。两个信号混在一起，就会出现
    「改个数量，整行选型一起免检」这种过度豁免。
    """

    __slots__ = ("reasons", "model_changed", "qty_changed", "new",
                 "old_model", "new_model", "old_qty", "new_qty")

    def __init__(self, new: bool = False):
        self.reasons: List[str] = []
        self.model_changed = False
        self.qty_changed = False
        self.new = new
        self.old_model = ""
        self.new_model = ""
        self.old_qty = ""
        self.new_qty = ""

    @property
    def text(self) -> str:
        return "；".join(self.reasons)

    def __bool__(self) -> bool:
        return bool(self.reasons)

    def __repr__(self) -> str:
        return "<RowChange {}>".format(self.text or "-")


def _differs(old, new) -> bool:
    """两侧都有值且不同才算改动。批阅副本经 openpyxl 重存后公式会丢缓存值，
    读回来是空——那不是人工改动，不能据此判 override。"""
    a, b = _num_text(old), _num_text(new)
    if not a or not b:
        return False
    return a != b


def compare_doc(doc, state: State) -> Dict[Tuple[str, int], RowChange]:
    """当前明细 vs 快照 -> {(工作表, 行号): RowChange}。行按 (工作表, 行号) 对齐；
    行号对不上时退化为按型号匹配（插行/删行后仍能认出同一件）。

    套数合计行（kind=sum）单独对：它没有型号，对不上位置就是没有基线，不比。
    """
    if not state:
        return {}
    if state.digest and state.digest == digest_doc(doc):
        return {}                    # 型号与数量全一致（含套数）：没人动过选型
    old_by_pos: Dict[Tuple[str, int], list] = {}
    old_by_model: Dict[str, List[list]] = {}
    old_sums: Dict[Tuple[str, int], list] = {}
    for row in state.rows:
        if not row or len(row) < 7:
            continue
        kind = str(row[7]) if len(row) > 7 and row[7] else "item"
        if kind == "sum":
            old_sums[(str(row[0]), int(row[1] or 0))] = row
            continue
        old_by_pos[(str(row[0]), int(row[1] or 0))] = row
        old_by_model.setdefault(str(row[2] or ""), []).append(row)

    changes: Dict[Tuple[str, int], RowChange] = {}
    for item in doc.items:
        key = (item.sheet, item.row)
        old = old_by_pos.get(key)
        if old is None:
            same = [r for r in old_by_model.get(item.model or "", [])
                    if str(r[0]) == item.sheet]
            old = same[0] if len(same) == 1 else None
        if old is None:
            change = RowChange(new=True)      # 快照里没有这一行：按新行全量校验
            change.reasons.append(CHANGE_NEW)
            changes[key] = change
            continue
        change = RowChange()
        if str(old[2] or "") != (item.model or ""):
            change.model_changed = True
            change.old_model = str(old[2] or "")
            change.new_model = item.model or ""
            change.reasons.append("{}：{} → {}".format(
                CHANGE_MODEL, change.old_model or "-", change.new_model or "-"))
        if _differs(old[4], item.qty):
            change.qty_changed = True
            change.old_qty = _num_text(old[4])
            change.new_qty = _num_text(item.qty)
            change.reasons.append("{}：{} → {}".format(
                CHANGE_QTY, change.old_qty, change.new_qty))
        if change:
            changes[key] = change
        # 单价/总价/描述只留痕不判：重存后公式丢缓存值、占位符插入都不是人工改选型

    for total in getattr(doc, "qty_totals", ()):
        key = (total.sheet, total.row)
        old = old_sums.get(key)
        if old is None:
            continue                     # 快照里没有套数合计：没有基线，不比
        if not _differs(old[4], total.qty):
            continue
        change = RowChange()
        change.qty_changed = True
        change.old_qty = _num_text(old[4])
        change.new_qty = _num_text(total.qty)
        change.reasons.append("{}：{} → {}".format(
            CHANGE_QTY, change.old_qty, change.new_qty))
        changes[key] = change
    return changes


def compare(report, state: State) -> Dict[Tuple[str, int], RowChange]:
    return compare_doc(report.doc, state)


def is_modified(report, state: Optional[State]) -> bool:
    return bool(state) and bool(state.digest) and state.digest != digest(report)


__all__ = ["State", "RowChange", "compare", "compare_doc", "digest",
           "digest_doc", "is_modified", "snapshot_title",
           "row_signatures", "row_signatures_doc"]
