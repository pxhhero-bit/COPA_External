"""改造后的契约语义、generated 留痕与 system prompt 规则回归（零网络）。"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from COPA.apps import contract
from COPA.apps.llm_chat import ChatSession


def _payload(fields: dict) -> dict:
    return {
        "schema_version": 1,
        "origin": "llm",
        "schema_fingerprint": contract.print_schema()["schema_fingerprint"],
        "quote": {
            "project": "测试项目", "m_brand": "FT", "c_brand": "FT",
            "quote_title": "COPA B", "declared_count": 1, "confirmed_by_user": True,
        },
        "items": [{
            "seq": 1, "item_type": "台秤", "quantity": 1,
            "flags": {"metrology": False, "high_precision": False, "ex": False,
                      "digital": False, "onsite_service": False},
            "fields": fields,
        }],
    }


class FieldSemanticsTests(unittest.TestCase):
    def test_schema_drops_alias_tables_and_keeps_field_definitions(self):
        semantics = contract.print_schema()["field_semantics"]
        fields = semantics["fields"]
        self.assertNotIn("aliases", fields["W1"])
        self.assertNotIn("mapping", fields["分体仪表支架"])
        self.assertFalse(
            any("aliases" in meta or "mapping" in meta for meta in fields.values())
        )
        self.assertEqual(fields["W1"]["unit"], "kg")
        self.assertIn("最大物料重量", fields["W1"]["hint"])
        self.assertIn("传感器接头", semantics["non_contract_columns"])
        self.assertIn("仪表电源", semantics["optional_columns"])
        self.assertIn("不是穷举", semantics["ignored_note"])
        self.assertIn("自行推断", semantics["note"])

    def test_json_schema_fields_have_chinese_descriptions(self):
        defs = contract.print_schema()["payload_contract"]["$defs"]
        self.assertIn(
            "最大物料重量", defs["fields"]["properties"]["W1"]["description"]
        )
        self.assertIn(
            "设备类型枚举", defs["item"]["properties"]["item_type"]["description"]
        )
        self.assertIn("正整数", defs["item"]["properties"]["quantity"]["description"])

    def test_print_prompt_uses_single_source_and_drops_stale_rules(self):
        prompt = contract.print_prompt()
        self.assertIn("field_semantics", prompt)
        self.assertIn("唯一真源", prompt)
        self.assertNotIn("字段别名", prompt)
        self.assertNotIn("传输层保持禁用", prompt)
        self.assertNotIn("每个从原文识别出的字段保留", prompt)
        self.assertNotIn("表格行号等定位", prompt)


class GeneratedMarkTests(unittest.TestCase):
    def test_marks_are_stripped_recorded_and_source_payload_untouched(self):
        payload = _payload({
            "台面尺寸": "600x800 (generated)",
            "W1": "3 (generated)",
            "material": "不锈钢",
        })
        before = copy.deepcopy(payload)
        normalized = contract.normalize_generated_marks(payload)
        fields = normalized["items"][0]["fields"]
        self.assertEqual(fields["台面尺寸"], "600x800")
        self.assertEqual(fields["W1"], 3)
        assert isinstance(fields["W1"], int)
        self.assertEqual(fields["material"], "不锈钢")
        provenance = normalized["items"][0]["provenance"]
        self.assertEqual(provenance["台面尺寸"]["source"], "generated")
        self.assertEqual(provenance["W1"]["source"], "generated")
        self.assertNotIn("material", provenance)
        self.assertEqual(payload, before)
        self.assertIn("(generated)", json.dumps(payload, ensure_ascii=False))

    def test_chinese_parentheses_and_decimal_number(self):
        payload = _payload({"W1": "12.5 （generated）"})
        fields = contract.normalize_generated_marks(payload)["items"][0]["fields"]
        self.assertEqual(fields["W1"], 12.5)

    def test_no_marks_is_identity_and_idempotent(self):
        plain = _payload({"台面尺寸": "600x800", "material": "不锈钢"})
        self.assertEqual(contract.normalize_generated_marks(plain), plain)
        marked = contract.normalize_generated_marks(
            _payload({"台面尺寸": "600x800 (generated)"})
        )
        self.assertEqual(contract.normalize_generated_marks(marked), marked)

    def test_load_candidate_normalizes_before_staging(self):
        session = ChatSession()
        session.load_candidate(_payload({"台面尺寸": "600x800 (generated)"}))
        candidate = session.candidate
        assert candidate is not None
        self.assertEqual(candidate["items"][0]["fields"]["台面尺寸"], "600x800")
        self.assertEqual(
            candidate["items"][0]["provenance"]["台面尺寸"]["source"], "generated"
        )
        self.assertFalse(candidate["quote"]["confirmed_by_user"])

    def test_normalized_candidate_passes_contract_validation(self):
        payload = _payload({
            "W1": 60, "material": "不锈钢",
            "台面尺寸": "600x800 (generated)", "安装形式": "一体",
        })
        normalized = contract.normalize_generated_marks(payload)
        warnings = contract.validate_payload(normalized)
        self.assertFalse(
            [w for w in warnings if w.get("code") != "SCHEMA_FINGERPRINT"],
        )
        entries = contract.payload_to_entries(normalized)
        self.assertEqual(entries[0]["parsed"]["data"]["台面尺寸"], "600x800")


class SystemPromptRulesTests(unittest.TestCase):
    def test_new_rules_present_and_old_conflicts_removed(self):
        prompt = ChatSession().messages[0]["content"]
        self.assertIn("条目数与 item_type", prompt)
        self.assertIn('{"message":', prompt)
        self.assertIn("quote.m_brand", prompt)
        self.assertIn("non_contract_columns", prompt)
        self.assertIn("按语义自行推断", prompt)
        self.assertIn("只是常见示例，不是穷举", prompt)
        self.assertIn("(generated)", prompt)
        self.assertIn("每个字段最多追问一次", prompt)
        self.assertIn("标准 Markdown", prompt)
        self.assertIn("field_semantics", prompt)
        self.assertNotIn("严禁猜测", prompt)
        self.assertNotIn("不猜测", prompt)
        self.assertNotIn("别名、单位换算与映射见", prompt)
        self.assertNotIn("必须在 message 中逐项追问", prompt)
        self.assertNotIn("本版真实模型传输层保持禁用", prompt)
        self.assertNotIn("表格行号", prompt)


if __name__ == "__main__":
    unittest.main()
