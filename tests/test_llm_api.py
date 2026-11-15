"""Stdlib tests for the real OpenAI-compatible transport.

All HTTP calls are injected; this module never opens a socket.  Credentials
used here are synthetic and must never be echoed into failure messages.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from COPA.apps.llm_chat import (
    ApiError,
    ChatSession,
    ChatSettings,
    OpenAICompatibleProvider,
    ProviderConfigError,
    ScriptedProvider,
    _HttpFailure,
    demo_payload,
    load_provider_config,
)

SECRET = "synthetic-key-not-a-real-secret"


def response(content: str, model: str = "glm-4.7-flash") -> dict:
    return {"model": model, "choices": [{"message": {"content": content}}]}


def envelope(message: str, payload=None) -> str:
    return json.dumps({"message": message, "payload": payload}, ensure_ascii=False)


class TransportHarness:
    """Records every request and replays a scripted sequence of results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls: list[dict] = []
        self.sleeps: list[float] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(json.dumps(body))})
        index = min(len(self.calls) - 1, len(self.results) - 1)
        value = self.results[index]
        if isinstance(value, Exception):
            raise value
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def make_provider(results, settings=None):
    harness = TransportHarness(results)
    settings = settings or ChatSettings(
        base_url="https://example.invalid/v1",
        model="glm-4.7-flash",
        api_key=SECRET,
        provider="api",
        supports_response_format=True,
        extra={"thinking": {"type": "disabled"}},
    )
    provider = OpenAICompatibleProvider(settings, transport=harness, sleeper=harness.sleep)
    return provider, harness


class ProviderTests(unittest.TestCase):
    def test_message_payload_envelope_is_decoded(self):
        payload = demo_payload()
        provider, _ = make_provider([response(envelope("请核对候选", payload))])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "请核对候选")
        assert reply.payload is not None
        self.assertEqual(reply.payload["items"][0]["fields"]["W1"], 2000)
        self.assertEqual(provider.last_model, "glm-4.7-flash")

    def test_plain_prose_is_a_clarification_turn(self):
        provider, _ = make_provider([response("请问量程是多少？")])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "请问量程是多少？")
        self.assertIsNone(reply.payload)

    def test_non_protocol_json_is_echoed_instead_of_shown_blank(self):
        # 实测 glm 对没有 schema 的极简提示词会回 {"answer": "pong"}；
        # 空 message 在界面上等于无响应，所以原样回显。
        provider, _ = make_provider([response('{"answer": "pong"}')])
        reply = provider.complete({"messages": [{"role": "user", "content": "只回复 pong"}]})
        self.assertIn("pong", reply.message)
        self.assertIsNone(reply.payload)

    def test_bare_quote_payload_is_staged_as_candidate(self):
        payload = demo_payload()
        provider, _ = make_provider([response(json.dumps(payload, ensure_ascii=False))])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        assert isinstance(reply.payload, dict)
        self.assertTrue(reply.message)

    def test_fenced_and_decorated_json_is_tolerated(self):
        text = "好的，结果如下：\n```json\n{}\n```\n以上请核对。".format(envelope("已生成", None))
        provider, _ = make_provider([response(text)])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "已生成")
        self.assertIsNone(reply.payload)

    def test_request_shape_and_credential_isolation(self):
        provider, harness = make_provider([response(envelope("收到", None))])
        provider.complete({"messages": [{"role": "system", "content": "规则"}, {"role": "user", "content": "需求"}]})
        call = harness.calls[0]
        self.assertTrue(call["url"].endswith("/chat/completions"))
        self.assertEqual(call["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(call["body"]["thinking"], {"type": "disabled"})
        self.assertFalse(call["body"]["stream"])
        self.assertEqual(len(call["body"]["messages"]), 2)
        self.assertTrue(call["headers"]["Authorization"].startswith("Bearer "))
        self.assertNotIn(SECRET, json.dumps(call["body"], ensure_ascii=False))

    def test_429_and_5xx_retry_with_backoff(self):
        from COPA.apps.llm_chat import _RETRY_DELAYS

        provider, harness = make_provider([
            _HttpFailure(429, '{"error":{"message":"rate limited"}}'),
            _HttpFailure(503, '{"error":{"message":"busy"}}'),
            response(envelope("恢复", None)),
        ])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "恢复")
        # 退避必须按 _RETRY_DELAYS 逐段走，而且越等越长：免费模型 429 的
        # 窗口是分钟级，短促重试只会重复撞在同一批失败请求上。
        self.assertEqual(harness.sleeps, list(_RETRY_DELAYS[:2]))
        self.assertGreaterEqual(harness.sleeps[0], 2.0)
        self.assertGreater(harness.sleeps[1], harness.sleeps[0])

    def test_exhausted_retries_raise_without_secret(self):
        provider, harness = make_provider([
            _HttpFailure(500, '{"error":{"message":"upstream"}}') for _ in range(3)
        ])
        with self.assertRaises(ApiError) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertIn("HTTP 500", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertEqual(len(harness.sleeps), 2)

    def test_429_exhaustion_advises_retry(self):
        provider, _ = make_provider([
            _HttpFailure(429, '{"error":{"message":"busy"}}') for _ in range(3)
        ])
        with self.assertRaises(ApiError) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertIn("排队", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_auth_failure_is_not_retried(self):
        provider, harness = make_provider([
            _HttpFailure(401, '{"error":{"message":"invalid api key"}}')
        ])
        with self.assertRaises(ApiError) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertEqual(harness.sleeps, [])

    def test_400_drops_response_format_once(self):
        provider, harness = make_provider([
            _HttpFailure(400, '{"error":{"message":"response_format unsupported"}}'),
            response(envelope("降级成功", None)),
        ])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "降级成功")
        self.assertIn("response_format", " ".join(provider.warnings))
        self.assertNotIn("response_format", harness.calls[1]["body"])
        self.assertEqual(harness.sleeps, [])

    def test_empty_content_is_retryable(self):
        provider, harness = make_provider([
            response(""),
            response(envelope("这次有了", None)),
        ])
        reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(reply.message, "这次有了")
        self.assertEqual(harness.sleeps, [2.0])

    def test_persistently_empty_content_raises(self):
        provider, _ = make_provider([response("") for _ in range(3)])
        with self.assertRaises(ApiError) as ctx:
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertIn("空内容", str(ctx.exception))

    def test_missing_key_never_sends_a_request(self):
        settings = ChatSettings(base_url="https://example.invalid/v1", model="m", provider="api")
        harness = TransportHarness([response("ok")])
        provider = OpenAICompatibleProvider(settings, transport=harness, sleeper=harness.sleep)
        with self.assertRaises(ApiError):
            provider.complete({"messages": [{"role": "user", "content": "需求"}]})
        self.assertEqual(harness.calls, [])

    def test_session_routes_api_error_into_conversation(self):
        settings = ChatSettings(
            base_url="https://example.invalid/v1", model="m", api_key=SECRET, provider="api"
        )
        harness = TransportHarness([_HttpFailure(401, '{"error":{"message":"denied"}}')])
        provider = OpenAICompatibleProvider(settings, transport=harness, sleeper=harness.sleep)
        session = ChatSession(settings=settings, provider=provider)
        reply = session.send("一条需求")
        self.assertIn("HTTP 401", reply.message)
        self.assertIsNone(session.candidate)
        self.assertNotIn(SECRET, repr(session.messages))

    def test_session_stages_real_provider_candidate(self):
        settings = ChatSettings(
            base_url="https://example.invalid/v1", model="m", api_key=SECRET, provider="api"
        )
        harness = TransportHarness([response(envelope("候选已生成", demo_payload()))])
        provider = OpenAICompatibleProvider(settings, transport=harness, sleeper=harness.sleep)
        session = ChatSession(settings=settings, provider=provider)
        reply = session.send("平台秤，2000kg")
        assert isinstance(reply.payload, dict)
        self.assertTrue(session.preview()["ready"])
        assert session.candidate is not None
        self.assertFalse(session.candidate["quote"]["confirmed_by_user"])


class PromptRuleTests(unittest.TestCase):
    def test_prompt_infers_semantics_without_guessing_ban(self):
        session = ChatSession(provider=ScriptedProvider(["ok"]))
        prompt = session.messages[0]["content"]
        self.assertNotIn("严禁猜测", prompt)
        self.assertIn("按语义自行推断", prompt)
        self.assertIn("品牌短码", prompt)
        self.assertIn("只填当前 item_type", prompt)
        # Existing contract keywords remain intact for the rest of the suite.
        self.assertIn("允许多轮澄清", prompt)
        self.assertIn("message/payload", prompt)


class ConfigTests(unittest.TestCase):
    def _write(self, directory: str, document: dict) -> Path:
        path = Path(directory) / "providers.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def test_environment_variable_wins_and_key_never_appears_in_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "active": "zhipu",
                "providers": {"zhipu": {
                    "base_url": "https://example.invalid/v1",
                    "model": "glm-4.7-flash",
                    "api_key_env": "COPA_TEST_KEY",
                    "api_key": "file-key",
                    "supports_response_format": True,
                    "extra": {"thinking": {"type": "disabled"}},
                }},
            })
            with patch.dict(os.environ, {"COPA_TEST_KEY": "env-key"}):
                settings = load_provider_config(path)
            self.assertEqual(settings.api_key, "env-key")
            self.assertEqual(settings.provider, "api")
            self.assertEqual(settings.provider_name, "zhipu")
            self.assertTrue(settings.supports_response_format)
            self.assertNotIn("env-key", repr(settings))
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_provider_config(path).api_key, "file-key")

    def test_use_proxy_defaults_on_and_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = {
                "base_url": "https://example.invalid/v1",
                "model": "glm-4.7-flash",
                "api_key": "file-key",
            }
            default = self._write(tmp, {"active": "a", "providers": {"a": dict(base)}})
            self.assertTrue(load_provider_config(default).use_proxy)
            direct = self._write(tmp, {
                "active": "a",
                "providers": {"a": dict(base, use_proxy=False)},
            })
            self.assertFalse(load_provider_config(direct).use_proxy)

    def test_missing_file_and_missing_provider_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProviderConfigError):
                load_provider_config(Path(tmp) / "absent.json")
            path = self._write(tmp, {"active": "ghost", "providers": {}})
            with self.assertRaises(ProviderConfigError):
                load_provider_config(path)

    def test_local_provider_needs_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "active": "local",
                "providers": {"local": {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "model": "qwen3:14b",
                    "api_key_env": None,
                    "supports_response_format": True,
                }},
            })
            settings = load_provider_config(path)
            self.assertFalse(settings.requires_api_key)
            harness = TransportHarness([response(envelope("本地模型", None))])
            provider = OpenAICompatibleProvider(settings, transport=harness, sleeper=harness.sleep)
            reply = provider.complete({"messages": [{"role": "user", "content": "需求"}]})
            self.assertEqual(reply.message, "本地模型")
            self.assertNotIn("Authorization", harness.calls[0]["headers"])
            self.assertTrue(harness.calls[0]["url"].endswith("/chat/completions"))


if __name__ == "__main__":
    unittest.main()
