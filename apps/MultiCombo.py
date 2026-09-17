"""COPA_apps_MultiCombo：可勾选多选下拉框。

GUI 结构化录入（Desk「下拉菜单输入」页签）需要一个下拉控件内勾选多个
选项（如扩展通讯协议）；QComboBox 原生只支持单选，故以 QStandardItemModel
的 CheckStateRole 扩展：弹层内逐项勾选、点选不关闭弹层，行编辑器
（只读）同步显示已选摘要。Ui_*.py 由 .ui 的 customwidget header 指向
本模块引用（uic 生成 from COPA.apps.MultiCombo import CheckableComboBox）。
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox


class CheckableComboBox(QComboBox):
    """多选下拉：条目带勾选框，行编辑器汇总显示已选文本"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 可编辑仅为承载只读行编辑器显示摘要；用户输入被 readOnly 拦下
        self.setEditable(True)
        line_edit = self.lineEdit()

        if line_edit is not None:
            line_edit.setReadOnly(True)

        self.setCurrentIndex(-1)

        self._model = QStandardItemModel(self)
        self.setModel(self._model)

        # 勾选状态变更 -> 刷新摘要文本
        self._model.itemChanged.connect(self._update_summary)

        # 拦下弹层条目的鼠标事件：切换勾选并吞掉事件，
        # 使视图不产生 activated（弹层保持展开，可连续勾选）
        self._filter = _PopupEventFilter(self)
        self.view().viewport().installEventFilter(self._filter)

    def addItem(self, text, userData=None):
        """追加一个可勾选条目（uic 生成代码调用 addItem("")+setItemText，
        因此初始文本为空也要登记词条，文本随后经 setItemText 回填）"""
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled
                      | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        if userData is not None:
            item.setData(userData)
        self._model.appendRow(item)

    def setItemText(self, index, text):
        model_item = self._model.item(index)

        if model_item is not None:
            model_item.setText(text)
        else:
            super().setItemText(index, text)

    def checkedItems(self):
        """已勾选条目文本（按条目顺序）"""
        texts = []

        for row in range(self._model.rowCount()):
            item = self._model.item(row)

            if item.checkState() == Qt.CheckState.Checked:
                texts.append(item.text())

        return texts

    def setCheckedItems(self, texts):
        """按文本批量设勾选；未登记的文本忽略"""
        wanted = set(texts)

        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            state = (Qt.CheckState.Checked if item.text() in wanted
                     else Qt.CheckState.Unchecked)

            if item.checkState() != state:
                item.setCheckState(state)

        self._update_summary()

    def _update_summary(self, *_args):
        self.setEditText("、".join(self.checkedItems()))

    def _toggle_at(self, index):
        """切换指定行勾选状态（点击行内任意位置生效，不必点中勾选框）"""
        item = self._model.itemFromIndex(index)

        if item is None:
            return

        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )


class _PopupEventFilter(QObject):
    """弹层视口事件过滤器：点击即切换勾选并吞掉事件，阻止弹层收起"""

    def __init__(self, combo):
        super().__init__(combo)
        self._combo = combo

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonRelease:
            view = self._combo.view()
            index = view.indexAt(event.position().toPoint())

            if index.isValid():
                self._combo._toggle_at(index)
                return True

        return False
