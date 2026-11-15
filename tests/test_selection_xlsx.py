"""使用交付的真实选型表验证逐行保留、单位换算与未确认状态。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from COPA.tools.parse_selection_xlsx import mass_kg, parse_selection


class SelectionImportTests(unittest.TestCase):
    def test_mass_units(self):
        half_gram = mass_kg("0.5g")
        assert half_gram is not None
        self.assertAlmostEqual(half_gram, .0005)
        self.assertEqual(mass_kg("3kg"), 3)
        self.assertEqual(mass_kg("1.5吨"), 1500)
        self.assertIsNone(mass_kg("\\"))

    def test_supplied_selection_table(self):
        source = ROOT.parent / "ref" / "称重选型表-20261026.xlsx"
        if not source.exists():
            self.skipTest("将原始 ref 放在 COPA 同级目录后执行真实表格回归")
        result = parse_selection(source)
        payload = result["payload"]
        self.assertEqual(payload["quote"]["declared_count"], 5)
        self.assertFalse(payload["quote"]["confirmed_by_user"])
        self.assertEqual([x["item_type"] for x in payload["items"]],
                         ["电子天平", "台秤", "台秤", "台秤", "平台秤"])
        self.assertEqual([x["fields"]["W1"] for x in payload["items"]], [3, 3, 12, 60, 600])
        self.assertEqual(payload["items"][2]["fields"]["台面尺寸"], "305x305")
        self.assertEqual(payload["items"][1]["fields"]["power"], "AC220V")
        self.assertIsNone(payload["items"][1]["fields"]["m_brand"])
        self.assertIsNone(payload["items"][1]["flags"]["high_precision"])
        self.assertEqual(result["source_evidence"][0]["cells"]["M3"]["value"], "0.1g")
        self.assertTrue(any(x["code"] == "ITEM_TYPE" for x in result["clarifications"]))


if __name__ == "__main__":
    unittest.main()
