"""报价诊断窗（MDI 子窗口）的开关生命周期。

真实用户点标题栏 X 之后，再点工具栏 C 报
`RuntimeError: libshiboken: Internal C++ object (QMdiSubWindow) already deleted`。
根因是 QMdiArea.addSubWindow 默认给子窗口打了 WA_DeleteOnClose，关闭即销毁，
Python 侧只剩空壳。这里把「关掉只是隐藏」「被销毁也能自愈」两件事钉住。
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from COPA.main import Commander


def must(value):
    """断言「这时一定有窗口」并把 Optional 收窄。"""

    assert value is not None
    return value


class AuditWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = Commander()
        self.win.show()
        self.app.processEvents()
        self.addCleanup(self._teardown)

    def _teardown(self):
        # 诊断面板可能已被用例销毁，closeMainWindow 前先挡掉野指针
        if self.win._audit_sub_alive():
            must(self.win._audit_sub).close()
        self.win.close()
        self.app.processEvents()

    # -- 基本开关 ---------------------------------------------------------

    def test_sub_window_refuses_delete_on_close(self):
        self.win._open_audit()
        sub = must(self.win._audit_sub)
        assert sub is not None
        self.assertFalse(
            sub.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose),
            '诊断子窗口不能带 WA_DeleteOnClose：关闭即销毁就没法重开了')

    def test_close_then_reopen_keeps_same_panel(self):
        self.win._open_audit()
        panel = self.win._audit
        sub = must(self.win._audit_sub)

        sub.close()
        self.app.processEvents()

        self.assertTrue(shiboken6.isValid(sub), '关闭后子窗口被销毁了')
        self.assertFalse(sub.isVisible(), '关闭后应当隐藏')
        self.assertTrue(shiboken6.isValid(panel), '关闭后诊断面板被销毁了')

        self.win._open_audit()
        self.app.processEvents()
        self.assertIs(must(self.win._audit), panel, '重开必须复用同一个面板，结果不能丢')
        self.assertIs(must(self.win._audit_sub), sub)
        self.assertTrue(must(self.win._audit_sub).isVisible(), '重开后子窗口没显示')
        self.assertTrue(must(self.win._audit).isVisible(), '重开后只剩标题栏空壳')

    def test_reopen_after_maximized_close(self):
        self.win._open_audit()
        must(self.win._audit_sub).showMaximized()
        self.app.processEvents()
        must(self.win._audit_sub).close()
        self.app.processEvents()

        self.win._open_audit()
        self.app.processEvents()
        self.assertTrue(must(self.win._audit_sub).isVisible())

    def test_close_all_then_reopen(self):
        self.win._open_audit()
        self.win._close_all()
        self.app.processEvents()
        self.assertFalse(must(self.win._audit_sub).isVisible())
        self.assertTrue(shiboken6.isValid(self.win._audit),
                        '「关闭所有」不该销毁诊断面板')

        self.win._open_audit()
        self.app.processEvents()
        self.assertTrue(must(self.win._audit_sub).isVisible())

    # -- 自愈 -------------------------------------------------------------

    def test_remove_sub_window_never_deletes_audit_panel(self):
        self.win._open_audit()
        panel = self.win._audit
        sub = must(self.win._audit_sub)

        # 绕过事件过滤器直接走统一清理路径：这是单例面板，只能隐藏
        self.win._remove_sub_window(sub)
        self.app.processEvents()

        self.assertTrue(shiboken6.isValid(panel), '统一清理路径把诊断面板删了')
        self.assertTrue(shiboken6.isValid(sub))
        self.assertFalse(sub.isVisible())

        self.win._open_audit()
        self.app.processEvents()
        self.assertTrue(must(self.win._audit_sub).isVisible())

    def test_rebuild_when_sub_window_was_destroyed(self):
        self.win._open_audit()
        old_global = shiboken6.isValid(self.win._audit)

        # 模拟历史版本的销毁路径：C++ 侧直接删除子窗口（会连带删面板）
        shiboken6.delete(must(self.win._audit_sub))
        self.assertFalse(self.win._audit_sub_alive())

        self.win._open_audit()          # 修复前这里抛 RuntimeError
        self.app.processEvents()
        self.assertTrue(shiboken6.isValid(self.win._audit),
                        '子窗口被销毁后应重建面板')
        self.assertTrue(must(self.win._audit_sub).isVisible())
        self.assertTrue(old_global)

    def test_reopen_is_idempotent(self):
        self.win._open_audit()
        sub = must(self.win._audit_sub)
        for _ in range(3):
            self.win._open_audit()
        self.app.processEvents()
        self.assertIs(must(self.win._audit_sub), sub, '重复点工具栏 C 不该造出第二个窗口')
        # MDI 里可能还有启动时的 Desk 项目窗，只数挂着诊断面板的那些
        mine = [s for s in self.win.mdi.subWindowList()
                if s.widget() is self.win._audit]
        self.assertEqual(len(mine), 1, '诊断面板挂了不止一个子窗口')


if __name__ == '__main__':
    unittest.main(verbosity=2)
