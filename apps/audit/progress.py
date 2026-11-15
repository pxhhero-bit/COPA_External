"""字符进度条：CLI 与 GUI 共用一套画法（GUI 里贴到 QLabel 上原位刷新）。

不用百分比而用「第几条」，因为批阅的耗时不在条数而在读取，用户看到的是
"正在处理第 3/9 个文件"而不是一个跳动的饼。
"""
DONE = "■"
TODO = "□"


def bar(done: int, total: int, width: int = 10) -> str:
    total = max(int(total), 1)
    done = max(0, min(int(done), total))
    filled = int(round(width * done / total))
    return DONE * filled + TODO * (width - filled)


def line(done: int, total: int, label: str = "", width: int = 10) -> str:
    text = "[{}] {}/{}".format(bar(done, total, width), min(done, total), total)
    return "{} {}".format(text, label).rstrip()
