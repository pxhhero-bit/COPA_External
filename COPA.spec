# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_DIR = Path(SPECPATH)

# LLM 对话协议与规则：冻结态优先读 exe 同目录 llm/rules，缺失时回退到
# _internal\llm\rules（contract._rules_dir）。缺规则会显式报错。
LLM_DATAS = [(str(PROJECT_DIR / 'llm' / 'rules'), 'llm/rules')]

# providers.json 随包分发（内部分发场景：口令由维护者持有、可随时吊销，
# 打包内含一份省去现场配置）。冻结态查找顺序仍是 exe 同目录优先，所以
# 现场换端点/换 key 只要在 exe 旁放一份覆盖即可，不必重新打包。
# 缺失时不加入，避免在没有配置文件的机器上打包直接失败。
_PROVIDERS = PROJECT_DIR / 'llm' / 'providers.json'
if _PROVIDERS.is_file():
    LLM_DATAS.append((str(_PROVIDERS), 'llm'))

a = Analysis(
    # 入口是 launch.py 而非 main.py：launch 先只加载 Qt 基础把启动画面
    # 刷上屏，再导入 main。若入口改回 main.py，启动画面会被 491ms 的业务
    # 模块导入挡在后面（用户看到的就是空桌面）。
    [str(PROJECT_DIR / 'launch.py')],
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
        # 启动画面图标：apps/Splash.py 冻结态按 _internal\COPA\apps\assets 取
        (str(PROJECT_DIR / 'apps' / 'assets'),
         'COPA/apps/assets'),
        # LLM 协议、规则与（可选的）providers.json，见文件头的 LLM_DATAS。
        *LLM_DATAS,
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