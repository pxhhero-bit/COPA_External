"""Headless/Checklist entry point for LLM translated quote payloads.

The command intentionally owns orchestration only.  Parsing and contract
translation live in :mod:`apps.llm_io` and :mod:`apps.contract`; product
selection remains the existing ``EngineService``.  Importing this module does
not import PySide6, so ``--print-schema`` and ``--print-prompt`` remain useful
on a machine without a GUI runtime.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.dirname(_PROJECT_ROOT)
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)


EXIT_OK = 0
EXIT_CONTRACT = 1
EXIT_ENGINE = 2
EXIT_ENVIRONMENT = 3

_ORIGIN = "llm"


class _EnvironmentFailure(Exception):
    """A local runtime/data problem, classified as exit code 3."""


def _json_default(value):
    """Keep archives readable when a legacy engine returns a non-JSON value."""
    try:
        return str(value)
    except Exception:
        return repr(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(session_dir: Path) -> Path:
    """List the archive products so a run can be restored without guesswork."""

    files = []
    for path in sorted(session_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        files.append({"name": path.name, "bytes": size})
    target = session_dir / "manifest.json"
    _write_json(target, {
        "session": session_dir.name,
        "files": files,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    })
    return target


def export_generated(root: Any = None) -> list[Path]:
    """Regenerate ``llm/generated/prompt.txt`` and ``schema.json`` together."""

    from COPA.apps.contract import print_prompt, print_schema

    base = Path(root) if root is not None else _runtime_root() / "llm" / "generated"
    base.mkdir(parents=True, exist_ok=True)
    prompt_path = base / "prompt.txt"
    schema_path = base / "schema.json"
    prompt_path.write_text(print_prompt(), encoding="utf-8")
    _write_json(schema_path, print_schema())
    return [prompt_path, schema_path]


def _safe_project_name(value: Any) -> str:
    """Map a project label to a stable directory component."""
    text = str(value or "未命名项目").strip()
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:80] or "未命名项目"


def _runtime_root() -> Path:
    """归档根目录：源码运行取项目根，打包后取 exe 所在目录。

    冻结态的 ``__file__`` 指向 _internal 里的模块占位，照它写盘会让归档
    藏进 _internal\\llm\\sessions，现场找不着；跟随 exe 才符合「就在程序旁边」。
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(_PROJECT_ROOT)


def _session_dir(project: Any, *, root: Any = None,
                 now: datetime | None = None) -> Path:
    """Create the per-run archive directory and return it."""
    base = Path(root) if root is not None else _runtime_root() / "llm" / "sessions"
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    stem = "{}_{}".format(stamp, _safe_project_name(project))
    path = base / stem
    suffix = 2
    while path.exists():
        path = base / "{}-{}".format(stem, suffix)
        suffix += 1
    path.mkdir(parents=True, exist_ok=True)
    return path


def _errors_from(exc: Exception) -> list:
    errors = getattr(exc, "errors", None)
    if errors:
        return list(errors)
    return [{"path": "$", "code": "ERROR", "message": str(exc)}]


def _format_error(error: Any) -> str:
    if isinstance(error, Mapping):
        path = error.get("path", "$")
        code = error.get("code", "ERROR")
        message = error.get("message", "")
        return "{} [{}] {}".format(path, code, message).rstrip()
    return str(error)


def _print_contract_errors(exc: Exception) -> None:
    for error in _errors_from(exc):
        print("契约错误：{}".format(_format_error(error)), file=sys.stderr)


def _input_error_exit(exc: Exception) -> int:
    if isinstance(exc, (OSError, ImportError)):
        return EXIT_ENVIRONMENT
    return (EXIT_ENVIRONMENT if any(
        isinstance(error, Mapping) and error.get("code") == "ENVIRONMENT"
        for error in _errors_from(exc)
    ) else EXIT_CONTRACT)


def _contract_error(errors: Sequence[Any]) -> Exception:
    """Build the shared ContractError while tolerating small API variations."""
    from COPA.apps.contract import ContractError

    normalized = []
    for error in errors:
        if isinstance(error, Mapping):
            normalized.append(dict(error))
        else:
            normalized.append({"path": "$", "code": "CONTRACT",
                               "message": str(error)})
    return ContractError(normalized)


def _project_from_payload(payload: Mapping[str, Any], override: str | None = None) -> str:
    if override:
        return str(override).strip() or "未命名项目"
    quote = payload.get("quote") or {}
    return str(quote.get("project") or "未命名项目").strip()


def _prepare_entries(payload: Mapping[str, Any]):
    """Validate, translate strictly, and tag entries for the engine call."""
    from COPA.apps.contract import build_engine_input, payload_to_entries

    entries = payload_to_entries(payload)
    entries = list(entries or [])
    errors = []

    for index, entry in enumerate(entries):
        entry["_origin"] = payload.get("origin") or _ORIGIN
        try:
            entry["_engine_input"] = build_engine_input(entry, strict=True)
        except Exception as exc:
            for error in _errors_from(exc):
                item = dict(error) if isinstance(error, Mapping) else {
                    "path": "items[{}]".format(index),
                    "code": "MISSING_FIELD",
                    "message": str(error),
                }
                path = str(item.get("path") or "")
                if not path.startswith("items["):
                    item["path"] = "items[{}].{}".format(index, path.lstrip("."))
                errors.append(item)

    if errors:
        raise _contract_error(errors)

    return entries


def _run_engine(entries: Sequence[Mapping[str, Any]]):
    """Run the existing service once and return ``(results, captured_log)``."""
    try:
        from COPA.apps.Desk import EngineService
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        raise _EnvironmentFailure("EngineService 无法加载：{}".format(exc)) from exc

    class StrictEngineService(EngineService):
        def _build_input(self, entry):
            return entry["_engine_input"]

    service = StrictEngineService()

    output = io.StringIO()
    try:
        with redirect_stdout(output), redirect_stderr(output):
            results = service.run_batch(list(entries))
    except (FileNotFoundError, ImportError, ModuleNotFoundError, OSError) as exc:
        raise _EnvironmentFailure("本地数据/运行环境不可用：{}".format(exc)) from exc
    return list(results or []), output.getvalue()


def _failure_reason(result: Mapping[str, Any]) -> str:
    from COPA.apps.contract import _failure_reason as shared
    return shared(result)


def _stage_counts(result: Mapping[str, Any]) -> Mapping[str, Any]:
    from COPA.apps.contract import _DIAGNOSTIC_KEYS
    if isinstance(result.get("stage_counts"), Mapping):
        return result["stage_counts"]
    for key in _DIAGNOSTIC_KEYS:
        diagnostic = result.get(key)
        if isinstance(diagnostic, Mapping) and isinstance(
                diagnostic.get("stage_counts"), Mapping):
            return diagnostic["stage_counts"]
    return {}


def _failure_records(results: Iterable[Mapping[str, Any]]) -> list:
    records = []
    for result in results:
        status = str(result.get("status") or "").upper()
        if status not in ("ERROR", "NO_MATCH"):
            continue
        records.append({
            "quote_id": result.get("quote_id"),
            "item_type": result.get("item_type"),
            "status": status,
            "reason": _failure_reason(result),
            "stage_counts": dict(_stage_counts(result)),
        })
    return records


def _attach_fallback(result: Mapping[str, Any], entry: Mapping[str, Any]):
    """Build a Checklist-only candidate result for a NO_MATCH row."""
    candidate = copy.deepcopy(dict(result))
    try:
        from COPA.apps.fallback import attach_fallback
        candidate = attach_fallback(candidate, entry) or candidate
    except Exception as exc:
        # A missing fallback module should not erase the original diagnostic;
        # Checklist will still render its normal "无匹配" row.
        candidate.setdefault("warnings", []).append(
            "候选构造失败：{}".format(exc))
    candidate["_origin"] = entry.get("_origin") or _ORIGIN
    return candidate


def _entry_by_id(entries: Sequence[Mapping[str, Any]]) -> dict:
    result = {}
    for entry in entries:
        info = entry.get("quote_info") or {}
        if info.get("quote_id") is not None:
            result[info["quote_id"]] = entry
    return result


def _attach_validation_warnings(entries, warnings):
    """Route contract warning messages to their corresponding Checklist row."""
    for warning in warnings or []:
        if not isinstance(warning, Mapping):
            continue
        path = str(warning.get("path") or "")
        match = re.match(r"items\[(\d+)\]", path)
        if match is None:
            continue
        index = int(match.group(1))
        if index < 0 or index >= len(entries):
            continue
        message = (warning.get("message") or warning.get("reason")
                   or warning.get("code") or "")
        if not message:
            continue
        entries[index].setdefault("warnings", []).append(str(message))


def _warnings_for(entry: Mapping[str, Any], result: Mapping[str, Any]) -> list:
    values = []
    for source in (entry.get("warnings"), entry.get("_warnings"),
                   result.get("warnings"), result.get("_warnings")):
        if isinstance(source, Mapping):
            message = (source.get("message") or source.get("reason")
                       or source.get("code") or "")
            if message:
                values.append(str(message))
        elif isinstance(source, str):
            values.append(source)
        elif isinstance(source, Iterable) and not isinstance(source, Mapping):
            values.extend(str(item) for item in source if item)
    # R3 may expose the confirmation hint under a single field instead of a
    # warning list.  Keep it visible without inventing a second validation.
    if entry.get("confirmed_nonstandard") and not any("非标" in value for value in values):
        parsed = entry.get("parsed") or {}
        fields = parsed.get("data") if isinstance(parsed, Mapping) else {}
        size = (entry.get("nonstandard_size")
                or (fields or {}).get("台面尺寸"))
        provenance = entry.get("provenance")
        record = provenance.get("台面尺寸") if isinstance(provenance, Mapping) else None
        downgraded = isinstance(record, Mapping) and record.get("source") == "size_downgraded"
        if downgraded:
            values.append(
                "非标台面尺寸：{}（已降级为最近标准规格，输出后需人工改回）".format(
                    size or "待复核")
            )
        else:
            values.append("非标台面尺寸：{}（已确认）".format(size or "待复核"))
    if result.get("fallback_note"):
        values.append(str(result["fallback_note"]))
    return list(dict.fromkeys(values))


def _mark_checklist_warnings(checklist, entries, results):
    """Annotate rows through existing Qt objects; Checklist source is untouched."""
    from PySide6.QtWidgets import QLabel

    by_id = _entry_by_id(entries)
    rows = list(checklist._iter_items()) if hasattr(checklist, "_iter_items") else []
    for row in rows:
        try:
            quote_id = int(row.label_ID.text())
        except (TypeError, ValueError):
            quote_id = row.label_ID.text()
        entry = by_id.get(quote_id, {})
        result = next((r for r in results if r.get("quote_id") == quote_id), {})
        warnings = _warnings_for(entry, result)
        if not warnings:
            continue
        text = "\n".join("提示：{}".format(value) for value in warnings)
        row.setProperty("llm_warnings", warnings)
        row.setToolTip(text)
        # Keep the Checklist module unchanged: add a small warning row beside
        # the existing QuoteListItem in its already-owned layout.
        object_name = "llmWarning_{}".format(quote_id)
        existing = checklist.findChild(QLabel, object_name)
        if existing is None:
            existing = QLabel(checklist.ChecklistContainer)
            existing.setObjectName(object_name)
            index = checklist.checklistLayout.indexOf(row)
            checklist.checklistLayout.insertWidget(index + 1, existing)
        existing.setText(text)
        existing.setWordWrap(True)
        existing.setToolTip(text)
        existing.setStyleSheet("color:#a15c00; padding-left:72px;")
        existing.show()
    checklist._refresh_scroll_area()


def _set_checklist_defaults(checklist, payload, project):
    quote = payload.get("quote") or {}
    title = quote.get("quote_title")
    combo = getattr(checklist, "titalComBox", None)
    if title and combo is not None and combo.findText(str(title)) >= 0:
        combo.setCurrentText(str(title))
    if project:
        checklist.setWindowTitle("选型清单 - {}".format(project))


def _save_cli_snapshot(session_dir: Path, project: str, entries, checklist) -> Path:
    """Save a successful Checklist run using Snapshot's existing renderer."""
    from COPA.apps import Snapshot

    class HeadlessDesk:
        def __init__(self, values):
            self._values = values
            self.serviceCheckBox = checklist.serviceCheckBox_1

        def collect_entries(self):
            return self._values

    target = session_dir / "snapshot.md"
    path = Path(Snapshot.save_snapshot(
        str(target), project, HeadlessDesk(entries), checklist=checklist))
    # Older Snapshot renderers do not know about provenance.  Add a harmless
    # markdown comment so the archive itself records the source without
    # changing the human-facing tables or restore parser.
    text = path.read_text(encoding="utf-8-sig")
    if "_origin" not in text:
        text = "<!-- _origin: llm -->\n" + text
        path.write_text(text, encoding="utf-8-sig", newline="\n")
    return path


def _show_no_match(checklist, results):
    failures = [r for r in results
                if str(r.get("status") or "").upper() == "NO_MATCH"]
    if not failures:
        return
    from PySide6.QtWidgets import QMessageBox
    lines = ["条目 {}：{}".format(r.get("quote_id") or 0,
                                 _failure_reason(r))
             for r in failures]
    QMessageBox.warning(
        checklist,
        "选型未匹配",
        "以下条目没有直接匹配，请在清单中确认候选：\n\n{}".format(
            "\n".join(lines)),
    )


def _start_checklist(payload, project, entries, results, session_dir) -> int:
    """Open Checklist directly, without creating Desk or Commander."""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        from COPA.apps.Checklist import Checklist
    except Exception as exc:
        print("环境错误：Qt/Checklist 无法启动：{}".format(exc), file=sys.stderr)
        return EXIT_ENVIRONMENT

    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        checklist = Checklist()
        _set_checklist_defaults(checklist, payload, project)
        checklist.load_results(results, entries)
        _mark_checklist_warnings(checklist, entries, results)

        def on_rollback():
            QMessageBox.information(
                checklist,
                "返回需求录入",
                "当前为 JSON 导入模式，回退请修改 JSON 后重新运行。",
            )

        def on_output():
            try:
                path = _save_cli_snapshot(session_dir, project, entries, checklist)
                print("项目快照已保存：{}".format(path))
            except Exception as exc:
                print("警告：项目快照保存失败：{}".format(exc), file=sys.stderr)

        checklist.rollbackRequested.connect(on_rollback)
        checklist.outputSucceeded.connect(on_output)
        checklist.show()
        # Keep the warning out of Checklist's constructor/load path so rows are
        # painted before the diagnostic dialog appears.
        QTimer.singleShot(0, lambda: _show_no_match(checklist, results))
        return int(app.exec())
    except Exception as exc:
        print("环境错误：Checklist 启动失败：{}".format(exc), file=sys.stderr)
        return EXIT_ENVIRONMENT


def _write_failures(session_dir: Path, failures: Sequence[Mapping[str, Any]]) -> None:
    if not failures:
        return
    payload: Any
    if len(failures) == 1:
        payload = dict(failures[0])
    else:
        payload = {"failures": list(failures)}
    _write_json(session_dir / "fail.json", payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m COPA.cli_quote",
        description="运行 LLM 翻译后的报价 JSON，并进入人工确认清单",
    )
    parser.add_argument("input", nargs="?", help="quote.json、raw.txt 或原始 JSON 文本")
    parser.add_argument("--no-gui", action="store_true",
                        help="仅打印摘要，不启动 Checklist")
    parser.add_argument("--project", help="覆盖归档目录使用的项目名")
    parser.add_argument("--sessions-dir", help="会话归档根目录（测试/隔离运行用）")
    parser.add_argument("--print-schema", action="store_true",
                        help="打印当前 JSON schema")
    parser.add_argument("--print-prompt", action="store_true",
                        help="打印给 LLM 的完整 system prompt")
    parser.add_argument("--export-generated", action="store_true",
                        help="重新导出 llm/generated/prompt.txt 与 schema.json")
    return parser


@dataclass
class QuoteRun:
    payload: dict
    project: str
    exit_code: int = 0
    error: str = ""
    session_dir: Path | None = None
    entries: list = field(default_factory=list)
    results: list = field(default_factory=list)
    checklist_results: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def run_payload(
    payload: dict,
    *,
    project: str | None = None,
    session_root: Any = None,
    llm_events: Sequence[Mapping[str, Any]] | None = None,
) -> QuoteRun:
    """Select an already-confirmed payload in memory; shared by CLI and chat UI.

    Files are archives only. No JSON hand-off file or nested QApplication is
    required by callers. The engine and all strict translation stay shared.

    Program normalization runs here as well, so a payload written by hand or
    piped through the CLI gets the same W_total / c_brand handling as the GUI.
    """
    from COPA.apps.contract import normalize_generated_marks, validate_payload
    from COPA.apps.llm_chat import normalize_program_defaults

    payload = normalize_program_defaults(
        normalize_generated_marks(copy.deepcopy(payload))
    )
    run = QuoteRun(payload=payload, project=_project_from_payload(payload, project))

    def finish(code, error=""):
        run.exit_code = code
        run.error = error
        return run

    project = run.project
    try:
        session_dir = _session_dir(
            project,
            root=session_root,
        )
        run.session_dir = session_dir
        _write_json(session_dir / "quote.json", payload)
    except Exception as exc:
        print("环境错误：无法建立会话归档：{}".format(exc), file=sys.stderr)
        return finish(EXIT_ENVIRONMENT, str(exc))

    try:
        warnings = validate_payload(payload) or []
        for warning in warnings:
            print("警告：{}".format(_format_error(warning)))
        run.warnings = warnings
        entries = _prepare_entries(payload)
        run.entries = entries
        _attach_validation_warnings(entries, warnings)
    except Exception as exc:
        _print_contract_errors(exc)
        try:
            (session_dir / "run.log").write_text(
                "契约错误：\n{}\n".format("\n".join(
                    _format_error(e) for e in _errors_from(exc))),
                encoding="utf-8",
            )
        except Exception:
            pass
        return finish(_input_error_exit(exc), str(exc))

    entry_map = _entry_by_id(entries)
    try:
        results, run_log = _run_engine(entries)
    except _EnvironmentFailure as exc:
        message = "环境错误：{}".format(exc)
        print(message, file=sys.stderr)
        try:
            (session_dir / "run.log").write_text(message + "\n", encoding="utf-8")
        except Exception:
            pass
        return finish(EXIT_ENVIRONMENT, str(exc))
    except Exception as exc:
        # A batch-level exception has no engine result to archive. Materialise
        # one ERROR result per input so fail.json keeps the normal shape.
        message = "选型计算异常：{}".format(exc)
        results = [{
            "quote_id": (entry.get("quote_info") or {}).get("quote_id"),
            "item_type": entry.get("item_type"),
            "status": "ERROR",
            "error": message,
            "_origin": payload.get("origin") or _ORIGIN,
        } for entry in entries]
        _write_json(session_dir / "results.json", results)
        _write_failures(session_dir, _failure_records(results))
        try:
            (session_dir / "run.log").write_text(message + "\n", encoding="utf-8")
        except Exception:
            pass
        print(message, file=sys.stderr)
        run.results = results
        return finish(EXIT_ENGINE, str(exc))

    # Engine output is the authoritative archive.  Checklist-only fallbacks
    # are attached to a deep copy below and never overwrite this file.
    archived_results = []
    for result in results:
        value = copy.deepcopy(dict(result))
        value["_origin"] = payload.get("origin") or _ORIGIN
        archived_results.append(value)
    _write_json(session_dir / "results.json", archived_results)

    run.results = archived_results

    # Pass the original successful results through and add candidates only for
    # rows with no match. This is the only result collection Checklist sees.
    checklist_results = []
    fallback_notes = []
    for result in results:
        status = str(result.get("status") or "").upper()
        if status == "NO_MATCH":
            entry = entry_map.get(result.get("quote_id"), {})
            candidate = _attach_fallback(result, entry)
            checklist_results.append(candidate)
            if candidate.get("fallback"):
                fallback_notes.append(
                    "条目 {}：候选来自全量通表，非选型结果".format(
                        result.get("quote_id") or 0))
        else:
            candidate = copy.deepcopy(dict(result))
            candidate["_origin"] = payload.get("origin") or _ORIGIN
            checklist_results.append(candidate)

    run.checklist_results = checklist_results

    log_lines = ["origin={} project={}".format(
        payload.get("origin") or _ORIGIN, project)]
    if run_log:
        log_lines.append(run_log.rstrip("\n"))
    for result in results:
        if str(result.get("status") or "").upper() in ("ERROR", "NO_MATCH"):
            log_lines.append(
                "条目 {} {}：{}".format(result.get("quote_id") or 0,
                                        result.get("status"),
                                        _failure_reason(result)))
    log_lines.extend(fallback_notes)
    if llm_events:
        log_lines.append("llm_events:")
        for event in llm_events:
            log_lines.append("  " + json.dumps(
                event, ensure_ascii=False, sort_keys=True, default=_json_default))
    try:
        (session_dir / "run.log").write_text("\n".join(log_lines) + "\n",
                                             encoding="utf-8")
    except Exception as exc:
        print("警告：run.log 写入失败：{}".format(exc), file=sys.stderr)

    failures = _failure_records(results)
    _write_failures(session_dir, failures)

    # Keep the engine's own per-item output visible after capture.
    if run_log:
        print(run_log, end="" if run_log.endswith("\n") else "\n")
    status_counts = {}
    for result in results:
        status = str(result.get("status") or "UNKNOWN").upper()
        status_counts[status] = status_counts.get(status, 0) + 1
    print("选型摘要：共 {} 项；{}".format(
        len(results), "，".join("{} {} 项".format(k, v)
                               for k, v in sorted(status_counts.items()))))
    for failure in failures:
        print("条目 {}：{}".format(failure.get("quote_id") or 0,
                                 failure.get("reason")))

    try:
        _write_manifest(session_dir)
    except Exception as exc:
        print("警告：manifest 写入失败：{}".format(exc), file=sys.stderr)

    if any(str(r.get("status") or "").upper() == "ERROR" for r in results):
        return finish(EXIT_ENGINE, "; ".join(f["reason"] for f in failures))

    return finish(EXIT_OK)


def main(argv: Sequence[str] | None = None, *, session_root: Any = None) -> int:
    args = _parser().parse_args(argv)

    # These branches intentionally happen before loading EngineService/Qt.
    if args.export_generated:
        try:
            paths = export_generated()
        except Exception as exc:
            print("环境错误：无法导出生成物：{}".format(exc), file=sys.stderr)
            return EXIT_ENVIRONMENT
        for path in paths:
            print(str(path))
        return EXIT_OK

    if args.print_schema:
        try:
            from COPA.apps.contract import print_schema
            print(json.dumps(print_schema(), ensure_ascii=False, indent=2,
                             default=_json_default))
            return EXIT_OK
        except Exception as exc:
            print("环境错误：无法输出 schema：{}".format(exc), file=sys.stderr)
            return EXIT_ENVIRONMENT

    if args.print_prompt:
        try:
            from COPA.apps.contract import print_prompt
            print(print_prompt())
            return EXIT_OK
        except Exception as exc:
            print("环境错误：无法输出 prompt：{}".format(exc), file=sys.stderr)
            return EXIT_ENVIRONMENT

    if not args.input:
        print("契约错误：请提供 quote.json/raw.txt，或使用 --print-schema/--print-prompt",
              file=sys.stderr)
        return EXIT_CONTRACT

    try:
        from COPA.apps.llm_io import load_payload
        payload = load_payload(args.input)
    except Exception as exc:
        _print_contract_errors(exc)
        return _input_error_exit(exc)

    run = run_payload(payload, project=args.project,
                      session_root=(args.sessions_dir or session_root))
    if run.exit_code != EXIT_OK or args.no_gui:
        return run.exit_code
    return _start_checklist(run.payload, run.project, run.entries,
                            run.checklist_results, run.session_dir)


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "EXIT_OK", "EXIT_CONTRACT", "EXIT_ENGINE", "EXIT_ENVIRONMENT",
    "main", "run_payload", "QuoteRun", "export_generated",
    "_failure_reason", "_session_dir", "_safe_project_name", "_write_manifest",
]
