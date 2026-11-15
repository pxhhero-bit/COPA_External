"""报价批阅命令行入口.

用法：
    python -m COPA.apps.audit.cli output/xxx.xlsx ref/yyy.xlsx
    python -m COPA.apps.audit.cli --dir "01 COPA A报价"
    python -m COPA.apps.audit.cli -a --dir "01 COPA A报价"   # 附带批阅副本

GUI 走同一套 runner / annotate，不重复实现。
"""
import argparse
import glob
import os
import sys
import time

if __package__ in (None, ""):
    # 直接以脚本方式运行时补项目根目录，使 COPA 包可导入
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from COPA.apps.audit.db import Catalog          # noqa: E402
from COPA.apps.audit.progress import line as progress_line  # noqa: E402
from COPA.apps.audit.report import write_annotated_ex  # noqa: E402
from COPA.apps.audit.runner import (audit_file, is_blank_template,  # noqa: E402
                                    summarize)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "output", "audit")


def collect(paths, dirs):
    files = []
    for path in paths:
        files.append(path)
    for folder in dirs:
        for pattern in ("*.xlsx", "*.xlsm"):
            files.extend(sorted(glob.glob(os.path.join(folder, "**", pattern), recursive=True)))
    # 去重且跳过 Excel 的临时锁文件（~$ 开头）
    seen, out = set(), []
    for path in files:
        abspath = os.path.abspath(path)
        if abspath in seen or os.path.basename(abspath).startswith("~$"):
            continue
        seen.add(abspath)
        out.append(abspath)
    return out


def print_rule_table():
    """把 config/audit_rules.json 摊成一张表，并同步写一份 md 供审核.

    规则只有一处真源（config/audit_rules.json）。这里的输出是给人审核用的
    视图——改了配置，表和文档跟着变，不会出现「文档写的和程序跑的不一样」。
    """
    from COPA.apps.audit.rules import get_rules, DEFAULT_PATH
    rules = get_rules()

    def order(code):
        digits = "".join(ch for ch in code if ch.isdigit()) or "0"
        return int(digits), code
    codes = sorted(rules.codes(), key=order)

    print("规则版本 {}｜共 {} 条｜描述引擎 {}".format(
        rules.version, len(codes), rules.desc_engine))
    print("-" * 88)
    for code in codes:
        meta = rules.raw(code)
        print("{:<5} {:<2} {}".format(
            code, "红" if meta.get("level") == "red" else "黄",
            meta.get("title", "")))
    print("-" * 88)

    lines = ["# 报价诊断规则总表", "",
             "> 自动生成，勿手改。真源：`{0}`｜规则版本 **{1}**｜共 {2} 条".format(
                 os.path.relpath(DEFAULT_PATH, _PROJECT_ROOT), rules.version,
                 len(codes)),
             "",
             "| 码 | 级别 | 标题 | 触发后怎么处理 |",
             "|---|---|---|---|"]
    for code in codes:
        meta = rules.raw(code)
        level = "红" if meta.get("level") == "red" else "黄"
        lines.append("| {} | {} | {} | {} |".format(
            code, level, meta.get("title", ""),
            (meta.get("advice", "") or "").replace("|", "／")))
    path = os.path.join(_PROJECT_ROOT, "docs", "audit-规则总表.md")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print("已同步规则总表：{}".format(path))
    except OSError as exc:
        print("规则总表写入失败（{}），控制台输出仍可用".format(exc))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit", description="报价单一致性批阅")
    parser.add_argument("files", nargs="*", help="报价单 xlsx/xlsm")
    parser.add_argument("--dir", "-d", action="append", default=[], help="目录（递归扫描 xlsx）")
    parser.add_argument("--out", "-o", default=DEFAULT_OUT, help="报告输出目录")
    parser.add_argument("--annotate", "-a", action="store_true", default=True,
                        help="生成批阅副本（默认开启；诊断内容就在副本的诊断页里）")
    parser.add_argument("--no-annotate", dest="annotate", action="store_false",
                        help="只出结论，不生成批阅副本")
    parser.add_argument("--quiet", "-q", action="store_true", help="只输出汇总")
    parser.add_argument("--modelspec", "--snapshot", dest="modelspec",
                        action="store_true",
                        help="列出型号规格基准的构建情况后退出（不落盘，按通表现算）")
    parser.add_argument("--engine", choices=("diff", "rules"), default=None,
                        help="描述一致性引擎：diff=快照比对(默认) / rules=旧规则")
    parser.add_argument("--rules", action="store_true",
                        help="列出全部问题码与判定口径（统一审核用）后退出")
    args = parser.parse_args(argv)

    if args.engine:
        os.environ["COPA_DESC_ENGINE"] = args.engine

    if args.rules:
        print_rule_table()
        return 0

    if args.modelspec:
        from COPA.apps.audit import modelspec
        from COPA.apps.audit.rules import get_rules
        catalog = Catalog.get()
        models = modelspec.all_models(catalog)
        hits = sum(1 for name in models if modelspec.get(catalog, name) is not None)
        print("型号规格基准：{} 个型号，{} 个有标准描述（不落盘，按通表现算）".format(
            len(models), hits))
        print("规则版本：{}｜描述引擎：{}".format(
            get_rules().version, get_rules().desc_engine))
        return 0

    files = collect(args.files, args.dir)
    if not files:
        print("没有可批阅的文件。用法：python -m COPA.apps.audit.cli <xlsx...>")
        return 2

    os.makedirs(args.out, exist_ok=True)
    catalog = Catalog.get()
    total = len(files)
    print("判定库：{} 个型号（台秤 {} / 平台秤 {} / 模块 {} / 仪表 {} / 描述 {}）".format(
        len(catalog.all_models()), len(catalog.benches), len(catalog.platforms),
        len(catalog.modules), len(catalog.instruments), len(catalog.descs)))

    failures = 0
    for index, path in enumerate(files, 1):
        name = os.path.basename(path)
        if "模板" in os.path.splitext(name)[0]:
            # 空白模板没有可批阅的内容，直接跳过（用户反馈：审阅模板毫无意义）
            print("\r" + progress_line(index, total, "{} 跳过（空白模板）".format(name)))
            continue
        if not args.quiet:
            print("\r" + progress_line(index - 1, total, name), end="", flush=True)
        started = time.time()
        try:
            report = audit_file(path)
        except Exception as exc:                       # 单个文件坏掉不影响其余文件
            failures += 1
            print("\r" + progress_line(index, total, "{} 读取失败：{}".format(name, exc)))
            continue

        if is_blank_template(report):                  # 内容级兜底：文件名不含「模板」也拦住
            print("\r" + progress_line(index, total, "{} 疑似空白模板，未逐行批阅".format(name)))
            print("    -> {}  ({:.2f}s)".format(summarize(report), time.time() - started))
            continue

        annotated = None
        if args.annotate:
            try:
                annotated = write_annotated_ex(report, args.out)
                if annotated.degraded:                 # 保真自检有丢失必须显式提示
                    print("    [注意] 批阅副本部分内容未完整保留：")
                    for warning in annotated.warnings:
                        print("           {}".format(warning))
            except Exception as exc:                   # 批阅失败不拦报告，标记失败
                failures += 1
                print("    [失败] 批阅副本生成失败：{}".format(exc))

        if not args.quiet:
            print("\r" + progress_line(index, total, "{}  {}".format(name, summarize(report))))
        print("    -> {}  ({:.2f}s)".format(summarize(report), time.time() - started))
        for note in getattr(report.doc, "notes", ()):   # 基线来源/失效原因，别吞
            print("       [提示] {}".format(note))
        if annotated is not None:
            print("       批阅副本：{}".format(annotated.path))

    print("\n完成：{} 个文件，失败 {} 个；输出目录 {}".format(total, failures, args.out))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
