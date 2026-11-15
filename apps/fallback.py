"""Deterministic product candidates for engine ``NO_MATCH`` results.

The engine deliberately reports ``NO_MATCH`` when a complete selection cannot
be made.  The checklist still needs a product list so a person can correct the
row in place.  This module is the small, Qt-free adapter for that hand-off:
it reads the same public :class:`engine.DatabaseLoader` data as the engine,
filters only by the requested body brand, and returns rows in the shapes that
``apps.Checklist`` already consumes.

Fallback rows are deliberately *candidates*, not a new selection result.  The
result status and its diagnostics are retained as ``NO_MATCH`` and callers can
use the top-level ``fallback`` marker when writing their run log.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Iterable, Mapping

try:  # Imported as ``COPA.apps.fallback`` in normal use and tests.
    from COPA.engine import engine as _engine
except ImportError:  # pragma: no cover - convenient for direct package use
    from ..engine import engine as _engine


_FALLBACK_NOTE = "候选来自全量通表，非选型结果"
_ITEM_TYPE_CODES = {"平台秤": "platform", "台秤": "bench"}


def attach_fallback(result: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """Attach human-editable candidates to a complete-line ``NO_MATCH``.

    ``result`` is deep-copied before any work, so neither the engine result nor
    any nested diagnostic/list is mutated.  Only platform/bench (whole-machine)
    results are eligible; module-line failures and non-``NO_MATCH`` results are
    returned byte-for-byte in value.  Existing product rows are preserved (for
    example, a bench may have a body row but no compatible controller).

    The returned value keeps ``status`` and nested diagnostic statuses intact.
    When at least one fallback row is available it receives ``fallback=True``;
    that marker is intentionally result-level so Checklist can ignore it while
    the CLI can write the required run-log note.
    """

    result_copy = copy.deepcopy(dict(result)) if isinstance(result, Mapping) else copy.deepcopy(result)
    if not isinstance(result_copy, dict):
        return result_copy
    if result_copy.get("status") != "NO_MATCH":
        return result_copy

    item_type = _item_type(result_copy, entry)
    if item_type not in ("platform", "bench"):
        return result_copy

    product_key = item_type
    # Do not replace a body row that the engine already found.  NO_MATCH can be
    # caused later by a controller/sensor stage and the existing row is already
    # the useful product list in that case.
    if result_copy.get(product_key):
        return result_copy

    data = _entry_data(entry)
    brand = _brand(data)
    if not brand:
        return result_copy

    try:
        rows = _load_product_rows(item_type)
    except (OSError, KeyError, TypeError, ValueError):
        # A missing catalogue is an environment/data problem.  Preserve the
        # original diagnostic rather than turning it into a seemingly valid
        # fallback result.
        return result_copy

    rows = [row for row in rows if _norm(row.get("品牌")) == brand]
    if not rows:
        return result_copy

    material = _field(data, "material", "材质")
    weight = _number(_field(data, "W1", "r_input", "量程"))
    rows.sort(key=lambda row: _sort_key(row, material, weight))

    if item_type == "platform":
        try:
            sensor_rows = _load_sensor_rows(brand)
        except (OSError, KeyError, TypeError, ValueError):
            sensor_rows = []
        result_copy[product_key] = [
            {
                "platform": row,
                "sensors": _platform_sensor_models(row, sensor_rows),
            }
            for row in rows
        ]
    else:
        # Engine's bench result is the raw通表 row list; keep that exact shape.
        result_copy[product_key] = rows

    if result_copy[product_key]:
        result_copy["fallback"] = True
        # This is a non-semantic diagnostic aid for callers that do not have a
        # logger object.  It does not alter status or any engine diagnostics.
        result_copy.setdefault("fallback_note", _FALLBACK_NOTE)
    return result_copy


def _item_type(result: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    code = result.get("item_type")
    if code in ("platform", "bench"):
        return code
    if isinstance(code, str) and code in _ITEM_TYPE_CODES:
        return _ITEM_TYPE_CODES[code]
    code = entry.get("item_type") if isinstance(entry, Mapping) else None
    if not isinstance(code, str):
        return ""
    return _ITEM_TYPE_CODES.get(code, code)


def _entry_data(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the normalized/user-facing data regardless of entry envelope."""

    if not isinstance(entry, Mapping):
        return {}
    module_data = entry.get("module_data")
    if isinstance(module_data, Mapping):
        return dict(module_data)

    parsed = entry.get("parsed")
    if isinstance(parsed, Mapping):
        parsed_data = parsed.get("data")
        if isinstance(parsed_data, Mapping):
            return dict(parsed_data)

    data = entry.get("data")
    if isinstance(data, Mapping):
        return dict(data)

    fields = entry.get("fields")
    if isinstance(fields, Mapping):
        return dict(fields)
    return {}


def _field(data: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = data.get(name)
        if value is not None and value != "":
            return value
    return None


def _brand(data: Mapping[str, Any]) -> str:
    return _norm(_field(data, "m_brand", "品牌", "brand"))


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _material_group(value: Any) -> set[str]:
    """Map business material values to通表 material codes."""

    text = str(value or "").strip().upper()
    groups = getattr(_engine, "PLATFORM_MATERIAL_GROUPS", {})
    for business, codes in groups.items():
        if text == str(business).upper() or text in {str(c).upper() for c in codes}:
            return {str(c).upper() for c in codes}
    return {text} if text else set()


def _sort_key(row: Mapping[str, Any], material: Any, weight: float | None) -> tuple[Any, ...]:
    row_material = _norm(row.get("材质"))
    wanted = _material_group(material)
    material_rank = 0 if wanted and row_material in wanted else 1
    capacity = _number(row.get("量程"))
    distance = abs(capacity - weight) if capacity is not None and weight is not None else math.inf
    model = str(row.get("具体型号") or "")
    return material_rank, distance, model


def _loader_brand() -> str:
    brands = _engine.resolver.rules.get("brands", {}).get("available_brands") or []
    return str(brands[0]) if brands else "FT"


def _load_product_rows(item_type: str) -> list[dict[str, Any]]:
    loader = _engine.DatabaseLoader(_engine.resolver.rules, _loader_brand())
    if item_type == "platform":
        return loader.load_platforms()
    return loader.load_benches()


def _load_sensor_rows(brand: str) -> list[dict[str, Any]]:
    sensor_files = _engine.resolver.rules.get("brands", {}).get("sensor_db", {})
    if brand not in sensor_files:
        return []
    return _engine.DatabaseLoader(_engine.resolver.rules, brand).load_sensors()


def _parse_sensor_token(token: Any) -> tuple[str | None, int | None]:
    # Reuse engine's public parser so kg/t handling stays identical to the
    # normal platform pipeline.  Keep a tiny local fallback for older engines.
    parser = getattr(_engine, "parse_platform_sensor_token", None)
    if parser is not None:
        return parser(str(token or "").strip())

    text = str(token or "").strip()
    match = re.fullmatch(r"(.+)-([0-9]+(?:\.[0-9]+)?)(kg|t)", text, re.IGNORECASE)
    if not match:
        return None, None
    try:
        value = float(match.group(2))
        if match.group(3).lower() == "t":
            value *= 1000
        return match.group(1), int(value)
    except ValueError:
        return None, None


def _platform_sensor_models(row: Mapping[str, Any], sensor_rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Resolve a platform row's ``可用传感器`` tokens against one brand DB."""

    all_sensors = list(sensor_rows)
    row_ex = _norm(row.get("防爆")) not in ("", "0", "FALSE", "NO", "N", "否")
    models: list[str] = []
    for token in str(row.get("可用传感器") or "").split("|"):
        family, capacity = _parse_sensor_token(token)
        if not family or capacity is None:
            continue
        matches = [
            sensor for sensor in all_sensors
            if sensor.get("family型号") == family
            and _number(sensor.get("capacity容量")) == capacity
            and ((_norm(sensor.get("EX_level")) not in ("", "0", "FALSE", "NO", "N", "否")) == row_ex)
        ]
        for sensor in matches:
            # Copy before adding EX_bool; callers may reuse a loader's rows.
            sensor_copy = dict(sensor)
            sensor_copy["EX_bool"] = row_ex
            formatter = getattr(_engine, "format_capacity", None)
            capacity_text = formatter(sensor_copy) if formatter else "{}kg".format(capacity)
            y_formatter = getattr(_engine, "y_suffix", None)
            y_text = y_formatter(sensor_copy, all_sensors) if y_formatter else ""
            ex_text = " EX" if row_ex else ""
            models.append(
                "{}-{}-{}{}{}".format(
                    sensor_copy.get("family型号"),
                    capacity_text,
                    sensor_copy.get("AC准确度等级", ""),
                    ex_text,
                    y_text,
                )
            )
    return models


__all__ = ["attach_fallback"]
