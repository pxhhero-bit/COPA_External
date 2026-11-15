"""批阅副本（染色另存）回归：锁住「另存不能毁原件」这条底线.

这里断言的不是"颜色好不好看"，而是三件会真正造成损失的事：
  1. 公式还在不在（data_only=True 存一次，报价单的公式就全变常量）
  2. 合并单元格还在不在（版式塌了，报价单就不能发）
  3. 缺参处的两个空格与批注有没有落到位（L7 的可读性全靠它）

跑法：
    python COPA/tests/test_annotate.py
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from COPA.apps.audit.annotate import (annotate_workbook_ex,   # noqa: E402
                                      AuditExportError, _insert_placeholders)
from COPA.apps.audit.model import LEVEL_RED, LEVEL_YELLOW     # noqa: E402
from COPA.apps.audit.report import annotate_filename          # noqa: E402
from COPA.apps.audit.runner import audit_file                 # noqa: E402

HEADERS = ["序号", "名称", "型号规格、描述", "单位", "数量", "单价(元)", "总价(元)"]

FONT_RED = "FFC00000"
FONT_ORANGE = "FFE36C09"


def _desc(model_line, capacity=60, face="400*500", material="碳钢",
          division=True, ex_text=""):
    lines = ["型号：{}".format(model_line)]
    lines.append("1.材质：{}，花纹钢台面；".format(material))
    if face:
        lines.append("2.台面尺寸：{}mm；".format(face))
    tail = []
    if capacity:
        tail.append("量程：{}kg".format(capacity))
    if division:
        tail.append("分度值e=d=20g")
    if tail:
        lines.append("3." + "，".join(tail) + "；")
    lines.append("供电：内置电池，含充电器；")
    if ex_text:
        lines.append(ex_text)
    return "\n".join(lines)


def make_fixture(path):
    """一张迷你报价单：红行 / 干净行 / L7 缺参行 / 小计行（含公式与合并标题）"""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "报价单"
    ws["A1"] = "某某公司电子秤报价单"
    ws.merge_cells("A1:G1")
    for col, text in enumerate(HEADERS, 1):
        ws.cell(2, col, text)

    rows = [
        # 红行：型号 006=6kg，描述 60kg；台面码 0405 为旧码
        ("1", "电子台秤", _desc("FTBR-C-006-0405", capacity=60), "台", 1, 100),
        # 干净行
        ("2", "电子台秤", _desc("FTBR-C-060-4050"), "台", 2, 200),
        # L7：描述里没有分度值
        ("3", "电子台秤", _desc("FTBR-C-060-4050", division=False), "台", 1, 300),
    ]
    for offset, (seq, name, desc, unit, qty, price) in enumerate(rows, 3):
        ws.cell(offset, 1, seq)
        ws.cell(offset, 2, name)
        ws.cell(offset, 3, desc)
        ws.cell(offset, 4, unit)
        ws.cell(offset, 5, qty)
        ws.cell(offset, 6, price)
        ws.cell(offset, 7, "=E{}*F{}".format(offset, offset))

    ws.cell(6, 2, "小计")
    ws.cell(6, 7, "=SUM(G3:G5)")
    wb.save(path)
    return path


def make_clean_quote(path):
    """只有一行干净明细的单：用来验证「零问题也出副本」"""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "报价单"
    for col, text in enumerate(HEADERS, 1):
        ws.cell(1, col, text)
    for col, value in enumerate(
            ("1", "电子台秤", _desc("FTBR-C-060-4050"), "台", 1, 100), 1):
        ws.cell(2, col, value)
    ws.cell(2, 7, "=E2*F2")
    wb.save(path)
    return path


def make_merged_quote(path):
    """描述列垂直合并（秤体 1 行 + 传感器 N 行共用一格），检查染色会不会串行"""
    headers = ["序号", "名称", "型号", "描述", "单位", "数量", "单价(元)", "总价(元)"]
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "报价单"
    for col, text in enumerate(headers, 1):
        ws.cell(1, col, text)
    ws.cell(2, 1, "1")
    ws.cell(2, 2, "电子台秤")
    ws.cell(2, 3, "FTBR-C-060-4050")
    ws.cell(2, 4, _desc("FTBR-C-060-4050", division=False))
    ws.cell(2, 5, "台")
    ws.cell(2, 6, 1)
    ws.cell(2, 7, 100)
    ws.cell(2, 8, "=F2*G2")
    ws.cell(3, 1, "2")
    ws.cell(3, 2, "连接线缆")
    ws.cell(3, 3, "CABLE-5m")
    ws.cell(3, 5, "根")
    ws.cell(3, 6, 1)
    ws.cell(3, 7, 50)
    ws.cell(3, 8, "=F3*G3")
    ws.merge_cells("D2:D3")
    wb.save(path)
    return path


def _font_of(ws, row, col):
    """字体颜色 rgb；默认主题色返回 None（不是我们写的红）"""
    color = ws.cell(row, col).font.color
    rgb = getattr(color, "rgb", None)
    return rgb if isinstance(rgb, str) else None


def _fill_of(ws, row, col):
    fill = ws.cell(row, col).fill
    return None if fill is None or fill.fill_type is None else fill.start_color.rgb


class AnnotateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_annotate_")
        cls.src = make_fixture(os.path.join(cls.tmp, "样例报价单.xlsx"))
        cls.report = audit_file(cls.src)
        cls.result = annotate_workbook_ex(cls.report, os.path.join(cls.tmp, "out"))
        cls.wb = load_workbook(cls.result.path)
        cls.ws = cls.wb["报价单"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- 文件与命名 -----------------------------------------------------
    def test_output_file(self):
        self.assertTrue(os.path.exists(self.result.path))
        self.assertTrue(self.result.path.endswith(".xlsx"))
        self.assertIn("_批阅_", os.path.basename(self.result.path))
        self.assertTrue(os.path.basename(self.result.path).startswith("样例报价单"))

    def test_xlsm_keeps_extension(self):
        self.assertTrue(annotate_filename("a/b/某单.xlsm").endswith(".xlsm"))

    def test_strip_temp_timestamp_prefix(self):
        name = annotate_filename("temp/20261106_231500_某报价单.xlsx")
        self.assertTrue(name.startswith("某报价单_批阅_"), name)

    # ---- 标注：只改字体，不铺底色 ---------------------------------------
    def test_problem_field_turns_red_bold(self):
        """型号/描述同列时只标问题行，且红黄分级：L3 红、L9 橙"""
        rich = load_workbook(self.result.path, rich_text=True)["报价单"]
        value = rich.cell(3, 3).value
        assert isinstance(value, CellRichText)
        # CellRichText 的元素是 str 或带字体的 TextBlock：只收后者里真正标了色的
        runs = []
        for block in value:
            font = getattr(block, "font", None)
            if font is None:
                continue
            color = getattr(font, "color", None)
            if color is None or getattr(color, "rgb", None) not in (FONT_RED, FONT_ORANGE):
                continue
            if not str(block).strip():
                continue
            runs.append((str(block), color.rgb, font.b))
        reds = [text for text, color, _ in runs if color == FONT_RED]
        oranges = [text for text, color, _ in runs if color == FONT_ORANGE]
        self.assertTrue(any("FTBR-C-006-0405" in text for text in reds),
                        "型号与量程不符，型号行必须标红：{}".format(runs))
        self.assertTrue(any("60kg" in text for text in reds),
                        "量程值段要标红，两处对照才看得出不一致：{}".format(runs))
        self.assertFalse(any("分度值" in text or "20g" in text
                             for text in reds + oranges),
                         "分度值与描述其余部分不参与量程冲突，不许连坐：{}".format(runs))
        self.assertTrue(all(bold for _, _, bold in runs), "标色文字必须加粗")
        plain = [str(block) for block in value if hasattr(block, "font")]
        self.assertTrue(any("材质" in text for text in plain), "其余描述应保留")
        self.assertFalse(any("材质" in text for text in reds + oranges),
                         "只有问题行标色，材质行不该被牵连")

    def test_no_fill_anywhere(self):
        """业务明确要求：不要整行/整格底色，报价单要保持原样"""
        for row in range(1, 7):
            for col in range(1, 8):
                self.assertIsNone(_fill_of(self.ws, row, col),
                                  "第 {} 行第 {} 列不该有底色".format(row, col))

    def test_clean_row_untouched(self):
        for col in range(1, 8):
            self.assertIsNone(_font_of(self.ws, 4, col), "第 4 行是干净行，不该改字体")

    def test_row_without_problem_not_colored(self):
        """同一行只有型号格有问题，名称/序号/数量列保持原样"""
        for col in (1, 2, 5, 6, 7):
            self.assertIsNone(_font_of(self.ws, 3, col),
                              "第 {} 列没被判为问题字段，不该动".format(col))

    # ---- 批注 -----------------------------------------------------------
    def test_comment_carries_evidence(self):
        """批注只留「问题 + 建议」：证据写在 message 里（60kg 那类），
        不再单列期望/实际——用户反馈那两行是重复信息。"""
        comment = self.ws.cell(3, 3).comment
        assert comment is not None, "红行型号格必须有批注"
        text = comment.text
        self.assertIn("L3", text)
        self.assertIn("60kg", text)          # 证据随 message 一起进批注
        self.assertIn("建议", text)
        self.assertNotIn("期望：", text)

    def test_l7_comment_names_missing_param(self):
        comment = self.ws.cell(5, 3).comment
        assert comment is not None, "L7 必须挂批注说明缺什么"
        self.assertIn("分度值", comment.text)

    # ---- L7 占位空格 ----------------------------------------------------
    def test_l7_only_marks_placeholder_not_whole_cell(self):
        """缺参不整格涂红：整段描述变红反而看不出缺在哪"""
        self.assertIsNone(_font_of(self.ws, 5, 3), "缺参格整格不该变红")

    def test_l7_two_spaces_inserted(self):
        rich = load_workbook(self.result.path, rich_text=True)["报价单"]
        value = rich.cell(5, 3).value
        assert isinstance(value, CellRichText), "缺参格应为富文本，以便单独特设空格"
        runs = []
        for block in value:
            font = getattr(block, "font", None)
            if font is None:
                continue
            color = getattr(font, "color", None)
            runs.append((str(block), color.rgb if color is not None else None,
                         font.u))
        marks = [(text, u) for text, color, u in runs if text == "  " and color == FONT_RED]
        self.assertEqual(1, len(marks), "缺参处应有两个深红加粗空格：{}".format(runs))
        self.assertEqual("single", marks[0][1], "占位空格要带下划线，白底上才看得见")

    def test_placeholder_stays_at_label(self):
        """有标签就把空格插在标签后，不另起一行；标记区间覆盖标签本身"""
        text = "1.材质：碳钢；\n2.台面尺寸：400*500mm；\n3.量程：60kg，分度值e=d="
        new, spans = _insert_placeholders(text, ["分度值"])
        self.assertTrue(new.endswith("e=d=  "), new)
        start, end = spans[0]
        self.assertIn("分度值", new[start:end], "标记区间要含标签，否则红字只有两个空格宽")
        self.assertTrue(new[start:end].endswith("  "))

    # ---- 保真 -----------------------------------------------------------
    def test_formulas_survive(self):
        self.assertEqual("=E3*F3", self.ws["G3"].value)
        self.assertEqual("f", self.ws["G3"].data_type)
        self.assertEqual("=SUM(G3:G5)", self.ws["G6"].value)

    def test_merged_title_survives(self):
        self.assertIn("A1:G1", [str(r) for r in self.ws.merged_cells.ranges])

    def test_fidelity_no_warning(self):
        self.assertFalse(self.result.degraded, self.result.warnings)
        before = self.result.fidelity["before"]
        after = self.result.fidelity["after"]
        self.assertEqual(before["merged"], after["merged"])
        self.assertEqual(before["formulas"], after["formulas"])

    # ---- 诊断表 ---------------------------------------------------------
    def test_diag_sheet(self):
        self.assertIn("诊断", self.wb.sheetnames)
        ws = self.wb["诊断"]
        self.assertEqual("报价单批阅结果", ws["A1"].value)
        # 抬头里的项目号必须与快照标题、报价页白字是同一个号
        self.assertEqual("项目号", ws["A3"].value)
        header_row = next(r for r in range(1, ws.max_row + 1)
                          if ws.cell(r, 1).value == "工作表")
        header = [ws.cell(header_row, c).value for c in range(1, 10)]
        self.assertEqual("问题码", header[3])
        codes = {str(ws.cell(r, 4).value)
                 for r in range(header_row + 1, ws.max_row + 1)
                 if ws.cell(r, 4).value}
        self.assertEqual({i.code for i in self.report.active_issues}, codes)

    # ---- 定位与异常 -----------------------------------------------------
    def test_no_skipped_issue(self):
        self.assertEqual([], self.result.skipped)

    def test_passed_report_still_exports(self):
        """全通过的单也要出副本（界面统一提示"已另存为"，不能有时有文件有时没有）"""
        src = make_clean_quote(os.path.join(self.tmp, "干净单.xlsx"))
        report = audit_file(src)
        self.assertTrue(report.passed,
                        [(i.code, i.message) for i in report.active_issues])
        result = annotate_workbook_ex(report, os.path.join(self.tmp, "out2"))
        self.assertTrue(os.path.exists(result.path))
        self.assertIn("诊断", load_workbook(result.path).sheetnames)

    def test_missing_source_raises(self):
        report = audit_file(self.src)
        report.doc.path = os.path.join(self.tmp, "不存在.xlsx")
        with self.assertRaises(AuditExportError):
            annotate_workbook_ex(report, self.tmp)


class L12FillTest(unittest.TestCase):
    """L12 空缺位：整格填黄是「无底色」口径下唯一的底色例外（用户拍板）。
    空的备注格里没有字可红，只能给格子本身上色提示「这里缺东西」。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_l12_")
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "报价单"
        for col, text in enumerate(HEADERS + ["备注"], 1):
            ws.cell(1, col, text)
        ws.cell(2, 1, "1")
        ws.cell(2, 2, "电子台秤")
        ws.cell(2, 3, "型号：FTBR-C-060-4050-E\n电子台秤\n"
                      "1.材质：全304不锈钢，拉丝面罩；\n"
                      "2.台面尺寸：400*500mm；\n"
                      "3.量程：60kg，分度值e=d=20g，精度等级C3；\n"
                      "4.防爆传感器*1；品牌：flintec\n"
                      "5.供电：内置电池（含充电器），配防爆电源；")
        ws.cell(2, 4, "台")
        ws.cell(2, 5, 1)
        ws.cell(2, 6, 100)
        ws.cell(2, 7, "=E2*F2")
        # H 列（备注）留空——L12 就是冲它来的
        cls.src = os.path.join(cls.tmp, "l12缺传感器.xlsx")
        wb.save(cls.src)
        cls.result = annotate_workbook_ex(
            audit_file(cls.src), os.path.join(cls.tmp, "out"))
        cls.wb = load_workbook(cls.result.path)
        cls.ws = cls.wb["报价单"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_remark_cell_filled_yellow(self):
        self.assertEqual("FFFFFF00", _fill_of(self.ws, 2, 8),
                         "空备注格应整格填黄")

    def test_no_other_fill(self):
        for col in range(1, 8):
            self.assertIsNone(_fill_of(self.ws, 1, col))
            self.assertIsNone(_fill_of(self.ws, 2, col),
                              "填黄只落在备注格，描述/型号格不铺底色")

    def test_comment_on_remark_cell(self):
        comment = self.ws.cell(2, 8).comment
        assert comment is not None, "填黄格必须带批注说明缺什么"
        self.assertIn("L12", comment.text)

    def test_desc_cell_font_untouched(self):
        """L12 只填黄备注格，描述格不做字体标注"""
        self.assertIsNone(_font_of(self.ws, 2, 3))


class ArithMarkTest(unittest.TestCase):
    """L16/L17 算术问题的标注路径：总价格红字、小计金额格红字+批注"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_arith_")
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "报价单"
        for col, text in enumerate(HEADERS, 1):
            ws.cell(1, col, text)
        # L16：2 × 100 = 200，总价写 350
        ws.cell(2, 1, "1")
        ws.cell(2, 2, "电子台秤")
        ws.cell(2, 3, _desc("FTBR-C-060-4050"))
        ws.cell(2, 4, "台")
        ws.cell(2, 5, 2)
        ws.cell(2, 6, 100)
        ws.cell(2, 7, 350)
        # L17：小计 500 ≠ 明细 350
        ws.cell(3, 2, "小计")
        ws.cell(3, 7, 500)
        cls.src = os.path.join(cls.tmp, "arith.xlsx")
        wb.save(cls.src)
        cls.report = audit_file(cls.src)
        cls.result = annotate_workbook_ex(cls.report, os.path.join(cls.tmp, "out"))
        cls.wb = load_workbook(cls.result.path)
        cls.ws = cls.wb["报价单"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_issues_detected(self):
        codes = {i.code for i in self.report.active_issues}
        self.assertIn("L16", codes)
        self.assertIn("L17", codes)

    def test_l16_marks_total_cell_red_bold(self):
        """总价格标红加粗，但数值不能被写成富文本：变成文本后 SUM 会漏算"""
        cell = self.ws.cell(2, 7)
        self.assertEqual(350, cell.value)
        assert isinstance(cell.value, int), "总价必须仍是数字"
        self.assertEqual(FONT_RED, _font_of(self.ws, 2, 7))
        self.assertTrue(cell.font.b)

    def test_l17_marks_subtotal_cell_red_bold(self):
        """小计金额格是文件级标注（整格字体），cell.font 直接可读"""
        cell = self.ws.cell(3, 7)
        self.assertEqual(FONT_RED, _font_of(self.ws, 3, 7))
        self.assertTrue(cell.font.b)

    def test_comments_carry_evidence(self):
        c16 = self.ws.cell(2, 7).comment
        c17 = self.ws.cell(3, 7).comment
        self.assertTrue(c16 and "数量" in c16.text, "L16 批注要带算式证据")
        self.assertTrue(c17 and "小计" in c17.text or c17, "L17 批注要落在小计格")


class MergedCellTest(unittest.TestCase):
    """垂直合并的描述块：标注落在锚点上，不能把样式漏到隔壁行"""

    def test_no_leak_to_next_row(self):
        tmp = tempfile.mkdtemp(prefix="audit_merge_")
        try:
            src = make_merged_quote(os.path.join(tmp, "合并.xlsx"))
            report = audit_file(src)
            self.assertIn("L7", {i.code for i in report.active_issues})
            result = annotate_workbook_ex(report, os.path.join(tmp, "out"))
            ws = load_workbook(result.path)["报价单"]

            # 合并区域只有一个样式宿主，描述格改字体后整块共享，属正常；
            # 关键是第 3 行自己的字段一个都不能变。
            self.assertIn("D2:D3", [str(r) for r in ws.merged_cells.ranges])
            self.assertIsNone(_font_of(ws, 3, 2), "第 3 行名称格没被判为问题，不该变红")
            self.assertIsNone(_font_of(ws, 3, 6))
            self.assertIsNone(_fill_of(ws, 2, 2), "不允许铺底色")
            self.assertEqual("=F3*G3", ws["H3"].value, "合并块旁边那一行的公式必须还在")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NamingTest(unittest.TestCase):
    def test_annotate_filename_is_stamped(self):
        name = annotate_filename("x/某单.xlsx", datetime(2026, 11, 6, 23, 0, 0))
        self.assertEqual("某单_批阅_20261106_230000.xlsx", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
