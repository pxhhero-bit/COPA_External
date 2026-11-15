"""Headless contract checks for the LLM handoff boundary.

Run with the bundled interpreter (no Qt required):
``python -m unittest -q tests.test_contract``
"""

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from COPA.apps import contract  # noqa: E402
from COPA.apps.contract import (  # noqa: E402
    ContractError,
    build_engine_input,
    payload_to_entries,
    print_prompt,
    print_schema,
    validate_payload,
)


class ContractTests(unittest.TestCase):
    def setUp(self):
        schema = print_schema()
        self.payload = {
            "schema_version": 1,
            "origin": "llm",
            "schema_fingerprint": schema["schema_fingerprint"],
            "quote": {
                "project": "测试项目",
                "m_brand": "FT",
                "c_brand": "FT",
                "quote_title": schema["quote_titles"][0],
                "declared_count": 1,
                "confirmed_by_user": True,
            },
            "items": [{
                "seq": 1,
                "item_type": "平台秤",
                "quantity": 1,
                "flags": {
                    "metrology": False,
                    "high_precision": False,
                    "ex": False,
                    "digital": False,
                    "onsite_service": False,
                },
                "fields": {
                    "W1": 2000,
                    "material": "碳钢",
                    "台面尺寸": "1500x1500",
                },
            }],
        }

    def assert_code(self, payload, code):
        with self.assertRaises(ContractError) as caught:
            validate_payload(payload)
        self.assertIn(code, {error["code"] for error in caught.exception.errors})

    def test_valid_payload_and_strict_translation(self):
        self.assertEqual(validate_payload(self.payload), [])
        entry = payload_to_entries(self.payload)[0]
        translated = build_engine_input(entry, strict=True)
        self.assertEqual(translated["module_data"]["item_type"], "platform")
        self.assertEqual(translated["module_data"]["台面尺寸"], "1500x1500")
        self.assertEqual(translated["module_data"]["c_brand"], "FT")

    def test_count_and_confirmation(self):
        payload = copy.deepcopy(self.payload)
        payload["quote"]["declared_count"] = 2
        self.assert_code(payload, "COUNT_MISMATCH")
        payload = copy.deepcopy(self.payload)
        payload["quote"]["confirmed_by_user"] = False
        self.assert_code(payload, "NOT_CONFIRMED")

    def test_missing_material_and_nonstandard_size(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["fields"].pop("material")
        self.assert_code(payload, "MISSING_FIELD")
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["fields"]["台面尺寸"] = "3000x3000"
        self.assert_code(payload, "NONSTANDARD_SIZE")
        payload["items"][0]["confirmed_nonstandard"] = True
        warnings = validate_payload(payload)
        self.assertIn("NONSTANDARD_SIZE", {warning["code"] for warning in warnings})

    def test_item_type_and_range(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["item_type"] = "platform"
        self.assert_code(payload, "ITEM_TYPE")
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["quantity"] = 0
        self.assert_code(payload, "RANGE")

    def test_r2_warning(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["item_type"] = "台秤"
        payload["items"][0]["fields"]["台面尺寸"] = "300x400"
        payload["items"][0]["fields"]["安装形式"] = "一体"
        warnings = validate_payload(payload)
        self.assertIn("R2_CARBON_STEEL", {warning["code"] for warning in warnings})

    def test_strict_does_not_apply_gui_fallbacks(self):
        payload = copy.deepcopy(self.payload)
        payload["quote"].pop("c_brand")
        # Contract validation reports the missing field before translation.
        self.assert_code(payload, "MISSING_FIELD")
        payload["quote"]["c_brand"] = "FT"
        entry = payload_to_entries(payload)[0]
        entry["parsed"]["data"].pop("c_brand")
        with self.assertRaises(ContractError):
            build_engine_input(entry, strict=True)

    def test_quote_title_follows_m_brand_only(self):
        payload = copy.deepcopy(self.payload)
        payload["quote"]["quote_title"] = "COPA A"  # 模型/手写都可能写错
        self.assertEqual(payload_to_entries(payload)[0]["quote_title"], "COPA B")
        # 仪表品牌跟抬头无关：c_brand=FAB 也仍是 FT 对应的抬头。
        payload["quote"]["c_brand"] = "FAB"
        self.assertEqual(payload_to_entries(payload)[0]["quote_title"], "COPA B")
        payload["quote"]["m_brand"] = "AW"
        payload["quote"]["c_brand"] = "FT"
        self.assertEqual(payload_to_entries(payload)[0]["quote_title"], "COPA A")

    def test_brands_are_quote_level_and_item_copies_are_ignored(self):
        payload = copy.deepcopy(self.payload)
        payload["quote"]["m_brand"] = "AW"
        payload["items"][0]["fields"]["m_brand"] = "FT"
        warnings = validate_payload(payload)
        self.assertIn(
            "items[0].fields.m_brand", {warning["path"] for warning in warnings}
        )
        entry = payload_to_entries(payload)[0]
        self.assertEqual(entry["parsed"]["data"]["m_brand"], "AW")
        self.assertEqual(entry["parsed"]["data"]["c_brand"], "FT")
        # 抬头也按 quote 级的 m_brand 走，不按条目里那个小动作。
        self.assertEqual(entry["quote_title"], "COPA A")

    def test_e_input_unit_is_normalized_to_kg(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["fields"]["e_input"] = "0.1kg"
        entry = payload_to_entries(payload)[0]
        translated = build_engine_input(entry, strict=True)
        self.assertEqual(translated["module_data"]["e_input"], 0.1)
        payload["items"][0]["fields"]["e_input"] = "0.5g"
        entry = payload_to_entries(payload)[0]
        translated = build_engine_input(entry, strict=True)
        self.assertEqual(translated["module_data"]["e_input"], 0.0005)

    def test_schema_describes_complete_payload_and_conditions(self):
        schema = print_schema()
        contract = schema["payload_contract"]
        self.assertEqual(
            contract["required"],
            ["schema_version", "origin", "schema_fingerprint", "quote", "items"],
        )
        self.assertEqual(
            contract["properties"]["quote"]["required"],
            ["project", "m_brand", "c_brand", "declared_count", "confirmed_by_user"],
        )
        item = contract["$defs"]["item"]
        self.assertEqual(
            item["required"],
            ["seq", "item_type", "quantity", "flags", "fields"],
        )
        self.assertEqual(
            item["properties"]["flags"]["required"],
            ["metrology", "high_precision", "ex", "digital", "onsite_service"],
        )
        # 三种产品线共用一份字段定义，必填差异写在条件分支里。
        self.assertEqual(sorted(contract["$defs"]), ["fields", "item"])
        self.assertIn("vibration", contract["$defs"]["fields"]["properties"])
        self.assertNotIn("m_brand", contract["$defs"]["fields"]["properties"])
        conditions = str(item["allOf"])
        self.assertIn("required_ex", conditions)
        self.assertIn("RPM", conditions)
        self.assertIn("vibration", conditions)
        self.assertEqual(schema["sources"]["selection_rules"], "config/selection_rules.json")
        self.assertEqual(schema["sources"]["parser_rules"], "config/parser_rules.json")
        self.assertNotIn("C:\\Users\\", str(schema))
        self.assertIn("payload_contract", print_prompt())
        self.assertIn("confirmed_by_user", print_prompt())

    def test_unknown_install_is_warned_and_does_not_reach_engine(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["fields"]["install"] = "隔爆式"
        warnings = validate_payload(payload)
        self.assertIn("UNKNOWN_FIELD", {warning["code"] for warning in warnings})
        entry = payload_to_entries(payload)[0]
        translated = build_engine_input(entry, strict=True)
        self.assertIsNone(translated["hardware"]["install"])

    def test_structural_fields_are_derived_after_merge(self):
        """seq 与 declared_count 由程序按最终条目算，模型可完全不写。

        顺序很关键：这两项必须在增量合并之后补。合并前按位置补 seq，多条
        报价里「只改第 2 条」会被补成 seq=1，直接改写第 1 条。
        """

        payload = copy.deepcopy(self.payload)
        payload["items"][0].pop("seq")
        payload["quote"].pop("declared_count")
        staged = contract.apply_program_fields(payload)
        # 合并前不动结构字段，交给 fill_structural_fields 在合并后处理。
        self.assertNotIn("seq", staged["items"][0])
        self.assertNotIn("declared_count", staged["quote"])
        filled = contract.fill_structural_fields(staged)
        self.assertEqual(filled["items"][0]["seq"], 1)
        self.assertEqual(filled["quote"]["declared_count"], 1)

    def test_explicit_seq_is_kept_and_declared_count_follows_items(self):
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["seq"] = 7
        payload["quote"]["declared_count"] = 99
        filled = contract.fill_structural_fields(
            contract.apply_program_fields(payload))
        self.assertEqual(filled["items"][0]["seq"], 7)
        # 条数以实际条目为准；界面与 Checklist 都不展示 declared_count，
        # 真正的条数确认由人在预览里做。
        self.assertEqual(filled["quote"]["declared_count"], 1)

    def test_prompt_never_requires_derived_structural_fields(self):
        prompt_schema = contract._prompt_schema()["payload_contract"]
        self.assertNotIn("seq", prompt_schema["$defs"]["item"]["required"])
        self.assertNotIn(
            "declared_count", prompt_schema["properties"]["quote"]["required"])
        # 定义要留着：多条报价里模型仍要靠 seq 指名改哪一条。
        self.assertIn("seq", prompt_schema["$defs"]["item"]["properties"])
        self.assertIn(
            "declared_count", prompt_schema["properties"]["quote"]["properties"])
        # 校验用的 schema 不受影响，手写/归档 payload 仍然是严格结构。
        strict_schema = contract.print_schema()["payload_contract"]
        self.assertIn("seq", strict_schema["$defs"]["item"]["required"])

    def test_protocol_strings_use_parser_engine_codes(self):
        payload = copy.deepcopy(self.payload)
        fields = payload["items"][0]["fields"]
        fields["req_com1"] = "Modbus"
        fields["special_req"] = 1
        fields["req_com2"] = "DP"
        entry = payload_to_entries(payload)[0]
        parsed = entry["parsed"]["data"]
        self.assertEqual(parsed["req_com1"], ["RTU_1", "RTU_2"])
        self.assertEqual(parsed["req_com2"], ["DP"])

        payload = copy.deepcopy(self.payload)
        payload["items"][0]["fields"]["req_com1"] = "RS232+RS485"
        parsed = payload_to_entries(payload)[0]["parsed"]["data"]
        self.assertEqual(parsed["req_com1"], ["basic_2", "RTU_2", "RS232", "RS485"])

    def test_contract_entry_reaches_real_engine(self):
        from COPA.engine import engine

        entry = payload_to_entries(self.payload)[0]
        engine_input = build_engine_input(entry, strict=True)
        rules = engine.resolver.rules
        first_loader = engine.DatabaseLoader(rules, "FT")
        controllers = []
        for brand in rules["brands"]["controller_db"]:
            controllers.extend(engine.DatabaseLoader(rules, brand).load_controllers())
        databases = {
            "sensors": first_loader.load_sensors(),
            "modules": first_loader.load_modules(),
            "jbox": first_loader.load_jbox(),
            "platforms": first_loader.load_platforms(),
            "benches": first_loader.load_benches(),
            "controllers": controllers,
        }
        result = engine.run_engine(
            user_input=engine_input,
            resolver=engine.resolver,
            databases=databases,
            quote_id=1,
        )
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result.get("platform"))


if __name__ == "__main__":
    unittest.main()
