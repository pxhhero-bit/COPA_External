"""整个 COPA 软件层面统一版本号：About 窗口展示、Feedback 数据包标注
均从此导入，升级软件时只改这一个文件。"""

APP_VERSION = "v1.42"
APP_RELEASE_DATE = "2026-11-16"

# 渠道标记：Beta 版在「关于」、反馈数据包与快照里都会带上，出正式版时置空。
APP_CHANNEL = ""


def version_text() -> str:
    """带渠道的完整版本串：``v1.42 Beta`` / 正式版 ``v1.42``。"""

    return "{} {}".format(APP_VERSION, APP_CHANNEL) if APP_CHANNEL else APP_VERSION
