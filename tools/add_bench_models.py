"""补台秤通表缺失的量程×台面组合(可重复执行，已存在则跳过)。

本次补两类(依据客户实单 广州兰达机电不锈钢防爆台秤报价单_261027.xlsx)：
  12kg @ 300x400  —— 实单 FTBR-HS-012-3040，分度值 2g(6000e)
  60kg @ 600x800  —— 实单 FTBR-HS-060-6080，分度值 10g(6000e)
按既有命名与分组规律生成 品牌(FT/AW) × 材质(C/S/HC/HS) × 防爆(0/1) 共 32 行：
电子台秤(C/S) 按 3000e 取分度值，高精度电子台秤(HC/HS) 按 6000e。
型批型号沿用 TCS-{量程}kg / TCS-{量程}kg EX。
"""
import csv
import os
import re
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "台秤通表.csv")

# (kg量程, 台面尺寸, 三位量程码, 台面尺寸码, 电子台秤分度值g, 高精度分度值g)
NEW_COMBOS = [
    (12, "300x400", "012", "3040", 4, 2),
    (60, "600x800", "060", "6080", 20, 10),
]
MATERIALS = [("C", "电子台秤", 0), ("S", "电子台秤", 0),
             ("HC", "高精度电子台秤", 1), ("HS", "高精度电子台秤", 1)]
BRANDS = ["FT", "AW"]


def build_rows(cap, deck, code, deck_code, g_std, g_high):
    rows = []

    for brand in BRANDS:
        for ex in (0, 1):
            for material, kind, high in MATERIALS:
                model = "{}BR-{}-{}-{}{}".format(
                    brand, material, code, deck_code, "-E" if ex else "")
                rows.append([
                    model,
                    "TCS-{}kg{}".format(cap, " EX" if ex else ""),
                    brand, str(cap), deck, material, kind, str(ex),
                    str(g_high if high else g_std),
                ])

    return rows


def row_key(row):
    return row[0]


def main():
    with open(PATH, "r", encoding="utf-8", newline="") as f:
        lines = [r for r in csv.reader(f)]

    header, body = lines[0], lines[1:]
    existing = {r[0] for r in body}
    inserted = 0

    for cap, deck, code, deck_code, g_std, g_high in NEW_COMBOS:
        new_rows = [r for r in build_rows(cap, deck, code, deck_code,
                                          g_std, g_high)
                    if row_key(r) not in existing]

        if not new_rows:
            continue

        for brand in BRANDS:
            brand_rows = [r for r in new_rows if r[2] == brand]
            plain = [r for r in brand_rows if r[7] == "0"]
            ex_rows = [r for r in brand_rows if r[7] == "1"]
            same_cap = [i for i, r in enumerate(body)
                        if r[0].startswith("{}BR-".format(brand))
                        and r[0].split("-")[2] == code]

            if same_cap:
                # 已有同量程(如 60kg 其他台面)：非防爆插在防爆块之前，
                # 防爆行接在同量程末条防爆行之后(先插靠后的 EX，避免索引漂移)
                first_ex = next(i for i in same_cap if body[i][7] == "1")
                last_ex = max(i for i in same_cap if body[i][7] == "1")
                body[last_ex + 1:last_ex + 1] = ex_rows
                body[first_ex:first_ex] = plain
            else:
                # 新增量程(如 12kg)：整块插在同品牌下一量程之前
                next_cap = {12: "015", 60: "150"}[cap]
                anchor = next(i for i, r in enumerate(body)
                              if r[0].startswith("{}BR-".format(brand))
                              and r[0].split("-")[2] == next_cap)
                body[anchor:anchor] = plain + ex_rows

            inserted += len(brand_rows)

        existing.update(row_key(r) for r in new_rows)

    with open(PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(body)

    print("新增台秤型号 {} 行，通表现共 {} 行".format(inserted, len(body)))


if __name__ == "__main__":
    main()
