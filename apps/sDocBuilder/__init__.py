"""sDocBuilder：技术方案编排与输出工具（2026-09 整体并入 COPA）。

入口 sDocBuilder.py 既被 Commander 工具栏 B 按钮以 MDI 子窗体内嵌
（导入 MainWindow），也保留独立运行（python sDocBuilder.py）；
sdoc 包内导入均为绝对导入（from sdoc...），依赖本目录在 sys.path。
"""
