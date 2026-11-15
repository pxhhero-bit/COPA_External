"""问题码规则表：config/audit_rules.json 的读取与 Issue 构造.

检查器只写「哪个码 + 证据」，标题/级别/建议话术统一在这里补，避免同一句话在
六七个检查器里各写一遍（也就不会各写一个版本）。
"""
import json
import os
from typing import Dict, Optional

from COPA.apps.audit.model import Issue, LEVEL_YELLOW, SPAN_DESC

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PATH = os.path.join(_ROOT, "config", "audit_rules.json")

_FALLBACK = {"title": "未定义问题码", "level": LEVEL_YELLOW, "advice": ""}


class Rules:
    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_PATH
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.version = str(data.get("version", "1.0"))
        self._rules: Dict[str, dict] = data.get("rules") or {}
        # 描述一致性引擎：diff=快照比对（新）/ rules=逐条规则（旧）
        # 环境变量可临时切换，便于同一份单据两种口径对跑
        self.desc_engine = (os.environ.get("COPA_DESC_ENGINE")
                            or str(data.get("desc_engine", "diff"))).strip().lower()

    def meta(self, code: str) -> dict:
        return self._rules.get(code, _FALLBACK)

    def codes(self):
        """全部问题码（按配置顺序）。审核视图与测试都用它枚举。"""
        return list(self._rules)

    def raw(self, code: str) -> dict:
        """原始条目（含 advice），审核表格用"""
        return self._rules.get(code, {})

    def level(self, code: str) -> str:
        return self.meta(code).get("level", LEVEL_YELLOW)

    def title(self, code: str) -> str:
        return self.meta(code).get("title", code)

    def advice(self, code: str) -> str:
        return self.meta(code).get("advice", "")

    def issue(self, code: str, message: str = "", expected: str = "",
              actual: str = "", missing: str = "", anchor=None,
              mark: str = "", level: str = "", sheet: str = "",
              span=None, field: str = "", span_scope: str = SPAN_DESC) -> Issue:
        """按码构造一条问题；级别与建议自动从规则表带出。
        mark 覆盖规则表默认值（None 时不带标注提示）；
        level 覆盖规则表级别（缺项类按「型号蕴含项」与「说明性项」分别定级）；
        sheet 给文件级问题定位工作表（行号跨表会重，不能靠猜）；
        span=(起, 止) 是字符区间——有它才做字符级标红，没有就只能整格标或者
        按标签反查（见 annotate._issue_ranges 的老路）；
        span_scope 指明这个区间相对谁：SPAN_DESC（默认，item.desc）还是
        SPAN_CELL（锚点格本身，抬头这类跨格拼接用）"""
        meta = self.meta(code)
        return Issue(code=code, level=level or meta.get("level", LEVEL_YELLOW),
                     title=meta.get("title", code), message=message,
                     advice=meta.get("advice", ""), expected=expected,
                     actual=actual, missing=missing, anchor=anchor,
                     mark=mark or meta.get("mark", ""), sheet=sheet,
                     span=span, field=field, span_scope=span_scope)


_RULES: Optional[Rules] = None


def get_rules() -> Rules:
    global _RULES
    if _RULES is None:
        _RULES = Rules()
    return _RULES
