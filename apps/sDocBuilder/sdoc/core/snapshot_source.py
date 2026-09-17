# -*- coding: utf-8 -*-
"""sDocBuilder 快照适配层：项目信息来源。

CopaSnapshotSource 自含解析 COPA 快照 md（只读，不依赖 COPA 包），
只提取技术文档需要的参数——项目头（名称/公司/联系人/时间）、逐条目
需求字段与 engine 参数、选型清单 JSON（型号组合/量程分度/通讯电源）。
"""
import json
import os
import re

from dataclasses import dataclass, field

_MD_TABLE_SEP = re.compile(r"^\|[\s:\-|]+\|$")

_TYPE_CN = {"module": "称重模块", "platform": "平台秤", "bench": "台秤"}


@dataclass
class Entry:
    quote_id: int
    item_type: str            # module/platform/bench
    quantity: int
    metrology: bool = False
    high_precision: bool = False
    ex: bool = False
    digital: bool = False
    description: str = ""
    engine: dict = field(default_factory=dict)      # module_data/com/hardware/metrology
    selection: dict = field(default_factory=dict)   # 选型清单 JSON（原样）
    families: list = field(default_factory=list)    # [(family_key, 状态)] 型号匹配结果

    @property
    def type_cn(self):
        return _TYPE_CN.get(self.item_type, self.item_type or "")

    def module_data(self, key, default=""):
        return (self.engine.get("module_data") or {}).get(key, default) or default


@dataclass
class ProjectInfo:
    project_id: str = ""
    company: str = ""
    contact: str = ""
    entries: list = field(default_factory=list)
    saved_at: str = ""
    onsite_service: bool = False
    title_brand: str = ""       # 报价抬头（COPA B/COPA A）
    lang: str = "中文"
    source_path: str = ""


class SnapshotSource:
    def default_project(self):
        raise NotImplementedError

    def open(self, path):
        raise NotImplementedError


def _tables_and_json(text):
    """快照 md -> (表格单元格流[(section, entry_id, cells)], json块流[(entry_id, dict)])"""
    lines = text.splitlines()
    section, entry_id = "", None
    tables, jsons = [], []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if line.startswith("# COPA 项目快照："):
            section = "header"
        elif line.startswith("## 一、"):
            section = "desk"
        elif line.startswith("## 二、"):
            section = "checklist"
            entry_id = None          # 清单整单状态表不属于任何条目
        elif line.startswith("### 条目"):
            m = re.match(r"^###\s*条目\s*(\d+)", line)
            entry_id = int(m.group(1)) if m else None
        elif line.startswith("|") and i + 1 < n \
                and _MD_TABLE_SEP.match(lines[i + 1].strip()):
            rows = []
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip()
                         for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            tables.append((section, entry_id, rows))
            continue
        elif line.startswith("```json"):
            buf = []
            i += 1
            while i < n and lines[i].strip() != "```":
                buf.append(lines[i])
                i += 1
            try:
                jsons.append((entry_id, json.loads("\n".join(buf))))
            except ValueError:
                pass
        i += 1
    return tables, jsons


def _to_bool(text):
    return (text or "").strip() == "是"


def _to_int(text, default=1):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _clean(text):
    t = (text or "").strip()
    return "" if t in ("（未提供）", "（未填写）", "（空）") else t


class CopaSnapshotSource(SnapshotSource):
    """真实快照读取（只读）"""

    def open(self, path):
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        tables, jsons = _tables_and_json(text)

        project = ProjectInfo(source_path=os.path.abspath(path))
        entries = {}
        by_id_json = {qid: obj for qid, obj in jsons if qid is not None}

        for section, entry_id, rows in tables:
            if section == "header":
                for cells in rows:
                    k, v = cells[0], cells[1] if len(cells) > 1 else ""
                    if k == "项目名称":
                        project.project_id = _clean(v)
                    elif k == "公司名称":
                        project.company = _clean(v)
                    elif k == "联系人":
                        project.contact = _clean(v)
                    elif k == "本次保存时间":
                        project.saved_at = _clean(v)
                    elif k == "现场服务（整单）":
                        project.onsite_service = _to_bool(v)
                    elif k == "选型清单" and "未生成" in v:
                        project.title_brand = ""
            elif section == "checklist" and entry_id is None:
                for cells in rows:
                    k, v = cells[0], cells[1] if len(cells) > 1 else ""
                    if k == "报价抬头":
                        project.title_brand = _clean(v)
                    elif k == "输出语言":
                        project.lang = _clean(v)
                    elif k == "现场服务":
                        project.onsite_service = _to_bool(v) \
                            or project.onsite_service
            elif entry_id is not None:
                e = entries.setdefault(entry_id, Entry(
                    quote_id=entry_id, item_type="", quantity=1))
                if section == "desk":
                    for cells in rows:
                        k, v = cells[0], cells[1] if len(cells) > 1 else ""
                        if k == "数量":
                            e.quantity = _to_int(v)
                        elif k == "条目类型":
                            e.item_type = {"称重模块": "module",
                                           "平台秤": "platform",
                                           "台秤": "bench"}.get(v, v)
                        elif k == "需要检定":
                            e.metrology = _to_bool(v)
                        elif k == "高精度":
                            e.high_precision = _to_bool(v)
                        elif k == ("防爆要求" if section == "desk" else "防爆"):
                            e.ex = _to_bool(v)
                        elif k in ("数字化方案", "数字化"):
                            e.digital = _to_bool(v)
                # engine_input 组标题行 -> 后续表挂到对应组
        # engine_input 组表：靠内容识别（组内首列是已知参数键）
        for section, entry_id, rows in tables:
            if section != "desk" or entry_id is None:
                continue
            e = entries.setdefault(entry_id, Entry(
                quote_id=entry_id, item_type="", quantity=1))
            joined = {r[0]: (r[1] if len(r) > 1 else "")
                      for r in rows if r}
            if "item_type" in joined:
                group = {"group": "module_data", **joined}
                e.engine["module_data"] = group
            elif "req_com1" in joined:
                e.engine["com"] = {"group": "com", **joined}
            elif "install" in joined:
                e.engine["hardware"] = {"group": "hardware", **joined}
            elif "metrology" in joined:
                e.engine["metrology"] = {"group": "metrology", **joined}
            elif "需求描述" in joined:
                pass

        # 需求描述（desk 条目标题后的引用块）单独抓
        entries = self._absorb_descriptions(text, entries)

        for qid in sorted(entries):
            e = entries[qid]
            e.selection = by_id_json.get(qid, {})
            if e.selection:
                e.quantity = _to_int(e.selection.get("qty"), e.quantity)
                e.ex = bool(e.selection.get("ex", e.ex))
                e.digital = bool(e.selection.get("digital", e.digital))
                t = e.selection.get("type")
                if t:
                    e.item_type = t
            e.families = []          # 由 LibraryStore.match_entry 填充
            project.entries.append(e)
        return project

    @staticmethod
    def _absorb_descriptions(text, entries):
        """需求描述：desk 段「**需求描述**」后的引用块"""
        section = ""
        entry_id = None
        capture = False
        buf = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("## "):
                # 段落切换：上一捕获中的描述先落账
                if capture and entry_id in entries:
                    entries[entry_id].description = "\n".join(buf).strip()
                section = s
                entry_id, capture, buf = None, False, []
                continue
            if s.startswith("### 条目"):
                # 上一条目的描述先落账
                if capture and entry_id in entries:
                    entries[entry_id].description = "\n".join(buf).strip()
                m = re.match(r"^###\s*条目\s*(\d+)", s)
                entry_id = int(m.group(1)) if m else None
                capture, buf = False, []
                continue
            if s == "**需求描述**" and section.startswith("## 一、"):
                capture, buf = True, []
                continue
            if capture and s.startswith(">"):
                buf.append(s.lstrip("> ").strip())
        if capture and entry_id in entries:
            entries[entry_id].description = "\n".join(buf).strip()
        return entries

    def default_project(self):
        return ProjectInfo(project_id="（未打开快照）")


class MockSnapshotSource(SnapshotSource):
    """占位项目（启动默认/调试用）：无条目，打开真实快照后替换"""

    def default_project(self):
        return ProjectInfo(
            project_id="示例项目 (1)",
            company="（占位客户公司）",
            contact="（占位联系人）",
            saved_at="",
        )
