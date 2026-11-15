# -*- coding: utf-8 -*-
"""按 FT230二区防爆仪表配置表.xlsx 重建 flintec 仪表库与描述通表的 FT-230 二区防爆行。

编码规则（FT230 + 6 位）：
  [1] 外壳  N=二区防爆大外壳（不锈钢）
  [2] 模拟数字 A=模拟
  [3] 功能  0=无 1=单网口 2=Wifi B=蓝牙 3=2IN/4OUT A=1路4-20mA
  [4] 电池  0=无
  [5] 支架  1=壁挂 2=立杆
  [6] 电源  A=220VAC  D=24VDC  B=电池版本(24VDC)
"""
import csv
import os
import re

import openpyxl

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
XLSX = r"D:/Documents/Myself/Copilot/FT230二区防爆仪表配置表.xlsx"
CSV_DB = os.path.join(ROOT, "flintec仪表.csv")
CSV_DESC = os.path.join(ROOT, "description", "FT描述通表.csv")

FUNC_ZH = {
    "0": "",
    "1": "单网口（Modbus TCP）",
    "2": "Wifi模块（UDP，TCP）",
    "B": "蓝牙模块",
    "3": "2个输入4个输出（继电器）",
    "A": "1路4-20mA输出",
}
FUNC_EN = {
    "0": "",
    "1": "single Ethernet port (Modbus TCP)",
    "2": "WiFi module (UDP, TCP)",
    "B": "Bluetooth module",
    "3": "2 inputs and 4 outputs (relay)",
    "A": "one 4-20 mA output",
}
COM2 = {"0": "0", "1": "TCP", "2": "TCP|UDP", "B": "BT", "3": "IO", "A": "ANALOG"}
POWER = {"A": ("AC220V", "220VAC without power cord"),
         "D": ("DC24V", "24VDC without power cord"),
         "B": ("DC24V", "24VDC without power cord")}
# 描述文本沿用源表写法（220VAC / 24VDC），库内 power 列用引擎词表（AC220V / DC24V）
POWER_TXT = {"A": "220VAC", "D": "24VDC", "B": "24VDC"}
BRACKET = {"1": ("壁挂支架", "wall mount"), "2": ("立杆支架", "pole stand")}


def read_config():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["Sheet1"]

    out, seen = [], set()

    for row in ws.iter_rows(values_only=True):
        code = next((str(c).strip() for c in row
                     if c and re.fullmatch(r"FT230[A-Z0-9]{6}", str(c).strip())), None)
        desc = next((str(c).strip() for c in row
                     if c and str(c).strip().startswith("FT230,")), None)

        if code and desc and code not in seen:
            seen.add(code)
            out.append((code, desc))

    return out


def clean_zh(desc):
    """配置说明 -> 库内描述：去掉型号前缀，收敛空格，补品牌后缀"""
    text = desc.split(",", 1)[1].strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。；：）])", r"\1", text)
    text = re.sub(r"([（，；])\s+", r"\1", text)
    text = text.rstrip("；; ")

    if not text.endswith("flintec"):
        text += "；品牌：flintec"

    return text


def build_en(code):
    func = code[7]
    bracket = code[9]
    power = code[10]

    parts = [
        "Stainless steel analog indicator",
        "ex-proof Ex ec IIC T6/Ex tc IIIC T85℃ Dc",
        "stainless steel casing",
        "no battery",
        "LCD display",
    ]

    if FUNC_EN[func]:
        parts.append(FUNC_EN[func])

    parts.append("RS232+RS485(MODBUS-RTU)")
    parts.append(POWER[power][1])
    parts.append(BRACKET[bracket][1])

    if power == "B":
        parts.append("with battery connector, battery excluded")

    return ", ".join(parts) + "; Brand: flintec"


def build_zh(code):
    func = code[7]
    bracket = code[9]
    power = code[10]

    parts = [
        "不锈钢外壳模拟仪表",
        "防爆Ex ec IIC T6/Ex tc IIIC T85℃ Dc",
        "不锈钢外壳",
        "无电池",
        "LCD显示",
    ]

    if FUNC_ZH[func]:
        parts.append(FUNC_ZH[func])

    parts.append("RS232+RS485(MODBUS-RTU)")
    parts.append(POWER_TXT[power] + "无电源线")
    parts.append(BRACKET[bracket][0])

    if power == "B":
        parts.append("带电池接口，电池另配")

    return "，".join(parts) + "；品牌：flintec"


def build_db_row(code):
    func, bracket, power = code[7], code[9], code[10]

    return [
        "FT", "FT-230", "230", code,
        "RTU_2",
        COM2[func],
        "电池接口" if power == "B" else "无电池",
        "中文",
        "二区防爆",
        BRACKET[bracket][0],
        POWER[power][0],
        "IICT6",
        "不锈钢外壳",
        "A",
    ]


def rewrite(csv_path, is_db, configs):
    encoding = "utf-8" if is_db else "utf-8-sig"
    lineterm = "\r\n"

    with open(csv_path, encoding=encoding, newline="") as f:
        rows = list(csv.reader(f))

    head, body = rows[0], rows[1:]
    key = (lambda r: r[3]) if is_db else (lambda r: r[2])

    old_idx = [i for i, r in enumerate(body)
               if len(r) > 3 and key(r).startswith("FT230N")]

    if not old_idx:
        raise SystemExit("未找到 FT230N 现有行，终止")

    at = old_idx[0]
    kept = [r for i, r in enumerate(body) if i not in set(old_idx)]

    if is_db:
        new = [build_db_row(code) for code, _ in configs]
    else:
        new = [["FT", "FT-230", code, build_zh(code), build_en(code)]
               for code, _ in configs]

    out = [head] + kept[:at] + new + kept[at:]

    with open(csv_path, "w", encoding=encoding, newline="") as f:
        csv.writer(f, lineterminator=lineterm).writerows(out)

    print("{}: {} 行 -> {} 行（替换 {} 为 {}）".format(
        os.path.basename(csv_path), len(rows), len(out), len(old_idx), len(new)))


def main():
    configs = read_config()

    if len(configs) != 28:
        raise SystemExit("配置表条数异常：{}".format(len(configs)))

    rewrite(CSV_DB, True, configs)
    rewrite(CSV_DESC, False, configs)


if __name__ == "__main__":
    main()
