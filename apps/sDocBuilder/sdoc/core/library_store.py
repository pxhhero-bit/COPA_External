# -*- coding: utf-8 -*-
"""sDocBuilder 库适配层：候选池数据来源。

统一块内容模型（Mock/Real 共用）：BlockDef.items 为有序内容项——
  ("text", str)                     语料段落（"## "前缀=子标题）
  ("image", (abs_path, caption))    图片（含题注；路径不存在→渲染占位框）
  ("table", {"rows":…, "caption":…}) 表格

RealLibraryStore 索引 COPA/library（2026-09 人工审阅版约定）：
  <类目>/<family>/{features.md, params_*.csv|md, form_*.csv, img_*.png|jpeg,
                   general.md=资产清单(属性+题注)}
  _global/<Name>/{若干内容md（按文件名成块）, form/params csv, 独立图片}
ref 编码：fam:<family>:<blockid> / glob:<Name>:<blockid>
"""
import csv
import os
import re

from dataclasses import dataclass, field

# 块类别（决定池图标/标签与渲染分支）
FEATURES, PARAMS, FORM, IMAGES, TEXT = (
    "features", "params", "form", "images", "text")

KIND_LABEL = {
    FEATURES: "特点", PARAMS: "参数表", FORM: "表格",
    IMAGES: "图片", TEXT: "文本",
}

_MD_TABLE_SEP = re.compile(r"^\|[\s:\-|]+\|$")
# 纯「行x列」尺寸备注（如 28x7）：是表格规模信息而非标题/题注
_DIM_NOTE = re.compile(r"\d+\s*[x×]\s*\d+")


@dataclass
class BlockDef:
    kind: str                       # FEATURES/PARAMS/FORM/IMAGES/TEXT
    title: str
    items: list = field(default_factory=list)
    ref: str = ""                   # 全库唯一引用（构建时填）
    # 统计（构建时算好，预览用）
    n_images: int = 0
    n_missing: int = 0

    def _recount(self):
        self.n_images = sum(1 for k, p in self.items if k == "image"
                            and os.path.exists(p[0]))
        self.n_missing = sum(1 for k, p in self.items if k == "image"
                             and not os.path.exists(p[0]))

    def n_tables(self):
        return sum(1 for k, _ in self.items if k == "table")

    def n_paras(self):
        return sum(1 for k, _ in self.items if k == "text")


@dataclass
class Family:
    key: str
    title: str
    category: str
    brand: str
    blocks: list = field(default_factory=list)


def _read_manifest(folder):
    """general.md（旧 entry.md）-> (属性dict, {文件名: 说明})。

    md 表格 = 表头行 + 分隔行 + 数据行：分隔行行首恒为 "---"，表类型
    只能按其前一行（表头行）首格是否「资产文件」判定（旧实现看分隔行
    自身首格，永远判不中，导致说明列整体失效）；数据行紧随分隔行，
    属性表收 meta、资产表收 文件名->说明。"""
    meta, captions = {}, {}
    for name in ("general.md", "entry.md"):
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            continue
        table = None                  # 当前表类型，由表头行首格定性
        header_first = None           # 最近一行竖线文本的首格
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.rstrip("\n").strip()
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if _MD_TABLE_SEP.match(line):
                    table = ("assets" if header_first == "资产文件"
                             else "props") if header_first else None
                    continue
                first = cells[0] if cells else ""
                if table == "props" and len(cells) >= 2 \
                        and first != "资产文件":
                    meta[first] = cells[1]
                elif table == "assets" and len(cells) >= 3 \
                        and first not in ("", "资产文件"):
                    if not _DIM_NOTE.fullmatch(cells[2]):
                        captions[first] = cells[2]
                header_first = first
        break
    return meta, captions


def _parse_md_lines(path, base_dir, captions):
    """features/内容 md -> items：文本段落 / 图片 / md表格行"""
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = f.read().splitlines()
    i, n = 0, len(raw)
    while i < n:
        line = raw[i].strip()
        if not line:
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)", line)
        if m:
            cap, fname = m.group(1).strip(), m.group(2).strip()
            items.append(("image", (os.path.join(base_dir, fname),
                                    cap or captions.get(fname, ""))))
            i += 1
            continue
        m = re.match(r"^（(?:参数表|表格)：([^）]+)）$", line)
        if m:                           # 语料里的表格标记 -> 内联为真表格
            tf = os.path.join(base_dir, m.group(1).strip())
            if os.path.exists(tf) and tf.lower().endswith(".csv"):
                items.append(("table", _parse_csv_table(tf)))
                i += 1
                continue
        if line.startswith("|") and i + 1 < n \
                and _MD_TABLE_SEP.match(raw[i + 1].strip()):
            rows = []
            while i < n and raw[i].strip().startswith("|"):
                if not _MD_TABLE_SEP.match(raw[i].strip()):
                    cells = [c.strip()
                             for c in raw[i].strip().strip("|").split("|")]
                    rows.append(cells)
                i += 1
            items.append(("table", {"rows": rows, "caption": ""}))
            continue
        if line.startswith("#") and not line.startswith("##"):
            line = line.lstrip("# ").strip()     # 单#为文档标题行，剥前缀
        items.append(("text", line))             # "## " 保留：语料小节信号
        i += 1
    return items


def _parse_csv_table(path, caption=""):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [row for row in csv.reader(f) if any(c.strip() for c in row)]
    table = {"rows": rows, "caption": caption}
    if rows and "归属公司" in rows[0]:
        table["filter"] = "归属公司"   # 内部归属标签：渲染时按抬头筛行并删列
    return table


def _standalone_images(folder, captions, referenced):
    """未被任何 md 引用的图片 -> [("image", (path, cap)), ...]"""
    out = []
    for name in sorted(os.listdir(folder)):
        low = name.lower()
        if not low.endswith((".png", ".jpg", ".jpeg")):
            continue
        if name in referenced:
            continue
        out.append(("image", (os.path.join(folder, name),
                              captions.get(name, os.path.splitext(name)[0]))))
    return out


class LibraryStore:
    """候选池接口"""

    def categories(self):
        raise NotImplementedError

    def block(self, ref):
        raise NotImplementedError

    def block_title(self, ref):
        """块的展示标题：family 块返回型号名，全局块返回文件/清单名，
        条目配置块返回固定名"""
        if ref.startswith("entry:"):
            return "选型配置与技术参数"
        if ref.startswith("fam:"):
            key = ref.split(":")[1]
            for _, fams in self.categories():
                for f in fams:
                    if f.key == key:
                        return f.title
            return ref
        b = self.block(ref)
        return b.title if b else ref

    def first_family_key(self, category):
        """某类目的第一个 family key（默认模板铺底用）"""
        for cat, fams in self.categories():
            if cat == category and fams:
                return fams[0].key
        return None

    def family_by_key(self, key):
        for _, fams in self.categories():
            for f in fams:
                if f.key == key:
                    return f
        return None


class RealLibraryStore(LibraryStore):
    """索引真实 COPA/library 目录（人工审阅版约定）"""

    CAT_DIRS = [("load_cell", "传感器"), ("module", "称重模块"),
                ("controller", "仪表"), ("jbox", "接线盒"), ("cable", "电缆")]
    GLOBAL_DIR = "_global"
    # 型号关键词 -> 变体后缀候选（CSV 反查失败时的编码猜测回退）
    VAR_HINTS = [("隔爆式", ("EX", "EXD")),
                 ("防尘式", ("DR", "FANGCHEN")), ("导轨式", ("DIN", "RAIL"))]
    # 仪表 CSV「安装方式」值 -> library 变体后缀（反查真值映射）
    CSV_VAR_MAP = {"面板式": "面板式", "防尘式": "防尘式", "导轨式": "导轨式",
                   "隔爆": "隔爆式", "隔爆式": "隔爆式",
                   "二区防爆": "二区防爆式", "台式": "台式"}

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._blocks = {}          # ref -> BlockDef
        self._cats = []            # [(类目名, [Family])]
        self._base_index = {}
        self._build()

    # ----构建----

    def _build(self):
        for rel, label in self.CAT_DIRS:
            base = os.path.join(self.root, rel)
            if not os.path.isdir(base):
                continue
            entries = []
            for name in sorted(os.listdir(base)):
                folder = os.path.join(base, name)
                if os.path.isdir(folder):
                    fam = self._build_family(name, folder, label)
                    if fam.blocks:
                        entries.append(fam)
            if entries:
                self._cats.append((label, entries))
        gbase = os.path.join(self.root, self.GLOBAL_DIR)
        if os.path.isdir(gbase):
            entries = []
            for name in sorted(os.listdir(gbase)):
                folder = os.path.join(gbase, name)
                if not os.path.isdir(folder):
                    continue
                fam = self._build_global(name, folder)
                if fam.blocks:
                    entries.append(fam)
            if entries:
                self._cats.append(("全局", entries))
        # 型号匹配索引：base(归一化) -> [family keys]（同 base 多变体全收）
        self._base_index = {}
        for _, fams in self._cats:
            for f in fams:
                if f.category == "全局":
                    continue
                base = self._norm(self._split_variant(f.key)[0])
                if not base:
                    continue
                self._base_index.setdefault(base, []).append(f.key)
        self._instr_csv = self._load_instr_csv_index()

    def _build_family(self, key, folder, cat_label):
        meta, captions = _read_manifest(folder)
        fam = Family(key, meta.get("型号") or key,
                     meta.get("类别") or cat_label, meta.get("品牌", ""))
        referenced = set()
        fpath = os.path.join(folder, "features.md")
        if os.path.exists(fpath):
            items = _parse_md_lines(fpath, folder, captions)
            for k, p in items:
                if k == "image":
                    referenced.add(os.path.basename(p[0]))
            blk = BlockDef(FEATURES, "特点", items,
                           ref="fam:{}:features".format(key))
            blk._recount()
            fam.blocks.append(blk)
            self._blocks[blk.ref] = blk
        for stem, blk in self._table_blocks(key, folder, captions):
            fam.blocks.append(blk)
            self._blocks[blk.ref] = blk
        img_items = _standalone_images(folder, captions, referenced)
        if img_items:
            blk = BlockDef(IMAGES, "图片", img_items,
                           ref="fam:{}:images".format(key))
            blk._recount()
            fam.blocks.append(blk)
            self._blocks[blk.ref] = blk
        return fam

    def _build_global(self, name, folder):
        _, captions = _read_manifest(folder)
        fam = Family("glob:" + name, name, "全局", "")
        referenced = set()
        for fname in sorted(os.listdir(folder)):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath) or fname in ("general.md",
                                                      "entry.md"):
                continue
            low = fname.lower()
            stem = os.path.splitext(fname)[0]
            ref = "glob:{}:{}".format(name, stem)
            if low.endswith(".md"):
                items = _parse_md_lines(fpath, folder, captions)
                for k, p in items:
                    if k == "image":
                        referenced.add(os.path.basename(p[0]))
                kind = FEATURES if any(k == "table" for k, _ in items) \
                    else TEXT
                blk = BlockDef(kind, stem, items, ref=ref)
                blk._recount()
                fam.blocks.append(blk)
                self._blocks[ref] = blk
            elif low.endswith(".csv"):
                kind = FORM if low.startswith("form_") else PARAMS
                cap = captions.get(fname, "")       # 无说明不给 caption
                blk = BlockDef(kind, cap or stem,
                               [("table", _parse_csv_table(fpath, cap))],
                               ref=ref)
                blk._recount()
                fam.blocks.append(blk)
                self._blocks[ref] = blk
        img_items = _standalone_images(folder, captions, referenced)
        if img_items:
            blk = BlockDef(IMAGES, "图片", img_items,
                           ref="glob:{}:images".format(name))
            blk._recount()
            fam.blocks.append(blk)
            self._blocks[blk.ref] = blk
        return fam

    def _table_blocks(self, key, folder, captions):
        """params_*.csv / params_*.md / form_*.csv -> [(stem, BlockDef)]"""
        blocks = []
        for fname in sorted(os.listdir(folder)):
            low = fname.lower()
            if not (low.startswith("params") or low.startswith("form_")):
                continue
            fpath = os.path.join(folder, fname)
            cap = captions.get(fname, "")
            stem = os.path.splitext(fname)[0]
            ref = "fam:{}:{}".format(key, stem)
            if low.endswith(".csv"):
                kind = FORM if low.startswith("form_") else PARAMS
                blocks.append((stem, BlockDef(
                    kind, cap or stem,
                    [("table", _parse_csv_table(fpath, cap))], ref=ref)))
            elif low.endswith(".md"):
                items = _parse_md_lines(fpath, folder, captions)
                tables = [p for k, p in items if k == "table"]
                if tables:
                    blocks.append((stem, BlockDef(
                        PARAMS, cap or stem,
                        [("table", dict(t, caption=cap or stem))
                         for t in tables], ref=ref)))
        return blocks

    # ----查询----

    def categories(self):
        return list(self._cats)

    def block(self, ref):
        return self._blocks.get(ref)

    @staticmethod
    def _norm(text):
        return re.sub(r"[\s\-_]", "", (text or "")).upper()

    @staticmethod
    def _split_variant(key):
        """family key -> (base, 变体或"")；仅当"-"后是中文才是变体
        （52-30M 是型号内连字符，不拆）"""
        m = re.match(r"^([^-]+)-([\u4e00-\u9fff].*)$", key)
        return (m.group(1), m.group(2)) if m else (key, "")

    def match_family_all(self, model):
        """型号串 -> 全部命中 family key（按 base 长度降序）。
        模块串（如 "52-30M CS SLB-2268kg"）可同时命中模块与传感器。"""
        m = self._norm(model)
        if not m:
            return []
        hits = []
        for base, keys in self._base_index.items():
            if base in m:
                hits.append((len(base), keys))
        out = []
        for ln, keys in sorted(hits, key=lambda x: -x[0]):
            for k in keys:
                if k not in out:
                    out.append(k)
        return out

    def match_family(self, model):
        """选型型号串 -> 最可能的 family key。
        变体判定优先级：仪表 CSV 反查（真值）> 编码猜测 > 字典序首个。"""
        key, _basis = self.match_family_basis(model)
        return key

    def match_family_basis(self, model):
        """同 match_family，另返回判定依据：
        "csv"=仪表CSV反查真值 / "guess"=编码推断 / "single"=唯一变体 /
        (None, None)=未命中"""
        hits = self.match_family_all(model)
        if not hits:
            return None, None
        key = hits[0]
        base, _ = self._split_variant(key)
        keys = self._base_index.get(self._norm(base), [key])
        if len(keys) == 1:
            return key, "single"
        m = self._norm(model)
        # 1) 仪表 CSV 反查：快照型号即引擎从该表选出，反查安装方式为真值
        row = self._instr_csv.get(m)
        if row:
            var = self.CSV_VAR_MAP.get(row.get("安装方式", ""))
            cand = "{}-{}".format(base, var) if var else None
            if cand and cand in keys:
                return cand, "csv"
        # 2) 编码猜测回退
        for var, kws in self.VAR_HINTS:
            if any(self._norm(kw) in m for kw in kws):
                cand = "{}-{}".format(base, var)
                if cand in keys:
                    return cand, "guess"
        return sorted(keys)[0], "guess"

    def _load_instr_csv_index(self):
        """COPA/data/*仪表*.csv -> {归一化model_full: 行dict}（按表头名取列）"""
        import glob as _glob

        index = {}
        data_dir = os.path.normpath(os.path.join(self.root, "..", "data"))
        for path in _glob.glob(os.path.join(data_dir, "*仪表*.csv")):
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        full = (row.get("model_full") or "").strip()
                        if full:
                            index[self._norm(full)] = row
            except Exception:
                continue
        return index

    def match_entry(self, entry):
        """条目选型结果 -> [(family_key, 来源)] 去重（顺序保留）"""
        sel = entry.selection or {}
        candidates = []
        module = sel.get("module")
        if isinstance(module, (list, tuple)) and module:
            candidates.append((module[0], "模块/传感器"))
        elif isinstance(module, str) and module:
            candidates.append((module, "模块/传感器"))
        for key, label in (("platform", "平台秤"), ("bench", "台秤"),
                           ("jbox", "接线盒"), ("controller", "仪表"),
                           ("display", "大屏幕")):
            v = sel.get(key)
            if isinstance(v, str) and v:
                candidates.append((v, label))
        out, seen = [], set()

        def add(key, label):
            if key and key not in seen:
                seen.add(key)
                out.append((key, label))

        for model, label in candidates:
            add(self.match_family(model), label)
            if label == "模块/传感器":      # 模块串内含传感器等附加型号
                for key in self.match_family_all(model):
                    add(key, label)
        return out


class MockLibraryStore(LibraryStore):
    """占位库（library 缺失时回退/调试用）"""

    def __init__(self):
        self._blocks = {}

        def fam(key, title, cat, brand, kinds, n_img=0):
            blocks = []
            for k in kinds:
                if k == FEATURES:
                    blk = BlockDef(FEATURES, "特点", [
                        ("text", "（占位语料）{}：高精度、长期稳定性好。".format(title)),
                        ("text", "（占位语料）防护等级 IP68。"),
                    ], ref="fam:{}:features".format(key))
                elif k == PARAMS:
                    blk = BlockDef(PARAMS, "参数表", [
                        ("table", {"rows": [["参数", "值"],
                                            ["量程", "（占位）227/454/3000 kg"],
                                            ["精度等级", "（占位）C3 / C6"]],
                                   "caption": ""}),
                    ], ref="fam:{}:params".format(key))
                elif k == IMAGES:
                    blk = BlockDef(IMAGES, "图片",
                                   [("image", ("::missing::{}-{}".format(key, i),
                                               "占位图{}".format(i + 1)))
                                    for i in range(n_img)],
                                   ref="fam:{}:images".format(key))
                else:
                    blk = BlockDef(TEXT, "文本", [("text", "（占位）")],
                                   ref="fam:{}:text".format(key))
                blk._recount()
                blocks.append(blk)
                self._blocks[blk.ref] = blk
            return Family(key, title, cat, brand, blocks)

        self._fams = [
            fam("SB14", "SB14 称重传感器", "传感器", "富林泰克",
                [FEATURES, PARAMS, IMAGES], n_img=2),
            fam("52-30M", "52-30M 称重模块", "称重模块", "富林泰克",
                [FEATURES, PARAMS]),
            fam("M30", "M30 称重模块附件", "称重模块附件", "COPA A",
                [FEATURES]),
            fam("FAB330", "FAB330 称重显示控制器", "仪表", "富林泰博",
                [FEATURES, PARAMS]),
            fam("AWJX-005D", "AWJX-005D 防爆接线盒", "接线盒", "COPA A",
                [FEATURES]),
            fam("AWG", "AWG 信号电缆", "电缆", "富林泰克", [FEATURES]),
        ]
        g = Family("glob:公司介绍", "公司介绍", "全局", "")
        for stem, text in (("富林泰克", "（占位）FLINTEC Group 创立于 1969 年……"),
                           ("COPA B", "（占位）COPA B Co., Ltd.……")):
            blk = BlockDef(TEXT, stem, [("text", text)],
                           ref="glob:公司介绍:{}".format(stem))
            blk._recount()
            g.blocks.append(blk)
            self._blocks[blk.ref] = blk
        self._fams.append(g)
        self._cats = self._categories()

    def _categories(self):
        order = ["传感器", "称重模块", "称重模块附件", "仪表", "接线盒", "电缆", "全局"]
        out = []
        for cat in order:
            fams = [f for f in self._fams if f.category == cat]
            if fams:
                out.append((cat, fams))
        return out

    def categories(self):
        return list(self._cats)

    def block(self, ref):
        return self._blocks.get(ref)
