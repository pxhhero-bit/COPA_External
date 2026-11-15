"""L28：数量与报价快照不符.

数量校验不做业务推理（不问「8 套 × 3 支点该配 24 只传感器」），就是跟快照
里那次输出的数量直接 diff——快照是出报价那一刻自动存下来的事实，之后数量
变了，差值本身就是要找的东西。

两处都用它：
  - 明细行数量（每套用量）；
  - 套数合计行（一共多少套）。套数是总价的乘数，改它不改行内算术，行内
    L16 抓不到，只有快照比得出来。

口径：
  - 没快照（原始报价单、非批阅副本）→ 不比，避免把「第一次批阅」报成问题；
  - 型号变了、数量没变 → 不报（选型问题归 L27/其他检查器）；
  - 数量变了 → L28（黄）。金额是否联动由 L16/L17 照常核算，本条只管数量事实。
"""
from COPA.apps.audit.model import LEVEL_YELLOW


def check(item, change, rules):
    """change 来自 mark.compare_doc：None / RowChange。"""
    if change is None or not getattr(change, "qty_changed", False):
        return []
    old, new = change.old_qty or "-", change.new_qty or "-"
    return [rules.issue(
        "L28",
        level=LEVEL_YELLOW,
        message="本行数量与报价快照不符：快照 {} → 现 {}".format(old, new),
        expected="快照数量：{}".format(old),
        actual="当前数量：{}".format(new),
        anchor=item.cells.get("qty") or item.cells.get("model") or (item.row, 1))]


def check_total(total, change, rules):
    """套数合计行：同样只跟快照 diff。返回文件级问题（合计行不是明细行）。"""
    if change is None or not getattr(change, "qty_changed", False):
        return []
    old, new = change.old_qty or "-", change.new_qty or "-"
    label = (total.label or "套数合计").splitlines()[0]
    return [rules.issue(
        "L28",
        level=LEVEL_YELLOW,
        message="「{}」与报价快照不符：快照 {} 套 → 现 {} 套".format(label, old, new),
        expected="快照套数：{}".format(old),
        actual="当前套数：{}".format(new),
        sheet=total.sheet,
        anchor=(total.row, total.qty_col or 1))]


__all__ = ["check", "check_total"]
