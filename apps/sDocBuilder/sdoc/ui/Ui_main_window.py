# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMenuBar, QPushButton, QSizePolicy,
    QSpacerItem, QSplitter, QStatusBar, QTextBrowser,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from sdoc.ui.panels import (OutlinePanel, PoolPanel)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1120, 760)
        icon = QIcon()
        icon.addFile(u"../../assets/app.ico", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        MainWindow.setWindowIcon(icon)
        self.actionOpenSnapshot = QAction(MainWindow)
        self.actionOpenSnapshot.setObjectName(u"actionOpenSnapshot")
        icon1 = QIcon(QIcon.fromTheme(u"folder-open"))
        self.actionOpenSnapshot.setIcon(icon1)
        self.actionSaveArrangement = QAction(MainWindow)
        self.actionSaveArrangement.setObjectName(u"actionSaveArrangement")
        icon2 = QIcon(QIcon.fromTheme(u"document-save"))
        self.actionSaveArrangement.setIcon(icon2)
        self.actionLoadArrangement = QAction(MainWindow)
        self.actionLoadArrangement.setObjectName(u"actionLoadArrangement")
        self.actionLoadArrangement.setIcon(icon1)
        self.actionRebuildTemplate = QAction(MainWindow)
        self.actionRebuildTemplate.setObjectName(u"actionRebuildTemplate")
        icon3 = QIcon(QIcon.fromTheme(u"system-reboot"))
        self.actionRebuildTemplate.setIcon(icon3)
        self.actionQuit = QAction(MainWindow)
        self.actionQuit.setObjectName(u"actionQuit")
        icon4 = QIcon(QIcon.fromTheme(u"system-shutdown"))
        self.actionQuit.setIcon(icon4)
        self.actionUndo = QAction(MainWindow)
        self.actionUndo.setObjectName(u"actionUndo")
        icon5 = QIcon(QIcon.fromTheme(u"edit-undo"))
        self.actionUndo.setIcon(icon5)
        self.actionRedo = QAction(MainWindow)
        self.actionRedo.setObjectName(u"actionRedo")
        icon6 = QIcon(QIcon.fromTheme(u"edit-redo"))
        self.actionRedo.setIcon(icon6)
        self.actionPromote = QAction(MainWindow)
        self.actionPromote.setObjectName(u"actionPromote")
        icon7 = QIcon(QIcon.fromTheme(u"go-previous"))
        self.actionPromote.setIcon(icon7)
        self.actionDemote = QAction(MainWindow)
        self.actionDemote.setObjectName(u"actionDemote")
        icon8 = QIcon(QIcon.fromTheme(u"go-next"))
        self.actionDemote.setIcon(icon8)
        self.actionDeleteNode = QAction(MainWindow)
        self.actionDeleteNode.setObjectName(u"actionDeleteNode")
        icon9 = QIcon(QIcon.fromTheme(u"application-exit"))
        self.actionDeleteNode.setIcon(icon9)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.mainLayout = QVBoxLayout(self.centralwidget)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(12, 12, 12, 12)
        self.splitter = QSplitter(self.centralwidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.poolTree = PoolPanel(self.splitter)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, u"1")
        self.poolTree.setHeaderItem(__qtreewidgetitem)
        self.poolTree.setObjectName(u"poolTree")
        self.splitter.addWidget(self.poolTree)
        self.page = QFrame(self.splitter)
        self.page.setObjectName(u"page")
        self.page.setStyleSheet(u"QFrame { background: #ffffff; border: 1px solid #dddddd; }")
        self.pageLayout = QVBoxLayout(self.page)
        self.pageLayout.setObjectName(u"pageLayout")
        self.pageLayout.setContentsMargins(24, 24, 24, 24)
        self.outlineTree = OutlinePanel(self.page)
        __qtreewidgetitem1 = QTreeWidgetItem()
        __qtreewidgetitem1.setText(0, u"1")
        self.outlineTree.setHeaderItem(__qtreewidgetitem1)
        self.outlineTree.setObjectName(u"outlineTree")

        self.pageLayout.addWidget(self.outlineTree)

        self.splitter.addWidget(self.page)
        self.previewBrowser = QTextBrowser(self.splitter)
        self.previewBrowser.setObjectName(u"previewBrowser")
        self.previewBrowser.setStyleSheet(u"QTextBrowser { background: #ffffff; border: 1px solid #dddddd; }")
        self.splitter.addWidget(self.previewBrowser)

        self.mainLayout.addWidget(self.splitter)

        self.buttonRow = QHBoxLayout()
        self.buttonRow.setObjectName(u"buttonRow")
        self.labelProjectName = QLabel(self.centralwidget)
        self.labelProjectName.setObjectName(u"labelProjectName")
        font = QFont()
        font.setPointSize(12)
        self.labelProjectName.setFont(font)

        self.buttonRow.addWidget(self.labelProjectName)

        self.editProjectName = QLineEdit(self.centralwidget)
        self.editProjectName.setObjectName(u"editProjectName")
        self.editProjectName.setMinimumSize(QSize(220, 0))
        font1 = QFont()
        font1.setPointSize(11)
        self.editProjectName.setFont(font1)

        self.buttonRow.addWidget(self.editProjectName)

        self.labelCustomerName = QLabel(self.centralwidget)
        self.labelCustomerName.setObjectName(u"labelCustomerName")
        self.labelCustomerName.setFont(font)

        self.buttonRow.addWidget(self.labelCustomerName)

        self.editCustomerName = QLineEdit(self.centralwidget)
        self.editCustomerName.setObjectName(u"editCustomerName")
        self.editCustomerName.setMinimumSize(QSize(220, 0))
        self.editCustomerName.setFont(font1)

        self.buttonRow.addWidget(self.editCustomerName)

        self.midSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.buttonRow.addItem(self.midSpacer)

        self.label = QLabel(self.centralwidget)
        self.label.setObjectName(u"label")
        self.label.setFont(font)

        self.buttonRow.addWidget(self.label)

        self.comboBox = QComboBox(self.centralwidget)
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.setObjectName(u"comboBox")
        self.comboBox.setFont(font1)

        self.buttonRow.addWidget(self.comboBox)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.buttonRow.addItem(self.horizontalSpacer)

        self.btnPreview = QPushButton(self.centralwidget)
        self.btnPreview.setObjectName(u"btnPreview")
        self.btnPreview.setMinimumSize(QSize(130, 40))
        self.btnPreview.setMaximumSize(QSize(120, 16777215))
        font2 = QFont()
        font2.setPointSize(15)
        self.btnPreview.setFont(font2)

        self.buttonRow.addWidget(self.btnPreview)


        self.mainLayout.addLayout(self.buttonRow)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1120, 33))
        self.menuFile = QMenu(self.menubar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuEdit = QMenu(self.menubar)
        self.menuEdit.setObjectName(u"menuEdit")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuEdit.menuAction())
        self.menuFile.addAction(self.actionOpenSnapshot)
        self.menuFile.addAction(self.actionSaveArrangement)
        self.menuFile.addAction(self.actionLoadArrangement)
        self.menuFile.addAction(self.actionRebuildTemplate)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionQuit)
        self.menuEdit.addAction(self.actionUndo)
        self.menuEdit.addAction(self.actionRedo)
        self.menuEdit.addSeparator()
        self.menuEdit.addAction(self.actionPromote)
        self.menuEdit.addAction(self.actionDemote)
        self.menuEdit.addAction(self.actionDeleteNode)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u6280\u672f\u65b9\u6848\u7f16\u6392", None))
        self.actionOpenSnapshot.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00\u5feb\u7167\u2026", None))
        self.actionSaveArrangement.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u7f16\u6392\u7a3f", None))
#if QT_CONFIG(shortcut)
        self.actionSaveArrangement.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+S", None))
#endif // QT_CONFIG(shortcut)
        self.actionLoadArrangement.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00\u7f16\u6392\u7a3f\u2026", None))
#if QT_CONFIG(shortcut)
        self.actionLoadArrangement.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+O", None))
#endif // QT_CONFIG(shortcut)
        self.actionRebuildTemplate.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u65b0\u94fa\u9ed8\u8ba4\u6a21\u677f", None))
        self.actionQuit.setText(QCoreApplication.translate("MainWindow", u"\u9000\u51fa", None))
        self.actionUndo.setText(QCoreApplication.translate("MainWindow", u"\u64a4\u56de", None))
#if QT_CONFIG(shortcut)
        self.actionUndo.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+Z", None))
#endif // QT_CONFIG(shortcut)
        self.actionRedo.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u505a", None))
#if QT_CONFIG(shortcut)
        self.actionRedo.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+Y", None))
#endif // QT_CONFIG(shortcut)
        self.actionPromote.setText(QCoreApplication.translate("MainWindow", u"\u5347\u7ea7", None))
#if QT_CONFIG(shortcut)
        self.actionPromote.setShortcut(QCoreApplication.translate("MainWindow", u"Shift+Tab", None))
#endif // QT_CONFIG(shortcut)
        self.actionDemote.setText(QCoreApplication.translate("MainWindow", u"\u964d\u7ea7", None))
#if QT_CONFIG(shortcut)
        self.actionDemote.setShortcut(QCoreApplication.translate("MainWindow", u"Tab", None))
#endif // QT_CONFIG(shortcut)
        self.actionDeleteNode.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664\u9009\u4e2d\u8282\u70b9\uff08Del\uff09", None))
        self.labelProjectName.setText(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u540d\u79f0", None))
        self.editProjectName.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u786e\u8ba4\u65f6\u5c06\u53cd\u5199\u56de\u5feb\u7167", None))
        self.labelCustomerName.setText(QCoreApplication.translate("MainWindow", u"\u5ba2\u6237\u540d\u79f0", None))
        self.editCustomerName.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u65e0\u5feb\u7167\u65f6\u53ef\u76f4\u63a5\u8f93\u5165", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"\u516c\u53f8\u62ac\u5934", None))
        self.comboBox.setItemText(0, QCoreApplication.translate("MainWindow", u"\u9a91\u665f", None))
        self.comboBox.setItemText(1, QCoreApplication.translate("MainWindow", u"\u827e\u529b\u5a01", None))

        self.btnPreview.setText(QCoreApplication.translate("MainWindow", u"\u751f\u6210\u9884\u89c8", None))
        self.menuFile.setTitle(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6", None))
        self.menuEdit.setTitle(QCoreApplication.translate("MainWindow", u"\u7f16\u8f91", None))
    # retranslateUi

