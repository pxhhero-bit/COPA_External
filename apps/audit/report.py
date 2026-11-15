"""报告输出：markdown（问题清单）与批阅副本（xlsx 字体标注）.

markdown 是给人看的（发同事/存档），xlsx 副本是给客户单用的（在原件上标出来）。
两者的数据源都是同一个 Report，不存在"报告说 A、文件标 B"的可能。

xlsx 标注采用「字体标注，无底色」（用户拍板的口径）：
  - 严重(红 #C00000) / 提示(橙 #E36C09)：问题字段红色/橙色加粗，只标问题行
  - L7 缺参：描述里插入两空格占位，占位字符红色加粗+下划线，并加批注写明缺什么
  - 富文本 run 不支持 fill（SpreadsheetML 限制），故不使用任何底色
  - 另存后做保真自检（公式/合并/图片/图表），丢失必须告警
"""
import os
import re
from datetime import datetime
from typing import List, Optional

from COPA.apps.audit.model import (LEVEL_RED, LEVEL_YELLOW, Report)

_LEVEL_MARK = {LEVEL_RED: "🔴", LEVEL_YELLOW: "🟡"}


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _cell_text(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _num(value) -> str:
    return str(int(value)) if isinstance(value, float) and value == int(value) else str(value)


def render_markdown(report: Report, annotated_path: Optional[str] = None,
                    generated: Optional[datetime] = None) -> str:
    doc = report.doc
    generated = generated or datetime.now()
    counts = report.item_counts
    lines: List[str] = []

    lines.append("# 报价单批阅报告")
    lines.append("")
    lines.append("- 文件：`{}`".format(os.path.basename(doc.path)))
    lines.append("- 路径：`{}`".format(doc.path))
    lines.append("- 项目号：{}".format(getattr(doc, "project_no", "") or "（未编号）"))
    lines.append("- 批阅时间：{}".format(generated.strftime("%Y-%m-%d %H:%M:%S")))
    lines.append("- 规则版本：{}".format(report.rules_version))
    for note in getattr(doc, "notes", ()):        # 基线来源/失效原因
        lines.append("- 说明：{}".format(note))
    if annotated_path:
        lines.append("- 批阅副本：`{}`".format(annotated_path))
    lines.append("")

    # ---- 结论 ---------------------------------------------------------
    lines.append("## 结论")
    lines.append("")
    if report.passed:
        lines.append("**未发现问题。** {} 行明细全部通过（未识别 0 行）。".format(len(doc.items)))
    else:
        file_count = len([i for i in doc.file_issues if not i.ignored])
        extra = "（含文件级 {} 条）".format(file_count) if file_count else ""
        lines.append("**发现 {} 条问题**：严重 {} 条，提示 {} 条；涉及 {} 行明细{}。".format(
            len(report.active_issues), report.count(LEVEL_RED),
            report.count(LEVEL_YELLOW), counts[LEVEL_RED] + counts[LEVEL_YELLOW], extra))
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|---|---|")
    lines.append("| 明细行 | {} |".format(len(doc.items)))
    lines.append("| 红行（必须改） | {} |".format(counts[LEVEL_RED]))
    lines.append("| 黄行（建议确认） | {} |".format(counts[LEVEL_YELLOW]))
    lines.append("| 通过行 | {} |".format(counts["clean"]))
    lines.append("| 未识别行 | {} |".format(len(doc.unrecognized)))
    lines.append("| 项目段 | {} |".format(len(doc.blocks)))
    lines.append("")

    # ---- 问题一览 ------------------------------------------------------
    flat = _flat(report)          # 只有文件级问题（如 L17/L28）时，别留空表空详情
    if flat:
        lines.append("## 问题一览")
        lines.append("")
        lines.append("| 行 | 名称 / 型号 | 码 | 级别 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for item, issue in flat:
            lines.append("| {} | {} | {} | {} | {} |".format(
                item.row, _cell_text(item.label)[:28], issue.code,
                issue.level_name, _cell_text(issue.message)))
        lines.append("")

        lines.append("## 逐行详情")
        lines.append("")
        for item, issue in flat:
            lines.append("### 第 {} 行 · {} · {}".format(
                item.row, _cell_text(item.label)[:40], item.model or "无型号"))
            lines.append("")
            lines.append("**{} {}（{}）**".format(
                _LEVEL_MARK.get(issue.level, ""), issue.title, issue.level_name))
            lines.append("")
            if issue.message:
                lines.append("- 说明：{}".format(issue.message))
            if issue.expected:
                lines.append("- 期望：{}".format(issue.expected))
            if issue.actual:
                lines.append("- 实际：{}".format(issue.actual))
            if issue.advice:
                lines.append("- 建议：{}".format(issue.advice))
            lines.append("")

    # ---- 文件级问题（汇总算术 / 套数合计 / 公式形态）-------------------
    file_issues = [i for i in doc.file_issues if not i.ignored]
    if file_issues:
        lines.append("## 文件级问题")
        lines.append("")
        lines.append("| 工作表 | 行 | 码 | 级别 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for issue in file_issues:
            row = issue.anchor[0] if issue.anchor else ""
            lines.append("| {} | {} | {} | {} | {} |".format(
                issue.sheet or doc.sheet_of(row), row, issue.code, issue.level_name,
                _cell_text(issue.message or issue.title)))
        lines.append("")

    # ---- 未识别行 ------------------------------------------------------
    if doc.unrecognized:
        lines.append("## 未识别行（需人工确认）")
        lines.append("")
        lines.append("| 工作表 | 行 | 内容 | 原因 |")
        lines.append("|---|---|---|---|")
        for row in doc.unrecognized:
            lines.append("| {} | {} | {} | {} |".format(
                row.sheet, row.row, _cell_text(row.text)[:60], row.reason))
        lines.append("")

    # ---- 通过行 --------------------------------------------------------
    clean = [it for it in doc.items if not it.level]
    if clean:
        lines.append("## 通过行")
        lines.append("")
        for item in clean:
            lines.append("- 第 {} 行 · {} · {}".format(item.row, item.label, item.model))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("由 COPA audit 生成。判定口径：只报「型号与描述两端都能确定且冲突」的问题；"
                 "「未收录」与「不存在」分开计级，避免历史旧码淹没真问题。")
    return "\n".join(lines)


def _flat(report: Report):
    """按 (行, 问题码) 拉平，报告与界面共用同一顺序"""
    out = []
    for item in report.doc.items:
        for issue in item.active_issues:
            out.append((item, issue))
    out.sort(key=lambda pair: (pair[0].row, pair[1].code))
    return out


# ---------------------------------------------------------------------------
# 批阅副本（GUI 依赖 write_annotated_ex；write_annotated 为兼容入口）
# ---------------------------------------------------------------------------

_TS_PREFIX = re.compile(r"^\d{8}_\d{6}_")


def display_stem(path: str) -> str:
    """留存件名 {YYYYMMDD}_{HHMMSS}_{原名} -> 原名 stem（剥时间戳前缀）。

    输出文件名用原名，避免「时间戳前缀 + 时间戳后缀」重复出现；
    直接喂原件（CLI 批量）时无前缀，原样返回。
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    return _TS_PREFIX.sub("", stem, count=1)


def report_filename(path: str, when: Optional[datetime] = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return "{}_诊断报告_{}.md".format(display_stem(path), stamp)


def write_markdown(report: Report, out_dir: str,
                   annotated_path: Optional[str] = None,
                   when: Optional[datetime] = None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    when = when or datetime.now()
    target = os.path.join(out_dir, report_filename(report.doc.path, when))
    with open(target, "w", encoding="utf-8") as f:
        f.write(render_markdown(report, annotated_path, when))
    return target


def annotate_filename(path: str, when: Optional[datetime] = None) -> str:
    """批阅副本命名：剥时间戳前缀用原名，保留原后缀（.xlsm 宏不能丢）"""
    stem, ext = os.path.splitext(os.path.basename(path))
    ext = ext.lower() or ".xlsx"
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return "{}_批阅_{}{}".format(display_stem(stem), stamp, ext)


def write_annotated_ex(report: Report, out_dir: str,
                       when: Optional[datetime] = None):
    """生成批阅副本，返回 AnnotateResult（路径/告警/定位失败/保真数据）。

    GUI 入口：degraded 为真时界面必须提示原件内容未完整保留。
    """
    from COPA.apps.audit.annotate import annotate_workbook_ex
    return annotate_workbook_ex(report, out_dir, when or datetime.now())


def write_annotated(report: Report, out_dir: str,
                    when: Optional[datetime] = None) -> Optional[str]:
    """兼容入口：只返回路径（告警走 warnings，GUI 请用 write_annotated_ex）"""
    from COPA.apps.audit.annotate import annotate_workbook
    return annotate_workbook(report, out_dir, when or datetime.now())


def safe_stem(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(text or "")).strip() or "quote"
