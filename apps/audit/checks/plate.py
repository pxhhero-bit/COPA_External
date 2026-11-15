"""L34：上下安装过渡板规格与同段模块不符.

过渡板在命名规则里只有两段：**材质 + 典型量程段**（`CS 2t` / `SS 5t`），
没有「系列-量程-台面」那种型号结构，所以它不进通表逐条收录，而是按规则校验：

  材质：跟模块的附件材质一致（模块写 SS 就是不锈钢板，CS 就是碳钢板）；
  量程：按同段模块的传感器容量段映射，不是按实际总重算。

映射口径（用户 2026-11-08 确认）：
  COPA A   3t 及以下传感器 -> 2t 板；5t 剪切梁 -> 5t 板；柱式（AWD）统一 20t
  富林泰克 3t 及以下 -> 3t 板；4536kg（SB14）-> 4.5t；5099kg（SB5）-> 5t；
           柱式（RC3）统一 22.5t

为什么按映射而不是按描述：珠海锐进那张单里 SS 7.5T / SS 2.5t 都是不存在的
量程段——过渡板根本没有 7.5t、2.5t 这两个规格。按规则比，这类「写了但不存在」
的组合才抓得出来；按字符串比，它只会一直跳「未收录」。
"""
import re
from typing import Optional, Tuple

from COPA.apps.audit.model import (KIND_ACCESSORY, KIND_MODULE, LEVEL_RED,
                                   SPAN_CELL)

# 传感器系列 -> (是否柱式)。柱式统一用最大那档板，跟容量无关。
_COLUMN = {"RC3", "AWD"}
# 传感器容量两种写法都常见：SB14-4536kg（带 kg）与 RC3-7.5T（带 T）
_SENSOR = re.compile(
    r"(RC3|SB14|SB5|SB8|SB6|SLB|AWBS|AWB|AWC|AWD)[-\s]?"
    r"(\d+(?:\.\d+)?)\s*(kg|[tT](?![a-zA-Z]))", re.I)
_RE_PLATE = re.compile(r"(CS|SS)\s*(\d+(?:\.\d+)?)\s*[tT](?![a-zA-Z])")

# 富林泰克模块型号以 52-/55-/56- 开头，COPA A是 M20/M30/M50
_FT_MODULE = re.compile(r"^(?:5[2-6]|FT)", re.I)

_PLATE_SIZE = {  # brand -> (柱式板, 默认板)
    "FT": (22.5, 3.0),
    "AW": (20.0, 2.0),
}


def _brand(text: str) -> str:
    return "AW" if re.match(r"^\s*M\d", text or "", re.I) else "FT"


def _capacity(kg: float, brand: str, column: bool) -> float:
    if column:
        return _PLATE_SIZE[brand][0]
    if brand == "FT":
        if kg <= 3000:
            return 3.0
        if abs(kg - 4536) < 1:
            return 4.5
        if abs(kg - 5099) < 1:
            return 5.0
        return 5.0
    # COPA A：3t 及以下通用 2t 板，5t 剪切梁用 5t 板
    return 2.0 if kg <= 3000 else 5.0


def expectation(module) -> Optional[Tuple[str, float]]:
    """同段模块 -> 过渡板应有的 (材质, 量程t)。判不出来返回 None。"""
    if module is None:
        return None
    text = " ".join(filter(None, (module.model_text, module.name, module.model)))
    sensor = _SENSOR.search(text)
    if not sensor:
        return None
    family = sensor.group(1).upper()
    try:
        kg = float(sensor.group(2))
    except ValueError:
        return None
    if sensor.group(3).lower() == "t":
        kg *= 1000
    brand = _brand(text)
    material = ""
    upper = text.upper()
    if re.search(r"\bSS\b", upper) or re.search(r"\bS\b(?=\s|$)", upper):
        material = "SS"
    elif re.search(r"\bCS\b", upper) or re.search(r"\bC\b(?=\s|$)", upper):
        material = "CS"
    return material, _capacity(kg, brand, family in _COLUMN)


def _fmt(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)


def _spec_span(item, anchor):
    """过渡板规格（「SS 7.5T」）在锚点格里的区间；锚点格不是那个单元格就 None.

    过渡板的规格写在**名称格**（「上安装过渡板\nSS 7.5T」）而不是描述里，
    所以区间参照系是单元格本身（SPAN_CELL），不是 desc——照 desc 平移会把
    红色标到描述里那句「碳钢材质」上，正好指错。
    """
    if not anchor:
        return None
    for key in ("model", "name", "desc"):
        if item.cells.get(key) != anchor:
            continue
        text = {"model": item.model_text, "name": item.name,
                "desc": item.desc}.get(key) or ""
        match = _RE_PLATE.search(text)
        if match:
            return (match.start(), match.end())
    return None


def check_doc(doc, rules):
    """-> {(工作表, 行): [问题]}；逐段看，同段找不到模块就不判（配件可能单卖）"""
    modules = {}
    for item in doc.items:
        if item.kind == KIND_MODULE and item.block:
            modules.setdefault((item.sheet, item.block), item)

    out = {}
    for item in doc.items:
        if item.kind != KIND_ACCESSORY or "过渡板" not in (item.name or ""):
            continue
        if not item.model:
            continue                      # 名称里没写规格：交给「未填型号」
        expect = expectation(modules.get((item.sheet, item.block)))
        if expect is None or not expect[0]:
            continue
        want_mtl, want_t = expect
        match = _RE_PLATE.search(item.model)
        if not match:
            continue
        got_mtl = match.group(1).upper()
        try:
            got_t = float(match.group(2))
        except ValueError:
            continue
        reasons = []
        if got_mtl != want_mtl:
            reasons.append("材质 {}（模块为 {}）".format(got_mtl, want_mtl))
        if abs(got_t - want_t) > 1e-6:
            reasons.append("量程 {}t（该模块应配 {}t）".format(_fmt(got_t), _fmt(want_t)))
        if not reasons:
            continue
        module = modules.get((item.sheet, item.block))
        if module is None:
            continue
        out[(item.sheet, item.row)] = [rules.issue(
            "L34",
            level=LEVEL_RED,
            message="过渡板规格与本段模块不符：{}；模块 {}".format(
                "、".join(reasons), module.model or module.name.split("\n")[-1]),
            expected="{} {}t".format(want_mtl, _fmt(want_t)),
            actual="{} {}t".format(got_mtl, _fmt(got_t)),
            anchor=item.cells.get("model") or item.cells.get("name"),
            span=_spec_span(item, item.cells.get("model") or item.cells.get("name")),
            field="过渡板规格", span_scope=SPAN_CELL)]
    return out


__all__ = ["check_doc", "expectation"]
