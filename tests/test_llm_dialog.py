"""COPA 对话窗体的离线交互回归。

覆盖三件事：
1. 界面不出现任何接口地址/口令/提供方配置；
2. 气泡式会话记录只显示可读文本，不倾倒 JSON；
3. 候选通过校验后**自动**交接，不再让用户点「确认进入选型」。
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QComboBox

from COPA.apps.LlmChat import LlmChat


class Reply:
    def __init__(self, message: str, payload=None):
        self.message = message
        self.payload = payload


def candidate():
    return {
        "quote": {"project": "离线测试", "quote_title": "COPA B", "confirmed_by_user": False},
        "items": [
            {
                "seq": 1,
                "item_type": "平台秤",
                "quantity": 1,
                "flags": {
                    "metrology": False,
                    "high_precision": True,
                    "ex": False,
                    "digital": False,
                    "onsite_service": True,
                },
                "fields": {
                    "W1": 2000,
                    "material": "碳钢",
                    "m_brand": "FT",
                    "c_brand": "FT",
                    "台面尺寸": "1500x1500",
                },
            }
        ],
    }


class FakeSession:
    """最小会话替身：只用于验证 UI 的收发与失败恢复。"""

    def __init__(self, *, delay=0.02):
        self.settings = SimpleNamespace(
            base_url="", model="", api_key="", provider="demo", provider_name="zhipu")
        self.messages = [{"role": "system", "content": "internal context"}]
        self.candidate = None
        self.delay = delay
        self.fail_next = False
        self.error_next: str | None = None
        self.last_error: str | None = None
        self.sent: list[str] = []

    def send(self, text):
        time.sleep(self.delay)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("fake provider failed")
        if self.error_next:
            # 模拟真实传输层：返回一条带前缀的失败文案，同时留下 last_error。
            message = self.error_next
            self.error_next = None
            self.last_error = message
            self.sent.append(text)
            self.messages.append({"role": "user", "content": text})
            return Reply(message, None)
        self.last_error = None
        self.sent.append(text)
        self.messages.append({"role": "user", "content": text})
        payload = candidate()
        self.candidate = payload
        self.messages.append({"role": "assistant", "content": "offline reply"})
        return Reply("offline reply", payload)

    def load_candidate(self, payload, merge=False):
        self.candidate = payload

    def preview(self):
        count = len(self.candidate.get("items", [])) if self.candidate else 0
        return {
            "errors": [] if self.candidate else ["NO_CANDIDATE"],
            "count": count,
            "ready": bool(self.candidate),
        }

    def confirm(self, actual_count, force_quote=False):
        if not self.candidate or actual_count != len(self.candidate["items"]):
            raise ValueError("COUNT_MISMATCH")
        result = dict(self.candidate)
        result["quote"] = dict(result["quote"], confirmed_by_user=True)
        return result

    def reset(self):
        self.messages = [{"role": "system", "content": "internal context"}]
        self.candidate = None
        self.sent = []


class LlmChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until_idle(self, chat, timeout=3.0):
        deadline = time.monotonic() + timeout
        while chat.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertFalse(chat.busy, "后台 worker 未在测试窗口内完成")

    def make_chat(self, session=None):
        chat = LlmChat(session=session or FakeSession())
        self.addCleanup(chat.close)
        return chat

    # -- 界面形态 ---------------------------------------------------------

    def test_no_credentials_or_endpoint_widgets_exist(self):
        chat = self.make_chat()
        for name in ("apiKeyEdit", "baseUrlEdit", "modelEdit", "providerCombo"):
            self.assertFalse(hasattr(chat, name), name)
        self.assertTrue(hasattr(chat, "modelCombo"))
        self.assertTrue(hasattr(chat, "modelIntroLabel"))

    def test_ui_source_has_no_credential_fields(self):
        source = (Path(__file__).resolve().parents[1] / "apps" / "ui" / "llmChat.ui").read_text(
            encoding="utf-8"
        )
        for forbidden in ("apiKey", "口令", "base_url", "API 地址"):
            self.assertNotIn(forbidden, source)
        self.assertIn("如需接入其他付费模型，请通过反馈联系开发者。", source)

    def test_model_selector_only_shows_labels_and_intro(self):
        chat = self.make_chat()
        labels = [chat.modelCombo.itemText(i) for i in range(chat.modelCombo.count())]
        self.assertTrue(labels)
        self.assertNotIn("zhipu", labels)  # 展示的是标签，不是配置键
        self.assertTrue(chat.modelIntroLabel.text())

    def test_model_selector_fits_the_longest_label(self):
        """模型名不能被下拉框截断，简介也不能把输入卡片顶高。

        QComboBox 默认只在首次显示时算一次宽度：之后加进长名字（例如
        Nemotron 3.5 Lightning），sizeHint 还停在空列表的 89px，列表里就
        只能看到「Nemotron 3.5 L…」。这里钉住两件事：宽度按内容自适应、
        简介固定单行左对齐。
        """

        chat = self.make_chat()
        chat.resize(920, 640)
        chat.show()
        self.app.processEvents()
        combo = chat.modelCombo
        self.assertEqual(
            combo.sizeAdjustPolicy(),
            QComboBox.SizeAdjustPolicy.AdjustToContents,
            "下拉框宽度必须跟随内容，否则后加的长模型名会被截断",
        )
        metrics = combo.fontMetrics()
        longest = max(
            (combo.itemText(i) for i in range(combo.count())),
            key=lambda text: metrics.horizontalAdvance(text),
        )
        self.assertGreaterEqual(
            combo.width(), metrics.horizontalAdvance(longest) + 16,
            "最长的模型名 {} 放不下".format(longest),
        )
        intro = chat.modelIntroLabel
        self.assertLessEqual(
            intro.height(), intro.fontMetrics().height() + 8,
            "简介必须保持单行，不能撑高输入卡片",
        )
        self.assertTrue(
            intro.alignment() & Qt.AlignmentFlag.AlignLeft,
            "简介要靠左紧跟模型名，不能被空白推到卡片中间",
        )

    def test_composer_height_follows_content(self):
        """输入框按行数收放，且打开时就是一行高。

        钉住「行数不是像素」：QPlainTextEdit 纯文本布局的
        ``document().size().height()`` 单位是行数，当像素算会让输入框永远
        停在最小高度；打开那一刻文档还没布局，同一个值又会异常大、直接顶
        到上限，于是刚打开比演示里的空输入框高出一截。
        """

        chat = self.make_chat()
        chat.resize(920, 640)
        chat.show()
        self.app.processEvents()
        edit = chat.messageEdit
        opened = edit.height()
        self.assertEqual(opened, 56, "打开时输入框应为 .ui 里的一行高度")
        edit.setPlainText("\n".join("第{}行".format(i + 1) for i in range(5)))
        self.app.processEvents()
        five = edit.height()
        self.assertGreater(five, opened, "5 行内容必须比空输入框高")
        edit.setPlainText("\n".join("第{}行".format(i + 1) for i in range(8)))
        self.app.processEvents()
        eight = edit.height()
        edit.setPlainText("\n".join("第{}行".format(i + 1) for i in range(14)))
        self.app.processEvents()
        self.assertEqual(edit.height(), eight, "超过上限后不再继续长高")
        edit.clear()
        self.app.processEvents()
        self.assertEqual(edit.height(), opened, "清空后回到一行高")

    def test_model_list_follows_ui_order(self):
        """列表顺序按 ui.order 升序，默认选中项由 providers.json 的 active 决定。

        用真实配置构造，但不钉具体供应商名——增删供应商时这个测试不该跟着改。
        """

        config_path = Path(__file__).resolve().parents[1] / "llm" / "providers.json"
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        ordered = sorted(
            ((item.get("ui") or {}).get("order", 99), (item.get("ui") or {}).get("label"))
            for item in config["providers"].values()
            if not (item.get("ui") or {}).get("hidden")
        )
        expected = [label for _, label in ordered]

        chat = LlmChat()
        self.addCleanup(chat.close)
        labels = [chat.modelCombo.itemText(i) for i in range(chat.modelCombo.count())]
        self.assertGreaterEqual(len(labels), 2)
        self.assertEqual(labels, expected, "下拉框必须按 ui.order 升序")
        active = config["providers"][config["active"]]["ui"]["label"]
        self.assertEqual(chat.modelCombo.currentText(), active,
                         "默认模型应当是 active 指向的那一项")

    # -- 滚动与附件闸口 ---------------------------------------------------

    def _settle(self, rounds=6):
        """布局要跑几轮事件循环才定高：气泡先算宽度、再由布局分配高度。"""

        for _ in range(rounds):
            self.app.processEvents()
            time.sleep(0.01)

    def _fill_conversation(self, chat, count=30):
        for index in range(count):
            chat._append("LLM", "第 {} 条消息，用来把对话区撑出滚动条。".format(index))
        chat._render_conversation()
        self._settle()

    def test_scroll_button_returns_to_latest(self):
        chat = self.make_chat()
        chat.resize(760, 460)
        chat.show()
        self._fill_conversation(chat)
        bar = chat.conversationArea.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "对话区应当出现滚动条")
        self.assertEqual(bar.value(), bar.maximum(), "新消息应当自动滚到底部")

        bar.setValue(0)
        self._settle(2)
        self.assertTrue(chat._scrollButton.isVisible(), "上滚后应浮出回到最新按钮")

        chat._scrollButton.click()
        self._settle(2)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertFalse(chat._scrollButton.isVisible(), "回到底部后按钮应收起")

    def test_scroll_button_absent_when_content_fits(self):
        chat = self.make_chat()
        chat.resize(760, 460)
        chat.show()
        chat._append("LLM", "只有一条消息")
        chat._render_conversation()
        self._settle(2)
        self.assertFalse(chat._scrollButton.isVisible())

    def _fake_drop(self, path):
        url = SimpleNamespace(toLocalFile=lambda: str(path))
        mime = SimpleNamespace(hasUrls=lambda: True, urls=lambda: [url])
        return SimpleNamespace(mimeData=lambda: mime)

    def test_dropped_xls_and_doc_are_accepted(self):
        for name in ("清单.xls", "方案.doc", "报价.xlsx", "需求.docx"):
            target = Path("C:/tmp") / name
            self.assertEqual(LlmChat._dropped_file(self._fake_drop(target)), str(target))
        rejected = Path("C:/tmp") / "示意图.png"
        self.assertIsNone(LlmChat._dropped_file(self._fake_drop(rejected)))

    def _feed_ingest(self, chat, text, source):
        from COPA.apps.doc_ingest import IngestResult

        chat._ingest_generation = chat._generation
        chat._ingest_thread = SimpleNamespace(
            isRunning=lambda: False, quit=lambda: None, wait=lambda: None)
        chat._ingest_finished(IngestResult(text, source, []))

    def test_ingest_without_requirement_is_rejected(self):
        chat = self.make_chat()
        self._feed_ingest(chat, "会议纪要：下周三上午讨论年度预算与人员编制。", "会议纪要.docx")
        self.assertEqual(chat._attachments, [], "不含选型要求的附件不能挂上")
        texts = [text for _, text in chat._entries]
        self.assertTrue(any("未能解析到选型要求" in text for text in texts), texts)
        self.assertIn("已中断", chat._status_text)

    def test_ingest_with_requirement_is_attached(self):
        chat = self.make_chat()
        self._feed_ingest(chat, "平台秤 3吨 碳钢台面 1200x1200", "清单.xlsx")
        self.assertEqual(len(chat._attachments), 1)
        self.assertEqual(chat._attachments[0]["name"], "清单.xlsx")

    def test_model_popup_carries_its_own_light_style(self):
        """弹窗是独立顶层窗口，不吃 #LlmChat 的样式表。

        深色系统 palette 下它曾经被画成一块纯黑方块：没有背景、文字也是
        深色，只剩一条高亮竖线。这里钉住弹窗自带浅色样式与 palette。
        """

        chat = self.make_chat()
        view = chat.modelCombo.view()
        assert view is not None
        self.assertIn("background-color: #ffffff", view.styleSheet())
        popup = view.window() or view.parentWidget()
        assert popup is not None
        self.assertIn("background-color: #ffffff", popup.styleSheet())
        self.assertEqual(popup.palette().color(QPalette.ColorRole.Base).name(),
                         "#ffffff")

    def test_parameter_panels_are_gone(self):
        chat = self.make_chat()
        for name in ("previewText", "issuesList", "confirmButton", "actualCountSpin"):
            self.assertFalse(hasattr(chat, name), name)

    def test_action_rail_is_vertically_centred(self):
        chat = self.make_chat()
        layout = chat.railLayout
        top = layout.itemAt(0)
        bottom = layout.itemAt(layout.count() - 1)
        assert top is not None and bottom is not None
        self.assertIs(top.spacerItem(), chat.railTopSpacer)
        self.assertIs(bottom.spacerItem(), chat.railSpacer)

    def test_bubble_colours_come_from_one_theme_table(self):
        from COPA.apps.LlmChat import BUBBLE_THEME, _Bubble

        original = dict(BUBBLE_THEME["用户"])
        bubble = None
        try:
            BUBBLE_THEME["用户"] = dict(original, bg="#123456")
            bubble = _Bubble("用户", "换个颜色")
            self.assertIn("#123456", bubble.styleSheet())
        finally:
            BUBBLE_THEME["用户"] = original
            if bubble is not None:
                bubble.deleteLater()
        self.assertIn(original["bg"], _Bubble("用户", "恢复").styleSheet())

    # -- 交互 -------------------------------------------------------------

    def test_send_renders_bubbles_and_hands_off_automatically(self):
        chat = self.make_chat()
        received = []
        chat.payloadConfirmed.connect(received.append)
        chat.messageEdit.setPlainText("一台平台秤")
        chat.sendButton.click()
        self.wait_until_idle(chat)

        roles = [role for role, _ in chat._entries]
        self.assertEqual(roles, ["用户", "LLM", "系统"])
        self.assertIn("参数已通过校验", chat._entries[-1][1])
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0]["quote"]["confirmed_by_user"])
        self.assertEqual(chat.messageEdit.toPlainText(), "")  # 发送后清空输入框
        self.assertTrue(chat._confirmation_sent)

    def test_conversation_never_dumps_payload_json(self):
        chat = self.make_chat()
        chat.messageEdit.setPlainText("需求")
        chat.sendButton.click()
        self.wait_until_idle(chat)
        text = "\n".join(body for _, body in chat._entries)
        self.assertIn("offline reply", text)
        self.assertNotIn('"payload"', text)
        self.assertNotIn("schema_version", text)

    def test_enter_sends_and_shift_enter_keeps_newline(self):
        chat = self.make_chat()
        chat.messageEdit.setPlainText("第一行")
        QTest.keyClick(chat.messageEdit, Qt.Key.Key_Return)
        self.assertTrue(chat.busy)
        self.wait_until_idle(chat)

        chat.messageEdit.setPlainText("第一行")
        QTest.keyClick(
            chat.messageEdit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertFalse(chat.busy)
        self.assertIn("\n", chat.messageEdit.toPlainText())

    def test_failed_send_shows_system_bubble_and_keeps_input(self):
        session = FakeSession()
        chat = self.make_chat(session)
        session.fail_next = True
        chat.messageEdit.setPlainText("第一次")
        chat._send_message()
        self.wait_until_idle(chat)
        self.assertIn("发送失败", chat.statusLabel.text())
        self.assertEqual(chat._entries[-1][0], "系统")
        self.assertIn("发送失败", chat._entries[-1][1])
        self.assertTrue(chat.sendButton.isEnabled() or
                        not chat.messageEdit.toPlainText().strip())

        chat._send_message()
        self.wait_until_idle(chat)
        self.assertEqual(len(session.sent), 1)

    def test_model_failure_status_shows_only_a_short_code(self):
        session = FakeSession()
        chat = self.make_chat(session)
        long_reason = "模型调用失败：网络异常：" + "上游拒绝连接；" * 30
        session.error_next = long_reason
        chat.messageEdit.setPlainText("需求")
        chat._send_message()
        self.wait_until_idle(chat)

        # 状态行只留短码：没有完整原因、没有省略号，也不重复前缀。
        shown = chat.statusLabel.text()
        self.assertEqual(shown, "网络异常")
        self.assertEqual(chat.statusLabel.toolTip(), long_reason)
        # 失败不是模型说的话：单独的角色与配色，不冒充模型气泡。
        self.assertEqual(chat._entries[-1][0], "错误")
        self.assertIn(long_reason, chat._entries[-1][1])

    def test_new_session_clears_bubbles(self):
        chat = self.make_chat()
        chat.messageEdit.setPlainText("需求")
        chat.sendButton.click()
        self.wait_until_idle(chat)
        self.assertTrue(chat._entries)
        chat._new_session()
        self.assertEqual(chat._entries, [])
        self.assertIsNone(chat.session.candidate)

    def test_drag_and_drop_attaches_a_chip_instead_of_dumping_text(self):
        import tempfile

        chat = self.make_chat()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "需求.md"
            path.write_text("# 需求\n一台 2000kg 平台秤", encoding="utf-8")
            chat._ingest_path(str(path))
            self.wait_until_idle(chat)
        # 附件只占一枚气泡，原文留在内存里随下一句话一起发。
        self.assertEqual(chat._entries[-1][0], "附件")
        self.assertIn("需求.md", chat._entries[-1][1])
        self.assertEqual(chat.messageEdit.toPlainText(), "")
        self.assertTrue(chat.sendButton.isEnabled(), "只有附件也应该能发送")

        chat.messageEdit.setPlainText("按这个报价")
        chat._send_message()
        self.wait_until_idle(chat)
        self.assertIn("2000kg", chat.session.sent[0])
        self.assertIn("按这个报价", chat.session.sent[0])
        self.assertEqual(chat._attachments, [], "附件发过就该清掉，不能重复提交")

    def test_dropped_file_filter_ignores_unsupported_suffix(self):
        chat = self.make_chat()

        class _Url:
            def __init__(self, path):
                self._path = path

            def toLocalFile(self):
                return self._path

        class _Mime:
            def __init__(self, path):
                self._paths = [path]

            def hasUrls(self):
                return True

            def urls(self):
                return [_Url(p) for p in self._paths]

        class _Event:
            def __init__(self, path):
                self._mime = _Mime(path)

            def mimeData(self):
                return self._mime

        self.assertIsNone(LlmChat._dropped_file(_Event("C:/tmp/a.pdf")))
        self.assertEqual(
            LlmChat._dropped_file(_Event("C:/tmp/a.xlsx")), "C:/tmp/a.xlsx")
        del chat


class HandoffTests(unittest.TestCase):
    """校验通过 -> 自动交接；未通过 -> 继续追问，不交接。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from COPA.apps.llm_chat import ChatSession

        self.ChatSession = ChatSession

    def wait(self, chat, timeout=5.0):
        deadline = time.monotonic() + timeout
        while chat.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertFalse(chat.busy)

    def chat_with(self, replies):
        from COPA.apps.llm_chat import ChatSession, ScriptedProvider

        session = ChatSession(provider=ScriptedProvider(replies))
        # 这组用例只测「校验通过 → 自动交接」，防爆表态由 ProgramFlagTests
        # 单独覆盖；这里预置已表态，免得门禁把交接挡住。
        session._ex_state = False
        chat = LlmChat(session=session)
        self.addCleanup(chat.close)
        received = []
        chat.payloadConfirmed.connect(received.append)
        return chat, received

    def test_complete_candidate_hands_off_without_user_confirmation(self):
        from COPA.apps.llm_chat import ChatReply, demo_payload

        chat, received = self.chat_with([ChatReply("请核对", demo_payload())])
        chat.messageEdit.setPlainText("一台平台秤")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["items"][0]["fields"]["W1"], 2000)

    def test_tolerated_gap_waits_for_explicit_quote_request(self):
        from COPA.apps.llm_chat import ChatReply, demo_payload

        payload = demo_payload()
        item = payload["items"][0]
        item["item_type"] = "称重模块"
        item["fields"] = {
            "W1": 5000, "support": 4, "material": "碳钢",
            "m_brand": "FT", "c_brand": "FT", "vibration": False,
        }  # 故意缺 W2（皮重）
        item["provenance"] = {}
        chat, received = self.chat_with([
            ChatReply("还需要皮重", payload),
            ChatReply("好的", payload, intent="request_quote"),
        ])
        chat.messageEdit.setPlainText("称重模块")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(received, [])  # 缺项未通过校验，不自动交接

        chat.messageEdit.setPlainText("没别的了，你报价吧")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["items"][0]["fields"]["W2"], 0)
        self.assertEqual(
            received[0]["items"][0]["provenance"]["W2"]["source"], "default_unspecified")

    def test_nonstandard_size_is_downgraded_on_handoff(self):
        from COPA.apps.llm_chat import ChatReply, demo_payload

        payload = demo_payload()
        payload["items"][0]["fields"]["台面尺寸"] = "3000x3000"
        payload["items"][0]["provenance"].pop("台面尺寸", None)
        chat, received = self.chat_with([
            ChatReply("台面是非标尺寸", payload),
            ChatReply("好的", payload, intent="request_quote"),
        ])
        chat.messageEdit.setPlainText("需求")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(received, [])

        chat.messageEdit.setPlainText("你报价吧")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(len(received), 1)
        item = received[0]["items"][0]
        self.assertEqual(item["fields"]["台面尺寸"], "2000x2000")
        self.assertEqual(item["nonstandard_size"], "3000x3000")

    def test_returning_to_chat_can_hand_off_again(self):
        from COPA.apps.llm_chat import ChatReply, demo_payload

        chat, received = self.chat_with([
            ChatReply("请核对", demo_payload()),
            ChatReply("请核对", demo_payload()),
        ])
        chat.messageEdit.setPlainText("一台平台秤")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(len(received), 1)

        # 回退到对话（清单被丢弃）后再发一轮，必须能再次交接。
        chat.messageEdit.setPlainText("再加一台同规格的")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(len(received), 2)

    def test_demo_action_never_calls_the_model(self):
        from COPA.apps.llm_chat import ChatSession, DisabledApiProvider

        session = ChatSession(provider=DisabledApiProvider())
        chat = LlmChat(session=session)
        self.addCleanup(chat.close)
        self._compress_demo(chat)
        received = []
        chat.payloadConfirmed.connect(received.append)
        chat._use_demo()
        # 点下就进入"演示中"，防止用户连点叠出两遍。
        self.assertTrue(chat.busy)
        self._pump(lambda: bool(received))
        self.assertEqual(len(received), 1)
        # 展示用例是「设备清单」那三行：称重模块 5t×2、2t×1、平台秤 3t×2。
        self.assertEqual(len(received[0]["items"]), 3)
        self.assertEqual(received[0]["items"][0]["fields"]["W1"], 5000)
        self.assertEqual(received[0]["items"][2]["fields"]["W1"], 3000)
        self.assertFalse(chat.busy)
        self.assertFalse(chat._demo_running)

    def test_demo_script_is_the_recorded_attachment_case(self):
        from COPA.apps.llm_chat import DEMO_CASE_ATTACHMENT, demo_case_turns

        turns = demo_case_turns()
        self.assertEqual([role for role, _ in turns], ["附件", "用户", "LLM", "用户", "LLM"])
        self.assertIn(DEMO_CASE_ATTACHMENT, turns[0][1])
        self.assertEqual(turns[1][1], "FT系列，报价")

    def test_demo_pacing_matches_the_requested_timeline(self):
        self.assertEqual(LlmChat.DEMO_START_DELAY, 1000)   # 点击后先停一秒
        self.assertEqual(LlmChat.DEMO_REPLY_DELAY, 500)    # 需求落下后停半秒
        self.assertEqual(LlmChat.DEMO_USER_DELAY, 700)     # 回复播完再放下一句
        self.assertEqual(LlmChat.DEMO_TYPE_INTERVAL, 23)   # 逐字输出，接近常用 AI 语速
        # 回复播完不再干等：交接立刻发生，清单窗的停顿由编排层负责。
        self.assertFalse(
            hasattr(LlmChat, "DEMO_HANDOFF_DELAY"),
            "交接后不应再有对话侧的空白等待")

    def test_demo_reply_is_typed_out_then_handed_off_immediately(self):
        from COPA.apps.llm_chat import ChatSession, DisabledApiProvider, demo_case_turns

        chat = LlmChat(session=ChatSession(provider=DisabledApiProvider()))
        self.addCleanup(chat.close)
        self._compress_demo(chat)
        chat.DEMO_TYPE_INTERVAL = 2
        received = []
        entries_at_handoff: list[list[tuple[str, str]]] = []

        def on_confirmed(payload):
            # 交出的这一刻屏幕上就该有「正在生成选型清单」，不能是空白等待。
            received.append(payload)
            entries_at_handoff.append(list(chat._entries))

        chat.payloadConfirmed.connect(on_confirmed)
        chat._use_demo()

        lengths: list[int] = []
        deadline = time.monotonic() + 10
        while not received and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
            if chat._entries and chat._entries[-1][0] == "LLM":
                lengths.append(len(chat._entries[-1][1]))
        self.app.processEvents()

        self.assertEqual(len(received), 1)
        self.assertGreater(len(set(lengths)), 3, "回复应当逐字出现，而不是一次贴完")
        last_line = demo_case_turns()[-1][1]
        self.assertGreaterEqual(max(lengths), len(last_line) - 1)

        snapshot = entries_at_handoff[0]
        self.assertEqual(
            [role for role, _ in snapshot],
            ["附件", "用户", "LLM", "用户", "LLM", "系统"])
        self.assertEqual(snapshot[4][1], last_line)  # 全文已经播完
        self.assertIn("正在生成选型清单", snapshot[5][1])  # 提示先于交接出现

    def test_new_session_is_refused_while_the_demo_is_playing(self):
        from COPA.apps.llm_chat import ChatSession, DisabledApiProvider

        chat = LlmChat(session=ChatSession(provider=DisabledApiProvider()))
        self.addCleanup(chat.close)
        chat.DEMO_START_DELAY = 60_000  # 故意卡在第一步
        received = []
        chat.payloadConfirmed.connect(received.append)
        chat._use_demo()
        self.assertTrue(chat.busy)
        self.assertFalse(chat.newSessionButton.isEnabled())

        chat._new_session()  # 演示期间不接受新会话，避免把播放中的画面清掉
        self.assertTrue(chat._demo_running)

        chat._cancel_demo()  # 复位后立刻停下来，不再交接
        self.assertFalse(chat.busy)
        self.assertEqual(received, [])

    def _compress_demo(self, chat):
        chat.DEMO_START_DELAY = 0
        chat.DEMO_REPLY_DELAY = 0
        chat.DEMO_USER_DELAY = 0
        chat.DEMO_TYPE_INTERVAL = 0

    def _pump(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()

    def test_no_more_info_without_force_quote_does_not_hand_off(self):
        from COPA.apps.llm_chat import ChatReply, demo_payload

        payload = demo_payload()
        payload["items"][0]["fields"].pop("W1", None)  # 必须项缺失
        payload["items"][0]["provenance"].pop("W1", None)
        chat, received = self.chat_with([
            ChatReply("还缺量程", payload),
            ChatReply("好的", payload, intent="no_more_info"),
        ])
        chat.messageEdit.setPlainText("需求")
        chat._send_message()
        self.wait(chat)
        chat.messageEdit.setPlainText("没有更多信息了")
        chat._send_message()
        self.wait(chat)
        self.assertEqual(received, [])
        self.assertEqual(chat.session.exit_state, "stopped")
        self.assertTrue(any("仍缺" in body for _, body in chat._entries))


if __name__ == "__main__":
    unittest.main()
