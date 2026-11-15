"""文件输入 -> 纯文本转写稿（轻量版）。

本版范围：``txt`` / ``md`` / ``csv`` / ``xlsx`` / ``xlsm`` / ``xls`` /
``docx`` / ``doc`` / ``html`` / ``htm`` 本地读取，零网络、零新增依赖。PDF、
PPT、图片/扫描件等非文本格式不做，由用户自行转换成上述格式；多模态解析留待
后续版本。

老式 ``.doc`` 是 OLE2 复合文档，这里用标准库直接读 CFB 目录、FAT 与
Word 97 的 CLX piece table；老式 ``.xls`` 同样从 CFB 里取 ``Workbook`` 流，
按 BIFF8 记录解析 SST 与单元格。两者都不需要本机装 Office/WPS，也不需要新
pip 包。

边界：抽取结果只是一条普通用户消息，字段判断仍由 ``ChatSession`` 与
``contract`` 承担；本模块不产出结构化候选，也不改动会话层。表格一律转写为
标准 Markdown 表格（不输出单元格坐标），由模型按表头语义自行转 JSON。
HTML 只做纯文本解析，不发起任何请求、不加载外部资源、不执行脚本。
"""

from __future__ import annotations

import csv
import io
import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, NamedTuple

TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".csv", ".xlsx", ".xlsm", ".xls", ".docx", ".doc",
    ".html", ".htm",
})
SUPPORTED_HINT = (
    "txt / md / CSV / Word(.docx/.doc) / Excel(.xlsx/.xlsm/.xls) / HTML(.html/.htm)"
)
FILE_FILTER = (
    "文本类文件 (*.txt *.md *.csv *.xlsx *.xlsm *.xls *.docx *.doc *.html *.htm);;"
    "纯文本 (*.txt *.md *.csv);;"
    "Excel (*.xlsx *.xlsm *.xls);;"
    "Word (*.docx *.doc);;"
    "网页 (*.html *.htm)"
)

_MAX_ROWS = 300
_MAX_CHARS = 40000

MESSAGE_PREFIX = (
    "以下是从文件《{source}》抽取的需求原文转写，按标准语法转写，仅供提取字段。\n"
    "【语法】表格一律为标准 Markdown 表格：第一行为表头，第二行为 | --- | 分隔线，"
    "其后每行一条记录；空单元格留空，单元格内换行已折为空格、竖线已转义。"
    "表格里没有单元格坐标或行列号，请按表头语义自行理解并转成 JSON 字段。\n"
    "非表格文本按原样逐行排列。未写明的字段一律视为未提供。\n\n"
)

_BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "tr", "table", "ul", "ol", "dl", "dt", "dd",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
    "header", "footer", "pre", "blockquote",
})
_CELL_TAGS = frozenset({"td", "th"})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "head"})


class IngestError(RuntimeError):
    """可安全显示在对话框里的抽取失败原因。"""


class IngestResult(NamedTuple):
    text: str
    source: str
    warnings: list[str]


def suffix_of(path: Any) -> str:
    return Path(path).suffix.lower()


def is_supported(path: Any) -> bool:
    return suffix_of(path) in TEXT_SUFFIXES


def compose_message(result: IngestResult) -> str:
    """把转写稿包成一条普通用户消息，会话层不需要任何改动。"""

    return MESSAGE_PREFIX.format(source=result.source) + result.text


def _clip(text: str, warnings: list[str], label: str) -> str:
    if len(text) > _MAX_CHARS:
        warnings.append("{}内容过长，已截取前 {} 字".format(label, _MAX_CHARS))
        return text[:_MAX_CHARS] + "\n…（内容已截断）"
    return text


def _decode_text(raw: bytes, *, meta_charset: bool = False) -> str:
    """按 BOM / 声明编码 / utf-8 / gb18030 依次解码，兼容国内 GBK 文件。"""

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "replace")
    encodings: list[str] = []
    if meta_charset:
        declared = re.search(
            r"charset\s*=\s*[\"']?([\w-]+)",
            raw[:2048].decode("ascii", "ignore"),
            re.I,
        )
        if declared:
            encodings.append(declared.group(1))
    encodings += ["utf-8", "gb18030"]
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _cell_text(value: Any) -> str:
    """单元格转 Markdown：折行、压空白、转义竖线。"""

    # Excel 的数值一律是 double，3000 会写成 3000.0；整数就还它本来面目。
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("|", "\\|")


def _markdown_table(rows: list[list[Any]], warnings: list[str], label: str) -> str:
    """二维表 -> 标准 Markdown 表格；首行若是标题则单独输出，不冒充表头。"""

    table = [[_cell_text(value) for value in row] for row in rows]
    table = [row for row in table if any(row)]
    if not table:
        warnings.append("{}中没有可读取的表格内容".format(label))
        return ""
    last = max(index for row in table for index, cell in enumerate(row) if cell)
    width = last + 1
    table = [row[:width] + [""] * max(0, width - len(row)) for row in table]
    lines: list[str] = []
    if len(table) >= 2 and sum(bool(c) for c in table[0]) < sum(bool(c) for c in table[1]):
        lines.append(" ".join(cell for cell in table[0] if cell))
        table = table[1:]
    lines.append("| " + " | ".join(table[0]) + " |")
    lines.append("| " + " | ".join(["---"] * width) + " |")
    lines.extend("| " + " | ".join(row) + " |" for row in table[1:])
    return "\n".join(lines)


def _read_text(path: Path, warnings: list[str]) -> str:
    """txt / md 原样保留，Markdown 的标题与竖线表格 LLM 能直接理解。"""

    text = _decode_text(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        warnings.append("文件中没有可读取的文本内容")
    return _clip(text, warnings, "文本")


def _read_csv(path: Path, warnings: list[str]) -> str:
    """CSV 读成二维表后统一转 Markdown，不带单元格坐标。"""

    text = _decode_text(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    sample = text[:4096]
    delimiter = max((",", "\t", ";", "|"), key=sample.count)
    if sample.count(delimiter) == 0:
        delimiter = ","
    try:
        rows: list[list[Any]] = []
        for index, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
            rows.append(row)
            if index >= _MAX_ROWS:
                warnings.append("CSV 超过 {} 行，已截断".format(_MAX_ROWS))
                break
    except csv.Error as exc:
        raise IngestError("CSV 格式无法解析：{}".format(exc)) from None
    return _clip(_markdown_table(rows, warnings, "CSV"), warnings, "CSV")


def _read_xlsx(path: Path, warnings: list[str]) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True, read_only=True)
    lines: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows: list[list[Any]] = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                rows.append(list(row))
                if row_index >= _MAX_ROWS:
                    warnings.append("工作表 {} 超过 {} 行，已截断".format(sheet.title, _MAX_ROWS))
                    break
            table = _markdown_table(rows, warnings, "工作表 " + sheet.title)
            if table:
                lines.append("【工作表：{}】".format(sheet.title))
                lines.append(table)
    finally:
        workbook.close()
    return _clip("\n".join(lines), warnings, "表格")


def _read_docx(path: Path, warnings: list[str]) -> str:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = [[cell.text for cell in row.cells] for row in table.rows[:_MAX_ROWS]]
            markdown = _markdown_table(rows, warnings, "文档表格")
            if markdown:
                lines.append("【表格】")
                lines.append(markdown)
    return _clip("\n".join(lines), warnings, "文档")


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


class _Ole2File:
    """只够读 Word .doc 的 CFB 最小实现：DIFAT / FAT / MiniFAT / 目录。"""

    _END_OF_CHAIN = 0xFFFFFFFE
    _MAX_SECTOR = 0xFFFFFFFA
    _SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def __init__(self, data: bytes) -> None:
        if data[:8] != self._SIGNATURE:
            raise IngestError("不是标准的 Word 二进制文档")
        self._data = data
        self._sector_size = 1 << _u16(data, 30)
        self._mini_size = 1 << _u16(data, 32)
        fat_count = _u32(data, 44)
        dir_start = _u32(data, 48)
        self._cutoff = _u32(data, 56)
        minifat_start = _u32(data, 60)
        minifat_count = _u32(data, 64)
        difat_start = _u32(data, 68)
        difat_count = _u32(data, 72)

        difat = [_u32(data, 76 + 4 * i) for i in range(109)]
        sector = difat_start
        for _ in range(difat_count):
            if sector >= self._MAX_SECTOR:
                break
            block = self._sector(sector)
            difat += [_u32(block, 4 * i) for i in range(self._sector_size // 4 - 1)]
            sector = _u32(block, self._sector_size - 4)
        fat: list[int] = []
        for item in difat[:fat_count]:
            if item >= self._MAX_SECTOR:
                continue
            block = self._sector(item)
            fat += [_u32(block, 4 * i) for i in range(self._sector_size // 4)]
        self._fat = fat

        directory = self._chain(dir_start, fat)
        self._entries: list[tuple[str, int, int, int]] = []
        for offset in range(0, len(directory) - 127, 128):
            entry = directory[offset:offset + 128]
            name_length = _u16(entry, 64)
            name = (
                entry[:max(0, name_length - 2)].decode("utf-16le", "replace")
                if name_length >= 2 else ""
            )
            self._entries.append((
                name, entry[66], _u32(entry, 116),
                struct.unpack_from("<Q", entry, 120)[0],
            ))
        root = next((item for item in self._entries if item[1] == 5), None)
        self._mini_stream = (
            self._chain(root[2], fat)[:root[3]] if root and root[3] else b""
        )
        minifat = b""
        sector = minifat_start
        for _ in range(minifat_count):
            if sector >= self._MAX_SECTOR:
                break
            minifat += self._sector(sector)
            sector = fat[sector] if sector < len(fat) else self._END_OF_CHAIN
        self._minifat = [_u32(minifat, 4 * i) for i in range(len(minifat) // 4)]

    def _sector(self, number: int) -> bytes:
        offset = (number + 1) * self._sector_size
        return self._data[offset:offset + self._sector_size]

    def _chain(self, start: int, fat: list[int], *, mini: bool = False) -> bytes:
        out = bytearray()
        sector = start
        seen: set[int] = set()
        while sector < self._MAX_SECTOR and sector not in seen:
            seen.add(sector)
            if mini:
                offset = sector * self._mini_size
                out += self._mini_stream[offset:offset + self._mini_size]
            else:
                out += self._sector(sector)
            sector = fat[sector] if sector < len(fat) else self._END_OF_CHAIN
            if len(out) > 32 * 1024 * 1024:
                break
        return bytes(out)

    def stream(self, name: str) -> bytes | None:
        for entry_name, kind, start, size in self._entries:
            if kind == 2 and entry_name == name:
                if size < self._cutoff:
                    return self._chain(start, self._minifat, mini=True)[:size]
                return self._chain(start, self._fat)[:size]
        return None


def _clean_doc_text(text: str) -> str:
    """Word 控制符转文本：域代码丢弃、单元格用竖线、段落用换行。"""

    text = re.sub(r"\x13.*?\x14", "", text, flags=re.S)
    text = text.replace("\x15", "").replace("\x07", " | ").replace("\x02", "")
    text = text.replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n")
    lines: list[str] = []
    for line in text.splitlines():
        line = "".join(ch if ch >= " " or ch == "\t" else " " for ch in line)
        line = re.sub(r"[ \t\r\f\v\u00a0]+", " ", line).strip()
        line = re.sub(r"(\s*\|)+$", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _read_doc_binary(path: Path, raw: bytes) -> str:
    """Word 97-2003：FIB -> fcClx -> CLX piece table -> 文本片段。"""

    container = _Ole2File(raw)
    word = container.stream("WordDocument")
    if not word:
        raise IngestError("文档里找不到 WordDocument 流")
    if _u16(word, 2) < 0x00C1:
        raise IngestError("只支持 Word 97-2003 的 .doc，请另存为 .docx")
    flags = _u16(word, 10)
    if flags & 0x0100:
        raise IngestError("文档已加密，请解密后另存为 .docx")
    language = _u16(word, 6)
    ansi = "gb18030" if language in (0x0804, 0x0404, 0x0C04, 0x1004) else "cp1252"
    table_name = "1Table" if flags & 0x0200 else "0Table"
    table = container.stream(table_name) or b""

    # FIB 的 FibRgFcLcb97 中第 33 组是 fcClx / lcbClx。
    count_w = _u16(word, 32)
    count_lw_offset = 34 + count_w * 2
    count_lw = _u16(word, count_lw_offset)
    pairs_offset = count_lw_offset + 2 + count_lw * 4 + 2
    fc_clx = _u32(word, pairs_offset + 33 * 8)
    lcb_clx = _u32(word, pairs_offset + 33 * 8 + 4)

    if not table or fc_clx + lcb_clx > len(table):
        fc_min, fc_mac = _u32(word, 24), _u32(word, 28)
        return _clean_doc_text(
            word[fc_min:fc_mac].decode("utf-16le", "replace")
        )
    clx = table[fc_clx:fc_clx + lcb_clx]
    index = 0
    while index < len(clx) and clx[index] == 1:  # 跳过 Prc
        index += 3 + _u16(clx, index + 1)
    if index >= len(clx) or clx[index] != 2:  # 0x02 = Pcdt
        raise IngestError("文档的文本索引（CLX）无法解析")
    length = _u32(clx, index + 1)
    plc = clx[index + 5:index + 5 + length]
    pieces = (length - 4) // 12
    if pieces <= 0:
        raise IngestError("文档中没有可读取的文本片段")
    checkpoints = [_u32(plc, 4 * k) for k in range(pieces + 1)]
    parts: list[str] = []
    for k in range(pieces):
        pcd = 4 * (pieces + 1) + 8 * k
        fc = _u32(plc, pcd + 2)
        offset = fc & 0x3FFFFFFF
        chars = checkpoints[k + 1] - checkpoints[k]
        if fc & 0x40000000:  # 单字节 ANSI 片段
            start = offset // 2
            parts.append(word[start:start + chars].decode(ansi, "replace"))
        else:  # UTF-16LE 片段
            parts.append(word[offset:offset + chars * 2].decode("utf-16le", "replace"))
    return _clean_doc_text("".join(parts))


def _read_doc(path: Path, warnings: list[str]) -> str:
    raw = path.read_bytes()
    if raw[:8] == _Ole2File._SIGNATURE:
        return _clip(_read_doc_binary(path, raw), warnings, "文档")
    # 有些系统导出的 .doc 其实是 HTML 或 Word 2003 XML；按网页降级解析。
    parser = _TextHTMLParser()
    parser.feed(_decode_text(raw, meta_charset=True))
    parser.close()
    text = parser.text() or _decode_text(raw).replace("\r\n", "\n")
    warnings.append("不是标准 Word 二进制格式，已按文本读取；如有乱码请另存为 .docx")
    return _clip(text, warnings, "文档")


# --- Excel 97-2003（.xls / BIFF8） -----------------------------------------

_BIFF_BOF = 0x0809
_BIFF_EOF = 0x000A
_BIFF_BOUNDSHEET = 0x0085
_BIFF_SST = 0x00FC
_BIFF_CONTINUE = 0x003C
_BIFF_LABELSST = 0x00FD
_BIFF_LABEL = 0x0204
_BIFF_NUMBER = 0x0203
_BIFF_RK = 0x027E
_BIFF_MULRK = 0x00BD
_BIFF_FORMULA = 0x0006
_BIFF_STRING = 0x0207
_BIFF_BOOLERR = 0x0205


def _biff_records(stream: bytes, start: int = 0):
    """逐条吐出 (记录类型, 数据体)；遇到 EOF 或越界即止。"""

    pos = start
    total = len(stream)
    while pos + 4 <= total:
        kind = _u16(stream, pos)
        size = _u16(stream, pos + 2)
        body = stream[pos + 4:pos + 4 + size]
        pos += 4 + size
        yield kind, body
        if kind == _BIFF_EOF:
            break


def _biff_string_at(body: bytes, offset: int) -> str:
    """BIFF8 的 XLUnicodeString（短字符串，不含 CONTINUE 跨段）。"""

    if offset + 3 > len(body):
        return ""
    count = _u16(body, offset)
    flags = body[offset + 2]
    pos = offset + 3
    if flags & 0x08:  # 富文本 run 计数
        pos += 2
    if flags & 0x04:  # 扩展数据长度
        pos += 4
    if flags & 0x01:
        return body[pos:pos + count * 2].decode("utf-16le", "replace")
    return body[pos:pos + count].decode("latin-1", "replace")


class _SegCursor:
    """SST 会被 CONTINUE 切成多段；这里按段推进，跨段时由调用方换编码标志。"""

    def __init__(self, segments: list[bytes]) -> None:
        self._segments = segments or [b""]
        self._index = 0
        self._pos = 0

    def remaining(self) -> int:
        return len(self._segments[self._index]) - self._pos

    def next_segment(self) -> bool:
        if self._index + 1 >= len(self._segments):
            return False
        self._index += 1
        self._pos = 0
        return True

    def read(self, count: int) -> bytes:
        out = bytearray()
        while count > 0:
            if self.remaining() <= 0 and not self.next_segment():
                raise IngestError("共享字符串表被截断")
            take = min(count, self.remaining())
            segment = self._segments[self._index]
            out += segment[self._pos:self._pos + take]
            self._pos += take
            count -= take
        return bytes(out)

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_u16(self) -> int:
        return _u16(self.read(2), 0)

    def read_u32(self) -> int:
        return _u32(self.read(4), 0)

    def skip(self, count: int) -> None:
        while count > 0:
            if self.remaining() <= 0 and not self.next_segment():
                return
            take = min(count, self.remaining())
            self._pos += take
            count -= take


def _sst_string(cursor: _SegCursor) -> str:
    """XLUnicodeRichExtendedString：字符数据可能刚好被段边界切开。"""

    count = cursor.read_u16()
    flags = cursor.read_u8()
    high = bool(flags & 0x01)
    runs = cursor.read_u16() if flags & 0x08 else 0
    extra = cursor.read_u32() if flags & 0x04 else 0

    parts: list[str] = []
    left = count
    while left > 0:
        width = 2 if high else 1
        room = cursor.remaining()
        if room < width:
            # 换段后第一个字节是新的 fHighByte，不是字符数据。
            if not cursor.next_segment():
                break
            high = bool(cursor.read_u8() & 0x01)
            continue
        take = min(left, room // width)
        raw = cursor.read(take * width)
        parts.append(raw.decode("utf-16le" if high else "latin-1", "replace"))
        left -= take
    cursor.skip(runs * 4)
    cursor.skip(extra)
    return "".join(parts)


def _parse_sst(segments: list[bytes]) -> list[str]:
    if not segments or len(segments[0]) < 8:
        return []
    cursor = _SegCursor(segments)
    cursor.read_u32()  # 总引用数，用不到
    unique = cursor.read_u32()
    strings: list[str] = []
    for _ in range(max(0, unique)):
        strings.append(_sst_string(cursor))
    return strings


def _rk_number(raw: int) -> float:
    """RK：bit0 = 除以 100，bit1 = 30 位整数，否则高 30 位是 double 的高位。"""

    if raw & 0x02:
        value = raw >> 2
        if value & 0x20000000:
            value -= 0x40000000
        number = float(value)
    else:
        number = struct.unpack("<d", struct.pack("<Q", (raw & 0xFFFFFFFC) << 32))[0]
    return number / 100.0 if raw & 0x01 else number


def _parse_sheet(stream: bytes, start: int, strings: list[str],
                 warnings: list[str], title: str) -> str:
    """从 BoundSheet8 指向的位置读一张工作表，返回 Markdown 表格。"""

    cells: dict[int, dict[int, Any]] = {}
    pending: tuple[int, int] | None = None

    for kind, body in _biff_records(stream, start):
        if kind == _BIFF_EOF:
            break
        if kind == _BIFF_LABELSST and len(body) >= 10:
            row, column = _u16(body, 0), _u16(body, 2)
            index = _u32(body, 6)
            cells.setdefault(row, {})[column] = (
                strings[index] if 0 <= index < len(strings) else ""
            )
        elif kind == _BIFF_LABEL and len(body) >= 6:
            row, column = _u16(body, 0), _u16(body, 2)
            cells.setdefault(row, {})[column] = _biff_string_at(body, 6)
        elif kind == _BIFF_NUMBER and len(body) >= 14:
            row, column = _u16(body, 0), _u16(body, 2)
            cells.setdefault(row, {})[column] = struct.unpack_from("<d", body, 6)[0]
        elif kind == _BIFF_RK and len(body) >= 10:
            row, column = _u16(body, 0), _u16(body, 2)
            cells.setdefault(row, {})[column] = _rk_number(_u32(body, 6))
        elif kind == _BIFF_MULRK and len(body) >= 12:
            row = _u16(body, 0)
            first = _u16(body, 2)
            for offset in range((len(body) - 6) // 6):
                value = _rk_number(_u32(body, 4 + offset * 6 + 2))
                cells.setdefault(row, {})[first + offset] = value
        elif kind == _BIFF_FORMULA and len(body) >= 20:
            row, column = _u16(body, 0), _u16(body, 2)
            marker = _u16(body, 6)
            if marker == 0xFFFF:
                code = body[8]
                if code == 0:  # 字符串结果放在紧随其后的 STRING 记录
                    pending = (row, column)
                elif code == 1:  # 布尔
                    cells.setdefault(row, {})[column] = "TRUE" if body[9] else "FALSE"
            else:
                cells.setdefault(row, {})[column] = struct.unpack_from("<d", body, 6)[0]
        elif kind == _BIFF_STRING and pending is not None:
            cells.setdefault(pending[0], {})[pending[1]] = _biff_string_at(body, 0)
            pending = None
        elif kind == _BIFF_BOOLERR and len(body) >= 8 and body[7] == 0:
            row, column = _u16(body, 0), _u16(body, 2)
            cells.setdefault(row, {})[column] = "TRUE" if body[6] else "FALSE"

    if not cells:
        return ""
    last_row = max(cells)
    if last_row + 1 > _MAX_ROWS:
        warnings.append("工作表 {} 超过 {} 行，已截断".format(title, _MAX_ROWS))
        last_row = _MAX_ROWS - 1
    rows: list[list[Any]] = []
    for row in range(last_row + 1):
        line = cells.get(row) or {}
        if not line:
            rows.append([])
            continue
        width = max(line) + 1
        rows.append([line.get(column, "") for column in range(width)])
    return _markdown_table(rows, warnings, "工作表 " + title)


def _read_xls_biff8(raw: bytes, warnings: list[str]) -> str:
    container = _Ole2File(raw)
    stream = container.stream("Workbook") or container.stream("Book")
    if not stream:
        raise IngestError("表格里找不到 Workbook 流")

    segments: list[bytes] = []
    sheets: list[tuple[int, str]] = []
    collecting = False
    for kind, body in _biff_records(stream, 0):
        if kind == _BIFF_SST:
            segments = [body]
            collecting = True
            continue
        if kind == _BIFF_CONTINUE and collecting:
            segments.append(body)
            continue
        collecting = False
        if kind == _BIFF_BOUNDSHEET and len(body) >= 8:
            offset = _u32(body, 0)
            length = body[6]
            if body[7] & 0x01:
                name = body[8:8 + length * 2].decode("utf-16le", "replace")
            else:
                name = body[8:8 + length].decode("latin-1", "replace")
            sheets.append((offset, name or "工作表"))
        if kind == _BIFF_EOF:
            break

    strings = _parse_sst(segments) if segments else []
    lines: list[str] = []
    for offset, name in sheets:
        table = _parse_sheet(stream, offset, strings, warnings, name)
        if table:
            lines.append("【工作表：{}】".format(name))
            lines.append(table)
    return _clip("\n".join(lines), warnings, "表格")


def _read_xls(path: Path, warnings: list[str]) -> str:
    raw = path.read_bytes()
    if raw[:8] == _Ole2File._SIGNATURE:
        return _read_xls_biff8(raw, warnings)
    # 不少国内系统导出的「.xls」其实是 HTML 表格或制表符分隔文本。
    head = raw[:4096].lstrip().lower()
    if head.startswith(b"<") or b"<table" in head:
        parser = _TextHTMLParser()
        parser.feed(_decode_text(raw, meta_charset=True))
        parser.close()
        warnings.append("该 .xls 实际是网页格式，已按表格解析")
        return _clip(parser.text() or "", warnings, "表格")
    warnings.append("该 .xls 不是 Excel 二进制格式，已按纯文本读取")
    return _clip(_decode_text(raw).replace("\r\n", "\n"), warnings, "表格")


# --- 选型要求闸口 -----------------------------------------------------------

REQUIREMENT_TERMS = (
    "秤", "称重", "称量", "衡器", "地磅", "磅", "传感器", "仪表", "接线盒",
    "量程", "精度", "分度值", "台面", "材质", "防爆", "不锈钢", "碳钢",
    "规格", "型号", "品牌", "载重", "吨位", "容量", "平台", "模块",
    "报价", "单价", "数量", "采购", "询价", "需求", "参数",
    "kg", "mm", "吨",
    # 外贸报价单常常整份英文，只看中文词会把它们全挡在外面。
    "scale", "weigh", "load cell", "capacity", "platform", "steel",
    "material", "model", "quantity", "qty", "price", "indicator",
    "sensor", "deck", "explosion",
)
_REQUIREMENT_MIN_CHARS = 6


def has_requirement(text: str) -> bool:
    """粗判一段转写稿是否像选型需求。

    判据刻意保守：既没有选型要素词、又短得不像清单的，一律挡回去——让
    模型拿到一份无关文件只会瞎猜字段，比直接拒绝更糟。
    """

    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < _REQUIREMENT_MIN_CHARS:
        return False
    lowered = compact.lower()
    return any(term in lowered for term in REQUIREMENT_TERMS)


class _TextHTMLParser(HTMLParser):
    """把 HTML 降解成按行排列的纯文本，表格单元格用竖线分隔。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif not self._skip:
            if tag in _CELL_TAGS:
                self._chunks.append(" | ")
            elif tag in _BLOCK_TAGS:
                self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag in _BLOCK_TAGS and not self._skip:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif not self._skip and tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        lines: list[str] = []
        for line in "".join(self._chunks).splitlines():
            line = re.sub(r"[ \t\r\f\v\u00a0]+", " ", line).strip()
            line = re.sub(r"^(\|\s*)+", "", line)
            line = re.sub(r"(\s*\|)+$", "", line)
            if line:
                lines.append(line)
        return "\n".join(lines)


def _read_html(path: Path, warnings: list[str]) -> str:
    parser = _TextHTMLParser()
    parser.feed(_decode_text(path.read_bytes(), meta_charset=True))
    parser.close()
    text = parser.text()
    if not text:
        warnings.append("网页中未找到可读取的文本内容")
    return _clip(text, warnings, "网页")


def read_document(path: Any, warnings: list[str] | None = None) -> str:
    """本地读取文本类文件，不发任何网络请求。"""

    target = Path(path)
    notes = warnings if warnings is not None else []
    suffix = suffix_of(target)
    if suffix not in TEXT_SUFFIXES:
        raise IngestError("不支持的文件类型：{}".format(suffix or "(无扩展名)"))
    if not target.is_file():
        raise IngestError("找不到文件：{}".format(target.name))
    reader = {
        ".txt": _read_text,
        ".md": _read_text,
        ".csv": _read_csv,
        ".xlsx": _read_xlsx,
        ".xlsm": _read_xlsx,
        ".xls": _read_xls,
        ".docx": _read_docx,
        ".doc": _read_doc,
        ".html": _read_html,
        ".htm": _read_html,
    }[suffix]
    try:
        return reader(target, notes)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("读取 {} 失败：{}".format(target.name, exc)) from None


def ingest(path: Any) -> IngestResult:
    """抽取单个文件，返回带来源标记的转写稿。"""

    target = Path(path)
    suffix = suffix_of(target)
    warnings: list[str] = []
    if suffix == ".pdf":
        raise IngestError(
            "本版暂不支持 PDF，请先另存为 {} 后再导入".format(SUPPORTED_HINT)
        )
    if suffix not in TEXT_SUFFIXES:
        raise IngestError(
            "本版暂不支持 {} 格式；请自行转换为 {} 后再导入".format(
                suffix or "(无扩展名)", SUPPORTED_HINT
            )
        )
    if not target.is_file():
        raise IngestError("找不到文件：{}".format(target.name))

    text = read_document(target, warnings)
    if not text.strip():
        raise IngestError("文件 {} 没有抽取到可用文本".format(target.name))
    warnings.append("来源：{} / 本地读取".format(target.name))
    return IngestResult(text, target.name, warnings)


__all__ = [
    "FILE_FILTER", "IngestError", "IngestResult", "REQUIREMENT_TERMS",
    "SUPPORTED_HINT", "compose_message", "has_requirement", "ingest",
    "is_supported", "read_document",
]
