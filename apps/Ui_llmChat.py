# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'llmChat.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpacerItem, QToolButton, QVBoxLayout,
    QWidget)

class Ui_LlmChat(object):
    def setupUi(self, LlmChat):
        if not LlmChat.objectName():
            LlmChat.setObjectName(u"LlmChat")
        LlmChat.resize(920, 640)
        LlmChat.setMinimumSize(QSize(720, 480))
        LlmChat.setStyleSheet(u"#LlmChat { background-color: #f7f8fa; }\n"
"#composerCard { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 16px; }\n"
"#messageEdit { border: none; background-color: transparent; color: #1f2329; font-size: 13px; }\n"
"#statusLabel { color: #6b7280; font-size: 11px; }\n"
"#hintLabel { color: #9aa1ad; font-size: 11px; }\n"
"#modelIntroLabel { color: #6b7280; font-size: 11px; }\n"
"QComboBox#modelCombo { border: none; background-color: transparent; color: #374151; padding: 2px 4px; }\n"
"QComboBox#modelCombo:hover { background-color: #f1f2f4; border-radius: 6px; }\n"
"QComboBox#modelCombo::drop-down { border: none; width: 16px; }\n"
"QToolButton#attachButton { border: none; border-radius: 6px; color: #4b5563; font-size: 18px; }\n"
"QToolButton#attachButton:hover { background-color: #f1f2f4; }\n"
"QPushButton#sendButton { background-color: #2f6fed; color: #ffffff; border: none; border-radius: 17px; font-size: 16px; }\n"
"QPushButton#sendButton:hover { background-color: #2563d8; }\n"
"QPushBut"
                        "ton#sendButton:disabled { background-color: #c9d2e3; }\n"
"QToolButton#demoButton, QToolButton#newSessionButton { background-color: #ffffff; border: 1px solid #e3e5ea; border-radius: 10px; color: #4b5563; font-size: 11px; padding: 6px 2px; }\n"
"QToolButton#demoButton:hover, QToolButton#newSessionButton:hover { background-color: #ffffff; border-color: #c9ced9; color: #1f2329; }\n"
"QToolButton#demoButton:disabled, QToolButton#newSessionButton:disabled { color: #b8bdc7; border-color: #eef0f3; }")
        self.rootLayout = QVBoxLayout(LlmChat)
        self.rootLayout.setSpacing(0)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout = QHBoxLayout()
        self.contentLayout.setSpacing(0)
        self.contentLayout.setObjectName(u"contentLayout")
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout = QVBoxLayout()
        self.mainLayout.setSpacing(0)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.conversationArea = QScrollArea(LlmChat)
        self.conversationArea.setObjectName(u"conversationArea")
        self.conversationArea.setFrameShape(QFrame.Shape.NoFrame)
        self.conversationArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conversationArea.setWidgetResizable(True)
        self.conversationAreaContents = QWidget()
        self.conversationAreaContents.setObjectName(u"conversationAreaContents")
        self.conversationAreaContents.setGeometry(QRect(0, 0, 912, 552))
        self.conversationArea.setWidget(self.conversationAreaContents)

        self.mainLayout.addWidget(self.conversationArea)

        self.composerLayout = QVBoxLayout()
        self.composerLayout.setSpacing(6)
        self.composerLayout.setObjectName(u"composerLayout")
        self.composerLayout.setContentsMargins(18, 6, 18, 10)
        self.composerCard = QFrame(LlmChat)
        self.composerCard.setObjectName(u"composerCard")
        self.composerCard.setFrameShape(QFrame.Shape.NoFrame)
        self.cardLayout = QVBoxLayout(self.composerCard)
        self.cardLayout.setSpacing(4)
        self.cardLayout.setObjectName(u"cardLayout")
        self.cardLayout.setContentsMargins(14, 12, 14, 10)
        self.messageEdit = QPlainTextEdit(self.composerCard)
        self.messageEdit.setObjectName(u"messageEdit")
        self.messageEdit.setMinimumSize(QSize(0, 56))
        self.messageEdit.setMaximumSize(QSize(16777215, 118))

        self.cardLayout.addWidget(self.messageEdit)

        self.toolbarLayout = QHBoxLayout()
        self.toolbarLayout.setSpacing(6)
        self.toolbarLayout.setObjectName(u"toolbarLayout")
        self.attachButton = QToolButton(self.composerCard)
        self.attachButton.setObjectName(u"attachButton")
        self.attachButton.setMinimumSize(QSize(28, 28))
        self.attachButton.setMaximumSize(QSize(28, 28))

        self.toolbarLayout.addWidget(self.attachButton)

        self.modelCombo = QComboBox(self.composerCard)
        self.modelCombo.setObjectName(u"modelCombo")
        self.modelCombo.setMinimumSize(QSize(150, 26))

        self.toolbarLayout.addWidget(self.modelCombo)

        self.modelIntroLabel = QLabel(self.composerCard)
        self.modelIntroLabel.setObjectName(u"modelIntroLabel")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.modelIntroLabel.sizePolicy().hasHeightForWidth())
        self.modelIntroLabel.setSizePolicy(sizePolicy)

        self.toolbarLayout.addWidget(self.modelIntroLabel)

        self.toolbarSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.toolbarLayout.addItem(self.toolbarSpacer)

        self.sendButton = QPushButton(self.composerCard)
        self.sendButton.setObjectName(u"sendButton")
        self.sendButton.setMinimumSize(QSize(34, 34))
        self.sendButton.setMaximumSize(QSize(34, 34))

        self.toolbarLayout.addWidget(self.sendButton)


        self.cardLayout.addLayout(self.toolbarLayout)


        self.composerLayout.addWidget(self.composerCard)

        self.footerRow = QHBoxLayout()
        self.footerRow.setSpacing(8)
        self.footerRow.setObjectName(u"footerRow")
        self.statusLabel = QLabel(LlmChat)
        self.statusLabel.setObjectName(u"statusLabel")

        self.footerRow.addWidget(self.statusLabel)

        self.footerSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.footerRow.addItem(self.footerSpacer)

        self.hintLabel = QLabel(LlmChat)
        self.hintLabel.setObjectName(u"hintLabel")

        self.footerRow.addWidget(self.hintLabel)


        self.composerLayout.addLayout(self.footerRow)


        self.mainLayout.addLayout(self.composerLayout)


        self.contentLayout.addLayout(self.mainLayout)

        self.railLayout = QVBoxLayout()
        self.railLayout.setSpacing(8)
        self.railLayout.setObjectName(u"railLayout")
        self.railLayout.setContentsMargins(4, 12, 12, 12)
        self.railTopSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.railLayout.addItem(self.railTopSpacer)

        self.demoButton = QToolButton(LlmChat)
        self.demoButton.setObjectName(u"demoButton")
        self.demoButton.setMinimumSize(QSize(68, 68))
        self.demoButton.setMaximumSize(QSize(68, 68))
        self.demoButton.setIconSize(QSize(20, 20))
        self.demoButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        self.railLayout.addWidget(self.demoButton)

        self.newSessionButton = QToolButton(LlmChat)
        self.newSessionButton.setObjectName(u"newSessionButton")
        self.newSessionButton.setMinimumSize(QSize(68, 68))
        self.newSessionButton.setMaximumSize(QSize(68, 68))
        self.newSessionButton.setIconSize(QSize(20, 20))
        self.newSessionButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        self.railLayout.addWidget(self.newSessionButton)

        self.railSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.railLayout.addItem(self.railSpacer)


        self.contentLayout.addLayout(self.railLayout)

        self.contentLayout.setStretch(0, 1)

        self.rootLayout.addLayout(self.contentLayout)


        self.retranslateUi(LlmChat)

        QMetaObject.connectSlotsByName(LlmChat)
    # setupUi

    def retranslateUi(self, LlmChat):
        LlmChat.setWindowTitle(QCoreApplication.translate("LlmChat", u"\u5bf9\u8bdd\u9009\u578b", None))
        self.messageEdit.setPlaceholderText(QCoreApplication.translate("LlmChat", u"\u8bf7\u63cf\u8ff0\u4f60\u7684\u9700\u6c42\uff0c\u53ef\u76f4\u63a5\u62d6\u5165\u9644\u4ef6\uff0c\u6216\u70b9\u51fb\u4e0b\u65b9+\u6dfb\u52a0", None))
#if QT_CONFIG(tooltip)
        self.attachButton.setToolTip(QCoreApplication.translate("LlmChat", u"\u9009\u62e9\u6587\u4ef6\uff08txt / md / CSV / Word / Excel / HTML\uff09", None))
#endif // QT_CONFIG(tooltip)
        self.attachButton.setText(QCoreApplication.translate("LlmChat", u"+", None))
#if QT_CONFIG(tooltip)
        self.modelCombo.setToolTip(QCoreApplication.translate("LlmChat", u"\u6a21\u578b\u7531 llm/providers.json \u51b3\u5b9a", None))
#endif // QT_CONFIG(tooltip)
        self.modelIntroLabel.setText("")
#if QT_CONFIG(tooltip)
        self.sendButton.setToolTip(QCoreApplication.translate("LlmChat", u"\u53d1\u9001\uff08Enter\uff09", None))
#endif // QT_CONFIG(tooltip)
        self.sendButton.setText("")
        self.statusLabel.setText(QCoreApplication.translate("LlmChat", u"\u5c31\u7eea", None))
        self.hintLabel.setText(QCoreApplication.translate("LlmChat", u"\u5982\u9700\u63a5\u5165\u5176\u4ed6\u4ed8\u8d39\u6a21\u578b\uff0c\u8bf7\u901a\u8fc7\u53cd\u9988\u8054\u7cfb\u5f00\u53d1\u8005\u3002", None))
#if QT_CONFIG(tooltip)
        self.demoButton.setToolTip(QCoreApplication.translate("LlmChat", u"\u7528\u56fa\u5b9a\u793a\u4f8b\u8d70\u4e00\u904d\u5b8c\u6574\u6d41\u7a0b\uff08\u4e0d\u8c03\u7528\u6a21\u578b\uff09", None))
#endif // QT_CONFIG(tooltip)
        self.demoButton.setText(QCoreApplication.translate("LlmChat", u"\u4f7f\u7528\u5c55\u793a", None))
#if QT_CONFIG(tooltip)
        self.newSessionButton.setToolTip(QCoreApplication.translate("LlmChat", u"\u6e05\u7a7a\u4e0a\u4e0b\u6587\uff0c\u5f00\u59cb\u65b0\u4f1a\u8bdd", None))
#endif // QT_CONFIG(tooltip)
        self.newSessionButton.setText(QCoreApplication.translate("LlmChat", u"\u65b0\u4f1a\u8bdd", None))
    # retranslateUi

