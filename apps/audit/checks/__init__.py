"""检查器注册表.

每个 check(item, catalog, rules) 是纯函数：给一条明细行，返回它踩到的问题列表。
新增检查项 = 新增一个模块 + 在这里注册，读取层与导出层都不用改。
"""
from COPA.apps.audit.checks import arith, consistency, descdiff, existence

# 顺序即报告顺序：先判「型号码本身对不对」，再判「型号与描述自洽」，最后判金额
CHECKS = (existence.check, consistency.check, descdiff.check, arith.check)

# 不进 CHECKS 的检查器：需要文件级状态（快照 / 项目段），入口在 runner.py
#   snapqty  L28 数量与报价快照不符（change 来自 mark.compare_doc，明细行 + 套数合计）
#   blockqty L29 模块/过渡板数量与支点数不符（按项目段标题判）


def run_checks(item, catalog, rules):
    issues = []
    for check in CHECKS:
        issues.extend(check(item, catalog, rules) or [])
    return issues
