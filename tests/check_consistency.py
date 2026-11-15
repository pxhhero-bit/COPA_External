# -*- coding: utf-8 -*-
"""报价诊断的「契约一致性」自检：规则、项目号、快照、双端装配、文档口径.

为什么要有这一支
    这几处的一致性靠人记是记不住的：
      - 规则码写在 `config/audit_rules.json`，代码里硬编码引用，手册与总表各写一份；
      - 项目号要同时出现在报价页白字、隐藏快照标题、诊断表、md 报告、本地 json；
      - 界面与 CLI 是两条装配路径，少挂一步基线就会出现「界面不报 L28、CLI 却报」。
    任何一处改动漏了另一半，单看代码都正常，跑起来才发现对不上账。

用法：
    python COPA/tests/check_consistency.py      # 全部通过退出码 0

不检查业务判定是否正确（那是 test_audit 的事），只检查「同一件事在多处是否同一个说法」。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # COPA/
PKG_PARENT = os.path.dirname(ROOT)
for path in (ROOT, PKG_PARENT):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_RETIRED = {"L11"}          # 已下线但代码/文档里仍有历史说明的码
_FAILED = []


def check(name, passed, detail: object = ""):
    print(("  [OK] " if passed else "  [NG] ") + name
          + ("  -> {}".format(detail) if detail else ""))
    if not passed:
        _FAILED.append(name)
    return passed


def _skip(name, reason=""):
    """可选检查（依赖不入库的 aidocs/）缺文件时跳过，不算失败"""
    print("  [SKIP] " + name + ("  -> {}".format(reason) if reason else ""))


def _read(*parts):
    """读文档：先按给的路走，缺了再试 aidocs/。

    aidocs/ 是智能体生成的辅助文档，**不入库**（.gitignore 已排除），只有本机
    才可能有；因此文档类检查用 _read_docs() 读，缺了就跳过而不是当成失败。
    """

    candidates = [os.path.join(ROOT, *parts)]
    if parts and parts[0] == "docs":
        candidates.append(os.path.join(ROOT, "aidocs", *parts[1:]))
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
    raise FileNotFoundError(candidates[-1])


def _read_docs(*parts):
    """读可选文档：不存在返回 None（干净克隆里 aidocs/ 不在，文档检查跳过）"""
    try:
        return _read(*parts)
    except FileNotFoundError:
        return None


def check_rules():
    print("== 1. 规则真源 / 代码 / 文档 三方对齐 ==")
    rules = json.loads(_read("config", "audit_rules.json"))
    codes = set(rules["rules"])
    used = set()
    for dirpath, _, filenames in os.walk(os.path.join(ROOT, "apps")):
        if "pycache" in dirpath:
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                text = open(os.path.join(dirpath, filename), encoding="utf-8",
                            errors="ignore").read()
                used |= set(re.findall(r"\bL\d{1,2}[A-Z]?\b", text))

    manual = _read_docs("docs", "audit-问题码手册.md")
    table = _read_docs("docs", "audit-规则总表.md")
    check("规则条数与代码引用一致", not (codes - used), sorted(codes - used))
    check("代码不引用未定义的码", used - codes <= _RETIRED, sorted(used - codes - _RETIRED))

    if manual is None or table is None:
        _skip("手册/规则总表", "aidocs/ 不入库，本机也没有")
    else:
        check("手册覆盖全部码",
              not (codes - set(re.findall(r"\bL\d{1,2}[A-Z]?\b", manual))),
              sorted(codes - set(re.findall(r"\bL\d{1,2}[A-Z]?\b", manual))))
        check("总表覆盖全部码",
              not (codes - set(re.findall(r"\|\s*(L\d{1,2}[A-Z]?)\s*\|", table))))
        check("版本号三处一致",
              rules["version"] in manual and rules["version"] in table,
              rules["version"])
        check("总表声明真源是配置文件",
              "config/audit_rules.json" in table or "config\\audit_rules.json" in table)
    check("L1T/L1F 判红（缺具体型号按硬伤处理）",
          rules["rules"]["L1T"]["level"] == "red"
          and rules["rules"]["L1F"]["level"] == "red")
    check("抬头四项进规则表", {"L35", "L36", "L37", "L38"} <= codes)

    # 标定量程的区间口径必须与 engine 的规则文件一致，否则审计与出单会各说各话
    selection = json.loads(_read("config", "selection_rules.json"))
    rule = selection["metrology_rules"]["rated_range_rule"]
    from COPA.apps.audit.checks import header
    check("标定量程下限与 engine 一致（≥料重）", bool(rule.get("must_ge_W1")) is True)
    check("标定量程上限与 engine 一致（1.5 倍）",
          abs(float(rule.get("upper_limit_ratio", 0)) - header.RATED_UPPER_RATIO) < 1e-9,
          rule.get("upper_limit_ratio"))


def check_project_no():
    print("== 2. 项目号 / 快照 契约 ==")
    from COPA.apps.audit import mark, pno
    check("号格式 COPA{YYMMDD}-{4位}", pno._RE.pattern == r"COPA\d{6}-\d{4}")
    check("提示语「，勿删」", pno.NOTE == "，勿删")
    check("1 号白字", pno.SIZE == 1 and pno.WHITE == "FFFFFFFF")
    check("标题 = 项目号 · 时间戳",
          mark.snapshot_title("COPA261108-0001", "2026-11-08 14:00:00")
          == "COPA261108-0001 · 2026-11-08 14:00:00")
    check("无号时标题只写时间戳",
          mark.snapshot_title("", "2026-11-08 14:00:00") == "2026-11-08 14:00:00")
    state = mark.State("d", "2026-11-08 14:00:00", [], "x", "COPA261108-0001")
    check("State.title 与标题同格式",
          state.title == "COPA261108-0001 · 2026-11-08 14:00:00")

    # 基线只在项目快照里：报价单与批阅副本都不承载任何内部数据
    source = _read("apps", "audit", "mark.py")
    pno_source = _read("apps", "audit", "pno.py")
    check("快照不再建隐藏工作表", "create_sheet" not in source)
    check("不再读写自定义文档属性", "COPA_SNAPSHOT_" not in source)
    check("基线写进项目快照", "append_order" in pno_source)
    check("批阅按项目号反查基线", "find_order" in pno_source)
    check("型号规格基准不落盘",
          "write_cache" not in _read("apps", "audit", "modelspec.py"))


def check_two_ends():
    print("== 3. 双端（GUI / CLI）装配一致 ==")
    from COPA.apps import Audit
    from COPA.apps.audit import cli
    gui = _read("apps", "Audit.py")
    runner = _read("apps", "audit", "runner.py")
    check("GUI 线程挂了基线", "attach_baseline(doc)" in gui)
    check("CLI 经 audit_file 挂基线", "attach_baseline(doc)" in runner)
    check("输出目录同一路径",
          os.path.normcase(Audit.OUT_DIR) == os.path.normcase(cli.DEFAULT_OUT))
    check("诊断表写项目号", '"项目号"' in _read("apps", "audit", "annotate.py"))
    check("md 报告写项目号", "项目号：" in _read("apps", "audit", "report.py"))
    check("抬头校验已接入 runner",
          "header.check_doc" in runner and "header_issues" in runner)
    check("项目段带工作表（跨表同名段不串）",
          "sheet: str = \"\"" in _read("apps", "audit", "model.py"))


def check_docs():
    print("== 4. 文档口径 ==")
    manual = _read_docs("docs", "audit-问题码手册.md")

    if manual is None:
        _skip("手册口径", "aidocs/ 不入库（智能体生成的辅助文档）")
        return

    check("已写 .xls 支持", "借本机 Excel 转存" in manual)
    check("已写电缆口径（不乘台数）", "不按台数折算总长" in manual)
    check("已写过渡板映射", "过渡板规格（按规则校验" in manual)
    check("已写基线存放位置", "三、出单记录" in manual and "项目快照" in manual)
    check("已写三处同号", "三处必须是同一个号" in manual)
    check("已写双端基线一致性", "基线一致性" in manual)
    check("已写抬头校验口径", "条目抬头（模块段的规格声明）" in manual)
    check("已写快照不进打印区", "不进打印区" in manual)


def main():
    check_rules()
    check_project_no()
    check_two_ends()
    check_docs()
    print()
    if _FAILED:
        print("未通过 {} 项：{}".format(len(_FAILED), "、".join(_FAILED)))
        return 1
    print("一致性检查全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
