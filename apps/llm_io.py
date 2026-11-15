"""Runtime-free input handling for LLM quote payloads.

The LLM integration deliberately stops at a JSON object.  This module only
normalises the few wrappers that are common when a model response is copied
from a chat window; it does not infer missing fields or repair prose.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .contract import ContractError


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*", re.MULTILINE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _contract_error(message: str, *, raw: str = "") -> ContractError:
    """Construct the shared field/code/message error."""
    detail = message
    if raw:
        detail = "{}；原文前200字符：{}".format(message, raw[:200])
    error = {"path": "$", "code": "PARSE_ERROR", "message": detail}
    return ContractError([error])


def _read_source(path_or_text: Any) -> str:
    """Read a path when it names a file, otherwise treat it as raw text."""
    if isinstance(path_or_text, os.PathLike):
        path = os.fspath(path_or_text)
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                return handle.read()
        except OSError as exc:
            raise _contract_error("无法读取输入文件：{}".format(exc)) from exc

    if not isinstance(path_or_text, str):
        raise _contract_error("输入必须是 JSON 文本或文件路径")

    # A string containing a real existing path is unambiguously a file.  A
    # missing path is left as text so callers can pass a pasted raw response.
    try:
        if os.path.isfile(path_or_text):
            with open(path_or_text, "r", encoding="utf-8-sig") as handle:
                return handle.read()
    except OSError as exc:
        raise _contract_error("无法读取输入文件：{}".format(exc)) from exc
    return path_or_text


def _clean_text(text: str) -> str:
    """Remove transport wrappers while preserving the response body exactly."""
    # ``utf-8-sig`` handles a file BOM; this also covers a pasted BOM.
    text = (text or "").lstrip("\ufeff").replace("\u00a0", " ")
    # Strip one leading fence and one trailing fence.  Explanatory text and
    # multiple JSON blocks are handled by the per-brace decode below.
    text = _FENCE_RE.sub("", text, count=1)
    return re.sub(r"\s*```\s*$", "", text)


def _decode(text: str) -> Any:
    """Return the first decodable JSON object in the text.

    Models sometimes wrap JSON in prose, emit several fenced blocks, or leave
    trailing commas.  Slicing from the first ``{`` to the last ``}`` corrupts
    all of those cases, so try each opening brace with ``raw_decode`` instead.
    """
    decoder = json.JSONDecoder()
    first_error: Exception | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        chunk = text[index:]
        for candidate in (chunk, _TRAILING_COMMA_RE.sub(r"\1", chunk)):
            try:
                value, _ = decoder.raw_decode(candidate)
            except (TypeError, ValueError) as exc:
                if first_error is None:
                    first_error = exc
                continue
            if isinstance(value, dict):
                return value
    if first_error is None:
        raise _contract_error("未找到 JSON 对象", raw=text)
    raise _contract_error("JSON 解析失败：{}".format(first_error), raw=text)


def load_payload(path_or_text: Any) -> dict:
    """Load a quote payload from ``.json``/``.txt`` or pasted raw text.

    The returned value is a JSON object.  No schema or business validation is
    performed here; callers should pass it to ``apps.contract.validate_payload``
    next.
    """
    raw = _read_source(path_or_text)
    candidate = _clean_text(raw)
    payload = _decode(candidate)

    if not isinstance(payload, dict):
        raise _contract_error("JSON 顶层必须是对象", raw=candidate)
    return payload


__all__ = ["ContractError", "load_payload"]
