"""Qt-free conversation core for the COPA LLM dialog.

The dialog owns the conversation state and the hand-off boundary to the
existing COPA contract.  Local providers (``DemoProvider`` /
``ScriptedProvider`` / ``DisabledApiProvider``) never touch the network;
``OpenAICompatibleProvider`` implements the real transport with the stdlib
only.  Configuration and credentials are read from ``llm/providers.json``
or the environment and are never written to messages, logs or snapshots.

The model is only allowed to return a structured candidate.  A candidate is
always staged with ``quote.confirmed_by_user=False``; the dialog calls
``confirm(actual_count)`` automatically once the contract passes — there is
no preview/confirm button here, human review happens later in Checklist.
Exit intents only stop the clarification loop and surface a program notice.
Deterministic normalisation
(total weight -> W1/W2, missing c_brand -> m_brand) is done by the program at
staging time and recorded in provenance, never inferred by the model.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import contract
from .llm_io import load_payload

# 对话出口的机器信号。模型按语义判断用户意图，程序只认这三个值；
# 关键词表只在模型未输出 intent 时兜底，不承担语义判断。
CONTINUE = "continue"
NO_MORE_INFO = "no_more_info"
REQUEST_QUOTE = "request_quote"
_EXIT_INTENTS = frozenset({NO_MORE_INFO, REQUEST_QUOTE})


def _normalise_intent(value: Any) -> str:
    """Only known machine signals are accepted; everything else is continue."""

    text = str(value or "").strip().casefold()
    return text if text in _EXIT_INTENTS or text == CONTINUE else CONTINUE


@dataclass(frozen=True)
class ChatSettings:
    """Internal provider settings.

    ``api_key`` is excluded from ``repr`` so it cannot leak into previews,
    logs or conversation archives.  The extra transport fields only affect
    :class:`OpenAICompatibleProvider`.
    """

    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    provider: str = "demo"
    supports_response_format: bool = False
    extra: dict[str, Any] = field(default_factory=dict, repr=False)
    timeout: float = 60.0
    max_attempts: int = 3
    provider_name: str = ""
    requires_api_key: bool = True
    # 是否沿用系统/环境代理。内网机器上代理常指向一个没启动的端口，
    # 报出来就是 10061；把这条设成 false 即直连。
    use_proxy: bool = True


@dataclass
class ChatReply:
    """A provider response and an optional structured quote candidate.

    ``intent`` is the model's classification of the user's exit intent.  It is
    a machine signal, never an authorisation to quote: only a human clicking
    the confirmation button may set ``confirmed_by_user``.
    """

    message: str
    payload: dict[str, Any] | None = None
    intent: str = CONTINUE


class Provider:
    """Provider interface used by :class:`ChatSession`."""

    def complete(self, request: Mapping[str, Any]) -> ChatReply:
        raise NotImplementedError


class ApiDisabledError(RuntimeError):
    """Raised by the deliberately disabled no-network provider."""


class ApiError(RuntimeError):
    """A model-call failure whose message is safe to display in the dialog.

    Implementations must never place credentials, headers or full response
    bodies into this exception.
    """


class ProviderConfigError(ApiError):
    """The local provider configuration is missing or unusable."""


def _default_providers_path() -> Path:
    """Prefer the config beside the exe, then the source tree, then bundled data."""

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "llm" / "providers.json")
    candidates.append(Path(__file__).resolve().parent.parent / "llm" / "providers.json")
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "llm" / "providers.json")
    return next((path for path in candidates if path.is_file()), candidates[0])


DEFAULT_PROVIDERS_PATH = _default_providers_path()
# Free-tier models answer "访问量过大" with 429; short backoffs just race the
# 窗口而不是等它过去。实测星辰4.0 的限流窗口在 60 秒级别：2/4/8 秒三次退避
# 加起来 14 秒，连打 5 次全落在窗口内；改成 2/5/12/30 后累计约 49 秒，能跨过
# 一次完整的冷却期。max_attempts 上限仍是 5，所以这里第 5 段用不上，留作兜底。
_RETRY_DELAYS = (2.0, 5.0, 12.0, 30.0, 45.0)
# Free-tier models allow one concurrent request; the dialog keeps the rest
# of the application responsive while this lock serialises model calls.
_API_LOCK = threading.Lock()


class _HttpFailure(Exception):
    """Internal transport failure carrying only status and a sanitised body."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _http_message(status: int, detail: str) -> str:
    """Extract an upstream error message without echoing request headers."""

    text = ""
    try:
        parsed = json.loads(detail)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, Mapping):
        error = parsed.get("error")
        if isinstance(error, Mapping):
            text = str(error.get("message") or "")
        elif isinstance(error, str):
            text = error
        if not text:
            text = str(parsed.get("message") or "")
    if not text:
        text = str(detail or "")
    text = text.strip()[:300]
    if status == 0:
        return "网络异常：{}（如本机开了代理或加速器，先确认它还在运行）".format(
            text or "连接失败")
    return "HTTP {}：{}".format(status, text) if text else "HTTP {}".format(status)


_HTTP_CODE_RE = re.compile(r"HTTP\s*(\d{3})")


def error_code(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "调用失败"
    for prefix in ("模型调用失败：", "模型调用失败:", "发送失败：", "发送失败:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    if not raw:
        return "调用失败"
    match = _HTTP_CODE_RE.search(raw)
    if match:
        return "HTTP {}".format(match.group(1))
    if "网络异常" in raw or "连接失败" in raw or "10061" in raw:
        return "网络异常"
    if "排队" in raw:
        return "排队中"
    head = re.split(r"[：:，,。；;]", raw)[0].strip()
    if 0 < len(head) <= 14 and head not in {"模型调用失败", "发送失败"}:
        return head
    return "调用失败"


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float,
               *, use_proxy: bool = True) -> dict[str, Any]:
    """One OpenAI-compatible POST using only the standard library."""

    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # 空 ProxyHandler 表示直连：系统代理设了却不工作时，走它能救回来。
    opener = (urllib.request.build_opener() if use_proxy
              else urllib.request.build_opener(urllib.request.ProxyHandler({})))
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        raise _HttpFailure(exc.code, detail) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise _HttpFailure(0, str(reason)) from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiError("模型响应不是合法 JSON") from None
    if not isinstance(data, dict):
        raise ApiError("模型响应顶层不是对象")
    return data


def _response_content(data: Mapping[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""


def _decode_chat_reply(content: str) -> ChatReply:
    """Accept message/payload JSON, a bare quote payload, or plain prose."""

    text = content.strip()
    try:
        envelope = load_payload(text)
    except contract.ContractError:
        # A clarification round is ordinary prose; there is no candidate yet.
        return ChatReply(text)
    message = envelope.get("message")
    payload = envelope.get("payload")
    intent = _normalise_intent(envelope.get("intent"))
    if message is None and payload is None and ("items" in envelope or "schema_version" in envelope):
        return ChatReply("已收到结构化候选，请核对参数与条数。", envelope, intent)
    if payload is not None and not isinstance(payload, dict):
        payload = None
    if not str(message or "").strip() and payload is None:
        # 模型偶发返回约定之外的 JSON（实测 glm 对无 schema 的极简提示词会回
        # {"answer": "pong"}）。空 message 在界面上等同于「没有回应」，所以
        # 这里原样回显原始内容，至少让人看到模型到底说了什么。
        return ChatReply(text)
    return ChatReply(str(message or ""), payload, intent)


def load_provider_config(path: Any = None, name: str | None = None) -> ChatSettings:
    """Read ``llm/providers.json`` into memory-only :class:`ChatSettings`.

    Credentials resolve in this order: ``api_key_env`` environment variable,
    then the local ``api_key`` field.  Nothing here logs or persists a key.
    """

    target = Path(path) if path is not None else DEFAULT_PROVIDERS_PATH
    if not target.is_file():
        raise ProviderConfigError("找不到模型配置文件：{}".format(target))
    try:
        document = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProviderConfigError("模型配置读取失败：{}".format(exc)) from None
    if not isinstance(document, Mapping):
        raise ProviderConfigError("模型配置文件顶层必须是对象")
    active = str(name or document.get("active") or "").strip()
    providers = document.get("providers")
    cfg = providers.get(active) if isinstance(providers, Mapping) else None
    if not isinstance(cfg, Mapping):
        raise ProviderConfigError("模型配置中没有可用的提供方：{}".format(active or "(未指定)"))
    env_name = str(cfg.get("api_key_env") or "").strip()
    key = os.environ.get(env_name, "") if env_name else ""
    if not key:
        key = str(cfg.get("api_key") or "")
    requires_api_key = bool(env_name) or bool(key)
    extra = cfg.get("extra")
    try:
        timeout = float(cfg.get("timeout") or 60.0)
        attempts = max(1, min(5, int(cfg.get("max_attempts") or 3)))
    except (TypeError, ValueError) as exc:
        raise ProviderConfigError("模型配置的超时/重试次数无效：{}".format(exc)) from None
    return ChatSettings(
        base_url=str(cfg.get("base_url") or "").rstrip("/"),
        model=str(cfg.get("model") or ""),
        api_key=key.strip(),
        provider="api",
        supports_response_format=bool(cfg.get("supports_response_format")),
        extra=dict(extra) if isinstance(extra, Mapping) else {},
        timeout=timeout,
        max_attempts=attempts,
        provider_name=active,
        requires_api_key=requires_api_key,
        use_proxy=bool(cfg.get("use_proxy", True)),
    )


DEMO_TEXT = (
    "演示需求：一台平台秤，量程 2000kg，台面 1500x1500，材质碳钢，"
    "秤体品牌 FT，仪表品牌 FT，不防爆。"
)
DEMO_CONFIRM_TEXT = "确认以上演示参数，生成结构化候选。"


def demo_text() -> str:
    """Return the exact text shown by the UI's local demonstration action."""

    return DEMO_TEXT


def demo_payload() -> dict[str, Any]:
    """Build the fixed, explicit, locally verifiable demo payload.

    The schema fingerprint comes from the live COPA library marker.  All
    selection fields remain explicit; no free-text extraction or defaulting is
    performed here.
    """

    schema = contract.print_schema()
    return {
        "schema_version": 1,
        "origin": "llm",
        "schema_fingerprint": schema["schema_fingerprint"],
        "quote": {
            "project": "COPA 对话演示",
            "m_brand": "FT",
            "c_brand": "FT",
            "quote_title": "COPA B",
            "source": "COPA 本地演示",
            "declared_count": 1,
            "confirmed_by_user": False,
        },
        "items": [
            {
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
                "note": "COPA 本地演示：全部字段显式给出",
                "provenance": {
                    "W1": {"source": "demo", "basis": "演示固定参数 2000kg"},
                    "台面尺寸": {"source": "demo", "basis": "演示固定参数 1500x1500"},
                    "material": {"source": "demo", "basis": "演示固定参数 碳钢"},
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# 展示用例：「附件 + 一句话」报价
# ---------------------------------------------------------------------------

DEMO_CASE_ATTACHMENT = "设备清单.xlsx"

DEMO_CASE_TURNS: tuple[tuple[str, str], ...] = (
    ("附件", "附件：{}".format(DEMO_CASE_ATTACHMENT)),
    ("用户", "FT系列，报价"),
    (
        "LLM",
        "已提取到 3 条设备：两套称重模块（VT-1、VT-5；VT-2）和一台 3t 平台秤×2。"
        "先确认两点：称重模块的支腿按 4 支和 3 支配吗？平台秤的自重没填，按 0 算可以吗？",
    ),
    (
        "用户",
        "VT-1、VT-5 那两套四支腿，VT-2 三支腿；平台秤自重没数据，按 0 算。"
        "台面 1200×1200，220V，不防爆。其他没了，直接出。",
    ),
    (
        "LLM",
        "收到：VT-1、VT-5 四支腿，VT-2 三支腿；平台秤 1200×1200、AC220V，自重按 0。"
        "三条参数齐了，不再追问——现在推入选型，清单出来后核一下支腿数和台面尺寸就行。",
    ),
)


def demo_case_turns() -> tuple[tuple[str, str], ...]:
    """展示脚本：附件 → 用户一句话 → 模型追问 → 用户澄清 → 模型定稿。"""

    return DEMO_CASE_TURNS


def demo_case_payload() -> dict[str, Any]:
    """展示用例交接的参数：与上面那段对话一一对应，逐字段显式。

    数值来自实跑那一轮的候选，不做任何猜测或默认填充。
    """

    schema = contract.print_schema()
    return {
        "schema_version": 1,
        "origin": "llm",
        "schema_fingerprint": schema["schema_fingerprint"],
        "quote": {
            "project": "设备清单",
            "m_brand": "FT",
            "c_brand": "FT",
            # 抬头只按 m_brand 写死：FT → COPA B，与仪表品牌无关。
            "quote_title": "COPA B",
            "source": "llm",
            "declared_count": 3,
            "confirmed_by_user": False,
        },
        "items": [
            {
                "seq": 1,
                "item_type": "称重模块",
                "quantity": 2,
                "flags": {
                    "metrology": False,
                    "high_precision": False,
                    "ex": False,
                    "digital": False,
                    "onsite_service": False,
                },
                "fields": {
                    "W1": 5000,
                    "W2": 2000,
                    "support": 4,
                    "material": "碳钢",
                    "vibration": False,
                },
                "note": "VT-1、VT-5，4 支腿",
            },
            {
                "seq": 2,
                "item_type": "称重模块",
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
                    "W2": 1000,
                    "support": 3,
                    "material": "碳钢",
                    "vibration": False,
                },
                "note": "VT-2，3 支腿",
            },
            {
                "seq": 3,
                "item_type": "平台秤",
                "quantity": 2,
                "flags": {
                    "metrology": False,
                    "high_precision": False,
                    "ex": False,
                    "digital": False,
                    "onsite_service": False,
                },
                "fields": {
                    "W1": 3000,
                    "material": "不锈钢",
                    "台面尺寸": "1200x1200",
                    "power": "AC220V",
                },
                "note": "3t 平台秤，不锈钢",
                "provenance": {
                    "台面尺寸": {"source": "demo", "basis": "用户澄清 1200×1200"},
                    "power": {"source": "demo", "basis": "用户澄清 AC220V"},
                },
            },
        ],
    }


class DemoProvider(Provider):
    """Local provider with one explicit clarification round.

    It never interprets arbitrary prose.  Only the exact demonstration action
    and its explicit confirmation yield the fixed payload above.
    """

    def __init__(self) -> None:
        self._demo_requested = False

    def reset(self) -> None:
        """Forget an unfinished demonstration clarification round."""

        self._demo_requested = False

    def complete(self, request: Mapping[str, Any]) -> ChatReply:
        messages = request.get("messages") or ()
        text = ""
        for item in reversed(messages):
            if isinstance(item, Mapping) and item.get("role") == "user":
                text = str(item.get("content") or "")
                break
        if text == DEMO_TEXT:
            self._demo_requested = True
            return ChatReply(
                "这是 COPA 本地演示。请确认固定参数：2000kg、1500x1500、碳钢、"
                "FT 秤体、FT 仪表、不防爆。确认后我会提交结构化候选。"
            )
        if self._demo_requested and text.strip() == DEMO_CONFIRM_TEXT:
            self._demo_requested = False
            return ChatReply(
                "演示候选已生成，仍需用户在预览中核对条数并确认。",
                payload=demo_payload(),
            )
        return ChatReply(
            "本轮输入已记录；真实模型 API 尚未启用。请使用“载入演示”查看固定候选，"
            "COPA 不会从自由文本猜测选型参数。"
        )


class ScriptedProvider(Provider):
    """Deterministic local provider for tests and UI integration checks.

    ``replies`` may contain :class:`ChatReply`, strings, mappings with
    ``message``/``payload`` keys, or callables receiving the request.
    Requests are captured as deep copies for assertions; no logging occurs.
    """

    def __init__(
        self,
        replies: Iterable[ChatReply | str | Mapping[str, Any] | Callable[[Mapping[str, Any]], ChatReply]] = (),
    ) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def complete(self, request: Mapping[str, Any]) -> ChatReply:
        snapshot = copy.deepcopy(dict(request))
        self.requests.append(snapshot)
        if not self._replies:
            return ChatReply("脚本 provider 没有更多回复。")
        value = self._replies.pop(0)
        if callable(value):
            value = value(snapshot)
        if isinstance(value, ChatReply):
            return copy.deepcopy(value)
        if isinstance(value, str):
            return ChatReply(value)
        if isinstance(value, Mapping):
            payload = value.get("payload")
            return ChatReply(
                str(value.get("message") or ""),
                copy.deepcopy(payload) if isinstance(payload, dict) else None,
                _normalise_intent(value.get("intent")),
            )
        raise TypeError("脚本 provider 回复必须是 ChatReply、字符串、映射或可调用对象")


class DisabledApiProvider(Provider):
    """Explicit no-network seam for the future OpenAI-compatible transport."""

    def complete(self, request: Mapping[str, Any]) -> ChatReply:
        # Deliberately no requests/imports from HTTP clients are made here.
        raise ApiDisabledError("真实模型 API 调用当前已禁用；本轮未发出网络请求。")


class OpenAICompatibleProvider(Provider):
    """Real OpenAI-compatible ``/chat/completions`` transport.

    ``transport`` and ``sleeper`` are injectable so tests never touch the
    network.  The default transport is ``urllib`` from the standard library;
    no third-party SDK is required.
    """

    def __init__(
        self,
        settings: ChatSettings | None = None,
        *,
        transport: Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings or ChatSettings(provider="api")
        # 注入的 transport 保持四参数签名（测试里都是这么塞的），只有默认的
        # 真实传输才需要带 use_proxy。
        self._transport = transport or functools.partial(
            _post_json, use_proxy=bool(getattr(self.settings, "use_proxy", True)))
        self._sleep = sleeper or time.sleep
        self.last_model = ""
        self.warnings: list[str] = []

    @staticmethod
    def _endpoint(base_url: str) -> str:
        base = str(base_url or "").rstrip("/")
        if not base:
            return ""
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def complete(self, request: Mapping[str, Any]) -> ChatReply:
        settings = self.settings
        base_url = str(request.get("base_url") or settings.base_url or "")
        model = str(request.get("model") or settings.model or "")
        key = str(request.get("api_key") or settings.api_key or "")
        if not base_url:
            raise ApiError("未配置模型接口地址")
        if not model:
            raise ApiError("未配置模型名称")
        requires_key = bool(request.get("requires_api_key", settings.requires_api_key))
        if not key and requires_key:
            raise ApiError("未配置 API 口令：请设置环境变量或在 llm/providers.json 中填写 api_key")

        messages = request.get("messages") or []
        if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
            raise ApiError("消息上下文格式错误")
        clean_messages = [dict(item) for item in messages if isinstance(item, Mapping)]
        if not clean_messages:
            raise ApiError("消息上下文为空")

        supports = bool(request.get("supports_response_format", settings.supports_response_format))
        extra = dict(settings.extra)
        request_extra = request.get("extra")
        if isinstance(request_extra, Mapping):
            extra.update(request_extra)
        body: dict[str, Any] = {
            "model": model,
            "messages": clean_messages,
            "stream": False,
            "temperature": 0.2,
        }
        if supports:
            body["response_format"] = {"type": "json_object"}
        body.update(extra)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        url = self._endpoint(base_url)
        timeout = float(settings.timeout)
        attempts = max(1, int(settings.max_attempts))
        self.warnings = []

        data: dict[str, Any] | None = None
        content = ""
        attempt = 0
        downgraded = False
        with _API_LOCK:
            while attempt < attempts:
                try:
                    candidate = self._transport(url, dict(headers), dict(body), timeout)
                except _HttpFailure as exc:
                    # Some endpoints reject response_format outright; drop it
                    # once and rely on the prompt contract instead.
                    if exc.status == 400 and "response_format" in body and not downgraded:
                        body.pop("response_format")
                        downgraded = True
                        self.warnings.append("端点不支持 response_format，已改为纯提示词约束")
                        continue
                    # status=0 是超时/断网/DNS 失败；偶发网络抖动同样值得退避重试。
                    if (exc.status in (0, 429) or exc.status >= 500) and attempt + 1 < attempts:
                        attempt += 1
                        self._sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
                        continue
                    detail = _http_message(exc.status, exc.detail)
                    if exc.status == 429:
                        detail += "；免费模型当前排队，请稍后重试或稍后再发送"
                    raise ApiError("模型调用失败：{}".format(detail)) from None
                except ApiError:
                    raise
                except Exception as exc:
                    if attempt + 1 < attempts:
                        attempt += 1
                        self._sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
                        continue
                    raise ApiError("模型调用失败：{}".format(exc)) from None

                content = _response_content(candidate)
                if not content.strip():
                    # Empty content with finish_reason=stop is a known failure
                    # mode; treat it as retryable rather than an empty answer.
                    if attempt + 1 < attempts:
                        attempt += 1
                        self._sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
                        continue
                    raise ApiError("模型返回空内容，请重试或稍后再试")
                data = candidate
                break

        if data is None:
            raise ApiError("模型调用未得到响应")
        self.last_model = str(data.get("model") or model)
        return _decode_chat_reply(content)


# ---------------------------------------------------------------------------
# 校验反馈 LOOP：程序只负责「当前还缺什么」这一事实，面向用户的话术、人设、
# 语气全部交给模型。清单每轮由 _refresh_feedback() 依据最近一次候选重算，
# 只在请求里动态注入，绝不落进 session.messages —— 旧清单因此不会累积，
# 下一轮模型看到的永远是程序刚刚算出的当前状态。
# ---------------------------------------------------------------------------
# 需要人补充/确认的错误。其余（TYPE / RANGE / COUNT_MISMATCH / NOT_CONFIRMED
# / SCHEMA_VERSION / ITEM_TYPE / CONDITIONAL / NONSTANDARD_SIZE / ...）是候选
# 结构或程序处理项，不进中文缺参清单、不向用户追问。非标尺寸由程序降级到最接近
# 的标准规格，并在人工确认时留痕，不要求用户回答一个界面上无法确认的问题。
_ASKABLE_CODES = frozenset({"MISSING_FIELD", "ENUM"})
# 用户坚持报价时允许带缺项放行的业务非必须项。W1(总重)/材质/台面尺寸等
# 必须项与任何结构类错误一票否决。c_brand 已在程序归一阶段按 m_brand 补齐，
# 不再进入缺项清单；供电(power) 本就是契约可选字段，缺值不产生校验错误，
# 直接随正常流程进 Checklist，由人在 AC220V / DC24V 两种候选里确认。
_FORCE_QUOTE_LABELS = {
    "W2": "皮重",
    "vibration": "高速搅拌",
    "RPM": "搅拌转速",
    "req_com2": "拓展通讯",
    "e_input": "精度要求",
    "c_family": "仪表型号",
    "台面尺寸": "台面尺寸（降级为最近标准规格）",
}
_FORCE_QUOTE_DEFAULTS = {"W2": 0, "vibration": False, "RPM": 0}
_FORCE_QUOTE_CODES = frozenset({"MISSING_FIELD", "CONDITIONAL", "NONSTANDARD_SIZE"})
_FORCE_QUOTE_BASIS = "用户坚持报价，非必须项按中性默认处理，请在 Checklist 人工核对"
_LEFT_UNSET_BASIS = "用户未提供，保持留空，请在 Checklist 人工确认"
# 熔断：模型补不动的时候，继续追问只是把用户困在对话里。同一 (path, code)
# 连续这么多轮原样出现，就判定这一项模型改不了，转人工；连续这么多轮根本没
# 提交候选（只复述/闲聊），同样判定本模式推不动。
_STALL_ROUNDS = 3
_EMPTY_ROUND_LIMIT = 2
_STALL_NOTICE = "当前模式未能推进，建议转选型计算功能再次输入。"
_SIZE_DOWNGRADE_BASIS = (
    "非标尺寸 {requested} 已降级为最接近的标准规格 {size}（曼哈顿差 {distance} mm），"
    "输出后必须人工改回实际尺寸"
)

# 程序归一：这两项属于确定性换算/默认，交给程序而非模型语义推断。
# 与 apps/Parser.py 的「总重归一」同口径，字段名也沿用 W_total。
_TOTAL_WEIGHT_KEYS = ("W_total", "总重")
_TOTAL_WEIGHT_BASIS = "原文只给总重，按老口径归一：W1=总重、W2=0，请在 Checklist 人工核对"
_MODEL_SPLIT_BASIS = "皮重为 0，按 Desk 老口径视为只知总重（W1=总重、W2=0），请在 Checklist 人工核对"


def normalize_program_defaults(payload: Mapping[str, Any]) -> dict[str, Any]:
    """LLM 侧的程序归一，无法换算的总重数值原样落到 W1，由契约报 TYPE 而不是静默丢失。
    """

    staged = copy.deepcopy(dict(payload))
    items = staged.get("items")
    if not isinstance(items, list):
        return staged
    for item in items:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        provenance = (
            copy.deepcopy(item["provenance"])
            if isinstance(item.get("provenance"), dict) else {}
        )

        for key in _TOTAL_WEIGHT_KEYS:
            if key not in fields:
                continue
            raw_total = fields.pop(key)
            if "W1" not in fields and "W2" not in fields:
                total = contract._weight_to_kg(raw_total)
                fields["W1"] = total if total is not None else raw_total
                fields["W2"] = 0
                provenance["W1"] = {"source": "total_weight", "basis": _TOTAL_WEIGHT_BASIS}
                provenance["W2"] = {"source": "total_weight", "basis": _TOTAL_WEIGHT_BASIS}
            break

        if fields.get("W2") == 0 and fields.get("W1") is not None:
            for name in ("W1", "W2"):
                if name not in provenance:
                    provenance[name] = {
                        "source": "total_weight",
                        "basis": _MODEL_SPLIT_BASIS,
                    }

        if provenance:
            item["provenance"] = provenance

    quote = staged.get("quote")
    if isinstance(quote, dict):
        m_brand = quote.get("m_brand")
        c_brand = quote.get("c_brand")
        if (c_brand is None or (isinstance(c_brand, str) and not c_brand.strip())) \
                and isinstance(m_brand, str) and m_brand.strip():
            quote["c_brand"] = m_brand.strip()
    return staged


_QUOTE_REQUEST_MARKS = (
    "报价吧", "出报价", "生成报价", "直接报价", "开始报价", "去报价",
    "给我报价", "报价单吧", "直接算吧", "开始选型", "进入选型", "报个价",
)
_NO_INFO_PHRASES = (
    "没有更多信息", "没有其他信息", "没有别的信息", "没有其它信息",
    "不知道", "不清楚", "无法提供", "不提供了", "就这些", "没有了",
    "暂不提供", "无补充", "就这么多",
)
# 程序侧兜底只认最直白的收尾句；语义相近的无穷说法由模型的 intent 判。
_QUOTE_STOP_MARKS = (
    "没别的", "没有别的", "没其他", "没有其他", "没其它", "没有其它",
    "就这些", "就这样", "就这么多", "够了", "可以了", "不用再问",
    "别问了", "不用问了", "没有更多信息", "没更多信息", "不用了", "直接",
)
_FEEDBACK_HEADER = "COPA 契约校验（程序生成，非用户输入）："
_FEEDBACK_PROTOCOL = (
    '按 {"message","payload","intent"} 协议回复本轮；message 措辞由你决定，'
    "只问上面 missing 里的项；payload 只交本轮新增或修正的字段，已交过的不要重复，"
    "缺项保持缺失，不要推断补齐。"
)


# ---------------------------------------------------------------------------
# 防爆确认：唯一由程序强制追问的附加要求。
#
# 这几个集合是「是否触发追问」的唯一控制点：用户原文命中 _EX_TOPIC_TERMS
# 就视为已表态，程序直接落值；一条都不命中才追问，答了才放行自动交接。
# 下一轮会把它们提到外部配置，届时只改集合就能手动调控追问范围，判定逻辑
# 与词表解耦，不需要动别处。
# 其余四项（计量/高精度/数字式/现场服务）是强信号：用户没提一律 false，
# 不猜测、不追问、不标注，成本交给 Checklist。
# ---------------------------------------------------------------------------
_EX_TOPIC_TERMS = (
    "防爆等级", "防爆", "隔爆", "本安", "甲类车间", "Exd", "Exi", "IIBT", "IICT", "ATEX", "ex-proof"
)
_EX_NEGATIONS = ("不需要", "不用", "无需", "没有", "不要", "不", "不是", "非")
_EX_DECLINE_REPLIES = (
    "不用", "不需要", "无需", "没有", "否", "都不用", "都没有", "不要",
)
_EX_ACCEPT_REPLIES = ("要", "需要", "是", "有", "对", "要的")
_EX_QUESTION = (
    "COPA 防爆确认（程序生成，非用户新需求）：本轮原文未提到防爆，"
    "请在 message 里追问用户是否需要防爆，具体防爆等级是多少？需要得到用户明确的答复。"
    "不需写进 payload。用户回答后程序自动判定。"
)


def _scan_ex(text: str, asked: bool) -> bool | None:
    """Return True/False once the user has stated an EX requirement, else None.

    ``asked`` 表示上一轮已经问过：此时才接受「不用」「要」这类不含防爆二字
    的短回复，否则门禁永远解除不了。短回复只在被追问后才认，避免首轮
    「不用不锈钢」被误判成否定防爆。否定词用 ``endswith`` 看主题词紧邻
    前缀，同理不会把「不锈钢防爆」里的「不」当成否定。
    """

    stripped = str(text).strip()
    lowered = stripped.casefold()
    hit = -1
    for term in _EX_TOPIC_TERMS:
        pos = lowered.find(term.casefold())
        if pos >= 0 and (hit < 0 or pos < hit):
            hit = pos
    if hit >= 0:
        prefix = stripped[max(0, hit - 4):hit]
        return not any(prefix.endswith(mark) for mark in _EX_NEGATIONS)
    if asked:
        cleaned = stripped.rstrip(" \t，,。.！!？?、；;：:")
        if cleaned.endswith("了"):
            cleaned = cleaned[:-1]
        if cleaned in _EX_DECLINE_REPLIES:
            return False
        if cleaned in _EX_ACCEPT_REPLIES:
            return True
    return None


def _feedback_body(
    missing: Sequence[str],
    errors: Sequence[Mapping[str, Any]],
    allowed: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """把缺参清单与原始错误压成一行 JSON，省掉重复的中文说明。

    ``allowed`` 是程序查出的合法取值：光说「这条不对」，小模型会原地换几种
    写法继续错；把可选项一起给它，修复率明显更高，而多出来的字符只有几十个。
    """

    body: dict[str, Any] = {"missing": list(missing)}
    if errors:
        rows: list[dict[str, Any]] = []
        for item in errors:
            row: dict[str, Any] = {
                "path": item.get("path"),
                "code": item.get("code"),
                "message": item.get("message"),
            }
            values = (allowed or {}).get(str(item.get("path")))
            if values:
                row["allowed"] = list(values)
            rows.append(row)
        body["errors"] = rows
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _stall_label(path: str) -> str:
    """把错误 path 收成一个能给人看的字段名。"""

    field = str(path).rsplit(".", 1)[-1]
    return _FORCE_QUOTE_LABELS.get(field, field or "候选结构")


def _submitted_fields(payload: Any) -> list[str]:
    """List field names a round actually submitted, for the archive.

    只留字段名不留值：够回答「这一轮补了什么」，又不会把整份候选塞进日志。
    """

    if not isinstance(payload, Mapping):
        return []
    names: list[str] = []
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            fields = item.get("fields") if isinstance(item, Mapping) else None
            if isinstance(fields, Mapping):
                names.extend(str(key) for key in fields)
    return list(dict.fromkeys(names))


def _classify_user_intent(text: str) -> str | None:
    """模型未给出 intent 时的窄兜底，只认最直白的两类收尾句。

    语义判断归模型（「类似」的说法无穷无尽）；这里靠长度上限防止把
    「材质不清楚，其余照旧」这样的有效补充误判成放弃。
    request_quote 必须先判：「就这些，报价吧」是要求报价，不是没信息了。
    """

    stripped = text.strip()
    if not stripped or len(stripped) > 32:
        return None
    if any(mark in stripped for mark in _QUOTE_REQUEST_MARKS) and (
        any(mark in stripped for mark in _QUOTE_STOP_MARKS) or "吧" in stripped
    ):
        return REQUEST_QUOTE
    if len(stripped) <= 24 and any(phrase in stripped for phrase in _NO_INFO_PHRASES):
        return NO_MORE_INFO
    return None


def _error(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _merge_candidate(
    previous: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge a partial round into the previous candidate.

    Models sometimes resend only the fields they just learned.  Replacing the
    whole candidate would silently drop everything confirmed in earlier turns.
    Explicit values (including ``null``) always win over inherited ones.

    条目匹配有两条路：双方每个条目都带整数 ``seq`` 时按 ``seq`` 对齐（多条
    报价里只改其中一条的唯一可靠办法）；否则退回按位置对齐，条数不同就整份
    替换——那种情况只能由模型交完整列表来表达「条数变了」。
    """

    if not isinstance(previous, Mapping):
        return copy.deepcopy(dict(incoming))
    merged = copy.deepcopy(dict(previous))
    for key, value in incoming.items():
        if key in ("items", "quote"):
            continue
        merged[key] = copy.deepcopy(value)
    quote = incoming.get("quote")
    if isinstance(quote, Mapping) and isinstance(merged.get("quote"), Mapping):
        quote_merged = copy.deepcopy(dict(merged["quote"]))
        quote_merged.update(copy.deepcopy(dict(quote)))
        merged["quote"] = quote_merged
    elif quote is not None:
        merged["quote"] = copy.deepcopy(quote)

    new_items = incoming.get("items")
    old_items = previous.get("items")
    if not isinstance(new_items, list):
        return merged
    if not isinstance(old_items, list):
        merged["items"] = copy.deepcopy(new_items)
        return merged
    old_items = [item for item in old_items if isinstance(item, Mapping)]
    new_items = [item for item in new_items if isinstance(item, Mapping)]
    if not old_items or not new_items:
        merged["items"] = copy.deepcopy(new_items)
        return merged

    def _seqs(values: Sequence[Any]) -> list[int] | None:
        seqs = [value.get("seq") for value in values]
        if all(isinstance(seq, int) and not isinstance(seq, bool) for seq in seqs):
            return seqs
        return None

    old_seqs = _seqs(old_items)
    new_seqs = _seqs(new_items)
    if old_seqs is not None and new_seqs is not None:
        by_seq = {seq: copy.deepcopy(dict(item)) for seq, item in zip(old_seqs, old_items)}
        for seq, item in zip(new_seqs, new_items):
            target = by_seq.get(seq)
            if target is None:
                # 模型点名了一个还不存在的条目：当作新增，按 seq 排序落位。
                by_seq[seq] = copy.deepcopy(dict(item))
                continue
            by_seq[seq] = _merge_item(target, item)
        merged["items"] = [by_seq[seq] for seq in sorted(by_seq)]
        return merged

    if len(old_items) != len(new_items):
        merged["items"] = copy.deepcopy(new_items)
        return merged
    merged["items"] = [
        _merge_item(copy.deepcopy(dict(old)), new)
        for old, new in zip(old_items, new_items)
    ]
    return merged


def _merge_item(item: dict[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay one round's item onto an earlier one, deep-merging its maps."""

    for key, value in incoming.items():
        if key in ("fields", "flags", "provenance") and isinstance(value, Mapping) \
                and isinstance(item.get(key), Mapping):
            nested = copy.deepcopy(dict(item[key]))
            nested.update(copy.deepcopy(dict(value)))
            item[key] = nested
        else:
            item[key] = copy.deepcopy(value)
    return item


class ChatSession:
    """Conversation state, candidate staging, preview and confirmation."""

    def __init__(
        self,
        settings: ChatSettings | None = None,
        provider: Provider | None = None,
    ) -> None:
        self.settings = settings or ChatSettings()
        self.provider = provider or self._provider_for_settings(self.settings)
        self._candidate: dict[str, Any] | None = None
        self._draft = ""
        self.messages: list[dict[str, str]] = []
        # 归档与可观测：首轮原文、每轮调用事件、最近一次调用失败原因。
        self.source_text = ""
        self.events: list[dict[str, Any]] = []
        self._last_error: str | None = None
        self._round = 0
        # 独立于 _candidate 的快照：send() 开头会作废 _candidate，但清单
        # 必须基于「最近一次模型提交的候选」才能跨轮保持准确。
        self._feedback_candidate: dict[str, Any] | None = None
        self._feedback_text: str | None = None
        self._feedback_fields: list[str] = []
        self._feedback_stopped = False
        # 熔断：同一 (path, code) 连续出现的轮次、连续空回合数、熔断原因。
        # 三者都不进模型上下文，只用于出口判定与归档诊断。
        self._error_streak: dict[tuple[str, str], int] = {}
        self._streak_round = -1
        self._empty_rounds = 0
        self._stall_reason: str | None = None
        # 防爆门禁：None=用户尚未表态（追问中），True/False=程序已判定。
        # _ex_active 把门禁限定在 LLM 会话路径；手工导入 / CLI 不受影响。
        self._ex_state: bool | None = None
        self._ex_active = False
        self._ex_asked = False
        # 出口状态：collecting / awaiting_confirm / stopped / confirmed。
        # notice 是给 UI 的一次性系统消息，绝不进 session.messages。
        self._exit_state = "collecting"
        self._exit_notice: str | None = None
        self._exit_signature: tuple[str, str] | None = None
        self._start_context()

    @staticmethod
    def _provider_for_settings(settings: ChatSettings) -> Provider:
        kind = settings.provider.casefold()
        if kind == "disabled":
            return DisabledApiProvider()
        if kind in {"api", "openai", "openai-compatible"}:
            return OpenAICompatibleProvider(settings)
        return DemoProvider()

    def _start_context(self) -> None:
        # 单一真源：对话协议(00-*.md)、schema 与其余规则都由 contract 组装，
        # 避免这里再维护一份会与 rules/*.md 漂移的副本。
        self.messages = [{"role": "system", "content": contract.print_prompt()}]

    @property
    def candidate(self) -> dict[str, Any] | None:
        """Return a copy so UI edits cannot bypass the staging boundary."""

        return copy.deepcopy(self._candidate)

    def set_draft(self, text: str) -> None:
        """Record an input edit and invalidate any previous confirmation."""

        self._draft = str(text)
        self._invalidate_candidate()

    edit_input = set_draft

    def _invalidate_candidate(self) -> None:
        self._candidate = None

    def send(self, text: str) -> ChatReply:
        """Append one user turn, call the local provider, and stage its payload.

        校验反馈由程序按最近一次候选实时生成，作为一条临时的 user 消息插在
        本轮输入之前；它不进 ``self.messages``，所以下一轮不会残留旧清单。
        """

        if not isinstance(text, str):
            raise TypeError("对话输入必须是字符串")
        self._draft = text
        self._invalidate_candidate()
        if not text.strip():
            return ChatReply("请输入需求后再发送。")

        # 上一轮已熔断、用户这次主动补充：给模型一次重新推进的机会。只在
        # 熔断后清计数，否则「连续三轮」会被每轮开头清零，永远到不了阈值。
        if self._stall_reason:
            self._stall_reason = None
            self._error_streak.clear()
            self._empty_rounds = 0
            self._streak_round = -1

        # 防爆扫描必须先于收尾意图判定：用户回「不用」既是防爆否定，
        # 也可能被 _classify_user_intent 当成收尾，先落值才不会丢表态。
        self._ex_active = True
        verdict = _scan_ex(text, self._ex_asked)
        if verdict is not None:
            self._ex_state = verdict
            self._ex_asked = False

        user_intent = _classify_user_intent(text)
        if user_intent:
            # 兜底：用户直接说出收尾句时先停止追问；模型本轮的 intent 优先。
            self._feedback_stopped = True
            self._feedback_text = None
            self._feedback_fields = []
        elif self._feedback_stopped:
            # 用户又给了新信息，恢复 LOOP，并立刻按最近快照重算清单。
            self._feedback_stopped = False
            self._refresh_feedback()

        if not self.source_text:
            self.source_text = text
        self.messages.append({"role": "user", "content": text})
        # 系统提示以外的 system 条目只用于界面展示（例如调用失败），组包时
        # 过滤掉，避免 HTTP 错误文案变成模型下一轮的上下文。
        request_messages = [
            message for index, message in enumerate(self.messages)
            if index == 0 or message.get("role") != "system"
        ]
        request_messages.pop()  # 本轮输入排到反馈之后，保证因果顺序
        feedback = self._feedback_text
        if self.ex_pending:
            self._ex_asked = True
            if feedback:
                # 有缺项清单时合并进同一条消息，不新增 user 消息：清单仍
                # 紧邻本轮输入，历史消息结构与既有断言都不受影响。
                feedback = feedback + "\n" + _EX_QUESTION
            else:
                request_messages.append({"role": "user", "content": _EX_QUESTION})
        if feedback:
            request_messages.append({"role": "user", "content": feedback})
        request_messages.append({"role": "user", "content": text})
        request: dict[str, Any] = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "provider": self.settings.provider,
            "api_key": self.settings.api_key,
            "messages": request_messages,
        }
        self._round += 1
        started = time.monotonic()
        failed = False
        try:
            reply = self.provider.complete(request)
        except (ApiDisabledError, ApiError) as exc:
            failed = True
            self._last_error = str(exc)
            reply = ChatReply(str(exc))
        if not isinstance(reply, ChatReply):
            raise TypeError("provider.complete() 必须返回 ChatReply")
        if failed:
            # 失败轮不改出口状态、不动候选，只留一条可见的系统记录。
            # 传输层已经写过「模型调用失败：」，这里不再套第二层。
            reason = str(reply.message or "")
            prefix = "模型调用失败："
            if reason.startswith(prefix):
                reason = reason[len(prefix):]
            self.messages.append({
                "role": "system",
                "content": "程序提示：本轮模型调用失败：{}".format(reason),
            })
            self._record_event(started, reply.intent, error=reply.message)
            return copy.deepcopy(reply)
        self._last_error = None
        if reply.message or isinstance(reply.payload, dict):
            # 历史里只留 message 信封，不再回填**完整 payload**。
            # 上一轮的字段值已经落在 candidate 里，而「还缺什么」由程序每轮
            # 重算的校验反馈注入；把完整 JSON 塞回历史，等于第 3 轮就把前两轮
            # 的全部字段再念一遍，越聊越贵。保留 {"message": ...} 这个信封，
            # 是为了继续给模型一个「回复必须是 JSON 对象」的格式示范。
            self.messages.append({
                "role": "assistant",
                "content": json.dumps(
                    {"message": reply.message}, ensure_ascii=False, sort_keys=True),
            })
        if isinstance(reply.payload, dict):
            # 模型可能只提交本轮新字段：与上一轮候选按 seq 合并，
            # 避免「只答一部分」把已确定字段整体冲掉。
            self._empty_rounds = 0
            self.load_candidate(reply.payload, merge=True)
        else:
            # 模型本轮只追问、没提交候选时，也按最近一次快照重算清单，
            # 保证下一轮上下文依旧是程序刚算出的当前状态。
            # 连续空回合同样熔断：缺项清单会原样重发，用户只会觉得程序卡死。
            self._empty_rounds += 1
            if (self._empty_rounds >= _EMPTY_ROUND_LIMIT
                    and not self._stall_reason):
                self._stall_reason = "连续 {} 轮未提交候选".format(
                    self._empty_rounds)
            self._refresh_feedback()
        self._evaluate_exit(user_intent, reply.intent)
        self._record_event(
            started, reply.intent, submitted=_submitted_fields(reply.payload))
        return copy.deepcopy(reply)

    def _record_event(
        self,
        started: float,
        intent: str,
        *,
        error: str | None = None,
        submitted: Sequence[str] = (),
    ) -> None:
        """Record one call as secret-free telemetry for the archive."""

        _, ready, fields, errors, count = self._candidate_facts()
        self.events.append({
            "round": self._round,
            "provider": self.settings.provider,
            "model": self.settings.model,
            "intent": intent,
            "exit_state": self._exit_state,
            "ready": bool(ready),
            "items": count,
            "missing": list(fields),
            "submitted": list(submitted),
            # 失败归因：只留 path 与 code，够统计「哪个模型栽在哪个字段」，
            # 又不把整份候选和值塞进日志。
            "errors": [
                {"path": str(item.get("path") or ""),
                 "code": str(item.get("code") or "")}
                for item in errors
            ],
            "stall": self._stall_reason,
            "force_quote": bool(self._force_quote_plan()[0]),
            "ex_state": self._ex_state,
            "downgrades": self.size_downgrades,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        })

    @property
    def last_error(self) -> str | None:
        """最近一次模型调用失败原因；成功后清空。"""

        return self._last_error

    def archive(self) -> dict[str, Any]:
        """Session archive for chat.json: no api_key, no request headers."""

        return {
            "source_text": self.source_text,
            "messages": copy.deepcopy(self.messages),
            "events": copy.deepcopy(self.events),
            "exit_state": self._exit_state,
            "force_quote_labels": self.force_quote_labels,
            "size_downgrades": self.size_downgrades,
            "settings": {
                "provider": self.settings.provider,
                "model": self.settings.model,
                "base_url": self.settings.base_url,
            },
        }

    def load_candidate(
        self,
        payload: Mapping[str, Any],
        *,
        merge: bool = False,
    ) -> None:
        """Stage a model candidate as pending and force user confirmation off.

        ``merge=True`` is used for model rounds: fields omitted this round are
        inherited from the previous candidate.  Manual JSON import keeps the
        default replacement behaviour.
        """

        if not isinstance(payload, Mapping):
            raise TypeError("候选 payload 必须是对象")
        # 模型按提示词在无证据推断值后附 (generated)；暂存前剥成合法值，
        # 同时在 provenance 留下机器可读的来源标记。随后由程序做确定性归一：
        # 总重拆 W1/W2、c_brand 回退 m_brand，二者都不交给模型推断。
        incoming = normalize_program_defaults(
            contract.apply_program_fields(
                contract.normalize_generated_marks(payload)
            )
        )
        staged = (
            _merge_candidate(self._feedback_candidate, incoming)
            if merge else incoming
        )
        if merge:
            # 结构字段必须在合并之后补：合并前补 seq，单条增量会被当成第 1 条。
            staged = contract.fill_structural_fields(staged)
            # 附加要求同样等合并完再补：模型已不再输出 flags，ex 以程序
            # 判定为准；未表态时只补 false，门禁会拦住自动交接。
            staged = contract.apply_program_flags(staged, self._ex_state)
        quote = staged.get("quote")
        if isinstance(quote, Mapping):
            quote_copy = dict(quote)
            quote_copy["confirmed_by_user"] = False
            staged["quote"] = quote_copy
        else:
            # Keep malformed payloads available for preview diagnostics.
            staged["quote"] = quote
        self._candidate = staged
        self._feedback_candidate = copy.deepcopy(staged)
        self._refresh_feedback()

    # ---- 校验反馈 LOOP：程序侧，唯一真源是 contract 校验器 ------------------

    @property
    def feedback_text(self) -> str | None:
        """当前轮次将注入请求的校验反馈；None 表示无需追问。"""

        return self._feedback_text

    @property
    def feedback_fields(self) -> list[str]:
        """当前仍缺字段的中文清单（已去重），供 UI / 归档 / 测试查看。"""

        return list(self._feedback_fields)

    @property
    def feedback_stopped(self) -> bool:
        """用户已表示没有更多信息，LOOP 已停止追问。"""

        return self._feedback_stopped

    @property
    def ex_pending(self) -> bool:
        """防爆尚未表态：UI 自动交接必须拦住，直到用户回答那一次追问。

        只在 LLM 会话路径生效；手工导入 / CLI 直接交候选时不拦，避免把
        旧归档和离线运行挡在门外。``confirm()`` 本身不设门禁——门禁属于
        UI 自动交接策略，程序接口仍按调用方判断。
        """

        return self._ex_active and self._ex_state is None

    def _candidate_facts(self) -> tuple[bool, bool, list[str], list[dict[str, Any]], int]:
        """最近一次候选的校验事实：(有候选, 已通过, 中文缺参, 原始错误, 条数)。

        确认标记按 preview() 口径临时置 true：条数确认由界面负责，不能算成缺项。
        """

        if self._feedback_candidate is None:
            return False, False, [], [], 0
        temp = copy.deepcopy(self._feedback_candidate)
        quote = temp.get("quote")
        if isinstance(quote, Mapping):
            quote_copy = dict(quote)
            quote_copy["confirmed_by_user"] = True
            temp["quote"] = quote_copy
        errors, _ = self._validate(temp)
        askable = [
            str(item["message"]).strip()
            for item in errors
            if item.get("code") in _ASKABLE_CODES and str(item.get("message") or "").strip()
        ]
        items = temp.get("items")
        count = len(items) if isinstance(items, list) else 0
        return True, not errors, list(dict.fromkeys(askable)), errors, count

    def _force_quote_plan(self) -> tuple[bool, list[str], dict[int, set[str]]]:
        """判断当前候选能否带缺项报价，并列出需补中性默认的字段。

        白名单之外的任何错误（W1/总重、材质、防爆等级、类型、枚举、条数…）
        一票否决。c_brand 已由程序按 m_brand 补齐，power 是契约可选字段、
        缺值不产生错误，两者都不再进入这里。

        非标台面尺寸是唯一需要换算的放行项：只允许 ``NONSTANDARD_SIZE``，
        且必须能在通表里算出最接近的标准规格，否则仍否决。
        """

        if self._candidate is None:
            return False, [], {}
        has, ready, _, errors, _ = self._candidate_facts()
        if not has or ready or not errors:
            return False, [], {}
        raw_items = (
            self._feedback_candidate.get("items")
            if isinstance(self._feedback_candidate, Mapping) else None
        )
        items = raw_items if isinstance(raw_items, list) else []
        labels: list[str] = []
        touched: dict[int, set[str]] = {}
        for problem in errors:
            code = str(problem.get("code") or "")
            path = str(problem.get("path") or "")
            field = path.rsplit(".", 1)[-1]
            match = re.search(r"items\[(\d+)\]", path)
            index = int(match.group(1)) if match else 0
            item = items[index] if index < len(items) and isinstance(items[index], Mapping) else {}
            if field not in _FORCE_QUOTE_LABELS or code not in _FORCE_QUOTE_CODES:
                return False, [], {}
            if field == "台面尺寸":
                if code != "NONSTANDARD_SIZE":
                    return False, [], {}
                raw_fields = item.get("fields")
                fields = raw_fields if isinstance(raw_fields, Mapping) else {}
                item_type = item.get("item_type")
                if contract.nearest_standard_size(
                        item_type if isinstance(item_type, str) else "",
                        fields.get("台面尺寸")) is None:
                    return False, [], {}
            elif code == "NONSTANDARD_SIZE":
                return False, [], {}
            labels.append(_FORCE_QUOTE_LABELS[field])
            touched.setdefault(index, set()).add(field)
        if not touched:
            return False, [], {}
        return True, list(dict.fromkeys(labels)), touched

    @property
    def size_downgrades(self) -> list[dict[str, Any]]:
        """非标尺寸放行后将采用的降级方案，供系统消息与归档使用。"""

        allowed, _, touched = self._force_quote_plan()
        if not allowed:
            return []
        raw_items = (
            self._feedback_candidate.get("items")
            if isinstance(self._feedback_candidate, Mapping) else None
        )
        items = raw_items if isinstance(raw_items, list) else []
        result: list[dict[str, Any]] = []
        for index, names in sorted(touched.items()):
            if "台面尺寸" not in names:
                continue
            item = items[index] if index < len(items) and isinstance(items[index], Mapping) else {}
            raw_fields = item.get("fields")
            fields = raw_fields if isinstance(raw_fields, Mapping) else {}
            item_type = item.get("item_type")
            plan = contract.nearest_standard_size(
                item_type if isinstance(item_type, str) else "", fields.get("台面尺寸"))
            if plan is None:
                continue
            result.append({"seq": item.get("seq", index + 1), **plan})
        return result

    def _apply_force_quote_defaults(self, touched: Mapping[int, set[str]]) -> None:
        """只在用户真正点确认后补中性默认，并在 provenance 留痕供人工复核。"""

        for source in (self._candidate, self._feedback_candidate):
            if not isinstance(source, dict):
                continue
            items = source.get("items")
            if not isinstance(items, list):
                continue
            for index, names in touched.items():
                if index >= len(items) or not isinstance(items[index], dict):
                    continue
                item = items[index]
                fields = item.setdefault("fields", {})
                provenance = item.setdefault("provenance", {})
                for name in names:
                    if name == "台面尺寸":
                        # 非标尺寸不保留原值：降级到最近的标准规格，并在
                        # Checklist 用原始尺寸强制提示人工改回。
                        plan = contract.nearest_standard_size(
                            item.get("item_type"), fields.get("台面尺寸")
                        )
                        if plan is None:
                            continue
                        fields[name] = plan["size"]
                        item["confirmed_nonstandard"] = True
                        item["nonstandard_size"] = plan["requested"]
                        provenance[name] = {
                            "source": "size_downgraded",
                            "basis": _SIZE_DOWNGRADE_BASIS.format(
                                requested=plan["requested"],
                                size=plan["size"],
                                distance=plan["distance_mm"],
                            ),
                        }
                        continue
                    value = _FORCE_QUOTE_DEFAULTS.get(name)
                    if value is None:
                        # 拓展通讯 / 精度 / 仪表型号本就是可选字段：保持缺失，
                        # 但必须留痕，让 Checklist 顶部标红要人核对——静默
                        # 通过比缺一个字段危险得多。
                        provenance[name] = {
                            "source": "left_unset",
                            "basis": _LEFT_UNSET_BASIS,
                        }
                        continue
                    fields[name] = value
                    provenance[name] = {
                        "source": "default_unspecified",
                        "basis": _FORCE_QUOTE_BASIS,
                    }

    def _refresh_feedback(self) -> None:
        """依据最近一次候选重算中文缺参清单；每轮调用一次，不缓存旧结果。"""

        if self._feedback_stopped:
            self._feedback_text = None
            self._feedback_fields = []
            return
        has, ready, fields, errors, _ = self._candidate_facts()
        if ready:
            # 已通过校验：LOOP 自然结束，正常走条数确认流程。
            self._error_streak.clear()
            self._empty_rounds = 0
            self._feedback_text = None
            self._feedback_fields = []
            return
        if not has:
            # 还没有任何候选。空回合计数由 send() 负责，这里不能清零——
            # 清零会让「连续两轮没交候选」永远到不了阈值。
            self._feedback_text = None
            self._feedback_fields = []
            return

        self._track_errors(errors)
        if self._stall_reason:
            # 熔断后不再生成清单：同一句话重复三轮，模型不会凭空变好。
            # 这里不动 _feedback_stopped——那是「用户说收尾了」的语义，
            # 混在一起会让下一轮被当成「用户补充信息」而误恢复。
            self._feedback_text = None
            self._feedback_fields = []
            return

        # 只剩非必须项缺失：不再追问，改由 Checklist 顶部标红人工核对。
        # 只认 MISSING_FIELD / CONDITIONAL——非标尺寸是「值不对」不是「没给」，
        # 模型能改成标准规格，仍然要给它一轮带可选项的追问。
        allowed, _, _ = self._force_quote_plan()
        if allowed and all(
            str(item.get("code") or "") in ("MISSING_FIELD", "CONDITIONAL")
            for item in errors
        ):
            self._feedback_text = None
            self._feedback_fields = []
            return

        # 只有需要人补充/确认的错误进中文清单；结构类错误只出现在原始
        # 错误列表里，由模型自行修正，不向用户追问。
        self._feedback_fields = fields
        lines = [
            _FEEDBACK_HEADER,
            _feedback_body(fields, errors, self._allowed_for(errors)),
            _FEEDBACK_PROTOCOL,
        ]
        self._feedback_text = "\n".join(lines)

    def _track_errors(self, errors: Sequence[Mapping[str, Any]]) -> None:
        """按 (path, code) 记连续轮次；任一项到阈值就熔断整个 LOOP。

        修好的错误必须立刻从表里删掉，否则「三条里修好两条」也会被历史
        累计数误判成卡住。同一轮内只计一次：_refresh_feedback 会在
        load_candidate 与出口重算里被多次调用，重复计数会让阈值提前触发。
        """

        if self._streak_round == self._round:
            return
        self._streak_round = self._round
        current = {
            (str(item.get("path") or ""), str(item.get("code") or ""))
            for item in errors
        }
        for key in list(self._error_streak):
            if key not in current:
                del self._error_streak[key]
        for key in current:
            self._error_streak[key] = self._error_streak.get(key, 0) + 1
        worst = max(self._error_streak.values(), default=0)
        if worst >= _STALL_ROUNDS and not self._stall_reason:
            labels = [
                _stall_label(path)
                for (path, _), count in self._error_streak.items()
                if count >= _STALL_ROUNDS
            ]
            self._stall_reason = "同一项连续 {} 轮未修复：{}".format(
                worst, "、".join(dict.fromkeys(labels)))

    def _allowed_for(
        self, errors: Sequence[Mapping[str, Any]]
    ) -> dict[str, list[str]]:
        """给模型的「可选项」：枚举查契约，非标尺寸给同类型的标准规格表。"""

        allowed = contract.allowed_values([
            str(item.get("path")) for item in errors
            if str(item.get("code") or "") == "ENUM"
        ])
        rows = (
            self._feedback_candidate.get("items")
            if isinstance(self._feedback_candidate, Mapping) else None
        )
        items = rows if isinstance(rows, list) else []
        sizes = contract._known_sizes()
        for item in errors:
            if str(item.get("code") or "") != "NONSTANDARD_SIZE":
                continue
            path = str(item.get("path") or "")
            match = re.search(r"items\[(\d+)\]", path)
            index = int(match.group(1)) if match else 0
            row = items[index] if index < len(items) and isinstance(items[index], Mapping) else {}
            options = sizes.get(str(row.get("item_type") or "")) or []
            if options:
                allowed[path] = list(options)
        return allowed

    # ---- 出口：语义归模型、事实归程序、授权归人 ------------------------------

    @property
    def force_quote_allowed(self) -> bool:
        """当前候选的缺项是否全部落在可放行白名单内。"""

        return self._force_quote_plan()[0]

    @property
    def force_quote_labels(self) -> list[str]:
        """可放行缺项的中文名，供系统消息与人工核对使用。"""

        return self._force_quote_plan()[1]

    @property
    def exit_state(self) -> str:
        """collecting / awaiting_confirm / stopped / confirmed。"""

        return self._exit_state

    @property
    def exit_notice(self) -> str | None:
        """尚未被 UI 取走的程序系统消息；只给用户看，不进模型上下文。"""

        return self._exit_notice

    def take_exit_notice(self) -> str | None:
        """UI 每轮取一次，取走后不再重复插入同一条系统消息。"""

        notice = self._exit_notice
        self._exit_notice = None
        return notice

    def _set_exit_notice(self, state: str, notice: str) -> None:
        signature = (state, notice)
        self._exit_state = state
        self._exit_notice = notice if signature != self._exit_signature else None
        self._exit_signature = signature

    def _evaluate_exit(self, user_intent: str | None, reply_intent: str) -> None:
        """三类出口收敛到「停追问 + 插系统消息 + 开放交接」，不自动报价。

        交接本身由 UI 在读到这里的状态后立即执行：``awaiting_confirm`` 表示
        候选已可交 engine（通过校验，或用户明确要求报价且只剩非必须缺项）。
        """

        if self._stall_reason:
            # 熔断优先于一切出口判定：模型三轮没改对同一项（或两轮没提交
            # 候选），再问下去只是把用户困在对话里，直接指出另一条路。
            self._feedback_text = None
            self._set_exit_notice("stopped", "程序：" + _STALL_NOTICE)
            return

        intent = reply_intent if reply_intent in _EXIT_INTENTS else user_intent
        has, ready, fields, _, count = self._candidate_facts()
        missing = "、".join(fields) if fields else "（无中文缺参项，剩余为候选结构问题）"
        force_ok, force_labels, _ = self._force_quote_plan()
        force_text = "、".join(force_labels) if force_labels else ""
        size_text = "".join(
            "非标尺寸 {} 将降级为最接近标准规格 {}（差 {:g} mm），输出后必须人工改回。".format(
                item["requested"], item["size"], item["distance_mm"]
            )
            for item in self.size_downgrades
        )
        if intent in _EXIT_INTENTS:
            self._feedback_stopped = True
            self._feedback_text = None
            self._feedback_fields = []
        if intent == REQUEST_QUOTE:
            if has and ready:
                self._set_exit_notice(
                    "awaiting_confirm",
                    "程序：已收到报价请求，当前候选通过契约校验（共 {} 条），"
                    "正在生成选型清单。".format(count),
                )
            elif force_ok:
                self._set_exit_notice(
                    "awaiting_confirm",
                    "程序：已收到报价请求。以下非必须项将按默认处理，请在选型清单中"
                    "人工核对：{}。{}正在生成选型清单。".format(force_text, size_text),
                )
            else:
                self._set_exit_notice(
                    "stopped",
                    "程序：已收到报价请求，但候选含必须项或结构类错误，不能带缺项进入选型。"
                    "仍缺：{}。请继续补充，或改用 Desk 手工录入。".format(missing),
                )
        elif intent == NO_MORE_INFO:
            if force_ok:
                self._set_exit_notice(
                    "stopped",
                    "程序：已停止追问。以下非必须项可按默认处理：{}。{}"
                    "如需按这些默认值继续，请回复「按默认处理并报价」；"
                    "补充任意信息可继续澄清。".format(force_text, size_text),
                )
            else:
                self._set_exit_notice(
                    "stopped",
                    "程序：已停止追问。仍缺：{}。补充任意信息可继续澄清；"
                    "缺项较多的需求建议改用 Desk 手工录入。".format(missing),
                )
        elif has and ready:
            # 兜底：用户没说任何收尾句，程序发现字段齐了也直接交接。
            self._set_exit_notice(
                "awaiting_confirm",
                "程序：当前候选已通过契约校验（共 {} 条），正在生成选型清单。".format(count),
            )
        else:
            self._exit_state = "collecting"
            self._exit_notice = None
            self._exit_signature = None

    def load_demo(self) -> ChatReply:
        """Run the local two-turn demonstration and stage its candidate."""

        self.send(DEMO_TEXT)
        return self.send(DEMO_CONFIRM_TEXT)

    def _temporary_candidate(self) -> dict[str, Any] | None:
        if self._candidate is None:
            return None
        temp = copy.deepcopy(self._candidate)
        quote = temp.get("quote")
        if isinstance(quote, Mapping):
            quote_copy = dict(quote)
            quote_copy["confirmed_by_user"] = True
            temp["quote"] = quote_copy
        return temp

    @staticmethod
    def _append_errors(target: list[dict[str, Any]], errors: Sequence[Mapping[str, Any]]) -> None:
        seen = {(item.get("path"), item.get("code")) for item in target}
        for item in errors:
            value = dict(item)
            key = (value.get("path"), value.get("code"))
            if key not in seen:
                target.append(value)
                seen.add(key)

    def _validate(self, payload: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if payload is None:
            errors.append(_error("$", "NO_CANDIDATE", "尚未收到结构化候选"))
            return errors, warnings
        try:
            warnings.extend(contract.validate_payload(payload))
        except contract.ContractError as exc:
            self._append_errors(errors, exc.errors)
            return errors, warnings
        try:
            entries = contract.payload_to_entries(payload)
            for entry in entries:
                contract.build_engine_input(entry, strict=True)
        except contract.ContractError as exc:
            self._append_errors(errors, exc.errors)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(_error("$", "TRANSLATION", str(exc)))
        return errors, warnings

    def preview(self) -> dict[str, Any]:
        """Validate a temporary confirmed copy without mutating the candidate."""

        temp = self._temporary_candidate()
        errors, warnings = self._validate(temp)
        count = 0
        if isinstance(temp, Mapping) and isinstance(temp.get("items"), list):
            count = len(temp["items"])
        if temp is None:
            summary = "暂无候选"
        elif errors:
            summary = "候选待修正：{} 个问题，{} 条。".format(len(errors), count)
        else:
            project = ((temp.get("quote") or {}).get("project") if isinstance(temp.get("quote"), Mapping) else "")
            summary = "候选{}，共 {} 条，等待用户确认。".format(project or "已就绪", count)
        return {
            "summary": summary,
            "errors": copy.deepcopy(errors),
            "warnings": copy.deepcopy(warnings),
            "count": count,
            "ready": bool(temp is not None and not errors),
            # 熔断原因给界面与归档看：说明这一轮为什么停止追问。
            "stalled": bool(self._stall_reason),
            "stall_reason": self._stall_reason,
        }

    def confirm(self, actual_count: int, force_quote: bool = False) -> dict[str, Any]:
        """Confirm a candidate after explicit user count verification.

        ``force_quote=True`` is only valid when every remaining issue is a
        tolerated optional field.  Neutral defaults are applied *here*, at the
        moment the human clicks confirm, and recorded in provenance so the
        Checklist reviewer can tell they were never stated by the user.
        """

        if isinstance(actual_count, bool) or not isinstance(actual_count, int):
            raise ValueError("实际条数必须是整数")
        if self._candidate is None:
            raise ValueError("没有可确认的候选")
        items = self._candidate.get("items")
        count = len(items) if isinstance(items, list) else 0
        if actual_count != count:
            raise ValueError("COUNT_MISMATCH: 用户确认条数 {} 与候选条数 {} 不一致".format(actual_count, count))
        preview = self.preview()
        if not preview["ready"]:
            allowed, _, touched = self._force_quote_plan()
            if not force_quote or not allowed:
                raise contract.ContractError(preview["errors"])
            self._apply_force_quote_defaults(touched)
            preview = self.preview()
            if not preview["ready"]:
                raise contract.ContractError(preview["errors"])
        confirmed = copy.deepcopy(self._candidate)
        quote = confirmed.get("quote")
        if not isinstance(quote, Mapping):
            raise contract.ContractError(_error("quote", "MISSING_FIELD", "缺少 quote 对象"))
        quote_copy = dict(quote)
        quote_copy["confirmed_by_user"] = True
        confirmed["quote"] = quote_copy
        # Run the shared validators again on the exact object handed off.
        errors, _ = self._validate(confirmed)
        if errors:
            raise contract.ContractError(errors)
        self._candidate = copy.deepcopy(confirmed)
        self._feedback_text = None
        self._feedback_fields = []
        self._exit_state = "confirmed"
        self._exit_notice = None
        self._exit_signature = None
        return copy.deepcopy(confirmed)

    def reset(self) -> None:
        """Clear conversation turns and staged candidate, retaining system prompt."""

        self._draft = ""
        self._candidate = None
        self._feedback_candidate = None
        self._feedback_text = None
        self._feedback_fields = []
        self._feedback_stopped = False
        self._error_streak.clear()
        self._streak_round = -1
        self._empty_rounds = 0
        self._stall_reason = None
        self._ex_state = None
        self._ex_active = False
        self._ex_asked = False
        self._exit_state = "collecting"
        self._exit_notice = None
        self._exit_signature = None
        self.source_text = ""
        self.events = []
        self._last_error = None
        self._round = 0
        self._start_context()
        provider_reset = getattr(self.provider, "reset", None)
        if callable(provider_reset):
            provider_reset()


__all__ = [
    "ApiDisabledError",
    "ApiError",
    "CONTINUE",
    "ChatReply",
    "ChatSession",
    "ChatSettings",
    "DEFAULT_PROVIDERS_PATH",
    "DEMO_CASE_ATTACHMENT",
    "DEMO_CASE_TURNS",
    "DEMO_CONFIRM_TEXT",
    "DEMO_TEXT",
    "DemoProvider",
    "DisabledApiProvider",
    "NO_MORE_INFO",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderConfigError",
    "REQUEST_QUOTE",
    "ScriptedProvider",
    "demo_case_payload",
    "demo_case_turns",
    "demo_payload",
    "demo_text",
    "error_code",
    "load_provider_config",
    "normalize_program_defaults",
]
