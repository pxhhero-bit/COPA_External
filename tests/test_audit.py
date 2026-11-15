"""audit 种子回归：每个问题码至少一条正例 + 一条反例.

种子集的作用是**锁契约**（码、级别、证据字段），不是覆盖率。真实错误样本在
P0 跑通后从历史单里挖出来，确认一条就往 CASES 里加一条，不改任何代码。

跑法：
    python COPA/tests/test_audit.py
"""
import os
import shutil
import sys
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from COPA.apps.audit.reader import read_quote     # noqa: E402
from COPA.apps.audit.runner import audit_file   # noqa: E402

HEADERS = ["序号", "名称", "型号规格、描述", "单位", "数量", "单价(元)", "总价(元)"]
EN_HEADERS = ["No.", "Item", "Model & Description", "Unit", "Qty",
              "Unit Price (USD)", "Total Price (USD)"]


def _desc_is_placeholder():
    """判断当前数据集是不是「占位描述」的示例集。

    对外版只带脱敏示例数据，描述通表里写的是「这是……的产品描述。」这类
    占位文案，没有真实描述原文。L25/L26 与型号快照断言全靠描述原文做比对，
    示例集里没有输入源，只能跳过——不为了过测试去造数据。
    """
    import csv

    from COPA.apps.audit import db as _db

    path = os.path.join(_db.DATA_DIR, "description", "FT描述通表.csv")
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                return str(row.get("描述") or "").startswith("这是")
    except OSError:
        return False
    return False


DESC_PLACEHOLDER = _desc_is_placeholder()
needs_desc_text = unittest.skipIf(
    DESC_PLACEHOLDER,
    "示例数据集的描述通表是占位文案，没有描述原文可供 L25/L26 比对")


def issue_baseline(path, folder):
    """模拟「出报价」：给文件盖项目号，并把基线写进临时项目快照。

    返回项目号。批阅侧按这个号在快照里查基线，所以必须两边都对上。
    """
    from openpyxl import load_workbook

    from COPA.apps import Snapshot
    from COPA.apps.audit import pno

    wb = load_workbook(path)
    code = pno.stamp(wb)
    wb.save(path)

    md = os.path.join(folder, "项目快照.md")

    if not os.path.exists(md):
        with open(md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# COPA 项目快照：测试项目\n\n## 三、出单记录\n")

    pno.save_state(path, code, md)
    return code


def _desc(model_line, capacity=None, face=None, material="碳钢",
          division="20g", ex=False, extra="", supply="内置电池，含充电器"):
    """按模板真实写法拼描述，缺项就传 None。supply=None 可去掉供电行
    （L24 用例）；防爆场景自动补「配防爆电源」（L23 判据）"""
    lines = ["型号：{}".format(model_line), "电子台秤"]
    if material:
        lines.append("1.材质：{}，花纹钢台面；".format(material))
    if face:
        lines.append("2.台面尺寸：{}mm；".format(face))
    if capacity or division:
        parts = []
        if capacity:
            parts.append("量程：{}kg".format(capacity))
        if division:
            parts.append("分度值e=d={}".format(division))
        lines.append("3." + "，".join(parts) + "；")
    if ex:
        lines.append("4.防爆等级：Ex ia IIC T4 Ga；")
    if supply:
        text = supply + ("，配防爆电源" if ex else "")
        lines.append("5.供电：{}；".format(text))
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def make_quote(path, rows, headers=None, merge_model_col=False):
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "报价单"
    for col, text in enumerate(headers or HEADERS, 1):
        ws.cell(1, col, text)
    if merge_model_col:
        ws.merge_cells(start_row=1, start_column=3, end_row=1, end_column=4)
    for index, row in enumerate(rows, 2):
        for col, value in enumerate(row, 1):
            ws.cell(index, col, value)
    wb.save(path)
    return path


CASES = []


def case(name, rows, expect, headers=None, merge_model_col=False):
    CASES.append((name, rows, set(expect), headers, merge_model_col))


# ---- 反例：干净单必须 0 问题（否则误报会淹没真问题）---------------------
case("clean", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 0, 0,
]], [])

case("clean_platform", [[
    "1", "电子平台秤",
    _desc("FTPD-C-030-1515-N", capacity=3000, face="1500*1500", division="1kg"),
    "台", 1, 0, 0,
]], [])

# ---- L1 型号不存在 ------------------------------------------------------
case("L1_garbage", [[
    "1", "电子台秤", "XYZ-999-1234\n电子台秤",
    "台", 1, 0, 0,
]], ["L1", "L24"])       # 描述未声明供电方式，L24 同步提示

# ---- L1T 只有型批型号 ---------------------------------------------------
case("L1T_typebatch", [[
    "1", "电子台秤",
    _desc("TCS-60kg", capacity=60, face="400*500"),
    "台", 1, 0, 0,
]], ["L1T"])

# ---- L1M 型号列无可识别型号（空白/占位符）-------------------------------
case("L1M_no_model", [[
    "1", "电子台秤",
    "电子台秤\n1.材质：碳钢，花纹钢台面；\n2.台面尺寸：400*500mm；\n"
    "3.量程：60kg，分度值e=d=20g；\n5.供电：内置电池，含充电器；",
    "台", 1, 2600, 2600,
]], ["L1M"])

# ---- L2 名称与型号品类不符 ---------------------------------------------
case("L2_category", [[
    "1", "电子台秤",
    _desc("FTPD-C-030-1515-N", capacity=3000, face="1500*1500", division="1kg"),
    "台", 1, 0, 0,
]], ["L2"])

# ---- L3 量程不符 --------------------------------------------------------
case("L3_capacity", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=30, face="400*500"),
    "台", 1, 0, 0,
]], ["L3"])

# ---- L4 台面不符 --------------------------------------------------------
case("L4_face", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="500*600"),
    "台", 1, 0, 0,
]], ["L4"])

# ---- 材质不符：FTBR 台秤在描述通表里没有标准描述 -> 走旧规则 L5 --------
case("L5_material", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500", material="不锈钢"),
    "台", 1, 0, 0,
]], ["L5"])

# ---- 防爆不符：同上，型号非防爆、描述要求防爆 -> L6 ---------------------
case("L6_ex", [[
    # 台秤赋码里没有防爆位（BR/BY/BH…），型号不带 E 是正常写法，不判 L6；
    # 用平台秤测这条：平台秤型号的尾码 E 才是防爆位。
    "1", "电子平台秤",
    _desc("FTPD-C-030-1515-N", capacity=3000, face="1500*1500", ex=True),
    "台", 1, 0, 0,
]], ["L6"])

# 反例：防爆型号 + 描述要求防爆 -> 不报（快照 防爆=1 与描述一致）
case("L26_ex_ok", [[
    "1", "电子台秤",
    _desc("FTBR-S-060-4050-E", capacity=60, face="400*500", ex=True,
          material="不锈钢"),
    "台", 1, 0, 0,
]], [])

# ---- L7 描述缺参数 ------------------------------------------------------
case("L7_missing", [[
    "1", "电子台秤", "型号：FTBR-C-060-4050\n电子台秤\n1.材质：碳钢；",
    "台", 1, 0, 0,
]], ["L7", "L24"])       # 缺参数之外，供电方式也没声明

# ---- L8 描述内型号冲突 --------------------------------------------------
case("L8_inner", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500",
          extra="5.备用台秤 FTBR-C-030-4050 一台；"),
    "台", 1, 0, 0,
]], ["L8"])

# ---- L9 旧码：0405 等价 4050，且量程确实不符 ----------------------------
case("L9_legacy", [[
    "1", "电子台秤",
    _desc("FTBR-C-006-0405", capacity=60, face="400*500"),
    "台", 1, 0, 0,
]], ["L9", "L3"])

# ---- L10 未识别行 ------------------------------------------------------
case("L10_unrecognized", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 0, 0,
], ["", "附加说明：含安装调试", "", "", "", "", "见附件"]],
    ["L10"])

# ---- 表头认不出：不做表头校验，但不能静默（L39 兜底）-------------------
# 解析器认不出表头就整页跳过，这是拍板口径（不报表头类问题）。但跳过之后
# 一条明细都没有，必须留一条 L39——0 问题只会让人以为单子干净。
case("header_unknown_reports_empty", [[
    "1", "电子台秤", "FTBR-C-060-4050", "台", 1, 2600, 2600,
]], ["L39"],
    headers=["甲", "乙", "丙", "丁", "戊", "己", "庚"])

# ---- 英文表头 + 合并的型号列 -------------------------------------------
case("en_merged_header", [[
    "", "Electronic bench scale",
    "FTBR-C-060-4050\n1.Material: carbon steel\n2.Platform: 400*500mm\n"
    "3.Capacity: 60kg, e=d=20g\n4.Power supply: built-in battery, charger included",
    "PCS", 1, 0, 0,
]], [], EN_HEADERS, True)

# ---- L12 备注栏缺传感器型号（描述声明了传感器才查）---------------------
case("L12_remark_no_sensor", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500",
          supply="内置电池（含充电器），配防爆电源",
          extra="4.防爆传感器*1；品牌：flintec"),
    "台", 1, 0, 0,
    # 台秤赋码里也有防爆位：FTBR 非防爆不跟后缀，描述写防爆而型号不带 -E，
    # L6 照判（富林泰克台秤防爆型号是 FTBR-C-060-4050-E）
]], ["L12", "L6"])

case("L12_remark_desc_has_model", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500",
          supply="内置电池（含充电器），配防爆电源",
          extra="4.防爆传感器 SLB-91；品牌：flintec"),
    "台", 1, 0, 0,
]], ["L6"])        # 型号写在描述里也认（L12 不报）；型号不带 -E 但描述要求防爆，L6 照判

# ---- L13 仪表不符合防爆需求（非防爆仪表顶在防爆声明上）-----------------
case("L13_ex_instrument_mismatch", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050-E", capacity=60, face="400*500", ex=True,
          extra="5.防爆仪表FT-230（FT230HA012A）*1（不锈钢外壳模拟仪表）；"),
    "台", 1, 0, 0,
]], ["L13"])

# ---- L14 台秤描述内出现备注行 ------------------------------------------
case("L14_bench_note_line", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500",
          extra="备注：仪表分体安装，不含立柱。"),
    "台", 1, 0, 0,
]], ["L14"])

# ---- L15 分度值以 kg 计建议换算 g --------------------------------------
case("L15_division_unit", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500", division="0.02kg"),
    "台", 1, 0, 0,
]], ["L15"])

# ---- L21 模块拉杆变体：型号带 L（水平拉杆）描述必须声明（样例客户案例）--------
# 版式按样例客户真实单：型号+传感器串在名称列，描述列首行重复型号
case("L21_pull_rod_missing", [[
    "1", "称重模块",
    "52-30ML CS SB14-3000kg-BH-C3 EX\n"
    "传感器材质：17-4PH不锈钢，防爆等级：Ex ia ⅡC T6 Ga；模块附件材质：合金钢镀镍；",
    "只", 3, 2260, 6780,
]], ["L25"])          # 拉杆漏写 -> L25 描述缺项（型号蕴含项，判红）

case("L21_pull_rod_ok", [[
    "1", "称重模块",
    "52-30ML CS SB14-3000kg-BH-C3 EX\n"
    "传感器材质：17-4PH不锈钢，防爆等级：Ex ia ⅡC T6 Ga；带水平拉杆；模块附件材质：合金钢镀镍；",
    "只", 3, 2260, 6780,
]], [])

# 模块材质不由系列决定，由「系列 材质码 传感器型号」里的材质码决定：
# 同一个 52-30ML 既有 CS（合金钢镀镍）也有 SS（304不锈钢）。取快照必须按
# 详细型号，只拿系列会落到同系列任意一行——这就是样例客户单 L26 误报的根因。
case("L26_module_material_ss", [[
    "1", "称重模块",
    "52-30ML SS SB14-3000kg-BH-C3 EX\n"
    "传感器材质：17-4PH不锈钢，防爆等级：Ex ia ⅡC T6 Ga；带水平拉杆；模块附件材质：304不锈钢；",
    "只", 3, 2260, 6780,
]], [])

# 反例：型号写 SS（304不锈钢），描述写合金钢镀镍 —— 材质真冲突，必须报
case("L26_module_material_conflict", [[
    "1", "称重模块",
    "52-30ML SS SB14-3000kg-BH-C3 EX\n"
    "传感器材质：17-4PH不锈钢，防爆等级：Ex ia ⅡC T6 Ga；带水平拉杆；模块附件材质：合金钢镀镍；",
    "只", 3, 2260, 6780,
]], ["L26"])

# 汇总页聚合行：desc 即纯型号串（无中文，无独立描述）——不重复报 L21，
# 拉杆声明以报价单明细描述为准（样例客户汇总页 6 行误报的锁定用例）
case("L21_echo_summary_row", [[
    "1", "称重模块",
    "52-30ML CS SB14-3000kg-BH-C3 EX",
    "套", 21, 2260, 47460,
]], [])

# ---- L22 仪表供电与描述不符（海斯福案例：尾缀 D=DC24V，描述写 220VAC）----
case("L22_supply_mismatch", [[
    "1", "电子平台秤",
    "型号：SCS-3t EX（FTPD-S-030-1212-E）\n防爆电子平台秤\n"
    "1.材质：全不锈钢；\n2.台面规格：1200*1200；\n"
    "3.量程：3t，分度值e=d=1kg，精度等级C3；\n4.防爆传感器SB14*4；\n"
    "5.仪表FT210PA0A0000D（模拟仪表，供电220VAC）；",
    "台", 1, 0, 0,
]], ["L26"])          # 描述内嵌仪表型号 -> 走子型号快照比对

case("L22_supply_ok", [[
    "1", "电子平台秤",
    "型号：SCS-3t EX（FTPD-S-030-1212-E）\n防爆电子平台秤\n"
    "1.材质：全不锈钢；\n2.台面规格：1200*1200；\n"
    "3.量程：3t，分度值e=d=1kg，精度等级C3；\n4.防爆传感器SB14*4；\n"
    "5.仪表FT210PA0A0000A（模拟仪表，供电220VAC）；",
    "台", 1, 0, 0,
]], [])

# ---- L23 电池供电选配事项未说明（缺「电池另配」与「充电器」交代）--------
case("L23_battery_note_missing", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500", supply="电池供电"),
    "台", 1, 2600, 2600,
]], ["L30"])       # 只写「电池供电」没有实体电池与充电器：新版判红（L23 已被 L30 取代）

# ---- 平台秤系列级命中：组合未逐字收录不再报未收录（海斯福案例）----------
# 030（3t）与 0808（800x800）各自合法，只是该组合未收录于通表
case("platform_series_combo_ok", [[
    "1", "电子平台秤",
    "型号：SCS-3t EX（FTPD-S-030-0808-E）\n防爆电子平台秤\n"
    "1.材质：全不锈钢；\n2.台面规格：800*800；\n"
    "3.量程：3t，分度值e=d=1kg，精度等级C3；\n4.防爆传感器SB14*4；",
    "台", 2, 0, 0,
]], [])

# 新宙邦案例：6 位台面码 125125 = 125+125 -> 1250x1250mm，解码与 L4 都要认
case("platform_series_face6_ok", [[
    "1", "电子平台秤",
    "型号：SCS-3t EX（FTPD-S-030-125125-E）\n防爆电子平台秤\n"
    "1.材质：全不锈钢；\n2.台面规格：1250*1250mm；\n"
    "3.量程：3000kg，分度值e=d=1kg，精度等级C3；\n4.防爆传感器SB14*4；",
    "台", 1, 0, 0,
]], [])

# 台面码乱写（999999 超出合法边长范围）仍要报未收录
case("platform_bogus_face_still_l1u", [[
    "1", "电子平台秤",
    "型号：SCS-3t EX（FTPD-S-030-999999-E）\n防爆电子平台秤\n"
    "1.材质：全不锈钢；\n2.台面规格：1000*1000；\n"
    "3.量程：3t，分度值e=d=1kg，精度等级C3；\n4.防爆传感器SB14*4；",
    "台", 1, 0, 0,
]], ["L1U"])

# ---- 模块系列铁律：型号 = 模块系列+变体尾缀，传感器串只是配置 -------------
# 样例客户单口径（用户拍板）：模块型号从模块通表系列校验，52-30ML -> 52-30M；
# SB14-1134kg-BH-C3 是适配传感器不是型号，不该被抽去查库、更不该报 L1
case("module_series_prefix", [[
    "1", "称重模块\n52-30ML CS SB14-1134kg-BH-C3 EX",
    "",
    "只", 3, 2260, 6780,
]], [])

case("module_series_exact", [[
    "1", "称重模块\n55-30 CS RC3-7.5t-C3",
    "",
    "只", 4, 4800, 19200,
]], [])

# ---- L16 行金额算术：总价 ≠ 数量 × 单价 ---------------------------------
case("L16_amount_mismatch", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 2, 100, 350,
]], ["L16"])

# L16 反例：单价按分舍入的累计误差在容差内（3 × 99.99 = 299.97）
case("L16_amount_rounded_ok", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 3, 99.99, 299.97,
]], [])

# L16 反例：单价缺失（送审稿常态，总价列有数字也不猜）
case("L16_no_price_skip", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 2, "", 350,
]], [])

# L16 反例：单价为 0 等于没有价格（占位/送审稿），不做行核算
case("L16_zero_price_skip", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 2, 0, 350,
]], [])

# ---- L17 汇总金额：小计 ≠ 明细之和 --------------------------------------
case("L17_subtotal_mismatch", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 100, 100,
], [
    "2", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 200, 200,
], [
    "", "小计", "", "套", "", "", 500,
]], ["L17"])

# L17 反例：含运费的费用行参与加和（90 + 运费 10 = 小计 100）
case("L17_with_fee_ok", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 90, 90,
], [
    "", "运费", "", "批", 1, 10, 10,
], [
    "", "小计", "", "套", "", "", 100,
]], [])

# L17 反例：套数合计（数量列是套数不是金额）不参与金额校验
case("L17_qty_total_skip", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 90, 90,
], [
    "", "小计", "", "套", "", "", 90,
], [
    "", "套数合计", "", "套", 1, "", "",
]], [])

# L17 金额分层：明细(单套) ══ 小计 ══×套数══ 套数合计 ══Σ══ 设备合计。
# 明细只有 100/套，套数 3 -> 设备合计 300；拿明细之和 100 去比会差 3 倍（样例客户单实测 5 倍）
case("L17_segment_chain_ok", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 100, 100,
], [
    "", "小计", "", "套", 1, "", 100,
], [
    "", "套数合计", "", "套", 3, "", 300,
], [
    "", "设备合计", "", "套", 3, "", 300,
]], [])

# 反例：设备合计写成「明细之和」（漏乘套数）——旧口径会放过，现在必须报
case("L17_equipment_must_use_segment", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 100, 100,
], [
    "", "小计", "", "套", 1, "", 100,
], [
    "", "套数合计", "", "套", 3, "", 300,
], [
    "", "设备合计", "", "套", 3, "", 100,
]], ["L17"])

# 反例：套数合计既不是小计、也不是小计×套数（乘错了）
case("L17_qty_total_multiplied_wrong", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 100, 100,
], [
    "", "小计", "", "套", 1, "", 100,
], [
    "", "套数合计", "", "套", 3, "", 250,
]], ["L17"])

# ---- 「小计 × 套数」是标准公式形态，不能当「未识别」报 L20 -------------
# 设备合计 = 上一行小计 × 本行套数（=G3*E4）在报价单里很常见，业务上也对。
# 以前落到 else 分支被描述成「复合形态（明细+费用/跨表引用）」，文案与事实相反。
case("L20_summary_times_qty_ok", [[
    "1", "电子台秤",
    _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
    "台", 1, 100, 100,
], [
    "", "小计", "", "套", 1, "", 100,
], [
    "", "套数合计", "", "套", 2, "", 200,
], [
    "", "设备合计", "", "套", 2, "", "=G3*E5",
]], [])

# ---- 接线盒型号不能冒充整机型号 ----------------------------------------
# 平台秤模板的型号列首行是占位符「SCS-？t（AWPD-C-量程-尺寸）」，正文里
# 「5.接线盒AWJ-005*1」的 AWJ-005 在通表里是 jbox。以前从描述兜底捞型号时
# 只判「查库命中」，接线盒顶成整机型号且 level=exact，L1M 再也报不出来。
case("L1M_jbox_must_not_pose_as_machine", [[
    "1", "电子平台秤",
    "型号：SCS-？t（AWPD-C-量程-尺寸）\n"
    "1.材质：碳钢，花纹钢台面/光面板；\n"
    "2.台面规格：；\n"
    "3.量程：，分度值e=d=，精度等级C3；\n"
    "4.称重传感器XX*4（材质：合金钢/不锈钢）；品牌：alwe\n"
    "5.接线盒AWJ-005*1；品牌：alwe\n"
    "6.称重仪表xx*1（仪表描述、安装方式）；品牌：\n"
    "7.信号电缆5米。",
    "台", 1, 0, 0,
]], ["L1M"])

# ---- 反过来：行本身就是仪表，兜底必须取到仪表型号 ----------------------
# 阿根廷/COPA A双语单的版式：C 列前三行是「中文名 / 英文名 / 型号」，
# _head 只看前两行取不到型号，得从描述兜底。品类过滤如果一律只认整机，
# 这类行会被误判成「没写型号」（L1M），而它型号清清楚楚。
case("L1M_instrument_fallback_ok", [[
    "1", "称重显示控制器",
    "称重显示控制器\nController (Indicator)\nFAB3306HX10000D\n"
    "防尘式，4.3吋中英文显示，可接1个秤台，含1路RS232+1路RS485(RTU）通讯接口，"
    "DC24V供电；品牌：flintab",
    "台", 1, 0, 0,
]], [])

# ---- 整机型号未收录、但编码结构合法：取得到，不报「没写型号」 ---------
# 「SCS-1000kg（AWPD-C-010-1212）」通表没逐条收录，但 AWPD-C-010-1212
# 能解码成 AWPD 系列 —— 报「系列存在、具体型号未收录」比「没写型号」准确。
case("L1M_machine_code_decodable", [[
    "1", "电子平台秤",
    "电子平台秤\nEletric platform scale\n型号：SCS-1000kg（AWPD-C-010-1212）\n"
    "1.材质：碳钢，花纹钢台面；\n2.台面规格：1200*1200mm；\n3.量程：1000kg，"
    "分度值e=d=0.5kg，精度等级C3；\n4.称重传感器AWB-2t-BH-C3*4；\n5.仪表DC24V供电，含RS485接口",
    "台", 1, 0, 0,
]], [])


class AuditSeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_fixture_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_cases(self):
        for name, rows, expect, headers, merge in CASES:
            with self.subTest(case=name):
                path = os.path.join(self.tmp, name + ".xlsx")
                make_quote(path, rows, headers, merge)
                report = audit_file(path)
                got = {issue.code for issue in report.active_issues}
                if DESC_PLACEHOLDER and expect and not got \
                        and set(expect) <= {"L25", "L26"}:
                    self.skipTest("示例数据集无描述原文，{} 无输入源".format(name))
                self.assertEqual(expect, got,
                                 "{}: 期望 {} 实际 {}；明细={}".format(
                                     name, sorted(expect), sorted(got),
                                     [(i.row, i.label, i.model,
                                       [(x.code, x.message) for x in i.issues])
                                      for i in report.doc.items]))

    def test_no_silent_skip(self):
        """所有行必须有归属：明细 / 项目段 / 汇总 / 未识别，四类必居其一"""
        path = os.path.join(self.tmp, "coverage.xlsx")
        make_quote(path, [
            ["一", "电子台秤，共1台。量程60kg", "", "套", "", 0, 0],
            ["1", "电子台秤", _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
             "台", 1, 0, 0],
            ["2", "小计", "小计", "套", 1, 0, 0],
            ["", "某行看不懂的内容", "", "", "", "", "有值"],
        ])
        report = audit_file(path)
        doc = report.doc
        self.assertEqual(1, len(doc.items))
        self.assertEqual(1, len(doc.blocks))
        self.assertEqual(1, len(doc.unrecognized), "无法归类的行必须显式报告")

    def test_legacy_must_not_double_report(self):
        """旧码只报 L9，不再叠加 L1U——同一件事报两条会让人以为有两处错"""
        path = os.path.join(self.tmp, "legacy_only.xlsx")
        make_quote(path, [[
            "1", "电子台秤",
            _desc("FTBR-C-006-0405", capacity=6, face="400*500"),
            "台", 1, 0, 0,
        ]])
        report = audit_file(path)
        self.assertEqual({"L9"}, {i.code for i in report.active_issues})

    # ---- D 段 a 层：公式作用域（L18）------------------------------------

    def test_total_header_jihe(self):
        """「合计」也是金额列头（汇总页常用写法）：total 列识别成功 L16 才能核算"""
        path = os.path.join(self.tmp, "jihe_header.xlsx")
        make_quote(path, [
            ["1", "电子台秤",
             _desc("FTBR-C-060-4050", capacity=60, face="400*500"),
             "台", 2, 100, 350],
        ], headers=["序号", "名称", "型号规格、描述", "单位", "数量",
                    "单价(元)", "合计"])
        report = audit_file(path)
        self.assertIn("L16", {i.code for i in report.active_issues},
                      "「合计」列头必须识别为金额列")

    def test_summary_unrecognized_formula_still_amount_checked(self):
        """汇总格是没把握的公式（SUMIF 等）：公式作用域交 a 层 L20 提示，
        金额仍按「明细之和(+费用)」独立核算——样例客户单教训后的语义口径"""
        from COPA.apps.audit.checks import arith
        from COPA.apps.audit.model import LineItem, QuoteDoc, SummaryRow
        from COPA.apps.audit.rules import get_rules
        doc = QuoteDoc(path="")
        doc.items = [LineItem(sheet="s", row=2, name="称重模块", kind="module",
                              qty="1", price="100", total="100")]
        doc.summaries = [SummaryRow(sheet="s", row=5, label="设备合计",
                                    kind="grand", amount=100.0, amount_col=7)]
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual([], issues, "金额对得上就不报（公式形态由 a 层 L20 提示）")
        doc.summaries[0].amount = 999.0
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual(["L17"], [i.code for i in issues])

    def test_summary_grand_includes_fees(self):
        """合计 = 明细之和 + 费用行（服务费/运费）——「合计下面还有服务金额」
        的语义（用户拍板），费用不参与才是误报"""
        from COPA.apps.audit.checks import arith
        from COPA.apps.audit.model import LineItem, QuoteDoc, SummaryRow
        from COPA.apps.audit.rules import get_rules
        doc = QuoteDoc(path="")
        doc.items = [
            LineItem(sheet="报价单", row=2, name="称重模块", kind="module",
                     qty="1", price="100", total="100"),
            LineItem(sheet="报价单", row=3, name="信号电缆", kind="cable",
                     qty="1", price="20", total="20"),
        ]
        doc.summaries = [
            SummaryRow(sheet="报价单", row=4, label="服务费", kind="fee",
                       amount=6.0, amount_col=7),
            SummaryRow(sheet="报价单", row=5, label="总价", kind="grand",
                       amount=126.0, amount_col=7),
        ]
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual([], issues, "总价 126 = 明细 120 + 服务费 6，不应报")
        doc.summaries[1].amount = 200.0
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual(["L17"], [i.code for i in issues],
                         "总价与「明细+费用」不符必须报")

    def test_summary_equipment_cross_sheet(self):
        """设备合计直接引用汇总表（样例客户案例）：本表明细对不上、他表明细
        对上 -> 是跨表引用，不报；金额真错才报"""
        from COPA.apps.audit.checks import arith
        from COPA.apps.audit.model import LineItem, QuoteDoc, SummaryRow
        from COPA.apps.audit.rules import get_rules
        doc = QuoteDoc(path="")
        doc.items = [
            LineItem(sheet="报价单", row=2, name="称重模块", kind="module",
                     qty="1", price="100", total="100"),
            LineItem(sheet="汇总", row=2, name="称重模块", kind="module",
                     qty="24", price="2260", total="54240"),
        ]
        doc.summaries = [
            SummaryRow(sheet="报价单", row=10, label="设备合计", kind="equipment",
                       amount=54240.0, amount_col=7),
            SummaryRow(sheet="汇总", row=3, label="服务费", kind="fee",
                       amount=6000.0, amount_col=7),
            SummaryRow(sheet="汇总", row=4, label="合计", kind="grand",
                       amount=60240.0, amount_col=7),
        ]
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual([], issues,
                         "设备合计 54240=汇总表明细和；合计 60240=汇总明细+服务费")
        doc.summaries[0].amount = 54241.0
        issues = arith.check_summary(doc, get_rules())
        self.assertEqual(["L17"], [i.code for i in issues],
                         "跨表也对不上才报，且只报错的那条")

    def test_formula_scope_missed_row(self):
        """小计 SUM 公式漏了区间内的明细行（插入行后公式没跟上）"""
        path = os.path.join(self.tmp, "formula_miss.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, 100],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 200, 200],
            ["3", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 400, 400],
            ["", "小计", "", "套", "", "", "=SUM(G2:G3)"],
        ])
        report = audit_file(path)
        l18 = [i for i in report.active_issues if i.code == "L18"]
        self.assertEqual(1, len(l18), "SUM 漏第 4 行必须报 L18")
        self.assertIn("4", l18[0].message, "说明里要点出漏了哪一行")

    def test_formula_scope_ok(self):
        """反例：SUM 覆盖全段明细，公式层零问题"""
        path = os.path.join(self.tmp, "formula_ok.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, 100],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 200, 200],
            ["", "小计", "", "套", "", "", "=SUM(G2:G3)"],
        ])
        report = audit_file(path)
        self.assertNotIn("L18", {i.code for i in report.active_issues})

    def test_formula_ref_wrong_row(self):
        """明细总价公式引用了别的行（拖拽/复制错位）"""
        path = os.path.join(self.tmp, "formula_wrong_ref.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, 100],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 2, 100, ""],
        ])
        from openpyxl import load_workbook
        wb = load_workbook(path)
        ws = wb.active
        assert ws is not None
        ws.cell(3, 7, "=E2*F2")            # 第 3 行却引用第 2 行
        wb.save(path)
        report = audit_file(path)
        self.assertIn("L18", {i.code for i in report.active_issues})

    def test_formula_ref_round_ok(self):
        """反例：=ROUND(E2*F2,2) 是合法的行内核算，常数参数不算引用错位"""
        path = os.path.join(self.tmp, "formula_round.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 3, 99.99, ""],
        ])
        from openpyxl import load_workbook
        wb = load_workbook(path)
        ws = wb.active
        assert ws is not None
        ws.cell(2, 7, "=ROUND(E2*F2,2)")
        wb.save(path)
        report = audit_file(path)
        self.assertNotIn("L18", {i.code for i in report.active_issues})

    # ---- D 段 a 层：公式形态一致性（L19）与跳过说明（L20）----------------

    def test_formula_shape_inconsistent(self):
        """整齐的 =Ex*Fx 里混进 =Ex*Fx+100（藏系数）——L19 报少数派"""
        path = os.path.join(self.tmp, "formula_shape.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, "=E2*F2"],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 200, "=E3*F3"],
            ["3", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 400, "=E4*F4+100"],
        ])
        report = audit_file(path)
        l19 = [i for i in report.active_issues if i.code == "L19"]
        self.assertEqual(1, len(l19), "少数派公式形态必须报 L19")
        self.assertIn("4", l19[0].message)
        self.assertEqual((4, 7), l19[0].anchor, "定位到藏系数那格")

    def test_formula_shape_uniform_ok(self):
        """反例：整列同形态，L19 不报"""
        path = os.path.join(self.tmp, "formula_uniform.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, "=E2*F2"],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 2, 100, "=E3*F3"],
            ["3", "电子台秤", _desc("FTBR-C-060-4050"), "台", 3, 100, "=E4*F4"],
        ])
        report = audit_file(path)
        self.assertNotIn("L19", {i.code for i in report.active_issues})

    def test_formula_skip_notice(self):
        """小计 =SUM(...)+G2 非纯 SUM：不硬判，但必须给 L20 跳过说明"""
        path = os.path.join(self.tmp, "formula_skip.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, "=E2*F2"],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 200, "=E3*F3"],
            ["", "小计", "", "套", "", "", "=SUM(G2:G3)+G2"],
        ])
        report = audit_file(path)
        codes = {i.code for i in report.active_issues}
        self.assertNotIn("L18", codes, "形态没把握就不能硬报作用域错误")
        self.assertNotIn("L19", codes)
        l20 = [i for i in report.active_issues if i.code == "L20"]
        self.assertEqual(1, len(l20), "跳过必须留说明（L20）")
        self.assertIn("跳过", l20[0].message, "说明要讲清楚是因为没把握而跳过")

    def test_formula_skip_notice_grouped(self):
        """同形态多处跳过只出一条 L20（去重收敛，不逐行轰炸）"""
        path = os.path.join(self.tmp, "formula_skip_group.xlsx")
        make_quote(path, [
            ["1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100, "=E2*F2"],
            ["2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 200, "=E3*F3"],
            ["3", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 400, "=E4*F4"],
            ["", "小计", "", "套", "", "", "=SUM(G2:G4)*1.13"],
            ["", "价税合计", "", "套", "", "", "=SUM(G2:G4)*1.13"],
        ])
        report = audit_file(path)
        l20 = [i for i in report.active_issues if i.code == "L20"]
        self.assertEqual(1, len(l20), "同形态合并为一条说明")
        self.assertNotIn("L19", {i.code for i in report.active_issues})

    @unittest.skipUnless(os.path.exists(os.path.join(
        _ROOT, "ref", "广州兰达不锈钢防爆电子台秤报价单03032026-flintec.xlsx")),
        "缺少真实样本")
    def test_real_landa(self):
        """真实历史单（用户人工审核拍板的口径）：
        L3 量程不符 + L9 旧码，且必须报出四条漏检——
        L12 备注缺传感器型号 / L13 仪表不符合防爆需求 / L14 描述内多余备注行 /
        L15 分度值单位建议"""
        path = os.path.join(
            _ROOT, "ref", "广州兰达不锈钢防爆电子台秤报价单03032026-flintec.xlsx")
        report = audit_file(path)
        codes = {i.code for i in report.active_issues}
        self.assertIn("L3", codes)
        self.assertIn("L9", codes)
        self.assertIn("L12", codes)
        self.assertIn("L13", codes)
        self.assertIn("L14", codes)
        self.assertIn("L15", codes)
        self.assertEqual(1, len(report.doc.items))


class SnapshotEngineTest(unittest.TestCase):
    """快照比对引擎（L25/L26）：claims 归一、快照抽取、diff 判据。

    这一层的价值是「不写规则也能发现不符」——所以测的是**能力**：
    写法变体能认、系列级型号能取到标准配置、缺项与冲突分别定级。
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_snapshot_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_claims_supply_variants(self):
        from COPA.apps.audit import claims as C
        for text, expect in (("供电220VAC", "ac"), ("AC 220V无电源线", "ac"),
                             ("DC24V供电", "dc"), ("24VDC", "dc"),
                             ("内置电池，含充电器", "bat")):
            self.assertEqual(expect, C.extract(text)[C.K_POWER].value, text)

    def test_claims_material_tolerance(self):
        """型号写得比描述细（17-4PH不锈钢 vs 不锈钢）应判相容"""
        from COPA.apps.audit import claims as C
        std = C.extract("传感器材质：17-4PH不锈钢")
        quote = C.extract("传感器材质：不锈钢")
        self.assertTrue(C.compatible(std[C.K_SENSOR_MTL], quote[C.K_SENSOR_MTL]))
        carbon = C.extract("材质：碳钢")
        steel = C.extract("材质：不锈钢")
        self.assertFalse(C.compatible(carbon[C.K_SCALE_MTL], steel[C.K_SCALE_MTL]))

    @needs_desc_text
    def test_snapshot_module_pull_rod(self):
        """52-30ML 的型谱标准描述必须带出「带水平拉杆」"""
        from COPA.apps.audit import modelspec as S
        from COPA.apps.audit.db import Catalog
        snap = S.get(Catalog.get(), "52-30ML")
        assert snap is not None
        self.assertEqual("1", snap.claims()["pull_rod"].value)

    def test_snapshot_only_from_desc_table(self):
        """快照只认描述通表：通表收录的型号有快照，没收的（含秤体）返回 None.

        这一条是给「不拿结构化编码凑快照」立规矩的：FTBR 台秤通表里没有，
        宁可返回 None 让旧规则兜着（L3/L4/L5/L6/L7），也不许用编码解码去拼。
        """
        from COPA.apps.audit import modelspec as S
        from COPA.apps.audit.db import Catalog
        cat = Catalog.get()
        self.assertIsNotNone(S.get(cat, "FTPD-S-020-1212-E"))   # 通表有
        self.assertIsNone(S.get(cat, "FTPD-S-030-0808-E"))      # 通表无
        self.assertIsNone(S.get(cat, "FTBR-C-060-4050"))        # 秤体通表无

    @needs_desc_text
    def test_diff_missing_pull_rod(self):
        path = os.path.join(self.tmp, "diff_pull_rod.xlsx")
        make_quote(path, [[
            "1", "称重模块",
            "52-30ML CS SB14-3000kg-BH-C3 EX\n"
            "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；",
            "只", 3, 2260, 6780,
        ]])
        issues = [i for i in audit_file(path).active_issues if i.code.startswith("L2")]
        self.assertEqual(["L25"], [i.code for i in issues])
        self.assertEqual("red", issues[0].level, "型号蕴含项漏写判红")

    @needs_desc_text
    def test_diff_embedded_instrument_power(self):
        """秤体行描述里带的仪表型号，也要按它自己的快照比供电"""
        path = os.path.join(self.tmp, "diff_embedded.xlsx")
        make_quote(path, [[
            "1", "电子平台秤",
            "型号：SCS-3t EX（FTPD-S-030-1212-E）\n防爆电子平台秤\n"
            "1.材质：全不锈钢；\n2.台面规格：1200*1200；\n"
            "3.量程：3t，分度值e=d=1kg；\n4.防爆传感器SB14*4；\n"
            "5.仪表FT210PA0A0000D（供电220VAC）；",
            "台", 1, 0, 0,
        ]])
        codes = {i.code for i in audit_file(path).active_issues}
        self.assertIn("L26", codes)

    @needs_desc_text
    def test_embedded_model_must_match_exactly(self):
        """描述里夹带的型号按完整写法认，不能拿族名前缀去配无关配置行.

        `FAB3306(FAB3306HX1PN00A)` 里真正选的是 HX1PN00A（AC220V），通表确有
        这一行；若把族名 FAB3306 前缀放宽到 FAB3306D010000D（DC24V），就会
        凭空报一条「供电不符」。
        """
        path = os.path.join(self.tmp, "embedded_exact.xlsx")
        make_quote(path, [[
            "1", "电子台秤",
            "型号：AWBR-C-030-4050\n电子台秤\n1.材质：碳钢；\n"
            "2.台面尺寸：400*500mm；\n3.量程：30kg，分度值e=d=10g；\n"
            "4.称重传感器*1；\n5.仪表FAB3306(FAB3306HX1PN00A)，AC220V供电；",
            "台", 1, 0, 0,
        ]])
        codes = {i.code for i in audit_file(path).active_issues}
        self.assertNotIn("L26", codes, "完整型号本身就是 AC220V，不该报冲突")

        # 换成真的 DC24V 完整型号，同样写 AC220V -> 必须报
        make_quote(path, [[
            "1", "电子台秤",
            "型号：AWBR-C-030-4050\n电子台秤\n1.材质：碳钢；\n"
            "2.台面尺寸：400*500mm；\n3.量程：30kg，分度值e=d=10g；\n"
            "4.称重传感器*1；\n5.仪表FAB3306D010000D，AC220V供电；",
            "台", 1, 0, 0,
        ]])
        codes = {i.code for i in audit_file(path).active_issues}
        self.assertIn("L26", codes)


class SnapshotQtyTest(unittest.TestCase):
    """L27/L28：批阅副本自带快照，型号改了就放行选型，数量改了要单独报.

    口径是「跟输出报价时存下的快照直接 diff」，不做「8 套 × 3 支点」这类
    业务推理——数量变了就是变了，金额是否联动由 L16/L17 管。
    """

    def setUp(self):
        from COPA.apps import Snapshot
        self._snapshot_dir = Snapshot.SNAPSHOT_DIR
        self.tmp = tempfile.mkdtemp(prefix="audit_qty_")
        Snapshot.SNAPSHOT_DIR = self.tmp      # pno.state 查这个临时目录
        self.src = os.path.join(self.tmp, "quote.xlsx")
        make_quote(self.src, [[
            "1", "称重模块",
            "52-30ML CS SB14-3000kg-BH-C3 EX\n"
            "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；",
            "只", 3, 2260, 6780,
        ]])
        self.code = issue_baseline(self.src, self.tmp)   # 模拟出报价
        self.review = self._make_review()

    def tearDown(self):
        from COPA.apps import Snapshot
        Snapshot.SNAPSHOT_DIR = self._snapshot_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_review(self):
        from COPA.apps.audit.annotate import annotate_workbook_ex
        report = audit_file(self.src)
        return annotate_workbook_ex(report, os.path.join(self.tmp, "review")).path

    def _codes(self, path):
        return [i.code for i in audit_file(path).active_issues]

    def _edit(self, path, col, value, row=2):
        from openpyxl import load_workbook
        wb = load_workbook(path)
        wb["报价单"].cell(row, col, value)
        wb.save(path)

    def test_review_carries_no_snapshot(self):
        """批阅副本里不该有任何内部快照：隐藏表、自定义属性都不该有。

        基线只存在项目快照里——客户文件不承载内部数据，也不用担心属性被
        误删、隐藏表被连打印一起带出去。
        """
        from openpyxl import load_workbook
        wb = load_workbook(self.review)
        self.assertEqual(["报价单", "诊断"], wb.sheetnames)
        # openpyxl 存根里没有 custom_doc_props，取不到就当没有自定义属性
        props = getattr(wb, "custom_doc_props", [])
        names = [p.name for p in props]
        self.assertFalse([n for n in names if n.startswith("COPA_SNAPSHOT_")], names)
        wb.close()

    def test_baseline_lives_in_project_snapshot(self):
        """基线落在项目快照的「三、出单记录」，按项目号能反查回来"""
        from COPA.apps.audit import pno
        state = pno.state(self.code)
        assert state is not None
        self.assertEqual(self.code, state.pno)
        self.assertEqual(1, len(state.rows))
        self.assertEqual("3", str(state.rows[0][4]))     # 数量原样存下

    def test_baseline_survives_resave(self):
        """批阅副本被 openpyxl 重存一次，基线照样查得到（基线不在文件里）"""
        from openpyxl import load_workbook
        from COPA.apps.audit import pno
        wb = load_workbook(self.review)
        wb.save(self.review)
        state = pno.state(self.code)
        assert state is not None
        self.assertEqual("3", str(state.rows[0][4]))

    def test_no_snapshot_no_l28(self):
        """没有项目号的原始单：数量无从比对，不许凭空报 L28"""
        plain = os.path.join(self.tmp, "plain.xlsx")
        make_quote(plain, [[
            "1", "称重模块",
            "52-30ML CS SB14-3000kg-BH-C3 EX\n"
            "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；",
            "只", 3, 2260, 6780,
        ]])
        self.assertNotIn("L28", self._codes(plain))

    def test_qty_change_reports_l28_only(self):
        """改数量：型号没变，选型照样校验，只多一条 L28"""
        self._edit(self.review, 5, 8)                     # 数量列
        codes = self._codes(self.review)
        self.assertIn("L28", codes)
        self.assertNotIn("L27", codes, "数量变化不应触发整行免检")
        issues = [i for i in audit_file(self.review).active_issues if i.code == "L28"]
        self.assertIn("快照 3 → 现 8", issues[0].message)

    def test_model_change_skips_selection(self):
        """改型号：按人工确认放行选型，不再报 L25/L26，也不报 L28"""
        self._edit(self.review, 3,
                   "型号：52-30M CS SB14-3000kg-BH-C3 EX\n"
                   "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；")
        codes = self._codes(self.review)
        self.assertIn("L27", codes)
        self.assertNotIn("L25", codes)
        self.assertNotIn("L28", codes)

    def test_new_row_audited_normally(self):
        """插进来的新行没有基线，必须照常全量校验，不能借 override 蒙混"""
        from openpyxl import load_workbook
        wb = load_workbook(self.review)
        ws = wb["报价单"]
        for col, value in enumerate(
                ["2", "电子台秤", "型号：FTPD-S-999-1212-E\n电子台秤", "台", 1, 0, 0], 1):
            ws.cell(3, col, value)
        wb.save(self.review)
        codes = self._codes(self.review)
        self.assertTrue([c for c in codes if c.startswith("L1")],
                        "新增行必须照常校验型号：{}".format(codes))
        self.assertNotIn("L27", codes)

    def test_review_copy_no_diag_noise(self):
        """重新批阅一份批阅副本，不许把自带的诊断页报成 L11"""
        self.assertNotIn("L11", self._codes(self.review))

    def test_qty_annotation_keeps_number(self):
        """数量格的标注不能把数字写成文本：SUM 会静默漏算"""
        from openpyxl import load_workbook
        from COPA.apps.audit.annotate import annotate_workbook_ex
        self._edit(self.review, 5, 8)
        out = annotate_workbook_ex(audit_file(self.review),
                                   os.path.join(self.tmp, "out2")).path
        wb = load_workbook(out)
        cell = wb["报价单"].cell(2, 5)
        assert isinstance(cell.value, int)
        self.assertEqual(8, cell.value)
        assert cell.comment is not None
        wb.close()


class ProjectNoStampTest(unittest.TestCase):
    """项目号落点：A 列倒数第二行，1 号白字，不加批注，不改变表尾行数.

    真实模板（COPA B/样例客户）底部 B 列本来就有说明文字，按整行判空会让每次盖号
    都多长一行，「倒数第二行」就变成「新加的最后一行」——位置约定失效。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_stamp_")
        self.path = os.path.join(self.tmp, "q.xlsx")
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "报价单"
        for row in range(1, 8):
            ws.cell(row, 2, "第{}行说明".format(row))     # B 列有字，A 列全空
        wb.save(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lands_on_second_last_row(self):
        from openpyxl import load_workbook
        from COPA.apps.audit import pno
        wb = load_workbook(self.path)
        before = wb["报价单"].max_row
        code = pno.stamp(wb)
        wb.save(self.path)

        wb2 = load_workbook(self.path)
        ws = wb2["报价单"]
        self.assertEqual(before, ws.max_row, "盖号不该让表尾多长一行")
        cell = ws.cell(before - 1, 1)
        self.assertEqual(code + pno.NOTE, cell.value)
        self.assertEqual(1, cell.font.sz)
        self.assertEqual("FFFFFFFF", cell.font.color.rgb)
        self.assertIsNone(cell.comment, "号码不加批注")
        self.assertEqual(code, pno.find(wb2))

    def test_never_overwrites_column_a(self):
        from openpyxl import load_workbook
        from COPA.apps.audit import pno
        wb = load_workbook(self.path)
        ws = wb["报价单"]
        ws.cell(6, 1, "备注：原有内容")            # 倒数第二行 A 列已有字
        wb.save(self.path)

        wb = load_workbook(self.path)
        code = pno.stamp(wb)
        wb.save(self.path)
        wb2 = load_workbook(self.path)
        ws2 = wb2["报价单"]
        self.assertEqual("备注：原有内容", ws2.cell(6, 1).value)
        self.assertEqual(code + pno.NOTE, ws2.cell(7, 1).value)


class SnapshotBaselineTest(unittest.TestCase):
    """项目号 -> 项目快照的「出单记录」：报价页白字、诊断表、基线必须是同一个号.

    基线不再存在报价单里（隐藏表与文档属性都已废弃），所以「号对不上」这件事
    在数据上不可能发生：号是查基线的唯一钥匙，查不到就等于没有基线。
    """

    def setUp(self):
        from COPA.apps import Snapshot
        from COPA.apps.audit import pno
        self.pno = pno
        self._snapshot_dir = Snapshot.SNAPSHOT_DIR
        self.tmp = tempfile.mkdtemp(prefix="audit_pno_")
        Snapshot.SNAPSHOT_DIR = self.tmp
        self.src = os.path.join(self.tmp, "quote.xlsx")
        make_quote(self.src, [[
            "1", "称重模块",
            "52-30ML CS SB14-3000kg-BH-C3 EX\n"
            "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；",
            "只", 3, 2260, 6780,
        ]])
        self.code = issue_baseline(self.src, self.tmp)    # 出报价：盖号 + 落基线

    def tearDown(self):
        from COPA.apps import Snapshot
        Snapshot.SNAPSHOT_DIR = self._snapshot_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _review(self):
        from COPA.apps.audit.annotate import annotate_workbook_ex
        return annotate_workbook_ex(audit_file(self.src),
                                    os.path.join(self.tmp, "review")).path

    def test_baseline_records_pno(self):
        state = self.pno.state(self.code)
        assert state is not None
        self.assertEqual(self.code, state.pno)
        self.assertIn(self.code, state.title)
        self.assertIn(state.built_at, state.title)

    def test_baseline_heading_is_pno_and_timestamp(self):
        """快照里的那条标题是「项目号 · 时间戳」，能说清哪一单、哪一版"""
        from COPA.apps import Snapshot
        payload = Snapshot.find_order(self.code)
        assert payload is not None
        self.assertRegex(
            "{} · {}".format(self.code, payload["built_at"]),
            r"^COPA\d{6}-\d{4} · \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_diag_sheet_shows_same_pno(self):
        from openpyxl import load_workbook
        wb = load_workbook(self._review())
        ws = wb["诊断"]
        self.assertEqual("项目号", ws["A3"].value)
        self.assertEqual(self.code, ws["B3"].value)
        wb.close()

    def test_unknown_pno_falls_back(self):
        """号查不到出单记录：退回型号 vs 描述比对，不报 L28，并留下说明"""
        from openpyxl import load_workbook
        path = os.path.join(self.tmp, "other.xlsx")
        shutil.copy(self.src, path)
        wb = load_workbook(path)
        ws = wb["报价单"]
        for row in range(ws.max_row, 0, -1):
            value = ws.cell(row, 1).value
            if value and self.code in str(value):
                ws.cell(row, 1, "COPA000101-0001，勿删")
                break
        ws.cell(2, 5, 8)                            # 数量也改了
        wb.save(path)

        report = audit_file(path)
        codes = [i.code for i in report.active_issues]
        self.assertNotIn("L28", codes, "查不到基线就不该报数量不符")
        self.assertTrue(
            any("未在项目快照中找到出单记录" in n for n in report.doc.notes),
            report.doc.notes)

    def test_gui_path_matches_cli(self):
        """界面线程走 read_quote + attach_baseline + audit_doc，结论必须与 CLI 一致.

        少了 attach_baseline 这一步，界面批阅永远不报 L27/L28——人工改动看起来
        跟没改一样，而 CLI 却报，两边说法不一致。
        """
        from openpyxl import load_workbook
        from COPA.apps.audit.db import Catalog
        from COPA.apps.audit.reader import read_quote
        from COPA.apps.audit.runner import attach_baseline, audit_doc

        review = self._review()
        wb = load_workbook(review)
        wb["报价单"].cell(2, 5, 8)                 # 改数量
        wb.save(review)

        cli = sorted(i.code for i in audit_file(review).active_issues)
        catalog = Catalog.get()
        doc = read_quote(review, catalog)
        attach_baseline(doc)
        gui = sorted(i.code for i in audit_doc(doc, catalog).active_issues)
        self.assertEqual(cli, gui)
        self.assertIn("L28", gui)


class SnapshotTotalQtyTest(unittest.TestCase):
    """套数合计 = 一共多少套，属于数量校验第一组：跟快照的套数 diff（L28）"""

    def setUp(self):
        from COPA.apps import Snapshot
        self._snapshot_dir = Snapshot.SNAPSHOT_DIR
        self.tmp = tempfile.mkdtemp(prefix="audit_sum_")
        Snapshot.SNAPSHOT_DIR = self.tmp
        self.src = os.path.join(self.tmp, "sum.xlsx")
        make_quote(self.src, [
            ["1", "称重模块",
             "52-30ML CS SB14-3000kg-BH-C3 EX\n"
             "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；",
             "只", 3, 2260, 6780],
            ["6", "套数合计", None, "套", 8, None, None],
        ])
        self.code = issue_baseline(self.src, self.tmp)
        from COPA.apps.audit.annotate import annotate_workbook_ex
        self.review = annotate_workbook_ex(
            audit_file(self.src), os.path.join(self.tmp, "review")).path

    def tearDown(self):
        from COPA.apps import Snapshot
        Snapshot.SNAPSHOT_DIR = self._snapshot_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_qty_total_recorded(self):
        doc = read_quote(self.src)
        self.assertEqual(1, len(doc.qty_totals))
        total = doc.qty_totals[0]
        self.assertIn("套数合计", total.label)
        self.assertEqual("8", total.qty)
        self.assertEqual(5, total.qty_col)

    def test_qty_total_in_baseline(self):
        """套数合计也要进基线：它是总价的乘数，改它行内算术看不出来"""
        from COPA.apps.audit import pno
        state = pno.state(self.code)
        assert state is not None
        kinds = [str(r[7]) if len(r) > 7 else "" for r in state.rows]
        self.assertIn("sum", kinds)

    def test_qty_total_change_reports_l28(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.review)
        wb["报价单"].cell(3, 5, 10)          # 套数 8 -> 10
        wb.save(self.review)
        issues = [i for i in audit_file(self.review).active_issues if i.code == "L28"]
        self.assertEqual(1, len(issues), "套数改了必须报，且只报一条")
        self.assertIn("快照 8 套 → 现 10 套", issues[0].message)
        self.assertEqual((3, 5), issues[0].anchor)


class BlockQtyTest(unittest.TestCase):
    """L29：段内每套用量与支点数一致（模块 / 上·下安装过渡板）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_blockqty_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _codes(self, rows):
        path = os.path.join(self.tmp, "b.xlsx")
        make_quote(path, rows)
        return [(i.code, i.anchor[0] if i.anchor else 0)
                for i in audit_file(path).active_issues]

    def test_module_count_must_equal_supports(self):
        codes = self._codes([
            ["一", "设备名称：1T模块，3支点，共8套。", None, None, None, None, None],
            ["1", "称重模块", "52-30ML CS SB14-3000kg-BH-C3 EX", "只", 2, 2260, 4520],
        ])
        self.assertIn(("L29", 3), codes)

    def test_transition_plate_count(self):
        codes = self._codes([
            ["一", "设备名称：1T模块，3支点，共8套。", None, None, None, None, None],
            ["1", "称重模块", "52-30ML CS SB14-3000kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "上安装过渡板", "SS 5T", "块", 2, 500, 1000],
            ["3", "下安装过渡板", "SS 5T", "块", 3, 500, 1500],
        ])
        self.assertIn(("L29", 4), codes)      # 上过渡板 2 ≠ 3
        self.assertNotIn(("L29", 5), codes)   # 下过渡板 3 = 3

    def test_consistent_block_silent(self):
        codes = self._codes([
            ["一", "设备名称：1T模块，3支点，共8套。", None, None, None, None, None],
            ["1", "称重模块", "52-30ML CS SB14-3000kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "上安装过渡板", "SS 5T", "块", 3, 500, 1500],
        ])
        self.assertFalse([c for c in codes if c[0] == "L29"])

    def test_four_channel_instrument_skipped(self):
        """4 通道仪表每套配几台有多种可能：标题里有支点数也不参与计算"""
        codes = self._codes([
            ["一", "设备名称：60吨储罐，4支点，4通道仪表，共1套。", None, None, None, None, None],
            ["1", "称重显示控制器", "FAB3306EX4DP00D", "只", 7, 5000, 35000],
        ])
        self.assertFalse([c for c in codes if c[0] == "L29"])

    def test_supports_parse(self):
        from COPA.apps.audit.checks.blockqty import supports
        self.assertEqual(3, supports("设备名称：1T模块，3支点，共8套。"))
        self.assertEqual(4, supports("设备位号：WT-R1010，4支点，共2套"))
        self.assertEqual(2, supports("两支点小平台"))
        self.assertIsNone(supports("设备名称：4通道仪表，DP通讯"))


class PlateTest(unittest.TestCase):
    """L34：过渡板规格（材质 + 典型量程段）与同段模块的映射"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_plate_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _issues(self, rows):
        path = os.path.join(self.tmp, "p.xlsx")
        make_quote(path, rows)
        return [(i.code, i.anchor[0] if i.anchor else 0)
                for i in audit_file(path).active_issues]

    def test_spec_from_name_second_line(self):
        from COPA.apps.audit.reader import read_quote
        from COPA.apps.audit.db import Catalog
        path = os.path.join(self.tmp, "r.xlsx")
        make_quote(path, [["1", "上安装过渡板\nSS 7.5T", "", "块", 3, 500, 1500]])
        item = read_quote(path, Catalog.get()).items[0]
        self.assertEqual("SS 7.5t", item.model)
        self.assertEqual("accessory", item.kind)

    def test_mapping_by_sensor_capacity(self):
        from COPA.apps.audit.checks import plate
        from types import SimpleNamespace

        def mod(text):
            return SimpleNamespace(name=text, model_text=text, model=text.split()[0])

        # 富林泰克：3t 及以下 -> 3t；4536 -> 4.5t；5099 -> 5t；柱式 RC3 -> 22.5t
        self.assertEqual(("SS", 3.0), plate.expectation(
            mod("52-30M SS SB14-2268kg-BH-C3 EX")))
        self.assertEqual(("SS", 4.5), plate.expectation(
            mod("52-30M SS SB14-4536kg-BH-C3 EX")))
        self.assertEqual(("SS", 5.0), plate.expectation(
            mod("52-30M SS SB5-5099kg-BH-C3 EX")))
        self.assertEqual(("SS", 22.5), plate.expectation(
            mod("55-30 SS RC3-7.5T-BH-C3 EX")))

    def test_wrong_capacity_reported(self):
        """珠海锐进的真问题：SB14-4536kg 该配 4.5t，报价写了 5t"""
        codes = self._issues([
            ["一", "设备名称：3T模块，3支点，共1套。", None, None, None, None, None],
            ["1", "称重模块", "52-30M SS SB14-4536kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "上安装过渡板", "SS 5T", "块", 3, 500, 1500],
        ])
        self.assertIn(("L34", 4), codes)

    def test_correct_capacity_silent(self):
        codes = self._issues([
            ["一", "设备名称：3T模块，3支点，共1套。", None, None, None, None, None],
            ["1", "称重模块", "52-30M SS SB5-5099kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "上安装过渡板", "SS 5T", "块", 3, 500, 1500],
        ])
        self.assertFalse([c for c in codes if c[0] == "L34"])

    def test_plate_row_not_reported_as_missing_model(self):
        """过渡板没有型号列，靠规格码识别——不该再跳 L1M"""
        codes = self._issues([
            ["一", "设备名称：3T模块，3支点，共1套。", None, None, None, None, None],
            ["1", "称重模块", "52-30M SS SB5-5099kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "上安装过渡板", "SS 5T", "块", 3, 500, 1500],
            ["3", "下安装过渡板", "SS 5T", "块", 3, 500, 1500],
        ])
        self.assertFalse([c for c in codes if c[0] == "L1M"])


class CableTest(unittest.TestCase):
    """L32：只比单据上显式写的长度，不按台数折算总长"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_cable_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _codes(self, rows):
        path = os.path.join(self.tmp, "c.xlsx")
        make_quote(path, rows)
        return [(i.code, i.anchor[0] if i.anchor else 0)
                for i in audit_file(path).active_issues]

    def test_platform_default_five(self):
        base: dict = dict(capacity=3000, face="1500*1500", ex=True,
                    supply="220VAC", extra="7.信号电缆{}米。")
        ok = self._codes([["1", "电子平台秤",
                           _desc("FTPD-S-030-1515-E", **dict(base, extra=base["extra"].format(5))),
                           "台", 1, 0, 0]])
        bad = self._codes([["1", "电子平台秤",
                            _desc("FTPD-S-030-1515-E", **dict(base, extra=base["extra"].format(15))),
                            "台", 1, 0, 0]])
        self.assertFalse([c for c in ok if c[0] == "L32"], ok)
        self.assertIn(("L32", 2), bad)

    def test_module_uses_cable_row(self):
        """模块的长度写在「信号电缆」那一行的数量里，不在描述里"""
        rows = [
            ["一", "设备名称：1T模块，3支点，共1套。", None, None, None, None, None],
            ["1", "称重模块", "52-30ML CS SB14-3000kg-BH-C3 EX", "只", 3, 2260, 6780],
            ["2", "信号电缆", "AWG-26/3", "米", 15, 8, 120],
        ]
        self.assertIn(("L32", 4), self._codes(rows))
        rows[2][4] = 10
        self.assertFalse([c for c in self._codes(rows) if c[0] == "L32"])

    def test_bench_not_checked(self):
        codes = self._codes([["1", "电子台秤",
                              _desc("FTBR-C-060-4050", capacity=60, face="400*500",
                                    extra="7.信号电缆25米。"),
                              "台", 1, 0, 0]])
        self.assertFalse([c for c in codes if c[0] == "L32"])


class ExplosionPositionTest(unittest.TestCase):
    """L6：台秤也有防爆位（E=防爆 / 非防爆不跟后缀），不按品类豁免"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_ex_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _codes(self, rows):
        path = os.path.join(self.tmp, "e.xlsx")
        make_quote(path, rows)
        return [i.code for i in audit_file(path).active_issues]

    def test_bench_missing_e_suffix(self):
        """兰达 261027：描述写整秤防爆，型号 FTBR-HS-003-2430 没有 -E"""
        rows = [["1", "电子台秤",
                 _desc("FTBR-HS-003-2430", capacity=3, face="240*300", ex=True,
                       supply="24VDC", extra="6.整秤防爆等级：EX d ib IIB T4 Gb"),
                 "台", 1, 0, 0]]
        self.assertIn("L6", self._codes(rows))

    def test_bench_with_e_suffix_passes(self):
        rows = [["1", "电子台秤",
                 _desc("FTBR-HS-003-2430-E", capacity=3, face="240*300", ex=True,
                       supply="24VDC", extra="6.整秤防爆等级：EX d ib IIB T4 Gb"),
                 "台", 1, 0, 0]]
        self.assertNotIn("L6", self._codes(rows))


class HeaderBaselineTest(unittest.TestCase):
    """L35-L38：条目抬头是这一段的规格基线.

    抬头自己写错时，逐行看型号是看不出来的（行内自洽、整段错），所以拿抬头
    当基线单独校验。标定量程的口径与 engine 同源：≥ 料重、不直接等于总重、
    不超过料重 1.5 倍。
    """

    MOD = ("52-30ML CS SB14-3000kg-BH-C3 EX\n"
           "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；")
    MOD_NE = ("52-30ML CS SB14-3000kg-BH-C3\n"
              "传感器材质：17-4PH不锈钢，模块附件材质：合金钢镀镍；带水平拉杆；")
    HEAD = ("设备名称：3T模块，3支点，共1套。设备自重：1t，料重：3t，"
            "总重{}t，标定量程{}t，显示分度值1kg。{}")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_head_")
        self._n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _audit(self, rows):
        self._n += 1
        path = os.path.join(self.tmp, "h{}.xlsx".format(self._n))
        make_quote(path, rows)
        self.last_path = path
        return audit_file(path)

    def _codes(self, rows):
        return [(i.code, i.level) for i in self._audit(rows).active_issues]

    def _module_rows(self, header, tail="", model=None, qty=3):
        rows = [["一", header],
                ["1", "称重模块", model or self.MOD, "只", qty, 2260, 2260 * qty]]
        if tail:
            rows.append(["2", "称重显示控制器", tail, "只", 1, 4200, 4200])
        return rows

    def test_clean_header_passes(self):
        rows = self._module_rows(self.HEAD.format(4, 3, "防爆环境。"))
        self.assertEqual([], self._codes(rows))

    def test_rated_below_load_is_red(self):
        """标定量程低于料重：满料就超量程"""
        rows = self._module_rows(self.HEAD.format(4, 2, ""))
        self.assertEqual([("L35", "red")], self._codes(rows))

    def test_rated_equal_total_is_red(self):
        """标定量程等于总重：把皮重算进量程，分度值被放大"""
        rows = self._module_rows(self.HEAD.format(4, 4, ""))
        self.assertEqual([("L35", "red")], self._codes(rows))

    def test_rated_oversized_is_yellow(self):
        """超过料重 1.5 倍（engine 的 upper_limit_ratio）"""
        rows = self._module_rows(self.HEAD.format(4, 5, ""))
        self.assertEqual([("L36", "yellow")], self._codes(rows))

    def test_total_weight_mismatch(self):
        """总重 ≠ 料重 + 皮重"""
        rows = self._module_rows(self.HEAD.format(9, 3, ""))
        self.assertEqual([("L37", "red")], self._codes(rows))

    def test_span_points_at_the_wrong_number(self):
        """区间要落在填错的那个数上：标定量程 2t / 总重 9t，不是整格"""
        for total, rated, expect in ((4, 2, "2t"), (9, 3, "9t")):
            report = self._audit(self._module_rows(self.HEAD.format(total, rated, "")))
            issue = next(i for i in report.active_issues if i.code in ("L35", "L37"))
            self.assertEqual("cell", issue.span_scope,
                             "抬头区间是相对锚点格的，不能当 desc 坐标再平移")
            ws = load_workbook(self.last_path).active
            text = str(ws.cell(issue.anchor[0], issue.anchor[1]).value)
            self.assertEqual(expect, text[issue.span[0]:issue.span[1]],
                             "抬头问题标错了字：{}".format(issue.message))

    def test_only_total_weight_skips(self):
        """只有总重、没写料重皮重：没有可比对象，整项跳过（用户口径）"""
        header = ("设备名称：3T模块，3支点，共1套。设备与物料总重4t，"
                  "标定量程5t，显示分度值1kg。")
        self.assertEqual([], self._codes(self._module_rows(header)))

    def test_header_comm_not_matched_by_item(self):
        """抬头写 Profibus-DP，仪表描述只有 RS485"""
        ins = ("称重显示控制器\nFAB330（FAB3306HX1DP00D）\n"
               "壁挂安装，1路RS485，DC24V供电；品牌：flintab")
        rows = self._module_rows(self.HEAD.format(4, 3, "仪表，Profibus-DP通信，DC24V。"), ins)
        self.assertIn(("L38", "red"), self._codes(rows))

    def test_header_power_conflict(self):
        """抬头 220VAC，仪表描述 DC24V"""
        ins = ("称重显示控制器\nFAB330（FAB3306HX1DP00D）\n"
               "壁挂安装，1路RS485，DC24V供电；品牌：flintab")
        rows = self._module_rows(self.HEAD.format(4, 3, "仪表，220VAC。"), ins)
        self.assertIn(("L38", "red"), self._codes(rows))

    def test_header_ex_conflict(self):
        """抬头防爆环境，模块型号没有防爆位"""
        rows = self._module_rows(self.HEAD.format(4, 3, "防爆环境。"), model=self.MOD_NE)
        self.assertEqual([("L38", "red")], self._codes(rows))

    def test_header_continuation_row_not_l10(self):
        """抬头另起一行写（阿根廷 B15）：算抬头，不算未识别行"""
        rows = [["一", "模块方案：模块装在罐子下面"],
                ["", "设备3支点，共1套。设备自重：0.3t，料重：1.5t，总重1.8t，"
                     "标定量程2.5t，显示分度值0.5kg。防爆环境。"],
                ["1", "称重模块", self.MOD, "只", 3, 2260, 6780]]
        report = self._audit(rows)
        self.assertNotIn("L10", [i.code for i in report.active_issues])
        block = report.doc.blocks[0]
        self.assertEqual(2, len(block.header_cells), "标题行与续行都要记进抬头")
        self.assertIn("标定量程2.5t", block.header_text)


class MissingModelLevelTest(unittest.TestCase):
    """L1T/L1F 判红：缺具体型号是可追溯性硬伤，不是提示"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_l1t_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_typebatch_only_is_red(self):
        path = os.path.join(self.tmp, "t.xlsx")
        make_quote(path, [[
            "1", "电子台秤",
            _desc("TCS-60kg", capacity=60, face="400*500"),
            "台", 1, 0, 0,
        ]])
        issues = [i for i in audit_file(path).active_issues if i.code == "L1T"]
        self.assertTrue(issues, "只写型批型号必须报 L1T")
        self.assertEqual("red", issues[0].level)

    def test_rules_levels(self):
        from COPA.apps.audit.rules import get_rules
        rules = get_rules()
        self.assertEqual("red", rules.level("L1T"))
        self.assertEqual("red", rules.level("L1F"))


class LegacyEngineTest(unittest.TestCase):
    """旧规则引擎保留可回退（COPA_DESC_ENGINE=rules），不能被新代码顺手改坏"""

    def setUp(self):
        from COPA.apps.audit.rules import get_rules
        self.rules = get_rules()
        self._old = self.rules.desc_engine
        self.rules.desc_engine = "rules"
        self.tmp = tempfile.mkdtemp(prefix="audit_legacy_")

    def tearDown(self):
        self.rules.desc_engine = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_codes(self):
        path = os.path.join(self.tmp, "legacy.xlsx")
        make_quote(path, [[
            "1", "电子台秤",
            _desc("FTBR-C-060-4050", capacity=60, face="400*500", material="不锈钢"),
            "台", 1, 0, 0,
        ]])
        codes = {i.code for i in audit_file(path).active_issues}
        self.assertIn("L5", codes)
        self.assertNotIn("L25", codes)



if __name__ == "__main__":
    unittest.main(verbosity=2)
