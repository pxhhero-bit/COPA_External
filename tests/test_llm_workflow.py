"""Internal dialog -> in-memory selection -> original Checklist integration."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QLabel
import shiboken6
from COPA import cli_quote
from COPA.apps.llm_chat import ChatSession,ChatSettings,demo_payload
from COPA.apps.LlmChat import LlmChat
from COPA.apps.LlmWorkflow import LlmQuoteWorkflow


def must(value):
    """断言「此处一定有值」并把 Optional 收窄，供后面的属性访问使用。"""

    assert value is not None
    return value


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        session=ChatSession(ChatSettings(api_key='synthetic-secret-not-for-storage'))
        self.dialog=LlmChat(session=session)
        self.workflow=LlmQuoteWorkflow(dialog=self.dialog,session_root=Path(self.tmp.name)/'sessions')
        self.addCleanup(self.workflow.close)
        self.addCleanup(self.app.processEvents)

    def wait(self):
        deadline=time.monotonic()+5
        while self.workflow.busy and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.workflow.busy,'selection did not complete')

    def confirmed(self, nonstandard=False):
        payload=demo_payload()
        if nonstandard:
            payload['items'][0]['fields']['台面尺寸']='3000x3000'
            payload['items'][0]['confirmed_nonstandard']=True
        self.dialog.session.load_candidate(payload)
        return self.dialog.session.confirm(1)

    def test_direct_handoff_archive_rollback_and_rebuild(self):
        self.dialog.session.load_demo()
        payload=self.dialog.session.confirm(1)
        # A GUI hand-off must never invoke CLI parsing or start another event loop.
        with patch.object(cli_quote,'main',side_effect=AssertionError('CLI must not be invoked')):
            self.workflow.start_selection(payload)
            payload['items'][0]['fields']['W1']=999999
            self.wait()
        run=must(self.workflow.run)
        self.assertEqual(run.payload['items'][0]['fields']['W1'],2000)
        self.assertEqual(run.results[0]['status'],'OK')
        self.assertTrue((must(run.session_dir)/'quote.json').exists())
        chat=(must(run.session_dir)/'chat.json').read_text(encoding='utf-8')
        archived=json.loads(chat)
        self.assertIn('messages',archived)
        self.assertIn('events',archived)
        self.assertIn('source_text',archived)
        self.assertTrue((must(run.session_dir)/'manifest.json').exists())
        self.assertNotIn('synthetic-secret-not-for-storage',chat)
        # 清单叠在对话窗上面：对话窗不隐藏，用户还能回头看一眼刚才的对话。
        self.assertTrue(self.dialog.isVisible())
        old=next(must(self.workflow.checklist)._iter_items())
        old.qtyBox.setText('9')
        self.workflow.return_to_chat()
        self.app.processEvents()
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.workflow.checklist)
        self.assertGreater(len(self.dialog.session.messages),1)
        self.workflow.start_selection(self.dialog.session.confirm(1))
        self.wait()
        self.assertEqual(next(must(self.workflow.checklist)._iter_items()).qtyBox.text(),'1')

    def test_no_match_stays_editable_with_visible_warning(self):
        with patch.object(cli_quote,'_show_no_match'):
            self.workflow.start_selection(self.confirmed(nonstandard=True))
            self.wait()
        self.assertEqual(must(self.workflow.run).results[0]['status'],'NO_MATCH')
        row=next(must(self.workflow.checklist)._iter_items())
        self.assertGreater(row.productComBox.count(),1)
        label=must(must(self.workflow.checklist).findChild(QLabel,'llmWarning_1'))
        self.assertIn('非标',label.text())
        self.assertTrue((must(must(self.workflow.run).session_dir)/'fail.json').exists())

    def test_engine_failure_returns_to_dialog(self):
        payload=self.confirmed()
        failed=cli_quote.QuoteRun(payload=payload,project='测试',exit_code=2,error='测试：数据库异常')
        with patch.object(cli_quote,'run_payload',return_value=failed), \
             patch.object(self.dialog,'show_pipeline_error',wraps=self.dialog.show_pipeline_error) as show_error:
            self.workflow.start_selection(payload)
            self.wait()
        show_error.assert_called_once_with('测试：数据库异常')
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.workflow.checklist)

    def test_original_output_signal_saves_snapshot(self):
        self.workflow.start_selection(self.confirmed())
        self.wait()
        checklist=must(self.workflow.checklist)
        checklist.editCompanyName.setPlainText('自动化测试客户')
        checklist.editContactPerson.setPlainText('测试联系人')
        target=Path(self.tmp.name)/'test-only-quote.xlsx'
        with patch.object(checklist,'_confirm_output',return_value=True), \
             patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'')), \
             patch.object(QMessageBox,'information',return_value=QMessageBox.StandardButton.Ok):
            checklist._output_quote()
        self.app.processEvents()
        self.assertTrue(target.exists())
        snapshot=must(must(self.workflow.run).session_dir)/'snapshot.md'
        self.assertIn('_origin: llm',snapshot.read_text(encoding='utf-8-sig'))

    def test_checklist_waits_for_the_generating_notice(self):
        """交接立刻发生，但清单窗要等「正在生成」的提示露脸 1.5s 才弹。"""
        self.assertEqual(LlmQuoteWorkflow.CHECKLIST_MIN_VISIBLE_MS,1500)
        dialog=self.dialog
        dialog.DEMO_START_DELAY=0
        dialog.DEMO_REPLY_DELAY=0
        dialog.DEMO_USER_DELAY=0
        dialog.DEMO_TYPE_INTERVAL=0
        handoff=[]
        checklist_at_handoff=[]
        notice_at=[]

        def _on_handoff(_payload):
            handoff.append(time.monotonic())
            # 这一刻清单**应当**还没弹：故意取原始值（可能是 None）做断言。
            checklist_at_handoff.append(self.workflow.checklist)
            # 提示从 start_selection 起算（_handoff_at）。跨线程的信号可能
            # 排队晚到几百毫秒，那一刻编排层的槽还没跑就先按「现在」算。
            notice_at.append(self.workflow._handoff_at or time.monotonic())

        dialog.payloadConfirmed.connect(_on_handoff)

        dialog._use_demo()
        deadline=time.monotonic()+15
        while self.workflow.checklist is None and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()

        self.assertTrue(handoff,'应当已经交接')
        self.assertIsNone(checklist_at_handoff[0],'交接瞬间不应已经弹窗')
        assert self.workflow.checklist is not None, '清单窗最终要打开'
        # 计时基准是「正在生成选型清单」提示出现的那一刻；交接信号只表示
        # 对话框已交出参数，不能拿它当 1.5s 的起点（信号可能排队晚到）。
        self.assertGreaterEqual(time.monotonic()-notice_at[0],1.4)
        self.assertGreaterEqual(time.monotonic()-handoff[0],1.0)
        # 交付那一刻提示已经在屏幕上，用户不会看到空白等待。
        self.assertTrue(any('正在生成选型清单' in body for _role,body in dialog._entries))
        self.assertFalse(self.workflow.busy)

    def test_commander_entry_and_busy_close(self):
        from PySide6.QtGui import QCloseEvent
        from COPA.main import Commander
        win=Commander()
        self.addCleanup(win.close)
        self.assertIn(win.actionLlmChat,win.toolBarLeft.actions())
        win.actionLlmChat.trigger()
        first=must(win._llm_workflow)
        win.actionLlmChat.trigger()
        self.assertIs(win._llm_workflow,first)
        # 与「选型报价」一致：对话窗是 MDI 子窗口，不是独立对话框。
        assert first._chat_sub is not None
        self.assertIn(first.dialog,[sub.widget() for sub in win.mdi.subWindowList()])
        first.busy=True
        event=QCloseEvent()
        win.closeEvent(event)
        self.assertFalse(event.isAccepted())
        first.busy=False

    def test_commander_demo_flow_opens_checklist_as_subwindow(self):
        from COPA.main import Commander
        win=Commander()
        self.addCleanup(win.close)
        win.actionLlmChat.trigger()
        workflow=must(win._llm_workflow)
        dialog=workflow.dialog
        # 展示模式按 1s/0.5s/逐字 的节奏播放，测试里压到最短；清单窗前的
        # 1.5s 停留属于编排层，这里保留默认值。
        dialog.DEMO_START_DELAY=0
        dialog.DEMO_REPLY_DELAY=0
        dialog.DEMO_USER_DELAY=0
        dialog.DEMO_TYPE_INTERVAL=0
        dialog._use_demo()
        deadline=time.monotonic()+20
        while (workflow._checklist_sub is None or workflow.busy) and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(workflow.busy,'选型未完成')
        assert workflow._checklist_sub is not None
        self.assertIn(workflow.checklist,
                      [sub.widget() for sub in win.mdi.subWindowList()])
        # 清单是叠在对话窗上的浮层，不是把对话窗收走。这个用例没 show 主窗体，
        # isVisible() 对任何子控件都恒为 False，只能看「显式隐藏」标记。
        self.assertFalse(must(workflow._chat_sub).isHidden())
        self.assertFalse(workflow.dialog.isHidden(),'对话窗体内容不能被藏起来')
        self.assertIs(win.mdi.activeSubWindow(),must(workflow._checklist_sub))


class ChatWindowLifecycleTests(unittest.TestCase):
    """对话子窗口的开关：QMdiArea.addSubWindow 默认带 WA_DeleteOnClose，
    点一次标题栏 X 会把子窗口连同对话窗体一起销毁。"""

    def setUp(self):
        self.app=QApplication.instance() or QApplication([])
        from COPA.main import Commander
        self.win=Commander()
        self.addCleanup(self.win.close)
        self.win.show()
        self.app.processEvents()

    def pump(self,milliseconds=60):
        deadline=time.monotonic()+milliseconds/1000.0
        while time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        # 真正跑掉 deleteLater，否则「对象已删除」这类问题会被推迟掩盖。
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def open_chat(self):
        self.win.actionLlmChat.trigger()
        self.pump(30)
        return must(self.win._llm_workflow)

    def test_closing_the_chat_window_keeps_it_reusable(self):
        from PySide6.QtCore import Qt
        workflow=self.open_chat()
        sub=must(workflow._chat_sub)
        self.assertFalse(sub.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose),
                         '子窗口不能带「关闭即销毁」标志')
        workflow.dialog.session.messages.append(
            {"role":"user","content":"保留这句话"})
        sub.close()
        self.pump(80)
        self.assertTrue(shiboken6.isValid(sub),'关闭只是隐藏，不能销毁子窗口')
        self.assertTrue(shiboken6.isValid(workflow.dialog))
        self.assertIs(self.open_chat(),workflow)
        self.assertIs(must(workflow._chat_sub),sub)
        self.assertTrue(sub.isVisible())
        self.assertIn({"role":"user","content":"保留这句话"},
                      workflow.dialog.session.messages)

    def test_closing_the_chat_window_keeps_content_visible_on_reopen(self):
        """点 X 只是隐藏，但 QMdiSubWindow 会把内部控件一起 close() 掉；
        重开时若只 show 子窗口，就只剩一个空白壳。"""
        workflow=self.open_chat()
        dialog=workflow.dialog
        dialog._append('用户','关掉再打开这句话要还在')
        dialog._render_conversation()
        self.app.processEvents()
        must(workflow._chat_sub).close()
        self.pump(80)
        self.assertTrue(dialog.isHidden(),'关闭后窗体本身确实被藏起来了')
        self.open_chat()
        self.pump(60)
        self.assertFalse(dialog.isHidden(),'重开必须把窗体本身 show 回来')
        self.assertTrue(dialog.isVisible())
        assert dialog._last_bubble() is not None, '内容要跟着回来，不能是空白壳'

    def test_deleted_chat_window_is_rebuilt_instead_of_raising(self):
        from PySide6.QtCore import Qt
        workflow=self.open_chat()
        stale=workflow.dialog
        # 复刻旧版本的行为：子窗口带 WA_DeleteOnClose，点 X 后窗体一起没。
        must(workflow._chat_sub).setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        must(workflow._chat_sub).close()
        self.pump(100)
        self.assertFalse(shiboken6.isValid(stale),'这一轮应当真的销毁窗体')
        reopened=self.open_chat()   # 旧代码在这里抛 RuntimeError
        self.assertIs(reopened,workflow)
        self.assertTrue(shiboken6.isValid(workflow.dialog))
        self.assertIsNot(workflow.dialog,stale)
        self.assertTrue(must(workflow._chat_sub).isVisible())

    def test_opening_the_chat_closes_only_empty_desks(self):
        first=next(iter(self.win._projects.values()))
        self.assertTrue(self.win._desk_is_empty(first))
        self.open_chat()
        self.pump(80)
        self.assertNotIn(first,self.win._projects.values(),'空白需求录入应被收掉')
        self.assertEqual([s.windowTitle() for s in self.win.mdi.subWindowList()],
                         ['对话选型'])

        self.win._new_project()
        self.pump(30)
        kept=next(iter(self.win._projects.values()))
        kept.cardContainerLayout.itemAt(0).widget().plainTextEdit.setPlainText(
            '一台 2000kg 平台秤')
        self.assertFalse(self.win._desk_is_empty(kept))
        self.open_chat()
        self.pump(80)
        self.assertIn(kept,self.win._projects.values(),'已录入内容的需求窗不能被关掉')

    def test_checklist_overlays_chat_and_gives_it_back_on_close(self):
        workflow=self.open_chat()
        dialog=workflow.dialog
        dialog.DEMO_START_DELAY=0
        dialog.DEMO_REPLY_DELAY=0
        dialog.DEMO_USER_DELAY=0
        dialog.DEMO_TYPE_INTERVAL=0
        dialog._use_demo()
        deadline=time.monotonic()+20
        while workflow._checklist_sub is None and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        assert workflow._checklist_sub is not None, '清单窗未打开'
        # 清单出现，但对话窗留在原地当背景，不再被收走。
        self.assertTrue(must(workflow._chat_sub).isVisible(),'清单出现后对话窗不该消失')
        self.assertEqual(self.win.mdi.activeSubWindow().windowTitle(),'选型清单')
        # 对话窗留在屏幕上，状态行不能还挂着「正在选型，请稍候」。
        self.assertNotIn('正在选型',dialog.statusLabel.text())
        # 清单错开一点叠上去：两个标题栏都露出来，且不能被裁到视口外。
        sub=must(workflow._checklist_sub)
        self.assertEqual((sub.pos().x(),sub.pos().y()),
                         (LlmQuoteWorkflow.CHECKLIST_OFFSET,)*2)
        self.assertTrue(self.win.mdi.viewport().rect().contains(sub.geometry()),
                        '清单错位后不能超出视口')

        must(workflow._checklist_sub).close()
        self.pump(120)
        self.assertTrue(must(workflow._chat_sub).isVisible(),'关掉清单应回到对话')
        self.assertEqual(self.win.mdi.activeSubWindow().windowTitle(),'对话选型')
        # 不能留下一个空壳「选型清单」子窗口。
        self.assertEqual([s.windowTitle() for s in self.win.mdi.subWindowList()],
                         ['对话选型'])


if __name__=='__main__':
    unittest.main()
