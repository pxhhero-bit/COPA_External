"""L29：模块/过渡板数量与支点数不符.

数量校验的第二组逻辑，判据就在单据内部，不需要快照：

    项目段标题「设备名称：1T模块，3支点，共8套」
        └─ 1 套用量的模块数 = 支点数（3 只）
        └─ 上/下安装过渡板每个支点一块，数量也 = 支点数（3 块）

明细行数量写的是**每套用量**，套数合计才是「一共多少套」（那是第一组逻辑，
走 L28 跟快照比）。所以这里只在段内比，不乘套数。

不参与的品类：
  - 接线盒/电缆：数量按布线长度与方案定，跟支点数没有固定关系；
  - **4 通道仪表：统计口径不明确，暂不作校验**。每套该配几台仪表没有统一的
    统计口径，硬套一条规则只会制造误报，故不纳入本组比对。

级别定黄：标题写「3 支点」而明细写 4 只，可能是标题抄错，也可能是数量写错，
单据本身分不出谁对，交人确认。
"""
import re

from COPA.apps.audit.model import KIND_MODULE, LEVEL_YELLOW

_SUPPORT_RE = re.compile(r"([0-9]+|[一二两三四五六七八九十])\s*支点")
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def supports(title: str):
    """从项目段标题里取支点数：'3支点' / '三支点'。取不到返回 None。"""
    match = _SUPPORT_RE.search(title or "")
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token) or None
    return _CN_DIGITS.get(token)


def _number(text: str):
    try:
        value = float(str(text or "").replace(",", "").strip())
    except ValueError:
        return None
    return int(value) if value == int(value) else value


def _expected(item, supports_count: int):
    """这一行应该是多少（每套用量）。不参与校验的行返回 None。"""
    name = item.name or ""
    if "过渡板" in name:
        return supports_count
    if item.kind == KIND_MODULE or "模块" in name:
        return supports_count
    return None          # 接线盒/电缆/仪表（含 4 通道）：统计口径不明确，暂不作校验


def check_doc(doc, rules):
    """-> {(工作表, 行号): [Issue]}，由 runner 挂回对应明细行。"""
    out = {}
    for block in doc.blocks:
        count = supports(block.title)
        if not count:
            continue
        for item in block.items:
            expected = _expected(item, count)
            if expected is None:
                continue
            actual = _number(item.qty)
            if actual is None or actual == expected:
                continue
            label = (item.name or "").splitlines()[0] or "本行"
            if "过渡板" in item.name:
                message = "标题写 {} 支点，本行「{}」数量 {}——每个支点配一块过渡板".format(
                    count, label, actual)
            else:
                message = "标题写 {} 支点，本行模块数量 {} 只——单套用量的模块数应等于支点数".format(
                    count, actual)
            out.setdefault((item.sheet, item.row), []).append(rules.issue(
                "L29",
                level=LEVEL_YELLOW,
                message=message,
                expected="{} 支点 → 数量 {}".format(count, expected),
                actual="当前数量：{}".format(actual),
                anchor=item.cells.get("qty") or item.cells.get("model") or (item.row, 1)))
    return out


__all__ = ["check_doc", "supports"]
