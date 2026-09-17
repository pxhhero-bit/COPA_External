# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'quoteChecklist.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

class Ui_quoteChecklist(object):
    def setupUi(self, quoteChecklist):
        if not quoteChecklist.objectName():
            quoteChecklist.setObjectName(u"quoteChecklist")
        quoteChecklist.resize(704, 450)
        quoteChecklist.setMinimumSize(QSize(660, 450))
        self.rootLayout = QHBoxLayout(quoteChecklist)
        self.rootLayout.setSpacing(0)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(0, 0, 0, 9)
        self.mainColumn = QWidget(quoteChecklist)
        self.mainColumn.setObjectName(u"mainColumn")
        self.mainLayout = QVBoxLayout(self.mainColumn)
        self.mainLayout.setSpacing(9)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QScrollArea(self.mainColumn)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 700, 212))
        self.cardcontainerLayout = QVBoxLayout(self.scrollAreaWidgetContents_2)
        self.cardcontainerLayout.setObjectName(u"cardcontainerLayout")
        self.cardcontainerLayout.setContentsMargins(22, 9, 9, 9)
        self.ChecklistContainer = QWidget(self.scrollAreaWidgetContents_2)
        self.ChecklistContainer.setObjectName(u"ChecklistContainer")

        self.cardcontainerLayout.addWidget(self.ChecklistContainer)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.cardcontainerLayout.addItem(self.verticalSpacer)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents_2)

        self.mainLayout.addWidget(self.scrollArea)

        self.bottomBlock = QHBoxLayout()
        self.bottomBlock.setSpacing(30)
        self.bottomBlock.setObjectName(u"bottomBlock")
        self.bottomBlock.setContentsMargins(-1, -1, 30, -1)
        self.leftRows = QVBoxLayout()
        self.leftRows.setSpacing(9)
        self.leftRows.setObjectName(u"leftRows")
        self.startButtonRow = QHBoxLayout()
        self.startButtonRow.setObjectName(u"startButtonRow")
        self.startButtonRow.setContentsMargins(-1, -1, 0, -1)
        self.horizontalSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.startButtonRow.addItem(self.horizontalSpacer)

        self.label = QLabel(self.mainColumn)
        self.label.setObjectName(u"label")
        font = QFont()
        font.setPointSize(11)
        self.label.setFont(font)

        self.startButtonRow.addWidget(self.label)

        self.titalComBox = QComboBox(self.mainColumn)
        self.titalComBox.addItem("")
        self.titalComBox.addItem("")
        self.titalComBox.setObjectName(u"titalComBox")
        self.titalComBox.setMinimumSize(QSize(70, 0))
        self.titalComBox.setFont(font)

        self.startButtonRow.addWidget(self.titalComBox)

        self.horizontalSpacer_2 = QSpacerItem(10, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.startButtonRow.addItem(self.horizontalSpacer_2)

        self.serviceCheckBox_1 = QCheckBox(self.mainColumn)
        self.serviceCheckBox_1.setObjectName(u"serviceCheckBox_1")
        self.serviceCheckBox_1.setFont(font)
        self.serviceCheckBox_1.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.startButtonRow.addWidget(self.serviceCheckBox_1)

        self.langLabel = QLabel(self.mainColumn)
        self.langLabel.setObjectName(u"langLabel")
        self.langLabel.setFont(font)

        self.startButtonRow.addWidget(self.langLabel)

        self.langComBox = QComboBox(self.mainColumn)
        self.langComBox.addItem("")
        self.langComBox.addItem("")
        self.langComBox.setObjectName(u"langComBox")
        self.langComBox.setFont(font)

        self.startButtonRow.addWidget(self.langComBox)

        self.pushButtonRollback = QPushButton(self.mainColumn)
        self.pushButtonRollback.setObjectName(u"pushButtonRollback")
        self.pushButtonRollback.setMinimumSize(QSize(80, 0))
        self.pushButtonRollback.setFont(font)
        self.pushButtonRollback.setStyleSheet(u"color: rgb(255, 0, 0);")

        self.startButtonRow.addWidget(self.pushButtonRollback)


        self.leftRows.addLayout(self.startButtonRow)

        self.companyInfoRow = QHBoxLayout()
        self.companyInfoRow.setObjectName(u"companyInfoRow")
        self.companyInfoRow.setContentsMargins(-1, -1, 0, -1)
        self.companyInfoLeftSpacer = QSpacerItem(30, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.companyInfoRow.addItem(self.companyInfoLeftSpacer)

        self.labelCompanyName = QLabel(self.mainColumn)
        self.labelCompanyName.setObjectName(u"labelCompanyName")
        self.labelCompanyName.setFont(font)

        self.companyInfoRow.addWidget(self.labelCompanyName)

        self.editCompanyName = QPlainTextEdit(self.mainColumn)
        self.editCompanyName.setObjectName(u"editCompanyName")
        self.editCompanyName.setMinimumSize(QSize(220, 0))
        self.editCompanyName.setMaximumSize(QSize(220, 28))
        font1 = QFont()
        font1.setPointSize(10)
        self.editCompanyName.setFont(font1)

        self.companyInfoRow.addWidget(self.editCompanyName)

        self.companyInfoMidSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.companyInfoRow.addItem(self.companyInfoMidSpacer)

        self.labelContactPerson = QLabel(self.mainColumn)
        self.labelContactPerson.setObjectName(u"labelContactPerson")
        self.labelContactPerson.setFont(font)

        self.companyInfoRow.addWidget(self.labelContactPerson)

        self.editContactPerson = QPlainTextEdit(self.mainColumn)
        self.editContactPerson.setObjectName(u"editContactPerson")
        self.editContactPerson.setMinimumSize(QSize(140, 0))
        self.editContactPerson.setMaximumSize(QSize(140, 28))
        self.editContactPerson.setFont(font)
        self.editContactPerson.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editContactPerson.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.companyInfoRow.addWidget(self.editContactPerson)


        self.leftRows.addLayout(self.companyInfoRow)


        self.bottomBlock.addLayout(self.leftRows)

        self.pushButtonOutput = QPushButton(self.mainColumn)
        self.pushButtonOutput.setObjectName(u"pushButtonOutput")
        self.pushButtonOutput.setMinimumSize(QSize(120, 64))
        font2 = QFont()
        font2.setFamilies([u"\u5fae\u8f6f\u96c5\u9ed1"])
        font2.setPointSize(16)
        self.pushButtonOutput.setFont(font2)

        self.bottomBlock.addWidget(self.pushButtonOutput, 0, Qt.AlignmentFlag.AlignVCenter)


        self.mainLayout.addLayout(self.bottomBlock)


        self.rootLayout.addWidget(self.mainColumn)


        self.retranslateUi(quoteChecklist)

        QMetaObject.connectSlotsByName(quoteChecklist)
    # setupUi

    def retranslateUi(self, quoteChecklist):
        quoteChecklist.setWindowTitle(QCoreApplication.translate("quoteChecklist", u"\u9009\u578b\u6e05\u5355 ", None))
        self.label.setText(QCoreApplication.translate("quoteChecklist", u"\u62a5\u4ef7\u62ac\u5934", None))
        self.titalComBox.setItemText(0, QCoreApplication.translate("quoteChecklist", u"\u9a91\u665f", None))
        self.titalComBox.setItemText(1, QCoreApplication.translate("quoteChecklist", u"\u827e\u529b\u5a01", None))

        self.serviceCheckBox_1.setText(QCoreApplication.translate("quoteChecklist", u"\u73b0\u573a\u670d\u52a1", None))
        self.langLabel.setText(QCoreApplication.translate("quoteChecklist", u"\u62a5\u4ef7\u8bed\u8a00", None))
        self.langComBox.setItemText(0, QCoreApplication.translate("quoteChecklist", u"\u4e2d\u6587", None))
        self.langComBox.setItemText(1, QCoreApplication.translate("quoteChecklist", u"\u82f1\u6587", None))

        self.pushButtonRollback.setText(QCoreApplication.translate("quoteChecklist", u"\u56de\u9000\u4fee\u6539", None))
        self.labelCompanyName.setText(QCoreApplication.translate("quoteChecklist", u"\u516c\u53f8\u540d\u79f0", None))
        self.labelContactPerson.setText(QCoreApplication.translate("quoteChecklist", u"\u8054\u7cfb\u4eba", None))
        self.pushButtonOutput.setText(QCoreApplication.translate("quoteChecklist", u"\u8f93\u51fa\u62a5\u4ef7", None))
    # retranslateUi

