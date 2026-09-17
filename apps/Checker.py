"""COPA_com_Checker v1.0 自动解决方案检查器 by Hero Pang.
与 Writer/Diagnostic 同级：读取 engine 回传的 diagnostic，按
problem_shooting.json 的问题映射(问题代码 -> 人类语言解释/建议)推导问题清单，
按 quote_id 升序整理成列表，由 CheckerDialog 展示。
Checklist 的「查看自动解决方案」入口调用。
"""
import json
import os

from PySide6.QtWidgets import (QDialog, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

_RULES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "problem_shooting.json"
)

# 阶段计数键 -> 问题代码：平台秤/台秤流水线结构一致，仅前缀不同
_SCALE_STAGE_CODES = {
    "brand_pass": "{prefix}_BRAND_NO_MATCH",
    "subtype_pass": "{prefix}_SUBTYPE_NO_MATCH",
    "material_pass": "{prefix}_MATERIAL_NO_MATCH",
    "ex_pass": "{prefix}_EX_NO_MATCH",
    "range_pass": "{prefix}_RANGE_NO_MATCH",
    "size_pass": "{prefix}_SIZE_NO_MATCH",
    "e_pass": "{prefix}_E_NO_MATCH",
}

# 仪表流水线阶段计数键 -> 问题代码(顺序即筛选顺序)
_CONTROLLER_STAGE_CODES = (
    ("brand_pass", "CONTROLLER_BRAND_NO_MATCH"),
    ("family_pass", "CONTROLLER_FAMILY_NO_MATCH"),
    ("communication_pass", "CONTROLLER_COM_NO_MATCH"),
    ("hardware_pass", "CONTROLLER_HARDWARE_NO_MATCH"),
    ("ex_pass", "CONTROLLER_EX_NO_MATCH"),
)

# 模块淘汰原因 -> 问题代码
_MODULE_REJECTION_CODES = (
    ("传感器无匹配模块", "MODULE_SENSOR_FAMILY_NO_MATCH"),
    ("模块防爆不匹配", "MODULE_EX_NO_MATCH"),
    ("模块材质不匹配", "MODULE_MATERIAL_NO_MATCH"),
    ("模块孔距不匹配", "MODULE_HOLE_NO_MATCH"),
)


class Checker:

    def __init__(self, rules_path=_RULES_PATH):
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)

    # ====入口====

    def check(self, results):
        """engine结果列表 -> 问题清单 [{quote_id,code,title,description,suggestions,detail}]
        按 quote_id 升序排列；结果内部按 传感器->模块->秤->仪表->接线盒 的因果顺序汇报"""
        problems = []

        for result in sorted(results or [],
                              key=lambda r: (r.get("quote_id") or 0)):
            problems.extend(self._check_result(result or {}))

        return problems

    def _problem(self, quote_id, code, detail=None):
        info = self.rules.get(code) or {
            "title": code, "description": "", "suggestions": [],
        }
        problem = {"quote_id": quote_id or 0, "code": code,
                   "detail": detail or ""}
        problem.update(info)
        return problem

    def _check_result(self, result):
        quote_id = result.get("quote_id") or 0

        if result.get("status") == "ERROR":
            return [self._problem(quote_id, "ENGINE_ERROR",
                                  result.get("error", ""))]

        problems = []
        problems += self._check_sensor(quote_id, result)
        problems += self._check_module(quote_id, result)
        problems += self._check_scale(quote_id, result,
                                      "platform_diagnostic", "PLATFORM")
        problems += self._check_scale(quote_id, result,
                                      "bench_diagnostic", "BENCH")
        problems += self._check_controller(quote_id, result)
        problems += self._check_jbox(quote_id, result)
        return problems

    # ====各业务推导====

    def _check_sensor(self, quote_id, result):
        sensor = result.get("sensor") or {}
        diag = sensor.get("diagnostic") or {}

        if diag.get("status") != "NO_MATCH":
            return []

        stage = diag.get("stage_counts") or {}
        rejection = diag.get("rejection") or {}
        evidence = diag.get("evidence") or {}

        if not stage.get("ex_pass"):
            return [self._problem(quote_id, "SENSOR_EX_NO_MATCH")]

        if not stage.get("final"):
            detail = "SF范围 {}~{}，目标SF {}".format(
                evidence.get("sf_min"), evidence.get("sf_max"),
                sensor.get("best_SF"))

            if rejection.get("SF过低") or rejection.get("SF过高"):
                detail += "；SF过低淘汰{}项 / SF过高淘汰{}项".format(
                    rejection.get("SF过低", 0), rejection.get("SF过高", 0))

            return [self._problem(quote_id, "SENSOR_SF_NO_MATCH", detail)]

        return [self._problem(quote_id, "SENSOR_NO_MATCH")]

    def _check_module(self, quote_id, result):
        diag = result.get("module_diagnostic") or {}

        if diag.get("status") != "NO_MATCH":
            return []

        # 上游传感器为空时根因已在传感器段汇报，不重复报
        if (diag.get("input") or {}).get("sensor_count") == 0:
            return []

        rejection = diag.get("rejection") or {}
        problems = []

        for key, code in _MODULE_REJECTION_CODES:
            if rejection.get(key):
                problems.append(self._problem(
                    quote_id, code, "淘汰{}项".format(rejection[key])))

        if not problems:
            problems.append(self._problem(
                quote_id, "MODULE_NO_MATCH",
                (diag.get("evidence") or {}).get("reason")))

        return problems

    def _check_scale(self, quote_id, result, diag_key, prefix):
        diag = result.get(diag_key) or {}
        stage = diag.get("stage_counts") or {}

        if not diag:
            # 该业务无此诊断段(如模块结果无平台秤/台秤诊断)，不适用
            return []

        if diag.get("status") != "NO_MATCH" and stage.get("final"):
            return []

        reason = (diag.get("evidence") or {}).get("reason")

        # 首个计数为0的阶段即阻断环节(其前阶段均有剩余)
        for stage_key, code_tpl in _SCALE_STAGE_CODES.items():
            if stage_key in stage and not stage[stage_key]:
                return [self._problem(
                    quote_id, code_tpl.format(prefix=prefix), reason)]

        return [self._problem(quote_id,
                              "{}_NO_MATCH".format(prefix), reason)]

    def _check_controller(self, quote_id, result):
        diag = result.get("controller_diagnostic") or {}
        stage = diag.get("stage_counts") or {}

        if not stage or stage.get("final"):
            # SKIPPED等无阶段信息：根因在上游业务，不重复报
            return []

        detail = diag.get("reason") or ""

        for stage_key, code in _CONTROLLER_STAGE_CODES:
            if stage_key in stage and not stage[stage_key]:
                if code == "CONTROLLER_COM_NO_MATCH":
                    comm = diag.get("communication")

                    if isinstance(comm, dict):
                        comm_summary = "；".join(
                            "{}={}".format(k, v) for k, v in comm.items())
                        detail = "；".join(x for x in (detail, comm_summary) if x)

                return [self._problem(quote_id, code, detail)]

        return [self._problem(quote_id, "CONTROLLER_NO_MATCH", detail)]

    def _check_jbox(self, quote_id, result):
        if (result.get("item_type") in ("module", "platform")
                and result.get("jbox") is None
                and result.get("status") != "ERROR"):
            return [self._problem(quote_id, "JBOX_NO_MATCH")]

        return []


# ---------------------------------------------------------------------------
# 展示：按 quote_id 排列的问题清单子窗
# ---------------------------------------------------------------------------

def format_problems(problems):
    """问题清单 -> 可读文本(按 quote_id 分组)"""
    lines = []

    for problem in problems:
        block = ["条目 {}".format(problem["quote_id"]),
                 "  ▸ {}({})".format(problem["title"], problem["code"])]

        if problem.get("description"):
            block.append("    {}".format(problem["description"]))

        if problem.get("detail"):
            block.append("    [engine] {}".format(problem["detail"]))

        for i, tip in enumerate(problem.get("suggestions") or [], 1):
            block.append("    建议{}. {}".format(i, tip))

        lines.append("\n".join(block))

    return "\n\n".join(lines)


class CheckerDialog(QDialog):
    """自动解决方案子窗：问题列表(按quoteid排列) + 底部确认关闭"""

    def __init__(self, problems, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动解决方案 - 问题清单")
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(format_problems(problems))
        layout.addWidget(self.textEdit)

        btn_confirm = QPushButton("确认", self)
        btn_confirm.setDefault(True)
        btn_confirm.clicked.connect(self.accept)
        layout.addWidget(btn_confirm)
