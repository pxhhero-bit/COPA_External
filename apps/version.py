"""整个 COPA 软件层面统一版本号：About 窗口展示、Feedback 数据包标注
均从此导入，升级软件时只改这一个文件。"""

APP_VERSION = "v1.42"
APP_RELEASE_DATE = "2026-11-16"

# 渠道标记：对外发布版统一走 External，出现在「关于」、反馈数据包、
# 项目快照与打包产物文件名（COPA_v1.42_External.zip）里。
APP_CHANNEL = "External"


def version_text() -> str:
    """带渠道的完整版本串：``v1.42 Beta`` / 正式版 ``v1.42``。"""

    return "{} {}".format(APP_VERSION, APP_CHANNEL) if APP_CHANNEL else APP_VERSION
