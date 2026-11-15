# -*- coding: utf-8 -*-
"""COPA 基线自检：改动前后跑一遍，确认没有把原有功能改坏。

用法（用带 PySide6 的解释器）：
    python tests/test_baseline.py

覆盖四层：
  1. 语法   —— 全量 py 文件编译
  2. 导入   —— 各业务模块可正常 import（早发现循环导入/路径问题）
  3. 界面   —— 主窗口可构造（离屏，不弹窗）
  4. 选型   —— Desk 录入 → Parser → engine 的真实链路，断言选出型号

退出码 0 表示全部通过；任一失败打印原因并返回 1。
不依赖 pytest，纯标准库，方便在源码目录直接跑。
"""
import compileall
import importlib
import io
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_PARENT = os.path.dirname(ROOT)

if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

# 离屏渲染：CI 或无显示环境下也不弹窗
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CHECKS = []


def check(name):
    """注册一项检查：只登记，全部登记完再由 main() 依次执行，
    保证被测函数（如 _run_one）在执行时已完成定义"""

    def wrap(fn):
        _CHECKS.append((name, fn))
        return fn

    return wrap


@check("语法：全量 py 编译")
def _compile():
    ok = compileall.compile_dir(ROOT, quiet=2, legacy=False)

    if not ok:
        raise RuntimeError("存在语法错误的 py 文件")


@check("导入：业务模块")
def _imports():
    for name in (
        "COPA.main",
        "COPA.apps.Desk", "COPA.apps.Parser", "COPA.apps.SyncParser",
        "COPA.apps.Checklist", "COPA.apps.Writer", "COPA.apps.Snapshot",
        "COPA.apps.audit", "COPA.apps.MultiCombo",
        "COPA.apps.version",
        "COPA.engine.engine",
    ):
        importlib.import_module(name)


@check("界面：主窗口构造")
def _gui():
    from PySide6.QtWidgets import QApplication

    from COPA.main import Commander

    app = QApplication.instance() or QApplication([])
    win = Commander()

    if "Untitled (1)" not in win._projects:
        raise RuntimeError("默认项目未创建")

    win.close()
    app.processEvents()


@check("选型：模块品类端到端")
def _engine_module():
    text = "FT模块，碳钢，4支点，料重5吨，皮重450公斤。仪表3306，PN通讯。"
    result = _run_one("称重模块", text)

    if result.get("status") != "OK":
        raise RuntimeError("选型未通过：{}".format(result.get("error")))

    candidates = result.get("module") or []

    if not candidates:
        raise RuntimeError("未返回模块选型结果")

    first = candidates[0]
    model = first["module"]["module模块型号"]
    controller = (result.get("controller") or [{}])[0].get("详细型号")

    if not model:
        raise RuntimeError("模块型号为空")

    if not controller:
        raise RuntimeError("未选出仪表")

    print("       模块={} 传感器={} 仪表={}".format(
        model, first["sensor"]["family型号"], controller))


@check("报价：台秤整机行与模板路由")
def _writer_bench():
    """台秤输出：分度值按 g、备注列带传感器型号+Y值；秤类多项目走单项目模板，
    称重模块多项目才走多项目模板"""
    import tempfile

    import openpyxl

    from COPA.apps import Writer

    bench = {"type": "bench", "controller": "FT230NA002B",
             "controller_install": "立杆支架", "ex": True, "qty": 1}
    items = [dict(bench, quote_id=1, bench="FTBR-HS-003-2430"),
             dict(bench, quote_id=2, bench="FTBR-HS-060-6080")]

    if Writer._use_multi_template(items):
        raise RuntimeError("台秤多项目不应走多项目模板")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bench.xlsx")
        Writer.build_quote(items, brand="COPA B", lang="zh", out_path=path)
        ws = openpyxl.load_workbook(path).active
        assert ws is not None
        descs, remarks = [], []

        for r in range(1, ws.max_row + 1):
            name = str(ws.cell(row=r, column=2).value or "")

            if name != "电子台秤":
                continue

            descs.append(str(ws.cell(row=r, column=3).value or ""))
            remarks.append(str(ws.cell(row=r, column=8).value or ""))

    if len(descs) != 2:
        raise RuntimeError("台秤明细行数应为2，实际{}".format(len(descs)))

    if "分度值e=d=0.5g" not in descs[0] or "分度值e=d=10g" not in descs[1]:
        raise RuntimeError("台秤分度值未按 g 输出：{}".format(descs))

    if remarks[0] != "PC6-10kg-C3 EX Y=12500" or remarks[1] != "PCB-100kg-C3 EX Y=12500":
        raise RuntimeError("台秤备注列传感器/Y值不符：{}".format(remarks))

    model, desc = Writer.lookup_module("52-30M", "CS", "SB14", 227, True,
                                       y=11500, accuracy="C3")
    module = {"type": "module", "qty": 1, "ex": True, "digital": False,
              "module": (model, desc), "jbox": "KE-4",
              "controller": "FT230NA002B", "support": 4, "accessories": []}

    if not Writer._use_multi_template(
            [dict(module, quote_id=1), dict(module, quote_id=2)]):
        raise RuntimeError("称重模块多项目应走多项目模板")

    print("       台秤备注={} / {}".format(remarks[0], remarks[1]))


@check("报价：平台秤与台秤材质文案不通用")
def _writer_material_text():
    """同一个 S/C 代码，两种机型的「1.材质：」写法不同——平台秤是花纹钢台面
    （碳钢）或台面喷砂/光面板（不锈钢），台秤是花纹钢台面/拉丝面罩。

    这两套以前共用过一份台秤措辞，导致平台秤报价单的材质行一直是错的，
    所以单独立一条锁住，避免以后又被合并回一张表。
    """
    from COPA.apps.Writer import build_scale_desc

    def mtl_line(ptype, model):
        item = {"type": ptype, ptype: model, "ex": False}
        lines = [l for l in build_scale_desc(item).split("\n")
                 if l.startswith("1.材质")]
        return lines[0] if lines else ""

    plat_c = mtl_line("platform", "FTPD-C-003-0606-N")
    plat_s = mtl_line("platform", "FTPD-S-003-0606-N")
    bench_s = mtl_line("bench", "FTBR-S-003-2430")

    if "花纹钢台面" not in plat_c:
        raise RuntimeError("平台秤碳钢文案不符：{}".format(plat_c))

    if "台面喷砂/光面板" not in plat_s:
        raise RuntimeError("平台秤不锈钢文案不符：{}".format(plat_s))

    if "拉丝面罩" in plat_s:
        raise RuntimeError("平台秤套用了台秤文案：{}".format(plat_s))

    if "拉丝面罩" not in bench_s:
        raise RuntimeError("台秤文案被改成平台秤口径：{}".format(bench_s))

    print("       平台秤S={} / 台秤S={}".format(plat_s, bench_s))


@check("报价：平台秤传感器与仪表行按品牌区分")
def _writer_scale_sensor_text():
    """平台秤第 4 行按品牌分两套（对照 ref/01 COPA A、ref/02 COPA B 模板）：

    - COPA B(flintec)：原装进口 + 17-4PH，防护等级按传感器家族取**一档**：
      SLB/SB5 -> IP67，SB14/RC3 -> IP68（水深2m）/IP69K，SB8 -> IP68（水深2m）；
    - COPA A(alwe)：只写材质，材质选项随台面材质不同；
    - 品牌按条目 m_brand 映射：COPA B抬头下报 AW 秤，品牌与文案都得写 alwe；
    - 防爆机型：两家证书写法不同（ⅡC/T4 与 IIC/T6,T5），不能互相套用。

    第 6 行（台秤第 5 行）仪表：型号用全角括号，描述整段进括号，品牌在括号外。
    台秤第 4 行普通机型也必须是「称重传感器」而不是「传感器」。
    """
    from COPA.apps.Writer import _ft_sensor_spec, build_scale_desc

    def lines(ptype, model, ex, header, m_brand=None):
        item = {"type": ptype, ptype: model, "ex": ex,
                "controller": "FT230NA002B", "controller_install": "立杆安装，"}

        if m_brand:
            item["m_brand"] = m_brand

        return build_scale_desc(item, header_brand=header).split("\n")

    def pick(rows, prefix):
        return next((l for l in rows if l.startswith(prefix)), "")

    def need(text, token, label):
        if token not in text:
            raise RuntimeError("{} 缺 {}：{}".format(label, token, text))

    # COPA B + SLB（碳钢行的第一支传感器）：只该写 IP67 一档
    ft = lines("platform", "FTPD-C-003-0606-N", False, "COPA B")
    ft_sensor = pick(ft, "4.")

    for token in ("传感器原装进口", "17-4PH不锈钢", "防护等级：IP67"):
        need(ft_sensor, token, "COPA B SLB 传感器文案")

    if "IP69K" in ft_sensor:
        raise RuntimeError("SLB 只该写 IP67，不该并列 IP69K：{}".format(ft_sensor))

    # SB14（H 系列行）：IP68（水深2m）/IP69K
    hc = pick(lines("platform", "FTPD-HC-003-0606-N", False, "COPA B"), "4.")
    need(hc, "IP68（水深2m）/IP69K", "COPA B SB14 传感器文案")

    # 三个家族口径（SB8 通表暂无平台秤行，直接验函数）
    for sensor, want in (("SLB-227kg", "IP67"), ("SB5-100kg", "IP67"),
                         ("SB14-227kg", "IP68（水深2m）/IP69K"),
                         ("RC3-100kg", "IP68（水深2m）/IP69K"),
                         ("SB8-50kg", "IP68（水深2m）")):
        need(_ft_sensor_spec(sensor), "防护等级：" + want,
             "防护等级 {}".format(sensor))

    if "IP69K" in _ft_sensor_spec("SB8-50kg"):
        raise RuntimeError("SB8 不该带 IP69K：{}".format(_ft_sensor_spec("SB8-50kg")))

    # COPA B抬头 + m_brand=AW：品牌与文案都跟 AW 走
    aw_under_qs = pick(
        lines("platform", "AWPD-C-003-0606-N", False, "COPA B", "AW"), "4.")
    need(aw_under_qs, "品牌：alwe", "COPA B抬头下的 AW 秤")

    if "17-4PH" in aw_under_qs:
        raise RuntimeError("AW 秤套用了 flintec 文案：{}".format(aw_under_qs))

    aw_s = pick(lines("platform", "AWPD-S-003-0606-N", False, "COPA A"), "4.")
    aw_c = pick(lines("platform", "AWPD-C-003-0606-N", False, "COPA A"), "4.")

    if "材质：不锈钢" not in aw_s or "合金钢" in aw_s:
        raise RuntimeError("COPA A不锈钢传感器文案不符：{}".format(aw_s))

    if "材质：合金钢/不锈钢" not in aw_c:
        raise RuntimeError("COPA A碳钢传感器文案不符：{}".format(aw_c))

    if "原装进口" in aw_c:
        raise RuntimeError("COPA A套用了COPA B文案：{}".format(aw_c))

    ft_ex = pick(lines("platform", "FTPD-C-003-0606-E", True, "COPA B"), "4.")
    aw_ex = pick(lines("platform", "AWPD-C-003-0606-E", True, "COPA A"), "4.")

    if "防爆传感器" not in ft_ex or "Ex ia IIC T6/T5" not in ft_ex:
        raise RuntimeError("COPA B防爆传感器文案不符：{}".format(ft_ex))

    # 两家的证书不同：COPA A T4、COPA B T6/T5；气体组别写成 II / Ⅱ 都算（模板用
    # 罗马数字、编辑器常把它归一成两个 I），所以只锁温度组别，不锁那个字符。
    if "防爆传感器" not in aw_ex or "T4 Ga" not in aw_ex:
        raise RuntimeError("COPA A防爆传感器文案不符：{}".format(aw_ex))

    if "T6/T5" in aw_ex:
        raise RuntimeError("COPA A防爆等级套用了COPA B写法：{}".format(aw_ex))

    ind = pick(ft, "6.")

    if "FT-230（FT230NA002B）*1（" not in ind:
        raise RuntimeError("仪表型号/描述括号不符：{}".format(ind))

    if not ind.endswith("；品牌：flintec"):
        raise RuntimeError("仪表品牌应落在括号外：{}".format(ind))

    bench = pick(lines("bench", "FTBR-C-003-2430", False, "COPA B"), "4.")

    if not bench.startswith("4.称重传感器*1"):
        raise RuntimeError("台秤传感器行不符：{}".format(bench))

    # ---- 英文块：逐条对应中文口径（lang=en 返回 中文块+英文块，只取英文段） ----
    def en_lines(ptype, model, ex, header, m_brand=None):
        item = {"type": ptype, ptype: model, "ex": ex,
                "controller": "FT230NA002B", "controller_install": "立杆安装，"}

        if m_brand:
            item["m_brand"] = m_brand

        rows = build_scale_desc(item, lang="en", header_brand=header).split("\n")
        start = next((i for i, l in enumerate(rows) if l.startswith("Model:")), 0)
        return rows[start:]

    en_plat = en_lines("platform", "FTPD-C-003-0606-N", False, "COPA B")
    need(pick(en_plat, "1. Material"), "tread plate deck / plain deck",
         "英文平台秤碳钢材质")
    need(pick(en_plat, "2."), "2. Deck size:", "英文平台秤台面行")
    need(pick(en_plat, "4."),
         "4. Load cells SLB-227kg*4 (imported, material: 17-4PH stainless steel",
         "英文平台秤传感器行")

    en_bench = en_lines("bench", "FTBR-C-003-2430", False, "COPA B")
    en_bench_mtl = pick(en_bench, "1. Material")
    need(en_bench_mtl, "brushed cover", "英文台秤碳钢材质")

    if "tread plate" in en_bench_mtl:
        raise RuntimeError("台秤英文材质套用了平台秤台面写法：{}".format(en_bench_mtl))

    # 台面行两种机型统一 Deck size，不再区分 dimensions/size
    if "Deck dimensions" in "\n".join(en_bench):
        raise RuntimeError("英文台面行应统一 Deck size")

    need(pick(en_bench, "2."), "2. Deck size:", "英文台秤台面行")
    need(pick(en_bench, "4."), "4. Load cell*1", "英文台秤传感器行")

    en_ex_rows = en_lines("platform", "FTPD-C-003-0606-E", True, "COPA B")
    en_ex = pick(en_ex_rows, "4.")
    need(en_ex, "4. Ex-proof load cells", "英文防爆传感器行")
    need(en_ex, "ex-proof rating:", "英文防爆等级")
    need(pick(en_ex_rows, "6."), "6. Ex-proof indicator", "英文防爆仪表行")

    if "Explosion-proof" in "\n".join(en_ex_rows):
        raise RuntimeError("英文防爆仍写作 Explosion-proof：{}".format(
            "\n".join(en_ex_rows)))

    print("       COPA B={} | COPA AC={}".format(ft_sensor, aw_c))


@check("清单：项目字典带传感器品牌")
def _checklist_m_brand():
    """Writer 的平台秤传感器行按 m_brand 映射品牌，清单必须把它写进项目字典；
    否则整条链路只剩通表品牌可用，COPA B抬头下报 AW 秤会写错品牌与文案。"""
    from PySide6.QtWidgets import QApplication

    from COPA.apps.Checklist import QuoteListItem

    QApplication.instance() or QApplication([])
    item = QuoteListItem()
    item.label_ID.setText("1")
    item._params = {"m_brand": "AW"}
    item._result = {"item_type": "platform", "platform": []}
    item.comboBox.setCurrentText("平台秤")
    project, _warnings = item.build_item()

    if project.get("m_brand") != "AW":
        raise RuntimeError("项目字典未带 m_brand：{}".format(project))

    print("       project.m_brand = AW")


@check("数据：台秤传感器按品牌分流")
def _bench_sensor_coverage():
    """台秤传感器靠 engine 现算(防爆->品牌+材质fence->台面->容量倍率)，
    这里按通表逐型号校验三件事：
    1. FT 型号必须选得出来(备注列不能空)；
    2. AW 目前无单点式数据，允许为空——一旦有值就不得是 FT 系列(防跨品牌错配)；
    3. 非厂家白名单(override)的结果，容量倍率必须落在 1.3~2.5 之间。"""
    import csv

    from COPA.apps import Writer

    path = os.path.join(Writer.DATA_DIR, "台秤通表.csv")
    rules = __import__("COPA.engine.engine", fromlist=["engine"]).resolver.rules
    config = rules["bench_sensor_rules"]
    low = float(config["capacity_ratio"]["tolerant_min"])
    high = float(config["capacity_ratio"]["max"])
    allowed = {fam for brand in config["family_fence"].values()
               for groups in brand.values() for group in groups
               for fam in group}

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    missing, cross, out_of_range, combos = [], [], [], set()

    for row in rows:
        model = row["具体型号"].strip()
        brand = row["品牌"].strip().upper()
        combos.add((brand, row["材质"], row["kg量程"], row["台面尺寸"]))

        for ex in (False, True):
            item = {"type": "bench", "bench": model, "ex": ex}
            text = Writer.bench_sensor_text(item)

            if brand != "FT":
                if text:
                    cross.append((model, text))
                continue

            if not text:
                missing.append((model, ex))
                continue

            pick = Writer.bench_sensor_pick(item)
            assert pick is not None
            sensor = pick["default"]

            if sensor["family型号"] not in allowed:
                cross.append((model, text))

            if not sensor.get("is_override") and not (low <= pick["SF"] <= high):
                out_of_range.append((model, text, round(pick["SF"], 2)))

    if missing:
        raise RuntimeError("台秤传感器选不出 {} 个型号：{}".format(
            len(missing), missing[:5]))

    if cross:
        raise RuntimeError("台秤传感器跨品牌/越界 {} 条：{}".format(
            len(cross), cross[:3]))

    if out_of_range:
        raise RuntimeError("台秤传感器倍率越界 {} 条：{}".format(
            len(out_of_range), out_of_range[:3]))

    print("      {} 个品牌×材质×量程×台面组合 / {} 个型号："
          "FT 全部有选型，AW 留空待补数据".format(len(combos), len(rows)))


@check("数据：单点式传感器 Y 值档位完整")
def _single_point_y_values():
    """命名规则表(传感器2)给每个单点式系列两档 Y 值：
    PC42 10000/15000、PC46 7500/15000、PC60 7500/15000、
    PC6 12500/25000、PCB 12500/25000。

    每个"系列+容量"都必须两档齐全且各有非防爆/防爆两行，否则台秤下拉
    会缺选项，报价备注也可能写到不存在的组合。原先漏录第二档，故在此
    把命名规则表的档位写死。"""
    import csv

    from COPA.apps import Writer

    expected = {
        "PC42": {"10000", "15000"},
        "PC46": {"7500", "15000"},
        "PC60": {"7500", "15000"},
        "PC6": {"12500", "25000"},
        "PCB": {"12500", "25000"},
    }

    path = os.path.join(Writer.DATA_DIR, "富林泰克传感器.csv")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["安装方式"].strip() == "单点式"]

    seen, wrong_y, wrong_ex = {}, [], []

    for row in rows:
        family = row["family型号"].strip()
        key = (family, row["capacity容量"].strip())
        seen.setdefault(key, {"Y": set(), "EX": set()})
        seen[key]["Y"].add(row["Y值"].strip())
        seen[key]["EX"].add(row["EX防爆等级"].strip())

    for (family, capacity), got in seen.items():
        if got["Y"] != expected.get(family, set()):
            wrong_y.append((family, capacity, sorted(got["Y"])))

        if got["EX"] != {"0", "IICT6"}:
            wrong_ex.append((family, capacity, sorted(got["EX"])))

    if wrong_y:
        raise RuntimeError("{} 个型号 Y 值档位不全：{}".format(
            len(wrong_y), wrong_y[:3]))

    if wrong_ex:
        raise RuntimeError("{} 个型号防爆行不全：{}".format(
            len(wrong_ex), wrong_ex[:3]))

    print("      {} 个型号 × 2 档 Y 值 × 2 种防爆，共 {} 行".format(
        len(seen), len(rows)))


@check("数据：台秤选型对齐厂家常用配置")
def _bench_matches_catalog():
    """`ref/常用秤台尺寸.xlsx` 是厂家给的 FT 台秤标配表，选型结果必须逐条吻合。

    表里只有一套配置、不分材质，所以只校验碳钢(C/HC)：不锈钢按"只用不锈钢
    传感器"的材质规则走 PC6/PCB，本就不该与这张表一致(AW 无数据)。
    这张表同时是 3/6/12kg 白名单(override)的来源，改规则若把标配挤掉，
    说明 fence 或倍率窗口收得太紧，必须在这里拦下来。"""
    import csv

    from COPA.apps import Writer

    catalog = {
        ("3", "300x400"): "PC42-10",
        ("6", "300x400"): "PC42-20",
        ("15", "300x400"): "PC42-30",
        ("30", "300x400"): "PC46-50",
        ("30", "400x500"): "PC60-50",
        ("60", "400x500"): "PC60-100",
        ("60", "500x600"): "PC60-100",
        ("150", "400x500"): "PC60-300",
        ("150", "500x600"): "PC60-300",
        ("300", "500x600"): "PC60-500",
        ("300", "600x800"): "PC60-500",
        ("600", "500x600"): "PC60-750",
        ("600", "600x800"): "PC60-750",
    }

    path = os.path.join(Writer.DATA_DIR, "台秤通表.csv")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    checked, wrong = set(), []

    for row in rows:
        if row["品牌"].strip().upper() != "FT":
            continue

        if row["材质"].strip().upper() not in ("C", "HC"):
            continue

        key = (row["kg量程"].strip(), row["台面尺寸"].strip().replace("*", "x"))

        if key not in catalog or key in checked:
            continue

        checked.add(key)
        pick = Writer.bench_sensor_pick(
            {"type": "bench", "bench": row["具体型号"].strip(), "ex": False})
        assert pick is not None
        sensor = pick["default"]
        actual = "{}-{}".format(sensor["family型号"], sensor["capacity容量"])

        if actual != catalog[key]:
            wrong.append((key, catalog[key], actual))

    missing = set(catalog) - checked

    if missing:
        raise RuntimeError("常用秤台尺寸表有 {} 组在通表里找不到：{}".format(
            len(missing), sorted(missing)[:3]))

    if wrong:
        raise RuntimeError("与厂家常用配置不符 {} 组：{}".format(
            len(wrong), wrong[:3]))

    print("      {} 组碳钢标配逐条吻合(3kg PC42-10 … 600kg PC60-750)".format(
        len(checked)))


@check("解析：台面尺寸计量写法")
def _parser_size_variants():
    """台面尺寸的各种人话写法都要认：纯数字(mm)、带 m/米/cm/mm 单位、
    口语"1米5"。写单位的在解析步换算成 mm，没写单位的保留原形态，
    由 build_engine_input 的 size_to_mm 统一归一到通表口径(mm)"""
    from COPA.apps.Parser import Parser, size_to_mm

    parser = Parser()
    cases = {
        "台面1500*1500": "1500x1500",
        "台面1500mm×1500mm": "1500x1500",
        "台面1米5*1米5": "1.5x1.5",
        "台面1.5m×1.5m": "1500x1500",
        "台面1.5米x1.5米": "1500x1500",
        "台面1.2m x 1.5m": "1200x1500",
        "台面1米2x1米5": "1.2x1.5",
        "台面30x40cm": "300x400",
        "台面0.6x0.8": "0.6x0.8",
    }

    for text, expect in cases.items():
        got = parser.parse_quote_text(
            "平台秤，料重2000kg，{}，碳钢。".format(text)
        )["data"].get("台面尺寸")

        if got != expect:
            raise RuntimeError("{} 解析为 {}，应为 {}".format(text, got, expect))

    # 无「台面」前缀的裸写尺寸("3米*3米碳钢平台秤")也要认：这类写法
    # 片段里没有任何尺寸用语，靠裸尺寸兜底归到空位台面尺寸槽
    bare_cases = {
        "3米*3米碳钢平台秤": "3000x3000",
        "碳钢平台秤，台面3米×3米": "3000x3000",
        "3000x3000平台秤，碳钢": "3000x3000",
        "2米*3米平台秤，料重3000kg": "2000x3000",
    }

    for text, expect in bare_cases.items():
        got = parser.parse_quote_text(text)["data"].get("台面尺寸")

        if got != expect:
            raise RuntimeError("{} 解析为 {}，应为 {}".format(text, got, expect))

    # engine 边界：不论解析形态如何，都要归一成通表口径 mm
    for text, expect in (("1.5x1.5", "1500x1500"),
                         ("1500x1500", "1500x1500"),
                         ("0.6x0.8", "600x800"),
                         ("30x40cm", "300x400"),
                         ("1.2m×1.5m", "1200x1500"),
                         ("3x3", "3000x3000"),
                         ("2000x3000", "2000x3000")):
        got = size_to_mm(text)

        if got != expect:
            raise RuntimeError("{} 归一到 mm 为 {}，应为 {}".format(
                text, got, expect))

    print("       米制/厘米制/毫米制写法均归一为通表尺寸；裸写尺寸(无「台面」前缀)同样识别")


@check("录入：文本页签防爆勾选不被回填清除")
def _desk_ex_checkbox():
    """文本页签的防爆复选框是人工开关：描述没写"防爆"时，选型发起前的
    文本->下拉回填不得把它静默清掉；描述明确写了防爆意向时仍以文本为准"""
    from PySide6.QtWidgets import QApplication

    from COPA.apps.Desk import Desk

    app = QApplication.instance() or QApplication([])
    desk = Desk()
    desk.inputTabs.setCurrentIndex(0)
    card_item = desk.cardContainerLayout.itemAt(0)
    assert card_item is not None
    card = card_item.widget()
    from COPA.apps.Desk import QuoteCard
    assert isinstance(card, QuoteCard)
    card.comboBox.setCurrentText("称重模块")

    def _ex_after_backfill(description, checked):
        card.plainTextEdit.setPlainText(description)
        card.checkBox_3.setChecked(checked)
        desk._backfill_gui_from_text()
        return bool(desk.collect_entries()[0]["Ex_P"])

    plain = "料重5吨，皮重450公斤，4支点，碳钢，仪表3306，PN通讯。"

    if not _ex_after_backfill(plain, True):
        raise RuntimeError("勾选防爆后，文本回填把勾选清掉了")

    if _ex_after_backfill(plain + "无需防爆。", True):
        raise RuntimeError("描述明确无需防爆时，未按文本取消防爆")

    desk.close()
    app.processEvents()
    print("       勾选保留 / 文本明确否定时以文本为准")


@check("报价：单项目模板按明细行数扩展")
def _writer_single_rows():
    """单项目模板原为 7 行明细固定区，条目多时报"超过7行"拒输出；
    改为按实际明细行数重建后，服务费/价税合计/备注区随之下移且公式行号正确"""
    import tempfile

    import openpyxl

    from COPA.apps import Writer

    model, desc = Writer.lookup_module("52-30M", "CS", "SB14", 227, True,
                                       y=11500, accuracy="C3")
    base = {"type": "module", "qty": 1, "ex": True, "digital": False,
            "module": (model, desc), "jbox": "KE-4",
            "controller": "FT230NA002B", "support": 4, "accessories": []}
    items = [dict(base, quote_id=1) for _ in range(7)]

    if Writer._use_multi_template(items):
        raise RuntimeError("同项目号多条目应走单项目模板")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "module.xlsx")
        Writer.build_quote(items, brand="COPA B", lang="zh", out_path=path,
                           service=True)
        ws = openpyxl.load_workbook(path).active
        assert ws is not None

    detail_rows = [r for r in range(13, ws.max_row + 1)
                   if ws.cell(row=r, column=2).value == "称重模块"]
    r_total = next((r for r in range(13, ws.max_row + 1)
                    if str(ws.cell(row=r, column=1).value or "")
                    .startswith("价税合计")), None)

    if len(detail_rows) != 7:
        raise RuntimeError("明细行应为7条，实际{}".format(len(detail_rows)))

    if r_total is None:
        raise RuntimeError("未找到价税合计行")

    expect_sum = "=SUM(G13:G{})".format(r_total - 1)

    if ws.cell(row=r_total, column=7).value != expect_sum:
        raise RuntimeError("合计公式应为 {}，实际 {}".format(
            expect_sum, ws.cell(row=r_total, column=7).value))

    if "G{}".format(r_total) not in str(ws.cell(row=r_total, column=3).value):
        raise RuntimeError("大写金额公式未指向合计行 G{}".format(r_total))

    print("       7条明细下移合计至第 {} 行，公式已重映射".format(r_total))


@check("报价：模块线仪表行用「系列（具体型号）」")
def _writer_module_controller_row():
    """模块线仪表行按模板 B 列写「称重显示控制器\\nFAB330（具体型号）」：

    - 型号列 = 系列（具体型号），与整机描述第 6 行同一套 _indicator_label；
    - 描述整段在后、品牌落在末尾（与平台秤「；品牌：」在括号外同构）；
    - 通表描述自带「；品牌：alwe」的只留一个品牌，不许叠两遍。
    """
    from COPA.apps import Writer

    model, desc = Writer.lookup_module("52-30M", "CS", "SB14", 227, True,
                                       y=11500, accuracy="C3")

    def row(controller, install=""):
        item = {"type": "module", "quote_id": 1, "qty": 1, "ex": True,
                "digital": False, "module": (model, desc), "jbox": "KE-4",
                "controller": controller, "controller_install": install,
                "support": 4, "accessories": []}
        rows, _ = Writer.build_item_rows(item, lang="zh")
        return next(r for r in rows if r[0] == "称重显示控制器")

    line = row("FAB3306EX10000A", "立杆安装，")
    expect = Writer._indicator_label("FAB3306EX10000A")

    if line[1] != expect:
        raise RuntimeError("仪表型号列应为「{}」，实际「{}」".format(expect, line[1]))

    if "（" not in line[1]:
        raise RuntimeError("型号列未带具体型号：{}".format(line[1]))

    if "立杆安装" not in line[4]:
        raise RuntimeError("安装方式没进描述：{}".format(line[4]))

    if not line[4].endswith("；品牌：flintab"):
        raise RuntimeError("仪表描述应以品牌结尾：{}".format(line[4]))

    aw = row("AW220T1PA001A", "壁挂安装，")

    if aw[4].count("品牌：") != 1:
        raise RuntimeError("描述自带品牌时不该重复追加：{}".format(aw[4]))

    if not aw[4].endswith("；品牌：alwe"):
        raise RuntimeError("COPA A仪表品牌应为 alwe：{}".format(aw[4]))

    print("       {} | {}".format(line[1], line[4][-18:]))


@check("解析：品牌写法（含与仪表同片段）")
def _parser_brand_variants():
    """平台秤报价常只写品牌不写"模块"：FT品牌 / 品牌FT / FT/AW 都要能落到
    m_brand；品牌与仪表挤在同一片段("品牌FT 仪表3306")时，仪表品牌不得把
    秤台品牌挤掉"""
    from COPA.apps.Parser import Parser

    parser = Parser()
    base = "平台秤，料重2000kg，台面1500*1500，碳钢，{}。"

    cases = {
        "FT模块": ("FT", None),
        "FT品牌": ("FT", None),
        "品牌FT": ("FT", None),
        "FT/AW": ("FT", None),
        "品牌FT 仪表3306": ("FT", "FAB"),
        "FT品牌 仪表3306，RS485": ("FT", "FAB"),
        "FT/AW 仪表3306": ("FT", "FAB"),
        "品牌AW 仪表3306": ("AW", "FAB"),
    }

    for text, (m_brand, c_brand) in cases.items():
        data = parser.parse_quote_text(base.format(text))["data"]

        if data.get("m_brand") != m_brand:
            raise RuntimeError("{} 的 m_brand 为 {}，应为 {}".format(
                text, data.get("m_brand"), m_brand))

        if c_brand is not None and data.get("c_brand") != c_brand:
            raise RuntimeError("{} 的 c_brand 为 {}，应为 {}".format(
                text, data.get("c_brand"), c_brand))

    # 反向确认没把同一次提及重复归属：只写"FT模块"时不得再多补一个 c_brand
    if "c_brand" in parser.parse_quote_text(base.format("FT模块"))["data"]:
        raise RuntimeError("FT模块 被重复归属出 c_brand")

    print("       品牌独立写/前缀写/并列写均落到 m_brand，仪表品牌不受影响")


@check("选型：整机线品牌缺省与缺参提示")
def _platform_brand_default():
    """整机线(平台秤/台秤)只给一个品牌词时，秤体与仪表同品牌配套——用户说
    "FT品牌/FT/FT平台秤"是指整机品牌，不该再索要一次仪表品牌。模块线不套用
    (FT 模块配 FAB 仪表是常规组合)，仍分别校验。缺品牌时提示"秤体品牌"。"""
    from COPA.apps.Desk import (
        EngineService, build_engine_input, _missing_message)
    from COPA.apps.Parser import Parser

    parser = Parser()

    def engine_input_of(item_type, description):
        parsed = parser.parse_quote_text(description)
        entry = {
            "description": description,
            "item_type": item_type,
            "quote_info": {"quote_id": 1, "quantity": 1},
            "parsed": parsed,
            "Ex_P": False,
            "high_precision": False,
            "metrology": False,
            "digital": False,
        }
        return entry, build_engine_input(entry)

    # 三种写法都该落到 FT 仪表并跑通
    for text in (
        "碳钢平台秤，台面1500*1500，料重2000kg，FT品牌",
        "碳钢平台秤，台面1500*1500，料重2000kg，FT",
        "FT平台秤，台面1500*1500，料重2000kg，碳钢",
    ):
        entry, ei = engine_input_of("平台秤", text)
        module_data = ei["module_data"]

        if module_data["c_brand"] != "FT":
            raise RuntimeError("{} 的 c_brand 为 {}，应回退为 FT".format(
                text, module_data["c_brand"]))

        missing = EngineService._missing_required(ei)

        if missing:
            raise RuntimeError("{} 仍报缺参 {}".format(text, missing))

        result = _run_one("平台秤", text)

        if result.get("status") != "OK":
            raise RuntimeError("{} 选型未通过：{}".format(
                text, result.get("status")))

        model = ((result.get("platform") or [{}])[0].get("platform")
                 or {}).get("具体型号", "")

        if not model.startswith("FT"):
            raise RuntimeError("{} 选出的型号为 {}，应属 FT 品牌".format(
                text, model))

    # AW 同规则
    _, ei = engine_input_of("平台秤", "AW平台秤，台面1500*1500，料重2000kg，碳钢")

    if ei["module_data"]["c_brand"] != "AW":
        raise RuntimeError("AW 平台秤 c_brand 未回退：{}".format(
            ei["module_data"]["c_brand"]))

    # 无品牌：拦在"秤体品牌"，不能报成仪表品牌
    entry, ei = engine_input_of(
        "平台秤", "碳钢平台秤，台面1500*1500，料重2000kg")
    missing = EngineService._missing_required(ei)

    if "m_brand" not in missing:
        raise RuntimeError("平台秤缺品牌未被拦下：{}".format(missing))

    message = _missing_message(missing, "platform", entry["parsed"])

    if "缺少秤体品牌" not in message:
        raise RuntimeError("缺参提示为「{}」，应含「缺少秤体品牌」".format(message))

    # 模块线不得被回退污染
    _, ei = engine_input_of("称重模块", "FT模块，碳钢，4支点，料重5吨，皮重450公斤")
    module_data = ei["module_data"]

    if module_data["c_brand"] is not None:
        raise RuntimeError("模块线 c_brand 被回退污染：{}".format(
            module_data["c_brand"]))

    if "c_brand" not in EngineService._missing_required(ei):
        raise RuntimeError("模块线缺仪表品牌未被拦下")

    print("       整机线单品牌词同品牌配套，模块线分别校验，缺参指向秤体品牌")


@check("清单：安全系数色块分区")
def _checklist_sf_zone():
    """色块分区按业务口径：<1.3 红、1.3~2.0 绿、2.0~2.5 黄、>=2.5 红；
    边界值归上一档(1.3 绿、2.0 黄、2.5 红)"""
    from COPA.apps.Checklist import sf_zone

    expect = {1.29: "#E53935", 1.3: "#43A047", 1.99: "#43A047",
              2.0: "#FFD600", 2.49: "#FFD600", 2.5: "#E53935", 3.33: "#E53935"}

    for sf, color in expect.items():
        got, _desc = sf_zone(sf)

        if got != color:
            raise RuntimeError("SF={} 色块为 {}，应为 {}".format(sf, got, color))

    print("       1.29红 / 1.30绿 / 1.99绿 / 2.00黄 / 2.49黄 / 2.50红")


@check("清单：安全系数标签与色块成组")
def _checklist_sf_group():
    """「安全系数」文字标签与色块必须同进同退(否则只剩半组不知所云)，
    且在传感器行内不压其他控件：下拉 < 标签 < 色块 < 衍生品种标签"""
    from PySide6.QtWidgets import QApplication

    from COPA.apps.Checklist import QuoteListItem

    app = QApplication.instance() or QApplication([])
    item = QuoteListItem()

    if item.sfLabel.text() != "安全系数：":
        raise RuntimeError("标签文案为「{}」".format(item.sfLabel.text()))

    # 卡片本身未 show，isVisible 恒为 False，这里看「是否被显式隐藏」
    for widget in (item.sfLabel, item.sfChip):
        if not widget.isHidden():
            raise RuntimeError("{} 初始应为隐藏(无传感器结果)".format(
                widget.objectName() or widget))

    item._show_sf_group(True)
    app.processEvents()

    for widget in (item.sfLabel, item.sfChip):
        if widget.isHidden():
            raise RuntimeError("成组显示时 {} 仍被隐藏".format(
                widget.objectName() or widget))

    item._show_sf_group(False)

    for widget in (item.sfLabel, item.sfChip):
        if not widget.isHidden():
            raise RuntimeError("成组隐藏时 {} 仍在显示".format(
                widget.objectName() or widget))

    # 同一行内的横向次序，任一处越界即说明改布局时撞车
    left = item.sensorComBox.geometry().right()
    order = [("安全系数标签", item.sfLabel), ("色块", item.sfChip),
             ("衍生品种标签", item.derivativeLb)]

    for name, widget in order:
        geo = widget.geometry()

        if geo.left() <= left:
            raise RuntimeError("{} 左边缘 {} 压到前一个控件右边缘 {}".format(
                name, geo.left(), left))

        left = geo.right()

    if left > item.derivativeComBox.geometry().right():
        raise RuntimeError("该行控件超出卡片右边界")

    print("       标签+色块同步显隐；传感器下拉→标签→色块→衍生品种无重叠")


@check("契约：规则 / 项目号 / 快照 / 双端 / 文档一致")
def _consistency():
    """check_consistency.py 的 23 项契约检查并入日常自检。

    这批检查不看业务判定对不对，只看「同一件事在多处是不是同一个说法」：
    规则码三处对齐、项目号五处对号、GUI 与 CLI 同一条基线装配、文档口径
    跟代码一致。这类漂移单看任何一处都正常，只有并排比才看得出来，所以
    必须跟基线自检一起跑。"""
    from COPA.tests import check_consistency as cc

    buf = io.StringIO()
    stdout, sys.stdout = sys.stdout, buf

    try:
        cc._FAILED.clear()

        for fn in (cc.check_rules, cc.check_project_no,
                   cc.check_two_ends, cc.check_docs):
            fn()
    finally:
        sys.stdout = stdout

    report = buf.getvalue()
    total = report.count("[OK]") + report.count("[NG]")

    if cc._FAILED:
        print(report)
        raise RuntimeError("契约不一致 {} 项：{}".format(
            len(cc._FAILED), "、".join(cc._FAILED)))

    print("       规则三方对齐 / 项目号五处对号 / 双端同一装配 / 文档口径，共 {} 项".format(total))


def _run_one(item_type, description):
    """按 Desk 采集出的条目形状组装，走 EngineService 同一条计算路径"""
    from COPA.apps.Desk import EngineService
    from COPA.apps.Parser import Parser

    parser = Parser()
    parsed = parser.parse_quote_text(description)
    data = parsed["data"]
    data["req_com1"] = data.get("req_com1") or parser.default_req_com1()

    entry = {
        "description": description,
        "item_type": item_type,
        "quote_info": {"quote_id": 1, "quantity": 1},
        "onsite_service": False,
        "parsed": parsed,
        "Ex_P": False,
        "high_precision": False,
        "metrology": False,
        "digital": False,
    }

    # 引擎计算会往 stdout 打印明细，这里吞掉保持报告干净
    buf = io.StringIO()
    stdout, sys.stdout = sys.stdout, buf

    try:
        return EngineService().run_batch([entry])[0]
    finally:
        sys.stdout = stdout


def _version():
    try:
        from COPA.apps.version import APP_VERSION
        return APP_VERSION
    except Exception:
        return "unknown"


def main():
    print("=" * 60)
    print("COPA 基线自检  版本 {}  根目录 {}".format(_version(), ROOT))
    print("=" * 60)

    fails = []

    for name, fn in _CHECKS:
        try:
            fn()
            print("[PASS] {}".format(name))
        except Exception as err:
            print("[FAIL] {} -> {}".format(name, err))
            traceback.print_exc(limit=3)
            fails.append(name)

    if fails:
        print("\n{} 项未通过：{}".format(len(fails), "、".join(fails)))
        return 1

    print("\n全部通过（{} 项）。".format(len(_CHECKS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
