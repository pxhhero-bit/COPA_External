"""报价项目号：出报价时给文件盖一个内部号码，并在项目快照里留一条出单记录.

为什么要有它
    批阅的比对基线是「输出报价那一刻的型号与数量」。项目号把两者串起来：

      出报价  ->  签发 COPA{YYMMDD}-{4位}，白字写进报价单 A 列倒数第二行，
                 同时把该单的型号/数量/单价/总价追加到**项目快照**的
                 「三、出单记录」章节
      批阅时  ->  文件里读得到项目号，就去项目快照里取出单记录当基线；
                 取不到（首次批阅或外部单）就退回「型号 vs 描述」比对

为什么是白字而非隐藏工作表
    出报价的是给客户的正式文件，多一张表等于把内部结构暴露出去；A 列角落里
    1 号白字既看不见、也不进打印区，客户不会留意。它不随「另存为 / 重存 /
    改数量」变动——这正是要的：号码不变量，基线才靠得住。

为什么基线并进项目快照
    号码要能读回来，快照不能给客户：文件里只放号码，基线留在本地。
    以前基线按号码单独存一份 JSON（data/cache/pno/<号码>.json），同一个项目
    出过几张单就散成几个文件，跟项目快照各说各话；现在并进项目快照的
    「出单记录」——一个项目出过哪几张单、每张单当时是什么样，一份 md 说全。
"""
import json
import os
import re
from datetime import datetime
from typing import Optional

from openpyxl.styles import Font

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(_ROOT, "data", "cache")
COUNTER_PATH = os.path.join(CACHE_DIR, "pno_counter.json")

PREFIX = "COPA"
NOTE = "，勿删"                      # 顺手提醒不要删掉这一格
WHITE = "FFFFFFFF"
SIZE = 1                             # 1 号白字：看不见，也不占版面

_RE = re.compile(r"COPA\d{6}-\d{4}")


# ---------------------------------------------------------------------------
# 号码签发
# ---------------------------------------------------------------------------
def _today(when: Optional[datetime] = None) -> str:
    return (when or datetime.now()).strftime("%y%m%d")


def issue(when: Optional[datetime] = None) -> str:
    """签发一个当日流水号：COPA{YYMMDD}-{0001..}。断号不影响，只要不复用。"""
    day = _today(when)
    data = {}
    if os.path.exists(COUNTER_PATH):
        try:
            with open(COUNTER_PATH, encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except (OSError, ValueError):
            data = {}
    seq = int(data.get("seq", 0)) + 1 if data.get("date") == day else 1
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(COUNTER_PATH, "w", encoding="utf-8") as fh:
            json.dump({"date": day, "seq": seq}, fh)   # 先占号再返回，避免重号
    except OSError:
        pass
    return "{}{}-{:04d}".format(PREFIX, day, seq)


# ---------------------------------------------------------------------------
# 写进报价单
# ---------------------------------------------------------------------------
def _free_row(ws) -> int:
    """A 列倒数第二行；该格已有内容就退到最后一行/追加一行，绝不覆盖已有内容。

    只判 A 列：号码写的就是 A 列，同一行 B..L 有合计/说明文字并不冲突——
    1 号白字不占版面、也不会压在文字上。按整行判空会让真实报价单每次都
    多长一行（COPA B/样例客户模板底部 B 列本来就有说明文字），而「倒数第二行」
    一旦变成「新加的最后一行」，这个位置约定就废了。
    """
    last = max(ws.max_row, 1)
    for row in (last - 1, last):
        if row >= 1 and ws.cell(row, 1).value in (None, ""):
            return row
    return last + 1


def stamp(wb, when: Optional[datetime] = None, ws=None) -> str:
    """把项目号写进报价页（白字 1 号，A 列倒数第二行），返回号码"""
    target = ws if ws is not None else (wb.active or wb.worksheets[0])
    code = issue(when)
    row = _free_row(target)
    cell = target.cell(row=row, column=1, value=code + NOTE)
    try:
        cell.font = Font(color=WHITE, sz=SIZE)
    except Exception:                 # 样式写不了也不影响号码本身
        pass
    return code


def find(wb) -> str:
    """在已打开的工作簿里找项目号；找不到返回空串"""
    for ws in wb.worksheets:
        if ws.title.startswith("_COPA"):
            continue
        for row in range(ws.max_row, 0, -1):
            value = ws.cell(row, 1).value
            if value is None:
                continue
            match = _RE.search(str(value))
            if match:
                return match.group(0)
            # A 列到底了仍是空：不用继续往上翻（号码写在底部）
            if str(value).strip().endswith("勿删"):
                return ""
    return ""


def find_in_file(path: str) -> str:
    """不打开整份文件找号码（批阅入口用；异常一律当没有）"""
    if not path or not os.path.exists(path):
        return ""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return ""
    try:
        return find(wb)
    except Exception:
        return ""
    finally:
        try:
            wb.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 出单基线（存进项目快照）
# ---------------------------------------------------------------------------
def save_state(path: str, code: str, snapshot_path: str = "") -> bool:
    """把这张报价单的「型号 + 数量」基线追加到项目快照的出单记录。

    snapshot_path 为空（项目还没保存过快照）就不写——上层会先补一份再调用。
    写不进去不影响出报价，只影响这份单后续批阅时的可比性。
    """
    if not code or not path or not os.path.exists(path) or not snapshot_path:
        return False

    try:
        from COPA.apps.Snapshot import append_order
        from COPA.apps.audit import mark
        from COPA.apps.audit.reader import read_quote

        doc = read_quote(path)
        stamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "pno": code,
            "version": 5,
            "title": mark.snapshot_title(code, stamp_text),
            "built_at": stamp_text,
            "source": os.path.basename(path),
            "digest": mark.digest_doc(doc),
            "rows": mark.row_signatures_doc(doc),
        }
        return append_order(snapshot_path, payload)
    except Exception:                  # 目录只读/解析失败：报价单已存好，不连坐
        return False


def state(code: str):
    """项目号 -> mark.State（批阅比对基线）；项目快照里没有则 None"""
    if not code:
        return None

    try:
        from COPA.apps.Snapshot import find_order
        payload = find_order(code)
    except Exception:
        return None

    if not payload:
        return None

    from COPA.apps.audit.mark import State

    rows = [list(r) for r in (payload.get("rows") or [])]
    origin = os.path.basename(str(payload.get("snapshot") or ""))
    return State(str(payload.get("digest") or ""), str(payload.get("built_at") or ""),
                 rows, source="快照:{}".format(origin) if origin else "快照", pno=code)


def known(code: str) -> bool:
    return state(code) is not None


__all__ = ["issue", "stamp", "find", "find_in_file", "save_state", "state",
           "known", "COUNTER_PATH", "PREFIX", "NOTE"]
