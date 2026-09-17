# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_DIR = Path(SPECPATH)

a = Analysis(
    [str(PROJECT_DIR / 'main.py')],
    # apps/sDocBuilder：sdoc 包为绝对导入(from sdoc...)，其父目录须在
    # 搜索路径，PyInstaller 才能把 sdoc.* 收进包
    pathex=[str(PROJECT_DIR.parent),
            str(PROJECT_DIR / 'apps' / 'sDocBuilder')],
    binaries=[],
    # config/data/template/snapshot/library 不打包：打包完成后手动复制到
    # dist\COPA\ 根目录(exe 同目录)，程序冻结态按 exe 位置定位(见
    # Parser/engine/Writer/Checklist 的 frozen 分支；library 由
    # apps/sDocBuilder 的冻结分支同样按 exe 同目录读取)。注意：每次
    # 重新打包会重建 dist\COPA，手动复制的文件夹需要重拷。
    #
    # manual(使用说明素材)与 COPA.ico(About 窗口图标)例外：经 datas 打
    # 进 _internal，不外显在 exe 旁；Manual.py/About.py 冻结态从
    # sys._MEIPASS(6.x 即 _internal)读取。
    datas=[
        (str(PROJECT_DIR / 'manual'), 'manual'),
        (str(PROJECT_DIR / 'COPAv2.ico'), '.'),
        # sDocBuilder 应用图标：冻结态 _SDOC_ROOT 即 _internal\COPA\apps\
        # sDocBuilder，按原目录结构落位使 sDocBuilder._APP_ICON 命中
        (str(PROJECT_DIR / 'apps' / 'sDocBuilder' / 'assets'),
         'COPA/apps/sDocBuilder/assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='COPA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_DIR / 'COPAv2.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='COPA',
)