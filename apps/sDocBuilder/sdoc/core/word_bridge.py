# -*- coding: utf-8 -*-
"""办公软件 COM 桥：docx -> PDF（预览所见即办公软件所得）。

多引擎探测链：Word -> WPS(KWPS/WPS) -> LibreOffice CLI -> 放弃(None)。
- Word/WPS 走 COM：可刷新目录/页码域，PDF 预览自带目录页码；
- LibreOffice 走 CLI 转换：不更新目录域（PDF 目录无页码，文档本体不受影响）；
- 均不可用时返回 None，调用方回退到 HTML 摘要预览。

update_fields 仅走 COM 链（LibreOffice 刷新 TOC 需宏注入，不值得）；
失败静默——交付 docx 恒有效，目录最多待用户打开时 F9。
"""
import os
import shutil
import subprocess
from typing import Any

# COM 探测顺序：微软 Word -> 金山 WPS 文字（个人版 KWPS / 旧版 WPS 注册名）
_COM_PROGIDS = ("Word.Application", "KWPS.Application", "WPS.Application")

# LibreOffice 常见安装位置（机器无任何 COM 办公软件时的 CLI 兜底）
_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


def _find_soffice():
    """定位 soffice.exe：PATH 优先，再探常见安装目录；找不到返回 None"""
    exe = shutil.which("soffice")
    if exe:
        return exe
    for path in _SOFFICE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _dispatch_office(win32com_client):
    """按探测链创建 Word/WPS COM 实例；全部失败返回 (None, None)。
    DispatchEx 独立进程实例，不干扰用户已打开的文档窗口。"""
    for progid in _COM_PROGIDS:
        try:
            return win32com_client.DispatchEx(progid), progid
        except Exception:
            continue
    return None, None


def _open_doc(app: Any, docx_path: str, read_only: bool):
    """打开文档：先按 Word 命名参数，失败（WPS 个别版本签名出入）退
    位置参数 Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)"""
    try:
        return app.Documents.Open(docx_path, ReadOnly=read_only,
                                  AddToRecentFiles=False)
    except Exception:
        return app.Documents.Open(docx_path, False, read_only, False)


def _export_pdf(doc: Any, pdf_path: str) -> None:
    """导出 PDF：ExportAsFixedFormat 失败时退 SaveAs2(wdFormatPDF=17)
    （两者 Word/WPS 均支持，双保险覆盖签名出入）"""
    try:
        doc.ExportAsFixedFormat(OutputFileName=pdf_path, ExportFormat=17)
    except Exception:
        doc.SaveAs2(pdf_path, 17)


def docx_to_pdf(docx_path: str, pdf_path: str) -> "str | None":
    """把 docx 经 Word/WPS/LibreOffice 导出为 PDF；成功返回 pdf_path，
    全部引擎不可用或转换失败返回 None。
    目标已存在先删除；COM 偶发失败重试一次。"""
    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.exists(docx_path):
        return None
    for attempt in (1, 2):
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except OSError:
            pass
        result = _export_via_com(docx_path, pdf_path)
        if result:
            return result
        # COM 链不可用（重试也无济于事）时才落 LibreOffice 兜底，
        # 放在重试循环外层判断会重复跑 LO，这里仅在第二次尝试后执行
        if attempt == 2:
            result = _export_via_lo(docx_path, pdf_path)
            if result:
                return result
    return None


def _export_via_com(docx_path: str, pdf_path: str) -> "str | None":
    """Word/WPS COM 导出；任一环节失败返回 None（由调用方决定重试/兜底）"""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    pythoncom.CoInitialize()
    # COM 动态对象显式标 Any：先置 None、finally 里再收尾（try/except
    # 兜底未成功创建的情形），否则静态检查把此处推断成 None
    app: Any = None
    doc: Any = None
    try:
        app, _progid = _dispatch_office(win32com.client)
        if app is None:
            return None
        app.Visible = False
        app.DisplayAlerts = 0
        doc = _open_doc(app, docx_path, read_only=True)
        try:
            doc.Fields.Update()        # 目录/页码域刷新，PDF 即带目录
        except Exception:
            pass
        _export_pdf(doc, pdf_path)
        return pdf_path if os.path.exists(pdf_path) else None
    except Exception:
        return None
    finally:
        for close in (lambda: doc.Close(False), lambda: app.Quit()):
            try:
                close()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _export_via_lo(docx_path: str, pdf_path: str) -> "str | None":
    """LibreOffice CLI 兜底转换（目录域不更新）；失败返回 None"""
    soffice = _find_soffice()
    if not soffice:
        return None
    out_dir = os.path.dirname(pdf_path)
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", out_dir, docx_path],
            timeout=180,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True)
    except Exception:
        return None
    # LO 以输入文件主名落 PDF；目标名不同则挪过去
    produced = os.path.splitext(docx_path)[0] + ".pdf"
    if not os.path.exists(produced):
        return None
    if os.path.abspath(produced) != os.path.abspath(pdf_path):
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            os.replace(produced, pdf_path)
        except OSError:
            return None
    return pdf_path if os.path.exists(pdf_path) else None


def update_fields(docx_path: str) -> bool:
    """正式输出的 docx 落盘更新域（目录带页码）；Word/WPS 均不可用或
    失败时静默返回 False（文档仍有效，目录待用户打开时 F9）"""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    docx_path = os.path.abspath(docx_path)
    if not os.path.exists(docx_path):
        return False
    pythoncom.CoInitialize()
    app: Any = None
    doc: Any = None
    try:
        app, _progid = _dispatch_office(win32com.client)
        if app is None:
            return False
        app.Visible = False
        app.DisplayAlerts = 0
        doc = _open_doc(app, docx_path, read_only=False)
        try:
            doc.Fields.Update()
            for toc in doc.TablesOfContents:
                toc.Update()
        except Exception:
            pass
        doc.Save()
        return True
    except Exception:
        return False
    finally:
        for close in (lambda: doc.Close(False), lambda: app.Quit()):
            try:
                close()
            except Exception:
                pass
        pythoncom.CoUninitialize()
