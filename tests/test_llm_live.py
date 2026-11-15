"""Optional real-API smoke test; skipped unless a credential is present.

The default suite stays offline.  Set ``ZHIPU_API_KEY`` (or ``COPA_LLM_LIVE=1``
with a key already in ``llm/providers.json``) to exercise the real endpoint.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

_LIVE = bool(os.environ.get("ZHIPU_API_KEY")) or os.environ.get("COPA_LLM_LIVE") == "1"


@unittest.skipUnless(_LIVE, "设置 ZHIPU_API_KEY 或 COPA_LLM_LIVE=1 才跑真实 API 冒烟")
class LiveProviderSmokeTests(unittest.TestCase):
    def test_endpoint_answers_a_minimal_prompt(self):
        from COPA.apps.llm_chat import OpenAICompatibleProvider, load_provider_config

        settings = load_provider_config()
        provider = OpenAICompatibleProvider(settings)
        reply = provider.complete({
            "messages": [{"role": "user", "content": "只回复 pong"}],
        })
        # 端点只返回 content 就够；不约定 schema 时模型可能回 {"answer": "pong"}，
        # 由 _decode_chat_reply 原样回显，界面不会出现空白回复。
        self.assertIn("pong", reply.message.lower())

    def test_session_prompt_is_accepted_and_returns_a_message(self):
        from COPA.apps.llm_chat import (
            ChatSession,
            OpenAICompatibleProvider,
            load_provider_config,
        )

        # 必须显式注入配置文件：不带 settings 的 ChatSession() 是演示 provider，
        # 断言「message 非空」会被演示话术蒙混过去，等于没测到真实端点。
        session = ChatSession(settings=load_provider_config())
        assert isinstance(session.provider, OpenAICompatibleProvider)
        reply = session.send("一台 2000kg 平台秤，台面 1500x1500，碳钢，FT 品牌，不防爆。")
        self.assertTrue(reply.message.strip())
        self.assertNotIn("尚未启用", reply.message)
        self.assertNotIn("载入演示", reply.message)


if __name__ == "__main__":
    unittest.main()
