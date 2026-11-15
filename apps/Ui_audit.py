# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'audit.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget)

class Ui_AuditDialog(object):
    def setupUi(self, AuditDialog):
        if not AuditDialog.objectName():
            AuditDialog.setObjectName(u"AuditDialog")
        AuditDialog.resize(920, 640)
        self.mainLayout = QVBoxLayout(AuditDialog)
        self.mainLayout.setSpacing(6)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(AuditDialog)
        self.stack.setObjectName(u"stack")
        self.pageSelect = QWidget()
        self.pageSelect.setObjectName(u"pageSelect")
        self.selectLayout = QVBoxLayout(self.pageSelect)
        self.selectLayout.setSpacing(6)
        self.selectLayout.setObjectName(u"selectLayout")
        self.selectLayout.setContentsMargins(64, 12, 64, 12)
        self.topSpacer = QSpacerItem(0, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.selectLayout.addItem(self.topSpacer)

        self.titleLabel = QLabel(self.pageSelect)
        self.titleLabel.setObjectName(u"titleLabel")
        self.titleLabel.setStyleSheet(u"font-size: 26px; font-weight: bold;")
        self.titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.selectLayout.addWidget(self.titleLabel)

        self.hintLabel = QLabel(self.pageSelect)
        self.hintLabel.setObjectName(u"hintLabel")
        font = QFont()
        font.setPointSize(12)
        self.hintLabel.setFont(font)
        self.hintLabel.setStyleSheet(u"color: #666666;")
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.selectLayout.addWidget(self.hintLabel)

        self.midSpacer = QSpacerItem(0, 24, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.selectLayout.addItem(self.midSpacer)

        self.dropZone = QFrame(self.pageSelect)
        self.dropZone.setObjectName(u"dropZone")
        self.dropZone.setMinimumSize(QSize(0, 190))
        self.dropZone.setStyleSheet(u"QFrame#dropZone {\n"
"    border: 2px dashed #A8A8A8;\n"
"    border-radius: 10px;\n"
"    background-color: #FAFAFA;\n"
"}\n"
"QFrame#dropZone[dragOver=\"true\"] {\n"
"    border: 2px dashed #C00000;\n"
"    background-color: #FFF3F3;\n"
"}")
        self.dropLayout = QVBoxLayout(self.dropZone)
        self.dropLayout.setSpacing(12)
        self.dropLayout.setObjectName(u"dropLayout")
        self.dropTopSpacer = QSpacerItem(0, 16, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.dropLayout.addItem(self.dropTopSpacer)

        self.dropIcon = QLabel(self.dropZone)
        self.dropIcon.setObjectName(u"dropIcon")
        self.dropIcon.setStyleSheet(u"font-size: 30px; color: #888888; border: none;")
        self.dropIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.dropLayout.addWidget(self.dropIcon)

        self.dropLabel = QLabel(self.dropZone)
        self.dropLabel.setObjectName(u"dropLabel")
        self.dropLabel.setFont(font)
        self.dropLabel.setStyleSheet(u"color: #555555; border: none;")
        self.dropLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.dropLayout.addWidget(self.dropLabel)

        self.btnChoose = QPushButton(self.dropZone)
        self.btnChoose.setObjectName(u"btnChoose")
        self.btnChoose.setFont(font)

        self.dropLayout.addWidget(self.btnChoose, 0, Qt.AlignmentFlag.AlignHCenter)

        self.dropBottomSpacer = QSpacerItem(0, 16, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.dropLayout.addItem(self.dropBottomSpacer)


        self.selectLayout.addWidget(self.dropZone)

        self.fileLabel = QLabel(self.pageSelect)
        self.fileLabel.setObjectName(u"fileLabel")
        self.fileLabel.setStyleSheet(u"color: #333333; font-weight: bold;")
        self.fileLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.selectLayout.addWidget(self.fileLabel)

        self.btnStart = QPushButton(self.pageSelect)
        self.btnStart.setObjectName(u"btnStart")
        self.btnStart.setEnabled(False)
        self.btnStart.setMinimumSize(QSize(160, 38))
        font1 = QFont()
        font1.setBold(True)
        self.btnStart.setFont(font1)
        self.btnStart.setStyleSheet(u"font-weight: bold; font-size: 15px;")

        self.selectLayout.addWidget(self.btnStart, 0, Qt.AlignmentFlag.AlignHCenter)

        self.bottomSpacer = QSpacerItem(0, 56, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.selectLayout.addItem(self.bottomSpacer)

        self.stack.addWidget(self.pageSelect)
        self.pageProgress = QWidget()
        self.pageProgress.setObjectName(u"pageProgress")
        self.progressLayout = QVBoxLayout(self.pageProgress)
        self.progressLayout.setObjectName(u"progressLayout")
        self.pTopSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.progressLayout.addItem(self.pTopSpacer)

        self.progressTitle = QLabel(self.pageProgress)
        self.progressTitle.setObjectName(u"progressTitle")
        self.progressTitle.setStyleSheet(u"font-size: 20px; font-weight: bold;")
        self.progressTitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progressLayout.addWidget(self.progressTitle)

        self.fileTag = QLabel(self.pageProgress)
        self.fileTag.setObjectName(u"fileTag")
        self.fileTag.setStyleSheet(u"color: #666666;")
        self.fileTag.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progressLayout.addWidget(self.fileTag)

        self.progressLabel = QLabel(self.pageProgress)
        self.progressLabel.setObjectName(u"progressLabel")
        self.progressLabel.setStyleSheet(u"font-family: \"Consolas\", \"Courier New\", monospace; font-size: 18px; color: #C00000;")
        self.progressLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progressLayout.addWidget(self.progressLabel)

        self.progressHint = QLabel(self.pageProgress)
        self.progressHint.setObjectName(u"progressHint")
        self.progressHint.setStyleSheet(u"color: #444444;")
        self.progressHint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progressLayout.addWidget(self.progressHint)

        self.pBottomSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.progressLayout.addItem(self.pBottomSpacer)

        self.stack.addWidget(self.pageProgress)
        self.pageResult = QWidget()
        self.pageResult.setObjectName(u"pageResult")
        self.resultLayout = QVBoxLayout(self.pageResult)
        self.resultLayout.setObjectName(u"resultLayout")
        self.resultLayout.setContentsMargins(12, 12, 12, 8)
        self.splitter = QSplitter(self.pageResult)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.tableWidget = QTableWidget(self.splitter)
        if (self.tableWidget.columnCount() < 6):
            self.tableWidget.setColumnCount(6)
        __qtablewidgetitem = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        self.tableWidget.setObjectName(u"tableWidget")
        self.tableWidget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tableWidget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tableWidget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tableWidget.setColumnCount(6)
        self.splitter.addWidget(self.tableWidget)
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
        self.tableWidget.verticalHeader().setVisible(False)
        self.detailBrowser = QTextBrowser(self.splitter)
        self.detailBrowser.setObjectName(u"detailBrowser")
        self.detailBrowser.setStyleSheet(u"QTextBrowser { border: 1px solid #D0D0D0; background: #FCFCFC; }")
        self.splitter.addWidget(self.detailBrowser)

        self.resultLayout.addWidget(self.splitter)

        self.bottomBar = QHBoxLayout()
        self.bottomBar.setObjectName(u"bottomBar")
        self.statLabel = QLabel(self.pageResult)
        self.statLabel.setObjectName(u"statLabel")
        self.statLabel.setStyleSheet(u"color: #333333;")

        self.bottomBar.addWidget(self.statLabel)

        self.btnOpenFolder = QPushButton(self.pageResult)
        self.btnOpenFolder.setObjectName(u"btnOpenFolder")

        self.bottomBar.addWidget(self.btnOpenFolder)

        self.btnAgain = QPushButton(self.pageResult)
        self.btnAgain.setObjectName(u"btnAgain")

        self.bottomBar.addWidget(self.btnAgain)


        self.resultLayout.addLayout(self.bottomBar)

        self.stack.addWidget(self.pageResult)

        self.mainLayout.addWidget(self.stack)


        self.retranslateUi(AuditDialog)

        QMetaObject.connectSlotsByName(AuditDialog)
    # setupUi

    def retranslateUi(self, AuditDialog):
        AuditDialog.setWindowTitle(QCoreApplication.translate("AuditDialog", u"\u62a5\u4ef7\u8bca\u65ad - COPA", None))
        self.titleLabel.setText(QCoreApplication.translate("AuditDialog", u"\u62a5\u4ef7\u5355\u8bca\u65ad", None))
        self.hintLabel.setText(QCoreApplication.translate("AuditDialog", u"\u4e0a\u4f20\u62a5\u4ef7\u5355\uff0c\u81ea\u52a8\u68c0\u67e5\u914d\u7f6e\u4e0e\u7b97\u672f\u7b49\u57fa\u672c\u9519\u8bef\u3002\u652f\u6301 .xlsx / .xlsm/ .xls", None))
        self.dropIcon.setText(QCoreApplication.translate("AuditDialog", u"\u21e9", None))
        self.dropLabel.setText(QCoreApplication.translate("AuditDialog", u"\u628a\u62a5\u4ef7\u5355\u62d6\u5230\u8fd9\u91cc\uff0c\u6216", None))
        self.btnChoose.setText(QCoreApplication.translate("AuditDialog", u"\u9009\u62e9\u6587\u4ef6...", None))
        self.fileLabel.setText("")
        self.btnStart.setText(QCoreApplication.translate("AuditDialog", u"\u5f00\u59cb\u68c0\u67e5", None))
        self.progressTitle.setText(QCoreApplication.translate("AuditDialog", u"\u6b63\u5728\u6279\u9605", None))
        self.fileTag.setText("")
        self.progressLabel.setText(QCoreApplication.translate("AuditDialog", u"[\u25a1\u25a1\u25a1\u25a1\u25a1\u25a1\u25a1\u25a1\u25a1\u25a1] 0/6", None))
        self.progressHint.setText("")
        # horizontalHeaderItem() 可能返回 None（列头没建出来时），逐个判空再改字。
        ___headers = (
            u"\u5de5\u4f5c\u8868", u"\u884c", u"\u540d\u79f0 / \u578b\u53f7",
            u"\u95ee\u9898\u7801", u"\u7ea7\u522b", u"\u95ee\u9898",
        )
        for ___index, ___text in enumerate(___headers):
            ___item = self.tableWidget.horizontalHeaderItem(___index)
            if ___item is not None:
                ___item.setText(QCoreApplication.translate("AuditDialog", ___text, None))
        self.statLabel.setText("")
        self.btnOpenFolder.setText(QCoreApplication.translate("AuditDialog", u"\u6253\u5f00\u62a5\u544a\u6587\u4ef6\u5939", None))
        self.btnAgain.setText(QCoreApplication.translate("AuditDialog", u"\u91cd\u65b0\u68c0\u67e5", None))
    # retranslateUi

