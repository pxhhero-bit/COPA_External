"""Focused acceptance tests for the NO_MATCH fallback adapter.

This file intentionally uses only the standard-library unittest runner so
``python tests/test_fallback.py`` executes all five cases and reports an
unambiguous count.  The fifth case is skipped when Qt is unavailable.
"""

from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# The application contract keeps apps.fallback Qt-free; import it through the
# normal package path so this test exercises the same interface as the CLI.
from COPA.apps.fallback import attach_fallback  # noqa: E402


def _entry(item_type="平台秤", **data):
    values = {
        "m_brand": "FT",
        "W1": 300,
        "material": "不锈钢",
        "台面尺寸": "600x600",
    }
    values.update(data)
    return {
        "quote_info": {"quote_id": 101, "quantity": 1},
        "item_type": item_type,
        "parsed": {"data": values},
    }


class FallbackTests(unittest.TestCase):
    def test_platform_fallback_has_engine_shape_and_real_sensors(self):
        result = {
            "quote_id": 101,
            "item_type": "platform",
            "status": "NO_MATCH",
            "platform": [],
            "platform_diagnostic": {
                "status": "NO_MATCH",
                "evidence": {"reason": "forced test"},
            },
        }
        original = copy.deepcopy(result)

        out = attach_fallback(result, _entry())

        self.assertEqual(result, original)
        self.assertIsNot(out, result)
        self.assertEqual(out["status"], "NO_MATCH")
        self.assertEqual(out["platform_diagnostic"]["status"], "NO_MATCH")
        self.assertTrue(out["fallback"])
        self.assertEqual(out["fallback_note"], "候选来自全量通表，非选型结果")
        self.assertTrue(out["platform"])
        row = out["platform"][0]
        self.assertEqual(set(row), {"platform", "sensors"})
        self.assertEqual(row["platform"]["品牌"], "FT")
        assert isinstance(row["sensors"], list)

        # FT's real platform通表 and sensor DB contain these family/capacity
        # pairs (blind-hole formatting comes from the engine helper).
        all_sensor_models = [
            sensor
            for candidate in out["platform"]
            for sensor in candidate["sensors"]
        ]
        self.assertTrue(
            any(
                sensor.startswith(("SLB-227kg-BH-C3", "SB14-227kg-BH-C3"))
                for sensor in all_sensor_models
            )
        )

    def test_sort_is_same_material_then_capacity_distance_then_model(self):
        out = attach_fallback(
            {"item_type": "bench", "status": "NO_MATCH", "bench": []},
            _entry("台秤", W1=30, material="不锈钢"),
        )
        rows = out["bench"]
        self.assertTrue(rows)
        self.assertEqual(out["status"], "NO_MATCH")

        # The first material group is stainless (S/HS), and within each group
        # distance to the requested 30 kg range is non-decreasing.
        ranks = [0 if row["材质"] in ("S", "HS") else 1 for row in rows]
        self.assertEqual(ranks, sorted(ranks))
        for left, right in zip(rows, rows[1:]):
            if left["材质"] == right["材质"]:
                self.assertLessEqual(
                    abs(float(left["量程"]) - 30),
                    abs(float(right["量程"]) - 30),
                )
        self.assertTrue(
            all(
                set(row) >= {"具体型号", "品牌", "量程", "台面尺寸"}
                for row in rows
            )
        )

    def test_unmatched_sensor_token_is_left_empty_and_non_whole_line_untouched(self):
        # AW's real database does not contain the FT SLB/SB14 tokens on some
        # AW platform rows. The fallback exposes those rows but never invents
        # a sensor model for an unresolved token.
        out = attach_fallback(
            {"item_type": "platform", "status": "NO_MATCH", "platform": []},
            _entry(m_brand="AW", material="碳钢"),
        )
        self.assertTrue(out["platform"])
        aw_row = next(
            row
            for row in out["platform"]
            if "SLB-227kg" in row["platform"].get("可用传感器", "")
        )
        # AWB resolves from the AW DB; unmatched SLB/SB14 tokens are omitted.
        self.assertTrue(all(model.startswith("AWB-") for model in aw_row["sensors"]))

        module = {"item_type": "module", "status": "NO_MATCH", "module": []}
        self.assertEqual(
            attach_fallback(module, _entry("称重模块", m_brand="FT")), module
        )

    def test_non_no_match_and_existing_rows_are_value_preserving_copies(self):
        ok = {"item_type": "platform", "status": "OK", "platform": [{"x": 1}]}
        self.assertEqual(attach_fallback(ok, _entry()), ok)
        self.assertIsNot(attach_fallback(ok, _entry()), ok)

        existing = {
            "item_type": "bench",
            "status": "NO_MATCH",
            "bench": [{"具体型号": "already-selected"}],
        }
        self.assertEqual(attach_fallback(existing, _entry("台秤")), existing)
        self.assertNotIn("fallback", attach_fallback(existing, _entry("台秤")))

    def test_checklist_load_results_has_selectable_fallback_products(self):
        """Real Checklist rendering keeps NO_MATCH while offering choices."""

        try:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication
            from COPA.apps.Checklist import Checklist
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6" or (exc.name or "").startswith("PySide6."):
                self.skipTest("PySide6 unavailable")
            raise

        app = QApplication.instance() or QApplication([])
        result = {
            "quote_id": 101,
            "item_type": "platform",
            "status": "NO_MATCH",
            "platform": [],
            "platform_diagnostic": {
                "status": "NO_MATCH",
                "evidence": {"reason": "forced checklist test"},
            },
        }
        entry = _entry()
        result_with_candidates = attach_fallback(result, entry)
        window = Checklist()
        try:
            window.load_results([result_with_candidates], [entry])
            app.processEvents()

            self.assertEqual(
                window.checklistLayout.count(), 1,
                "Checklist should render the fallback row",
            )
            item = next(iter(window._iter_items()))
            combo = item.productComBox
            self.assertGreater(combo.count(), 1)
            self.assertNotEqual(combo.itemText(0), "无匹配")
            first = combo.currentText()
            combo.setCurrentIndex(1)
            app.processEvents()
            self.assertNotEqual(combo.currentText(), "无匹配")
            self.assertNotEqual(combo.currentText(), first)
            rendered = item.result()
            assert rendered is not None
            self.assertEqual(rendered["status"], "NO_MATCH")
            self.assertEqual(
                rendered["platform_diagnostic"]["status"], "NO_MATCH"
            )
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    # unittest prints ``Ran 5 tests`` (and a skip count when Qt is absent), so
    # a direct invocation cannot silently pass without executing the cases.
    unittest.main(verbosity=2)
