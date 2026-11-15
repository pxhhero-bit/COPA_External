"""离线读取电子秤选型表，生成待澄清 JSON；不调用模型、不补业务默认值。"""
import argparse
import json
import re
from pathlib import Path

from openpyxl import load_workbook


def mass_kg(value):
    """将表内明确带单位的质量换成 kg；纯数值按列标题的 kg。"""
    if isinstance(value, (int, float)):
        return value
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(kg|公斤|g|克|t|吨)?\s*", str(value or ""), re.I)
    if not match:
        return None
    unit = (match[2] or "kg").lower()
    return float(match[1]) * {"kg": 1, "公斤": 1, "g": .001, "克": .001, "t": 1000, "吨": 1000}[unit]


def parse_selection(path):
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = workbook["电子秤"]
        headers = [c.value for c in next(sheet.iter_rows(min_row=2, max_row=2, max_col=25))]
        items, evidence, questions = [], [], []
        names = {"电子台秤": "台秤", "可掀起式平台秤": "平台秤", "平台秤": "平台秤", "称重模块": "称重模块"}
        for row in sheet.iter_rows(min_row=3, max_col=25):
            values = [c.value for c in row]
            if not isinstance(values[0], (int, float)) or not values[1]:
                continue
            seq = len(items) + 1
            name = str(values[1]).strip()
            item_type = names.get(name, name)
            raw = {c.coordinate: {"header": headers[i], "value": c.value}
                   for i, c in enumerate(row) if c.value is not None}
            evidence.append({"seq": seq, "sheet": sheet.title, "row": row[0].row, "cells": raw})
            fields = {"W1": mass_kg(values[10]), "material": None,
                      "m_brand": None, "c_brand": None}
            if values[5] == values[6] and values[5] in ("不锈钢", "碳钢"):
                fields["material"] = values[5]
            if item_type in ("台秤", "平台秤"):
                fields["台面尺寸"] = str(values[4]).replace("*", "x").replace("×", "x") if values[4] else None
                fields["e_input"] = str(values[12]) if values[12] else None
            ex = True if values[18] == "防爆" else (False if values[18] == "不防爆" else None)
            fields["required_ex"] = None if ex is not False else False
            if item_type == "台秤":
                fields["安装形式"] = None
            power_map = {"220VAC": "AC220V", "24VDC": "DC24V",
                         "AC220V": "AC220V", "DC24V": "DC24V"}
            power_key = values[20] if isinstance(values[20], str) else ""
            power = power_map.get(power_key)
            if power:
                fields["power"] = power
            if values[14] == "4-20mA+RPOFIBUS DP":
                questions.append({"seq": seq, "code": "SOURCE_TYPO", "message": "通讯原文 RPOFIBUS DP 疑为 PROFIBUS DP，需确认，未自动改写。"})
            provenance = {"W1": {"source": "text", "basis": f"{sheet.title}!K{row[0].row}: {values[10]}"},
                          "台面尺寸": {"source": "text", "basis": f"{sheet.title}!E{row[0].row}: {values[4]}"}}
            items.append({"seq": seq, "item_type": item_type, "quantity": values[24],
                          "flags": {"metrology": None, "high_precision": None, "ex": ex,
                                    "digital": None, "onsite_service": None},
                          "fields": fields, "note": f"{sheet.title}!A{row[0].row}:Y{row[0].row}；原名称：{name}；原通讯：{values[14]}",
                          "provenance": provenance})
            if item_type == name and name not in ("台秤", "平台秤", "称重模块"):
                questions.append({"seq": seq, "code": "ITEM_TYPE", "message": f"{name} 不属于本版支持品类，保留原行，不冒充台秤或删条。"})
            questions.append({"seq": seq, "code": "NEEDS_CLARIFICATION", "message": "原表未明确品牌、防爆等级及全部必填开关；null 保留待澄清，不能直接进入选型。"})
        payload = {"schema_version": 1, "origin": "llm", "schema_fingerprint": "pending",
                   "quote": {"project": "选型表导入待确认", "quote_title": None,
                             "source": Path(path).name, "declared_count": len(items), "confirmed_by_user": False},
                   "items": items}
        return {"payload": payload, "source_evidence": evidence, "clarifications": questions}
    finally:
        workbook.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = parse_selection(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, data in (("selection.draft.json", result["payload"]),
                           ("selection.evidence.json", result["source_evidence"]),
                           ("selection.clarifications.json", result["clarifications"])):
        (args.output_dir / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已读取 {len(result['payload']['items'])} 条；草稿未确认，缺项保留为 null。")


if __name__ == "__main__":
    main()
