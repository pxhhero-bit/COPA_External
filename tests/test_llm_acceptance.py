"""交接计划的端到端验收，全部使用合成需求；不调用 LLM、不发客户报价。"""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from COPA import cli_quote
from COPA.apps.contract import print_schema, payload_to_entries, validate_payload


def sample():
    return {"schema_version": 1, "origin": "llm",
            "schema_fingerprint": print_schema()["schema_fingerprint"],
            "quote": {"project": "自动化验收", "m_brand": "FT", "c_brand": "FT",
                      "quote_title": "COPA B", "declared_count": 1, "confirmed_by_user": True},
            "items": [{"seq": 1, "item_type": "平台秤", "quantity": 1,
                       "flags": {"metrology": False, "high_precision": False, "ex": False, "digital": False, "onsite_service": False},
                       "fields": {"W1": 2000, "material": "碳钢", "台面尺寸": "1500x1500"}}]}


class LlmAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_cli(self, payload, **kwargs):
        path = self.root / "input.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = cli_quote.main([str(path), "--no-gui"], session_root=self.root / "sessions", **kwargs)
        return code, output.getvalue()

    def test_01_valid_platform_and_17_deterministic_rerun(self):
        payload = sample()
        self.assertEqual(self.run_cli(payload)[0], 0)
        self.assertEqual(self.run_cli(payload)[0], 0)
        sessions = sorted((self.root / "sessions").iterdir())
        self.assertEqual(len(sessions), 2, "两次运行不能覆盖归档")
        results = [json.loads((p / "results.json").read_text(encoding="utf-8")) for p in sessions]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0]["status"], "OK")
        self.assertTrue(results[0][0]["platform"])
        self.assertEqual(results[0][0]["_origin"], "llm")

    def test_02_to_08_contract_exits(self):
        changes = [
            ("COUNT_MISMATCH", lambda p: p["quote"].update(declared_count=2)),
            ("NOT_CONFIRMED", lambda p: p["quote"].update(confirmed_by_user=False)),
            ("ITEM_TYPE", lambda p: p["items"][0].update(item_type="平台秤 ")),
            ("ITEM_TYPE", lambda p: p["items"][0].update(item_type="platform")),
            ("MISSING_FIELD", lambda p: p["items"][0]["fields"].pop("material")),
            ("RANGE", lambda p: p["items"][0].update(item_type="称重模块", fields={"W1": 5000, "W2": 450, "support": 2, "vibration": False, "material": "碳钢"})),
            ("NONSTANDARD_SIZE", lambda p: p["items"][0]["fields"].update({"台面尺寸": "3000x3000"})),
        ]
        for expected, change in changes:
            with self.subTest(expected=expected):
                payload = sample()
                change(payload)
                code, output = self.run_cli(payload)
                self.assertEqual(code, 1, output)
                self.assertIn(expected, output)

    def test_09_15_16_nonstandard_and_mixed_no_match(self):
        payload = sample()
        second = copy.deepcopy(payload["items"][0])
        second.update(seq=2, confirmed_nonstandard=True)
        second["fields"]["台面尺寸"] = "3000x3000"
        payload["items"].append(second)
        payload["quote"]["declared_count"] = 2
        code, output = self.run_cli(payload)
        self.assertEqual(code, 0, output)
        folder = next((self.root / "sessions").iterdir())
        results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        self.assertEqual([r["status"] for r in results], ["OK", "NO_MATCH"])
        self.assertEqual(json.loads((folder / "fail.json").read_text(encoding="utf-8"))["status"], "NO_MATCH")
        self.assertIn("候选来自全量通表", (folder / "run.log").read_text(encoding="utf-8"))

    def test_10_ex_ac220v_not_rejected_by_contract(self):
        # 冲突规则 R4（防爆电源）本版整条不实现：电源与防爆的组合不做
        # 契约层拦截，由 engine 的防爆等级筛选决定，人工在清单核对。
        payload = sample()
        payload["items"][0]["flags"]["ex"] = True
        fields = payload["items"][0]["fields"]
        fields.update(required_ex="IIBT4", power="AC220V", c_family="FT220")
        code, output = self.run_cli(payload)
        self.assertEqual(code, 0, output)
        self.assertNotIn("EX_POWER_CONFLICT", output)

    def test_12_carbon_bench_warning(self):
        payload = sample()
        payload["items"][0].update(item_type="台秤")
        payload["items"][0]["fields"].update({"W1": 60, "台面尺寸": "400x500", "安装形式": "一体"})
        code, output = self.run_cli(payload)
        self.assertEqual(code, 0, output)
        self.assertIn("R2_CARBON_STEEL", output)

    def test_13_14_fenced_and_truncated_text(self):
        path = self.root / "raw.txt"
        raw = "说明\n```json\n" + json.dumps(sample(), ensure_ascii=False) + "\n```\n结束"
        path.write_text(raw, encoding="utf-8-sig")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli_quote.main([str(path), "--no-gui"], session_root=self.root / "sessions"), 0)
        path.write_text('{"schema_version":1,"items":[', encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(cli_quote.main([str(path), "--no-gui"], session_root=self.root / "sessions"), 1)
        self.assertIn("原文前200字符", output.getvalue())

    def test_engine_error_exit_and_archive(self):
        result = {"quote_id": 1, "item_type": "platform", "status": "ERROR", "error": "测试计算异常"}
        with patch.object(cli_quote, "_run_engine", return_value=([result], "测试日志\n")):
            code, output = self.run_cli(sample())
        self.assertEqual(code, 2, output)
        folder = next((self.root / "sessions").iterdir())
        self.assertEqual(json.loads((folder / "fail.json").read_text(encoding="utf-8"))["reason"], "测试计算异常")

    def test_missing_catalog_exits_as_environment_error(self):
        from COPA.apps import contract
        payload = sample()
        with patch.object(contract, "_DATA_DIR", self.root / "missing-data"):
            code, output = self.run_cli(payload)
        self.assertEqual(code, 3, output)
        self.assertIn("ENVIRONMENT", output)

    def test_gui_carbon_bench_warning_is_visible(self):
        from PySide6.QtWidgets import QApplication, QLabel
        from COPA.apps.Checklist import Checklist
        from COPA.apps.Desk import EngineService
        app = QApplication.instance() or QApplication([])
        payload = sample()
        payload["items"][0].update(item_type="台秤")
        payload["items"][0]["fields"].update({"W1": 60, "台面尺寸": "400x500", "安装形式": "一体"})
        warnings = validate_payload(payload)
        entries = payload_to_entries(payload)
        cli_quote._attach_validation_warnings(entries, warnings)
        results = EngineService().run_batch(entries)
        checklist = Checklist()
        self.addCleanup(checklist.close)
        checklist.load_results(results, entries)
        cli_quote._mark_checklist_warnings(checklist, entries, results)
        label = checklist.findChild(QLabel, "llmWarning_1")
        assert label is not None
        self.assertIn("碳钢秤架", label.text())
        self.assertFalse(label.isHidden())
        app.processEvents()

    def test_gui_warnings_output_and_snapshot(self):
        from PySide6.QtWidgets import QApplication, QLabel, QFileDialog, QMessageBox
        from COPA.apps.Checklist import Checklist
        from COPA.apps.Desk import EngineService
        from COPA.apps import Snapshot
        from COPA.apps.fallback import attach_fallback
        app = QApplication.instance() or QApplication([])
        payload = sample()
        payload["items"][0]["confirmed_nonstandard"] = True
        payload["items"][0]["fields"]["台面尺寸"] = "3000x3000"
        entries = payload_to_entries(payload)
        result = EngineService().run_batch(entries)[0]
        candidate = attach_fallback(result, entries[0])
        checklist = Checklist()
        self.addCleanup(checklist.close)
        checklist.load_results([candidate], entries)
        cli_quote._mark_checklist_warnings(checklist, entries, [candidate])
        app.processEvents()
        labels = [x.text() for x in checklist.findChildren(QLabel)]
        self.assertTrue(any("非标" in text for text in labels), labels)
        row = next(checklist._iter_items())
        self.assertGreater(row.productComBox.count(), 1)
        row.productComBox.setCurrentIndex(1)
        self.assertNotEqual(row.productComBox.currentText(), "无匹配")
        checklist.close()

        payload = sample()
        payload["items"][0]["flags"]["onsite_service"] = True
        entries = payload_to_entries(payload)
        results = EngineService().run_batch(entries)
        checklist = Checklist()
        self.addCleanup(checklist.close)
        checklist.load_results(results, entries)
        checklist.editCompanyName.setPlainText("自动化测试客户")
        checklist.editContactPerson.setPlainText("测试联系人")
        destination = self.root / "test-only-quote.xlsx"
        saved = []
        checklist.outputSucceeded.connect(lambda: saved.append(cli_quote._save_cli_snapshot(self.root, "自动化验收", entries, checklist)))
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")), \
             patch.object(checklist, "_confirm_output", return_value=True), \
             patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            checklist._output_quote()
        app.processEvents()
        self.assertTrue(destination.is_file())
        self.assertEqual(len(saved), 1)
        self.assertIn("_origin", saved[0].read_text(encoding="utf-8-sig"))
        restored = Snapshot.parse_snapshot(str(saved[0]))
        self.assertTrue(restored["onsite_service"])
        self.assertTrue(restored["checklist"]["onsite_service"])
        self.assertEqual(len(restored["checklist"]["items"]), 1)


if __name__ == "__main__":
    unittest.main()
