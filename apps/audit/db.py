"""通表查询层：把 data/*.csv 组织成「型号 -> 属性」的判定库.

只做查询，不做任何判断。检查器需要的三件事都在这里：
  1. 这个型号在库里吗（四级：精确 / 归一化 / 型批 / 未收录）
  2. 它是哪个品类（秤体 / 模块 / 仪表 / 接线盒 / 传感器）
  3. 秤体的属性是什么（量程 / 台面 / 材质 / 防爆 / 分度值）

装载口径与 Writer 一致：品牌描述通表三表合并（型号编码不冲突），台秤与平台秤
通表为 FT+AW 合并属性表，仪表表三品牌合并。
"""
import csv
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from COPA.apps.audit.naming import CodeTables, norm
from COPA.apps.audit.model import (KIND_ACCESSORY, KIND_BENCH,
                                   KIND_INSTRUMENT, KIND_JBOX, KIND_MODULE,
                                   KIND_PLATFORM, KIND_UNKNOWN)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_ROOT, "data")

_SENSOR_FILES = ("富林泰克传感器.csv", "COPA A传感器.csv")
_INSTRUMENT_FILES = ("flintec仪表.csv", "alwe仪表.csv", "flintab仪表.csv")
_DESC_FILES = ("description/FT描述通表.csv",
               "description/AW描述通表.csv",
               "description/FAB描述通表.csv")


def read_csv(name: str) -> List[dict]:
    """读 data/ 下的 csv。utf-8-sig 兼容 Excel 另存的 BOM。"""
    path = os.path.join(DATA_DIR, name)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f)]


@dataclass
class Hit:
    """一次型号查询的结果"""
    level: str = "none"          # exact / normalized / typebatch / desc / none
    kind: str = KIND_UNKNOWN
    model: str = ""              # 库里的规范写法（用于展示「期望值」）
    row: Dict[str, str] = field(default_factory=dict)
    source: str = ""             # 命中来源表，便于排查

    @property
    def found(self) -> bool:
        return self.level != "none"


class Catalog:
    """惰性单例式的判定库。构造一次约 30ms，逐文件批阅时复用。"""

    _instance: Optional["Catalog"] = None

    @classmethod
    def get(cls) -> "Catalog":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.benches: Dict[str, dict] = {}
        self.platforms: Dict[str, dict] = {}
        self.modules: Dict[str, dict] = {}
        self.jboxes: Dict[str, dict] = {}
        self.instruments: Dict[str, dict] = {}
        self.instrument_power: Dict[str, str] = {}   # norm(仪表型号) -> 'ac'/'dc'
        self.instrument_battery: set = set()         # 支持电池供电的仪表型号 (norm)
        self.descs: Dict[str, dict] = {}
        self.sensors: Dict[str, dict] = {}
        self.type_batch: Dict[str, Tuple[str, str]] = {}   # norm(型批) -> (kind, 原文)
        self.brands: set = set()                           # 品牌前缀（FT/AW/FAB），数据里现取
        self.model_families: set = set()                   # 型号family（FT-210 这类系列名）
        self.codes = CodeTables()
        self._nindex: Dict[str, Hit] = {}                  # norm型号 -> Hit
        self._load()

    # ---- 装载 -----------------------------------------------------------
    def _load(self):
        for row in read_csv("台秤通表.csv"):
            self.benches[row["具体型号"].strip()] = row
            self.codes.add(KIND_BENCH, row["具体型号"].strip(),
                           row.get("kg量程"), row.get("台面尺寸"),
                           row.get("材质") or "")
            self._add_type_batch(row.get("型批型号"), KIND_BENCH)

        for row in read_csv("平台秤通表.csv"):
            self.platforms[row["具体型号"].strip()] = row
            self.codes.add(KIND_PLATFORM, row["具体型号"].strip(),
                           row.get("kg量程"), row.get("台面尺寸"),
                           row.get("材质") or "")
            self._add_type_batch(row.get("型批型号"), KIND_PLATFORM)

        for row in read_csv("称重模块通表.csv"):
            self.modules[row["module模块型号"].strip()] = row

        for row in read_csv("Jbox通表 (FT+AW).csv"):
            self.jboxes[row["model型号"].strip()] = row

        for name in _INSTRUMENT_FILES:
            for row in read_csv(name):
                self.instruments[row["model_full"].strip()] = row
                power = (row.get("power") or "").strip().upper()
                if power.startswith(("AC", "DC")):
                    self.instrument_power[norm(row["model_full"])] = \
                        "ac" if power.startswith("AC") else "dc"
                # com_3 是电池配置列：「8.4V锂电池」=带电池，「无电池」=不带
                com3 = (row.get("com_3") or "").strip()
                if "电池" in com3 and "无" not in com3:
                    self.instrument_battery.add(norm(row["model_full"]))
                if row.get("brand"):
                    self.brands.add(norm(row["brand"]))
                if row.get("family"):
                    self.model_families.add(norm(row["family"]))

        for name in _DESC_FILES:
            for row in read_csv(name):
                desc = (row.get("描述") or "").strip()
                if row.get("型号family"):
                    self.model_families.add(norm(row["型号family"]))
                for model in (row.get("详细型号") or "").split("|"):
                    model = model.strip()
                    if model:
                        self.descs[model] = dict(row, 描述=desc)

        for name in _SENSOR_FILES:
            for row in read_csv(name):
                key = "{}|{}".format(row.get("family型号", "").strip(),
                                     row.get("capacity容量", "").strip())
                self.sensors[key] = row

        self.codes.finalize()
        self._build_index()

    def _add_type_batch(self, value: Optional[str], kind: str):
        text = (value or "").strip()
        if not text:
            return
        # 型批型号分「TCS-3t」与「TCS-3t EX」两行，两者都收
        self.type_batch[norm(text)] = (kind, text)

    def _build_index(self):
        tables = (
            (self.benches, KIND_BENCH, "台秤通表"),
            (self.platforms, KIND_PLATFORM, "平台秤通表"),
            (self.modules, KIND_MODULE, "称重模块通表"),
            (self.jboxes, KIND_JBOX, "Jbox通表"),
            (self.instruments, KIND_INSTRUMENT, "仪表通表"),
        )
        for table, kind, source in tables:
            for model, row in table.items():
                self._nindex.setdefault(norm(model), Hit("normalized", kind, model, row, source))
        for model, row in self.descs.items():
            key = norm(model)
            if key in self._nindex:
                continue
            self._nindex[key] = Hit("desc", self._kind_from_desc(model, row), model, row, "描述通表")

    @staticmethod
    def _kind_from_desc(model: str, row: dict) -> str:
        """描述通表里的型号品类：先看 family 段是否属于秤体系列，再看型号外观。"""
        family = (row.get("型号family") or "").split("-")[0].strip().upper()
        if family.startswith(("FTBR", "AWBR")):
            return KIND_BENCH
        if family.startswith(("FTPD", "AWPD", "FTPE", "AWPE")):
            return KIND_PLATFORM
        if family.startswith(("FTWD", "AWWD")):
            return KIND_PLATFORM
        if "接线盒" in family or family.startswith("AWJ") or family.startswith("KE"):
            return KIND_JBOX
        # 过渡板：描述通表按「碳钢过渡板 / 不锈钢过渡板」表达，规格是
        # 「CS 5t / SS 5t」这种两段码（命名规则里就没有更细的型号）
        if "过渡板" in family:
            return KIND_ACCESSORY
        return KIND_UNKNOWN

    # ---- 查询 -----------------------------------------------------------
    def lookup(self, model: str) -> Hit:
        """四级判定：精确 -> 归一化 -> 型批 -> 未收录"""
        text = (model or "").strip()
        if not text:
            return Hit()

        for table, kind, source in (
            (self.benches, KIND_BENCH, "台秤通表"),
            (self.platforms, KIND_PLATFORM, "平台秤通表"),
            (self.modules, KIND_MODULE, "称重模块通表"),
            (self.jboxes, KIND_JBOX, "Jbox通表"),
            (self.instruments, KIND_INSTRUMENT, "仪表通表"),
            (self.descs, "desc", "描述通表"),
        ):
            if text in table:
                row = table[text]
                kind_resolved = self._kind_from_desc(text, row) if kind == "desc" else kind
                level = "exact" if kind != "desc" else "desc"
                return Hit(level, kind_resolved, text, row, source)

        key = norm(text)
        hit = self._nindex.get(key)
        if hit is not None:
            return Hit("normalized", hit.kind, hit.model, hit.row, hit.source)

        batch = self.type_batch.get(key)
        if batch is not None:
            return Hit("typebatch", batch[0], batch[1], {}, "型批型号")

        return Hit()

    def scale_row(self, model: str) -> Optional[dict]:
        """秤体属性行（量程/台面/材质/防爆/分度值），非秤体返回 None"""
        return self.benches.get(model) or self.platforms.get(model)

    def desc_of(self, model: str) -> str:
        hit = self.lookup(model)
        return (hit.row.get("描述") or "").strip() if hit.found else ""

    def kind_name(self, model: str) -> str:
        from COPA.apps.audit.model import KIND_NAMES
        return KIND_NAMES.get(self.lookup(model).kind, "")

    def all_models(self) -> List[str]:
        return (list(self.benches) + list(self.platforms) + list(self.modules)
                + list(self.jboxes) + list(self.instruments) + list(self.descs))

    def module_series_hit(self, token: str) -> Optional[str]:
        """模块系列前缀命中：52-30ML -> 52-30M，55-30 -> 55-30。

        模块通表只存基系列，报价单的完整选型串会带变体尾缀（52-30ML 的 L
        即拉杆变体）再接材质/传感器配置。按用户拍板口径「模块型号从描述
        通表里去查」：token 以某个模块系列开头、尾缀是 1~3 个字母即认命中。
        返回命中的系列名，未命中返回 None。
        """
        if not hasattr(self, "_module_series_list"):
            # 长系列优先，防止短系列抢命中（如同时存在 52-30 与 52-30M）
            self._module_series_list = sorted(
                (s for s in self.modules if s), key=len, reverse=True)
        key = norm(token)
        if not key:
            return None
        for series in self._module_series_list:
            s = norm(series)
            if s and key.startswith(s):
                tail = key[len(s):]
                if not tail or re.fullmatch(r"[A-Z]{1,3}", tail):
                    return series
        return None

    def scale_series_hit(self, model: str) -> bool:
        """台秤/平台秤系列级命中（用户拍板，与模块同口径）。

        通表按「系列 × 量程码 × 台面码」配对表达，组合空间远大于收录行数。
        型号结构完整、量程码在码表内、台面码是合法写法（现行码 / 旧码可换算 /
        6 位 cm 写法）即认存在，不再报「未收录」——海斯福案例：
        FTPD-S-030-0808-E 的 030 与 0808 各自合法，只是该组合未逐字收录。
        量程/台面与描述是否相符由 L3/L4 继续把关，这里只回答
        「是不是本系列的正常写法」。
        """
        info = self.codes.decode(model)
        if info is None:
            return False
        if not self.codes.cap_code_known(info.family, info.cap_code):
            return False
        return self.codes.face_code_effective(info.family, info.face_code)

    def sensor_families(self) -> List[str]:
        """传感器系列词表（SLB/SB/…）：判断文本里是否写了传感器型号用。
        sensors 的 key 形如 "SLB|91"，系列取竖线前段"""
        if not hasattr(self, "_sensor_families"):
            self._sensor_families = sorted(
                {key.split("|")[0].strip().upper()
                 for key in self.sensors if key and "|" in key})
        return self._sensor_families
