"""L25/L26：描述与型号快照的比对（替代逐条描述规则的「对齐」）.

判据换了个方向：不再问「描述里写的材质和型号材质段一致吗」这类逐字段命题，
而是把型号的标准配置摊开（快照），把报价描述也摊开（claims），两边对表：

  L25 描述缺项：快照有、描述没提
       —— 型号蕴含项（拉杆/防爆/供电）判红：漏写就是配置与型号不符；
          说明性项（材质/外壳/安装方式）判黄：信息不全，客户验收没依据。
  L26 描述不符：两边都写了但互相排斥（220VAC vs DC24V、碳钢 vs 不锈钢）
       —— 一律判红。

两路比对：
  1. 本行型号（item.model）→ 快照，比全部 compare_keys；
  2. 描述正文里的其他型号（秤体行带仪表、模块行带传感器）→ 只比型号蕴含项
     （供电/防爆/电池），这正是海斯福 C14「仪表尾缀 D 却写 220VAC」的来路。

量程/台面/分度值仍归 L3/L4/L15；快照取不到的字段不提要求（宁漏不误报）。
宽容口径见 claims.compatible：型号写法更完整、协议多写少写都算相容。
"""
import re

from COPA.apps.audit import claims as C
from COPA.apps.audit import modelspec as S
from COPA.apps.audit.model import (KIND_ACCESSORY, KIND_CABLE, KIND_NAMES,
                                   KIND_UNKNOWN, LEVEL_RED, LEVEL_YELLOW)
from COPA.apps.audit.naming import norm, tokenize_models

# 快照值 -> 人话（报告里「标准配置为『1』」这种是给人看的，不能是编码）
_EXPECT_TEXT = {
    C.K_PULL_ROD: lambda v: "带水平拉杆" if v == "1" else "不带拉杆",
    C.K_EX: lambda v: "非防爆" if v in ("0", "") else "防爆",
    C.K_POWER: lambda v: {"ac": "AC220V", "dc": "DC24V", "bat": "电池供电"}.get(v, v),
    C.K_BATTERY: lambda v: {"has": "带电池配置", "none": "无电池"}.get(v, v),
}

# 描述正文里的其他型号只比这几项：写错会直接烧表/装不上，且描述里必然出现
_EMBEDDED_KEYS = (C.K_POWER, C.K_EX, C.K_BATTERY)


def _is_echo(item) -> bool:
    """汇总页聚合行：描述列与型号列同格，desc 是纯型号串回显，没有独立描述"""
    if not item.model_text:
        return False
    if norm(item.desc) != norm(item.model_text):
        return False
    return not re.search(r"[\u4e00-\u9fff]", item.desc or "")


def _battery_ok(expected: dict, actual: C.Claim) -> bool:
    """描述写「电池供电」而标准描述标 AC220V：若该型号标准描述里本身就带
    电池配置（锂电池/电池接口），这是「交直流通用」而不是写错，不判冲突。"""
    if actual is None or actual.value != "bat":
        return False
    battery = expected.get(C.K_BATTERY)
    return battery is not None and battery.value == "has"


def _exp_text(key: str, claim: C.Claim) -> str:
    fn = _EXPECT_TEXT.get(key)
    return fn(claim.value) if fn else (claim.raw or claim.value)


def check(item, catalog, rules):
    if getattr(rules, "desc_engine", "diff") != "diff":
        return []                          # rules 引擎：旧规则负责，不重复报
    if not item.model or not item.desc:
        return []
    if item.kind in (KIND_CABLE, KIND_UNKNOWN):
        return []
    if _is_echo(item):
        return []
    # 模块取「详细型号」（系列+材质码+传感器）查通表：材质只写在详细型号里，
    # 用系列名会查到同系列的任意一行，材质必错（L26 误报的根源）
    snap = S.get(catalog, getattr(item, "model_detail", "") or item.model)
    if snap is None:
        # 本行型号在描述通表里没有标准描述（如 FTBR 台秤）：本行不比，
        # 但描述正文里内嵌的仪表/传感器在通表里有标准描述，写错供电/防爆
        # 照样要报——海斯福 C14 就是秤体行里夹着仪表型号。
        if catalog is None:
            return []
        return _embedded(item, None, rules, catalog, C.extract(item.desc), set())
    return diff(item, snap, rules, catalog)


def diff(item, snap, rules, catalog=None):
    """快照 vs 描述 -> 问题列表（纯函数，便于单测逐条打靶）"""
    expected = snap.claims()
    got = C.extract(item.desc)
    must = S.MUST_DECLARE.get(snap.kind, ())
    anchor = item.cells.get("desc") or item.cells.get("model") or (item.row, 1)
    issues = []
    reported = set()

    for key in snap.compare_keys():
        exp = expected.get(key)
        if exp is None:
            continue
        if key == C.K_PULL_ROD and exp.value != "1":
            continue                       # 型号不带拉杆：描述写不写都不判
        label = C.KEY_NAMES.get(key, key)
        actual = got.get(key)

        if key == C.K_EX and exp.value in ("0", ""):
            # 非防爆型号：不要求描述声明「非防爆」，只在描述要求防爆时报冲突
            if actual is not None and not C.compatible(exp, actual):
                issues.append(rules.issue(
                    "L26",
                    message="型号 {} 为非防爆型，描述却要求「{}」".format(
                        _short(item.model), C.describe(actual)),
                    expected="{}：非防爆".format(label),
                    actual=C.describe(actual),
                    anchor=anchor, span=actual.span, field=label))
                reported.add(key)
            continue

        if actual is None:
            if key not in must and key not in S.MODEL_IMPLIED:
                continue                   # 说明性字段没写不算问题，只在写错时报
            critical = key in S.MODEL_IMPLIED
            issues.append(rules.issue(
                "L25",
                level=LEVEL_RED if critical else LEVEL_YELLOW,
                message="描述未写明{}（型号 {} 的标准配置：{}）".format(
                    label, _short(item.model), _exp_text(key, exp)),
                expected="{}：{}".format(label, _exp_text(key, exp)),
                actual="（描述未提及{}）".format(label),
                missing=label,
                anchor=anchor, field=label))
            reported.add(key)
            continue

        if C.compatible(exp, actual):
            continue
        if key == C.K_POWER and _battery_ok(expected, actual):
            continue
        issues.append(rules.issue(
            "L26",
            message="描述的{}与型号不符：型号 {} 对应{}，描述写「{}」".format(
                label, _model_label(item), _exp_text(key, exp), C.describe(actual)),
            expected="{}：{}".format(label, _exp_text(key, exp)),
            actual=C.describe(actual),     # 纯 token，批阅端字符定位用
            anchor=anchor, span=actual.span, field=label))
        reported.add(key)

    if catalog is not None:
        issues.extend(_embedded(item, snap, rules, catalog, got, reported))
    return issues


def _embedded(item, snap, rules, catalog, got, reported):
    """描述正文里的其他型号（秤体行带仪表 / 模块行带传感器）也走一次快照比对.

    只比供电/防爆/电池三项，且不报缺项——这些是「写错就出事故」的项，
    写错必报，没写是另一类问题（L24/L7 已在管）。
    """
    issues, seen, flagged = [], set(), []
    # 长的先看：`FAB3306(FAB3306HX1PN00A)` 里完整型号才是型号，族名 FAB3306 不是
    for token in sorted(tokenize_models(item.desc or ""), key=len, reverse=True):
        key = norm(token)
        if key in seen or key == norm(item.model):
            continue
        seen.add(key)
        if any(key in done or done in key for done in flagged):
            continue                       # 同一台设备的不同写法，报一次就够
        # 正文里夹带的型号按完整写法认：前缀放宽会把族名配到无关配置行
        sub = S.build(catalog, token, prefix_ok=False)
        if sub is None:
            continue
        if snap is not None and sub.kind == snap.kind:
            continue                       # 与主型号同品类：不重复比（多半是别的配置串）
        sub_expected = sub.claims()
        for name in _EMBEDDED_KEYS:
            if name in reported:
                continue
            exp, actual = sub_expected.get(name), got.get(name)
            if exp is None or actual is None or C.compatible(exp, actual):
                continue
            if name == C.K_POWER and _battery_ok(sub_expected, actual):
                continue
            label = C.KEY_NAMES.get(name, name)
            issues.append(rules.issue(
                "L26",
                message="描述中的{} {} {}与型号不符：该型号为{}，描述写「{}」".format(
                    KIND_NAMES.get(sub.kind, "部件"), token, label,
                    _exp_text(name, exp), C.describe(actual)),
                expected="{}：{}".format(label, _exp_text(name, exp)),
                actual=C.describe(actual),
                anchor=item.cells.get("desc") or (item.row, 1),
                span=actual.span, field=label))
            flagged.append(key)
            break
    return issues


def _short(model: str) -> str:
    """型号只取首段（去掉后面的材质/传感器配置），报告里更易读"""
    return (model or "").split()[0]


def _model_label(item) -> str:
    """报告里怎么称呼这个型号：系列 + 材质码。

    模块材质由「系列 材质码 传感器型号」里的材质码决定，只报系列看不出差异——
    同一个 52-30ML 既有 CS（合金钢镀镍）也有 SS（304不锈钢）。
    """
    series = _short(item.model)
    detail = (getattr(item, "model_detail", "") or "").split()
    if len(detail) >= 2 and detail[0] == series:
        return "{} {}".format(series, detail[1])
    return series


__all__ = ["check", "diff"]
