"""型号命名解析：归一化、编码表（从通表现推）、旧码等价与现行型号建议.

设计底线：**码表不写死在代码里**。台面码 4050 -> 400x500、容量段 060 -> 60kg
这类对应关系全部由 data/*.csv 的「具体型号 ↔ 量程/台面」配对反推，并同时反推
出各系列的编码倍率（台秤容量码 x1、平台秤 x100；台秤台面码 x10、平台秤 x100）。
新增系列或改码后无需改代码，只要通表里成对存在即可。

这样做的直接好处：旧码 0405（=04|05，x10 -> 400x500）能自动等价到现行 4050，
而 006（=6kg）不会被"修正"成 060（=60kg）——因为两者解码结果不同，量程不等价
才是真错误，编码写法不同只是过期。
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# 全角/异体符号统一（NFKC 已处理大部分，这里补工程上常见的写法）
_SYMBOL_MAP = str.maketrans({
    "（": "(", "）": ")", "【": "[", "】": "]",
    "＊": "*", "×": "x", "✕": "x", "／": "/",
    "－": "-", "—": "-", "–": "-", "＿": "_", "　": " ",
})


def norm(text) -> str:
    """型号归一化：NFKC（全角转半角）+ 符号统一 + 去空白 + 大写.

    只用于比对，不用于展示——展示始终用原文字，避免把用户写的型号改掉。
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).translate(_SYMBOL_MAP)
    return re.sub(r"\s+", "", s).upper()


def as_number(text) -> Optional[float]:
    """'1,500' / '3t' / '60' -> 数字；无法解析返回 None"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def as_size(text) -> Optional[Tuple[int, int]]:
    """'1500x1500mm' / '1500*1500' / '400 × 500' -> (1500, 1500)"""
    if not text:
        return None
    m = re.search(r"(\d{2,5})\s*[*xX×✕]\s*(\d{2,5})", str(text))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


@dataclass
class ModelInfo:
    """一个具体型号解码后的属性。from_table 标记该项是查表命中还是按倍率推算。"""
    raw: str
    parts: List[str] = field(default_factory=list)
    family: str = ""
    material: str = ""
    cap_code: str = ""
    capacity_kg: Optional[float] = None
    cap_from_table: bool = False
    face_code: str = ""
    face_mm: Optional[Tuple[int, int]] = None
    face_from_table: bool = False
    suffix: str = ""
    ex: bool = False

    @property
    def face_text(self) -> str:
        return "{}x{}".format(*self.face_mm) if self.face_mm else ""

    @property
    def capacity_text(self) -> str:
        if self.capacity_kg is None:
            return ""
        return "{}kg".format(int(self.capacity_kg) if self.capacity_kg == int(self.capacity_kg) else self.capacity_kg)


def _majority_int(values: List[float]) -> int:
    """取众数（编码倍率），避免个别脏数据把倍率带偏"""
    if not values:
        return 1
    counts: Dict[int, int] = {}
    for v in values:
        k = int(round(v))
        counts[k] = counts.get(k, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]


class CodeTables:
    """各系列的容量码/台面码码表，从通表现推。

    型号结构约定（仅台秤/平台秤/汽车衡适用）：
        {family}-{material}-{capacity}-{face}-{type}
    例：FTBR-S-060-4050-E  -> family=FTBR material=S capacity=060 face=4050 type=E
        AWPD-C-030-1515-N-D1 -> 多出的一位是配置尾码，不影响前四段语义
    称重模块/仪表/接线盒编码不遵循此结构，不参与解码。
    """

    def __init__(self):
        self._cap: Dict[str, Dict[str, float]] = {}          # family -> {code: kg}
        self._face: Dict[str, Dict[str, Tuple[int, int]]] = {}  # family -> {code: (w,h)}
        self._mtl: Dict[str, Set[str]] = {}                  # family -> {材质段}
        self._cap_mult: Dict[str, int] = {}
        self._face_mult: Dict[str, int] = {}
        self._cap_rev: Dict[str, Dict[float, str]] = {}
        self._face_rev: Dict[str, Dict[Tuple[int, int], str]] = {}
        self._face_set: Dict[str, Set[Tuple[int, int]]] = {}
        self.families: Dict[str, str] = {}                   # family -> kind
        self.samples = 0

    # ---- 建表 -----------------------------------------------------------
    def add(self, kind: str, model: str, capacity, size, material: str) -> bool:
        """用一条通表记录喂表。结构不符（模块/仪表型号）直接忽略。"""
        parts = (model or "").split("-")
        if len(parts) < 4:
            return False
        family, mat, cap, face = parts[0], parts[1], parts[2], parts[3]
        if not (cap.isdigit() and face.isdigit() and len(face) == 4):
            return False
        kg = as_number(capacity)
        mm = as_size(size)
        if kg is None or mm is None:
            return False
        self.families[family] = kind
        self._cap.setdefault(family, {})[cap] = kg
        self._face.setdefault(family, {})[face] = mm
        self._mtl.setdefault(family, set()).add(mat)
        self.samples += 1
        return True

    def finalize(self):
        """推算倍率与反向索引（容量码 <-> kg，台面码 <-> (w,h)）"""
        for family, table in self._cap.items():
            ratios = [kg / int(code) for code, kg in table.items() if int(code or 0) > 0]
            self._cap_mult[family] = _majority_int(ratios) or 1
            self._cap_rev[family] = {}
            for code, kg in sorted(table.items()):
                self._cap_rev[family].setdefault(kg, code)
        for family, table in self._face.items():
            ratios = []
            for code, (w, _h) in table.items():
                head = int(code[:2])
                if head:
                    ratios.append(w / head)
            self._face_mult[family] = _majority_int(ratios) or 10
            self._face_rev[family] = {}
            for code, mm in sorted(table.items()):
                self._face_rev[family].setdefault(mm, code)
            self._face_set[family] = set(table.values())

    # ---- 查询 -----------------------------------------------------------
    def has_family(self, family: str) -> bool:
        return family.upper() in self._cap

    def cap_code_known(self, family: str, code: str) -> bool:
        return code in self._cap.get(family.upper(), {})

    def face_code_known(self, family: str, code: str) -> bool:
        return code in self._face.get(family.upper(), {})

    def face_code_effective(self, family: str, code: str) -> bool:
        """台面码是否为该系列的合法写法——合法组合不要求逐字收录在通表：
          1) 现行码表内（如 FTPD 的 0808）
          2) 旧码按多倍率尝试能落到现行台面（如 4050 -> 400x500）
          3) 6 位 cm 写法（125125 = 125+125 -> 1250x1250mm；边长限 30~320cm，
             拒收 999999 这类随手乱敲的数字）
        供系列级存在性判定用（海斯福案例：030-0808 组合未收录但两段码都合法）。"""
        fam = (family or "").upper()
        if code in self._face.get(fam, {}):
            return True
        if len(code) == 4 and code.isdigit():
            known = self._face_set.get(fam, set())
            mult = self._face_mult.get(fam, 10)
            head, tail = int(code[:2]), int(code[2:])
            for factor in (mult, mult * 10, max(mult // 10, 1)):
                if (head * factor, tail * factor) in known:
                    return True
            return False
        if len(code) == 6 and code.isdigit():
            h1, h2 = int(code[:3]), int(code[3:])
            return 30 <= h1 <= 320 and 30 <= h2 <= 320
        return False

    def cap_code_for(self, family: str, kg: float) -> Optional[str]:
        return self._cap_rev.get(family.upper(), {}).get(float(kg))

    def face_code_for(self, family: str, mm: Tuple[int, int]) -> Optional[str]:
        return self._face_rev.get(family.upper(), {}).get((int(mm[0]), int(mm[1])))

    def capacities(self, family: str) -> List[float]:
        return sorted(set(self._cap.get(family.upper(), {}).values()))

    def faces(self, family: str) -> List[Tuple[int, int]]:
        return sorted(set(self._face.get(family.upper(), {}).values()))

    # ---- 解码 -----------------------------------------------------------
    def decode(self, model: str) -> Optional[ModelInfo]:
        """具体型号 -> 属性。码不在表内时按该系列倍率推算，并标记 from_table=False。"""
        if not model:
            return None
        parts = model.split("-")
        if len(parts) < 4:
            return None
        family = parts[0].upper()
        if family not in self._cap:
            return None

        info = ModelInfo(raw=model, parts=parts, family=family,
                         material=parts[1].upper(), suffix=parts[4].upper() if len(parts) > 4 else "")
        info.cap_code = parts[2]
        info.face_code = parts[3]
        info.ex = info.suffix == "E"

        kg = self._cap[family].get(info.cap_code)
        if kg is not None:
            info.capacity_kg, info.cap_from_table = kg, True
        elif info.cap_code.isdigit():
            info.capacity_kg = float(int(info.cap_code) * self._cap_mult.get(family, 1))

        mm = self._face[family].get(info.face_code)
        if mm is not None:
            info.face_mm, info.face_from_table = mm, True
        elif len(info.face_code) == 6 and info.face_code.isdigit():
            # 6 位写法是 cm 口径：125125 = 125+125 -> 1250x1250mm（报价单里
            # 1250mm 边台的常见写法，通表 4 位码装不下）。先按 cm 解；
            # 边长不在 30~320cm（300~3200mm）内的按乱码处理，不硬解，
            # 让存在性检查去报「未收录」而不是拿 9990x9990 这种荒谬值跑一致性
            head, tail = int(info.face_code[:3]), int(info.face_code[3:])
            if 30 <= head <= 320 and 30 <= tail <= 320:
                known = self._face_set.get(family, set())
                candidates = [(head * 10, tail * 10)]
                mult = self._face_mult.get(family, 10)
                candidates.append((head * mult, tail * mult))
                info.face_mm = next((c for c in candidates if c in known),
                                    candidates[0])
        elif len(info.face_code) == 4 and info.face_code.isdigit():
            head, tail = int(info.face_code[:2]), int(info.face_code[2:])
            mult = self._face_mult.get(family, 10)
            known = self._face_set.get(family, set())
            # 旧码写法不统一：0405 与 4050 是同一块 400x500 台面的两种编码
            # （前导零写法等于把两位数字当 4/5 而不是 40/50）。所以按多个倍率
            # 各解一次，取**能落到现行码表**的那个；都不落地才用首选倍率。
            candidates = [(head * mult, tail * mult)]
            for factor in (mult * 10, max(mult // 10, 1)):
                candidates.append((head * factor, tail * factor))
            info.face_mm = next((c for c in candidates if c in known), candidates[0])

        return info

    def suggest(self, model: str, capacity_kg: Optional[float] = None,
                face_mm: Optional[Tuple[int, int]] = None) -> Optional[str]:
        """按给定容量/台面，把型号改写为现行编码；改不动或未变化返回 None.

        用于 L9（旧码）与 L3/L4（描述与型号冲突时给候选正确型号）的建议值。
        """
        info = self.decode(model)
        if info is None:
            return None
        new_parts = list(info.parts)

        if capacity_kg is not None:
            code = self.cap_code_for(info.family, capacity_kg)
            if not code:
                return None
            new_parts[2] = code
        elif not self.cap_code_known(info.family, info.cap_code):
            return None

        if face_mm is not None:
            code = self.face_code_for(info.family, face_mm)
            if not code:
                return None
            new_parts[3] = code
        elif not self.face_code_known(info.family, info.face_code):
            return None

        candidate = "-".join(new_parts)
        return candidate if candidate != model else None


# ---------------------------------------------------------------------------
# 型号抽取（从「名称/型号」或「型号+描述」合并列里捞出真正的具体型号）
# ---------------------------------------------------------------------------

# 型号候选：允许数字开头（如模块型号 52-30M），段内允许小数点
# （模块量程写法 7.5T——曾因点号把 RC3-7.5T-BH-C3 劈成 RC3-7 + 5T-BH-C3，
# 5T-BH-C3 这个虚构型号还赢了打分），结尾不能落在点上。
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9.])([A-Za-z0-9][A-Za-z0-9.]*(?:[-/][A-Za-z0-9.]+)*)(?<![.])(?![A-Za-z0-9])")

# 明显不是型号的短词（单位/协议/标准/防护等级）
_STOP_TOKENS = {
    "KG", "MM", "PCS", "SET", "EX", "USD", "CNY", "RMB", "LED", "LCD",
    "RS232", "RS485", "RTU", "MODBUS", "PROFINET", "TCP", "UDP", "AC", "DC",
    "C3", "C4", "OIML", "CE", "PVC", "SS", "CS", "POWER", "TYPE", "SUS",
}


def tokenize_models(text: str) -> List[str]:
    """文本 -> 型号候选（保持原文大小写，去重后按出现顺序）

    过滤掉三类噪音：纯数字（400-500 台面尺寸）、单位串（3000kg）、
    防护等级（IP68）——它们长得像型号，但永远不会是型号。
    纯数字多段系列（55-30 这类模块型号）放行，交给 pick_model 查库定夺：
    查库命中才是型号，不命中就是尺寸/数字。
    """
    if not text:
        return []
    out: List[str] = []
    seen: Set[str] = set()
    for raw in _TOKEN_RE.findall(str(text)):
        token = raw.strip(" ./")
        key = norm(token)
        if len(key) < 4 or key in _STOP_TOKENS:
            continue
        if not any(ch.isdigit() for ch in key):
            continue
        if not any(ch.isalpha() for ch in key) and "-" not in key:
            continue
        if re.fullmatch(r"IP\d+[A-Z]*", key):
            continue
        if "-" not in key and not re.fullmatch(r"[A-Z]{2,}[0-9][A-Z0-9]{2,}", key):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def in_parens(text: str, token: str) -> bool:
    """型号是否被括号包着——行业习惯是「名称（具体型号）」，括号内优先级最高"""
    if not text or not token:
        return False
    pattern = r"[\(\[][^\(\)\[\]]{0,20}" + re.escape(token)
    return re.search(pattern, str(text), re.IGNORECASE) is not None


def looks_like_model(token: str) -> bool:
    """松散的语法合法性：至少两段或「字母+数字」混合，长度>=4"""
    key = norm(token)
    if len(key) < 4 or not any(c.isdigit() for c in key):
        return False
    if "-" in key:
        segments = [s for s in key.split("-") if s]
        return len(segments) >= 2 and all(re.fullmatch(r"[A-Z0-9]+", s) for s in segments)
    return re.fullmatch(r"[A-Z]{2,}[0-9][A-Z0-9]{2,}", key) is not None
