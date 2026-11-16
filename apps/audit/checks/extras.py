"""L30/L31/L32/L33：相对固定配置与库覆盖的三条补检.

用户反馈（2026-11-08 第八轮）逐条对应：

  L32 电缆长度   台秤一般不标长度，不校验；平台秤默认每台 5 米；称重模块默认
                 每套 10 米，多通道方案每套 20 米。不是默认值一律判橙——这类
                 偏差多半是漏改，但确实存在客户指定长度的情形，交人确认。
  L30/L31 电池   描述或型号涉及电池时，整单必须能对上「电池 + 充电器/防爆电源」。
                 只有「带电池接口」「电池另配」而没有实体电池描述 -> 红（L30），
                 大概率是接口写了、东西没配；有实体电池 -> 橙（L31），提示复核
                 充电器与防爆电源是否齐套。
  L33 传感器型号 描述写了传感器型号但不在传感器通表（茂名伟尔泰用 VPG 3510，
                 此前完全没有提示）。只在这个位置写了型号、又不是库内系列时
                 报橙——外购是可能的，但必须有人确认过。

为什么不是逐行纯函数：电池要跨行看整单（接口写在第 14 行、电池可能写在第 17 行），
电缆要看项目段标题判多通道。所以入口是 check_doc，返回按行挂载的问题。
"""
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from COPA.apps.audit.model import (KIND_CABLE, KIND_MODULE, KIND_PLATFORM,
                                   LEVEL_RED, LEVEL_YELLOW)
from COPA.apps.audit.naming import tokenize_models

# ---- 电缆 -----------------------------------------------------------------
_RE_CABLE_LEN = re.compile(
    r"(?:信号|数据|称重|屏蔽|主)?电缆[^0-9\n]{0,10}(\d+(?:\.\d+)?)\s*(?:米|m\b)", re.I)
_MULTI_CHANNEL = re.compile(r"多通道|4\s*通道|四通道|4CH", re.I)
_DEFAULT_CABLE = {KIND_PLATFORM: 5.0, KIND_MODULE: 10.0}
_MULTI_CABLE = 20.0


def cable_expectation(kind: str, multi: bool):
    """该品类的默认电缆长度（米）。None = 不校验（台秤/其他）。"""
    if kind == KIND_MODULE:
        return _MULTI_CABLE if multi else _DEFAULT_CABLE[KIND_MODULE]
    return _DEFAULT_CABLE.get(kind)


def _cable_length_spans(text: str):
    """-> [(米数, 起, 止)]。区间盖「5 米」这一小段，不盖整行描述"""
    out = []
    for match in _RE_CABLE_LEN.finditer(text or ""):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        out.append((value, match.start(1), match.end(0)))
    return out


def _cable_length(text: str):
    found = _cable_length_spans(text)
    return found[0][0] if found else None


# ---- 电池 -----------------------------------------------------------------
_RE_BATTERY = re.compile(r"电池|蓄电|防爆电源", re.I)
# 「无电池/不带电池」是反例，先剔掉再判断，否则「无电池…带电池接口」会被当成电池版
_RE_BATTERY_NEG = re.compile(
    r"(?:无|不带|不含|非|没有|未配|无需)[^，,；;。\n]{0,4}(?:电池|防爆电源)|(?:电池|防爆电源)[^，,；;。\n]{0,4}(?:另配|另购|不含)", re.I)
_RE_BATTERY_IFACE = re.compile(r"电池接口|电池仓|预留电池|电池接插件|电池插座", re.I)
# 标配口径：内置/标配电池 + 充电器 = 出厂配置已交代完整，不提醒。
# 台秤默认就是内置电池，若连标配都报橙，每张台秤单都会挂一条，规则就废了。
_RE_BATTERY_STD = re.compile(r"(?:内置|标配|自带)[^，,；;。\n]{0,6}电池", re.I)
_RE_CHARGER = re.compile(r"充电器|充电座|充电盒", re.I)
_RE_BATTERY_REAL = re.compile(
    r"(?:内置|标配|含|自带|配|采用|选配)[^，,；;。\n]{0,6}(?:锂|镍氢|铅酸|蓄)?电池"
    r"|\d+(?:\.\d+)?\s*(?:Ah|AH|ah)"
    r"|防爆电源|防爆电池|BT-?\d+|锂电池|蓄电池", re.I)


def battery_state(text: str) -> str:
    """-> 'real'（写了实体电池）/ 'iface'（只有接口或另配）/ ''（不涉及）"""
    if not text or not _RE_BATTERY.search(text):
        return ""
    cleaned = _RE_BATTERY_NEG.sub(" ", text)
    if not _RE_BATTERY.search(cleaned):
        return ""
    if _RE_BATTERY_STD.search(cleaned) and _RE_CHARGER.search(cleaned):
        return ""                       # 标配内置电池 + 充电器：完整交代
    if _RE_BATTERY_REAL.search(cleaned):
        return "real"
    return "iface"


def _instrument_supports_battery(text: str, catalog) -> bool:
    """描述里内嵌的仪表型号是否属于「支持电池」的型号（型号里带 B 位）。"""
    if not text or not getattr(catalog, "instrument_battery", None):
        return False
    for token in tokenize_models(text):
        from COPA.apps.audit.naming import norm
        if norm(token) in catalog.instrument_battery:
            return True
    return False


# ---- 传感器 ---------------------------------------------------------------
_SENSOR_WINDOW = re.compile(r"传感器[^；;\n]{0,44}")
_SENSOR_JUNK = re.compile(r"PH|不锈钢|合金|碳钢|材质|等级|精度|IP\d+|℃", re.I)


def sensor_tokens(text: str) -> List[str]:
    """描述里「传感器」附近写出的型号 token（排除材质/等级这类词）。"""
    out: List[str] = []
    for match in _SENSOR_WINDOW.finditer(text or ""):
        for token in tokenize_models(match.group(0)):
            if len(token) < 4 or not re.search(r"\d", token):
                continue
            if _SENSOR_JUNK.search(token):
                continue
            if token not in out:
                out.append(token)
    return out


# ---- 入口 -----------------------------------------------------------------
def check_doc(doc, catalog, rules) -> Tuple[Dict[Tuple[str, int], List], List]:
    """-> (按行挂载的问题, 文件级问题)"""
    by_row: Dict[Tuple[str, int], List] = defaultdict(list)
    file_issues: List = []
    titles = {block.key: block.title for block in doc.blocks}

    # 电缆行按项目段归集：模块方案的电缆长度不是写在描述里，而是「信号电缆」
    # 那一行的数量（单位米）。所以先扫一遍，段内模块才有长度可比。
    cables: Dict[Tuple[str, str], List] = defaultdict(list)
    for item in doc.items:
        if item.kind == KIND_CABLE or "电缆" in (item.name or ""):
            cables[(item.sheet, item.block)].append(item)

    # 多通道方案：整单里出现「4 通道 / 多通道」的段（枧洋那种末段是 4 通道
    # 仪表的单子），电缆按每套 20 米算。按段判不够——多通道体现在仪表段而不是
    # 模块段的标题里。
    multi_doc = any(_MULTI_CHANNEL.search(t) for t in titles.values())
    cable_done = set()                 # 一段只报一条，别按模块行数重复

    for item in doc.items:
        desc = item.desc or ""

        # ---- L32 电缆长度 ------------------------------------------------
        # 只比「单据上显式写的那个数」，不按台数折算总长：
        #   平台秤 -> 描述里写的长度，默认 5 米/台；
        #   称重模块 -> 电缆行的数量（米），默认 10 米/套（多通道 20 米）；
        #   台秤 -> 一般不标，不校验。
        multi = bool(multi_doc or _MULTI_CHANNEL.search(titles.get(item.block, ""))
                     or _MULTI_CHANNEL.search(desc))
        if item.kind == KIND_PLATFORM:
            expected = cable_expectation(item.kind, multi)
            found = _cable_length_spans(desc)
            actual = found[0][0] if found else None
            if expected is not None and actual is not None \
                    and abs(actual - expected) > 1e-6:
                by_row[(item.sheet, item.row)].append(rules.issue(
                    "L32",
                    level=LEVEL_YELLOW,
                    message="描述写电缆 {} 米，平台秤默认每台 {} 米".format(
                        _fmt(actual), _fmt(expected)),
                    expected="{} 米".format(_fmt(expected)),
                    actual="{} 米".format(_fmt(actual)),
                    anchor=item.cells.get("desc") or item.cells.get("model"),
                    span=(found[0][1], found[0][2]), field="电缆长度"))
        elif item.kind == KIND_MODULE:
            expected = cable_expectation(item.kind, multi)
            key = (item.sheet, item.block)
            cable = _block_cable(cables.get(key, ())) if item.block else None
            actual = _num_or_none(cable.qty) if cable is not None else None
            if cable is not None and expected is not None and actual is not None \
                    and abs(actual - expected) > 1e-6 and key not in cable_done:
                cable_done.add(key)
                # 挂在电缆行上：要改的是这一格的数量，不是模块描述
                by_row[(cable.sheet, cable.row)].append(rules.issue(
                    "L32",
                    level=LEVEL_YELLOW,
                    message="本段电缆写 {} 米，称重模块默认每套 {} 米{}".format(
                        _fmt(actual), _fmt(expected), "（多通道方案）" if multi else ""),
                    expected="{} 米".format(_fmt(expected)),
                    actual="{} 米".format(_fmt(actual)),
                    anchor=cable.cells.get("qty") or cable.cells.get("name")))

        # ---- L33 传感器型号未收录 ----------------------------------------
        families = catalog.sensor_families() if catalog else []
        if families and "传感器" in desc:
            if not any(fam in desc.upper() for fam in families):
                tokens = sensor_tokens(desc)
                if tokens:
                    at = desc.find(tokens[0])
                    by_row[(item.sheet, item.row)].append(rules.issue(
                        "L33",
                        level=LEVEL_YELLOW,
                        message="传感器型号 {} 不在传感器通表（库内系列：{}）".format(
                            tokens[0], "、".join(families[:6])),
                        expected="库内传感器型号",
                        actual=tokens[0],
                        anchor=item.cells.get("desc") or item.cells.get("model"),
                        span=(at, at + len(tokens[0])) if at >= 0 else None,
                        field="传感器型号"))

    # ---- L30/L31 电池（整单）--------------------------------------------
    states = [(item, battery_state(item.desc)) for item in doc.items]
    # 型号支持电池 = 触发（该配电池却没写），不等于「已配电池」——
    # 兰达 261027 的教训：FT230NA002B 支持电池，描述写「无电池…带电池接口」，
    # 如果按 real 记，整单就被判成「已配电池」，红降成橙。
    # 只有「描述完全没提电池」时，型号支持电池才作为「该配没配」的触发。
    # 描述已经写了内置电池 + 充电器（标配）就不该再报——L13 用例的教训。
    states += [(item, "iface") for item in doc.items
               if not _RE_BATTERY.search(item.desc or "")
               and _instrument_supports_battery(item.desc, catalog)]
    triggers = [(it, st) for it, st in states if st]
    if triggers:
        has_real = any(st == "real" for _, st in triggers)
        anchor_item = triggers[0][0]
        anchor = anchor_item.cells.get("desc") or anchor_item.cells.get("model")
        if not has_real:
            file_issues.append(rules.issue(
                "L30",
                level=LEVEL_RED,
                message="本单涉及电池（型号支持电池或描述写了电池接口），但没有配置实体电池："
                        "只写了「带电池接口/电池另配」不算配置完成",
                expected="写明电池型号与数量，或明确改为 220VAC / 24VDC 供电",
                actual=triggers[0][1] == "iface" and "仅电池接口/另配" or "无电池描述",
                anchor=anchor, sheet=anchor_item.sheet))
        else:
            file_issues.append(rules.issue(
                "L31",
                level=LEVEL_YELLOW,
                message="本单已配置电池，请复核充电器、防爆电源是否齐套，且与仪表供电方式一致",
                expected="电池 + 充电器（防爆环境含防爆电源）齐套",
                actual="已写电池配置", anchor=anchor, sheet=anchor_item.sheet))

    return dict(by_row), file_issues


def _block_cable(items):
    """段内那条「信号电缆」行；多条取第一条（同段一般只有一条主电缆）"""
    for item in items:
        return item
    return None


def _num_or_none(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)


def _kind_name(kind: str) -> str:
    return {KIND_PLATFORM: "平台秤", KIND_MODULE: "称重模块"}.get(kind, "设备")


__all__ = ["check_doc", "battery_state", "cable_expectation", "sensor_tokens"]
