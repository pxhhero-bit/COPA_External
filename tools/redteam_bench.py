# -*- coding: utf-8 -*-
"""台秤 pipeline 红队测试：从极限值/错误录入角度打链路，不改业务代码。

用法（用带 PySide6 的解释器，工作目录任意）：
    python tools/redteam_bench.py

覆盖 A~F 六组、28 条：
  A 量程边界      B 台面尺寸边界   C 品类/材质/品牌/防爆
  D 传感器选型    E 输出与一致性   F 契约健壮性

判定基准只取 data/ 通表与 ref/ 厂家常用秤台尺寸，不引用 library/ 参数
（该目录资料存在过期项，用作预期会把错的判成对的）。

结果三态：
  PASS    符合判定线
  FAIL    违反判定线（错配/崩溃/静默吞值）
  OBSERVE 行为未崩但业务口径需人工拍板
"""
import csv
import io
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_PARENT = os.path.dirname(ROOT)

if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RESULTS = []
_PARSER = None
_SERVICE = None
_SENSORS = None


# ---------- 基础设施 ----------

def parser():
    global _PARSER
    if _PARSER is None:
        from COPA.apps.Parser import Parser
        _PARSER = Parser()
    return _PARSER


def service():
    global _SERVICE
    if _SERVICE is None:
        from COPA.apps.Desk import EngineService
        _SERVICE = EngineService()
    return _SERVICE


def sensors_db():
    global _SENSORS
    if _SENSORS is None:
        from COPA.engine import engine
        _SENSORS = engine.DatabaseLoader(
            engine.resolver.rules, "FT").load_sensors()
    return _SENSORS


def rules():
    from COPA.engine import engine
    return engine.resolver.rules


def note(cid, status, detail=""):
    RESULTS.append((cid, status, detail))
    print("{:<8} {:<4} {}".format(status, cid, detail))


def build_entry(desc, item_type="台秤", **flags):
    parsed = parser().parse_quote_text(desc)
    data = parsed["data"]
    data["req_com1"] = data.get("req_com1") or parser().default_req_com1()

    entry = {
        "description": desc,
        "item_type": item_type,
        "quote_info": {"quote_id": 1, "quantity": 1},
        "onsite_service": False,
        "parsed": parsed,
        "Ex_P": False,
        "high_precision": False,
        "metrology": False,
        "digital": False,
    }
    entry.update(flags)
    return entry


def run_entry(entry):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        return service().run_batch([entry])[0]
    finally:
        sys.stdout = old


def run_one(desc, item_type="台秤", **flags):
    return run_entry(build_entry(desc, item_type, **flags))


def bench_of(res):
    rows = res.get("bench") or []
    return rows[0] if rows else None


def picked(res):
    bs = res.get("bench_sensor") or {}
    return bs.get("default")


def picked_name(res):
    row = picked(res)

    if not row:
        return ""

    return "{}-{}".format(row.get("family型号"), row.get("capacity容量"))


def target_range(res):
    evidence = (res.get("bench_diagnostic") or {}).get("evidence") or {}
    return evidence.get("target_range")


def bench_text(res):
    """用返回的整机行 + 防爆态生成报价备注文案，等价 Writer 路径"""
    from COPA.apps import Writer
    row = bench_of(res)

    if not row:
        return ""

    return Writer.bench_sensor_text({
        "type": "bench",
        "bench": row["具体型号"],
        "ex": row["防爆"] != "0",
    })


def parse_ok(res, expect_range, expect_sensor):
    """量程档 + 默认传感器双断言，返回 (ok, detail)"""
    if res.get("status") != "OK":
        return False, "status={} {}".format(res.get("status"), res.get("error") or "")
    rng = target_range(res)
    name = picked_name(res)

    if rng != expect_range:
        return False, "量程档 {}（期望 {}）".format(rng, expect_range)

    if name != expect_sensor:
        return False, "传感器 {}（期望 {}）".format(name or "空", expect_sensor)

    return True, "{}kg 档 -> {} SF={}".format(
        rng, name, (res.get("bench_sensor") or {}).get("SF"))


# ---------- A 量程边界 ----------

def group_a():
    desc = "台秤，量程{}，台面{}，{}，FT传感器，仪表FT230。"

    r = run_one(desc.format("0kg", "300x400", "碳钢"))
    err = r.get("error") or ""

    # 0 值被 Parser 丢弃后走缺参分支，错误文案用业务名「最大物料重量」
    if r.get("status") == "ERROR" and ("量程" in err or "重量" in err):
        note("A1", "PASS", err)
    else:
        note("A1", "FAIL", "0kg 未拒绝：status={} {}".format(r.get("status"), err))

    r = run_one(desc.format("-30kg", "300x400", "碳钢"))
    err = r.get("error") or ""

    if r.get("status") == "ERROR" and "不能为负" in err:
        note("A2", "PASS", err)
    elif r.get("status") == "ERROR":
        note("A2", "PASS", "已拒绝（文案未点明负数）：{}".format(err))
    else:
        note("A2", "FAIL", "负号被吞，仍选出 {}kg 档".format(target_range(r)))

    for cid, qty, size, rng, sensor in (
        ("A3", "3000g", "300x400", 3, "PC42-10"),
        ("A4", "0.006t", "300x400", 6, "PC42-20"),
        ("A5", "45kg", "400x500", 60, "PC60-100"),
    ):
        ok, detail = parse_ok(run_one(desc.format(qty, size, "碳钢")), rng, sensor)
        note(cid, "PASS" if ok else "FAIL", detail)

    r = run_one(desc.format("800kg", "600x800", "碳钢"))
    evidence = (r.get("bench_diagnostic") or {}).get("evidence") or {}

    if r.get("status") == "NO_MATCH" and evidence.get("max_range") == 600:
        note("A6", "PASS", "NO_MATCH，max_range=600：{}".format(
            evidence.get("reason")))
    else:
        note("A6", "FAIL", "status={} max_range={} {}".format(
            r.get("status"), evidence.get("max_range"), r.get("error") or ""))

    r = run_one(desc.format("1kg", "300x400", "碳钢"))
    rng = target_range(r)
    note("A7", "OBSERVE" if rng == 3 else "FAIL",
         "1kg 输入静默升到 {}kg 档（{}），返回里靠 target_range 才看得出".format(
             rng, picked_name(r)))


# ---------- B 台面尺寸边界 ----------

def group_b():
    base = "台秤，量程30kg，台面{}，碳钢，FT传感器，仪表FT230。"

    for cid, size, label in (
        ("B1", "0.3x0.4", "米制"),
        ("B2", "30x40cm", "cm 单侧单位"),
        ("B3", "300*400", "星号"),
        ("B4", "300 X 400", "大写X+空格"),
        ("B8", "3040", "紧凑四位数"),
        ("B9", "300400", "紧凑六位数"),
    ):
        r = run_one(base.format(size))
        row = bench_of(r)
        actual = (row or {}).get("台面尺寸")

        if r.get("status") == "OK" and actual == "300x400":
            note(cid, "PASS", "{}「{}」-> {}".format(label, size, actual))
        else:
            note(cid, "FAIL", "{}「{}」未归一为 300x400：status={} {}".format(
                label, size, r.get("status"), r.get("error") or actual or ""))

    r = run_one(base.format("1000x1000"))
    evidence = (r.get("bench_diagnostic") or {}).get("evidence") or {}

    if r.get("status") == "NO_MATCH" and evidence.get("available_sizes"):
        sizes = sorted(set(evidence.get("available_sizes") or []))
        note("B5", "PASS", "NO_MATCH，该档可选尺寸 {}".format(sizes))
    else:
        note("B5", "FAIL", "status={} {}".format(
            r.get("status"), r.get("error") or ""))

    r = run_one(base.format("300"))

    if r.get("status") == "ERROR" and "台面" in (r.get("error") or ""):
        note("B6", "PASS", r.get("error"))
    else:
        note("B6", "FAIL", "单边尺寸未报缺参：status={} {}".format(
            r.get("status"), r.get("error") or ""))

    r = run_one("台秤，量程600kg，台面240x300，碳钢，FT传感器，仪表FT230。")

    if r.get("status") == "NO_MATCH":
        note("B7", "PASS", "600kg@240x300 正确拒绝")
    else:
        note("B7", "FAIL", "600kg@240x300 竟选出 {}kg@{}".format(
            target_range(r), (bench_of(r) or {}).get("台面尺寸")))

    # B10/B11：拆出来的尺寸不存在时必须被拒。解析层只负责右侧对半拆分，
    # 台面是否真实存在由引擎的台面筛选裁决(报出该档可选尺寸)
    for cid, compact in (("B10", "300040"), ("B11", "30000400")):
        r = run_one(base.format(compact))
        row = bench_of(r)
        evidence = (r.get("bench_diagnostic") or {}).get("evidence") or {}

        if r.get("status") in ("ERROR", "NO_MATCH") and not row:
            note(cid, "PASS", "{} 正确拒绝：{}".format(
                compact, r.get("error") or evidence.get("reason")))
        else:
            note(cid, "FAIL", "{} 未被拒绝：status={} 台面={}".format(
                compact, r.get("status"), (row or {}).get("台面尺寸")))


# ---------- C 品类/材质/品牌/防爆 ----------

def group_c():
    desc = "台秤，量程30kg，台面300x400，碳钢，FT传感器，仪表FT230。"

    r = run_one(desc, high_precision=True)
    row = bench_of(r)

    if row and row.get("细分品种") == "高精度电子台秤":
        note("C1", "PASS", "复选框 high_precision -> 高精度电子台秤")
    else:
        note("C1", "FAIL", "细分品种={} status={}".format(
            (row or {}).get("细分品种"), r.get("status")))

    r = run_one(desc, Ex_P=True)
    row = bench_of(r)
    sensor = picked(r) or {}
    text = bench_text(r)

    if (row and row.get("防爆") != "0"
            and sensor.get("EX_level") not in (None, "0")
            and " EX" in text):
        note("C2", "PASS", "复选框 Ex_P -> 防爆整机 + {} + 备注「{}」".format(
            sensor.get("EX_level"), text))
    else:
        note("C2", "FAIL", "整机防爆={} 传感器EX={} 备注={}".format(
            (row or {}).get("防爆"), sensor.get("EX_level"), text))

    r = run_one("台秤，量程30kg，台面300x400，304不锈钢，FT传感器，仪表FT230。")
    row = bench_of(r)

    if row and row.get("材质") in ("S", "HS"):
        note("C3", "PASS", "304不锈钢 -> 材质 {}".format(row.get("材质")))
    else:
        note("C3", "FAIL", "status={} 材质={} {}".format(
            r.get("status"), (row or {}).get("材质"), r.get("error") or ""))

    r = run_one("台秤，量程30kg，台面300x400，CS，FT传感器，仪表FT230。")

    if r.get("status") == "NO_MATCH":
        note("C4", "PASS", "混合材质无对应台秤，正确拒绝")
    else:
        note("C4", "FAIL", "混合材质竟选出 {} 材质整机".format(
            (bench_of(r) or {}).get("材质")))

    r = run_one("台秤，量程30kg，台面300x400，碳钢，仪表FT230。")

    if r.get("status") == "ERROR" and "品牌" in (r.get("error") or ""):
        note("C5", "PASS", r.get("error"))
    else:
        note("C5", "FAIL", "未填传感器品牌仍通过：status={} {}".format(
            r.get("status"), r.get("error") or picked_name(r)))

    r = run_one("台秤，量程30kg，台面300x400，碳钢，AW传感器，仪表AW-220。")
    row = bench_of(r)
    text = bench_text(r)
    bs = r.get("bench_sensor") or {}
    empty = not bs.get("candidates")

    if row and row.get("品牌") == "AW" and text == "" and empty:
        note("C6", "PASS", "AW 整机 {}，传感器留空（不套 FT 型号）".format(
            row["具体型号"]))
    else:
        note("C6", "FAIL", "整机品牌={} 候选={} 备注={}".format(
            (row or {}).get("品牌"), len(bs.get("candidates") or []), repr(text)))

    r = run_one("台秤，量程30kg，台面300x400，碳钢，AW传感器，仪表FT230。")
    row = bench_of(r)
    ctrls = r.get("controller") or []

    if row and row.get("品牌") == "AW" and ctrls:
        note("C7", "PASS", "AW 秤体 + FT 仪表可混搭，仪表 {} 项".format(len(ctrls)))
    else:
        note("C7", "FAIL", "整机品牌={} 仪表{}项 status={}".format(
            (row or {}).get("品牌"), len(ctrls), r.get("status")))

    r = run_one("台秤，量程30kg，台面300x400，碳钢，FT传感器，仪表XYZ999。")
    ctrls = r.get("controller") or []
    reason = ((r.get("bench_diagnostic") or {}).get("evidence") or {}).get("reason") or ""

    if r.get("status") == "NO_MATCH" and not ctrls:
        note("C8", "PASS", "status=NO_MATCH，仪表 0 项；原因：{}".format(
            reason or "(未给出)"))
    else:
        note("C8", "FAIL", "不存在的仪表仍被放行：status={} 仪表{}项".format(
            r.get("status"), len(ctrls)))


# ---------- D 传感器选型边界 ----------

def group_d():
    from COPA.engine import engine

    res = engine.select_bench_sensors(
        {"品牌": "FT", "材质": "S", "量程": 3, "台面尺寸": "600x800"},
        sensors_db(), False, rules())
    names = ["{}-{}".format(c["family型号"], c["capacity容量"])
             for c in res["candidates"]]

    if "PC6-10" in names:
        note("D1", "FAIL", "3kg 台面 600x800 仍给出 PC6-10（台面上限失效）")
    elif not names:
        note("D1", "OBSERVE", "候选为空：{}".format(res.get("reason")))
    else:
        note("D1", "PASS", "无 PC6-10，候选 {}（flag={}）".format(
            names, res.get("flag")))

    r = run_one("台秤，量程600kg，台面600x800，不锈钢，FT传感器，仪表FT230。")
    name = picked_name(r)
    flag = (r.get("bench_sensor") or {}).get("flag")

    if name == "PCB-1000":
        note("D2", "PASS", "600kg 不锈钢 -> PCB-1000（{}）".format(flag))
    elif not name:
        note("D2", "OBSERVE", "候选为空：{}".format(
            (r.get("bench_sensor") or {}).get("reason")))
    else:
        note("D2", "FAIL", "600kg 不锈钢 -> {}（{}），疑似超/欠配".format(name, flag))

    r = run_one("台秤，量程15kg，台面240x300，不锈钢，FT传感器，仪表FT230。")
    name = picked_name(r)
    flag = (r.get("bench_sensor") or {}).get("flag")

    if name == "PC6-50" and flag == "over":
        note("D3", "PASS", "15kg 不锈钢 -> PC6-50，flag=over（已登记例外）")
    else:
        note("D3", "FAIL", "15kg 不锈钢 -> {} flag={}".format(name or "空", flag))

    r = run_one("台秤，量程30kg，台面400x500，碳钢，FT传感器，仪表FT230。")
    names = ["{}-{}".format(c["family型号"], c["capacity容量"])
             for c in ((r.get("bench_sensor") or {}).get("candidates") or [])]

    if picked_name(r) == "PC60-50" and not any(n.startswith("PC46") for n in names):
        note("D4", "PASS", "30kg@400x500 默认 PC60-50，PC46 已被台面上限剔除")
    else:
        note("D4", "FAIL", "默认={} 候选={}".format(picked_name(r) or "空", names))

    r = run_one("台秤，量程3kg，台面300x400，碳钢，FT传感器，仪表FT230。",
                Ex_P=True)
    sensor = picked(r) or {}

    if picked_name(r) == "PC42-10" and sensor.get("EX_level") not in (None, "0"):
        note("D5", "PASS", "3kg 防爆 -> PC42-10（{}）".format(sensor.get("EX_level")))
    else:
        note("D5", "FAIL", "3kg 防爆 -> {} EX={}".format(
            picked_name(r) or "空", sensor.get("EX_level")))

    res = engine.select_bench_sensors(
        {"品牌": "FT", "材质": "C", "量程": 120, "台面尺寸": "500x600"},
        sensors_db(), False, rules())
    default = res.get("default") or {}

    if (default.get("family型号"), default.get("capacity容量")) == ("PC60", 200):
        note("D6", "PASS", "120kg（通表无此档）-> PC60-200，就近 2.0 生效 SF={}".format(
            res.get("SF")))
    else:
        note("D6", "FAIL", "120kg -> {}-{} SF={}".format(
            default.get("family型号"), default.get("capacity容量"), res.get("SF")))


# ---------- E 输出与一致性 ----------

def _read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    cells = []

    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for value in row:
                if value is not None:
                    cells.append(str(value))

    return cells


def group_e():
    from COPA.apps import Writer

    items = [
        {"type": "bench", "bench": "FTBR-C-003-3040", "controller": "FT-230",
         "ex": False, "qty": 1},
        {"type": "bench", "bench": "FTBR-C-060-4050", "controller": "FT-230",
         "ex": False, "qty": 1},
        {"type": "bench", "bench": "FTBR-C-600-5060", "controller": "FT-230",
         "ex": False, "qty": 1},
        {"type": "platform", "platform": "FTPD-C-003-0606-N",
         "controller": "FT-230", "ex": False, "qty": 1, "jbox": "KE-4"},
    ]
    out_dir = tempfile.mkdtemp(prefix="redteam_bench_")
    path = os.path.join(out_dir, "multi.xlsx")

    try:
        Writer.build_quote(items, out_path=path, lang="zh")
        cells = _read_xlsx(path)
        joined = "\n".join(cells)
        models = sum(joined.count(m) for m in (
            "FTBR-C-003-3040", "FTBR-C-060-4050", "FTBR-C-600-5060",
            "FTPD-C-003-0606-N"))
        totals = sum(1 for c in cells if c.startswith("价税合计"))
        remarks = sum(1 for c in cells if "kg-C3" in c)

        if models >= 4 and totals == 1 and remarks == 3:
            note("E1", "PASS", "4 条整机 + 合计 1 处 + 台秤备注 3 处")
        else:
            note("E1", "FAIL", "整机命中 {} 处 / 合计 {} 处 / 备注 {} 处".format(
                models, totals, remarks))
    except Exception as err:
        note("E1", "FAIL", "出单异常：{}".format(err))
        traceback.print_exc()

    path2 = os.path.join(out_dir, "same.xlsx")
    same = [dict(items[0]) for _ in range(2)]

    try:
        Writer.build_quote(same, out_path=path2, lang="zh")
        cells = _read_xlsx(path2)
        count = "\n".join(cells).count("FTBR-C-003-3040")

        if count == 2:
            note("E2", "PASS", "同型号 2 条 -> 2 行（不合并/不覆盖）")
        else:
            note("E2", "FAIL", "同型号出现 {} 次".format(count))
    except Exception as err:
        note("E2", "FAIL", "出单异常：{}".format(err))

    text = Writer.bench_sensor_text({
        "type": "bench", "bench": "AWBR-C-030-3040", "ex": False})

    if text == "":
        note("E3", "PASS", "AW 台秤备注为空串（非 None/-）")
    else:
        note("E3", "FAIL", "AW 台秤备注 = {!r}".format(text))

    rows = list(csv.DictReader(open(
        os.path.join(ROOT, "data", "台秤通表.csv"), encoding="utf-8-sig")))
    from COPA.engine import engine
    db = sensors_db()
    bad = []

    for row in rows:
        for ex in (False, True):
            # select_bench_sensors 吃的是 engine 行模型(键「量程」)，
            # 通表列名是「kg量程」，此处按契约映射，不是业务差异
            default = engine.select_bench_sensors(
                {"品牌": row["品牌"], "材质": row["材质"],
                 "量程": row["kg量程"], "台面尺寸": row["台面尺寸"]},
                db, ex, rules()).get("default")
            text = Writer.bench_sensor_text(
                {"type": "bench", "bench": row["具体型号"], "ex": ex})

            if default is None:
                if text:
                    bad.append((row["具体型号"], ex, "空选型却有文案", text))
                continue

            prefix = "{}-{}kg".format(
                default["family型号"], default["capacity容量"])

            if not text.startswith(prefix):
                bad.append((row["具体型号"], ex, "型号不一致", text))
            elif ((" EX" in text) != bool(ex)):
                bad.append((row["具体型号"], ex, "EX 后缀不一致", text))

    if bad:
        note("E4", "FAIL", "{} 处不一致，前 3：{}".format(len(bad), bad[:3]))
    else:
        note("E4", "PASS", "通表 {} 行 × 2 防爆态，engine 与 Writer 全一致".format(
            len(rows)))


# ---------- F 契约健壮性 ----------

def group_f():
    from COPA.engine import engine

    entry = build_entry("台秤，量程30kg，台面300x400，碳钢，FT传感器，仪表FT230。")
    entry.pop("Ex_P", None)
    r = run_entry(entry)

    if r.get("status") == "ERROR":
        note("F1", "PASS", "缺 Ex_P 键 -> ERROR：{}".format(r.get("error")))
    else:
        note("F1", "FAIL", "缺键未转 ERROR：status={}".format(r.get("status")))

    res = engine.select_bench_sensors(
        {"品牌": "FT", "材质": "C", "量程": 30, "台面尺寸": "300x400"},
        [], False, rules())

    if not res["candidates"] and res.get("reason"):
        note("F2", "PASS", "空传感器库 -> 候选空 + reason「{}」".format(
            res["reason"]))
    else:
        note("F2", "FAIL", "空库仍返回候选 {}".format(len(res["candidates"])))

    res = engine.select_bench_sensors(
        {"品牌": "FT", "材质": "C", "量程": 30, "台面尺寸": "300x400"},
        sensors_db(), False, {})

    if not res["candidates"] and res.get("reason"):
        note("F3", "PASS", "缺 bench_sensor_rules -> 候选空 + reason「{}」".format(
            res["reason"]))
    else:
        note("F3", "FAIL", "缺配置仍返回候选 {}".format(len(res["candidates"])))

    desc = "台秤，量程30kg，台面300x400，碳钢，FT传感器，仪表FT230。"
    snaps = []

    for _ in range(3):
        res = run_one(desc)
        bs = res.get("bench_sensor") or {}
        snaps.append((
            picked_name(res),
            tuple((c["family型号"], c["capacity容量"], c["SF"], c["flag"])
                  for c in (bs.get("candidates") or [])),
        ))

    if len(set(snaps)) == 1:
        note("F4", "PASS", "同输入 3 次结果一致（{} 候选）".format(
            len(snaps[0][1])))
    else:
        note("F4", "FAIL", "3 次结果不一致")


# ---------- 主流程 ----------

GROUPS = [
    ("A 量程边界", group_a),
    ("B 台面尺寸边界", group_b),
    ("C 品类/材质/品牌/防爆", group_c),
    ("D 传感器选型", group_d),
    ("E 输出与一致性", group_e),
    ("F 契约健壮性", group_f),
]


def main():
    print("=" * 78)
    print("台秤 pipeline 红队测试")
    print("=" * 78)

    for title, fn in GROUPS:
        print("\n--- {} ---".format(title))
        try:
            fn()
        except Exception:
            note(title.split()[0], "FAIL", "组内异常：{}".format(
                traceback.format_exc(limit=1).strip().splitlines()[-1]))

    stat = {}

    for _, status, _ in RESULTS:
        stat[status] = stat.get(status, 0) + 1

    print("\n" + "=" * 78)
    print("合计 {} 条：{}".format(
        len(RESULTS),
        " / ".join("{} {}".format(k, v) for k, v in sorted(stat.items()))))
    print("=" * 78)

    fails = [cid for cid, status, _ in RESULTS if status == "FAIL"]

    if fails:
        print("FAIL 清单：{}".format("、".join(fails)))

    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
