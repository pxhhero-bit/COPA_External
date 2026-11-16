"""校验反馈 LOOP 的离线回归：清单由程序每轮重算，全程零网络。

设计要点（与 2026-11-07 六组实验结论一致，选 D 方案）：
- 程序只产出「当前还缺什么」的事实，措辞/人设/语气交给模型；
- 原始 errors 保留给模型自行修正结构类错误，中文清单只收可追问的错误；
- 反馈只在请求里动态注入，不落 session.messages，旧清单不累积；
- 出口：模型判意图、程序判事实、人点按钮授权，句子触发绝不自动报价。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from COPA.apps.llm_chat import (ChatReply, ChatSession, Provider,
                                ScriptedProvider, demo_payload)

FEEDBACK_MARK = "COPA 契约校验（程序生成，非用户输入）"


def must(value):
    """断言「此处一定有值」，同时把 Optional 收窄给静态检查。

    这些用例断言的正是「这一轮之后就该有候选/反馈」，因此缺值本身就是
    测试失败，用 assert 表达与 assertIsNotNone 等价。
    """

    assert value is not None
    return value


def partial(drop=()):
    """从完整演示候选里删掉若干必填字段，模拟模型的部分候选。"""

    payload = demo_payload()
    fields = payload["items"][0]["fields"]
    provenance = payload["items"][0].get("provenance", {})
    for name in drop:
        fields.pop(name, None)
        provenance.pop(name, None)
    return payload


def module_payload(drop=(), **extra):
    """完整称重模块候选，按需删掉字段，模拟模块线的缺项候选。"""

    payload = demo_payload()
    item = payload["items"][0]
    item["item_type"] = "称重模块"
    item["fields"] = {
        "W1": 5000, "W2": 450, "support": 4, "material": "碳钢",
        "vibration": False,
    }
    item["provenance"] = {}
    for name in drop:
        item["fields"].pop(name, None)
    item["fields"].update(extra)
    return payload


def has_feedback(request):
    return any(FEEDBACK_MARK in str(m.get("content", "")) for m in request["messages"])


class FeedbackLoopTests(unittest.TestCase):
    def test_checklist_shrinks_each_round_and_never_persists_in_history(self):
        provider = ScriptedProvider([
            ChatReply("先提交一版", payload=partial(("material", "台面尺寸"))),
            ChatReply("已合并材质", payload=partial(("台面尺寸",))),
            ChatReply("已合并台面尺寸", payload=demo_payload()),
        ])
        session = ChatSession(provider=provider)
        session.send("需求原文：一台 2000kg 平台秤")
        first_fields = list(session.feedback_fields)
        self.assertEqual(len(first_fields), 2)
        self.assertTrue(any("材质" in x for x in first_fields))
        first_text = must(session.feedback_text)

        session.send("材质用不锈钢，秤体品牌 FT")
        second_fields = list(session.feedback_fields)
        self.assertEqual(len(second_fields), 1)
        self.assertIn("台面尺寸", second_fields[0])
        self.assertNotEqual(first_text, must(session.feedback_text))  # 重算，非缓存

        # 反馈插在本轮输入之前；对话历史里不留痕，下一轮不会累积旧清单。
        messages = provider.requests[1]["messages"]
        self.assertEqual(messages[-1]["content"], "材质用不锈钢，秤体品牌 FT")
        self.assertIn(FEEDBACK_MARK, messages[-2]["content"])
        self.assertIn("缺少材质", messages[-2]["content"])
        for message in session.messages:
            self.assertNotIn(FEEDBACK_MARK, str(message.get("content", "")))

        # 第三轮拿到的是「上一轮结束时」的清单，用户本轮补充排在它后面。
        session.send("台面尺寸 1500x1500")
        self.assertIn("缺少台面尺寸", provider.requests[2]["messages"][-2]["content"])
        self.assertEqual(provider.requests[2]["messages"][-1]["content"], "台面尺寸 1500x1500")
        self.assertIsNone(session.feedback_text)
        self.assertEqual(session.feedback_fields, [])
        self.assertTrue(session.preview()["ready"])

    def test_feedback_is_facts_only_and_keeps_full_error_list(self):
        provider = ScriptedProvider([ChatReply("候选", payload=partial(("material",)))])
        session = ChatSession(provider=provider)
        session.send("需求")
        text = must(session.feedback_text)
        assert text is not None
        self.assertIn(FEEDBACK_MARK, text)
        self.assertIn("程序生成，非用户输入", text)
        self.assertIn('"missing":["缺少材质"]', text)
        self.assertIn("MISSING_FIELD", text)  # 原始 errors 仍交给模型
        self.assertIn("措辞由你决定", text)
        # 程序不生成面向用户的话术
        self.assertNotIn("请确认以下信息", text)
        self.assertNotIn("请补充：", text)

    def test_structural_errors_stay_out_of_chinese_checklist(self):
        payload = demo_payload()
        payload["items"][0]["fields"]["W1"] = "abc"  # TYPE
        payload["items"][0]["fields"].pop("material")  # MISSING_FIELD
        payload["items"][0].get("provenance", {}).pop("material", None)
        provider = ScriptedProvider([ChatReply("候选", payload=payload)])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertEqual(len(session.feedback_fields), 1)
        self.assertIn("材质", session.feedback_fields[0])
        self.assertIn("TYPE", must(session.feedback_text))
        self.assertIn("W1 必须是数值", must(session.feedback_text))

    def test_no_payload_round_recomputes_from_last_candidate_snapshot(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material", "台面尺寸"))),
            ChatReply("请补充材质"),  # 本轮无 payload
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        before = list(session.feedback_fields)
        self.assertEqual(len(before), 2)
        session.send("我再想想")
        # send() 会作废 _candidate，清单必须靠独立快照维持。
        self.assertEqual(session.feedback_fields, before)
        self.assertIn(FEEDBACK_MARK, provider.requests[1]["messages"][-2]["content"])

    def test_ready_candidate_ends_the_loop(self):
        provider = ScriptedProvider([
            ChatReply("完整候选", payload=demo_payload()),
            ChatReply("收到"),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertIsNone(session.feedback_text)
        session.send("确认")
        self.assertFalse(has_feedback(provider.requests[1]))

    def test_no_info_stops_loop_and_new_info_resumes_it(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("好的"),
            ChatReply("再次追问"),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        must(session.feedback_text)
        session.send("没有更多信息了")
        self.assertTrue(session.feedback_stopped)
        self.assertIsNone(session.feedback_text)
        self.assertFalse(has_feedback(provider.requests[1]))
        session.send("材质用不锈钢，仪表品牌 FT")
        self.assertFalse(session.feedback_stopped)
        self.assertTrue(has_feedback(provider.requests[2]))

    def test_long_sentence_with_unclear_word_is_not_mistaken_for_no_info(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("收到"),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("材质我暂时不清楚，量程按 600kg，其余照旧，请继续帮我整理")
        self.assertFalse(session.feedback_stopped)
        must(session.feedback_text)

    def test_reset_clears_all_feedback_state(self):
        provider = ScriptedProvider([ChatReply("缺参候选", payload=partial(("material",)))])
        session = ChatSession(provider=provider)
        session.send("需求")
        must(session.feedback_text)
        session.reset()
        self.assertIsNone(session.feedback_text)
        self.assertEqual(session.feedback_fields, [])
        self.assertFalse(session.feedback_stopped)
        self.assertEqual(len(session.messages), 1)

    def test_external_candidate_load_and_confirm_clear_feedback(self):
        provider = ScriptedProvider([ChatReply("缺参候选", payload=partial(("material",)))])
        session = ChatSession(provider=provider)
        session.send("需求")
        must(session.feedback_text)
        session.load_candidate(demo_payload())
        self.assertIsNone(session.feedback_text)
        session.confirm(1)
        self.assertIsNone(session.feedback_text)
        self.assertEqual(session.feedback_fields, [])


class ExitGateTests(unittest.TestCase):
    """出口设置：句子/intent 只停追问并给提示，授权来自校验通过后的自动交接。"""

    def test_ready_candidate_opens_confirm_without_any_exit_sentence(self):
        provider = ScriptedProvider([ChatReply("候选", payload=demo_payload())])
        session = ChatSession(provider=provider)
        session.send("一台 2000kg 平台秤")
        self.assertEqual(session.exit_state, "awaiting_confirm")
        notice = must(session.take_exit_notice())
        self.assertIn("已通过契约校验", notice)
        self.assertIn("正在生成选型清单", notice)
        self.assertIsNone(session.take_exit_notice())  # 一次性，不重复插
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])

    def test_no_more_info_stops_loop_but_never_quotes(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("好的", payload=partial(("material",))),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没有更多信息了")
        self.assertEqual(session.exit_state, "stopped")
        self.assertTrue(session.feedback_stopped)
        notice = must(session.take_exit_notice())
        self.assertIn("已停止追问", notice)
        self.assertIn("材质", notice)  # 程序及时更新的中文缺参清单
        self.assertFalse(session.preview()["ready"])
        with self.assertRaises(Exception):
            session.confirm(1)

    def test_quote_request_with_incomplete_candidate_is_refused(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("收到", payload=partial(("material",))),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没别的了，你报价吧")
        self.assertEqual(session.exit_state, "stopped")
        notice = must(session.take_exit_notice())
        self.assertIn("不能带缺项进入选型", notice)
        self.assertIn("材质", notice)
        self.assertFalse(session.preview()["ready"])
        with self.assertRaises(Exception):
            session.confirm(1)

    def test_quote_request_with_ready_candidate_still_requires_human_confirm(self):
        provider = ScriptedProvider([
            ChatReply("完整候选", payload=demo_payload()),
            ChatReply("收到", payload=demo_payload()),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertIsNotNone(must(session.take_exit_notice()))  # 消费 ready 兜底消息
        session.send("没别的了，你报价吧")
        self.assertEqual(session.exit_state, "awaiting_confirm")
        self.assertIn("已收到报价请求", must(session.take_exit_notice()))
        # 句子不是授权：仍须人核对条数并点击确认。
        self.assertFalse(must(session.candidate)["quote"]["confirmed_by_user"])
        confirmed = session.confirm(1)
        self.assertTrue(confirmed["quote"]["confirmed_by_user"])
        self.assertEqual(session.exit_state, "confirmed")

    def test_model_intent_is_primary_for_semantically_similar_sentences(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("收到", payload=partial(("material",)), intent="request_quote"),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        # 不在任何关键词表里，只有模型按语义才能判出这是要求报价。
        session.send("剩下的你看着办吧，就按这版走")
        self.assertEqual(session.exit_state, "stopped")
        self.assertIn("不能带缺项进入选型", must(session.take_exit_notice()))

    def test_keyword_fallback_when_model_omits_intent(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("收到", payload=partial(("material",))),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("就这些，直接报价吧")
        self.assertEqual(session.exit_state, "stopped")
        self.assertIn("已收到报价请求", must(session.take_exit_notice()))

    def test_envelope_intent_is_decoded_and_unknown_values_are_ignored(self):
        from COPA.apps.llm_chat import _decode_chat_reply

        raw = json.dumps(
            {"message": "好的", "payload": None, "intent": "no_more_info"},
            ensure_ascii=False,
        )
        self.assertEqual(_decode_chat_reply(raw).intent, "no_more_info")
        self.assertEqual(
            _decode_chat_reply(raw.replace("no_more_info", "something_else")).intent,
            "continue",
        )

    def test_exit_notice_never_enters_model_context(self):
        provider = ScriptedProvider([
            ChatReply("候选", payload=demo_payload()),
            ChatReply("收到", payload=demo_payload()),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertTrue(must(session.take_exit_notice()))
        session.send("继续")
        for index in range(2):
            for message in provider.requests[index]["messages"]:
                self.assertNotIn("程序：", str(message.get("content", "")))
        for message in session.messages:
            self.assertNotIn("程序：", str(message.get("content", "")))

    def test_new_info_resumes_loop_and_clears_stop(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=partial(("material",))),
            ChatReply("好的", payload=partial(("material",))),
            ChatReply("补齐了", payload=demo_payload()),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没有更多信息了")
        self.assertEqual(session.exit_state, "stopped")
        session.send("材质用不锈钢")
        self.assertFalse(session.feedback_stopped)
        # 补上最后一项必须字段后收敛到待确认；再停在 collecting 说明没推进。
        self.assertEqual(session.exit_state, "awaiting_confirm")
        self.assertTrue(has_feedback(provider.requests[2]))

    def test_reset_clears_exit_state(self):
        provider = ScriptedProvider([ChatReply("候选", payload=demo_payload())])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertEqual(session.exit_state, "awaiting_confirm")
        session.reset()
        self.assertEqual(session.exit_state, "collecting")
        self.assertIsNone(session.take_exit_notice())


class ForceQuoteTests(unittest.TestCase):
    """用户坚持报价：程序归一之外的白名单缺项才允许带进选型流程。"""

    def test_tolerated_gaps_are_limited_to_optional_fields(self):
        payloads = [module_payload(("W2",)),
                    module_payload(("W2", "vibration")),
                    module_payload(("RPM",), vibration=True)]
        for index, payload in enumerate(payloads):
            with self.subTest(case=index):
                provider = ScriptedProvider([ChatReply("候选", payload=payload)])
                session = ChatSession(provider=provider)
                session.send("需求")
                self.assertFalse(session.preview()["ready"])
                self.assertTrue(session.force_quote_allowed)
                self.assertNotIn("供电", session.force_quote_labels)
                self.assertNotIn("仪表品牌", session.force_quote_labels)

    def test_hard_required_or_structural_errors_veto_force_quote(self):
        cases = [
            partial(("W1",)),                # 缺总重/量程
            partial(("material",)),          # 缺材质
            partial(("台面尺寸",)),          # 缺台面尺寸
        ]
        bad_power = demo_payload()
        bad_power["items"][0]["fields"]["power"] = "不存在的电源"
        cases.append(bad_power)              # 供电枚举错误
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                provider = ScriptedProvider([ChatReply("候选", payload=payload)])
                session = ChatSession(provider=provider)
                session.send("需求")
                self.assertFalse(session.force_quote_allowed)

    def test_defaults_are_applied_only_when_human_confirms(self):
        provider = ScriptedProvider([
            ChatReply("候选", payload=module_payload(("W2", "vibration")))
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertNotIn("W2", must(session.candidate)["items"][0]["fields"])
        with self.assertRaises(Exception):
            session.confirm(1)  # 不带 force_quote 仍然严格拒绝
        confirmed = session.confirm(1, force_quote=True)
        item = confirmed["items"][0]
        self.assertEqual(item["fields"]["W2"], 0)
        self.assertIs(item["fields"]["vibration"], False)
        self.assertEqual(item["provenance"]["W2"]["source"], "default_unspecified")
        self.assertEqual(item["provenance"]["vibration"]["source"], "default_unspecified")
        self.assertTrue(confirmed["quote"]["confirmed_by_user"])
        self.assertTrue(session.preview()["ready"])

    def test_quote_request_with_tolerated_gaps_opens_confirm(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=module_payload(("W2",))),
            ChatReply("收到", payload=module_payload(("W2",))),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没别的了，你报价吧")
        self.assertEqual(session.exit_state, "awaiting_confirm")
        notice = must(session.take_exit_notice())
        self.assertIn("按默认处理", notice)
        self.assertIn("选型清单", notice)
        self.assertTrue(session.force_quote_allowed)

    def test_no_more_info_with_tolerated_gaps_keeps_default_path_available(self):
        provider = ScriptedProvider([
            ChatReply("缺参候选", payload=module_payload(("W2",))),
            ChatReply("收到", payload=module_payload(("W2",))),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没有更多信息了")
        self.assertEqual(session.exit_state, "stopped")
        self.assertIn("按默认处理并报价", must(session.take_exit_notice()))
        self.assertTrue(session.force_quote_allowed)  # 回复该句即可带默认值交接


class ProgramDefaultTests(unittest.TestCase):
    """总重归一 / c_brand 补齐 / power 直通：确定性补值只由程序完成。"""

    @staticmethod
    def total_weight_payload(total, **explicit):
        payload = demo_payload()
        item = payload["items"][0]
        item["fields"].pop("W1", None)
        item["provenance"].pop("W1", None)
        item["fields"]["W_total"] = total
        item["fields"].update(explicit)
        return payload

    @staticmethod
    def stage(payload):
        session = ChatSession(provider=ScriptedProvider([ChatReply("候选", payload)]))
        session.send("需求")
        return session

    def test_total_weight_only_becomes_w1_and_zero_tare(self):
        session = self.stage(self.total_weight_payload(5000))
        item = must(session.candidate)["items"][0]
        self.assertEqual(item["fields"]["W1"], 5000)
        self.assertEqual(item["fields"]["W2"], 0)
        self.assertNotIn("W_total", item["fields"])
        self.assertEqual(item["provenance"]["W1"]["source"], "total_weight")
        self.assertEqual(item["provenance"]["W2"]["source"], "total_weight")
        self.assertEqual(session.feedback_fields, [])  # 不再误报「缺量程/皮重」
        self.assertTrue(session.preview()["ready"])

    def test_total_weight_with_unit_is_converted_by_program(self):
        session = self.stage(self.total_weight_payload("5t"))
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["W1"], 5000)
        self.assertTrue(session.preview()["ready"])

    def test_model_pre_split_total_weight_gets_matching_provenance(self):
        # 真实模型实测会自己写 W1=总重、W2=0；程序不改写数值，只按 Desk 老口径补留痕。
        payload = demo_payload()
        item = payload["items"][0]
        item["item_type"] = "称重模块"
        item["fields"] = {
            "W1": 5000, "W2": 0, "support": 4, "material": "碳钢",
            "vibration": False,
        }
        item["provenance"] = {}
        session = self.stage(payload)
        staged = must(session.candidate)["items"][0]
        self.assertEqual(staged["fields"]["W1"], 5000)
        self.assertEqual(staged["fields"]["W2"], 0)
        self.assertEqual(staged["provenance"]["W1"]["source"], "total_weight")
        self.assertEqual(staged["provenance"]["W2"]["source"], "total_weight")
        self.assertEqual(session.feedback_fields, [])
        self.assertTrue(session.preview()["ready"])
        from COPA.apps.llm_chat import normalize_program_defaults
        self.assertEqual(normalize_program_defaults(must(session.candidate)), must(session.candidate))

    def test_explicit_split_wins_and_total_is_ignored(self):
        session = self.stage(self.total_weight_payload(9999, W1=2000, W2=450))
        item = must(session.candidate)["items"][0]
        self.assertEqual(item["fields"]["W1"], 2000)
        self.assertEqual(item["fields"]["W2"], 450)
        self.assertNotIn("W_total", item["fields"])
        self.assertNotIn("W1", item["provenance"])

    def test_invalid_total_weight_falls_through_to_contract_type_error(self):
        session = self.stage(self.total_weight_payload("说不清"))
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["W1"], "说不清")
        self.assertIn("W1 必须是数值", must(session.feedback_text))
        self.assertFalse(session.preview()["ready"])

    def test_missing_c_brand_is_filled_on_all_item_types(self):
        # 品牌是整单共用的：c_brand 缺失时按 quote.m_brand 补齐，与条目类型无关。
        platform = demo_payload()
        platform["quote"].pop("c_brand", None)
        bench = demo_payload()
        bench["items"][0]["item_type"] = "台秤"
        bench["items"][0]["fields"]["安装形式"] = "一体"
        bench["items"][0]["confirmed_nonstandard"] = True  # 平台秤尺寸不是台秤通表尺寸
        bench["quote"].pop("c_brand", None)
        module = module_payload()
        module["quote"].pop("c_brand", None)
        for index, payload in enumerate((platform, bench, module)):
            with self.subTest(case=index):
                session = self.stage(payload)
                quote = must(session.candidate)["quote"]
                self.assertEqual(quote["c_brand"], quote["m_brand"])
                self.assertTrue(session.preview()["ready"])
                self.assertFalse(session.force_quote_allowed)  # 不再需要放行通道

    def test_explicit_c_brand_is_never_overwritten(self):
        payload = demo_payload()
        payload["quote"]["c_brand"] = "FAB"
        session = self.stage(payload)
        self.assertEqual(must(session.candidate)["quote"]["c_brand"], "FAB")
        # 抬头只按 m_brand 写死，仪表品牌不同也不改抬头。
        self.assertEqual(must(session.candidate)["quote"]["quote_title"], "COPA B")

    def test_power_missing_is_optional_and_passes_straight_through(self):
        payload = demo_payload()
        payload["items"][0]["fields"].pop("power", None)
        session = self.stage(payload)
        self.assertTrue(session.preview()["ready"])
        self.assertNotIn("power", must(session.candidate)["items"][0]["fields"])
        confirmed = session.confirm(1)  # 正常路径，不需要 force_quote
        from COPA.apps import contract
        entry = contract.payload_to_entries(confirmed)[0]
        engine_input = contract.build_engine_input(entry, strict=True)
        self.assertIsNone(engine_input["hardware"]["power"])

    def test_prompt_states_program_defaults_and_quote_output_boundary(self):
        from COPA.apps import contract
        prompt = ChatSession().messages[0]["content"]
        self.assertIn("【程序归一】", prompt)
        self.assertIn("W_total", prompt)
        self.assertIn("c_brand 缺失时由程序按 m_brand 同值补齐", prompt)
        self.assertIn("power 是契约可选字段", prompt)
        self.assertIn("【输出边界】", prompt)
        self.assertIn("将进入选型流程", prompt)
        self.assertNotIn("将进入报价生成流程", prompt)
        self.assertNotIn("不要用 Markdown 标记", prompt)
        self.assertNotIn("我将为您生成正式报价", prompt)
        exported = contract.print_prompt()
        self.assertIn("W_total", exported)
        self.assertIn("将进入选型流程", exported)
        self.assertNotIn("将进入报价生成流程", exported)
        self.assertEqual((ROOT / "llm" / "generated" / "prompt.txt").read_text(encoding="utf-8"),
                         exported)

    def test_prompt_schema_is_compact_but_still_complete(self):
        """提示词里的 schema 可以压缩，但不能丢结构或取值信息。

        压缩只发生在「给模型看的文本」上：校验仍用 ``print_schema()``，
        fingerprint 不变，字段 enum、必填关系和 sizes 速查表都必须还在。
        """

        import json
        from COPA.apps import contract

        prompt = contract.print_prompt()
        body = prompt.split("schema:", 1)[1].strip()
        body = body.rsplit("}", 1)[0] + "}"
        parsed = json.loads(body)
        # 1. 体积：缩进换行占掉的字符没了。
        self.assertLess(len(prompt), 15000, "压缩后 prompt 仍偏大：{}".format(len(prompt)))
        # 2. schema 是最后一段，紧邻用户消息（模型照着它抄字段名）。
        self.assertTrue(prompt.rstrip().endswith("}"))
        self.assertLess(prompt.index("规则文件"), prompt.index("schema:"))
        # 3. 开发者元数据不进提示词契约，但校验用的 print_schema() 仍然带着。
        for key in ("sources", "schema_version", "schema_fingerprint"):
            self.assertNotIn(key, parsed)
        self.assertTrue(contract.print_schema()["schema_fingerprint"])
        # 4. 枚举仍在 $defs 里，sizes 速查表保留。
        module_fields = parsed["payload_contract"]["$defs"]["fields"]["properties"]
        self.assertIn("碳钢", module_fields["material"]["enum"])
        self.assertIn("平台秤", parsed["sizes"])
        self.assertIn("1200x1200", parsed["sizes"]["平台秤"])
        # 5. 程序填写的字段不再出现在提示词契约里。
        payload = parsed["payload_contract"]
        for key in ("schema_version", "origin", "schema_fingerprint"):
            self.assertNotIn(key, payload["required"])
            self.assertNotIn(key, payload["properties"])
        self.assertNotIn("confirmed_by_user",
                         payload["properties"]["quote"]["required"])

    def test_program_fills_the_four_fixed_fields(self):
        """模型不写 schema_version/origin/fingerprint/confirmed_by_user 也能过校验。"""

        from COPA.apps import contract

        payload = demo_payload()
        for key in ("schema_version", "origin", "schema_fingerprint"):
            payload.pop(key)
        payload["quote"].pop("confirmed_by_user", None)

        try:
            errors = contract.validate_payload(payload)
        except contract.ContractError as exc:
            errors = getattr(exc, "errors", []) or []
        missing = {e["path"] for e in errors if e.get("code") == "MISSING_FIELD"}
        self.assertTrue({"schema_version", "origin", "schema_fingerprint"} <= missing,
                        "前提：原样送校验就是缺这四项")

        filled = contract.apply_program_fields(payload)
        self.assertEqual(filled["schema_version"], 1)
        self.assertEqual(filled["origin"], "llm")
        self.assertEqual(filled["schema_fingerprint"],
                         contract.print_schema()["schema_fingerprint"])
        self.assertIs(filled["quote"]["confirmed_by_user"], False,
                      "确认权在人，程序只置 False")
        try:
            rest = contract.validate_payload(filled)
        except contract.ContractError as exc:
            rest = getattr(exc, "errors", []) or []
        codes = {e["code"] for e in rest}
        self.assertNotIn("MISSING_FIELD", codes)


class SizeDowngradeTests(unittest.TestCase):
    """非标尺寸：放行，但只降级到最近标准规格，并在清单强制人工改回。"""

    @staticmethod
    def payload(size="3000x3000"):
        payload = demo_payload()
        payload["items"][0]["fields"]["台面尺寸"] = size
        payload["items"][0]["provenance"].pop("台面尺寸", None)
        return payload

    def test_only_downgrade_on_human_confirm(self):
        from COPA.apps import contract

        provider = ScriptedProvider([ChatReply("候选", payload=self.payload())])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertFalse(session.preview()["ready"])
        self.assertTrue(session.force_quote_allowed)
        self.assertIn("台面尺寸", "".join(session.force_quote_labels))
        plan = must(contract.nearest_standard_size("平台秤", "3000x3000"))
        self.assertEqual(session.size_downgrades[0]["size"], plan["size"])
        # 暂存值不动：没有人工确认就不改写用户原文。
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["台面尺寸"], "3000x3000")
        with self.assertRaises(Exception):
            session.confirm(1)
        confirmed = session.confirm(1, force_quote=True)
        item = confirmed["items"][0]
        self.assertEqual(item["fields"]["台面尺寸"], plan["size"])
        self.assertEqual(item["provenance"]["台面尺寸"]["source"], "size_downgraded")
        self.assertIn("3000x3000", item["provenance"]["台面尺寸"]["basis"])
        self.assertIn("人工改回", item["provenance"]["台面尺寸"]["basis"])
        self.assertIs(item["confirmed_nonstandard"], True)
        self.assertEqual(item["nonstandard_size"], "3000x3000")
        self.assertTrue(confirmed["quote"]["confirmed_by_user"])

    def test_notice_states_the_downgrade_and_keeps_confirm_open(self):
        provider = ScriptedProvider([
            ChatReply("候选", payload=self.payload()),
            ChatReply("收到", payload=self.payload(), intent="request_quote"),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("没别的了，你报价吧")
        self.assertEqual(session.exit_state, "awaiting_confirm")
        notice = must(session.take_exit_notice())
        self.assertIn("非标尺寸 3000x3000", notice)
        self.assertIn("2000x2000", notice)
        self.assertIn("人工改回", notice)

    def test_unparsable_size_is_still_vetoed(self):
        provider = ScriptedProvider([
            ChatReply("候选", payload=self.payload("说不清"))
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        self.assertFalse(session.force_quote_allowed)
        self.assertEqual(session.size_downgrades, [])


class PartialRoundMergeTests(unittest.TestCase):
    """模型某轮只答一部分时，程序按 seq 继承上一轮候选，不整体替换。"""

    def test_later_round_inherits_fields_it_does_not_repeat(self):
        first = demo_payload()
        second = demo_payload()
        second["items"][0]["fields"] = {"material": "不锈钢"}
        second["items"][0]["provenance"] = {}
        provider = ScriptedProvider([
            ChatReply("第一版", payload=first),
            ChatReply("只补充材质", payload=second),
        ])
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("材质用不锈钢")
        item = must(session.candidate)["items"][0]
        self.assertEqual(item["fields"]["material"], "不锈钢")
        self.assertEqual(item["fields"]["W1"], 2000)
        self.assertEqual(item["fields"]["台面尺寸"], "1500x1500")
        self.assertEqual(must(session.candidate)["quote"]["m_brand"], "FT")
        self.assertEqual(item["item_type"], "平台秤")
        self.assertTrue(session.preview()["ready"])

    def test_manual_import_still_replaces_instead_of_merging(self):
        session = ChatSession(provider=ScriptedProvider([]))
        session.load_candidate(demo_payload())
        session.load_candidate(demo_payload())
        self.assertEqual(len(must(session.candidate)["items"]), 1)

    @staticmethod
    def two_item_payload():
        """两条设备：平台秤 + 台秤，seq 由模型给出。"""

        payload = demo_payload()
        second = demo_payload()["items"][0]
        second["seq"] = 2
        second["item_type"] = "台秤"
        second["fields"] = {
            "W1": 300, "material": "不锈钢", "台面尺寸": "600x800", "安装形式": "一体",
        }
        payload["items"].append(second)
        payload["quote"]["declared_count"] = 2
        return payload

    def test_program_fills_seq_and_declared_count_for_model_rounds(self):
        """模型不写 seq / declared_count 也能过校验——程序和它算。"""

        payload = demo_payload()
        payload["items"][0].pop("seq")
        payload["quote"].pop("declared_count")
        session = ChatSession(provider=ScriptedProvider([
            ChatReply("候选", payload=payload),
        ]))
        session.send("需求")
        self.assertEqual(must(session.candidate)["items"][0]["seq"], 1)
        self.assertEqual(must(session.candidate)["quote"]["declared_count"], 1)

    def test_delta_with_seq_touches_only_that_item(self):
        """只交一条增量时，seq 决定改哪一条，另一条必须原样保留。"""

        base = self.two_item_payload()
        delta = {"items": [{"seq": 2, "fields": {"台面尺寸": "800x1000"}}]}
        provider = ScriptedProvider([
            ChatReply("两台", payload=base),
            ChatReply("第二台换台面", payload=delta),
        ])
        session = ChatSession(provider=provider)
        session.send("一台平台秤，一台台秤")
        session.send("第二台台面改成 800x1000")
        items = must(session.candidate)["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual([item["seq"] for item in items], [1, 2])
        self.assertEqual(items[0]["fields"]["台面尺寸"], "1500x1500")
        self.assertEqual(items[1]["fields"]["台面尺寸"], "800x1000")
        # 增量没提到的字段同样继承，不会被空对象冲掉。
        self.assertEqual(items[1]["fields"]["安装形式"], "一体")
        self.assertEqual(items[1]["item_type"], "台秤")

    def test_unseen_seq_appends_instead_of_overwriting(self):
        base = self.two_item_payload()
        third = demo_payload()["items"][0]
        third["seq"] = 3
        delta = {"items": [third]}
        provider = ScriptedProvider([
            ChatReply("两台", payload=base),
            ChatReply("再加一台", payload=delta),
        ])
        session = ChatSession(provider=provider)
        session.send("一台平台秤，一台台秤")
        session.send("再加一台平台秤")
        items = must(session.candidate)["items"]
        self.assertEqual([item["seq"] for item in items], [1, 2, 3])
        self.assertEqual(must(session.candidate)["quote"]["declared_count"], 3)


class ProviderFailureRoundTests(unittest.TestCase):
    class _Flaky(Provider):
        def __init__(self):
            self.requests = []
            self.calls = 0

        def complete(self, request):
            self.requests.append(json.loads(json.dumps(request)))
            self.calls += 1
            if self.calls == 2:
                from COPA.apps.llm_chat import ApiError

                raise ApiError("HTTP 500：upstream exploded")
            return ChatReply("好的", demo_payload())

    def test_error_round_is_visible_but_never_replayed_to_model(self):
        provider = self._Flaky()
        session = ChatSession(provider=provider)
        session.send("需求")
        session.send("补充一句")
        self.assertIn("HTTP 500", must(session.last_error))
        self.assertEqual(session.messages[-1]["role"], "system")
        self.assertIn("upstream exploded", session.messages[-1]["content"])
        session.send("再试一次")
        third = json.dumps(provider.requests[2]["messages"], ensure_ascii=False)
        self.assertNotIn("upstream exploded", third)
        self.assertNotIn("HTTP 500", third)
        self.assertIsNone(session.last_error)
        must(session.candidate)


class NetworkRetryTests(unittest.TestCase):
    def test_network_status_zero_is_retried(self):
        from COPA.apps.llm_chat import (
            ChatSettings,
            OpenAICompatibleProvider,
            _HttpFailure,
        )

        calls = []

        def transport(url, headers, body, timeout):
            calls.append(1)
            raise _HttpFailure(0, "timed out")

        settings = ChatSettings(
            base_url="http://example.invalid", model="m", api_key="k",
            provider="api", max_attempts=2,
        )
        provider = OpenAICompatibleProvider(settings, transport=transport)
        provider._sleep = lambda seconds: None
        with self.assertRaises(Exception) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(len(calls), 2)
        self.assertIn("网络异常", str(ctx.exception))


class ArchiveTests(unittest.TestCase):
    def test_archive_has_source_events_and_no_credential(self):
        from COPA.apps.llm_chat import ChatSettings

        settings = ChatSettings(
            base_url="http://example.invalid", model="m",
            api_key="synthetic-secret", provider="api",
        )
        session = ChatSession(
            settings=settings,
            provider=ScriptedProvider([ChatReply("候选", demo_payload())]),
        )
        session.send("一台平台秤")
        archive = session.archive()
        self.assertEqual(archive["source_text"], "一台平台秤")
        self.assertEqual(len(archive["events"]), 1)
        self.assertEqual(archive["events"][0]["intent"], "continue")
        self.assertNotIn("synthetic-secret", json.dumps(archive, ensure_ascii=False))


class FailureRoundTests(unittest.TestCase):
    """调用失败不该污染下一轮上下文，文案也别套两层前缀。"""

    def test_failed_round_keeps_user_turn_and_hides_the_system_notice(self):
        from COPA.apps.llm_chat import ApiError

        def boom(request):
            raise ApiError("模型调用失败：HTTP 502：upstream connect failed")

        provider = ScriptedProvider([boom, ChatReply("收到，我按原需求再来一次。")])
        session = ChatSession(provider=provider)

        reply = session.send("富林泰克，报价")
        self.assertIn("模型调用失败", reply.message)
        notice = session.messages[-1]
        self.assertEqual(notice["role"], "system")
        # 传输层已经带了前缀，系统记录不该再套一层。
        self.assertEqual(notice["content"].count("模型调用失败"), 1)
        self.assertEqual(session.last_error, reply.message)

        session.send("重试一次")
        sent = provider.requests[1]["messages"]
        # 重试轮多一条程序 user 消息：防爆未表态时的强制追问（失败轮没有
        # 候选，也就没有可合并的缺项清单）。
        self.assertEqual([m["role"] for m in sent], ["system", "user", "user", "user"])
        self.assertEqual(sent[1]["content"], "富林泰克，报价")
        self.assertIn("防爆确认", sent[2]["content"])
        self.assertEqual(sent[3]["content"], "重试一次")
        # 失败提示只是界面记录，绝不能变成模型上下文。
        self.assertFalse(any("模型调用失败" in str(m.get("content", "")) for m in sent))

    def test_network_failure_mentions_the_local_proxy(self):
        from COPA.apps.llm_chat import (
            ApiError,
            ChatSettings,
            OpenAICompatibleProvider,
            _HttpFailure,
        )

        def refused(url, headers, body, timeout):
            raise _HttpFailure(0, "[WinError 10061] 由于目标计算机积极拒绝，无法连接。")

        settings = ChatSettings(base_url="https://example.invalid/v1", model="m",
                                api_key="k", provider="api", max_attempts=1)
        provider = OpenAICompatibleProvider(settings, transport=refused, sleeper=lambda _: None)
        with self.assertRaises(ApiError) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertIn("网络异常", str(ctx.exception))
        self.assertIn("代理", str(ctx.exception))


class ErrorCodeTests(unittest.TestCase):
    """状态行只放短码，完整原因留给气泡。"""

    def test_error_code_maps_known_failures(self):
        from COPA.apps.llm_chat import error_code

        self.assertEqual(error_code("模型调用失败：HTTP 500：操作失败"), "HTTP 500")
        self.assertEqual(error_code("模型调用失败：HTTP 429：too many requests"), "HTTP 429")
        self.assertEqual(
            error_code("模型调用失败：网络异常：[WinError 10061] 目标计算机积极拒绝"),
            "网络异常")
        self.assertEqual(error_code("模型调用失败：HTTP 500：免费模型当前排队"), "HTTP 500")
        self.assertEqual(error_code("排队中，请稍后重试"), "排队中")

    def test_error_code_never_returns_a_paragraph(self):
        from COPA.apps.llm_chat import error_code

        # 认不出类型的第三方异常：不猜、也不把长句铺到状态行。
        self.assertEqual(error_code("模型调用失败：something exploded " + "x" * 200), "调用失败")
        self.assertEqual(error_code(""), "调用失败")
        self.assertEqual(error_code(None), "调用失败")
        # 首段本身够短且有意义时保留（如配置缺失），否则同样退成通用码。
        self.assertEqual(error_code("模型调用失败：找不到模型配置文件"), "找不到模型配置文件")
        self.assertLessEqual(len(error_code("模型调用失败：找不到模型配置文件")), 14)


class ScriptedRealConversationTests(unittest.TestCase):
    """两组按真人节奏写的对话，钉住程序侧的事实，不评价模型措辞。

    a) 3t 平台秤：用户分三次才把必填项说全，且刻意不提供电/精度/特殊要求。
    b) 4 支点模块：型号「3306」需要被解释成 FT 仪表，第二轮用户又甩出
       「或者用 210 仪表？」这种扰动问句。

    这两组要守的底线是：缺参清单逐轮收敛；用户没说过的字段不许被发明；
    型号数字不许混进品牌/材质这类枚举字段；扰动问句既不能吞掉已有字段，
    也不能被当成「没有更多信息」直接收尾。
    """

    @staticmethod
    def _candidate(item_type: str, fields: dict, m_brand: str = "FT") -> dict:
        """按字面给过的字段拼候选：测试里每轮都只提交真的说出口的内容。

        品牌写在 quote 级（整单共用）；c_brand 故意留空，验证程序按
        m_brand 补齐；抬头由程序按 m_brand 写死。
        """

        payload = demo_payload()
        payload["quote"]["m_brand"] = m_brand
        payload["quote"].pop("c_brand", None)
        item = payload["items"][0]
        item["item_type"] = item_type
        item["quantity"] = 1
        item["note"] = ""
        item["fields"] = dict(fields)
        item["provenance"] = {
            name: {"source": "user", "basis": "用户口述"} for name in fields
        }
        item["flags"] = {name: False for name in item["flags"]}
        return payload

    def test_three_rounds_complete_a_platform_scale(self):
        platform = self._candidate
        provider = ScriptedProvider([
            ChatReply("收到，一台 3t 平台秤。材质和台面尺寸麻烦确认。",
                      payload=platform("平台秤", {"W1": 3000})),
            ChatReply("材质记下了，台面做多大？",
                      payload=platform("平台秤", {
                          "W1": 3000, "material": "碳钢"})),
            ChatReply("参数齐了，可以进选型。",
                      payload=platform("平台秤", {
                          "W1": 3000, "material": "碳钢",
                          "台面尺寸": "1200x1200"})),
        ])
        session = ChatSession(provider=provider)

        # 第一次输入只交代了量程和品牌：清单必须精确到这两个缺项。
        session.send("一台富林泰克3吨平台秤，常规精度")
        self.assertEqual(session.feedback_fields, ["缺少材质", "缺少台面尺寸"])
        item = must(session.candidate)["items"][0]
        # 仪表品牌不是用户说的，是程序按 m_brand 补齐的；抬头只看 m_brand。
        self.assertEqual(must(session.candidate)["quote"]["c_brand"], "FT")
        self.assertEqual(must(session.candidate)["quote"]["quote_title"], "COPA B")
        self.assertNotIn("m_brand", item["fields"])
        # 用户没提的字段一律不进候选，程序也不替他补。
        for absent in ("power", "e_input", "special_req"):
            self.assertNotIn(absent, item["fields"])
        self.assertFalse(item["flags"]["metrology"])  # 「常规精度」不是计量器具

        # 第二次只补材质：清单收敛到 1 项，旧缺项不残留。
        session.send("碳钢的")
        self.assertEqual(session.feedback_fields, ["缺少台面尺寸"])
        self.assertEqual(must(session.candidate)["items"][0]["fields"]["material"], "碳钢")

        # 第三次补台面：清单清空，进入待确认，但仍未被授权报价。
        reply = session.send("台面 1.2 米乘 1.2 米，仪表也用 FT 吧")
        self.assertEqual(session.feedback_fields, [])
        self.assertIsNone(session.feedback_text)
        self.assertTrue(session.preview()["ready"])
        self.assertEqual(session.exit_state, "awaiting_confirm")
        self.assertNotEqual(reply.intent, "request_quote")

        confirmed = session.confirm(1)
        fields = confirmed["items"][0]["fields"]
        self.assertEqual(fields["台面尺寸"], "1200x1200")
        self.assertEqual(fields["W1"], 3000)
        self.assertNotIn("power", fields)
        self.assertTrue(confirmed["quote"]["confirmed_by_user"])

    def test_model_number_is_explained_once_and_the_alternative_is_just_noise(self):
        module = self._candidate
        provider = ScriptedProvider([
            ChatReply("收到 4 支点模块。量程、皮重和有没有高速搅拌？",
                      payload=module("称重模块", {
                          "support": 4, "material": "碳钢"})),
            ChatReply("3306 和 210 都是 FT 的仪表型号，按你指定的 3306 报。"
                      "还差一项：有没有高速搅拌？",
                      payload=module("称重模块", {
                          "support": 4, "material": "碳钢",
                          "W1": 2000, "W2": 500})),
            ChatReply("明白，按常规工况。",
                      payload=module("称重模块", {
                          "support": 4, "material": "碳钢",
                          "W1": 2000, "W2": 500, "vibration": False})),
        ])
        session = ChatSession(provider=provider)

        session.send("4支点模块，碳钢，FT，配3306")
        self.assertEqual(len(session.feedback_fields), 3)
        self.assertIn("缺少vibration", session.feedback_fields)
        # 型号不是品牌：3306 只能落到 FT 上，不许原样塞进任何枚举字段。
        self.assertNotIn("3306", json.dumps(must(session.candidate), ensure_ascii=False))
        self.assertEqual(must(session.candidate)["quote"]["m_brand"], "FT")

        # 第二轮：澄清型号 + 抛出「或者用 210 仪表？」的扰动问句。
        reply = session.send(
            "量程 2 吨，皮重 0.5 吨。3306 是 FT 的仪表，就配它。或者用 210 仪表？")
        self.assertEqual(reply.intent, "continue")
        self.assertIsNone(session.take_exit_notice())  # 问句不是收尾句
        # 只剩 vibration 这一项非必须缺项：不再追问，改由 Checklist 标红。
        self.assertEqual(session.feedback_fields, [])
        item = must(session.candidate)["items"][0]
        self.assertEqual(item["fields"]["support"], 4)  # 扰动不吞掉已有字段
        self.assertEqual(item["fields"]["W1"], 2000)
        self.assertEqual(item["fields"]["W2"], 500)
        self.assertEqual(must(session.candidate)["quote"]["c_brand"], "FT")
        self.assertNotIn("210", json.dumps(item["fields"], ensure_ascii=False))

        session.send("不用高速搅拌，没别的了，直接报")
        self.assertEqual(session.feedback_fields, [])
        self.assertTrue(session.preview()["ready"])
        confirmed = session.confirm(1)
        item = confirmed["items"][0]
        self.assertFalse(item["fields"]["vibration"])
        self.assertEqual(item["fields"]["support"], 4)
        self.assertEqual(confirmed["quote"]["c_brand"], "FT")


if __name__ == "__main__":
    unittest.main()
