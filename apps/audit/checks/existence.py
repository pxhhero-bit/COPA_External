"""L1/L1U/L1T/L9：型号存在性与命名时效.

为什么不统一判「不存在 = 红」：通表只覆盖现行在售配置，历史单里大量旧码、一行
多码、描述表独有型号（如模块组合码 M30-C-AWB-1t-BH-C3-X）。一刀切判红会让
历史单一开就满屏红，真正的问题反而被淹没。所以四级口径：

  精确 / 归一化命中  -> 通过
  仅型批型号         -> L1T 黄（缺具体型号，可追溯性不足）
  系列存在、型号未收录 -> L1U 黄（多半是旧码，带现行型号建议）
  系列都不存在       -> L1 红（错字或臆造）
  系列存在但台面/容量段写法过期 -> L9 黄（等价换算，给出建议）
"""
from COPA.apps.audit.desclib import desc_capacity
from COPA.apps.audit.model import (EXISTENCE_EXEMPT, KIND_BENCH, KIND_MODULE,
                                   KIND_PLATFORM, SPAN_CELL)
from COPA.apps.audit.naming import looks_like_model, norm


def check(item, catalog, rules):
    issues = []
    # 型号类问题的落点与区间：型号常常不在 cells["model"] 那一格（合并版式里
    # 型号写在描述第一行），按锚点格标会把红色落在「电子台秤」上。
    anchor, span = (item.locate_model() or (item.cells.get("model"), None)) \
        if item.model else (item.cells.get("model"), None)

    if item.kind in EXISTENCE_EXEMPT:
        # 电缆/附件型号命名自由，不查库
        return issues

    if not item.model:
        # 缺型号属「无法核查」，不是「写错了」——判黄不判红，否则空模板会满屏红
        return [rules.issue(
            "L1M", message="型号列无可识别型号（空白模板或占位符）",
            expected="通表收录的具体型号", actual="（型号列无可识别内容）",
            anchor=item.cells.get("model"))]

    hit = catalog.lookup(item.model)
    legacy = _legacy_code(item, catalog, rules)

    # ---- 通过 ---------------------------------------------------------
    if hit.level in ("exact", "normalized", "desc"):
        issues.extend(legacy)
        return issues

    if hit.level == "typebatch":
        issues.append(rules.issue(
            "L1T", message="只写了型批型号「{}」，没有可追溯的具体型号".format(item.model),
            expected="型批型号 + 具体型号（如 SCS-3t（FTPD-C-030-1515-E））",
            actual=item.model, anchor=anchor,
            span=span, span_scope=SPAN_CELL, field="型号"))
        return issues

    # 旧码能换算到现行码 -> 只报 L9，不再重复报「未收录」：
    # 同一件事报两条，只会让人以为有两处错。
    if legacy:
        issues.extend(legacy)
        return issues

    # 模块系列前缀命中（52-30ML -> 52-30M）：模块通表按「基系列+配置」表达，
    # 完整选型串不逐字收录。系列成立即视为存在（用户拍板口径：模块型号
    # 从通表系列校验），不再对变体尾缀报「未收录」——那只会淹没真问题。
    if item.kind == KIND_MODULE and catalog.module_series_hit(item.model):
        return issues

    # 台秤/平台秤系列级命中（海斯福案例，与模块同口径）：FTPD-S-030-0808-E
    # 的量程码 030 与台面码 0808 各自合法，只是该组合未逐字收录——通表按
    # 「系列×量程×台面」配对表达，组合空间远大于收录行数。系列成立即视为
    # 存在，量程/台面是否与描述相符交给 L3/L4 继续把关。
    if item.kind in (KIND_BENCH, KIND_PLATFORM) and catalog.scale_series_hit(item.model):
        return issues

    issues.extend(_not_found(item, catalog, rules))
    return issues


def _not_found(item, catalog, rules):
    codes = catalog.codes
    info = codes.decode(item.model)
    anchor, span = item.locate_model() or (item.cells.get("model"), None)

    if info is not None:
        suggestion = codes.suggest(item.model, face_mm=info.face_mm)
        message = "系列 {} 存在，但具体型号未收录".format(info.family)
        if suggestion:
            message += "；按现行编码应为 {}".format(suggestion)
        return [rules.issue(
            "L1U", message=message,
            expected=suggestion or "通表中的现行具体型号",
            actual=item.model, anchor=anchor,
            span=span, span_scope=SPAN_CELL, field="型号")]

    key = norm(item.model)

    # 只写了系列名（FAB330 / FT-230 这类）：模板里常见「FAB330（具体型号）」
    # 注意：当前判定价库里 76 个 family 全部能被 lookup 的「精确/归一化/型批」
    # 先命中（多数系列名本身就是型批型号），所以这条分支实际不可达，
    # 场景由 L1T 覆盖。保留作防御：family 只在描述通表出现而没进型批表时生效。
    if key in catalog.model_families:
        return [rules.issue(
            "L1F", message="只写了型号系列「{}」，缺具体型号".format(item.model),
            expected="系列 + 配置码（如 FAB3306D01PN00D）",
            actual=item.model, anchor=anchor,
            span=span, span_scope=SPAN_CELL, field="型号")]

    # 品牌前缀认得（FT/AW/FAB），说明是本厂产品但系列未入库 -> 提示而非判错
    if any(key.startswith(brand) for brand in catalog.brands if brand):
        return [rules.issue(
            "L1U", message="型号属本厂系列，但通表中未收录", expected="通表中的现行具体型号",
            actual=item.model, anchor=anchor,
            span=span, span_scope=SPAN_CELL, field="型号")]

    if looks_like_model(item.model):
        return [rules.issue(
            "L1", message="通表中查无此型号，且无法识别其系列",
            expected="通表收录的具体型号", actual=item.model, anchor=anchor,
            span=span, span_scope=SPAN_CELL, field="型号")]

    return [rules.issue(
        "L1", message="型号写法不符合命名结构，无法与通表比对",
        expected="如 FTBR-S-060-4050-E", actual=item.model, anchor=anchor,
        span=span, span_scope=SPAN_CELL, field="型号")]


def _legacy_code(item, catalog, rules):
    """台面码/容量码写法过期：解码后能落到现行码表，说明只是编码旧，不是选错。"""
    codes = catalog.codes
    info = codes.decode(item.model)
    if info is None:
        return []

    stale = []
    if info.face_mm and not info.face_from_table:
        current = codes.face_code_for(info.family, info.face_mm)
        if current:
            stale.append(("台面码", info.face_code, current, info.face_text))
    if info.capacity_kg is not None and not info.cap_from_table:
        current = codes.cap_code_for(info.family, info.capacity_kg)
        if current:
            stale.append(("容量码", info.cap_code, current, info.capacity_text))

    if not stale:
        return []

    # 建议值：优先用「描述里的量程 + 解码出的台面」拼一个完整现行型号，
    # 这样 L9 给的建议和 L3 给的建议是同一个，不会出现两个互相打架的型号。
    desc_kg = desc_capacity(item.desc)
    capacity_hint = None
    if desc_kg is not None and info.capacity_kg and abs(desc_kg - info.capacity_kg) > 0.01:
        capacity_hint = desc_kg
    suggestion = codes.suggest(item.model, capacity_kg=capacity_hint,
                               face_mm=info.face_mm if not info.face_from_table else None)
    if not suggestion:
        suggestion = codes.suggest(
            item.model, face_mm=info.face_mm if not info.face_from_table else None)

    detail = "；".join("{} {} -> {}".format(what, old, new) for what, old, new, _ in stale)
    actual = "；".join("{}={}".format(what, text) for what, _, _, text in stale)
    message = "命名使用旧编码：" + detail
    if suggestion:
        message += "；现行型号 {}".format(suggestion)
    anchor, span = item.locate_model() or (item.cells.get("model"), None)
    return [rules.issue(
        "L9", message=message,
        expected=suggestion or "现行命名编码", actual=actual,
        anchor=anchor,
        span=span, span_scope=SPAN_CELL, field="型号")]
