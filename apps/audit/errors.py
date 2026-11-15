"""输入文件异常中文化：把 openpyxl / 文件系统层的英文异常翻译成能照做的提示.

只翻译「读文件」这一层，不吞异常：抛出的 AuditFileError 保留原始 cause，
CLI / GUI 直接把 str(exc) 展示给用户即可，两类通道文案一致。

为什么值得单独一层：openpyxl 对「旧版 .xls」「加密工作簿」「文件损坏」
统一抛 `File is not a zip file`，用户看不懂也不知道下一步该做什么；
而这三种情况处置方式完全不同（另存为 xlsx / 解除密码 / 重新导出）。
"""
import zipfile

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # .xls 与加密 xlsx 共用 OLE 容器


class AuditFileError(Exception):
    """批阅输入不可用（消息已是给用户看的中文）。"""


def _head(path: str, size: int = 8) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def describe(path: str, exc: BaseException) -> str:
    """把异常翻译成一句中文 + 处置建议。未知异常原样带出，便于排查。"""
    name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

    if isinstance(exc, FileNotFoundError):
        return "文件不存在，可能已被移动或删除：{}".format(path)
    if isinstance(exc, PermissionError):
        return "文件无法读取（可能正被 Excel 打开，或没有访问权限）。" \
               "请关闭 Excel 中打开的「{}」后重试".format(name)
    if isinstance(exc, IsADirectoryError):
        return "这是一个文件夹，不是报价单文件：{}".format(path)

    head = _head(path)
    if not head:
        return "文件是空的（0 字节），没有可批阅的内容：{}".format(name)
    if head.startswith(OLE_MAGIC):
        return ("「{}」是旧版 .xls 格式或设置了打开密码的工作簿，暂不支持直接批阅。"
                "请用 Excel 打开后「另存为 .xlsx」（加密文件先解除密码）再试").format(name)

    if isinstance(exc, zipfile.BadZipFile):
        if head.startswith(b"PK"):
            return "「{}」的 xlsx 结构已损坏（压缩包不完整）。" \
                   "请用 Excel 打开后另存为一份新文件再试".format(name)
        return "「{}」不是 Excel 工作簿（扩展名改成了 .xlsx，但内容不是）。" \
               "请确认文件类型后重试".format(name)

    if isinstance(exc, KeyError):
        return "「{}」的 xlsx 内部缺少必要部件，文件可能已损坏。" \
               "请用 Excel 打开后另存为一份新文件再试".format(name)

    return "读取「{}」失败：{}".format(name, exc)


def wrap(path: str, exc: BaseException) -> AuditFileError:
    return AuditFileError(describe(path, exc))
