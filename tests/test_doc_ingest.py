"""文件抽取的离线回归：本版只支持文本类文件（含老式 .doc / .xls / CSV），全程零网络。"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from COPA.apps import doc_ingest as di

_HTML = """<html><head><title>报价单</title><style>.x{color:red}</style></head>
<body>
<h1>需求清单</h1>
<p>3米*3米&nbsp;碳钢平台秤 &amp; 防爆仪表</p>
<table><tr><th>名称</th><th>数量</th></tr><tr><td>平台秤</td><td>2台</td></tr></table>
<script>var secret = "不应出现";</script>
</body></html>"""


class LocalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_xlsx_uses_markdown_table_without_coordinates(self):
        from openpyxl import Workbook

        path = self.root / "需求.xlsx"
        book = Workbook()
        sheet = book.active
        assert sheet is not None
        sheet.title = "清单"
        sheet["A1"] = "台面尺寸"
        sheet["B1"] = "1500x1500"
        book.save(path)
        text = di.read_document(path)
        self.assertIn("【工作表：清单】", text)
        self.assertIn("| 台面尺寸 | 1500x1500 |", text)
        self.assertIn("| --- | --- |", text)
        self.assertNotIn("A1=", text)

    def test_title_row_is_not_mistaken_for_header(self):
        from openpyxl import Workbook

        path = self.root / "需求.xlsx"
        book = Workbook()
        sheet = book.active
        assert sheet is not None
        sheet["A1"] = "电子秤选型表"
        sheet["A2"], sheet["B2"] = "名称", "数量"
        sheet["A3"], sheet["B3"] = "平台秤", "2台"
        book.save(path)
        text = di.read_document(path)
        self.assertIn("电子秤选型表\n| 名称 | 数量 |", text)
        self.assertIn("| 平台秤 | 2台 |", text)

    def test_docx_keeps_paragraph_and_table_in_order(self):
        from docx import Document

        path = self.root / "需求.docx"
        document = Document()
        document.add_paragraph("3米*3米碳钢平台秤")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "数量"
        table.cell(0, 1).text = "2台"
        document.save(str(path))
        text = di.read_document(path)
        self.assertLess(text.index("3米*3米"), text.index("数量"))
        self.assertIn("【表格】", text)
        self.assertIn("| 数量 | 2台 |", text)
        self.assertIn("| --- | --- |", text)

    def test_txt_is_read_verbatim_including_gbk(self):
        path = self.root / "需求.txt"
        path.write_bytes("台面1500x1500\n碳钢平台秤 2台".encode("gbk"))
        text = di.read_document(path)
        self.assertIn("台面1500x1500", text)
        self.assertIn("碳钢平台秤 2台", text)

    def test_md_keeps_headings_and_table_pipes(self):
        path = self.root / "需求.md"
        path.write_text(
            "# 需求清单\n\n| 设备 | 台面尺寸 |\n| --- | --- |\n| 平台秤 | 1500x1500 |\n",
            encoding="utf-8",
        )
        text = di.read_document(path)
        self.assertIn("# 需求清单", text)
        self.assertIn("| 平台秤 | 1500x1500 |", text)

    def test_html_keeps_table_structure_and_drops_noise(self):
        path = self.root / "需求.html"
        path.write_text(_HTML, encoding="utf-8")
        text = di.read_document(path)
        self.assertIn("需求清单", text)
        self.assertIn("3米*3米 碳钢平台秤 & 防爆仪表", text)
        self.assertIn("名称 | 数量", text)
        self.assertIn("平台秤 | 2台", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("报价单", text)  # head 整段跳过

    def test_html_respects_declared_gbk_charset(self):
        path = self.root / "需求.html"
        path.write_bytes('<meta charset="gbk"><p>碳钢平台秤</p>'.encode("gbk"))
        self.assertIn("碳钢平台秤", di.read_document(path))

    def test_htm_suffix_is_supported(self):
        path = self.root / "需求.htm"
        path.write_text("<p>台面1500x1500</p>", encoding="utf-8")
        self.assertTrue(di.is_supported(path))
        self.assertIn("台面1500x1500", di.ingest(path).text)

    def test_filter_only_lists_current_formats(self):
        for suffix in ("*.txt", "*.md", "*.csv", "*.html", "*.docx", "*.doc", "*.xlsx"):
            self.assertIn(suffix, di.FILE_FILTER)
        for suffix in ("*.pptx", "*.png", "*.pdf"):
            self.assertNotIn(suffix, di.FILE_FILTER)
        for name in ("清单.txt", "清单.md", "清单.csv", "方案.doc", "方案.docx"):
            self.assertTrue(di.is_supported(name), name)
        self.assertIn("md", di.SUPPORTED_HINT)
        self.assertIn("CSV", di.SUPPORTED_HINT)
        self.assertIn(".doc", di.SUPPORTED_HINT)

    def test_pdf_is_explicitly_rejected(self):
        path = self.root / "扫描件.pdf"
        path.write_bytes(b"%PDF-1.4")
        with self.assertRaises(di.IngestError) as raised:
            di.ingest(path)
        self.assertIn("暂不支持 PDF", str(raised.exception))
        self.assertIn("另存为", str(raised.exception))

    def test_image_and_ppt_are_rejected(self):
        for name in ("照片.png", "方案.pptx"):
            with self.assertRaises(di.IngestError) as raised:
                di.ingest(self.root / name)
            self.assertIn("本版暂不支持", str(raised.exception))
            self.assertIn("自行转换", str(raised.exception))

    def test_unknown_suffix_and_missing_file(self):
        path = self.root / "notes.bin"
        path.write_bytes(b"\x00\x01\x02")
        with self.assertRaises(di.IngestError) as raised:
            di.ingest(path)
        self.assertIn("自行转换", str(raised.exception))
        with self.assertRaises(di.IngestError):
            di.ingest(self.root / "不存在.xlsx")

    def test_ingest_txt_marks_source(self):
        path = self.root / "需求.txt"
        path.write_text("台面1500x1500", encoding="utf-8")
        result = di.ingest(path)
        self.assertEqual(result.text, "台面1500x1500")
        self.assertEqual(result.source, "需求.txt")
        self.assertTrue(any("本地读取" in note for note in result.warnings))

    def test_ingest_marks_source_and_local_origin(self):
        path = self.root / "需求.html"
        path.write_text("<p>台面1500x1500</p>", encoding="utf-8")
        result = di.ingest(path)
        self.assertEqual(result.source, "需求.html")
        self.assertTrue(any("本地读取" in note for note in result.warnings))

    def test_empty_document_is_reported(self):
        path = self.root / "空.html"
        path.write_text("<script>var a=1;</script>", encoding="utf-8")
        with self.assertRaises(di.IngestError) as raised:
            di.ingest(path)
        self.assertIn("没有抽取到可用文本", str(raised.exception))

    def test_compose_message_marks_source_and_forbids_guessing(self):
        result = di.IngestResult("台面 1500x1500", "需求.xlsx", [])
        message = di.compose_message(result)
        self.assertIn("《需求.xlsx》", message)
        self.assertIn("未写明的字段一律视为未提供", message)
        self.assertTrue(message.endswith("台面 1500x1500"))


class CsvAndLegacyDocTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_csv_uses_markdown_table_without_coordinates(self):
        path = self.root / "需求.csv"
        path.write_text(
            "设备,台面尺寸,数量\n平台秤,1500x1500,2台\n台秤,300x400,1台\n",
            encoding="utf-8",
        )
        text = di.read_document(path)
        self.assertIn("| 设备 | 台面尺寸 | 数量 |", text)
        self.assertIn("| --- | --- | --- |", text)
        self.assertIn("| 平台秤 | 1500x1500 | 2台 |", text)
        self.assertNotIn("A1=", text)

    def test_csv_handles_gbk_and_semicolon_delimiter(self):
        path = self.root / "需求.csv"
        path.write_bytes("设备;数量\n碳钢平台秤;2台".encode("gbk"))
        text = di.read_document(path)
        self.assertIn("| 设备 | 数量 |", text)
        self.assertIn("| 碳钢平台秤 | 2台 |", text)

    def test_csv_quoted_comma_is_not_split(self):
        path = self.root / "需求.csv"
        path.write_text('备注,数量\n"防爆,二区IIBT4",2\n', encoding="utf-8")
        text = di.read_document(path)
        self.assertIn("| 防爆,二区IIBT4 | 2 |", text)

    def test_cell_text_escapes_pipes_and_folds_newlines(self):
        self.assertEqual(di._cell_text("a|b\n c"), "a\\|b c")
        self.assertEqual(di._cell_text(None), "")

    def test_message_prefix_explains_markdown_syntax(self):
        message = di.compose_message(di.IngestResult("内容", "需求.xlsx", []))
        self.assertIn("标准 Markdown 表格", message)
        self.assertIn("没有单元格坐标或行列号", message)
        self.assertIn("按表头语义自行理解并转成 JSON 字段", message)
        self.assertNotIn("A1=", message)

    def test_clean_doc_text_maps_word_controls(self):
        raw = "标题\r单元格A\x07单元格B\x07\r\x13INCLUDETEXT\x14值\x15"
        self.assertEqual(di._clean_doc_text(raw), "标题\n单元格A | 单元格B\n值")

    def test_html_disguised_as_doc_falls_back_to_text(self):
        path = self.root / "方案.doc"
        path.write_text("<html><body><p>3米*3米碳钢平台秤</p></body></html>", encoding="utf-8")
        result = di.ingest(path)
        self.assertIn("3米*3米碳钢平台秤", result.text)
        self.assertTrue(any("另存为 .docx" in note for note in result.warnings))

    def test_real_legacy_doc_binary_is_readable(self):
        workspace = Path(__file__).resolve().parents[2]
        candidates = sorted((workspace / "ref" / "技术方案").glob("*.doc"))
        if not candidates:
            self.skipTest("工作区没有真实 .doc 样本")
        text = di.read_document(candidates[0])
        self.assertGreater(len(text), 200)
        self.assertTrue(any(word in text for word in ("称重", "COPA A", "技术")))


class LegacyXlsTests(unittest.TestCase):
    """老式 .xls（BIFF8）：这里只喂字节流，不依赖本机 Excel 生成的样本。"""

    @staticmethod
    def _record(kind: int, body: bytes) -> bytes:
        return struct.pack("<HH", kind, len(body)) + body

    def test_xls_suffix_is_supported(self):
        self.assertIn(".xls", di.TEXT_SUFFIXES)
        self.assertIn("*.xls", di.FILE_FILTER)
        self.assertIn(".xls", di.SUPPORTED_HINT)
        self.assertTrue(di.is_supported("清单.xls"))

    def test_sst_reads_utf16_and_survives_segment_split(self):
        whole = (struct.pack("<II", 1, 1) + struct.pack("<HB", 3, 0x01)
                 + "平台秤".encode("utf-16le"))
        self.assertEqual(di._parse_sst([whole]), ["平台秤"])

        # 字符数据被 CONTINUE 切开时，下一段首字节是新的 fHighByte。
        first = struct.pack("<II", 1, 1) + struct.pack("<HB", 4, 0x00) + b"AB"
        second = b"\x00" + b"CD"
        self.assertEqual(di._parse_sst([first, second]), ["ABCD"])

    def test_sheet_parses_label_number_rk_and_mulrk(self):
        labelsst = self._record(
            0x00FD, struct.pack("<HHHI", 0, 0, 0, 0))            # A1 = SST[0]
        number = self._record(
            0x0203, struct.pack("<HHH", 0, 1, 0) + struct.pack("<d", 3000.0))
        rk_int = self._record(
            0x027E, struct.pack("<HHH", 1, 0, 0) + struct.pack("<I", (2 << 2) | 0x02))
        mulrk = self._record(
            0x00BD,
            struct.pack("<HH", 1, 1)
            + struct.pack("<H", 0) + struct.pack("<I", (1 << 2) | 0x02)
            + struct.pack("<H", 0) + struct.pack("<I", (1200 << 2) | 0x02)
            + struct.pack("<H", 2),
        )
        stream = (self._record(0x0809, b"\x00\x06\x05\x00" + b"\x00" * 12)
                  + labelsst + number + rk_int + mulrk
                  + self._record(0x000A, b""))
        warnings: list[str] = []
        table = di._parse_sheet(stream, 0, ["台面尺寸"], warnings, "Sheet1")
        self.assertIn("台面尺寸", table)
        self.assertIn("3000", table)
        self.assertIn("1200", table)
        self.assertEqual(warnings, [])

    def test_html_disguised_as_xls_falls_back_to_table(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "清单.xls"
            path.write_text(
                "<html><body><table><tr><td>平台秤</td><td>2</td></tr></table></body></html>",
                encoding="utf-8",
            )
            result = di.ingest(path)
            self.assertIn("平台秤", result.text)
            self.assertTrue(any("网页格式" in note for note in result.warnings))
        finally:
            tmp.cleanup()

    def test_empty_sheet_does_not_crash(self):
        stream = self._record(0x0809, b"\x00\x06\x05\x00" + b"\x00" * 12) \
            + self._record(0x000A, b"")
        warnings: list[str] = []
        self.assertEqual(di._parse_sheet(stream, 0, [], warnings, "空表"), "")


class RequirementGateTests(unittest.TestCase):
    def test_real_requirements_pass(self):
        for text in (
            "一台富林泰克3吨平台秤，常规精度",
            "序号 | 名称 | 规格 | 数量\n1 | 平台秤 | 1500x1500 | 2",
            "不锈钢防爆电子台秤，台面1200x1200，量程3吨",
            # 外贸报价单常整份英文，不能因为没中文就被挡回去。
            "Electronic Platform Scale, capacity 3t, carbon steel deck 1500x1500",
            "Item: load cell | Qty: 4 | Unit Price: 120",
        ):
            self.assertTrue(di.has_requirement(text), text)

    def test_unrelated_documents_are_rejected(self):
        for text in (
            "这是一份会议纪要，讨论明年预算安排与人员调整，请各同事确认。",
            "下周团建安排：周六上午九点在公司楼下集合，记得带伞。",
            "abc",
            "",
        ):
            self.assertFalse(di.has_requirement(text), text)


class DialogWiringTests(unittest.TestCase):
    def test_compiled_ui_exposes_attach_button(self):
        source = (Path(__file__).resolve().parents[1] / "apps" / "Ui_llmChat.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("self.attachButton = QToolButton", source)
        self.assertIn("self.messageEdit = QPlainTextEdit", source)

    def test_chat_exposes_import_handlers(self):
        from COPA.apps.LlmChat import LlmChat

        for name in ("_pick_file", "_ingest_path", "_ingest_finished", "_dropped_file"):
            self.assertTrue(hasattr(LlmChat, name), name)


if __name__ == "__main__":
    unittest.main()
