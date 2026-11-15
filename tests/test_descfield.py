"""描述字段树与字符区间的契约测试.

这一层的价值全在「区间切出来必须正好是那几个字」——差一个字符，标红就会
偏到隔壁字段上。所以这里不测「解析成功」，只测**切片等于原文**。
"""
import unittest

from COPA.apps.audit import claims as C
from COPA.apps.audit import descfield
from COPA.apps.audit.annotate import _span_ranges


MODULE_DESC = (
    "52-30ML CS SB14-3000kg-BH-C3 EX\n"
    "传感器材质：17-4PH不锈钢，防爆等级：Ex ia ⅡC T6 Ga；带水平拉杆；"
    "模块附件材质：合金钢镀镍；"
)
BENCH_DESC = (
    "1.材质：碳钢，花纹钢台面；\n"
    "2.台面规格：1200*1200mm；\n"
    "3.量程：1000kg，分度值e=d=0.5kg，精度等级C3；\n"
    "4.称重传感器4只，DC24V供电"
)
HEADER_DESC = "设备名称：1T模块，3支点，共8套。仪表，Profibus-DP通信，DC24V。防爆环境。"


class FieldTreeTest(unittest.TestCase):
    def test_every_clause_span_slices_to_its_value(self):
        """所有样本：clause.span 切出来必须等于 clause.value（不差一个字符）"""
        for src in (MODULE_DESC, BENCH_DESC, HEADER_DESC):
            doc = descfield.parse(src)
            self.assertTrue(doc.clauses, src[:20])
            for clause in doc.clauses:
                self.assertEqual(clause.span.text(src), clause.value,
                                 "{} 的区间切偏了".format(clause.name))

    def test_split_on_semicolon_and_comma_only_when_new_field(self):
        doc = descfield.parse(BENCH_DESC)
        names = [c.name for c in doc.clauses if c.name]
        # 「量程：1000kg，分度值e=d=0.5kg」里的逗号要切出分度值
        self.assertIn("量程", names)
        self.assertIn("分度值", names)
        # 「材质：碳钢，花纹钢台面」里的逗号不是新字段，不切
        material = doc.first("材质")
        self.assertIn("花纹钢台面", material.value)

    def test_sequence_number_kept_but_excluded_from_value(self):
        doc = descfield.parse(BENCH_DESC)
        material = doc.first("材质")
        self.assertEqual(material.no, "1")
        self.assertEqual(material.value, "碳钢，花纹钢台面")

    def test_header_sentence_split_by_period(self):
        """条目抬头用「。」断句，抬头校验才拿得到 仪表/供电/防爆 三段"""
        doc = descfield.parse(HEADER_DESC)
        values = [c.value for c in doc.clauses]
        self.assertIn("DC24V", values)
        self.assertIn("防爆环境", values)

    def test_line_numbers(self):
        doc = descfield.parse(BENCH_DESC)
        self.assertEqual(doc.first("量程").line, 2)      # 第三行（0-based）
        self.assertEqual(doc.first("材质").line, 0)

    def test_locate_tolerates_whitespace(self):
        doc = descfield.parse("模块附件材质：合金钢 镀镍；")
        span = doc.locate("合金钢镀镍")
        self.assertIsNotNone(span)
        self.assertEqual(span.text("模块附件材质：合金钢 镀镍；").replace(" ", ""),
                         "合金钢镀镍")

    def test_markdown_view(self):
        md = descfield.parse(BENCH_DESC).to_markdown()
        self.assertIn("| 字段 | 值 |", md)
        self.assertIn("台面规格", md)


class ClaimSpanTest(unittest.TestCase):
    def _assert_span(self, src, key, expect):
        claim = C.extract(src)[key]
        self.assertIsNotNone(claim.span, "{} 没有区间".format(key))
        self.assertEqual(claim.span[0], src.find(expect),
                         "{} 的起点不对".format(key))
        self.assertEqual(src[claim.span[0]:claim.span[1]], expect)

    def test_material_span_is_the_value_only(self):
        # 模块附件材质：合金钢镀镍 -> 只标「合金钢镀镍」，不连「模块附件材质：」
        self._assert_span(MODULE_DESC, C.K_MODULE_MTL, "合金钢镀镍")
        self._assert_span(BENCH_DESC, C.K_SCALE_MTL, "碳钢")

    def test_numeric_spans(self):
        self._assert_span(BENCH_DESC, C.K_CAPACITY, "1000kg")
        self._assert_span(BENCH_DESC, C.K_FACE, "1200*1200")
        self._assert_span(BENCH_DESC, C.K_DIVISION, "0.5kg")

    def test_power_span_covers_unit_suffix(self):
        self._assert_span(BENCH_DESC, C.K_POWER, "DC24V")

    def test_ex_span(self):
        self._assert_span(MODULE_DESC, C.K_EX, "Ex ia ⅡC T6 Ga")

    def test_protocol_span_is_first_hit_only(self):
        """协议可能在不同行各写一次；区间取第一处，不能 min..max 圈住整段"""
        src = "仪表，RS485通信\n备用，RS232通信"
        claim = C.extract(src)[C.K_PROTOCOL]
        self.assertEqual(src[claim.span[0]:claim.span[1]], "RS485")

    def test_line_number_from_tree(self):
        claim = C.extract(BENCH_DESC)[C.K_CAPACITY]
        self.assertEqual(claim.line, 2)

    def test_parse_doc_exposes_fields_with_spans(self):
        doc = C.parse_doc(BENCH_DESC)
        value, raw, span = doc.fields[C.K_CAPACITY]
        self.assertEqual(raw, "1000kg")
        self.assertEqual(span.text(BENCH_DESC), "1000kg")


class HeaderTreeTest(unittest.TestCase):
    """抬头也是描述：同一棵字段树，只是多了「拼接文本 -> 原格」这一层换算."""

    HEAD = ("设备位号：WT-R1008，3支点，共1套。设备自重：1t，料重：3t，"
            "总重4t，标定量程3t，显示分度值1kg。仪表FT210，220VAC。")

    def _weights(self, text):
        from COPA.apps.audit.checks.header import weight_fields
        return weight_fields(descfield.parse(text))

    def test_weight_spans_slice_to_the_value(self):
        weights = self._weights(self.HEAD)
        self.assertEqual({"料重", "皮重", "总重", "标定"}, set(weights))
        for key, (kg, span) in weights.items():
            self.assertEqual(span.text(self.HEAD).lower(),
                             "{}t".format(int(kg / 1000)),
                             "{} 的区间标偏了".format(key))

    def test_bare_value_without_colon(self):
        """抬头常写「总重8t，标定量程6t」——没有冒号也要认成字段"""
        doc = descfield.parse("料重3t，总重8t，标定量程6t")
        self.assertEqual("3t", doc.first("料重").value)
        self.assertEqual("8t", doc.first("总重").value)
        self.assertEqual("6t", doc.first("标定量程").value)

    def test_weight_does_not_steal_the_total(self):
        """「设备自重及料合共总重3t」：这 3t 是总重，不能读成皮重"""
        weights = self._weights("设备自重及料合共总重3t，标定量程3t")
        self.assertNotIn("皮重", weights)

    def test_cellmap_maps_span_back_to_cell(self):
        """跨格拼接的抬头：区间要能换算回「哪一格 + 格内第几个字」"""
        pieces = [(14, 2, "一、模块方案"), (15, 2, "3支点，共1套。料重：3t，总重4t")]
        cmap = descfield.CellMap.build(pieces)
        doc = descfield.parse(cmap.text)
        clause = doc.first("料重")
        self.assertEqual((15, 2), cmap.locate(clause.span)[:2])
        row, col, local = cmap.locate(clause.span)
        self.assertEqual("3t", pieces[1][2][local[0]:local[1]])

    def test_cellmap_prefers_given_text(self):
        """给了 header_text 就以它为准：拼接时被改写过的空白不会让整段落错位"""
        cmap = descfield.CellMap.build([(3, 2, "a b"), (4, 2, "c")], text="a  b\nc")
        self.assertEqual("a  b\nc", cmap.text)
        self.assertEqual((4, 2), cmap.locate(descfield.Span(5, 6))[:2])


class AnnotateSpanTest(unittest.TestCase):
    def test_span_shifted_by_model_line(self):
        """型号与描述同格时，区间要按 desc 在格内的起点整体平移"""
        class Item:
            desc = "模块附件材质：合金钢镀镍；"
        text = "52-30ML SS\n" + Item.desc
        issue = type("I", (), {"span": (7, 12)})()
        ranges = _span_ranges(issue, Item(), text)
        self.assertEqual(len(ranges), 1)
        start, end = ranges[0]
        self.assertEqual(text[start:end], "合金钢镀镍")

    def test_no_span_returns_empty(self):
        class Item:
            desc = "abc"
        issue = type("I", (), {"span": None})()
        self.assertEqual(_span_ranges(issue, Item(), "abc"), [])


if __name__ == "__main__":
    unittest.main()
