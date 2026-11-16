"""Stdlib tests for the Qt-free COPA conversation core."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from COPA.apps.contract import ContractError
from COPA.apps.llm_chat import (
    ApiDisabledError,
    ChatReply,
    ChatSession,
    ChatSettings,
    DEMO_CONFIRM_TEXT,
    DEMO_TEXT,
    DemoProvider,
    DisabledApiProvider,
    ScriptedProvider,
    demo_payload,
)


def must(value):
    """断言「一定有值」并把 Optional 收窄，省掉每次访问前的判空。"""

    assert value is not None
    return value


def scripted(session):
    """这些用例的提供方一定是 ScriptedProvider，取出来才能读 requests。"""

    provider = session.provider
    assert isinstance(provider, ScriptedProvider)
    return provider


class LlmChatTests(unittest.TestCase):
    def test_system_prompt_and_full_multiturn_context(self):
        provider = ScriptedProvider([ChatReply("第一轮"), ChatReply("第二轮")])
        session = ChatSession(ChatSettings(base_url="https://example.invalid/v1", model="test"), provider)
        session.send("第一条需求")
        session.send("补充第二条")
        self.assertEqual(session.messages[0]["role"], "system")
        self.assertIn("允许多轮澄清", session.messages[0]["content"])
        self.assertIn("message/payload", session.messages[0]["content"])
        self.assertIn("confirmed_by_user 由 COPA 程序填写", session.messages[0]["content"])
        # 第二轮多一条程序 user 消息：防爆未表态时的强制追问。此时还没有
        # 候选、没有可合并的缺项清单，所以追问独立成一条。
        self.assertEqual(
            [m["role"] for m in provider.requests[1]["messages"]],
            ["system", "user", "assistant", "user", "user"],
        )
        self.assertIn("防爆确认", provider.requests[1]["messages"][-2]["content"])
        self.assertEqual(provider.requests[1]["messages"][-1]["content"], "补充第二条")

    def test_payload_reply_keeps_envelope_but_drops_full_payload(self):
        """下一轮只带 message 信封；字段值留在 candidate，靠校验反馈传递。

        完整 payload 回填进历史，等于每轮都把前几轮的字段再念一遍。模型需
        要知道的「还缺什么」由程序重算的反馈注入，不需要回读自己的旧 JSON。
        """

        payload = demo_payload()
        provider = ScriptedProvider([
            ChatReply("候选已生成", payload=payload),
            ChatReply("请继续补充。"),
        ])
        session = ChatSession(provider=provider)
        first = session.send("已明确一条需求")
        assert first.payload is not None
        # 数值本身没有丢：候选里还在，归档的 event 也记了本轮提交的字段名。
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["W1"], 2000)
        self.assertIn("W1", session.events[0]["submitted"])
        session.send("补充现场服务要求")
        assistant = provider.requests[1]["messages"][2]
        envelope = json.loads(assistant["content"])
        self.assertEqual(envelope["message"], "候选已生成")
        self.assertNotIn("payload", envelope)

    def test_api_key_stays_out_of_messages(self):
        provider = ScriptedProvider(["收到"])
        session = ChatSession(ChatSettings(model="m", api_key="secret-key"), provider)
        self.assertNotIn("secret-key", repr(session.settings))
        session.send("普通输入")
        self.assertEqual(provider.requests[0]["api_key"], "secret-key")
        messages = provider.requests[0]["messages"]
        self.assertNotIn("secret-key", repr(messages))
        self.assertNotIn("secret-key", repr(session.messages))

    def test_demo_is_explicit_and_requires_one_clarification(self):
        session = ChatSession(provider=DemoProvider())
        first = session.send(DEMO_TEXT)
        self.assertIsNone(first.payload)
        self.assertIsNone(session.candidate)
        second = session.send("确认以上演示参数，生成结构化候选。")
        assert isinstance(second.payload, dict)
        assert session.candidate is not None
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])
        self.assertTrue(session.preview()["ready"])

    def test_reset_forgets_unfinished_demo_round(self):
        provider = DemoProvider()
        session = ChatSession(provider=provider)
        session.send(DEMO_TEXT)
        session.reset()
        reply = session.send(DEMO_CONFIRM_TEXT)
        self.assertIsNone(reply.payload)

    def test_free_text_does_not_guess_demo_values(self):
        session = ChatSession()
        reply = session.send("帮我选一台 2000kg 台秤")
        self.assertIsNone(reply.payload)
        self.assertIsNone(session.candidate)
        self.assertIn("不会从自由文本猜测", reply.message)

    def test_preview_uses_copy_and_confirm_returns_copy(self):
        payload = demo_payload()
        session = ChatSession(provider=ScriptedProvider([]))
        original = copy.deepcopy(payload)
        session.load_candidate(payload)
        payload["quote"]["confirmed_by_user"] = True
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])
        preview = session.preview()
        self.assertTrue(preview["ready"])
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])
        confirmed = session.confirm(1)
        self.assertTrue(confirmed["quote"]["confirmed_by_user"])
        confirmed["items"][0]["fields"]["W1"] = 1
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["W1"], 2000)
        self.assertFalse(original["quote"]["confirmed_by_user"])

    def test_confirm_count_is_user_verified(self):
        session = ChatSession(provider=ScriptedProvider([]))
        session.load_candidate(demo_payload())
        with self.assertRaisesRegex(ValueError, "COUNT_MISMATCH"):
            session.confirm(2)
        with self.assertRaisesRegex(ValueError, "整数"):
            session.confirm(True)

    def test_new_send_edit_and_reset_invalidate_old_confirmation(self):
        session = ChatSession(provider=ScriptedProvider(["继续", "编辑后"]))
        session.load_candidate(demo_payload())
        session.confirm(1)
        self.assertTrue(must(session.candidate)["quote"]["confirmed_by_user"])
        session.send("新的问题")
        self.assertIsNone(session.candidate)
        session.load_candidate(demo_payload())
        session.confirm(1)
        session.set_draft("正在编辑")
        self.assertIsNone(session.candidate)
        session.load_candidate(demo_payload())
        session.reset()
        self.assertIsNone(session.candidate)
        self.assertEqual(len(session.messages), 1)
        self.assertEqual(session.messages[0]["role"], "system")

    def test_candidate_is_deep_copied_and_model_confirmation_forced_false(self):
        payload = demo_payload()
        payload["quote"]["confirmed_by_user"] = True
        session = ChatSession(provider=ScriptedProvider([]))
        session.load_candidate(payload)
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])
        self.assertTrue(payload["quote"]["confirmed_by_user"])

    def test_preview_reports_contract_errors_without_mutating_candidate(self):
        payload = demo_payload()
        payload["items"][0]["fields"].pop("material")
        session = ChatSession(provider=ScriptedProvider([]))
        session.load_candidate(payload)
        before = must(session.candidate)
        preview = session.preview()
        self.assertFalse(preview["ready"])
        self.assertTrue(any(e["code"] == "MISSING_FIELD" for e in preview["errors"]))
        self.assertEqual(before, must(session.candidate))
        with self.assertRaises(ContractError):
            session.confirm(1)

    def test_disabled_api_has_no_transport(self):
        provider = DisabledApiProvider()
        with self.assertRaises(ApiDisabledError):
            provider.complete({"base_url": "https://example.invalid", "model": "m", "messages": []})
        session = ChatSession(ChatSettings(provider="disabled"))
        reply = session.send("不会联网")
        self.assertIn("未发出网络请求", reply.message)

    def test_core_import_does_not_require_qt(self):
        import COPA.apps.llm_chat as llm_chat
        self.assertNotIn("PySide6", llm_chat.__dict__)
        session = ChatSession(provider=ScriptedProvider(["ok"]))
        self.assertEqual(session.send("hello").message, "ok")


class ProgramFlagTests(unittest.TestCase):
    """附加要求由程序负责：四项弱信号一律 false，防爆未表态才追问。

    模型已经看不到 flags 的 schema 定义；这里验证程序补值、关键词判定、
    追问注入与自动交接口径，全部离线、不联网。
    """

    @staticmethod
    def _bare_payload():
        payload = demo_payload()
        payload["items"][0].pop("flags", None)
        return payload

    @staticmethod
    def _session(*replies):
        return ChatSession(provider=ScriptedProvider(list(replies)))

    def test_model_may_omit_flags_and_program_fills_all_five(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("一台 3t 平台秤")
        flags = must(session.candidate)["items"][0]["flags"]
        self.assertEqual(
            set(flags),
            {"metrology", "high_precision", "ex", "digital", "onsite_service"},
        )
        self.assertFalse(any(flags.values()))
        self.assertFalse([
            e for e in session.preview()["errors"]
            if ".flags" in str(e.get("path", ""))
        ])

    def test_missing_ex_terms_injects_one_program_question(self):
        session = self._session(ChatReply("第一轮"))
        session.send("一台 3t 平台秤")
        messages = scripted(session).requests[0]["messages"]
        self.assertIn("防爆确认", messages[-2]["content"])
        self.assertEqual(messages[-1]["content"], "一台 3t 平台秤")
        self.assertTrue(session.ex_pending)

    def test_affirmative_ex_sets_true_without_question(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("要防爆，等级 IIBT4，一台 3t 平台秤")
        self.assertFalse(session.ex_pending)
        self.assertTrue(must(session.candidate)["items"][0]["flags"]["ex"])
        self.assertNotIn("防爆确认", "\n".join(
            str(m["content"]) for m in scripted(session).requests[0]["messages"]))

    def test_negated_ex_sets_false_without_question(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("不需要防爆，一台 3t 平台秤")
        self.assertFalse(session.ex_pending)
        self.assertFalse(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_decline_reply_releases_the_gate(self):
        session = self._session(
            ChatReply("第一轮"), ChatReply("候选", payload=self._bare_payload()))
        session.send("一台 3t 平台秤")
        self.assertTrue(session.ex_pending)
        session.send("不用")
        self.assertFalse(session.ex_pending)
        self.assertFalse(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_accept_reply_sets_ex_true(self):
        session = self._session(
            ChatReply("第一轮"), ChatReply("候选", payload=self._bare_payload()))
        session.send("一台 3t 平台秤")
        session.send("要")
        self.assertFalse(session.ex_pending)
        self.assertTrue(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_quote_request_does_not_fake_an_ex_answer(self):
        session = self._session(ChatReply("第一轮"), ChatReply("第二轮"))
        session.send("一台 3t 平台秤")
        session.send("没别的了，你报价吧")
        self.assertTrue(session.ex_pending)  # 「没」不是对防爆的回答

    def test_negative_prefix_in_first_round_does_not_fake_a_decision(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("不用不锈钢，用碳钢")
        self.assertTrue(session.ex_pending)  # 还没问过，「不用」不算回答

    def test_stainless_steel_prefix_is_not_read_as_negation(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("不锈钢防爆平台秤")
        self.assertFalse(session.ex_pending)
        self.assertTrue(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_program_ex_overrides_model_value(self):
        payload = self._bare_payload()
        payload["items"][0]["flags"] = {"ex": True}
        session = self._session(ChatReply("候选", payload=payload))
        session.send("不需要防爆")
        self.assertFalse(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_manual_import_is_not_gated_and_keeps_explicit_flags(self):
        session = self._session()
        payload = demo_payload()
        payload["items"][0]["flags"]["ex"] = True
        session.load_candidate(payload)
        self.assertFalse(session.ex_pending)
        self.assertTrue(must(session.candidate)["items"][0]["flags"]["ex"])

    def test_prompt_drops_flags_but_full_schema_keeps_them(self):
        from COPA.apps import contract

        self.assertNotIn('"flags"', contract.print_prompt())
        item = contract.print_schema()["payload_contract"]["$defs"]["item"]
        self.assertIn("flags", item["required"])
        self.assertIn("flags", item["properties"])
        generated = (ROOT / "llm" / "generated" / "prompt.txt").read_text(encoding="utf-8")
        self.assertEqual(generated, contract.print_prompt())

    def test_reset_clears_the_ex_gate(self):
        session = self._session(ChatReply("第一轮"))
        session.send("一台 3t 平台秤")
        self.assertTrue(session.ex_pending)
        session.reset()
        self.assertFalse(session.ex_pending)

    def test_events_record_ex_state(self):
        session = self._session(ChatReply("候选", payload=self._bare_payload()))
        session.send("要防爆")
        self.assertIs(session.events[0]["ex_state"], True)


class StallAndFeedbackTests(unittest.TestCase):
    """校验失败的两条收敛路径：熔断，以及把可选项一起交给模型。

    模型补不动的时候，继续追问只是把用户困在对话里；这里验证程序会在
    同一项连续三轮没修好、或连续两轮没交候选时停下来，并在反馈里给出
    合法取值，而不是让模型盲改。
    """

    @staticmethod
    def _missing(field):
        payload = demo_payload()
        item = payload["items"][0]
        item["fields"].pop(field, None)
        item.get("provenance", {}).pop(field, None)
        return payload

    @staticmethod
    def _session(*replies):
        return ChatSession(provider=ScriptedProvider(list(replies)))

    def test_same_missing_field_three_rounds_stalls(self):
        missing = self._missing("material")
        session = self._session(
            ChatReply("还缺材质", payload=missing),
            ChatReply("还缺材质", payload=missing),
            ChatReply("还缺材质", payload=missing),
        )
        for text in ("一台 3t 平台秤", "材质你定", "随便"):
            session.send(text)
        self.assertTrue(session.preview()["stalled"])
        self.assertIn(
            "当前模式未能推进，建议转选型计算功能再次输入。",
            session.exit_notice or "",
        )
        self.assertIsNone(session.feedback_text)

    def test_fixing_one_field_resets_the_streak(self):
        missing = self._missing("material")
        session = self._session(
            ChatReply("缺材质", payload=missing),
            ChatReply("补上了", payload=demo_payload()),
            ChatReply("缺材质", payload=missing),
        )
        session.send("一台 3t 平台秤")
        session.send("碳钢")
        session.send("换成不锈钢")
        # 中间一轮修好过，计数必须清零，不能被历史累计误判成卡住。
        self.assertFalse(session.preview()["stalled"])

    def test_two_empty_rounds_stall(self):
        session = self._session(ChatReply("收到"), ChatReply("收到"))
        session.send("一台 3t 平台秤")
        session.send("就这样")
        self.assertTrue(session.preview()["stalled"])
        self.assertIn(
            "当前模式未能推进，建议转选型计算功能再次输入。",
            session.exit_notice or "",
        )

    def test_new_user_input_clears_the_stall(self):
        session = self._session(
            ChatReply("收到"), ChatReply("收到"), ChatReply("收到"),
        )
        session.send("一台 3t 平台秤")
        session.send("就这样")
        self.assertTrue(session.preview()["stalled"])
        session.send("补一句：材质碳钢")
        self.assertFalse(session.preview()["stalled"])

    def test_enum_error_carries_allowed_values(self):
        payload = demo_payload()
        payload["items"][0]["fields"]["material"] = "铸铁"
        session = self._session(ChatReply("已收到", payload=payload))
        session.send("一台铸铁平台秤")
        body = session.feedback_text or ""
        self.assertIn('"allowed"', body)
        self.assertIn("碳钢", body)
        self.assertIn("material", body)

    def test_nonstandard_size_carries_the_standard_table(self):
        payload = demo_payload()
        payload["items"][0]["fields"]["台面尺寸"] = "1500x750"
        session = self._session(ChatReply("已收到", payload=payload))
        session.send("1500x750 的平台秤")
        body = session.feedback_text or ""
        self.assertIn("1500x1500", body)
        self.assertIn('"allowed"', body)

    def test_events_record_error_codes_for_attribution(self):
        session = self._session(
            ChatReply("缺材质", payload=self._missing("material")),
        )
        session.send("一台 3t 平台秤")
        recorded = session.events[0]["errors"]
        self.assertTrue(recorded)
        self.assertTrue(any(item["path"].endswith("material") for item in recorded))
        self.assertIsNone(session.events[0]["stall"])


class DeferredToChecklistTests(unittest.TestCase):
    """必要字段继续在对话里问，非必要字段转 Checklist 标红。

    分界线是「缺了补不上」还是「缺了能按默认/留空进清单」：材质、总重这类
    必须项一票否决；高速搅拌这类非必须项不再消耗一轮对话。
    """

    @staticmethod
    def _module_missing_vibration():
        payload = demo_payload()
        payload["items"][0] = {
            "seq": 1,
            "item_type": "称重模块",
            "quantity": 1,
            "fields": {"support": 4, "material": "碳钢", "W1": 2000, "W2": 500},
        }
        return payload

    def test_optional_field_is_not_asked_again(self):
        session = ChatSession(provider=ScriptedProvider([
            ChatReply("收到 4 支点模块", payload=self._module_missing_vibration()),
        ]))
        session.send("4 支点模块，碳钢")
        # vibration 属非必须项：不再追问，改由清单标红。
        self.assertEqual(session.feedback_fields, [])
        self.assertIsNone(session.feedback_text)

    def test_required_field_is_still_asked(self):
        payload = self._module_missing_vibration()
        payload["items"][0]["fields"].pop("material")
        session = ChatSession(provider=ScriptedProvider([
            ChatReply("收到", payload=payload),
        ]))
        session.send("4 支点模块")
        self.assertTrue(session.feedback_text)
        self.assertIn("材质", must(session.feedback_text))

    def test_confirm_leaves_a_trace_for_the_checklist(self):
        session = ChatSession(provider=ScriptedProvider([
            ChatReply("收到", payload=self._module_missing_vibration()),
        ]))
        session.send("4 支点模块，碳钢")
        confirmed = session.confirm(1, force_quote=True)
        provenance = confirmed["items"][0]["provenance"]
        self.assertEqual(
            provenance["vibration"]["source"], "default_unspecified")
        self.assertTrue(provenance["vibration"]["basis"])


if __name__ == "__main__":
    unittest.main()
