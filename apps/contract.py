"""Headless JSON contract and translation boundary for COPA.

The GUI and the LLM/CLI path intentionally share this module.  The functions
here only translate already-confirmed structured values and perform
deterministic structural checks; selection remains in :mod:`COPA.engine`.
There is no Qt import in this module.
"""

from __future__ import annotations

import copy
import csv
import json
import re
import sys
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeGuard

from COPA.engine import engine
from COPA.apps.Parser import Parser, size_to_mm


_ROOT_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
             else Path(__file__).resolve().parents[1])
_CONFIG_DIR = _ROOT_DIR / "config"
_DATA_DIR = _ROOT_DIR / "data"
_PARSER_RULES_PATH = _CONFIG_DIR / "parser_rules.json"
_SELECTION_RULES_PATH = _CONFIG_DIR / "selection_rules.json"


class ContractError(Exception):
    """Aggregated payload/translation errors.

    ``errors`` is deliberately a small JSON-friendly list.  Each item has a
    field ``path``, machine-readable ``code`` and human-readable ``message``.
    """

    def __init__(self, errors: Sequence[Mapping[str, Any]] | Mapping[str, Any] | str):
        if isinstance(errors, str):
            errors = [{"path": "$", "code": "CONTRACT", "message": errors}]
        elif isinstance(errors, Mapping):
            errors = [errors]
        self.errors = [dict(item) for item in errors]
        message = "; ".join(
            "{} {}: {}".format(
                item.get("path", "$"), item.get("code", "CONTRACT"),
                item.get("message", ""),
            )
            for item in self.errors
        )
        super().__init__(message or "契约校验失败")


def _err(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _warning(path: str, code: str, message: str) -> dict[str, str]:
    return _err(path, code, message)


def _load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return default


def _parser_rules() -> dict[str, Any]:
    return _load_json(_PARSER_RULES_PATH, {})


def _selection_rules() -> dict[str, Any]:
    # Keep this coupled to the already-loaded engine resolver where possible;
    # it is the source of truth used by selection itself.
    rules = getattr(getattr(engine, "resolver", None), "rules", None)
    if isinstance(rules, Mapping):
        return {str(key): value for key, value in rules.items()}
    return _load_json(_SELECTION_RULES_PATH, {})


def _supported_item_types() -> dict[str, str]:
    mapping = dict((_selection_rules().get("item_types") or {}))
    return {
        name: code for name, code in mapping.items()
        if code in {"module", "bench", "platform"}
    }


def _materials() -> list[str]:
    parameters = _parser_rules().get("parameters") or {}
    values = ((parameters.get("material") or {}).get("values") or {})
    result = []
    for value in values.values():
        if value not in result:
            result.append(value)
    if not result:
        result = ["碳钢", "不锈钢", "混合"]
    return result


def _brands() -> dict[str, list[str]]:
    brands = _selection_rules().get("brands") or {}
    sensors = list((brands.get("sensor_db") or {}).keys())
    controllers = list((brands.get("controller_db") or {}).keys())
    available = list(brands.get("available_brands") or [])
    if not sensors:
        sensors = [x for x in available if x in {"FT", "AW"}]
    if not controllers:
        controllers = available
    return {"m_brand": sensors, "c_brand": controllers}


def _parameter_options(name: str, fallback: Sequence[str] = ()) -> list[str]:
    parameter = ((_parser_rules().get("parameters") or {}).get(name) or {})
    values = parameter.get("options") or []
    return list(values) if values else list(fallback)


def _protocols() -> list[str]:
    result = []
    for item in _parser_rules().get("protocols") or []:
        value = item.get("canonical")
        if value and value not in result:
            result.append(value)
    return result


def _protocol_categories() -> dict[str, list[str]]:
    result = {"basic": [], "extended": []}
    for item in _parser_rules().get("protocols") or []:
        canonical = item.get("canonical")
        category = item.get("category")
        if canonical and category in result and canonical not in result[category]:
            result[category].append(canonical)
    return result


def _split_protocols(value: Any) -> list[str]:
    """Accept a scalar protocol or a compact ``RS232+RS485`` spelling."""
    if isinstance(value, str):
        parts = re.split(r"\s*(?:\+|,|、|/|&)\s*", value.strip())
        return [part for part in parts if part]
    if isinstance(value, (list, tuple)):
        result = []
        for part in value:
            result.extend(_split_protocols(part))
        return result
    return []


def _normalize_com_fields(fields: dict[str, Any]) -> None:
    """Translate JSON protocol names to the engine's communication codes."""
    basic = _split_protocols(fields.get("req_com1")) if "req_com1" in fields else []
    extended = _split_protocols(fields.get("req_com2")) if "req_com2" in fields else []
    if basic:
        # The parser's public derivation is the single source of truth for
        # basic serial/Modbus combinations and their engine coverage codes.
        modbus_count = 1
        if "Modbus" in basic:
            try:
                modbus_count = max(1, int(fields.get("special_req") or 1))
            except (TypeError, ValueError):
                modbus_count = 1
        fields["req_com1"] = Parser().derive_req_com1(basic, modbus_count)
    elif "req_com1" in fields and fields.get("req_com1") in ("", None):
        fields["req_com1"] = []
    if extended:
        fields["req_com2"] = extended
    elif "req_com2" in fields and fields.get("req_com2") in ("", None):
        fields["req_com2"] = []


def _required_ex_levels() -> list[str]:
    mapping = ((_selection_rules().get("controller_selection") or {})
               .get("ex_mapping") or {})
    return [str(key) for key in mapping if str(key) != "0"]


def _csv_rows(filename: str) -> list[dict[str, str]]:
    path = _DATA_DIR / filename
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except (OSError, csv.Error):
        return []


def _known_sizes() -> dict[str, list[str]]:
    """Return normalized table sizes from the actual product tables."""
    result: dict[str, list[str]] = {"平台秤": [], "台秤": []}
    for item_type, filename in (("平台秤", "平台秤通表.csv"),
                                ("台秤", "台秤通表.csv")):
        for row in _csv_rows(filename):
            raw = (row.get("台面尺寸") or "").strip()
            normalized = size_to_mm(raw)
            if normalized and normalized not in result[item_type]:
                result[item_type].append(normalized)
    for values in result.values():
        values.sort(key=lambda value: tuple(
            int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", value)
        ))
    return result


def _source_fingerprint() -> str:
    """Content marker for the rules and product tables behind the contract.

    Reads the source bytes so the marker is independent of copy time/mtime and
    changes whenever a table or rule changes.  An mtime marker drifted on every
    checkout and made archived payloads fail the fingerprint comparison for no
    business reason.
    """
    crc = 0
    for path in _source_paths(_selection_rules()):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        crc = zlib.crc32(path.name.encode("utf-8"), crc)
        crc = zlib.crc32(data, crc)
    return "{:08x}".format(crc & 0xFFFFFFFF)


def _source_paths(rules: Mapping[str, Any] | None = None) -> list[Path]:
    rules = rules if isinstance(rules, Mapping) else _selection_rules()
    brands = rules.get("brands") or {}
    paths = [_SELECTION_RULES_PATH, _PARSER_RULES_PATH]
    paths.extend([
        _DATA_DIR / str(brands.get("module_db") or ""),
        _DATA_DIR / "平台秤通表.csv",
        _DATA_DIR / "台秤通表.csv",
    ])
    paths.extend(
        _DATA_DIR / str(filename)
        for filename in (brands.get("sensor_db") or {}).values()
    )
    paths.extend(
        _DATA_DIR / str(filename)
        for filename in (brands.get("controller_db") or {}).values()
    )
    return paths


def _ensure_sources() -> None:
    missing = [str(path) for path in _source_paths() if not path.is_file()]
    if missing:
        raise ContractError([
            _err(path, "ENVIRONMENT", "契约所需规则或通表文件不存在")
            for path in missing
        ])


def _schema() -> dict[str, Any]:
    _ensure_sources()
    item_types = _supported_item_types()
    brands = _brands()
    sizes = _known_sizes()
    schema = {
        "schema_version": 1,
        "item_types": item_types,
        "quote_titles": _quote_titles(),
        "quote_title_by_m_brand": dict(QUOTE_TITLE_BY_M_BRAND),
        "materials": _materials(),
        "brands": brands,
        "required_ex": _required_ex_levels(),
        "sizes": sizes,
        "options": {
            "安装形式": _parameter_options("安装形式", ("一体", "分体")),
            "分体仪表支架": _parameter_options(
                "分体仪表支架", ("壁挂支架", "立杆支架", "壁挂", "立杆")
            ),
            "install": _parameter_options("install"),
            "power": _parameter_options("power", ("AC220V", "DC24V")),
            "protocols": _protocols(),
            "protocols_basic": _protocol_categories()["basic"],
            "protocols_extended": _protocol_categories()["extended"],
        },
        "fields": {
            "common_required": ["W1", "material"],
            "称重模块": ["W1", "W2", "support", "material", "vibration"],
            "平台秤": ["W1", "material", "台面尺寸"],
            "台秤": ["W1", "material", "台面尺寸", "安装形式"],
        },
        "field_semantics": copy.deepcopy(_FIELD_SEMANTICS),
        "sources": {
            "selection_rules": "config/selection_rules.json",
            "parser_rules": "config/parser_rules.json",
            "table_sizes": ["平台秤通表.csv", "台秤通表.csv"],
        },
    }
    schema["schema_fingerprint"] = _source_fingerprint()
    schema["payload_contract"] = _payload_contract(schema)
    return schema


def _quote_titles() -> list[str]:
    names = []
    template_dir = _ROOT_DIR / "template"
    try:
        files = template_dir.iterdir()
    except OSError:
        files = ()
    for path in files:
        for title in ("COPA B", "COPA A"):
            if title in path.name and title not in names:
                names.append(title)
    return names or ["COPA B", "COPA A"]


# 报价抬头只跟秤体/传感器品牌走，与仪表品牌无关：同一份报价里 c_brand 写
# 什么都不会改变抬头。抬头因此不再由模型输出，由程序按 m_brand 写死。
QUOTE_TITLE_BY_M_BRAND = {"FT": "COPA B", "AW": "COPA A"}


def quote_title_for(m_brand: Any, fallback: Any = None) -> Any:
    """Return the fixed quote header for a brand.

    未知品牌（例如只在仪表库里出现的 FAB）不猜抬头，沿用 ``fallback``；
    调用方拿不到就保持缺失，由 Checklist 的人工下拉决定。
    """

    key = str(m_brand or "").strip()
    title = QUOTE_TITLE_BY_M_BRAND.get(key.upper())
    if title:
        return title
    if isinstance(fallback, str) and fallback.strip() in _quote_titles():
        return fallback.strip()
    return None


# COPA 契约字段的语义说明。只描述字段含义、单位与合法取值，不列举原文别名或
# 固定映射：模糊转换交给模型，结果是否正确交给契约校验。这里同时用于给
# JSON Schema 的字段补 description，保证规则文本与运行时契约只有一份口径。
_FIELD_SEMANTICS: dict[str, Any] = {
    "note": (
        "COPA 契约字段的语义说明，只描述字段含义、单位与合法取值，不列举原文别名。"
        "原文说法与契约字段/枚举的对应关系由模型按语义自行推断；契约没列出的说法"
        "同样推断后交由 COPA 校验，校验不通过时保持缺失，不得因为没见过某种说法"
        "就拒绝映射。非契约列一律忽略。"
    ),
    "fields": {
        "item_type": {"hint": "设备类型枚举：称重模块 / 台秤 / 平台秤。"},
        "quantity": {"hint": "该条设备的数量，正整数。"},
        "W1": {"unit": "kg", "hint": "最大物料重量，kg 数值。"},
        "W2": {"unit": "kg", "hint": "设备自重，kg 数值，可为 0；仅称重模块需要。"},
        "台面尺寸": {"hint": "长x宽，单位 mm；米/厘米换算成 mm。"},
        "material": {"hint": "整机材质：碳钢 / 不锈钢 / 混合。"},
        "m_brand": {"hint": "整单共用的秤体/传感器品牌短码，写在 quote，不在条目里。"},
        "c_brand": {"hint": "整单共用的仪表/控制器品牌短码，写在 quote，不在条目里。"},
        "安装形式": {"hint": "台秤安装形式：一体 / 分体。"},
        "分体仪表支架": {"hint": "分体时的仪表支架枚举，按原文语义自行选择合法取值。"},
        "required_ex": {"hint": "防爆等级枚举；原文只给『防爆』而未给具体等级时属于缺项。"},
        "power": {"hint": "仪表电源，可选字段。"},
    },
    "non_contract_columns": [
        "序号", "传感器材质", "传感器等级/Y值", "传感器数量", "精度等级", "分度值(e)",
        "传感器接头", "通讯接口", "仪表是否需要I/O控制", "立柱", "防护等级",
        "仪表与接线盒距离(m)", "其他要求", "单位",
    ],
    "optional_columns": ["仪表安装方式", "仪表电源", "仪表是否防爆"],
    "ignored_note": (
        "non_contract_columns 只是常见示例，不是穷举：凡不属于 COPA 契约字段的原文列"
        "一律忽略，不追问、不请求确认、不填入 payload、也不当成缺失字段。"
        "optional_columns 对应可选字段：原文有明确值可按需填入，缺值不追问。"
    ),
}


def _describe(properties: dict[str, Any]) -> dict[str, Any]:
    """给 JSON Schema 字段补中文语义说明，避免模型把表头列名当契约字段。"""

    for name, meta in _FIELD_SEMANTICS["fields"].items():
        hint = meta.get("hint") if isinstance(meta, Mapping) else None
        prop = properties.get(name)
        if hint and isinstance(prop, dict):
            updated = dict(prop)
            updated["description"] = hint
            properties[name] = updated
    return properties


def _field_contract(
    item_types: Mapping[str, str],
    materials: Sequence[str],
    levels: Sequence[str],
    options: Mapping[str, Sequence[str]],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Build JSON-schema field definitions from the live rule data.

    三种产品线的字段集合完全相同，只有必填清单不同，所以只返回一份共享
    定义 + 各产品线的必填清单；``$defs`` 里不再存三份重复的字段表。
    ``m_brand`` / ``c_brand`` 已提到 quote 级，不在这里。
    """
    def enum_property(values: Sequence[str], value_type: str = "string") -> dict[str, Any]:
        prop: dict[str, Any] = {"type": value_type}
        if values:
            prop["enum"] = list(values)
        return prop

    weight = {
        "oneOf": [
            {"type": "number"},
            {
                "type": "string",
                "pattern": r"^\s*\d+(?:\.\d+)?\s*(?:kg|千克|公斤|g|克|t|吨)?\s*$",
            },
        ],
    }
    w1_number = {"type": "number", "exclusiveMinimum": 0}
    w2_number = {"type": "number", "minimum": 0}
    protocol_basic = list(options.get("protocols_basic", options.get("protocols", ())))
    protocol_extended = list(options.get("protocols_extended", options.get("protocols", ())))

    def protocol_scalars(values: Sequence[str]) -> list[str]:
        result = list(values)
        for index, left in enumerate(values):
            for right in values[index + 1:]:
                result.append("{}+{}".format(left, right))
        return result

    fields_common: dict[str, Any] = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "W1": w1_number,
            "W2": w2_number,
            "support": {"type": "integer", "minimum": 3},
            "material": enum_property(materials),
            "vibration": {"type": "boolean"},
            "RPM": {"type": "integer", "minimum": 0},
            "台面尺寸": {
                "type": "string",
                "pattern": r"^\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)?\s*[xX×*]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)?\s*$",
            },
            "required_ex": {
                "oneOf": [
                    enum_property(levels),
                    {"const": False},
                    {"type": "null"},
                ],
            },
            "安装形式": enum_property(options.get("安装形式", ())),
            "分体仪表支架": {
                "oneOf": [
                    enum_property(options.get("分体仪表支架", ())),
                    {"const": False},
                    {"type": "null"},
                ],
            },
            "power": enum_property(options.get("power", ())),
            "e_input": dict(weight),
            "c_family": {"type": "string"},
            "req_com1": {
                "oneOf": [
                    {"type": "array", "items": enum_property(protocol_basic)},
                    enum_property(protocol_scalars(protocol_basic)),
                ],
            },
            "req_com2": {
                "oneOf": [
                    {"type": "array", "items": enum_property(protocol_extended)},
                    enum_property(protocol_extended),
                ],
            },
            "special_req": {"type": "integer", "minimum": 1},
            "special_req2": {"type": "boolean"},
        },
    }
    fields_common["properties"] = _describe(dict(fields_common["properties"]))
    required_by_type = {
        "称重模块": ["W1", "W2", "support", "material", "vibration"],
        "平台秤": ["W1", "material", "台面尺寸"],
        "台秤": ["W1", "material", "台面尺寸", "安装形式"],
    }
    required_by_type = {
        name: names for name, names in required_by_type.items()
        if name in item_types
    }
    return fields_common, required_by_type


def _payload_contract(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete machine-readable quote payload contract."""
    fields_common, required_by_type = _field_contract(
        schema["item_types"], schema["materials"],
        schema["required_ex"], schema["options"],
    )
    brands = schema["brands"]
    flags_required = [
        "metrology", "high_precision", "ex", "digital", "onsite_service"
    ]
    item_properties = {
        "seq": {"type": "integer", "minimum": 1},
        "item_type": {"type": "string", "enum": list(schema["item_types"])},
        "quantity": {"type": "integer", "minimum": 1},
        "flags": {
            "type": "object", "additionalProperties": True,
            "required": flags_required,
            "properties": {name: {"type": "boolean"} for name in flags_required},
        },
        "fields": {"$ref": "#/$defs/fields"},
        "note": {"type": "string"},
        "provenance": {
            "type": "object",
            "additionalProperties": {
                "type": "object", "additionalProperties": True,
                "properties": {
                    "source": {"type": "string"},
                    "basis": {"type": "string"},
                },
            },
        },
        "confirmed_nonstandard": {"type": "boolean"},
    }
    item_properties = _describe(item_properties)
    item_schema: dict[str, Any] = {
        "type": "object", "additionalProperties": True,
        "required": ["seq", "item_type", "quantity", "flags", "fields"],
        "properties": item_properties,
        "allOf": [
            {
                "if": {
                    "required": ["flags"],
                    "properties": {
                        "flags": {
                            "required": ["ex"],
                            "properties": {"ex": {"const": True}},
                        }
                    },
                },
                "then": {"properties": {"fields": {"required": ["required_ex"]}}},
            },
            {
                "if": {
                    "required": ["fields"],
                    "properties": {
                        "fields": {
                            "required": ["vibration"],
                            "properties": {"vibration": {"const": True}},
                        }
                    },
                },
                "then": {"properties": {"fields": {"required": ["RPM"]}}},
            },
        ],
    }
    # 各产品线的必填清单直接写在条件分支里，不再复制三份字段表。
    for display_name, names in required_by_type.items():
        item_schema["allOf"].append({
            "if": {
                "required": ["item_type"],
                "properties": {"item_type": {"const": display_name}},
            },
            "then": {"properties": {"fields": {"required": list(names)}}},
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "COPA LLM quote payload",
        "description": (
            "LLM 只翻译已确认需求；unknown fields 由 COPA 警告并忽略，"
            "不参与选型。"
        ),
        "type": "object", "additionalProperties": True,
        "required": ["schema_version", "origin", "schema_fingerprint", "quote", "items"],
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "origin": {"type": "string", "const": "llm"},
            "schema_fingerprint": {"type": "string"},
            "quote": {
                "type": "object", "additionalProperties": True,
                "required": [
                    "project", "m_brand", "c_brand", "declared_count",
                    "confirmed_by_user",
                ],
                "properties": {
                    "project": {"type": "string", "minLength": 1},
                    "m_brand": {
                        "type": "string", "enum": list(brands["m_brand"]),
                        "description": "整份报价共用的秤体/传感器品牌短码。",
                    },
                    "c_brand": {
                        "type": "string", "enum": list(brands["c_brand"]),
                        "description": "整份报价共用的仪表/控制器品牌短码。",
                    },
                    "quote_title": {
                        "type": "string", "enum": list(schema["quote_titles"]),
                        "description": "由程序按 m_brand 写死，不需要模型输出。",
                    },
                    "source": {"type": "string"},
                    "declared_count": {"type": "integer", "minimum": 0},
                    "confirmed_by_user": {"const": True},
                },
            },
            "items": {"type": "array", "items": {"$ref": "#/$defs/item"}},
        },
        "$defs": {"fields": fields_common, "item": item_schema},
    }


def print_schema() -> dict[str, Any]:
    """Build and return the current schema; callers decide how to print it."""
    return _schema()


# 提示词里的 schema 只是「给模型看的说明书」，校验仍用 _schema() 本体，因此
# 可以放心压缩：fingerprint 不参与，契约语义也不变。
#
# 三处纯开销：
# 1. json.dumps(indent=2) 让 2.5 万字符里有 1.4 万是缩进换行；
# 2. $schema / title / additionalProperties 只对 JSON Schema 校验器有意义；
# 3. description 与 field_semantics.fields[*].hint 是同一句话写了两遍。
_PROMPT_DECORATION_KEYS = ("$schema", "title", "additionalProperties")
# 这六个顶层键与 $defs 中各字段的 enum 完全重复；sizes 例外——它是标准尺寸
# 速查表，$defs 里只有格式 pattern，没有清单，删了模型就不知道有哪些标准规格。
_PROMPT_DUPLICATE_KEYS = (
    "item_types",
    "quote_titles",
    "quote_title_by_m_brand",
    "materials",
    "brands",
    "required_ex",
    "options",
)
# 这三个顶层键是给人和程序看的开发者元数据，对模型没有任何作用：
# sources 是规则文件路径，schema_version / schema_fingerprint 是版本标记，
# 而 fingerprint 本来就由程序写入、又已经在提示词里明说"不要输出"。
# 它们留在提示词里只会占位置，还可能诱导模型把 fingerprint 抄进 payload。
_PROMPT_DEV_ONLY_KEYS = ("sources", "schema_version", "schema_fingerprint")


def _prompt_schema() -> dict[str, Any]:
    """Return a compacted copy of the schema used only inside the prompt."""

    schema = copy.deepcopy(_schema())
    for key in (*_PROMPT_DUPLICATE_KEYS, *_PROMPT_DEV_ONLY_KEYS):
        schema.pop(key, None)

    _drop_program_filled_fields(schema)
    _drop_flag_fields(schema)

    semantics = schema.get("field_semantics")
    hints: set[str] = set()
    if isinstance(semantics, dict):
        for item in (semantics.get("fields") or {}).values():
            if isinstance(item, dict) and item.get("hint"):
                hints.add(str(item["hint"]).strip())

    def compact(node: Any) -> None:
        if isinstance(node, dict):
            for key in _PROMPT_DECORATION_KEYS:
                node.pop(key, None)
            description = node.get("description")
            if isinstance(description, str) and description.strip() in hints:
                node.pop("description")
            for value in node.values():
                compact(value)
        elif isinstance(node, list):
            for value in node:
                compact(value)

    compact(schema)
    return schema


# 这四个字段的取值完全由程序决定，模型写什么都一样：schema_version 恒为 1，
# origin 恒为 llm，schema_fingerprint 由规则/通表算出来，confirmed_by_user 由
# 人工确认按钮置位（模型写 true 也会被程序压回 false）。让模型输出它们只是
# 白送四类 MISSING_FIELD / SCHEMA_FINGERPRINT 错误，还会占掉每一轮的输出。
PROGRAM_FILLED_TOP_FIELDS = ("schema_version", "origin", "schema_fingerprint")
# quote_title 由 m_brand 推出、confirmed_by_user 由人工按钮置位，两者都不问模型。
PROGRAM_FILLED_QUOTE_FIELDS = ("confirmed_by_user", "quote_title")
# 这两项是「可推导」而不是「不可知」：seq 是条目位置，declared_count 是条目
# 条数。提示词里保留字段定义（多条时仍要模型点名是哪一条、用户报了条数时
# 仍要模型写下来），但不再列为必填，缺省由程序补。
PROGRAM_DERIVED_ITEM_FIELDS = ("seq",)
PROGRAM_DERIVED_QUOTE_FIELDS = ("declared_count",)


def _drop_program_filled_fields(schema: dict[str, Any]) -> None:
    """Strip program-filled fields from the prompt copy of the contract.

    两类处理不一样：``PROGRAM_FILLED_*`` 是模型不该知道的，连定义一起删；
    ``PROGRAM_DERIVED_*`` 是模型偶尔要用的，定义留着、只从 required 里摘掉
    ——模型省略不会变成 MISSING_FIELD，写了也仍然照写。
    """

    payload = schema.get("payload_contract")
    if not isinstance(payload, dict):
        return
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        return
    for key in PROGRAM_FILLED_TOP_FIELDS:
        properties.pop(key, None)
    required = payload.get("required")
    if isinstance(required, list):
        payload["required"] = [
            key for key in required if key not in PROGRAM_FILLED_TOP_FIELDS
        ]

    quote = properties.get("quote")
    if isinstance(quote, dict):
        quote_props = quote.get("properties")
        if isinstance(quote_props, dict):
            for key in PROGRAM_FILLED_QUOTE_FIELDS:
                quote_props.pop(key, None)
        quote_required = quote.get("required")
        if isinstance(quote_required, list):
            quote["required"] = [
                key for key in quote_required
                if key not in PROGRAM_FILLED_QUOTE_FIELDS
                and key not in PROGRAM_DERIVED_QUOTE_FIELDS
            ]

    definitions = payload.get("$defs")
    item = definitions.get("item") if isinstance(definitions, dict) else None
    if isinstance(item, dict):
        item_required = item.get("required")
        if isinstance(item_required, list):
            item["required"] = [
                key for key in item_required
                if key not in PROGRAM_DERIVED_ITEM_FIELDS
            ]


# 附加要求（flags）由程序负责，模型连字段定义都看不到。四项弱信号是
# 「用户没提就当 false」；防爆由程序按关键词判定，未表态时强制追问。
PROGRAM_FILLED_FLAG_FIELDS = (
    "metrology", "high_precision", "digital", "onsite_service",
)


def _drop_flag_fields(schema: dict[str, Any]) -> None:
    """Remove the flag contract from the prompt copy only.

    ``_schema()`` / ``validate_payload()`` / ``payload_to_entries()`` 保持原样：
    出口 payload 仍然必须带齐 5 个布尔，只是不再由模型写。``item.allOf``
    里的 ex→required_ex 条件分支在提示词里已无意义（模型看不到 flags），
    其余按类型必填分支保留。
    """

    payload = schema.get("payload_contract")
    definitions = payload.get("$defs") if isinstance(payload, dict) else None
    item = definitions.get("item") if isinstance(definitions, dict) else None
    if not isinstance(item, dict):
        return
    properties = item.get("properties")
    if isinstance(properties, dict):
        properties.pop("flags", None)
    required = item.get("required")
    if isinstance(required, list):
        item["required"] = [key for key in required if key != "flags"]
    branches = item.get("allOf")
    if isinstance(branches, list):
        item["allOf"] = [
            branch for branch in branches
            if not (
                isinstance(branch, dict)
                and isinstance(branch.get("if"), dict)
                and "flags" in (branch["if"].get("required") or [])
            )
        ]


def apply_program_flags(
    payload: Mapping[str, Any], ex_value: bool | None
) -> dict[str, Any]:
    """Fill the five attachment flags the model no longer submits.

    ``ex_value`` 是程序按防爆关键词判定的结果；``None`` 表示用户尚未表态
    （此时门禁会拦住自动交接）。四项弱信号与未判定的 ex **只补缺失键**，
    不覆盖模型显式写过的值——提示词已删掉 flags 定义，正常路径下模型不会
    写，保留显式值只是为了旧模型、回放与手工候选不丢真实信号。
    """

    staged = copy.deepcopy(dict(payload))
    items = staged.get("items")
    if not isinstance(items, list):
        return staged
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("flags")
        flags = dict(raw) if isinstance(raw, Mapping) else {}
        for name in PROGRAM_FILLED_FLAG_FIELDS:
            flags.setdefault(name, False)
        if ex_value is not None:
            flags["ex"] = bool(ex_value)   # 防爆以程序判定为准
        else:
            flags.setdefault("ex", False)
        item["flags"] = flags
    return staged


def apply_program_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fill the fields whose values are decided by COPA, not by the model.

    模型可以完全不写这几项（提示词里已经不再要求），也可以写错值；这里
    统一按程序口径补成确定值，让校验器只看「真正需要模型判断」的内容。
    ``quote_title`` 只按 ``quote.m_brand`` 推出，与仪表品牌无关；
    ``confirmed_by_user`` 一律置 False——确认权在人，任何模型输出都不能
    代替用户点确认。``seq`` 与 ``declared_count`` 见
    :func:`fill_structural_fields`（它们要等增量合并之后才准）。
    """

    staged = copy.deepcopy(dict(payload))
    staged.setdefault("schema_version", 1)
    if not _nonempty_string(staged.get("origin")):
        staged["origin"] = "llm"
    if not _nonempty_string(staged.get("schema_fingerprint")):
        staged["schema_fingerprint"] = _schema()["schema_fingerprint"]
    quote = staged.get("quote")
    if isinstance(quote, dict):
        quote["confirmed_by_user"] = False
        title = quote_title_for(quote.get("m_brand"), quote.get("quote_title"))
        if title:
            quote["quote_title"] = title
    return staged


def fill_structural_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fill the structural fields that only need the final item list.

    与 :func:`apply_program_fields` 分开，是因为这两项**必须在增量合并之后**
    才算得准：合并前按位置补 ``seq``，多条目报价里「只改第 2 条」会被补成
    ``seq=1``，直接改写第 1 条；``declared_count`` 也会被算成「本轮增量有几条」
    而不是整单几条。

    ``declared_count`` 一律由程序按实际条数写定——它在界面与 Checklist 里都
    不展示，唯一用途是契约自洽检查；真正的条数确认由人在预览里做。
    """

    staged = copy.deepcopy(dict(payload))
    items = staged.get("items")
    if not isinstance(items, list):
        return staged
    for index, item in enumerate(items, 1):
        # 模型显式写的 seq 不覆盖：多条报价里「改第几条」靠它定位，宁可用
        # 模型给的错值走校验，也不要程序替它猜一个位置。
        if isinstance(item, dict) and item.get("seq") is None:
            item["seq"] = index
    quote = staged.get("quote")
    if isinstance(quote, dict):
        quote["declared_count"] = len(items)
    return staged


def _dump_schema_for_prompt(schema: Mapping[str, Any]) -> str:
    """Serialize the schema with one top-level key per line.

    完全紧凑成一行有 1 万字符，模型读起来没有结构感；只保留顶层换行，
    既有分块又不多花一个字节的缩进。
    """

    lines = [
        '  {}: {}'.format(
            json.dumps(key, ensure_ascii=False),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
        for key, value in schema.items()
    ]
    return "{\n" + ",\n".join(lines) + "\n}"


def _rules_dir() -> Path:
    """Locate ``llm/rules`` for source runs, frozen builds and bundled data."""

    candidates = [_ROOT_DIR / "llm" / "rules"]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "llm" / "rules")
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def print_prompt() -> str:
    """Return the complete system prompt: protocol, rules, then the schema.

    ``llm/rules/00-*.md`` is the conversation protocol.  A packaged build that
    lost the rules directory would otherwise send a schema-only prompt with no
    error, so a missing or empty protocol fails loudly here.

    段落顺序是有意的：协议 → 规则 → 引导语 → schema。system prompt 每次会话
    逐字节相同，所以这个顺序对前缀缓存没有影响；它的作用在于「抄写距离」——
    模型是照着 schema 抄字段名和结构的，schema 放在末尾就紧邻用户消息，
    离生成点最近，自创字段名的概率最低。规则是禁止项，靠前背靠背读完即可。
    """
    rules_dir = _rules_dir()
    try:
        rule_paths = sorted(path for path in rules_dir.glob("*") if path.is_file())
    except OSError:
        rule_paths = []
    protocol: list[str] = []
    rules: list[str] = []
    for path in rule_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        if path.name.startswith("00-"):
            protocol.append(text)
        else:
            rules.append("规则文件 {}:\n{}".format(path.name, text))
    if not protocol:
        raise RuntimeError(
            "LLM 对话协议文件缺失：{}（需要 00-*.md）；"
            "打包或部署时必须包含 llm/rules".format(rules_dir)
        )
    parts = [
        *protocol,
        *rules,
        "以下是 COPA 契约的唯一真源：完整 JSON Schema 与字段语义说明。",
        "字段语义、单位与非契约列示例见 field_semantics；"
        "缺失字段保持缺失并交给契约报错。",
        "schema_version / origin / schema_fingerprint / quote.quote_title / "
        "quote.confirmed_by_user 由 COPA 程序填写（抬头只按 quote.m_brand 推出），"
        "schema 里已省略，你不需要输出它们。",
        "schema:",
        _dump_schema_for_prompt(_prompt_schema()),
    ]
    return "\n\n".join(parts)


_GENERATED_RE = re.compile(r"\s*[(（]generated[)）]\s*$", re.IGNORECASE)


def normalize_generated_marks(payload: Mapping[str, Any]) -> dict[str, Any]:
    """剥离模型推断值后的 ``(generated)`` 标记，并写入 provenance 留痕。

    LLM 按提示词在「无原文证据、靠语义推断」得到的值后面附 ``(generated)``。
    该标记只给人看，不能进 engine：这里统一剥离、还原数值类型，并在
    ``provenance[field].source = "generated"`` 留下机器可读记录。
    无标记的 payload 原样返回（幂等），因此 CLI / 手写候选不受影响。
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
        changed = False
        for name, value in list(fields.items()):
            if not isinstance(value, str) or not _GENERATED_RE.search(value):
                continue
            clean: Any = _GENERATED_RE.sub("", value).strip()
            if re.fullmatch(r"-?\d+(?:\.\d+)?", clean):
                clean = float(clean) if "." in clean else int(clean)
            fields[name] = clean
            record = provenance.get(name)
            record = dict(record) if isinstance(record, dict) else {}
            record["source"] = "generated"
            record["basis"] = record.get("basis") or "模型语义推断，无原文直接证据"
            provenance[name] = record
            changed = True
        if changed:
            item["provenance"] = provenance
    return staged


_TOP_FIELDS = {"schema_version", "origin", "schema_fingerprint", "quote", "items"}
_QUOTE_FIELDS = {
    "project", "m_brand", "c_brand", "quote_title", "source", "declared_count",
    "confirmed_by_user",
}
_ITEM_FIELDS = {
    "seq", "item_type", "quantity", "flags", "fields", "note", "provenance",
    "confirmed_nonstandard", "nonstandard_size",
}
_FLAG_FIELDS = {"metrology", "high_precision", "ex", "digital", "onsite_service"}
_COMMON_FIELD_NAMES = {
    "W1", "W2", "support", "material", "vibration",
    "RPM", "台面尺寸", "required_ex", "安装形式", "分体仪表支架", "power",
    "e_input", "c_family", "req_com1", "req_com2", "special_req",
    "special_req2",
}


def _is_bool(value: Any) -> TypeGuard[bool]:
    return isinstance(value, bool)


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_WEIGHT_UNIT_FACTORS = {
    "kg": 1.0,
    "千克": 1.0,
    "公斤": 1.0,
    "g": 0.001,
    "克": 0.001,
    "t": 1000.0,
    "吨": 1000.0,
}


def _weight_to_kg(value: Any) -> Any:
    """Normalize a numeric weight or a small explicit unit spelling to kg."""
    if _is_number(value):
        return value
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(kg|千克|公斤|g|克|t|吨)?\s*",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "kg").lower()
    result = number * _WEIGHT_UNIT_FACTORS[unit]
    rounded = round(result, 9)
    return int(rounded) if rounded.is_integer() else rounded


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown_warnings(value: Mapping[str, Any], allowed: set[str], prefix: str) -> list[dict[str, str]]:
    return [
        _warning(
            "{}.{}".format(prefix, key), "UNKNOWN_FIELD",
            "未知字段将被忽略：{}".format(key),
        )
        for key in value
        if key not in allowed
    ]


def _normal_size(value: Any) -> Any:
    return size_to_mm(value) if isinstance(value, str) else value


def allowed_values(paths: Sequence[str]) -> dict[str, list[str]]:
    """Map error paths to the enum values this contract accepts.

    校验反馈只说「哪里不对」时，小模型常常原地打转；把可选项一并交给它，
    比让它自己去 2.5 万字符的 schema 里翻便宜得多。查不到枚举的 path 直接
    不出现——缺字段本身没有可选值。
    """

    contract_def = _schema().get("payload_contract") or {}
    properties = contract_def.get("properties") or {}
    defs = contract_def.get("$defs") or {}
    groups = (
        ((properties.get("quote") or {}).get("properties") or {}),
        ((defs.get("fields") or {}).get("properties") or {}),
        ((defs.get("item") or {}).get("properties") or {}),
    )

    def enum_of(prop: Any) -> list[str]:
        if not isinstance(prop, Mapping):
            return []
        values = prop.get("enum")
        if isinstance(values, list):
            return [str(value) for value in values]
        items = prop.get("items")
        if isinstance(items, Mapping) and isinstance(items.get("enum"), list):
            return [str(value) for value in items["enum"]]
        return []

    found: dict[str, list[str]] = {}
    for path in paths:
        name = str(path).rsplit(".", 1)[-1]
        for group in groups:
            values = enum_of(group.get(name))
            if values:
                found[str(path)] = values
                break
    return found


def nearest_standard_size(item_type: str, raw: Any) -> dict[str, Any] | None:
    """Return the closest table size for a non-standard platform/bench size.

    ``distance`` is the Manhattan distance in millimetres; ties prefer the
    smaller area so a downgrade never silently jumps to a much larger machine.
    Returns ``None`` when the input cannot be parsed or the table has no sizes.
    """

    normalized = _normal_size(raw)
    if not isinstance(normalized, str) or not re.fullmatch(
            r"\d+(?:\.\d+)?x\d+(?:\.\d+)?", normalized):
        return None
    candidates = _known_sizes().get(item_type) or []
    if not candidates:
        return None
    try:
        length, width = (float(part) for part in normalized.split("x"))
    except ValueError:
        return None
    best: tuple[tuple[float, float, float, str], str] | None = None
    for value in candidates:
        try:
            candidate_length, candidate_width = (
                float(part) for part in value.split("x")
            )
        except ValueError:
            continue
        distance = abs(candidate_length - length) + abs(candidate_width - width)
        area_delta = abs(candidate_length * candidate_width - length * width)
        key = (distance, area_delta, candidate_length * candidate_width, value)
        if best is None or key < best[0]:
            best = (key, value)
    if best is None:
        return None
    return {
        "size": best[1],
        "requested": normalized,
        "distance_mm": best[0][0],
    }


def _controller_rows(brand: str) -> list[dict[str, Any]]:
    brands = (_selection_rules().get("brands") or {}).get("controller_db") or {}
    filename = brands.get(brand)
    if not filename:
        return []
    try:
        return engine.DatabaseLoader(_selection_rules(), brand).load_controllers()
    except (OSError, KeyError, ValueError):
        return []


def _ex_value(level: Any) -> int:
    mapping = ((_selection_rules().get("controller_selection") or {})
               .get("ex_mapping") or {})
    try:
        return int(mapping.get(str(level), 0))
    except (TypeError, ValueError):
        return 0


def _r1_brand_limit(
    item_path: str,
    item: Mapping[str, Any],
    errors: list[dict[str, str]],
    brand: Any,
) -> None:
    """R1：防爆等级不能超过该传感器/秤体品牌仪表库的上限。

    品牌来自 quote 级（整单共用一个 m_brand），与仪表品牌无关。
    """

    flags = item.get("flags") or {}
    fields = item.get("fields") or {}
    if flags.get("ex") is not True:
        return
    required_ex = fields.get("required_ex")
    if required_ex not in set(_required_ex_levels()) or brand not in set(_brands()["m_brand"]):
        return
    rows = _controller_rows(str(brand))
    maximum = max((_ex_value(row.get("EX_level")) for row in rows), default=0)
    requested = _ex_value(required_ex)
    if maximum < requested:
        levels = _required_ex_levels()
        available = next((level for level in levels if _ex_value(level) == maximum), "0")
        errors.append(_err(
            item_path + ".fields.required_ex", "EX_BRAND_LIMIT",
            "品牌 {} 的防爆仪表最高为 {}，无法满足 {}".format(
                brand, available, required_ex
            ),
        ))


def _field_required(item_type: str, name: str) -> bool:
    if name in {"W1", "material", "台面尺寸"}:
        return True
    if item_type == "称重模块" and name in {"W2", "support", "vibration"}:
        return True
    if item_type == "台秤" and name == "安装形式":
        return True
    return False


def validate_payload(payload: Any) -> list[dict[str, str]]:
    """Validate a quote payload and return non-blocking warnings.

    All blocking errors are accumulated so one correction round exposes the
    complete set of missing/invalid fields.
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(payload, Mapping):
        raise ContractError(_err("$", "TYPE", "顶层必须是 JSON 对象"))

    warnings.extend(_unknown_warnings(payload, _TOP_FIELDS, "$"))
    if "schema_version" not in payload:
        errors.append(_err("schema_version", "MISSING_FIELD", "缺少 schema_version"))
    elif payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        errors.append(_err("schema_version", "SCHEMA_VERSION", "只接受 schema_version=1"))
    if "origin" not in payload:
        errors.append(_err("origin", "MISSING_FIELD", "缺少 origin"))
    elif payload.get("origin") != "llm":
        errors.append(_err("origin", "ENUM", "origin 必须为 llm"))
    if not _nonempty_string(payload.get("schema_fingerprint")):
        errors.append(_err("schema_fingerprint", "MISSING_FIELD", "缺少 schema_fingerprint"))
    elif payload.get("schema_fingerprint") != _schema()["schema_fingerprint"]:
        warnings.append(_warning(
            "schema_fingerprint", "SCHEMA_FINGERPRINT",
            "schema_fingerprint 与当前规则/通表标记不一致",
        ))

    brands = _brands()
    quote = payload.get("quote")
    if not isinstance(quote, Mapping):
        errors.append(_err("quote", "MISSING_FIELD", "缺少 quote 对象"))
        quote = {}
    else:
        warnings.extend(_unknown_warnings(quote, _QUOTE_FIELDS, "quote"))
    if not _nonempty_string(quote.get("project")):
        errors.append(_err("quote.project", "MISSING_FIELD", "缺少项目名"))
    # 品牌是整单共用的两个值：抬头、防爆上限、选型全部按它们走，因此放在
    # quote 级只校验一次；条目里再写同名键只会被当成未知字段忽略。
    for name in ("m_brand", "c_brand"):
        value = quote.get(name)
        label = "秤体/传感器品牌" if name == "m_brand" else "仪表品牌"
        if name not in quote or not _nonempty_string(value):
            errors.append(_err(
                "quote." + name, "MISSING_FIELD", "缺少整单共用的{}".format(label),
            ))
        elif value not in brands[name]:
            errors.append(_err(
                "quote." + name, "ENUM", "{}不在当前品牌数据范围内".format(label),
            ))
    # 抬头由程序按 m_brand 写死，模型写错也只会被覆盖，不构成阻塞错误。
    if "quote_title" in quote and quote.get("quote_title") not in _quote_titles():
        warnings.append(_warning(
            "quote.quote_title", "QUOTE_TITLE",
            "报价抬头由程序按 m_brand 决定，此值将被覆盖",
        ))
    if "source" in quote and not isinstance(quote.get("source"), str):
        errors.append(_err("quote.source", "TYPE", "source 必须是字符串"))
    if "declared_count" not in quote:
        errors.append(_err("quote.declared_count", "MISSING_FIELD", "缺少 declared_count"))
    elif not _is_int(quote.get("declared_count")):
        errors.append(_err("quote.declared_count", "TYPE", "declared_count 必须是整数"))
    if "confirmed_by_user" not in quote:
        errors.append(_err("quote.confirmed_by_user", "MISSING_FIELD", "缺少 confirmed_by_user"))
    elif quote.get("confirmed_by_user") is not True:
        errors.append(_err(
            "quote.confirmed_by_user", "NOT_CONFIRMED",
            "confirmed_by_user 必须为 true",
        ))

    items = payload.get("items")
    if not isinstance(items, list):
        errors.append(_err("items", "TYPE", "items 必须是数组"))
        items = []
    if _is_int(quote.get("declared_count")) and quote.get("declared_count") != len(items):
        errors.append(_err(
            "quote.declared_count", "COUNT_MISMATCH",
            "declared_count={} 与 items 条数={} 不一致".format(
                quote.get("declared_count"), len(items)
            ),
        ))

    item_types = _supported_item_types()
    materials = set(_materials())
    levels = set(_required_ex_levels())
    options = _schema()["options"]
    known_sizes = _known_sizes()
    # 条目里不再有品牌字段，R1 上限与抬头统一按整单的 m_brand 判断。
    m_brand = quote.get("m_brand")

    for index, item in enumerate(items):
        path = "items[{}]".format(index)
        if not isinstance(item, Mapping):
            errors.append(_err(path, "TYPE", "条目必须是对象"))
            continue
        warnings.extend(_unknown_warnings(item, _ITEM_FIELDS, path))
        seq = item.get("seq")
        if "seq" not in item:
            errors.append(_err(path + ".seq", "MISSING_FIELD", "缺少 seq"))
        elif not _is_int(seq):
            errors.append(_err(path + ".seq", "TYPE", "seq 必须是整数"))
        elif seq != index + 1:
            errors.append(_err(path + ".seq", "RANGE", "seq 必须从 1 连续递增"))
        item_type = item.get("item_type")
        if "item_type" not in item:
            errors.append(_err(path + ".item_type", "MISSING_FIELD", "缺少 item_type"))
        elif item_type not in item_types:
            errors.append(_err(
                path + ".item_type", "ITEM_TYPE",
                "item_type 必须是当前规则支持的产品线",
            ))
        quantity = item.get("quantity")
        if "quantity" not in item:
            errors.append(_err(path + ".quantity", "MISSING_FIELD", "缺少 quantity"))
        elif not _is_int(quantity):
            errors.append(_err(path + ".quantity", "TYPE", "quantity 必须是整数"))
        elif quantity < 1:
            errors.append(_err(path + ".quantity", "RANGE", "quantity 必须大于等于 1"))

        flags = item.get("flags")
        if not isinstance(flags, Mapping):
            errors.append(_err(path + ".flags", "MISSING_FIELD", "缺少 flags 对象"))
            flags = {}
        else:
            warnings.extend(_unknown_warnings(flags, _FLAG_FIELDS, path + ".flags"))
        for name in sorted(_FLAG_FIELDS):
            if name not in flags:
                errors.append(_err(
                    path + ".flags." + name, "MISSING_FIELD", "缺少布尔字段 {}".format(name)
                ))
            elif not _is_bool(flags.get(name)):
                errors.append(_err(
                    path + ".flags." + name, "TYPE", "{} 必须是布尔值".format(name)
                ))

        fields = item.get("fields")
        if not isinstance(fields, Mapping):
            errors.append(_err(path + ".fields", "MISSING_FIELD", "缺少 fields 对象"))
            fields = {}
        else:
            warnings.extend(_unknown_warnings(fields, _COMMON_FIELD_NAMES, path + ".fields"))

        if item_type in item_types:
            for name in _schema()["fields"].get(item_type, []):
                value = fields.get(name)
                if name not in fields or value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(_err(
                        path + ".fields." + name, "MISSING_FIELD",
                        "缺少{}".format({
                            "W1": "最大物料重量" if item_type == "称重模块" else "量程",
                            "W2": "皮重", "support": "支点数", "material": "材质",
                            "m_brand": "秤体品牌" if item_type != "称重模块" else "传感器品牌",
                            "c_brand": "仪表品牌", "台面尺寸": "台面尺寸",
                            "安装形式": "安装形式",
                        }.get(name, name)),
                    ))

        for name in ("W1", "W2"):
            weight = fields.get(name)
            if weight is not None:
                if not _is_number(weight):
                    errors.append(_err(path + ".fields." + name, "TYPE", "{} 必须是数值".format(name)))
                elif name == "W1" and weight <= 0:
                    errors.append(_err(path + ".fields.W1", "RANGE", "W1 必须大于 0"))
        if "e_input" in fields and fields.get("e_input") is not None:
            e_value = _weight_to_kg(fields.get("e_input"))
            if e_value is None:
                errors.append(_err(path + ".fields.e_input", "TYPE", "e_input 必须是数值或带单位的分度值"))
            elif e_value <= 0:
                errors.append(_err(path + ".fields.e_input", "RANGE", "e_input 必须大于 0"))
        if item_type == "称重模块":
            w2 = fields.get("W2")
            if w2 is not None and _is_number(w2) and w2 < 0:
                errors.append(_err(path + ".fields.W2", "RANGE", "W2 不能小于 0"))
            if "support" in fields:
                support = fields.get("support")
                if not _is_int(support):
                    errors.append(_err(path + ".fields.support", "TYPE", "support 必须是整数"))
                elif support < 3:
                    errors.append(_err(path + ".fields.support", "RANGE", "support 必须大于等于 3"))
        if "material" in fields and fields.get("material") not in materials:
            errors.append(_err(path + ".fields.material", "ENUM", "材质不在当前规则取值范围内"))

        if "vibration" in fields and not _is_bool(fields.get("vibration")):
            errors.append(_err(path + ".fields.vibration", "TYPE", "vibration 必须是布尔值"))
        if fields.get("vibration") is True:
            if "RPM" not in fields or fields.get("RPM") is None:
                errors.append(_err(path + ".fields.RPM", "CONDITIONAL", "vibration=true 时必须提供 RPM"))
        if "RPM" in fields and fields.get("RPM") is not None:
            rpm = fields.get("RPM")
            if not _is_int(rpm):
                errors.append(_err(path + ".fields.RPM", "TYPE", "RPM 必须是整数"))
            elif rpm < 0:
                errors.append(_err(path + ".fields.RPM", "RANGE", "RPM 不能小于 0"))

        if flags.get("ex") is True:
            if not _nonempty_string(fields.get("required_ex")):
                errors.append(_err(path + ".fields.required_ex", "CONDITIONAL", "防爆条目必须提供 required_ex"))
            elif fields.get("required_ex") not in levels:
                errors.append(_err(path + ".fields.required_ex", "ENUM", "required_ex 不在当前防爆等级范围内"))
        elif "required_ex" in fields and fields.get("required_ex") not in (False, None, "", "0"):
            if fields.get("required_ex") not in levels:
                errors.append(_err(path + ".fields.required_ex", "ENUM", "required_ex 不在当前防爆等级范围内"))

        for name, allowed in (("安装形式", options.get("安装形式", [])),
                             ("分体仪表支架", options.get("分体仪表支架", [])),
                             ("power", options.get("power", []))):
            if name in fields and fields.get(name) not in (None, "", False) and allowed and fields.get(name) not in allowed:
                errors.append(_err(path + ".fields." + name, "ENUM", "{} 不在当前规则取值范围内".format(name)))
        if "分体仪表支架" in fields and not isinstance(fields.get("分体仪表支架"), (str, bool, type(None))):
            errors.append(_err(path + ".fields.分体仪表支架", "TYPE", "分体仪表支架必须是字符串或布尔值"))

        protocol_categories = _protocol_categories()
        for name in ("req_com1", "req_com2"):
            if name not in fields or fields.get(name) in (None, ""):
                continue
            value = fields.get(name)
            if not isinstance(value, (str, list, tuple)):
                errors.append(_err(path + ".fields." + name, "TYPE", "{} 必须是协议字符串数组".format(name)))
                continue
            values = _split_protocols(value)
            allowed = protocol_categories["basic" if name == "req_com1" else "extended"]
            if allowed and any(v not in allowed for v in values):
                errors.append(_err(path + ".fields." + name, "ENUM", "{} 含未知通讯协议".format(name)))
        if "special_req" in fields and fields.get("special_req") is not None:
            special = fields.get("special_req")
            if not _is_int(special):
                errors.append(_err(path + ".fields.special_req", "TYPE", "special_req 必须是整数"))
            elif special < 1:
                errors.append(_err(path + ".fields.special_req", "RANGE", "special_req 必须大于等于 1"))

        if "confirmed_nonstandard" in item and not _is_bool(item.get("confirmed_nonstandard")):
            errors.append(_err(
                path + ".confirmed_nonstandard", "TYPE",
                "confirmed_nonstandard 必须是布尔值",
            ))

        if item_type in ("平台秤", "台秤") and "台面尺寸" in fields:
            raw_size = fields.get("台面尺寸")
            normalized = _normal_size(raw_size)
            if not isinstance(normalized, str) or not re.fullmatch(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?", normalized):
                errors.append(_err(path + ".fields.台面尺寸", "TYPE", "台面尺寸格式无法识别"))
            elif normalized not in set(known_sizes.get(item_type, [])):
                confirmed = item.get("confirmed_nonstandard") is True
                if not confirmed:
                    errors.append(_err(
                        path + ".fields.台面尺寸", "NONSTANDARD_SIZE",
                        "{} 不在通表内，属非标尺寸，请确认后标记 confirmed_nonstandard".format(raw_size),
                    ))
                else:
                    warnings.append(_warning(
                        path + ".fields.台面尺寸", "NONSTANDARD_SIZE",
                        "{} 为已确认的非标台面尺寸".format(normalized),
                    ))

        if item_type == "台秤" and fields.get("material") == "碳钢":
            warnings.append(_warning(
                path + ".fields.material", "R2_CARBON_STEEL",
                "台秤不存在纯碳钢机型，请确认是否接受碳钢秤架+不锈钢秤盘",
            ))

        if isinstance(flags, Mapping) and isinstance(fields, Mapping):
            _r1_brand_limit(path, item, errors, m_brand)

        note = item.get("note")
        if note is not None and not isinstance(note, str):
            errors.append(_err(path + ".note", "TYPE", "note 必须是字符串"))
        provenance = item.get("provenance")
        if provenance is not None and not isinstance(provenance, Mapping):
            errors.append(_err(path + ".provenance", "TYPE", "provenance 必须是对象"))
        elif isinstance(provenance, Mapping):
            for field_name, record in provenance.items():
                if field_name not in _COMMON_FIELD_NAMES:
                    warnings.append(_warning(
                        path + ".provenance." + str(field_name), "UNKNOWN_FIELD",
                        "provenance 字段不在契约字段范围内，将被忽略",
                    ))
                elif not isinstance(record, Mapping):
                    errors.append(_err(
                        path + ".provenance." + str(field_name), "TYPE",
                        "provenance 记录必须是对象",
                    ))
                else:
                    for record_key in ("source", "basis"):
                        if record_key in record and not isinstance(record.get(record_key), str):
                            errors.append(_err(
                                path + ".provenance." + str(field_name) + "." + record_key,
                                "TYPE",
                                "provenance 的 {} 必须是字符串".format(record_key),
                            ))
                    warnings.extend(_unknown_warnings(
                        record, {"source", "basis"},
                        path + ".provenance." + str(field_name),
                    ))

    if errors:
        # A missing/null value can otherwise trigger a follow-up enum/type
        # diagnostic for the same field.  Keep the first, most useful error per
        # path while preserving all independent field errors.
        unique_errors = []
        seen_paths = set()
        for error in errors:
            path = error.get("path")
            if path in seen_paths:
                continue
            seen_paths.add(path)
            unique_errors.append(error)
        raise ContractError(unique_errors)
    return warnings


def payload_to_entries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Translate a validated payload into the entry shape consumed by Desk."""
    # Keep this useful to callers that intentionally separate validation and
    # translation, while still failing clearly on malformed direct calls.
    validate_payload(payload)
    quote = payload["quote"]
    onsite = any(item["flags"].get("onsite_service", False) for item in payload["items"])
    # 品牌是整单共用的：翻译成 engine 输入时把 quote 级的两个值注入每一条，
    # 抬头按 m_brand 写死（与仪表品牌无关）。
    quote_brand = {
        "m_brand": quote.get("m_brand"),
        "c_brand": quote.get("c_brand"),
    }
    quote_title = quote_title_for(quote.get("m_brand"), quote.get("quote_title"))
    entries = []
    for item in payload["items"]:
        # Validation warns on unknown fields; they must not leak into the
        # engine adapter.  In particular ``install`` is a GUI/parser detail,
        # not part of the LLM fields contract, and must be ignored here.
        fields = {
            key: value for key, value in (item.get("fields") or {}).items()
            if key in _COMMON_FIELD_NAMES
        }
        fields.update({k: v for k, v in quote_brand.items() if v is not None})
        if "e_input" in fields and fields.get("e_input") is not None:
            normalized_e = _weight_to_kg(fields.get("e_input"))
            if normalized_e is not None:
                fields["e_input"] = normalized_e
        _normalize_com_fields(fields)
        fields["Ex_P"] = bool(item["flags"].get("ex"))
        fields["高精度"] = bool(item["flags"].get("high_precision"))
        fields["metrology"] = bool(item["flags"].get("metrology"))
        parsed = {"data": fields, "warnings": []}
        entries.append({
            "description": item.get("note", "") or "",
            "item_type": item["item_type"],
            "quote_info": {
                "quote_id": item["seq"],
                "quantity": item["quantity"],
            },
            "onsite_service": onsite,
            "parsed": parsed,
            "Ex_P": bool(item["flags"].get("ex")),
            "high_precision": bool(item["flags"].get("high_precision")),
            "metrology": bool(item["flags"].get("metrology")),
            "digital": bool(item["flags"].get("digital")),
            "_origin": payload.get("origin"),
            "origin": payload.get("origin"),
            "project": quote.get("project"),
            "quote_title": quote_title,
            "source": quote.get("source"),
            "note": item.get("note"),
            "provenance": item.get("provenance") or {},
            "confirmed_nonstandard": bool(item.get("confirmed_nonstandard", False)),
            "nonstandard_size": item.get("nonstandard_size"),
        })
    return entries


def build_engine_input(entry: Mapping[str, Any], strict: bool = False) -> dict[str, Any]:
    """Build the legacy engine input shape from a GUI/contract entry.

    ``strict=False`` is the exact historical GUI behavior.  ``strict=True``
    removes semantic fallbacks that would guess for an LLM payload.
    """
    parsed_container = entry.get("parsed") or {}
    parsed = parsed_container.get("data", {}) if isinstance(parsed_container, Mapping) else {}
    if not isinstance(parsed, Mapping):
        parsed = {}

    item_type = engine.resolver.resolve_item_type(entry["item_type"])
    w1 = parsed.get("W1")
    r_input = parsed.get("r_input")
    if item_type in ("platform", "bench") and w1 is None and not strict:
        w1 = r_input

    ex_p = bool(entry.get("Ex_P", False) or parsed.get("Ex_P", False))
    m_brand = parsed.get("m_brand")
    c_brand = parsed.get("c_brand")
    if c_brand is None and m_brand and item_type in ("platform", "bench") and not strict:
        c_brand = m_brand
    bracket = parsed.get("分体仪表支架")
    vibration = bool(parsed.get("vibration", False))
    channels = parsed.get("special_req") or 0
    required_ex = parsed.get("required_ex")
    if ex_p and not required_ex and not strict:
        required_ex = "IIBT4"
    if not ex_p:
        required_ex = False
    rpm = parsed.get("RPM")
    if not vibration:
        rpm = 0
    elif rpm is None and not strict:
        rpm = 0
    w2 = parsed.get("W2")
    if w2 is None and strict:
        w2 = 0
    e_input = parsed.get("e_input")
    if e_input is not None:
        normalized_e = _weight_to_kg(e_input)
        if normalized_e is not None:
            e_input = normalized_e

    result = {
        "module_data": {
            "item_type": item_type,
            "W1": w1,
            "W2": w2,
            "support": parsed.get("support"),
            "Ex_P": ex_p,
            "required_ex": required_ex,
            "material": parsed.get("material"),
            "vibration": vibration,
            "RPM": rpm,
            "台面尺寸": size_to_mm(parsed.get("台面尺寸")),
            "高精度": bool(entry.get("high_precision", False) or parsed.get("高精度", False)),
            "数字化": bool(entry.get("digital", False)),
            "e_input": e_input,
            "安装形式": parsed.get("安装形式"),
            "分体仪表支架": bracket,
            "m_brand": m_brand,
            "c_brand": c_brand,
            "c_family": parsed.get("c_family"),
        },
        "metrology": {
            "metrology": bool(entry.get("metrology", False) or parsed.get("metrology", False)),
            "r_input": parsed.get("r_input"),
            "e_input": e_input,
        },
        "com": {
            "req_com1": parsed.get("req_com1"),
            "req_com2": parsed.get("req_com2"),
            "special_req": channels >= 2,
            "special_req2": bool(parsed.get("special_req2", False)),
        },
        "hardware": {
            "install": parsed.get("install"),
            "power": parsed.get("power"),
            "bracket": bracket,
        },
    }
    if strict:
        missing = _strict_missing(result, entry)
        if missing:
            raise ContractError([
                _err("fields." + key, "MISSING_FIELD", _missing_message(
                    [key], item_type, parsed
                ).split("。", 1)[0])
                for key in missing
            ])
    return result


def _strict_missing(engine_input: Mapping[str, Any], entry: Mapping[str, Any]) -> list[str]:
    module_data = engine_input["module_data"]
    item_type = module_data["item_type"]
    parsed_container = entry.get("parsed") or {}
    parsed = parsed_container.get("data", {}) if isinstance(parsed_container, Mapping) else {}
    if not isinstance(parsed, Mapping):
        parsed = {}
    missing = []
    for key in ("W1", "material", "m_brand", "c_brand"):
        value = module_data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    if item_type == "module":
        for key in ("W2", "support", "vibration"):
            value = module_data.get(key)
            if key not in parsed or value is None or (isinstance(value, str) and not value.strip()):
                missing.append(key)
    elif module_data.get("台面尺寸") in (None, ""):
        missing.append("台面尺寸")
    if item_type == "bench" and not module_data.get("安装形式"):
        missing.append("安装形式")
    if module_data.get("Ex_P") and not module_data.get("required_ex"):
        missing.append("required_ex")
    if module_data.get("vibration") and module_data.get("RPM") is None:
        missing.append("RPM")
    return missing


_PARAM_NAME = {
    "m_brand": "传感器品牌",
    "c_brand": "仪表品牌",
    "support": "支点数",
    "material": "材质",
    "W1": "最大物料重量",
    "台面尺寸": "台面尺寸",
}

_PARAM_REASON_ALIASES = {"W1": ("W1", "r_input", "W_total")}


def _missing_message(missing: Sequence[str], item_type: str, parsed: Mapping[str, Any] | None) -> str:
    reasons = {
        warning.get("parameter"): warning.get("reason")
        for warning in (parsed or {}).get("warnings", [])
        if warning.get("reason")
    }
    clauses = []
    for key in missing:
        reason = next((reasons[alias] for alias in _PARAM_REASON_ALIASES.get(key, (key,))
                       if alias in reasons), None)
        if reason:
            clauses.append(reason)
            continue
        name = _PARAM_NAME.get(key, key)
        if key == "W1" and item_type in ("platform", "bench"):
            name = "量程"
        if key == "m_brand" and item_type in ("platform", "bench"):
            name = "秤体品牌"
        clauses.append("缺少{}".format(name))
    return "{}。请在需求中补充后重新选型。".format("；".join(clauses))


def _missing_required(engine_input: Mapping[str, Any]) -> list[str]:
    """Historical GUI preflight, retained as a module-level public helper."""
    module_data = engine_input["module_data"]
    required = ["W1", "material"]
    if module_data["item_type"] == "module":
        required += ["m_brand", "support", "c_brand"]
    else:
        required += ["m_brand"]
    missing = [key for key in required if module_data.get(key) is None]
    if module_data["item_type"] in ("platform", "bench") and module_data.get("台面尺寸") is None:
        missing.append("台面尺寸")
    return missing


_DIAGNOSTIC_KEYS = ("bench_diagnostic", "platform_diagnostic", "module_diagnostic")


def _failure_reason(result: Mapping[str, Any]) -> str:
    error = str(result.get("error") or "").strip()
    if error:
        return error
    for key in _DIAGNOSTIC_KEYS:
        diagnostic = result.get(key) or {}
        evidence = diagnostic.get("evidence") or {}
        for reason in (evidence.get("reason"), diagnostic.get("reason")):
            reason = str(reason or "").strip()
            if reason:
                return reason
    return "当前需求在数据库中没有匹配方案，请核对量程、台面尺寸、材质与防爆要求。"


__all__ = [
    "ContractError", "validate_payload", "payload_to_entries",
    "build_engine_input", "print_schema", "print_prompt", "_failure_reason",
    "_missing_required", "_missing_message", "nearest_standard_size",
    "normalize_generated_marks", "allowed_values",
]
