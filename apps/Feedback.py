"""COPA_com_Feedback v1.0 反馈与优化控件 by Hero Pang.
Commander「设置 -> 反馈与优化」：收集全部项目的 Desk 输入快照、
Checklist 人工确认状态与 engine 结果/diagnostic 生成 txt 数据包
(不向用户展示)，随用户描述的问题经 SMTP 发送到开发者邮箱。

SMTP 参数读 config/feedback.json(smtp_host/smtp_port/use_ssl/
sender/auth_code/receiver)，随安装包 config 目录分发；数据收集在
GUI 线程完成(纯内存字符串拼装，且模态对话框期间无并发修改)，仅
网络发送放后台线程，完成经信号回 GUI 线程提示与收尾。
"""
import json
import os
import platform
import smtplib
import sys
import threading
from datetime import datetime
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from COPA.apps import app_icon
from COPA.apps.Diagnostic import format_diagnostics
from COPA.apps.version import APP_VERSION

# 路径定位与 engine/Writer 同机制：打包后取 exe 旁，源码运行取项目根
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CONFIG_PATH = os.path.join(_ROOT_DIR, "config", "feedback.json")
_OUTPUT_DIR = os.path.join(_ROOT_DIR, "output")

# feedback.json 必备键：缺任一视为通道未配置，发送按钮置灰并提示
_REQUIRED_KEYS = ("smtp_host", "sender", "auth_code", "receiver")


def load_feedback_config():
    """config/feedback.json -> dict；文件不存在返回空 dict(由界面提示)"""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return {}

    if not isinstance(config, dict):
        raise RuntimeError("config/feedback.json 内容必须是对象")

    return config


# ---------------------------------------------------------------------------
# 数据包收集：全部项目的 Desk 快照 / Checklist 确认状态 / engine 结果诊断
# ---------------------------------------------------------------------------

def _format_entries(entries):
    """Desk 条目快照 -> 文本行(与 Desk._print_entries 同版式)"""
    lines = []

    for entry in entries:
        quote_info = entry.get("quote_info") or {}
        lines.append("-" * 34)
        lines.append("quote_id: {}".format(quote_info.get("quote_id")))
        lines.append("数量: {}".format(quote_info.get("quantity")))
        lines.append("条目类型: {}".format(entry.get("item_type")))
        lines.append("是否需要检定: {}".format(
            "是" if entry.get("metrology") else "否"))
        lines.append("是否高精度: {}".format(
            "是" if entry.get("high_precision") else "否"))
        lines.append("是否防爆: {}".format("是" if entry.get("Ex_P") else "否"))
        lines.append("现场服务: {}".format(
            "是" if entry.get("onsite_service") else "否"))
        lines.append("其他条目需求: {}".format(entry.get("description")))

        parsed = entry.get("parsed")
        if parsed is not None:
            for item in parsed.get("recognized") or []:
                lines.append("已识别：{} <- [{}|{}] {} = {}".format(
                    item.get("parameter"), item.get("term"),
                    item.get("source"), item.get("text") or "(推断)",
                    item.get("value")))

            for text in parsed.get("unrecognized") or []:
                lines.append("未识别：{}".format(text))

            for warning in parsed.get("warnings") or []:
                lines.append("警告：[{}] {} ({})".format(
                    warning.get("parameter"), warning.get("text"),
                    warning.get("reason")))

            lines.append("解析参数: {}".format(parsed.get("data")))

    return lines


def _format_checklist_states(states):
    """Checklist.dump_state() 的条目状态列表 -> 文本行"""
    lines = []

    for state in states:
        lines.append("-" * 34)
        lines.append("条目 {}：类型 {}    数量 {}".format(
            state.get("quote_id"), state.get("type"), state.get("qty")))
        lines.append("检定: {}    高精度: {}    防爆: {}".format(
            "是" if state.get("metrology") else "否",
            "是" if state.get("high_precision") else "否",
            "是" if state.get("ex") else "否"))

        for name, text in state.get("selections") or ():
            lines.append("{}: {}".format(name, text or "(空)"))

        item_out = state.get("item")
        lines.append("输出条目数据: {}".format(
            item_out if item_out is not None else "(未生成)"))

        for warning in state.get("warnings") or []:
            lines.append("警告: {}".format(warning))

    return lines


def build_report(commander):
    """Commander 全部项目数据 -> 数据包文本。各段独立 try/except，
    单段收集失败不影响其余段落(失败原因写入该段)。"""
    projects = getattr(commander, "_projects", None) or {}
    entries_map = getattr(commander, "_project_entries", None) or {}
    checklists = getattr(commander, "_checklists", None) or {}
    quote_data = getattr(commander, "_quote_data", None) or {}

    lines = [
        "COPA 反馈数据包",
        "生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "版本: {}".format(APP_VERSION),
        "运行环境: Python {} / {}".format(
            platform.python_version(), platform.platform()),
        "打包环境: {}".format("是" if getattr(sys, "frozen", False) else "否"),
        "项目数: {}".format(len(projects)),
    ]

    for sid in projects:
        lines.append("")
        lines.append("=" * 46)
        lines.append("==== 项目 {} ====".format(sid))

        try:
            lines.append("")
            lines.append("---- Desk 输入快照(发起选型时) ----")
            entries = entries_map.get(sid) or []
            lines += (_format_entries(entries) if entries
                      else ["(尚未发起过选型)"])
        except Exception as err:
            lines.append("(Desk 快照收集失败: {})".format(err))

        try:
            lines.append("")
            lines.append("---- Checklist 人工确认状态 ----")
            checklist = checklists.get(sid)

            if checklist is None:
                lines.append("(该项目没有已打开的选型清单)")
            else:
                states = checklist.dump_state()
                lines += (_format_checklist_states(states) if states
                          else ["(清单为空)"])
        except Exception as err:
            lines.append("(清单状态收集失败: {})".format(err))

        try:
            lines.append("")
            lines.append("---- engine 选型结果与诊断 ----")
            # 结果按「项目ID_条目ID」存档，取本项目键并按条目ID升序
            results = sorted(
                (r for k, r in quote_data.items()
                 if isinstance(r, dict) and k.startswith(sid + "_")),
                key=lambda r: r.get("quote_id") or 0)

            if not results:
                lines.append("(该项目没有选型结果存档)")

            for result in results:
                lines.append(format_diagnostics(result))
                lines.append("")
        except Exception as err:
            lines.append("(engine 结果收集失败: {})".format(err))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 邮件发送
# ---------------------------------------------------------------------------

def _send_mail(config, desc, contact, report):
    """组装 MIME(正文=用户描述，附件=数据包txt)并经 SMTP 发送。
    异常原样上抛，由对话框统一提示。"""
    host = (config.get("smtp_host") or "").strip()
    port = int(config.get("smtp_port") or 465)
    use_ssl = config.get("use_ssl", True)
    sender = (config.get("sender") or "").strip()
    auth_code = config.get("auth_code") or ""
    receiver = (config.get("receiver") or "").strip()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    subject = "【COPA反馈】{} {}".format(APP_VERSION, desc.splitlines()[0][:40])

    body = [desc]

    if contact:
        body += ["", "联系方式：{}".format(contact)]

    body += ["", "--", "由 COPA {} 自动发送".format(APP_VERSION)]

    msg = MIMEMultipart()
    # 主题先编码成 RFC2047 encoded-word 字符串再赋值：__setitem__ 形参
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["From"] = sender
    msg["To"] = receiver
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText("\n".join(body), "plain", "utf-8"))

    attachment = MIMEApplication(report.encode("utf-8"), _subtype="octet-stream")
    attachment.add_header(
        "Content-Disposition", "attachment",
        filename=("utf-8", "", "COPA反馈数据_{}.txt".format(stamp)))
    msg.attach(attachment)

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)

    try:
        if not use_ssl:
            server.starttls()

        server.login(sender, auth_code)
        server.sendmail(sender, [receiver], msg.as_string())
    finally:
        server.quit()


# ---------------------------------------------------------------------------
# 反馈对话框：问题描述(必填) + 联系方式(选填) + 发送/取消
# ---------------------------------------------------------------------------

class FeedbackDialog(QDialog):
    """反馈对话框：发送时自动附带全部项目数据 txt。发送走后台线程，
    完成经 sendFinished 回 GUI 线程提示；失败兜底把数据包落盘 output/"""

    sendFinished = Signal(bool, str)

    def __init__(self, commander, parent=None):
        super().__init__(parent or commander)
        self.setWindowIcon(app_icon())
        self.setWindowTitle("反馈与优化")
        self.resize(520, 360)

        self._commander = commander
        self._report = None
        self._config_error = None

        try:
            self._config = load_feedback_config()
        except Exception as err:
            self._config = {}
            self._config_error = str(err)

        missing = [key for key in _REQUIRED_KEYS
                   if not (self._config or {}).get(key)]

        layout = QVBoxLayout(self)

        tip = QLabel(self)
        tip.setWordWrap(True)
        tip.setText(
            "感谢您的反馈！请详细描述遇到的问题或优化建议。"
            "诊断信息仅用于开发者定位问题。")
        
        layout.addWidget(tip)

        if self._config_error or missing:
            warn = ["", "⚠ 反馈通道未配置，暂时无法发送："]

            if self._config_error:
                warn.append(self._config_error)

            if missing:
                warn.append("config/feedback.json 缺少：{}".format(
                    "、".join(missing)))

            tip.setText(tip.text() + "\n" + "\n".join(warn))

        layout.addWidget(QLabel("问题描述（必填）：", self))
        self.descEdit = QPlainTextEdit(self)
        self.descEdit.setPlaceholderText("请用文字描述问题，不支持截图。")
        layout.addWidget(self.descEdit)

        contact_row = QHBoxLayout()
        contact_row.addWidget(QLabel("联系方式（选填，便于回复）：", self))
        self.contactEdit = QLineEdit(self)
        contact_row.addWidget(self.contactEdit)
        layout.addLayout(contact_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btnSend = QPushButton("发送", self)
        self.btnSend.setDefault(True)
        self.btnSend.setEnabled(not (self._config_error or missing))
        self.btnSend.clicked.connect(self._on_send)
        btnCancel = QPushButton("取消", self)
        btnCancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btnSend)
        btn_row.addWidget(btnCancel)
        layout.addLayout(btn_row)

        self.sendFinished.connect(self._on_send_finished)

    def _on_send(self):
        desc = self.descEdit.toPlainText().strip()

        if not desc:
            QMessageBox.information(self, "反馈", "请先填写问题描述。")
            return

        try:
            # 收集在 GUI 线程完成(纯内存拼装，瞬时)；线程只做网络 IO
            self._report = build_report(self._commander)
        except Exception as err:
            # 数据包是定位问题的关键，收集失败则不发送
            QMessageBox.critical(self, "反馈", "数据包收集失败：{}".format(err))
            return

        self.btnSend.setEnabled(False)
        self.btnSend.setText("正在发送…")
        threading.Thread(
            target=self._send_worker,
            args=(desc, self.contactEdit.text().strip(), self._report),
            daemon=True,
        ).start()

    def _send_worker(self, desc, contact, report):
        try:
            _send_mail(self._config, desc, contact, report)
        except Exception as err:
            self.sendFinished.emit(False, str(err))
        else:
            self.sendFinished.emit(True, "")

    def _on_send_finished(self, ok, message):
        if ok:
            QMessageBox.information(self, "反馈", "反馈已发送，感谢您的支持！")
            self.accept()
            return

        # 发送失败：恢复按钮可重试，并把数据包落盘供手动转发
        self.btnSend.setEnabled(True)
        self.btnSend.setText("发送")

        fallback = self._save_fallback()
        text = "邮件发送失败：{}\n\n".format(message)

        if fallback:
            text += ("数据包已保存至：\n{}\n"
                     "您可以将该文件手动发送给开发者。").format(fallback)
        else:
            text += "数据包暂存失败，请重试。"

        QMessageBox.critical(self, "反馈", text)

    def _save_fallback(self):
        """发送失败兜底：数据包落盘 output/ 供手动转发；失败返回 None"""
        try:
            os.makedirs(_OUTPUT_DIR, exist_ok=True)
            path = os.path.join(_OUTPUT_DIR, "反馈数据包_{}.txt".format(
                datetime.now().strftime("%Y%m%d_%H%M%S")))

            with open(path, "w", encoding="utf-8") as f:
                f.write(self._report or "")

            return path
        except Exception:
            return None
