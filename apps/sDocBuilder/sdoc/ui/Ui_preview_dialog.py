# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'preview_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

import os

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)

class Ui_PreviewDialog(object):
    def setupUi(self, PreviewDialog):
        if not PreviewDialog.objectName():
            PreviewDialog.setObjectName(u"PreviewDialog")
        PreviewDialog.resize(760, 640)
        icon = QIcon()
        # 窗口图标按本文件位置定位包根的 COPAv2.ico（sdoc/ui 上四级），
        # 不依赖工作目录；Designer 相对路径在任意启动目录下都会失效
        _ICON_PATH = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "..", "COPAv2.ico"))
        icon.addFile(_ICON_PATH, QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        PreviewDialog.setWindowIcon(icon)
        self.verticalLayout = QVBoxLayout(PreviewDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.textBrowser = QTextBrowser(PreviewDialog)
        self.textBrowser.setObjectName(u"textBrowser")

        self.verticalLayout.addWidget(self.textBrowser)

        self.buttonBox = QDialogButtonBox(PreviewDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.verticalLayout.addWidget(self.buttonBox)


        self.retranslateUi(PreviewDialog)

        QMetaObject.connectSlotsByName(PreviewDialog)
    # setupUi

    def retranslateUi(self, PreviewDialog):
        PreviewDialog.setWindowTitle(QCoreApplication.translate("PreviewDialog", u"\u751f\u6210\u9884\u89c8", None))
    # retranslateUi

