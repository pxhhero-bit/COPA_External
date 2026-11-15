"""COPA 报价批阅(audit) v1.0.

对已有报价单 xlsx 做一致性检查：型号是否存在、型号与描述是否自洽、命名是否
仍符合现行规则，输出问题清单(markdown)与批阅用副本(xlsx)。

与 engine 的关系：本包只读 data/*.csv 与 config/audit_rules.json，不参与选型
计算，也不修改 engine 的任何状态。engine 的判定对象是「需求 -> 选型」，本包
的判定对象是「已出的单据」，两者共用同一套通表，但规则各自独立。

对外入口：
    from COPA.apps.audit import audit_file
    report = audit_file(path)          # -> Report
"""
from COPA.apps.audit.model import Issue, LineItem, QuoteDoc, Report
from COPA.apps.audit.runner import audit_file, audit_files

__all__ = ["Issue", "LineItem", "QuoteDoc", "Report", "audit_file", "audit_files"]
