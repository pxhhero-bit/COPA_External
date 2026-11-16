"""型号规格基准：把描述通表里该型号的「标准描述」抽成可比对的中间产物.

动机（用户拍板）：内容一致性不再靠一条条写规则去对齐写法，而是
    型号 --查描述通表(详细型号)--> 标准描述 --归一--> 基准
    报价行描述                  --同一套归一--> 声明集
两边比对，缺项与冲突自然浮现。规则只剩数值类（量程/台面/分度值/算术）。

数据来源只有一处：`data/description/*.csv` 的 **详细型号 → 描述** 两列。
不读任何结构化编码列（power/com_3/材质码/防爆位/信号协议码）——那些是选型
用的内部编码，拿它跟中文描述对表只会制造误报。描述通表本身就是这个型号
「对外该怎么说」的权威答案，直接比它最省事。

覆盖不到型号（如 FTBR 台秤，通表没有秤体）就不建基准，该行走原有数值规则
（L3/L4/L7/L15 + L24 供电），不猜、不误报。

**不落盘**：它是通表的派生结果，通表一改就必须重算，存一份 JSON 只会多一个
要维护、可能过期的文件（以前叫 model_snapshots.json，673KB，还要靠 CSV 的
mtime 指纹判断是否失效）。现在只在进程内缓存，进程退出即释放，永远和通表
一致。
"""
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from COPA.apps.audit import claims as C
from COPA.apps.audit.model import (KIND_ACCESSORY, KIND_BENCH,
                                   KIND_INSTRUMENT, KIND_JBOX, KIND_MODULE,
                                   KIND_PLATFORM, KIND_UNKNOWN)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_ROOT, "data")

# 每类机型参与快照比对的字段。量程/台面/分度值不在此列——它们继续由
# L3/L4/L15 按业务口径判（台面码换算、分度值单位、建议型号），快照判不了那么细。
COMPARE_KEYS = {
    KIND_MODULE: (C.K_SENSOR_MTL, C.K_MODULE_MTL, C.K_PULL_ROD),
    KIND_BENCH: (C.K_SCALE_MTL, C.K_EX),
    KIND_PLATFORM: (C.K_SCALE_MTL, C.K_EX),
    KIND_INSTRUMENT: (C.K_POWER, C.K_BATTERY, C.K_EX, C.K_HOUSING,
                      C.K_MOUNT, C.K_PROTOCOL, C.K_BRACKET, C.K_LANG),
    KIND_JBOX: (C.K_EX,),
    # 过渡板只有材质一件事可说（碳钢/不锈钢），描述通表里就两句话
    KIND_ACCESSORY: (C.K_SCALE_MTL,),
}

# 「漏写就要报」的字段：型号编码已经蕴含、或客户验收必须看到的配置。
# 其余字段只在「写错」时报，不因没写而报——避免把简洁描述当成问题。
MUST_DECLARE = {
    KIND_MODULE: (C.K_SENSOR_MTL, C.K_MODULE_MTL),
    KIND_INSTRUMENT: (C.K_POWER,),
    KIND_BENCH: (C.K_SCALE_MTL,),
    KIND_PLATFORM: (C.K_SCALE_MTL,),
    KIND_ACCESSORY: (C.K_SCALE_MTL,),
}

# 型号蕴含项：漏写属配置与型号不符（红）；其余漏写是信息不全（黄）
MODEL_IMPLIED = (C.K_PULL_ROD, C.K_EX, C.K_POWER)


@dataclass
class Snapshot:
    model: str
    kind: str = KIND_UNKNOWN
    family: str = ""
    std_desc: str = ""                       # 描述通表里的标准描述（原文）
    std_desc_en: str = ""
    brand: str = ""
    attrs: Dict[str, str] = field(default_factory=dict)     # 预留：描述之外的补充
    sources: List[str] = field(default_factory=list)

    def claims(self) -> Dict[str, C.Claim]:
        """快照 -> 声明集。标准描述经同一套归一出键，两边口径天然一致。"""
        out: Dict[str, C.Claim] = {}
        if self.std_desc:
            out.update(C.extract(self.std_desc))
        for key, value in self.attrs.items():
            if not value or key.startswith("_") or key in out:
                continue
            out[key] = C.Claim(key, value, value, -1)
        return out

    def compare_keys(self) -> tuple:
        return COMPARE_KEYS.get(self.kind, ())

    def to_dict(self) -> dict:
        return {"model": self.model, "kind": self.kind, "family": self.family,
                "std_desc": self.std_desc, "std_desc_en": self.std_desc_en,
                "brand": self.brand, "sources": self.sources}

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(model=data.get("model", ""), kind=data.get("kind", KIND_UNKNOWN),
                   family=data.get("family", ""), std_desc=data.get("std_desc", ""),
                   std_desc_en=data.get("std_desc_en", ""),
                   brand=data.get("brand", ""),
                   attrs=dict(data.get("attrs") or {}),
                   sources=list(data.get("sources") or []))

    def summary(self) -> str:
        """一行「标准配置」，报告与 GUI 详情里展示期望值时用"""
        return self.std_desc or "；".join(
            "{}：{}".format(C.KEY_NAMES.get(k, k), v)
            for k, v in self.claims().items())


# ---------------------------------------------------------------------------
# 型号 -> 描述通表行
# ---------------------------------------------------------------------------
def _family_of(row: dict) -> str:
    return (row.get("型号family") or "").split()[0].strip()


def _kind_from_family(family: str) -> str:
    """通表有、结构表没有的型号，按 family 前缀定性（只用于挑比对字段）"""
    fam = (family or "").upper()
    if fam.startswith(("52-", "55-")) or fam.startswith("ML"):
        return KIND_MODULE
    if fam.startswith(("FT-", "FAB", "AW-", "AW", "M2", "M3", "M5", "AWRF")):
        return KIND_INSTRUMENT
    if "接线盒" in family:
        return KIND_JBOX
    if fam.startswith(("FTPD", "FTPE")):
        return KIND_PLATFORM
    if fam.startswith(("FTBR", "AWBR")):
        return KIND_BENCH
    if "过渡板" in (family or ""):
        return KIND_ACCESSORY
    return KIND_UNKNOWN


# 过渡板这类「一行多规格」的写法：详细型号列写 "SS 3t|SS 4.5t|SS 5t|SS 22.5t"，
# 一行覆盖同材质的所有量程段；报价单写的是单个规格 "SS 2.5t"。
# 精确比必然落空（2.5t 这一段本来就不存在，由 L34 另判），但**材质**写在规格
# 前缀上（SS/CS），比「不锈钢材质 / 碳钢材质」这句话只需要这一位。所以按材质
# 兜底：珠海 011226 的下安装过渡板 SS 2.5T 描述写「碳钢材质」，就是这么漏掉的。
_RE_PLATE_SPEC = re.compile(r"^(CS|SS)\s*[\d.]+\s*t$", re.IGNORECASE)


def _variants(name: str) -> List[str]:
    return [part.strip() for part in str(name or "").split("|") if part.strip()]


def _plate_row(descs: dict, text: str) -> Optional[dict]:
    """单个过渡板规格 -> 同材质的那一行表（同规格优先，其次同材质任意规格）"""
    if not _RE_PLATE_SPEC.match(text or ""):
        return None
    code = text.split()[0].upper()
    best = None
    for name, row in descs.items():
        for variant in _variants(name):
            if variant.split()[0].upper() != code:
                continue
            if C._squash(variant) == C._squash(text):
                return row
            best = best or row
    return best


def match_desc(catalog, model: str, prefix_ok: bool = True) -> Optional[dict]:
    """报价单型号 -> 描述通表行。只按「详细型号」匹配，逐级放宽：

    1. 详细型号完全一致；
    2. 去掉空格/横线、统一大小写后一致（FT-210 与 FT210）；
    3. 取空格前的首段型号再试 1、2（`52-30ML CS SB14-3000kg-BH-C3 EX` → `52-30ML`）；
    4. prefix_ok 时同 family 取最长公共前缀（`52-30ML CS SB14-3000kg-BH-C3 EX`
       匹配通表里 `52-30ML CS SB14-3000kg-BH-C3` 这类完整组合行）。

    prefix_ok=False 用于**描述正文里夹带的型号**：那里的写法是完整型号，放宽
    前缀会把族名（FAB3306）配到一个无关配置行（FAB3306D010000D 是 DC24V，
    而实际写的是 FAB3306HX1PN00A = AC220V），凭空造出冲突。
    """
    descs = getattr(catalog, "descs", None) or {}
    text = (model or "").strip()
    if not text or not descs:
        return None

    if text in descs:
        return descs[text]
    key_sq = C._squash(text)
    for name, row in descs.items():
        if C._squash(name) == key_sq:
            return row

    # 一行多规格（"SS 3t|SS 4.5t|SS 5t|SS 22.5t"）：每个规格都是一个可用键
    for name, row in descs.items():
        for variant in _variants(name):
            if C._squash(variant) == key_sq:
                return row

    head = text.split()[0]
    if head != text:
        if head in descs:
            return descs[head]
        head_sq = C._squash(head)
        for name, row in descs.items():
            if C._squash(name) == head_sq:
                return row
    else:
        head_sq = key_sq

    if not prefix_ok:
        return None

    # 同 family 最长前缀：先同 family 精确，再 family 为首段前缀（52-30M ⊃ 52-30ML）
    exact, loose = [], []
    for name, row in descs.items():
        fam_sq = C._squash(_family_of(row))
        if not fam_sq:
            continue
        if fam_sq == head_sq:
            exact.append((name, row))
        elif head_sq.startswith(fam_sq):
            loose.append((name, row))
    best, best_score = None, 0
    for name, row in exact or loose:
        cand = C._squash(name)
        common = 0
        for a, b in zip(key_sq, cand):
            if a != b:
                break
            common += 1
        if common > best_score:
            best, best_score = row, common
    if best is not None and best_score >= len(head_sq):
        return best
    # 过渡板：表里只有「同材质各量程段」的合并行，按材质兜底
    return _plate_row(descs, text)


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------
def build(catalog, model: str, prefix_ok: bool = True) -> Optional[Snapshot]:
    """型号 -> 快照。描述通表里找不到该型号就返回 None——不猜、不误报。"""
    row = match_desc(catalog, model, prefix_ok=prefix_ok)
    if row is None:
        return None

    family = _family_of(row)
    kind = catalog.lookup(model).kind if model else KIND_UNKNOWN
    if kind in (KIND_UNKNOWN, ""):
        kind = _kind_from_family(family)
    if kind == KIND_UNKNOWN:
        return None                    # 配件（电缆/立杆/预埋框）：没有可比字段

    return Snapshot(
        model=(model or "").strip(),
        kind=kind,
        family=family,
        std_desc=(row.get("描述") or "").strip(),
        std_desc_en=(row.get("描述EN") or "").strip(),
        brand=(row.get("品牌") or "").strip(),
        sources=["描述通表"],
    )


# ---------------------------------------------------------------------------
# 进程内缓存（不落盘）
# ---------------------------------------------------------------------------
_MEM: Dict[str, Optional[Snapshot]] = {}


def get(catalog, model: str) -> Optional[Snapshot]:
    """型号 -> 规格基准；通表里没有该型号时返回 None。

    None 也缓存：同一份报价单里同型号经常重复出现，反复跑 match_desc 没必要。
    """
    key = (model or "").strip()

    if not key:
        return None

    if key not in _MEM:
        _MEM[key] = build(catalog, key)

    return _MEM[key]


def clear() -> None:
    """丢弃进程内缓存；通表热更新后调用，正常使用不需要"""
    _MEM.clear()


def all_models(catalog) -> List[str]:
    """通表里可建基准的型号 = 全部详细型号 + 各自的 family。

    台秤/平台秤的组合空间大且通表未收录，不预生成（get() 现算即返回 None）。
    """
    out = []
    descs = getattr(catalog, "descs", None) or {}
    for name, row in descs.items():
        if name:
            out.append(name.strip())
        family = _family_of(row)
        if family:
            out.append(family)
    return sorted({m for m in out if m})


__all__ = ["Snapshot", "COMPARE_KEYS", "MUST_DECLARE", "MODEL_IMPLIED",
           "build", "get", "clear", "match_desc", "all_models"]
