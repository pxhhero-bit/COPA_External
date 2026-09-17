# -*- coding: utf-8 -*-
"""sDocBuilder 面板行为类：候选池 / 大纲树。

由 main_window.ui 以 promotion 方式引用（header = sdoc.ui.panels），
Designer 里编辑的是同尺寸的 QTreeWidget 基类，行为全部在本模块。
"""
import json
import re

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QMenu, QStyledItemDelegate,
                               QStyleOptionViewItem, QTreeWidget,
                               QTreeWidgetItem)

MIME_REF = "application/x-sdoc-ref"
ROLE_KIND = Qt.UserRole            # "BLOCK" 标记块节点
ROLE_REF = Qt.UserRole + 1         # 块引用
ROLE_TITLE = Qt.UserRole + 2       # 节点原始标题（编号前缀之外）

GUIDE_COLOR = QColor("#c9ced4")    # 树形分支引导线


def _draw_branch_guides(view, painter, rect, index, is_leaf):
    """在 branch 缩进区画分支引导线：祖先层级竖线 + 自列肘线（└/├ 风格）"""
    depth, i = 0, index
    while i.isValid():
        depth += 1
        i = i.parent()
    indent = view.indentation()
    model = index.model()
    painter.save()
    painter.setPen(QPen(GUIDE_COLOR, 1))
    mid_y = rect.top() + rect.height() // 2
    # 祖先列：祖先不是其父层的最后一个兄弟时，竖线穿过本行
    chain, i = [], index.parent()
    while i.isValid():
        chain.append(i)
        i = i.parent()
    for lvl, anc in enumerate(reversed(chain), start=1):
        rows = model.rowCount(anc.parent())
        if anc.row() != rows - 1:
            x = rect.left() + (lvl - 1) * indent + indent // 2
            painter.drawLine(x, rect.top(), x, rect.bottom())
    # 自列：叶子画竖线+肘线；可展开行留给展开箭头
    x = rect.left() + (depth - 1) * indent + indent // 2
    if is_leaf(index):
        painter.drawLine(x, rect.top(), x, mid_y)
        painter.drawLine(x, mid_y, rect.right() - 4, mid_y)
    painter.restore()


def _kind_of(ref):
    """ref -> 类型标签：与 library_store 建块规则同源（按块 id 判型）。

    精确 id（features/params/form/images）直接映射；family 表块与全局
    块的 id 带 params*/form_* 前缀，按同源前缀判型；entry 配置块固定
    「配置」；其余（正文 md 块等）回落「文本」。"""
    from sdoc.core.library_store import KIND_LABEL
    tail = ref.rsplit(":", 1)[-1].lower()
    if tail in KIND_LABEL:
        return KIND_LABEL[tail]
    if tail == "config":
        return "配置"
    if tail.startswith("img"):
        return KIND_LABEL["images"]
    if tail.startswith("form_"):
        return KIND_LABEL["form"]
    if tail.startswith("params"):
        return KIND_LABEL["params"]
    if tail.startswith("features"):
        return KIND_LABEL["features"]
    return KIND_LABEL["text"]


class OutlineDelegate(QStyledItemDelegate):
    """大纲树的"文档化"渲染：章节按层级差异化排版（markdown 层级感）。
    只重写 paint/sizeHint，重命名编辑器走默认机制不受影响。"""

    BAND = QColor("#eef3f8")          # 一级章节底色带
    BAND_LINE = QColor("#d5dde5")     # 一级章节底部分隔线

    _LEVEL_STYLE = {                  # 深度 -> (字号, 加粗, 行高)
        1: (13.0, True, 32),
        2: (11.0, True, 27),
        3: (10.0, True, 24),
    }
    BLOCK_STYLE = (9.0, False, 23)

    def _node(self, index):
        is_block = index.data(ROLE_KIND) == "BLOCK"
        depth, i = 1, index.parent()
        while i.isValid():
            depth += 1
            i = i.parent()
        return is_block, depth

    def paint(self, painter, option, index):
        is_block, depth = self._node(index)
        if not is_block and depth == 1:
            painter.save()
            painter.fillRect(option.rect, self.BAND)
            painter.setPen(QPen(self.BAND_LINE, 1))
            painter.drawLine(option.rect.left(), option.rect.bottom(),
                             option.rect.right(), option.rect.bottom())
            painter.restore()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        size, bold, _ = self.BLOCK_STYLE if is_block \
            else self._LEVEL_STYLE.get(depth, (9.0, False, 23))
        opt.font.setPointSizeF(size)
        opt.font.setBold(bold)
        if is_block:
            opt.palette.setColor(opt.palette.ColorRole.Text,
                                 QColor("#444444"))
        super().paint(painter, opt, index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        is_block, depth = self._node(index)
        style = self.BLOCK_STYLE if is_block \
            else self._LEVEL_STYLE.get(depth, (9, False, 23))
        size.setHeight(max(size.height(), style[2]))
        return size


class PoolPanel(QTreeWidget):
    """左栏：候选池（分类 -> 型号 -> 块），拖出即编排"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("候选池（拖到右侧编排）")
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.setIndentation(22)

    def drawBranches(self, painter, rect, index):
        super().drawBranches(painter, rect, index)
        # 注意：此处拿到的是 QModelIndex（非 QTreeWidgetItem），
        # 子节点数要用 model.rowCount()
        _draw_branch_guides(self, painter, rect, index,
                            lambda i: i.model().rowCount(i) == 0)

    def set_store(self, store, project=None):
        from sdoc.core.library_store import KIND_LABEL
        self.clear()               # 重复打开快照时先清空，避免整树重复

        def add_family_item(top, f):
            label = "{}  〔{}〕".format(f.title, f.brand) if f.brand \
                else f.title
            fam_item = QTreeWidgetItem([label])
            fam_item.setData(0, ROLE_TITLE, f.title)
            top.addChild(fam_item)
            for b in f.blocks:
                leaf = QTreeWidgetItem(["　［{}］{}".format(
                    KIND_LABEL.get(b.kind, b.kind), b.title)])
                leaf.setData(0, ROLE_REF, b.ref)
                leaf.setData(0, ROLE_TITLE, b.title)
                fam_item.addChild(leaf)

        entries = getattr(project, "entries", []) if project else []
        for cat, fams in store.categories():
            top = QTreeWidgetItem([cat])
            top.setFlags(top.flags() & ~Qt.ItemIsDragEnabled)
            self.addTopLevelItem(top)
            for f in fams:
                add_family_item(top, f)
        if entries:
            # 快照分组置顶：全库折叠，仅展开本项目设备（命中库块）
            top = QTreeWidgetItem(["本项目设备（来自快照）"])
            top.setFlags(top.flags() & ~Qt.ItemIsDragEnabled)
            self.insertTopLevelItem(0, top)
            for e in entries:
                e_item = QTreeWidgetItem([e.type_cn])
                top.addChild(e_item)
                for key, _src in e.families:
                    f = store.family_by_key(key)
                    if f is not None:
                        add_family_item(e_item, f)
            self.collapseAll()
            top.setExpanded(True)
            for i in range(top.childCount()):
                top.child(i).setExpanded(True)
        else:
            for i in range(self.topLevelItemCount()):
                self.topLevelItem(i).setExpanded(True)

    def startDrag(self, allowed_actions):
        # 型号行（无 ROLE_REF）整体拖动 = 其下全部块；叶子块拖动 = 单块
        payload = []
        for it in self.selectedItems():
            ref = it.data(0, ROLE_REF)
            if ref is not None:
                payload.append({"ref": ref, "title": self._title_of(it)})
            elif it.childCount():
                payload += [{"ref": it.child(i).data(0, ROLE_REF),
                             "title": self._title_of(it.child(i))}
                            for i in range(it.childCount())
                            if it.child(i).data(0, ROLE_REF)]
        if not payload:
            return
        mime = QMimeData()
        mime.setData(MIME_REF, json.dumps(payload, ensure_ascii=False)
                     .encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    @staticmethod
    def _title_of(leaf):
        """叶子块的展示标题：全局块用自身名，family 块用所属型号名"""
        own = leaf.data(0, ROLE_TITLE)
        if own:
            return own
        parent = leaf.parent()
        return parent.data(0, ROLE_TITLE) if parent is not None \
            else leaf.text(0).strip()


class OutlinePanel(QTreeWidget):
    """右栏：白底文档页样式的大纲树（章节可嵌套3层，块不可嵌套）"""

    MAX_DEPTH = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(OutlineDelegate(self))
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setIndentation(24)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemChanged.connect(self._on_renamed)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.mutate_hook = None            # 变更前快照回调（撤回历史用）
        self.report_hook = None            # 消息回调（状态栏提示）
        self._numbering = False

    def _report(self, msg):
        if self.report_hook:
            self.report_hook(msg)

    @staticmethod
    def _subtree_height(item):
        """子树高度（含自身，单节点=1），用于降级前的层级上限校验"""
        children = [item.child(i) for i in range(item.childCount())]
        return 1 + max((OutlinePanel._subtree_height(c) for c in children),
                       default=0)

    def _depth_of(self, item):
        depth, p = 1, item.parent()
        while p is not None:
            depth += 1
            p = p.parent()
        return depth

    def drawBranches(self, painter, rect, index):
        super().drawBranches(painter, rect, index)

        def is_leaf(i):
            return (i.data(ROLE_KIND) == "BLOCK"
                    or i.model().rowCount(i) == 0)

        _draw_branch_guides(self, painter, rect, index, is_leaf)

    def _on_double_clicked(self, item):
        # 双击进入重命名前先存快照，保证撤回能回到改名前
        if self.mutate_hook:
            self.mutate_hook()

    def keyPressEvent(self, event):
        # Del 删除选中节点；重命名编辑中把按键交还编辑器
        # （PySide6 6.11 的 state() 返回普通枚举，用相等比较判断编辑态）
        editing = self.state() == QAbstractItemView.State.EditingState
        if event.key() == Qt.Key_Delete and not editing:
            it = self.currentItem()
            if it is not None:
                self._delete(it)
                return
        super().keyPressEvent(event)

    # ----节点构造----

    def add_chapter(self, title, parent_item=None):
        it = QTreeWidgetItem([title])
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        it.setData(0, ROLE_TITLE, title)
        if parent_item is None:
            self.addTopLevelItem(it)
        else:
            parent_item.addChild(it)
        it.setExpanded(True)
        return it

    def add_block(self, ref, title, parent_item=None):
        # 兼容带旧［类型］前缀的编排稿/快照标题：已有前缀不重复添加
        text = title if title.startswith("［") \
            else "［{}］{}".format(_kind_of(ref), title)
        it = QTreeWidgetItem([text])
        it.setFlags((it.flags() | Qt.ItemIsEditable) & ~Qt.ItemIsDropEnabled)
        it.setData(0, ROLE_KIND, "BLOCK")
        it.setData(0, ROLE_REF, ref)
        it.setData(0, ROLE_TITLE, text)
        if parent_item is None:
            self.addTopLevelItem(it)
        else:
            parent_item.addChild(it)
        return it

    def _raw_title(self, item):
        t = item.data(0, ROLE_TITLE)
        if t is None:
            t = re.sub(r"^[\d.]+\s+", "", item.text(0))
            item.setData(0, ROLE_TITLE, t)
        return t

    # ----拖拽----

    def dragEnterEvent(self, event):
        # Qt 默认只接受模型自带 MIME；自定义块的拖入必须在此显式放行
        if event.source() is self or event.mimeData().hasFormat(MIME_REF):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() is self or event.mimeData().hasFormat(MIME_REF):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self.mutate_hook:
            self.mutate_hook()
        if event.source() is not self and event.mimeData().hasFormat(MIME_REF):
            payload = json.loads(
                bytes(event.mimeData().data(MIME_REF)).decode("utf-8"))
            target = self.itemAt(event.position().toPoint())
            parent, anchor = self._drop_target(target)
            for p in payload:
                it = self.add_block(p["ref"], p["title"], parent)
                if anchor is not None:
                    self._move_after(parent, anchor, it)
                    anchor = it
            self.renumber()
            event.accept()
            return
        super().dropEvent(event)
        self._enforce_rules()
        self.renumber()

    def _drop_target(self, item):
        """返回 (块应挂的父节点, 锚点)：落块上=同层其后；落章节上=其块尾"""
        if item is None:
            return None, None
        if item.data(0, ROLE_KIND) == "BLOCK":
            return item.parent(), item
        return item, None

    def _move_after(self, parent, anchor, item):
        if parent is None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(item))
            self.insertTopLevelItem(self.indexOfTopLevelItem(anchor) + 1, item)
        else:
            parent.takeChild(parent.indexOfChild(item))
            parent.insertChild(parent.indexOfChild(anchor) + 1, item)

    def _enforce_rules(self):
        """内部拖拽后兜底：块不可有子节点；章节深度不超过 MAX_DEPTH"""

        def walk(item, depth):
            is_block = item.data(0, ROLE_KIND) == "BLOCK"
            parent = item.parent() or self.invisibleRootItem()
            children = [item.child(i) for i in range(item.childCount())]
            if children and (is_block or depth >= self.MAX_DEPTH):
                for c in children:
                    item.takeChild(item.indexOfChild(c))
                    parent.insertChild(parent.indexOfChild(item) + 1, c)
            for c in [item.child(i) for i in range(item.childCount())]:
                walk(c, depth + 1)

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i), 1)

    # ----编号/重命名/右键菜单----

    def renumber(self):
        """统一流水编号：章节与块都占号（1 / 1.1 / 1.1.1），
        与渲染器 numbered_nodes 同规则"""
        self._numbering = True

        def num(item, prefix):
            for i in range(item.childCount()):
                c = item.child(i)
                code = "{}.{}".format(prefix, i + 1) if prefix else str(i + 1)
                c.setText(0, "{} {}".format(code, self._raw_title(c)))
                if c.data(0, ROLE_KIND) != "BLOCK":
                    num(c, code)

        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            it.setText(0, "{} {}".format(i + 1, self._raw_title(it)))
            if it.data(0, ROLE_KIND) != "BLOCK":
                num(it, str(i + 1))
        self._numbering = False

    def _on_renamed(self, item, col):
        if col != 0 or self._numbering:
            return
        self._numbering = True
        text = item.text(0).strip()
        if item.data(0, ROLE_KIND) == "BLOCK":
            # 显示文本 = 编号 + ［类型］前缀 + 标题：重命名时剥掉前两者，
            # 按规范重建存储与显示，避免前缀/编号滚进标题里
            title = re.sub(r"^[\d.]+\s+", "", text)
            title = re.sub(r"^［[^］]*］\s*", "", title) or "未命名块"
            item.setData(0, ROLE_TITLE, "［{}］{}".format(
                _kind_of(item.data(0, ROLE_REF)), title))
            self.renumber()
        else:
            title = re.sub(r"^[\d.]+\s+", "", text) or "未命名章节"
            item.setData(0, ROLE_TITLE, title)
            item.setText(0, title)
            self.renumber()
        self._numbering = False

    def _menu(self, pos):
        it = self.itemAt(pos)
        menu = QMenu(self)
        if it is not None:
            menu.addAction("升级", lambda: self._report(
                self.promote() or "已升级"))
            menu.addAction("降级", lambda: self._report(
                self.demote() or "已降级"))
            menu.addSeparator()
            menu.addAction("重命名", lambda: self._start_rename(it))
            menu.addAction("删除", lambda: self._delete(it))
        menu.addAction("添加子章节",
                       lambda: self._add_sub_chapter(it))
        menu.exec(self.viewport().mapToGlobal(pos))

    def _start_rename(self, it):
        if self.mutate_hook:
            self.mutate_hook()
        self.editItem(it, 0)

    def promote(self):
        """升级：节点脱离父章节，挂到上层列表、紧跟原父章节之后。
        返回 None 表示成功，否则返回给用户看的提示文本。"""
        it = self.currentItem()
        if it is None:
            return "先在大纲里选中要升级的节点"
        parent = it.parent()
        if parent is None:
            return "「{}」已在顶层".format(self._raw_title(it))
        gp = parent.parent()
        if gp is None and it.data(0, ROLE_KIND) == "BLOCK":
            return "块已在最内层章节里，没有更外层可升"
        if self.mutate_hook:
            self.mutate_hook()
        if gp is None:
            idx = self.indexOfTopLevelItem(parent)
            parent.takeChild(parent.indexOfChild(it))
            self.insertTopLevelItem(idx + 1, it)
        else:
            pos = gp.indexOfChild(parent)
            parent.takeChild(parent.indexOfChild(it))
            gp.insertChild(pos + 1, it)
        it.setExpanded(True)
        self.renumber()
        self.setCurrentItem(it)
        return None

    def demote(self):
        """降级：节点成为前一个同级章节的子节点（末尾）。
        前一个节点必须是章节且降级后不超过最大层级。"""
        it = self.currentItem()
        if it is None:
            return "先在大纲里选中要降级的节点"
        parent = it.parent()
        idx = (parent.indexOfChild(it) if parent is not None
               else self.indexOfTopLevelItem(it))
        if idx == 0:
            return "「{}」前面没有兄弟章节，无法降级".format(self._raw_title(it))
        prev = (parent.child(idx - 1) if parent is not None
                else self.topLevelItem(idx - 1))
        if prev.data(0, ROLE_KIND) == "BLOCK":
            return "前一个节点是内容块，只能降级到章节之下"
        prev_depth = self._depth_of(prev)
        if prev_depth + self._subtree_height(it) - 1 > self.MAX_DEPTH:
            return "降级后「{}」会超过 {} 层".format(self._raw_title(it),
                                                  self.MAX_DEPTH)
        if self.mutate_hook:
            self.mutate_hook()
        if parent is None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(it))
        else:
            parent.takeChild(parent.indexOfChild(it))
        prev.addChild(it)
        prev.setExpanded(True)
        self.renumber()
        self.setCurrentItem(it)
        return None

    def _add_sub_chapter(self, it):
        if self.mutate_hook:
            self.mutate_hook()
        if it is not None and it.data(0, ROLE_KIND) == "BLOCK":
            it = it.parent()
        if it is not None and it.data(0, ROLE_KIND) != "BLOCK":
            self.add_chapter("新章节", it)
        else:
            self.add_chapter("新章节")
        self.renumber()

    def _delete(self, it):
        if self.mutate_hook:
            self.mutate_hook()
        parent = it.parent()
        if parent is None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(it))
        else:
            parent.removeChild(it)
        self.renumber()

    # ----与渲染器/编排稿交换数据----

    def to_items(self):
        def walk(item):
            if item.data(0, ROLE_KIND) == "BLOCK":
                # 去显示用［类型］前缀：编排稿/撤回快照只存逻辑标题
                # （load_items 会按 ref 重加前缀，否则每撤回一次前缀翻倍）
                title = re.sub(r"^［[^］]*］\s*", "", self._raw_title(item))
                return {"kind": "block", "ref": item.data(0, ROLE_REF),
                        "title": title}   # 无编号原题
            return {"kind": "chapter", "title": self._raw_title(item),
                    "children": [walk(item.child(i))
                                 for i in range(item.childCount())]}

        return [walk(self.topLevelItem(i))
                for i in range(self.topLevelItemCount())]

    def load_items(self, items):
        self.clear()
        self._numbering = True

        def build(node, parent):
            if node["kind"] == "chapter":
                it = self.add_chapter(node["title"], parent)
                for c in node.get("children", []):
                    build(c, it)
            else:
                self.add_block(node["ref"], node["title"], parent)

        for n in items:
            build(n, None)
        self._numbering = False
        self.renumber()
