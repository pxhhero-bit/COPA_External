# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'quoteDesk.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem, QTabWidget,
    QVBoxLayout, QWidget)

class Ui_quoteDesk(object):
    def setupUi(self, quoteDesk):
        if not quoteDesk.objectName():
            quoteDesk.setObjectName(u"quoteDesk")
        quoteDesk.resize(650, 490)
        quoteDesk.setMinimumSize(QSize(0, 490))
        self.rootLayout = QHBoxLayout(quoteDesk)
        self.rootLayout.setSpacing(0)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(0, 0, 0, 9)
        self.mainColumn = QWidget(quoteDesk)
        self.mainColumn.setObjectName(u"mainColumn")
        self.mainColumn.setMaximumSize(QSize(650, 16777215))
        self.mainLayout = QVBoxLayout(self.mainColumn)
        self.mainLayout.setSpacing(9)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.inputTabs = QTabWidget(self.mainColumn)
        self.inputTabs.setObjectName(u"inputTabs")
        self.tabText = QWidget()
        self.tabText.setObjectName(u"tabText")
        self.tabTextLayout = QVBoxLayout(self.tabText)
        self.tabTextLayout.setObjectName(u"tabTextLayout")
        self.tabTextLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QScrollArea(self.tabText)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setMaximumSize(QSize(650, 16777215))
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 646, 388))
        self.cardcontainerLayout = QVBoxLayout(self.scrollAreaWidgetContents_2)
        self.cardcontainerLayout.setObjectName(u"cardcontainerLayout")
        self.cardcontainerLayout.setContentsMargins(22, 9, 9, 9)
        self.cardContainer = QWidget(self.scrollAreaWidgetContents_2)
        self.cardContainer.setObjectName(u"cardContainer")

        self.cardcontainerLayout.addWidget(self.cardContainer)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer_2 = QSpacerItem(30, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_2)

        self.pushButton_add = QPushButton(self.scrollAreaWidgetContents_2)
        self.pushButton_add.setObjectName(u"pushButton_add")
        font = QFont()
        font.setPointSize(11)
        self.pushButton_add.setFont(font)
        self.pushButton_add.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.horizontalLayout.addWidget(self.pushButton_add)

        self.horizontalSpacer = QSpacerItem(150, 28, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.pushButton_del = QPushButton(self.scrollAreaWidgetContents_2)
        self.pushButton_del.setObjectName(u"pushButton_del")
        palette = QPalette()
        brush = QBrush(QColor(255, 0, 0, 255))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        palette.setBrush(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText, brush)
        palette.setBrush(QPalette.ColorGroup.Active, QPalette.ColorRole.Text, brush)
        palette.setBrush(QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText, brush)
        brush1 = QBrush(QColor(255, 0, 0, 128))
        brush1.setStyle(Qt.BrushStyle.SolidPattern)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText, brush1)
#endif
        palette.setBrush(QPalette.ColorGroup.Inactive, QPalette.ColorRole.WindowText, brush)
        palette.setBrush(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Text, brush)
        palette.setBrush(QPalette.ColorGroup.Inactive, QPalette.ColorRole.ButtonText, brush)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.ColorGroup.Inactive, QPalette.ColorRole.PlaceholderText, brush1)
#endif
        palette.setBrush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, brush)
        palette.setBrush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, brush)
        palette.setBrush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, brush)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.PlaceholderText, brush1)
#endif
        self.pushButton_del.setPalette(palette)
        self.pushButton_del.setFont(font)
        self.pushButton_del.setStyleSheet(u"color: rgb(255, 0, 0)")

        self.horizontalLayout.addWidget(self.pushButton_del)

        self.horizontalSpacer_3 = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_3)


        self.cardcontainerLayout.addLayout(self.horizontalLayout)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.cardcontainerLayout.addItem(self.verticalSpacer)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents_2)

        self.tabTextLayout.addWidget(self.scrollArea)

        self.inputTabs.addTab(self.tabText, "")
        self.tabGui = QWidget()
        self.tabGui.setObjectName(u"tabGui")
        self.tabGuiLayout = QVBoxLayout(self.tabGui)
        self.tabGuiLayout.setObjectName(u"tabGuiLayout")
        self.tabGuiLayout.setContentsMargins(0, 0, 0, 0)
        self.guiScrollArea = QScrollArea(self.tabGui)
        self.guiScrollArea.setObjectName(u"guiScrollArea")
        self.guiScrollArea.setMaximumSize(QSize(650, 16777215))
        self.guiScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.guiScrollArea.setWidgetResizable(True)
        self.guiScrollContents = QWidget()
        self.guiScrollContents.setObjectName(u"guiScrollContents")
        self.guiScrollContents.setGeometry(QRect(0, 0, 646, 388))
        self.guiContainerLayout = QVBoxLayout(self.guiScrollContents)
        self.guiContainerLayout.setObjectName(u"guiContainerLayout")
        self.guiContainerLayout.setContentsMargins(22, 9, 9, 9)
        self.guiCardContainer = QWidget(self.guiScrollContents)
        self.guiCardContainer.setObjectName(u"guiCardContainer")

        self.guiContainerLayout.addWidget(self.guiCardContainer)

        self.guiVerticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.guiContainerLayout.addItem(self.guiVerticalSpacer)

        self.guiScrollArea.setWidget(self.guiScrollContents)

        self.tabGuiLayout.addWidget(self.guiScrollArea)

        self.guiButtonRow = QHBoxLayout()
        self.guiButtonRow.setObjectName(u"guiButtonRow")
        self.guiSpacer_2 = QSpacerItem(30, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.guiButtonRow.addItem(self.guiSpacer_2)

        self.pushButton_gui_add = QPushButton(self.tabGui)
        self.pushButton_gui_add.setObjectName(u"pushButton_gui_add")
        self.pushButton_gui_add.setFont(font)
        self.pushButton_gui_add.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.guiButtonRow.addWidget(self.pushButton_gui_add)

        self.guiSpacer = QSpacerItem(150, 28, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.guiButtonRow.addItem(self.guiSpacer)

        self.pushButton_gui_del = QPushButton(self.tabGui)
        self.pushButton_gui_del.setObjectName(u"pushButton_gui_del")
        self.pushButton_gui_del.setFont(font)
        self.pushButton_gui_del.setStyleSheet(u"color: rgb(255, 0, 0)")

        self.guiButtonRow.addWidget(self.pushButton_gui_del)

        self.guiSpacer_3 = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.guiButtonRow.addItem(self.guiSpacer_3)


        self.tabGuiLayout.addLayout(self.guiButtonRow)

        self.inputTabs.addTab(self.tabGui, "")

        self.mainLayout.addWidget(self.inputTabs)

        self.startButtonRow = QHBoxLayout()
        self.startButtonRow.setObjectName(u"startButtonRow")
        self.startButtonRow.setContentsMargins(-1, -1, 39, -1)
        self.startButtonSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.startButtonRow.addItem(self.startButtonSpacer)

        self.serviceCheckBox = QCheckBox(self.mainColumn)
        self.serviceCheckBox.setObjectName(u"serviceCheckBox")
        font1 = QFont()
        font1.setPointSize(12)
        self.serviceCheckBox.setFont(font1)

        self.startButtonRow.addWidget(self.serviceCheckBox)

        self.horizontalSpacer_4 = QSpacerItem(100, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.startButtonRow.addItem(self.horizontalSpacer_4)

        self.pushButton_start = QPushButton(self.mainColumn)
        self.pushButton_start.setObjectName(u"pushButton_start")
        font2 = QFont()
        font2.setFamilies([u"\u5fae\u8f6f\u96c5\u9ed1"])
        font2.setPointSize(16)
        self.pushButton_start.setFont(font2)

        self.startButtonRow.addWidget(self.pushButton_start)


        self.mainLayout.addLayout(self.startButtonRow)


        self.rootLayout.addWidget(self.mainColumn)


        self.retranslateUi(quoteDesk)

        self.inputTabs.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(quoteDesk)
    # setupUi

    def retranslateUi(self, quoteDesk):
        quoteDesk.setWindowTitle(QCoreApplication.translate("quoteDesk", u"\u9700\u6c42\u5f55\u5165 - ", None))
        self.pushButton_add.setText(QCoreApplication.translate("quoteDesk", u"  \u65b0\u5efa\u6761\u76ee\uff08+\uff09", None))
#if QT_CONFIG(shortcut)
        self.pushButton_add.setShortcut(QCoreApplication.translate("quoteDesk", u"+", None))
#endif // QT_CONFIG(shortcut)
        self.pushButton_del.setText(QCoreApplication.translate("quoteDesk", u"\u5220\u9664\u6761\u76ee", None))
        self.inputTabs.setTabText(self.inputTabs.indexOf(self.tabText), QCoreApplication.translate("quoteDesk", u"\u8f93\u5165\u6846\u8f93\u5165", None))
        self.pushButton_gui_add.setText(QCoreApplication.translate("quoteDesk", u"  \u65b0\u5efa\u6761\u76ee\uff08+\uff09", None))
        self.pushButton_gui_del.setText(QCoreApplication.translate("quoteDesk", u"\u5220\u9664\u6761\u76ee", None))
        self.inputTabs.setTabText(self.inputTabs.indexOf(self.tabGui), QCoreApplication.translate("quoteDesk", u"\u4e0b\u62c9\u83dc\u5355\u8f93\u5165", None))
        self.serviceCheckBox.setText(QCoreApplication.translate("quoteDesk", u"\u662f\u5426\u9700\u8981\u73b0\u573a\u670d\u52a1", None))
        self.pushButton_start.setText(QCoreApplication.translate("quoteDesk", u"\u5f00\u59cb\u9009\u578b", None))
    # retranslateUi

