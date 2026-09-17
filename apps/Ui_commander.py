# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'commander.ui'
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
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMenuBar,
    QSizePolicy, QStatusBar, QToolBar, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1250, 850)
        MainWindow.setStyleSheet(u"QMdiSubWindow {\n"
"    background-color: #F3F3F3;\n"
"    border: 1px solid #444444;\n"
"    color: rgb(0, 0, 0);\n"
"}\n"
"\n"
"/* \u6807\u9898\u680f\u533a\u57df\uff08\u901a\u8fc7\u5185\u90e8\u5e03\u5c40\u63a7\u5236\uff09 */\n"
"QMdiSubWindow > QWidget {\n"
"    background-color: rgb(255, 255, 255);\n"
"    color: rgb(0, 0, 0);\n"
"}\n"
"QMainWindow {background-color: rgb(117, 117, 117)}")
        self.actionNew = QAction(MainWindow)
        self.actionNew.setObjectName(u"actionNew")
        icon = QIcon(QIcon.fromTheme(u"document-new"))
        self.actionNew.setIcon(icon)
        self.actionNew.setVisible(True)
        self.actionNew.setIconVisibleInMenu(True)
        self.actionNew.setPriority(QAction.Priority.HighPriority)
        self.actionOpen = QAction(MainWindow)
        self.actionOpen.setObjectName(u"actionOpen")
        icon1 = QIcon(QIcon.fromTheme(u"document-open"))
        self.actionOpen.setIcon(icon1)
        self.actionSave = QAction(MainWindow)
        self.actionSave.setObjectName(u"actionSave")
        icon2 = QIcon(QIcon.fromTheme(u"document-save"))
        self.actionSave.setIcon(icon2)
        self.actionCloseCurrent = QAction(MainWindow)
        self.actionCloseCurrent.setObjectName(u"actionCloseCurrent")
        icon3 = QIcon(QIcon.fromTheme(u"application-exit"))
        self.actionCloseCurrent.setIcon(icon3)
        self.actionCloseCurrent.setMenuRole(QAction.MenuRole.TextHeuristicRole)
        self.actionCloseAll = QAction(MainWindow)
        self.actionCloseAll.setObjectName(u"actionCloseAll")
        self.actionCloseAll.setIcon(icon3)
        self.actionCut = QAction(MainWindow)
        self.actionCut.setObjectName(u"actionCut")
        icon4 = QIcon(QIcon.fromTheme(u"edit-cut"))
        self.actionCut.setIcon(icon4)
        self.actionCopy = QAction(MainWindow)
        self.actionCopy.setObjectName(u"actionCopy")
        icon5 = QIcon(QIcon.fromTheme(u"edit-copy"))
        self.actionCopy.setIcon(icon5)
        self.actionPaste = QAction(MainWindow)
        self.actionPaste.setObjectName(u"actionPaste")
        icon6 = QIcon(QIcon.fromTheme(u"edit-paste"))
        self.actionPaste.setIcon(icon6)
        self.actionDel = QAction(MainWindow)
        self.actionDel.setObjectName(u"actionDel")
        icon7 = QIcon(QIcon.fromTheme(u"edit-delete"))
        self.actionDel.setIcon(icon7)
        self.actionSelectAll = QAction(MainWindow)
        self.actionSelectAll.setObjectName(u"actionSelectAll")
        self.actionManual = QAction(MainWindow)
        self.actionManual.setObjectName(u"actionManual")
        icon8 = QIcon(QIcon.fromTheme(u"help-browser"))
        self.actionManual.setIcon(icon8)
        self.actionInfo = QAction(MainWindow)
        self.actionInfo.setObjectName(u"actionInfo")
        icon9 = QIcon(QIcon.fromTheme(u"help-about"))
        self.actionInfo.setIcon(icon9)
        self.actionFeedback = QAction(MainWindow)
        self.actionFeedback.setObjectName(u"actionFeedback")
        icon10 = QIcon(QIcon.fromTheme(u"mail-forward"))
        self.actionFeedback.setIcon(icon10)
        self.actionDefaultInput = QAction(MainWindow)
        self.actionDefaultInput.setObjectName(u"actionDefaultInput")
        icon11 = QIcon(QIcon.fromTheme(u"mail-message-new"))
        self.actionDefaultInput.setIcon(icon11)
        self.actionToolA = QAction(MainWindow)
        self.actionToolA.setObjectName(u"actionToolA")
        icon12 = QIcon(QIcon.fromTheme(u"accessories-calculator"))
        self.actionToolA.setIcon(icon12)
        self.actionToolB = QAction(MainWindow)
        self.actionToolB.setObjectName(u"actionToolB")
        icon13 = QIcon(QIcon.fromTheme(u"document-print"))
        self.actionToolB.setIcon(icon13)
        self.actionNSD = QAction(MainWindow)
        self.actionNSD.setObjectName(u"actionNSD")
        self.actionNSD.setIcon(icon)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        MainWindow.setCentralWidget(self.centralwidget)
        self.toolBarLeft = QToolBar(MainWindow)
        self.toolBarLeft.setObjectName(u"toolBarLeft")
        self.toolBarLeft.setMinimumSize(QSize(0, 0))
        self.toolBarLeft.setMovable(False)
        self.toolBarLeft.setIconSize(QSize(32, 32))
        self.toolBarLeft.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toolBarLeft.setFloatable(False)
        MainWindow.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.toolBarLeft)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1250, 33))
        self.menubar.setStyleSheet(u"/* \u83dc\u5355\u680f\u80cc\u666f */\n"
"QMenuBar {\n"
"    background-color: rgb(234, 234, 234);\n"
"    color: rgb(0, 0, 0);\n"
"}\n"
"\n"
"/* \u83dc\u5355\u680f\u9879\uff1a\u9f20\u6807\u60ac\u505c/\u9009\u4e2d\u65f6\u7684\u6837\u5f0f */\n"
"QMenuBar::item:selected {\n"
"    background-color: rgb(222, 222, 222);  /* \u9009\u4e2d\u80cc\u666f\u8272 */\n"
"    color: rgb(0, 0, 0);             /* \u9009\u4e2d\u6587\u5b57\u8272 */\n"
"    border-radius: 4px;\n"
"}\n"
"\n"
"/* \u83dc\u5355\u680f\u9879\uff1a\u6309\u4e0b\u65f6\u7684\u6837\u5f0f */\n"
"QMenuBar::item:pressed {\n"
"    background-color: rgb(222, 222, 222);\n"
"    color: rgb(0, 0, 0);\n"
"}\n"
"\n"
"/* \u4e0b\u62c9\u83dc\u5355\u6574\u4f53\u80cc\u666f */\n"
"QMenu {\n"
"    background-color: rgb(255, 255, 255);\n"
"    color: rgb(0, 0, 0);\n"
"    border: 1px solid #444444;\n"
"}\n"
"\n"
"/* \u4e0b\u62c9\u83dc\u5355\u9879\uff1a\u60ac\u505c/\u9009\u4e2d */\n"
"QMenu::item:selected {\n"
"    background-color: rgb(222, 222, 222);\n"
"    color: rgb(0, 0, "
                        "0);\n"
"    border-radius: 3px;\n"
"}\n"
"\n"
"/* \u4e0b\u62c9\u83dc\u5355\u9879\uff1a\u7981\u7528\u72b6\u6001 */\n"
"QMenu::item:disabled {\n"
"    color: #888888;\n"
"}\n"
"\n"
"/* \u5206\u9694\u7ebf\u989c\u8272 */\n"
"QMenu::separator {\n"
"    background-color: #444444;\n"
"    height: 1px;\n"
"    margin: 4px 8px;\n"
"}")
        self.menuFile = QMenu(self.menubar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuEdit = QMenu(self.menubar)
        self.menuEdit.setObjectName(u"menuEdit")
        self.menuConfig = QMenu(self.menubar)
        self.menuConfig.setObjectName(u"menuConfig")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        self.statusbar.setStyleSheet(u"background-color: rgb(226, 226, 226)")
        MainWindow.setStatusBar(self.statusbar)

        self.toolBarLeft.addAction(self.actionToolA)
        self.toolBarLeft.addAction(self.actionToolB)
        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuEdit.menuAction())
        self.menubar.addAction(self.menuConfig.menuAction())
        self.menuFile.addAction(self.actionNew)
        self.menuFile.addAction(self.actionNSD)
        self.menuFile.addAction(self.actionOpen)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionSave)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionCloseCurrent)
        self.menuFile.addAction(self.actionCloseAll)
        self.menuEdit.addAction(self.actionCut)
        self.menuEdit.addAction(self.actionCopy)
        self.menuEdit.addAction(self.actionPaste)
        self.menuEdit.addAction(self.actionDel)
        self.menuEdit.addAction(self.actionSelectAll)
        self.menuConfig.addAction(self.actionDefaultInput)
        self.menuConfig.addSeparator()
        self.menuConfig.addAction(self.actionManual)
        self.menuConfig.addSeparator()
        self.menuConfig.addAction(self.actionInfo)
        self.menuConfig.addAction(self.actionFeedback)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"COPA  \u9009\u578b\u62a5\u4ef7\u8f85\u52a9\u7cfb\u7edf", None))
        self.actionNew.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa\u62a5\u4ef7\u9009\u578b", None))
#if QT_CONFIG(tooltip)
        self.actionNew.setToolTip(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa\u9879\u76ee\u62a5\u4ef7", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(shortcut)
        self.actionNew.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+N", None))
#endif // QT_CONFIG(shortcut)
        self.actionOpen.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00\u9879\u76ee\u5feb\u7167", None))
        self.actionSave.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u9879\u76ee\u5feb\u7167", None))
#if QT_CONFIG(tooltip)
        self.actionSave.setToolTip(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u9879\u76ee\u5feb\u7167", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(shortcut)
        self.actionSave.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+S", None))
#endif // QT_CONFIG(shortcut)
        self.actionCloseCurrent.setText(QCoreApplication.translate("MainWindow", u"\u5173\u95ed\u5f53\u524d...", None))
#if QT_CONFIG(shortcut)
        self.actionCloseCurrent.setShortcut(QCoreApplication.translate("MainWindow", u"Shift+F4", None))
#endif // QT_CONFIG(shortcut)
        self.actionCloseAll.setText(QCoreApplication.translate("MainWindow", u"\u5173\u95ed\u6240\u6709...", None))
        self.actionCut.setText(QCoreApplication.translate("MainWindow", u"\u526a\u5207", None))
#if QT_CONFIG(shortcut)
        self.actionCut.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+X", None))
#endif // QT_CONFIG(shortcut)
        self.actionCopy.setText(QCoreApplication.translate("MainWindow", u"\u590d\u5236", None))
#if QT_CONFIG(shortcut)
        self.actionCopy.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+C", None))
#endif // QT_CONFIG(shortcut)
        self.actionPaste.setText(QCoreApplication.translate("MainWindow", u"\u7c98\u8d34", None))
#if QT_CONFIG(shortcut)
        self.actionPaste.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+V", None))
#endif // QT_CONFIG(shortcut)
        self.actionDel.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664", None))
#if QT_CONFIG(shortcut)
        self.actionDel.setShortcut(QCoreApplication.translate("MainWindow", u"Del", None))
#endif // QT_CONFIG(shortcut)
        self.actionSelectAll.setText(QCoreApplication.translate("MainWindow", u"\u5168\u9009", None))
#if QT_CONFIG(shortcut)
        self.actionSelectAll.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+A", None))
#endif // QT_CONFIG(shortcut)
        self.actionManual.setText(QCoreApplication.translate("MainWindow", u"\u4f7f\u7528\u8bf4\u660e", None))
        self.actionInfo.setText(QCoreApplication.translate("MainWindow", u"\u5173\u4e8eCOPA", None))
        self.actionFeedback.setText(QCoreApplication.translate("MainWindow", u"\u53cd\u9988\u4e0e\u4f18\u5316", None))
        self.actionDefaultInput.setText(QCoreApplication.translate("MainWindow", u"\u9ed8\u8ba4\u8f93\u5165\u65b9\u5f0f...", None))
#if QT_CONFIG(tooltip)
        self.actionDefaultInput.setToolTip(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u9700\u6c42\u5f55\u5165\u7a97\u53e3\u9ed8\u8ba4\u663e\u793a\u7684\u8f93\u5165\u9875\u7b7e", None))
#endif // QT_CONFIG(tooltip)
        self.actionToolA.setText(QCoreApplication.translate("MainWindow", u"\u9009\u578b\u62a5\u4ef7", None))
#if QT_CONFIG(tooltip)
        self.actionToolA.setToolTip(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa\u62a5\u4ef7\u9879\u76ee\uff08Desk\uff09", None))
#endif // QT_CONFIG(tooltip)
        self.actionToolB.setText(QCoreApplication.translate("MainWindow", u"\u6280\u672f\u65b9\u6848", None))
#if QT_CONFIG(tooltip)
        self.actionToolB.setToolTip(QCoreApplication.translate("MainWindow", u"sDocBuilder \u6280\u672f\u65b9\u6848\u7f16\u6392", None))
#endif // QT_CONFIG(tooltip)
        self.actionNSD.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa\u6280\u672f\u65b9\u6848", None))
#if QT_CONFIG(shortcut)
        self.actionNSD.setShortcut(QCoreApplication.translate("MainWindow", u"Shift+O", None))
#endif // QT_CONFIG(shortcut)
        self.toolBarLeft.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u5de5\u5177\u680f", None))
        self.menuFile.setTitle(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6", None))
        self.menuEdit.setTitle(QCoreApplication.translate("MainWindow", u"\u7f16\u8f91", None))
        self.menuConfig.setTitle(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e", None))
    # retranslateUi

