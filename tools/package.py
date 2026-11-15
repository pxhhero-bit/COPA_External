"""一键出包：PyInstaller 打 exe + 复制外置资源 + 完整性自检 + 压缩。

``COPA.spec`` 只负责 exe 与 ``_internal``（manual、图标、llm/rules、
providers.json）。config / data / template / library / snapshot / output
必须躺在 exe 同目录，程序冻结态按 exe 位置定位（见 spec 文件头的说明）。
这几块以前靠手工复制，最容易漏；本脚本统一处理：先清干净 dist\\COPA，
再按白名单整目录复制，最后拿源目录和包内目录逐文件比对，少一个就报错。

用法::

    py -3 tools/package.py              # 打包 + 复制 + 自检 + 压缩
    py -3 tools/package.py --no-build   # 复用已有 dist\\COPA，只做复制/自检/压缩
    py -3 tools/package.py --no-zip     # 不生成压缩包

退出码非 0 表示自检没过，压缩包不会生成——宁可不出包，也别出一个少文件的包。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_DIR / "dist"
APP_DIR = DIST_DIR / "COPA"

# exe 同目录必须存在的运行期资源，整目录复制。
RESOURCE_DIRS = ("config", "data", "template", "library", "snapshot", "output")

# 只建空目录、不复制内容：这两处是使用过程中产生的东西（报价单、快照），
# 本机的样品不该跟着测试包发给别人，1.31 那版也是空目录。
EMPTY_DIRS = ("snapshot", "output")

# 永远不进包的东西：字节码缓存、运行时产物、素材库修剪备份。
SKIP_DIRS = {"__pycache__", "cache", "_backup_trim"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# 打包后应出现在 _internal 里的标记文件（少一个就说明 datas 掉了）。
INTERNAL_MARKERS = (
    "manual/manual.json",
    "COPAv2.ico",
    "llm/providers.json",
    "COPA/apps/sDocBuilder/assets",
    "COPA/apps/assets/splash_icon.png",
)


def _read_version() -> tuple[str, str]:
    """从 apps/version.py 取版本号与渠道，避免和界面显示对不上。"""

    text = (PROJECT_DIR / "apps" / "version.py").read_text(encoding="utf-8")
    version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    channel = re.search(r'APP_CHANNEL\s*=\s*"([^"]*)"', text)
    return (version.group(1) if version else "v0",
            channel.group(1) if channel else "")


def _iter_files(root: Path) -> list[str]:
    """列出相对路径清单，跳过缓存目录与字节码。"""

    if not root.exists():
        return []
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        found.append(rel.as_posix())
    return sorted(found)


def _clean() -> None:
    for path in (PROJECT_DIR / "build" / "COPA", APP_DIR):
        _discard(path)


def _build() -> None:
    print("==> PyInstaller（COPA.spec）")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(PROJECT_DIR / "COPA.spec"),
         "--noconfirm", "--clean"],
        cwd=str(PROJECT_DIR),
        check=True,
    )


def _discard(path: Path) -> None:
    """把目录挪进 temp\\_trash，而不是直接删。

    dist\\COPA 是八百多个文件，一次性 rmtree 会撞上本机的批量删除保护，
    整个打包进程会当场被中止（连异常都来不及抛）。挪走同样能拿到干净目录，
    又不丢数据；需要回收空间时手动清 temp\\_trash 就行。
    """

    if not path.exists():
        return
    trash = PROJECT_DIR / "temp" / "_trash"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%m%d_%H%M%S")
    target = trash / f"{path.name}-{stamp}"
    suffix = 2
    while target.exists():
        target = trash / f"{path.name}-{stamp}-{suffix}"
        suffix += 1
    shutil.move(str(path), str(target))
    print(f"    旧产物已移到 {target.relative_to(PROJECT_DIR)}")


def _copy_resources() -> dict[str, int]:
    if not (APP_DIR / "COPA.exe").is_file():
        sys.exit("!! dist\\COPA\\COPA.exe 不存在，先去掉 --no-build 重新打包")

    counts: dict[str, int] = {}
    for name in RESOURCE_DIRS:
        source = PROJECT_DIR / name
        if not source.is_dir():
            sys.exit(f"!! 源资源目录缺失：{source}")
        target = APP_DIR / name
        if target.exists():
            _discard(target)
        if name in EMPTY_DIRS:
            target.mkdir(parents=True)
            counts[name] = 0
            print(f"    {name:<9}    空目录（使用中生成，不带本机内容）")
            continue
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(
            *SKIP_DIRS, *{f"*{suffix}" for suffix in SKIP_SUFFIXES}))
        counts[name] = len(_iter_files(target))
        print(f"    {name:<9} {counts[name]:>4} 个文件")
    return counts


def _check_dirs(counts: dict[str, int]) -> list[str]:
    """逐文件核对：源里有的，包里必须有；包内不许出现跳过项。"""

    problems: list[str] = []
    for name in RESOURCE_DIRS:
        if name in EMPTY_DIRS:
            if not (APP_DIR / name).is_dir():
                problems.append(f"{name}/ 目录缺失")
            continue
        expected = set(_iter_files(PROJECT_DIR / name))
        actual = set(_iter_files(APP_DIR / name))
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        for rel in missing[:8]:
            problems.append(f"{name}/{rel} 未进包")
        for rel in extra[:8]:
            problems.append(f"{name}/{rel} 多出来了")
        if len(missing) > 8 or len(extra) > 8:
            problems.append(f"{name} 还有更多差异，见上")
    return problems


def _check_internal() -> list[str]:
    internal = APP_DIR / "_internal"
    problems: list[str] = []
    if not internal.is_dir():
        return ["_internal 目录不存在"]

    for marker in INTERNAL_MARKERS:
        if not (internal / marker).exists():
            problems.append(f"_internal/{marker} 缺失")

    # 规则文件数随协议演进会增减（v1.4 由 4 份合并为 2 份），不写死阈值，
    # 只核对「源里有几份，包里就有几份」。
    src_rules = list((PROJECT_DIR / "llm" / "rules").glob("*.md"))
    pkg_rules = list((internal / "llm" / "rules").glob("*.md")) \
        if (internal / "llm" / "rules").is_dir() else []
    if not pkg_rules:
        problems.append("_internal/llm/rules 为空")
    elif len(pkg_rules) != len(src_rules):
        problems.append(
            f"_internal/llm/rules 有 {len(pkg_rules)} 份，源目录 {len(src_rules)} 份")
    if not (internal / "manual" / "manual.json").is_file():
        problems.append("_internal/manual 不完整")

    # Qt 平台插件：缺了 exe 会静默退出，必须在自检里拦住。
    if not list(internal.glob("PySide6/plugins/platforms/qwindows.dll")):
        problems.append("Qt qwindows.dll 缺失，exe 起不来")
    return problems


def _zip(version: str, channel: str) -> Path:
    suffix = f"_{channel}" if channel else ""
    archive = DIST_DIR / f"COPA_{version}{suffix}.zip"
    if archive.exists():
        archive.unlink()
    print(f"==> 压缩到 {archive.name}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            name = path.relative_to(DIST_DIR).as_posix()
            # 空目录输出/快照也要留条目，解压后目录结构才对得上。
            if path.is_dir():
                zf.writestr(name + "/", "")
            else:
                zf.write(path, name)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="COPA 打包与完整性自检")
    parser.add_argument("--no-build", action="store_true", help="复用已有 dist\\COPA")
    parser.add_argument("--no-zip", action="store_true", help="不生成压缩包")
    args = parser.parse_args()

    version, channel = _read_version()
    print(f"==> COPA {version}{' ' + channel if channel else ''}")

    if not args.no_build:
        _clean()
        _build()

    print("==> 复制外置资源")
    counts = _copy_resources()

    print("==> 完整性自检")
    problems = _check_dirs(counts) + _check_internal()

    total = len([p for p in APP_DIR.rglob("*") if p.is_file()])
    size = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    print(f"    包内共 {total} 个文件，{size / 1024 / 1024:.1f} MB")

    if problems:
        print("!! 自检未通过：")
        for line in problems:
            print("   -", line)
        return 1
    print("    自检通过：源目录与包内文件逐一对齐")

    if not args.no_zip:
        archive = _zip(version, channel)
        print(f"==> 完成：{archive}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")
    else:
        print(f"==> 完成：{APP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
