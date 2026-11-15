"""L2-L8：型号与描述的自洽性.

判据只有一条铁律：**双端都能确定才判红**。
  - 型号侧：容量段/台面码/材质段/防爆位，由通表反推的码表解码得到
  - 描述侧：量程 / 台面尺寸 / 材质 / 分度值 / 防爆，由 desclib 从描述正文取
两端都取到且冲突才报；任一端取不到、或描述本身含糊（同时写了碳钢和不锈钢）
就跳过——宁可漏判，不可误红，误报一次用户就不信这个功能了。
"""
import re

from COPA.apps.audit import claims as C
from COPA.apps.audit import modelspec
from COPA.apps.audit.desclib import (MTL_TEXT, desc_capacity, desc_capacity_span,
                                     desc_division, desc_division_kv,
                                     desc_division_span, desc_ex, desc_face,
                                     desc_face_span, desc_material,
                                     desc_material_span, desc_note_line_spans,
                                     desc_note_lines, material_kind)
from COPA.apps.audit.model import (KIND_BENCH, KIND_MODULE, KIND_NAMES,
                                   SCALE_KINDS)
from COPA.apps.audit.naming import norm, tokenize_models
from COPA.apps.audit.reader import kind_from_name

# 参与跨段比对的品类（名称与型号的品类必须一致）
_CROSS_KINDS = (SCALE_KINDS[0], SCALE_KINDS[1], "module", "truck")

# 「防爆」与「仪表」近邻出现才算声明防爆仪表（跨句/跨行不算）
RE_EX_INSTRUMENT = re.compile(r"防爆[^。\n]{0,12}仪表|仪表[^。\n]{0,12}防爆")

_EX_LEVEL_WORDS = ("IICT", "IB", "EX", "EXIA", "EXIA IIC", "DIP", "防爆")

# 供电声明（L22/L23/L24 判据）。供电方式三类（用户拍板口径）：
#   220VAC / 24VDC / 电池供电（防爆电源归入电池供电）——各自都有写法变体。
# 裸「24V」不算 DC（传感器激励电压太常见），裸「电池」不算电池供电
# （「无电池」是反例），必须带明确的供电字样才认。
_RE_AC_CLAIM = re.compile(r"AC\s*\d{3}|\d{3}\s*V\s*AC|220\s*V|380\s*V|110\s*V|交流",
                          re.IGNORECASE)
_RE_DC_CLAIM = re.compile(r"DC\s*\d{2,3}|\d{2,3}\s*V\s*DC|直流\s*\d{2,3}",
                          re.IGNORECASE)
_RE_BAT_CLAIM = re.compile(
    r"电池供电|内置电池|锂电池|充电电池|干电池|带电池(?!接口|仓)|含电池|电池另配|另配电池"
    r"|防爆电源|本安电源|battery", re.IGNORECASE)
# 电池来源说明：另配/不含/标配/内置/自带/选配……（「电池另配」与「内置电池」都算）
_RE_BAT_NOTE = re.compile(
    r"(?:另配|另购|不含|标配|内置|自带|随机|含|选配)[^，,；;.\n]{0,6}电池"
    r"|电池[^，,；;.\n]{0,4}(?:另配|另购|不含)"
    r"|built[\s-]*in\s*battery|battery\s*powered|battery[^.\n]{0,12}included",
    re.IGNORECASE)
_RE_CHARGER_NOTE = re.compile(r"充电器|charger", re.IGNORECASE)
_RE_EX_POWER = re.compile(r"防爆电源|本安电源|防爆电池", re.IGNORECASE)


def _supply_claim(desc: str):
    """描述 -> (供电类别, 命中原文, 区间)。类别：'ac' / 'dc' / 'bat' / None。
    同时命中多类（交直流两用等）视作含糊，返回 None 不猜。"""
    hits = []
    for kind, regex in (("bat", _RE_BAT_CLAIM), ("dc", _RE_DC_CLAIM),
                        ("ac", _RE_AC_CLAIM)):
        m = regex.search(desc)
        if m:
            hits.append((kind, m))
    if len(hits) != 1:
        return None, "", None
    kind, m = hits[0]
    return kind, m.group(0), (m.start(), m.end())


def check(item, catalog, rules):
    # 描述一致性两套引擎（config/audit_rules.json 的 desc_engine）：
    #   diff（默认）= 型号快照比对，L5/L6/L21/L22 这些逐条对齐的规则退场；
    #   rules       = 旧口径，保留用于对跑与回退。
    diff_mode = getattr(rules, "desc_engine", "rules") == "diff"
    # 有快照才交给 L25/L26；描述通表没收录的（FTBR 台秤等）退回旧规则，
    # 别让材质/防爆没人管——快照是替代，不是免责。
    has_snap = diff_mode and bool(item.model) and modelspec.get(
        catalog, getattr(item, "model_detail", "") or item.model) is not None
    issues = []
    if item.kind == KIND_MODULE:
        # 模块不走秤体描述一致性（系列存在性在 existence 已按系列口径放行）。
        # diff 引擎下由 L25/L26 按快照比对拉杆与材质，这里不再重复。
        return [] if has_snap else _module_variant(item, catalog, rules)

    # diff 引擎下供电争议统一由 L26 判（含描述里内嵌的仪表型号），L22 退场，
    # 否则同一件事会一红一红报两遍。
    issues.extend(_supply_checks(item, catalog, rules, skip_power=diff_mode))
    if item.kind not in SCALE_KINDS:
        return issues

    issues.extend(_category_conflict(item, catalog, rules))

    info = catalog.codes.decode(item.model) if item.model else None
    issues.extend(_remark_sensor(item, catalog, rules))
    issues.extend(_ex_instrument(item, catalog, rules))
    issues.extend(_bench_note_line(item, rules))
    issues.extend(_division_unit(item, rules))
    if info is None:
        return issues

    issues.extend(_capacity(item, info, catalog, rules))
    issues.extend(_face(item, info, catalog, rules))
    if not has_snap:
        issues.extend(_material(item, info, rules))
        issues.extend(_explosion_proof(item, info, catalog, rules))
    issues.extend(_missing_params(item, rules, skip_material=has_snap))
    issues.extend(_inner_conflict(item, catalog, rules))
    return issues


def _category_conflict(item, catalog, rules):
    """L2：名称写台秤、型号却是平台秤——客户按名称验收，型号错了就是发错货"""
    hit = catalog.lookup(item.model)
    model_kind = hit.kind
    # 只看「名称」列：型号/描述合并列里常出现 "Platform: 400*500" 这类参数名，
    # 拿整段判断品类会把它误读成平台秤
    name_kind = kind_from_name(item.name)
    if model_kind in _CROSS_KINDS and name_kind in _CROSS_KINDS and model_kind != name_kind:
        return [rules.issue(
            "L2", message="名称写「{}」，型号却是{}".format(
                item.name or item.label, KIND_NAMES.get(model_kind, model_kind)),
            expected="与名称一致的型号", actual=item.model,
            anchor=item.cells.get("model"))]
    return []


def _capacity(item, info, catalog, rules):
    """L3：型号容量段 vs 描述量程"""
    found = desc_capacity_span(item.desc)
    wanted = found[0] if found else None
    have = info.capacity_kg
    if wanted is None or have is None or have <= 0:
        return []
    if abs(wanted - have) <= max(0.001 * have, 0.01):
        return []

    suggestion = catalog.codes.suggest(item.model, capacity_kg=wanted,
                                       face_mm=info.face_mm)
    message = "型号容量段 {} 对应 {}kg，描述写 {}kg".format(
        info.cap_code, _num(have), _num(wanted))
    if suggestion:
        message += "；若以描述为准，型号应为 {}".format(suggestion)
    return [rules.issue(
        "L3", message=message,
        expected="{}kg（按描述）".format(_num(wanted)),
        actual="{}kg（按型号 {}）".format(_num(have), info.cap_code),
        anchor=item.cells.get("model"),
        span=(found[1], found[2]), field="量程")]


def _face(item, info, catalog, rules):
    """L4：型号台面码 vs 描述台面尺寸"""
    found = desc_face_span(item.desc)
    wanted = (found[0], found[1]) if found else None
    have = info.face_mm
    if wanted is None or have is None:
        return []
    if _eq_size(wanted, have):
        return []

    suggestion = catalog.codes.suggest(item.model, face_mm=wanted,
                                       capacity_kg=info.capacity_kg)
    message = "型号台面码 {} 对应 {}mm，描述写 {}*{}mm".format(
        info.face_code, info.face_text, wanted[0], wanted[1])
    if suggestion:
        message += "；若以描述为准，型号应为 {}".format(suggestion)
    return [rules.issue(
        "L4", message=message,
        expected="{}*{}mm（按描述）".format(wanted[0], wanted[1]),
        actual="{}mm（按型号 {}）".format(info.face_text, info.face_code),
        anchor=item.cells.get("model"),
        span=(found[2], found[3]), field="台面尺寸")]


def _material(item, info, rules):
    """L5：型号材质段 vs 描述第一处「材质：」。描述含糊时跳过。"""
    expected = MTL_TEXT.get(info.material)
    found = desc_material_span(item.desc)
    raw = found[0] if found else ""
    actual = material_kind(raw)
    if not expected or not actual or expected == "混合材质" or actual == "混合材质":
        return []          # 描述自己就没说清（如「碳钢，不锈钢台面」），不判
    if expected == actual:
        return []
    return [rules.issue(
        "L5", message="型号材质段 {} 为{}，描述写「{}」".format(
            info.material, expected, raw),
        expected="{}（按型号 {}）".format(expected, info.material),
        actual="{}（按描述）".format(raw),
        anchor=item.cells.get("desc"),
        span=(found[1], found[2]), field="材质")]



def _model_ex(item, info, catalog):
    """型号的防爆位：-> True(防爆) / False(非防爆) / None(判不了，不猜)

    台秤/平台秤/模块/汽车衡都有防爆位，别按品类豁免——按赋码规则读码：
      通表行有「防爆」列（0/1）就以它为准，通表是选型结果，比反推可靠；
      通表没有这一行，再看型号尾段：E=防爆，N/Y=非防爆（COPA A E/N、
      富林泰克 E/不跟后缀、Y 作选项位），尾段是别的选项码就说明没写防爆位。
    """
    row = catalog.scale_row(item.model) or {}
    flag = str(row.get("防爆", "") or "").strip()
    if flag in ("0", "1"):
        return flag == "1"

    # 模块：防爆位在型号串尾（富林泰克 `... EX`、COPA A `...-X`），而 item.model
    # 只保留到基系列（52-30M），所以要看原文——模块同样有防爆位，不能跳过。
    # 型号与描述常挤在同一格（阿根廷 C16），只有前几行是型号，按行看串尾：
    # 整格看尾巴会落到描述末字（"…；品牌：alwe"），防爆位就永远读成 False。
    if item.kind == KIND_MODULE:
        chunks = []
        for text in (item.model_text or item.name or "", item.desc or ""):
            chunks.extend([line.strip() for line in str(text).splitlines()[:2]
                           if line.strip()])
        for line in chunks:
            if re.search(r"(?:^|\s)EX$", line, re.I):
                return True
            if re.search(r"-X$", line, re.I):
                return True
        return False if chunks else None

    suffix = (getattr(info, "suffix", "") or "").strip().upper()
    if suffix == "E":
        return True
    if suffix in ("N", "Y"):
        return False
    if info is not None and len(getattr(info, "parts", [])) <= 4:
        # 四段式型号（FTPD-C-030-1515）不带尾段 = 非防爆（富林泰克「非防爆
        # 不跟后缀」）；COPA A台秤则必有 E/N，缺了就是写法不全，不硬判
        if info.family.startswith(("FTPD", "FTPE", "FTPH", "FTPL", "FTPF",
                                   "FTBR")):
            return False
    return None


def model_ex(item, info, catalog):
    """公开别名：抬头校验（L38）也按同一套规则读防爆位，别各写一份"""
    return _model_ex(item, info, catalog)


def _explosion_proof(item, info, catalog, rules):
    """L6：型号防爆位 vs 描述防爆要求"""
    if not item.desc:
        return []
    model_ex = _model_ex(item, info, catalog)
    if model_ex is None:
        return []                      # 型号读不出防爆位：不猜，交给 L1U/L1T
    text_ex = desc_ex(item.desc)
    if model_ex == text_ex:
        return []

    if model_ex and not text_ex:
        expected = "描述应注明防爆"
        actual = "型号为防爆型（尾码 {}），描述未体现".format(info.suffix or "E")
        # 描述整个没提防爆，没有可标的字——落点交回型号（染型号码），
        # 这条的改法就是补一句防爆说明或者换型号，标描述反而指错方向
        span = None
    else:
        expected = "型号应为防爆型（尾码 E）"
        candidate = item.model + "-E"
        if catalog.lookup(candidate).found:
            expected = "型号应为防爆型：{}".format(candidate)
        actual = "描述要求防爆，型号非防爆"
        claim = C.extract(item.desc).get(C.K_EX)
        span = claim.span if claim else None
    return [rules.issue(
        "L6", message="型号防爆标识与描述不一致：" + actual,
        expected=expected, actual=actual, anchor=item.cells.get("model"),
        span=span, field="防爆等级")]



def _missing_params(item, rules, skip_material: bool = False):
    """L7：秤体描述缺关键参数（量程/台面/材质/分度值），四项都查，一次报全。

    skip_material=True（diff 引擎）：材质缺项已由 L25 按快照口径报，这里让位，
    避免同一件事一个红一个黄。"""
    missing = []
    if desc_capacity(item.desc) is None:
        missing.append("量程")
    if desc_face(item.desc) is None:
        missing.append("台面尺寸")
    if not skip_material and not desc_material(item.desc):
        missing.append("材质")
    if desc_division(item.desc) is None:
        missing.append("分度值")
    if not missing:
        return []

    return [rules.issue(
        "L7", message="描述缺少：{}".format("、".join(missing)),
        expected="量程 / 台面尺寸 / 材质 / 分度值 四项齐全",
        actual="缺 " + "、".join(missing), missing=",".join(missing),
        anchor=item.cells.get("desc"))]


def _inner_conflict(item, catalog, rules):
    """L8：描述正文里的型号与型号列不是同一个（同品类才判，避免把配件型号当冲突）"""
    if not item.model or not item.desc:
        return []
    seen = {norm(item.model)}
    for token in tokenize_models(item.desc):
        key = norm(token)
        if key in seen:
            continue
        seen.add(key)
        hit = catalog.lookup(token)
        if not hit.found or hit.level == "typebatch":
            continue
        if hit.kind != item.kind:
            continue
        if hit.kind not in _CROSS_KINDS:
            continue
        return [rules.issue(
            "L8", message="描述正文出现另一个{}型号「{}」".format(
                KIND_NAMES.get(hit.kind, hit.kind), token),
            expected=item.model, actual=token,
            anchor=item.cells.get("desc"),
            span=((item.desc.find(token), item.desc.find(token) + len(token))
                  if item.desc.find(token) >= 0 else None),
            field="型号")]
    return []


def _remark_sensor(item, catalog, rules):
    """L12：描述声明了传感器，但全行找不到传感器型号（备注栏应为传感器型号
    的归宿；COPA 台秤输出口径就是传感器型号写入备注栏）。空缺格整格填黄。"""
    if item.kind != KIND_BENCH:
        return []
    if not re.search(r"传感器", item.desc or "", re.IGNORECASE):
        return []                       # 没声明传感器就无从缺起，不猜
    families = catalog.sensor_families()
    if families and _has_sensor_model(item.desc, families):
        return []                       # 型号写在描述里也认，信息在就不缺
    remark = (item.remark or "").strip()
    if families and _has_sensor_model(remark, families):
        return []
    declared = bool(families)           # 库里无传感器数据时保守不报
    if not declared:
        return []
    anchor = item.cells.get("remark") or item.cells.get("desc")
    return [rules.issue(
        "L12",
        message="描述声明了传感器但未写明具体型号（含备注栏）",
        expected="传感器型号写入备注栏（如 SLB-91-6kg）",
        actual="备注栏为空" if not remark else "备注栏：{}".format(remark[:40]),
        anchor=anchor)]


def _has_sensor_model(text: str, families) -> bool:
    upper = (text or "").upper()
    return any(fam in upper for fam in families)


def _ex_instrument(item, catalog, rules):
    """L13：描述声明防爆仪表，但写出的仪表型号是非防爆型（兰达案例：
    「防爆仪表FT-230（FT230HA012A）」，HA012A 防爆等级 0，台式非防爆）。"""
    if not item.desc:
        return []
    desc = item.desc
    for m in RE_EX_INSTRUMENT.finditer(desc):
        window = desc[m.start():min(len(desc), m.end() + 60)]
        for token in tokenize_models(window):
            row = catalog.instruments.get(token)
            if row is None:
                continue
            level = str(row.get("防爆等级", "")).strip()
            if _is_ex_level(level):
                return []               # 声明成立：写的就是防爆仪表
            example = _ex_example(catalog, row)
            message = "描述声明「防爆仪表」，但仪表型号 {} 为非防爆型".format(token)
            if str(row.get("安装方式", "")).strip():
                message += "（安装方式：{}，防爆等级：{}）".format(
                    row.get("安装方式").strip(), level or "无")
            if example:
                message += "；如 {}".format(example)
            # 型号在描述里的位置：从「防爆仪表」那处往后找，避免撞上开头的
            # 秤体型号（同一串型号可能前面又出现一次）
            at = desc.find(token, m.start())
            span = (at, at + len(token)) if at >= 0 else None
            return [rules.issue(
                "L13", message=message,
                expected="防爆型仪表（防爆等级非 0）",
                actual=token,
                anchor=item.cells.get("desc"),
                span=span, field="仪表型号")]
    return []


def _is_ex_level(level: str) -> bool:
    text = norm(level)
    if not text or text in ("0", "无", "NON-EX", "N"):
        return False
    return any(word in text for word in _EX_LEVEL_WORDS)


def _ex_example(catalog, row) -> str:
    """同系列里的防爆型号示例（最多给一个，帮助用户直接改对）"""
    family = str(row.get("family", "")).strip()
    if not family:
        return ""
    for model, peer in catalog.instruments.items():
        if model != row.get("model_full") and str(peer.get("family", "")).strip() == family \
                and _is_ex_level(str(peer.get("防爆等级", "")).strip()):
            return model
    return ""


def _bench_note_line(item, rules):
    """L14：台秤描述内出现「备注：」行——台秤默认仪表一体安装，备注行应省略。"""
    if item.kind != KIND_BENCH:
        return []
    found = desc_note_line_spans(item.desc or "")
    if not found:
        return []
    text, start, end = found[0]
    return [rules.issue(
        "L14",
        message="描述内出现备注行「{}」；台秤默认仪表一体安装，描述内的备注行应省略".format(
            text[:50]),
        expected="描述内无备注行（传感器型号写在备注栏）",
        actual=text[:60],
        anchor=item.cells.get("desc"),
        span=(start, end), field="备注行")]


def _division_unit(item, rules):
    """L15：台秤分度值以 kg 计，建议换算为 g（0.02kg -> 20g），口径对齐输出模板。"""
    if item.kind != KIND_BENCH:
        return []
    info = desc_division_span(item.desc or "")
    if info is None or info[1] != "kg" or info[0] >= 1:
        return []
    value = info[0]
    grams = value * 1000
    gram_text = str(int(grams)) if grams == int(grams) else str(grams)
    kg_text = str(int(value)) if value == int(value) else str(value)
    return [rules.issue(
        "L15",
        message="分度值 e=d={}kg，建议换算为 g（e=d={}g）".format(kg_text, gram_text),
        expected="分度值以 g 计（e=d={}g）".format(gram_text),
        actual="{}kg".format(kg_text),
        anchor=item.cells.get("desc"),
        span=(info[2], info[3]), field="分度值")]



def _module_variant(item, catalog, rules):
    """L21：模块型号带 L 后缀（水平拉杆变体）但描述未声明拉杆（样例客户案例：
    「52-30ML」的描述只写材质/防爆，没有「带水平拉杆」——带拉杆与不带拉杆
    是两种安装结构，照单发货到现场装不上）。只查型号→描述方向：
    描述提拉杆而型号不带 L 的写法未约定，不猜。"""
    if not item.model or not item.desc:
        return []
    # 描述只是型号串回显（汇总页聚合行：型号列/描述列同格，desc 即纯型号串）
    # 才跳过——拉杆声明以报价单明细描述为准，不重复报。但明细页「型号行+描述行」
    # 共存于同一格时 desc==model_text 且含中文描述，那不是回显，漏写要照报。
    if (norm(item.desc) == norm(item.model_text or "")
            and not re.search(r"[\u4e00-\u9fff]", item.desc)):
        return []
    series = catalog.module_series_hit(item.model)
    if not series:
        return []
    tail = norm(item.model)[len(norm(series)):]
    if "L" not in tail or "拉杆" in item.desc:
        return []
    anchor = item.cells.get("desc") or item.cells.get("model") or (item.row, 1)
    return [rules.issue(
        "L21",
        message="模块型号 {} 带 L 后缀（水平拉杆变体），描述未声明拉杆".format(item.model),
        expected="描述声明「带水平拉杆」",
        actual="描述未提及拉杆",
        anchor=anchor)]


def _supply_checks(item, catalog, rules, skip_power: bool = False):
    """供电三查（用户拍板口径：供电方式三类 220VAC / 24VDC / 电池供电，
    防爆电源归电池供电；台秤优先校验；防爆环境校验防爆电源）：

      L22 红：仪表型号的供电与描述声明不符（海斯福案例：FT210EA0A0000D
              尾缀 D 为 DC24V 供电，描述却写 220VAC——照单采购，到货烧表）
      L23 黄：选电池供电但未说明「电池是否另配 / 是否含充电器」；
              防爆环境还须说明防爆电源（本安电源）
      L24 红：台秤描述未声明供电方式（台秤默认电池供电，优先校验）
    都是提示性质，用户确认后忽略即不再报（ignored 通道）。
    """
    issues = []
    desc = item.desc or ""
    if not desc:
        return issues
    power_map = getattr(catalog, "instrument_power", None) or {}
    battery_set = getattr(catalog, "instrument_battery", None) or set()

    # 描述里第一个认得的仪表型号 -> 型号侧供电证据
    model_token, power = None, ""
    for token in tokenize_models(desc):
        p = power_map.get(norm(token))
        if p:
            model_token, power = token, p
            break
    bat_model = bool(model_token) and norm(model_token) in battery_set
    claim, claim_text, claim_span = _supply_claim(desc)

    # ---- L22：型号供电 vs 描述声明（diff 引擎下由 L26 接管）------------
    if model_token and claim and not skip_power:
        wrong = expected = ""
        if claim == "ac" and power == "dc":
            wrong = "描述写 {}（交流供电）".format(claim_text.upper())
            expected = "DC24V 供电（或改用尾缀 A 的 AC220V 型号）"
        elif claim == "dc" and power == "ac":
            wrong = "描述写 {}（直流供电）".format(claim_text.upper())
            expected = "AC220V 供电（或改用尾缀 D 的 DC24V 型号）"
        elif claim == "bat" and not bat_model:
            wrong = "描述写 {}（电池供电）".format(claim_text)
            expected = "选用带电池配置的仪表型号（或改回 220VAC 表述）"
        if wrong:
            issues.append(rules.issue(
                "L22",
                message="仪表 {} 的供电与描述不符：型号为 {}，{}".format(
                    model_token,
                    "DC24V 供电（尾缀 D）" if power == "dc"
                    else "AC220V 供电（尾缀 A）" if power == "ac"
                    else "无电池配置",
                    wrong),
                expected=expected,
                actual=claim_text,          # 纯 token，批阅端字符定位用
                anchor=item.cells.get("desc"),
                span=claim_span, field="供电方式"))

    # ---- L23：电池供电的选配事项 ----------------------------------------
    if claim == "bat" or bat_model:
        missing = []
        if not _RE_BAT_NOTE.search(desc):
            missing.append("电池是否需要另配")
        if not _RE_CHARGER_NOTE.search(desc):
            missing.append("是否包含充电器")
        if desc_ex(desc) and not _RE_EX_POWER.search(desc):
            missing.append("防爆电源（本安电源）说明")
        if missing:
            issues.append(rules.issue(
                "L23",
                message="选择电池供电时请说明：{}".format("、".join(missing)),
                expected="电池来源与充电器（防爆环境含防爆电源）均有交代",
                actual=claim_text or (model_token or ""),
                anchor=item.cells.get("desc"),
                span=claim_span if claim == "bat" else None, field="电池配置"))

    # ---- L24：台秤供电方式声明（台秤优先校验电池供电）--------------------
    if item.kind == KIND_BENCH and not claim and not bat_model:
        extra = ("；防爆环境请确认防爆电源（本安电源）"
                 if desc_ex(desc) else "")
        issues.append(rules.issue(
            "L24",
            message="台秤描述未声明供电方式（电池供电 / 220VAC）" + extra,
            expected="描述注明供电方式；电池供电须交代电池另配与充电器",
            actual="（未提及供电）",
            anchor=item.cells.get("desc")))
    return issues


def _eq_size(a, b) -> bool:
    return tuple(sorted(a)) == tuple(sorted(b))


def _num(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)
