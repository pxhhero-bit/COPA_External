"""批阅编排：QuoteDoc -> Report.

只做三件事：跑检查、给未识别行补 L10、把规则版本带上。
不放任何判定逻辑——判定全部在 checks/ 里，方便单测逐条打靶。
"""
import os
from typing import List, Optional

from COPA.apps.audit import mark, pno
from COPA.apps.audit.checks import (blockqty, extras, header, plate,
                                    run_checks, snapqty)
from COPA.apps.audit.checks.arith import check, check_formulas, check_summary
from COPA.apps.audit.db import Catalog
from COPA.apps.audit.model import LEVEL_RED, LEVEL_YELLOW, QuoteDoc, Report
from COPA.apps.audit.reader import read_quote
from COPA.apps.audit.rules import get_rules


def audit_doc(doc: QuoteDoc, catalog: Optional[Catalog] = None) -> Report:
    catalog = catalog or Catalog.get()
    rules = get_rules()

    if not doc._l10_done:
        for row in doc.unrecognized:
            doc.file_issues.append(rules.issue(
                "L10", message="第 {} 行无法归类（{}）".format(row.row, row.reason),
                expected="明细行 / 项目段 / 小计合计", actual=row.text[:80],
                anchor=(row.row, 1)))
        doc._l10_done = True

    # 人工改动识别（mark.py）：批阅副本里带了快照，型号对不上就认定人改过，
    # 该行不再校验选型是否正确（override 不需要交互），只留一条说明。
    # 数量单独走 L28/L29：型号变了只免选型，不免数量。
    state = getattr(doc, "_copa_state", None)
    changes = mark.compare_doc(doc, state) if state else {}
    block_issues = blockqty.check_doc(doc, rules)      # L29 段内数量 vs 支点数
    plate_issues = plate.check_doc(doc, rules)         # L34 过渡板规格 vs 模块
    header_issues = header.check_doc(doc, catalog, rules)  # L35-L38 抬头基线
    extra_issues, extra_file = extras.check_doc(doc, catalog, rules)
    # L32 电缆长度 / L33 传感器型号（行级）、L30/L31 电池（文件级）
    for item in doc.items:
        change = changes.get((item.sheet, item.row))
        if change is not None and change.model_changed:
            item.issues = list(check(item, catalog, rules) or [])
            item.issues.append(rules.issue(
                "L27",
                message="本行型号相对批阅快照有变动（{}），视为人工确认，不再校验选型是否正确".format(
                    change.text),
                expected="如需重新校验，请用原始报价单批阅",
                actual=change.text,
                anchor=item.cells.get("model") or (item.row, 1)))
        else:
            item.issues = run_checks(item, catalog, rules)
        # L23 是电池校验的旧版简化口径；extras 已按整单给出 L30/L31，同一件事
        # 不再报两条（兰达 261027：明明写了「配防爆电池*2，充电器*1」还报 L23）
        if any(i.code in ("L30", "L31") for i in extra_file):
            item.issues = [i for i in item.issues if i.code != "L23"]
        item.issues.extend(snapqty.check(item, change, rules))
        item.issues.extend(block_issues.get((item.sheet, item.row), ()))
        item.issues.extend(plate_issues.get((item.sheet, item.row), ()))
        item.issues.extend(extra_issues.get((item.sheet, item.row), ()))

    # 套数合计行：不是明细行，问题记在文件级，锚点落在它的数量格上
    for total in doc.qty_totals:
        doc.file_issues.extend(snapqty.check_total(
            total, changes.get((total.sheet, total.row)), rules))

    doc.file_issues.extend(extra_file)                 # L30/L31 电池（整单判断）
    doc.file_issues.extend(header_issues)              # L35-L38 条目抬头基线

    # D 段算术（两层）：a 层公式作用域（L18）+ b 层独立核算（L17），均文件级
    doc.file_issues.extend(check_formulas(doc, rules))
    doc.file_issues.extend(check_summary(doc, rules))

    _notice_empty(doc, rules)
    _collapse_blank_template(doc, rules)
    return Report(doc=doc, rules_version=rules.version)


def _notice_empty(doc: QuoteDoc, rules) -> None:
    """一条明细都没读出来时必须说话（L39）。

    reader 认不出表头就整页跳过，这是刻意的（用户要求不做表头校验）。但
    「跳过」和「这份单没问题」是两码事：不给提示，用户看到 0 问题会以为单子
    干净，实际上一个格子都没读到——这是审计工具最危险的失败方式。
    通用报价模版 2.0（需求表+数据表+描述表+sheet）就踩在这里：需求表里明明
    写着主产品型号与量程，却因为版式认不出而全单零问题。
    """
    if doc.items or doc.suspect_template:
        return
    sheets = "、".join(doc.sheets[:3]) if doc.sheets else "（无工作表）"
    doc.file_issues.append(rules.issue(
        "L39",
        message="未识别到任何明细行（工作表：{}）".format(sheets),
        expected="明细表表头含 序号/名称/型号规格、描述/单位/数量/单价/总价",
        actual="没有可读明细，本单未被实际批阅",
        anchor=None))


def _collapse_blank_template(doc: QuoteDoc, rules) -> None:
    """空白模板收敛：绝大多数明细行都只是「未填型号」（L1M）且没有任何
    红级问题时，这是空白模板而不是真实报价单——逐行轰炸 30 条黄毫无意义
    （用户反馈）。清掉逐行问题，换成一条文件级提示；GUI/CLI 据此跳过批阅副本。"""
    items = doc.items
    if len(items) < 5:
        return
    l1m_rows = [it for it in items
                if it.active_issues and
                all(i.code == "L1M" for i in it.active_issues)]
    if any(i.level == LEVEL_RED for it in items for i in it.active_issues):
        return                              # 有红级问题就不是空白模板，照常逐行报
    if len(l1m_rows) < max(5, int(len(items) * 0.8)):
        return                              # 未填型号的行不够多，视为正常单据
    for item in l1m_rows:
        item.issues = []
    doc.suspect_template = True
    doc.file_issues.append(rules.issue(
        "L1M",
        message="{} 行明细中 {} 行均未填型号与描述，疑似空白模板，未逐行批阅".format(
            len(items), len(l1m_rows)),
        expected="填写型号与描述后再批阅",
        actual="空白模板",
        anchor=(items[0].row, items[0].cells.get("model", (0, 1))[1])))


def is_blank_template(report: Report) -> bool:
    """GUI/CLI 判断：该报告是否来自空白模板（不生成批阅副本）"""
    return bool(getattr(report.doc, "suspect_template", False))


def attach_baseline(doc: QuoteDoc):
    """挂上「人工改动」比对基线，返回 State 或 None。

    唯一来源：文件里那串白字项目号 -> 项目快照的出单记录（pno.state）。
    取不到（外部单、首次批阅、项目快照被删）就退回「型号 vs 描述」比对，不算错。
    """
    state = None

    if doc.project_no:
        state = pno.state(doc.project_no)

        if state is None:
            doc.notes.append(
                "项目号 {} 未在项目快照中找到出单记录，本次按「型号 vs 描述」比对".format(
                    doc.project_no))

    doc._copa_state = state
    return state


def audit_file(path: str, catalog: Optional[Catalog] = None) -> Report:
    catalog = catalog or Catalog.get()
    doc = read_quote(path, catalog)
    attach_baseline(doc)
    return audit_doc(doc, catalog)


def audit_files(paths: List[str], catalog: Optional[Catalog] = None) -> List[Report]:
    catalog = catalog or Catalog.get()
    return [audit_file(p, catalog) for p in paths]


def summarize(report: Report) -> str:
    """一行摘要，CLI 与 GUI 共用：'3 红 / 1 黄 / 8 通过'"""
    counts = report.item_counts
    if report.passed:
        return "{} 行全部通过".format(len(report.doc.items))
    return "{} 红 / {} 黄 / {} 通过".format(
        counts[LEVEL_RED], counts[LEVEL_YELLOW], counts["clean"])


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
