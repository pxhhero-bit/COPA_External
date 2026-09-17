# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'quotecard.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QLabel, QPlainTextEdit, QSizePolicy, QSpinBox,
    QWidget)

class Ui_Quotecard(object):
    def setupUi(self, Quotecard):
        if not Quotecard.objectName():
            Quotecard.setObjectName(u"Quotecard")
        Quotecard.resize(587, 190)
        Quotecard.setMinimumSize(QSize(575, 190))
        Quotecard.setAutoFillBackground(False)
        Quotecard.setStyleSheet(u"#Quotecard{\n"
"	border:1px solid black;\n"
"}")
        self.label = QLabel(Quotecard)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(110, 10, 61, 21))
        self.comboBox = QComboBox(Quotecard)
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.setObjectName(u"comboBox")
        self.comboBox.setGeometry(QRect(170, 10, 121, 21))
        self.comboBox.setToolTipDuration(5000)
        self.comboBox.setAutoFillBackground(True)
        self.comboBox.setEditable(True)
        self.plainTextEdit = QPlainTextEdit(Quotecard)
        self.plainTextEdit.setObjectName(u"plainTextEdit")
        self.plainTextEdit.setGeometry(QRect(110, 70, 461, 111))
        self.label_2 = QLabel(Quotecard)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(110, 40, 91, 31))
        self.label_ID = QLabel(Quotecard)
        self.label_ID.setObjectName(u"label_ID")
        self.label_ID.setGeometry(QRect(20, 50, 71, 61))
        font = QFont()
        font.setPointSize(28)
        self.label_ID.setFont(font)
        self.label_ID.setStyleSheet(u"color:rgb(120, 120, 120)")
        self.label_ID.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layoutWidget = QWidget(Quotecard)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(320, 10, 251, 56))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.checkBox = QCheckBox(self.layoutWidget)
        self.checkBox.setObjectName(u"checkBox")

        self.gridLayout.addWidget(self.checkBox, 0, 0, 1, 1)

        self.checkBox_2 = QCheckBox(self.layoutWidget)
        self.checkBox_2.setObjectName(u"checkBox_2")
        self.checkBox_2.setToolTipDuration(5000)

        self.gridLayout.addWidget(self.checkBox_2, 0, 1, 1, 1)

        self.checkBox_3 = QCheckBox(self.layoutWidget)
        self.checkBox_3.setObjectName(u"checkBox_3")
        self.checkBox_3.setToolTipDuration(5000)

        self.gridLayout.addWidget(self.checkBox_3, 1, 0, 1, 1)

        self.checkBox_4 = QCheckBox(self.layoutWidget)
        self.checkBox_4.setObjectName(u"checkBox_4")
        self.checkBox_4.setToolTipDuration(5000)

        self.gridLayout.addWidget(self.checkBox_4, 1, 1, 1, 1)

        self.spinBox = QSpinBox(Quotecard)
        self.spinBox.setObjectName(u"spinBox")
        self.spinBox.setGeometry(QRect(11, 121, 71, 21))
        font1 = QFont()
        font1.setPointSize(12)
        self.spinBox.setFont(font1)
        self.label_unit = QLabel(Quotecard)
        self.label_unit.setObjectName(u"label_unit")
        self.label_unit.setGeometry(QRect(80, 120, 31, 21))
        self.label_unit.setFont(font1)
        self.label_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        QWidget.setTabOrder(self.comboBox, self.spinBox)
        QWidget.setTabOrder(self.spinBox, self.plainTextEdit)
        QWidget.setTabOrder(self.plainTextEdit, self.checkBox)
        QWidget.setTabOrder(self.checkBox, self.checkBox_3)
        QWidget.setTabOrder(self.checkBox_3, self.checkBox_2)
        QWidget.setTabOrder(self.checkBox_2, self.checkBox_4)

        self.retranslateUi(Quotecard)

        QMetaObject.connectSlotsByName(Quotecard)
    # setupUi

    def retranslateUi(self, Quotecard):
        Quotecard.setWindowTitle(QCoreApplication.translate("Quotecard", u"\u65b0\u5efa\u6761\u76ee", None))
        self.label.setText(QCoreApplication.translate("Quotecard", u"\u6761\u76ee\u7c7b\u578b\uff1a", None))
        self.comboBox.setItemText(0, QCoreApplication.translate("Quotecard", u"\u79f0\u91cd\u6a21\u5757", None))
        self.comboBox.setItemText(1, QCoreApplication.translate("Quotecard", u"\u5e73\u53f0\u79e4", None))
        self.comboBox.setItemText(2, QCoreApplication.translate("Quotecard", u"\u53f0\u79e4", None))
        self.comboBox.setItemText(3, QCoreApplication.translate("Quotecard", u"\u6c7d\u8f66\u8861", None))
        self.comboBox.setItemText(4, QCoreApplication.translate("Quotecard", u"\u6570\u5b57\u5f0f\u6c7d\u8f66\u8861", None))

#if QT_CONFIG(tooltip)
        self.comboBox.setToolTip(QCoreApplication.translate("Quotecard", u"<html><head/><body><p>\u9f20\u6807\u60ac\u505c\u5e76\u6eda\u52a8\u6eda\u8f6e\u53ef\u5feb\u901f\u5207\u6362\u3002</p><p>\u6253\u5b57\u53ef\u8865\u5168\u3002</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.comboBox.setPlaceholderText(QCoreApplication.translate("Quotecard", u"\u8bf7\u9009\u62e9\u6761\u76ee\u7c7b\u578b", None))
        self.plainTextEdit.setPlaceholderText(QCoreApplication.translate("Quotecard", u"\u8bf7\u8f93\u5165\u5176\u4ed6\u9879\u76ee\u9700\u6c42\uff0c\u7528\u4e2d\u6587\u53e5\u53f7\u5206\u9694\u4e0d\u540c\u7ec4\u4ef6\u7684\u8981\u6c42\u3002\u5982\uff1a1\u53f03\u5428\u5e73\u53f0\u79e4\uff0cFT\u3002\u4eea\u88683306\u3002", None))
        self.label_2.setText(QCoreApplication.translate("Quotecard", u"\u5176\u4ed6\u9879\u76ee\u9700\u6c42\uff1a", None))
        self.label_ID.setText(QCoreApplication.translate("Quotecard", u"ID", None))
        self.checkBox.setText(QCoreApplication.translate("Quotecard", u"\u662f\u5426\u9700\u8981\u68c0\u5b9a", None))
#if QT_CONFIG(tooltip)
        self.checkBox_2.setToolTip(QCoreApplication.translate("Quotecard", u"\u6ce8\u610f\uff1a\u6c7d\u8f66\u8861\u7684\u9ad8\u7cbe\u5ea6\u4e3aC4\u7b49\u7ea7\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_2.setText(QCoreApplication.translate("Quotecard", u"\u662f\u5426\u9ad8\u7cbe\u5ea6", None))
#if QT_CONFIG(tooltip)
        self.checkBox_3.setToolTip(QCoreApplication.translate("Quotecard", u"\u5982\u52fe\u9009\uff0c\u8bf7\u5728\u4e0b\u65b9\u8f93\u5165\u5177\u4f53\u7684\u9632\u7206\u7b49\u7ea7\u3002\u9ed8\u8ba4\u4e3aIIBT4\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_3.setText(QCoreApplication.translate("Quotecard", u"\u662f\u5426\u9632\u7206", None))
#if QT_CONFIG(tooltip)
        self.checkBox_4.setToolTip(QCoreApplication.translate("Quotecard", u"\u672a\u5b8c\u5584,\u9700\u4eba\u5de5\u590d\u67e5", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_4.setText(QCoreApplication.translate("Quotecard", u"\u6570\u5b57\u5316\u65b9\u6848", None))
        self.label_unit.setText(QCoreApplication.translate("Quotecard", u"\u5957", None))
    # retranslateUi

