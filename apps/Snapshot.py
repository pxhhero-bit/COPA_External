"""COPA_com_Snapshot, 项目快照导出 by Hero Pang.
文件 -> 保存(Ctrl+S)：把当前项目的完整状态落成 snapshot/ 下的 markdown：
Desk 卡片录入字段、engine 需求格式参数(engine_input，与 EngineService
实际计算入参同构)，以及选型清单(Checklist)的客户信息与输出项目数据。
首次保存由上层弹对话框指定命名，之后覆盖同一文件；保存时间戳写入文档头，
随时可覆盖保存。本模块只做采集与渲染，文件命名/路径记忆归 Commander。
"""
import json
import os
import re
import sys
from datetime import datetime

from COPA.apps.Desk import build_engine_input
from COPA.apps.version import APP_RELEASE_DATE, APP_VERSION

# 快照目录随部署形态定位(与 engine 的 data 目录同一约定)：冻结打包后
# snapshot 随 exe 同目录摆放；源码运行时按本文件位置上溯到包根
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SNAPSHOT_DIR = os.path.join(_ROOT_DIR, "snapshot")

# engine_input 四组参数的渲染顺序与中文说明(组键即 engine 入参键)
_ENGINE_GROUPS = (
    ("module_data", "module_data（模块/秤体参数）"),
    ("metrology", "metrology（计量参数）"),
    ("com", "com（通讯参数）"),
    ("hardware", "hardware（硬件参数）"),
)


def snapshot_dir():
    """快照默认目录（snapshot/），不存在时惰性创建"""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    return SNAPSHOT_DIR


def suggest_path(project_id):
    """首次保存的默认路径：snapshot/ 下「项目ID_保存时刻.md」"""
    return os.path.join(
        snapshot_dir(),
        "{}_{}.md".format(project_id, datetime.now().strftime("%Y%m%d_%H%M%S"))
    )


def save_snapshot(path, project_id, desk, checklist=None, created_at=None):
    """采集当前项目完整状态并写入 markdown 快照；返回实际写入路径。
    created_at 为首次保存时间文本(None 时与本次保存时间相同)，由上层记忆"""
    markdown = build_markdown(project_id, desk, checklist, created_at)
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    # utf-8-sig：带 BOM 便于记事本/Excel 正确识别中文
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(markdown)

    return path


def build_markdown(project_id, desk, checklist=None, created_at=None):
    """Desk + Checklist 当前状态 -> 完整快照 markdown 文本（不落盘）"""
    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entries = desk.collect_entries()
    states = checklist.dump_state() if checklist is not None else None

    lines = [
        "# COPA 项目快照：{}".format(project_id),
        "",
        _table([
            ("项目名称", project_id),
            ("公司名称", _customer_field(checklist, "editCompanyName")),
            ("联系人", _customer_field(checklist, "editContactPerson")),
            ("首次保存时间", created_at or saved_at),
            ("本次保存时间", saved_at),
            ("条目数", len(entries)),
            ("现场服务（整单）", _checkbox_of(desk, "serviceCheckBox")),
            ("选型清单", "已生成（{} 项）".format(len(states))
             if states is not None else "未生成"),
            ("工具版本", "COPA {} ({})".format(APP_VERSION, APP_RELEASE_DATE)),
        ]),
        "",
        "## 一、需求录入参数（Desk）",
        "",
    ]

    if not entries:
        lines += ["（无卡片条目）", ""]

    for entry in entries:
        lines += _entry_section(entry)

    lines += _checklist_section(checklist, states)
    return "\n".join(lines)


# ====Desk 需求录入段====

def _entry_section(entry):
    """单张卡片条目：录入字段 + engine 需求格式参数（解析仅作构建入参，不落文）"""
    quote_info = entry.get("quote_info", {})
    lines = [
        "### 条目 {}".format(quote_info.get("quote_id", "?")),
        "",
        _table([
            ("数量", quote_info.get("quantity")),
            ("条目类型", entry.get("item_type")),
            ("需要检定", entry.get("metrology")),
            ("高精度", entry.get("high_precision")),
            ("防爆要求", entry.get("Ex_P")),
            ("数字化方案", entry.get("digital")),
        ]),
        "",
        "**需求描述**",
        "",
    ]

    desc = (entry.get("description") or "").strip()

    if desc:
        lines += ["> {}".format(l) for l in desc.splitlines()]
    else:
        lines.append("> （空）")

    lines += ["", "**Engine 需求格式参数（engine_input）**", ""]

    try:
        engine_input = build_engine_input(entry)
    except Exception as err:
        lines += ["无法生成：{}".format(err), ""]
        return lines

    for key, caption in _ENGINE_GROUPS:
        rows = list((engine_input.get(key) or {}).items())
        lines += ["**{}**".format(caption), "", _table(rows), ""]

    return lines


# ====Checklist 选型清单段====

def _checklist_section(checklist, states):
    """清单整单状态 + 逐条目的输出项目 JSON；states 为 None 表示清单未生成"""
    lines = ["## 二、选型清单（Checklist）", ""]

    if states is None:
        lines += ["尚未生成选型清单（该项目还未完成选型计算）。", ""]
        return lines
    lines += [
        _table([
            ("清单条目数", len(states)),
            ("现场服务", _checkbox_of(checklist, "serviceCheckBox_1")),
            ("报价抬头", _combo_of(checklist, "titalComBox")),
            ("输出语言", _combo_of(checklist, "langComBox")),
            ("是否已输出报价", bool(getattr(checklist, "output_completed", False))),
        ]),
        "",
    ]

    for st in states:
        lines += [
            "### 条目 {}（{} × {}）".format(
                st.get("quote_id", "?"), st.get("type", "?"), st.get("qty", "?")),
            "",
            _table([
                ("需要检定", st.get("metrology")),
                ("高精度", st.get("high_precision")),
                ("防爆", st.get("ex")),
                ("数字化", st.get("digital")),
            ]),
            "",
        ]

        project = st.get("item")

        if project is not None:
            lines += [
                "```json",
                json.dumps(project, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]

        warnings = st.get("warnings") or []

        if warnings:
            lines += ["警告："] + ["- {}".format(w) for w in warnings] + [""]

    return lines


# ====渲染辅助====

def _checkbox_of(widget, attr):
    """只读复选框状态；控件缺失(旧Ui)时返回 None 占位"""
    box = getattr(widget, attr, None)
    return box.isChecked() if box is not None else None


def _customer_field(checklist, attr):
    """清单上的客户信息栏(公司名称/联系人)文本：清单未生成时无处采集，
    给说明占位；控件缺失(旧Ui)返回 None，栏位未填写给（未填写）"""
    if checklist is None:
        return "（选型清单未生成）"

    widget = getattr(checklist, attr, None)

    if widget is None:
        return None

    text = widget.toPlainText().strip()
    return text if text else "（未填写）"


def _combo_of(widget, attr):
    """下拉当前文本；控件缺失(旧Ui)时返回 None 占位"""
    combo = getattr(widget, attr, None)
    return combo.currentText() if combo is not None else None


def _cell(value):
    """单元格文本转义：竖线与换行是 markdown 表格的结构字符，须内联化"""
    return _fmt(value).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def _fmt(value):
    """参数值的可读化：布尔转是/否，容器转顿号列举，None/空给占位说明"""
    if value is None:
        return "（未提供）"

    if isinstance(value, bool):
        return "是" if value else "否"

    if isinstance(value, dict):
        return "`{}`".format(json.dumps(value, ensure_ascii=False, default=str))

    if isinstance(value, (list, tuple)):
        return "、".join(_fmt(v) for v in value) if value else "（空）"

    text = str(value).strip()
    return text if text else "（空）"


def _table(rows):
    """(参数, 值) 序列 -> markdown 表格；空序列给占位避免悬空标题"""
    if not rows:
        return "（无）"

    lines = ["| 参数 | 值 |", "| --- | --- |"]
    lines += ["| {} | {} |".format(_cell(k), _cell(v)) for k, v in rows]
    return "\n".join(lines)


# ====快照解析(「打开快照」恢复)====

# 客户信息/空值占位单元格：恢复时一律视为未提供
_PLACEHOLDERS = ("（未填写）", "（选型清单未生成）", "（未提供）", "（空）")

_TYPE_LINE = "### 条目"
_DESC_MARK = "**需求描述**"


def parse_snapshot(path):
    """快照 markdown -> 结构化数据(「打开快照」恢复用)。解析与
    build_markdown 的渲染格式强耦合：小节按标题定位，表格按'|'行解析，
    条目确认数据取```json围栏；无法识别的行静默跳过(尽量多恢复)，
    文件不可读时上抛。返回：
    {project_id, company, contact, onsite_service, entries,
     checklist: None 或 {title, lang, onsite_service, items}}"""
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    data = {
        "project_id": "",
        "company": "",
        "contact": "",
        "onsite_service": False,
        "entries": [],
        "checklist": None,
    }
    meta = {"title": "", "lang": "", "onsite_service": False}
    items = []
    section = None
    current = None
    i = 0
    total = len(lines)

    while i < total:
        stripped = lines[i].strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("# COPA 项目快照："):
            data["project_id"] = stripped.split("：", 1)[1].strip()
            i += 1
            continue

        if stripped.startswith("## 一、") or stripped.startswith("## 二、"):
            section = "desk" if stripped.startswith("## 一、") else "checklist"
            current = None
            i += 1
            continue

        if section is not None and stripped.startswith(_TYPE_LINE):
            title = stripped[len(_TYPE_LINE):].strip()
            current = {
                "quote_id": _lead_int(title),
                "metrology": False, "high_precision": False,
                "ex": False, "digital": False,
            }

            if section == "desk":
                current.update({"item_type": "", "quantity": 1,
                                "description": ""})
                data["entries"].append(current)
            else:
                items.append(current)

            i += 1
            continue

        if stripped.startswith("```json"):
            buf = []
            i += 1

            while i < total and lines[i].strip() != "```":
                buf.append(lines[i])
                i += 1

            if current is not None and buf:
                try:
                    current.update(json.loads("\n".join(buf)))
                except ValueError:
                    pass   # 围栏内容损坏：跳过该块，其余照常恢复

            i += 1
            continue

        if stripped.startswith("|"):
            rows, i = _parse_table(lines, i)
            _absorb_rows(data, meta, section, current, rows)
            continue

        if stripped == _DESC_MARK and section == "desk" and current is not None:
            i += 1

            while i < total and not lines[i].strip():   # 跳过标记与引用块间空行
                i += 1

            desc = []

            while i < total and lines[i].startswith(">"):
                desc.append(_unquote(lines[i]))
                i += 1

            text = "\n".join(desc)
            current["description"] = "" if text == "（空）" else text
            continue

        i += 1

    if items or meta["title"] or meta["lang"] or meta["onsite_service"]:
        # 客户信息(公司名称/联系人)随清单meta一起下发：输入框就在清单上
        data["checklist"] = dict(meta, items=items,
                                 company=data["company"],
                                 contact=data["contact"])

    return data


def _parse_table(lines, i):
    """从 lines[i] 起解析一张 '| 参数 | 值 |' 表 -> ([(k, v)], 下一行下标)；
    表头分隔行须为 '| --- |'，单元格内转义的'\\|'不作为列分隔"""
    total = len(lines)

    if (i + 1 >= total
            or not lines[i + 1].strip().startswith("| ---")):
        return [], i + 1

    i += 2
    rows = []

    while i < total and lines[i].strip().startswith("|"):
        inner = lines[i].strip().strip("|")
        cells = [c.strip().replace("\\|", "|")
                 for c in re.split(r"(?<!\\)\|", inner)]

        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))

        i += 1

    return rows, i


def _absorb_rows(data, meta, section, current, rows):
    """表格行按上下文吸收：文件头元信息 / Desk卡片字段 / 清单整单状态 /
    清单条目状态；无关行忽略"""
    for key, value in rows:
        if section is None and current is None:
            if key == "公司名称":
                data["company"] = _clean_placeholder(value)
            elif key == "联系人":
                data["contact"] = _clean_placeholder(value)
            elif key == "现场服务（整单）":
                data["onsite_service"] = _to_bool(value)
        elif section == "desk" and current is not None:
            if key == "数量":
                current["quantity"] = _to_int(value)
            elif key == "条目类型":
                current["item_type"] = value
            elif key == "需要检定":
                current["metrology"] = _to_bool(value)
            elif key == "高精度":
                current["high_precision"] = _to_bool(value)
            elif key == "防爆要求":
                current["Ex_P"] = _to_bool(value)
            elif key == "数字化方案":
                current["digital"] = _to_bool(value)
        elif section == "checklist" and current is None:
            if key == "现场服务":
                meta["onsite_service"] = _to_bool(value)
            elif key == "报价抬头":
                meta["title"] = value
            elif key == "输出语言":
                meta["lang"] = value
        elif section == "checklist" and current is not None:
            if key == "需要检定":
                current["metrology"] = _to_bool(value)
            elif key == "高精度":
                current["high_precision"] = _to_bool(value)
            elif key == "防爆":
                current["ex"] = _to_bool(value)
            elif key == "数字化":
                current["digital"] = _to_bool(value)


def _lead_int(text):
    """标题文本前导整数(条目号)：「3（平台秤 × 2）」-> 3"""
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else 0


def _to_bool(text):
    return (text or "").strip() == "是"


def _to_int(text, default=1):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _clean_placeholder(text):
    text = (text or "").strip()
    return "" if text in _PLACEHOLDERS else text


def _unquote(line):
    """剥掉引用块前缀：「> 文本」->「文本」"""
    text = line[1:]
    return text[1:] if text.startswith(" ") else text
