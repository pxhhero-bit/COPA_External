# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'secDisplay.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QLabel, QPushButton,
    QSizePolicy, QWidget)

class Ui_secDisplay(object):
    def setupUi(self, secDisplay):
        if not secDisplay.objectName():
            secDisplay.setObjectName(u"secDisplay")
        secDisplay.resize(449, 139)
        self.brandComBox = QComboBox(secDisplay)
        self.brandComBox.addItem("")
        self.brandComBox.addItem("")
        self.brandComBox.setObjectName(u"brandComBox")
        self.brandComBox.setGeometry(QRect(80, 10, 121, 21))
        self.label = QLabel(secDisplay)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(10, 10, 61, 21))
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.sizeComBox = QComboBox(secDisplay)
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.addItem("")
        self.sizeComBox.setObjectName(u"sizeComBox")
        self.sizeComBox.setGeometry(QRect(80, 40, 121, 21))
        self.label_2 = QLabel(secDisplay)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(10, 40, 61, 21))
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.label_3 = QLabel(secDisplay)
        self.label_3.setObjectName(u"label_3")
        self.label_3.setGeometry(QRect(10, 70, 61, 21))
        self.label_3.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.colorComBox = QComboBox(secDisplay)
        self.colorComBox.addItem("")
        self.colorComBox.addItem("")
        self.colorComBox.addItem("")
        self.colorComBox.addItem("")
        self.colorComBox.setObjectName(u"colorComBox")
        self.colorComBox.setGeometry(QRect(80, 70, 121, 21))
        self.label_4 = QLabel(secDisplay)
        self.label_4.setObjectName(u"label_4")
        self.label_4.setGeometry(QRect(10, 100, 61, 21))
        self.label_4.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.comComBox = QComboBox(secDisplay)
        self.comComBox.addItem("")
        self.comComBox.addItem("")
        self.comComBox.addItem("")
        self.comComBox.addItem("")
        self.comComBox.setObjectName(u"comComBox")
        self.comComBox.setGeometry(QRect(80, 100, 121, 21))
        self.powerComBox = QComboBox(secDisplay)
        self.powerComBox.addItem("")
        self.powerComBox.addItem("")
        self.powerComBox.setObjectName(u"powerComBox")
        self.powerComBox.setGeometry(QRect(290, 10, 131, 21))
        self.label_5 = QLabel(secDisplay)
        self.label_5.setObjectName(u"label_5")
        self.label_5.setGeometry(QRect(220, 10, 61, 21))
        self.label_5.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.label_6 = QLabel(secDisplay)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setGeometry(QRect(220, 40, 61, 21))
        self.label_6.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.comPotComBox = QComboBox(secDisplay)
        self.comPotComBox.addItem("")
        self.comPotComBox.addItem("")
        self.comPotComBox.addItem("")
        self.comPotComBox.addItem("")
        self.comPotComBox.setObjectName(u"comPotComBox")
        self.comPotComBox.setGeometry(QRect(290, 40, 131, 21))
        self.comChenComBox = QComboBox(secDisplay)
        self.comChenComBox.addItem("")
        self.comChenComBox.addItem("")
        self.comChenComBox.setObjectName(u"comChenComBox")
        self.comChenComBox.setGeometry(QRect(290, 70, 131, 21))
        self.label_7 = QLabel(secDisplay)
        self.label_7.setObjectName(u"label_7")
        self.label_7.setGeometry(QRect(220, 70, 61, 21))
        self.label_7.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)
        self.pushButton = QPushButton(secDisplay)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(360, 100, 61, 31))
        font = QFont()
        font.setPointSize(12)
        self.pushButton.setFont(font)

        self.retranslateUi(secDisplay)

        QMetaObject.connectSlotsByName(secDisplay)
    # setupUi

    def retranslateUi(self, secDisplay):
        secDisplay.setWindowTitle(QCoreApplication.translate("secDisplay", u"\u5927\u5c4f\u5e55\u9009\u578b", None))
        self.brandComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"FT (\u5bcc\u6797\u6cf0\u514b)", None))
        self.brandComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"AW (\u827e\u529b\u5a01)", None))

        self.label.setText(QCoreApplication.translate("secDisplay", u"\u54c1\u724c", None))
        self.sizeComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"3", None))
        self.sizeComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"4", None))
        self.sizeComBox.setItemText(2, QCoreApplication.translate("secDisplay", u"5", None))
        self.sizeComBox.setItemText(3, QCoreApplication.translate("secDisplay", u"7", None))
        self.sizeComBox.setItemText(4, QCoreApplication.translate("secDisplay", u"10", None))
        self.sizeComBox.setItemText(5, QCoreApplication.translate("secDisplay", u"12", None))
        self.sizeComBox.setItemText(6, QCoreApplication.translate("secDisplay", u"15", None))

        self.label_2.setText(QCoreApplication.translate("secDisplay", u"\u5c3a\u5bf8 (\u82f1\u5bf8)", None))
        self.label_3.setText(QCoreApplication.translate("secDisplay", u"\u989c\u8272", None))
        self.colorComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"R : \u7ea2\u8272", None))
        self.colorComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"G : \u7eff\u8272", None))
        self.colorComBox.setItemText(2, QCoreApplication.translate("secDisplay", u"H : \u9ec4\u8272", None))
        self.colorComBox.setItemText(3, QCoreApplication.translate("secDisplay", u"C : \u4e09\u8272", None))

        self.label_4.setText(QCoreApplication.translate("secDisplay", u"\u901a\u8baf\u65b9\u5f0f", None))
        self.comComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"1 : RS232", None))
        self.comComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"2: RS485", None))
        self.comComBox.setItemText(2, QCoreApplication.translate("secDisplay", u"3 : \u65e0\u7ebf", None))
        self.comComBox.setItemText(3, QCoreApplication.translate("secDisplay", u"4 : RS232/485\u4e24\u7528", None))

        self.powerComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"D : 24V\u76f4\u6d41\u7535", None))
        self.powerComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"A : 220V\u4ea4\u6d41\u7535", None))

        self.label_5.setText(QCoreApplication.translate("secDisplay", u"\u901a\u8baf\u65b9\u5f0f", None))
        self.label_6.setText(QCoreApplication.translate("secDisplay", u"\u901a\u8baf\u534f\u8bae", None))
        self.comPotComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"M : \u6258\u5229\u591a\u534f\u8bae", None))
        self.comPotComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"F : FAB\u534f\u8bae", None))
        self.comPotComBox.setItemText(2, QCoreApplication.translate("secDisplay", u"Y : \u8000\u534e\u534f\u8bae", None))
        self.comPotComBox.setItemText(3, QCoreApplication.translate("secDisplay", u"Z : \u5176\u4ed6", None))

        self.comChenComBox.setItemText(0, QCoreApplication.translate("secDisplay", u"1 : \u5355\u901a\u9053", None))
        self.comChenComBox.setItemText(1, QCoreApplication.translate("secDisplay", u"4 : \u591a\u901a\u9053", None))

        self.label_7.setText(QCoreApplication.translate("secDisplay", u"\u901a\u9053", None))
        self.pushButton.setText(QCoreApplication.translate("secDisplay", u"\u786e\u5b9a", None))
    # retranslateUi

