# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'guicard.ui'
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
    QHBoxLayout, QLabel, QSizePolicy, QSpinBox,
    QWidget)

from COPA.apps.MultiCombo import CheckableComboBox

class Ui_Guicard(object):
    def setupUi(self, Guicard):
        if not Guicard.objectName():
            Guicard.setObjectName(u"Guicard")
        Guicard.resize(587, 400)
        Guicard.setMinimumSize(QSize(575, 400))
        Guicard.setStyleSheet(u"#Guicard{\n"
"	border:1px solid black;\n"
"}")
        self.label_ID = QLabel(Guicard)
        self.label_ID.setObjectName(u"label_ID")
        self.label_ID.setGeometry(QRect(20, 150, 71, 61))
        font = QFont()
        font.setPointSize(28)
        self.label_ID.setFont(font)
        self.label_ID.setStyleSheet(u"color:rgb(120, 120, 120)")
        self.label_ID.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinBox = QSpinBox(Guicard)
        self.spinBox.setObjectName(u"spinBox")
        self.spinBox.setGeometry(QRect(11, 241, 71, 21))
        font1 = QFont()
        font1.setPointSize(12)
        self.spinBox.setFont(font1)
        self.label_unit = QLabel(Guicard)
        self.label_unit.setObjectName(u"label_unit")
        self.label_unit.setGeometry(QRect(80, 240, 31, 21))
        self.label_unit.setFont(font1)
        self.label_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel(Guicard)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(110, 10, 61, 21))
        self.comboBox = QComboBox(Guicard)
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.setObjectName(u"comboBox")
        self.comboBox.setGeometry(QRect(170, 10, 121, 21))
        self.comboBox.setToolTipDuration(5000)
        self.comboBox.setEditable(True)
        self.checkRowWidget = QWidget(Guicard)
        self.checkRowWidget.setObjectName(u"checkRowWidget")
        self.checkRowWidget.setGeometry(QRect(110, 34, 465, 26))
        self.checkRowLayout = QHBoxLayout(self.checkRowWidget)
        self.checkRowLayout.setSpacing(6)
        self.checkRowLayout.setObjectName(u"checkRowLayout")
        self.checkRowLayout.setContentsMargins(0, 0, 0, 0)
        self.checkBox = QCheckBox(self.checkRowWidget)
        self.checkBox.setObjectName(u"checkBox")

        self.checkRowLayout.addWidget(self.checkBox)

        self.checkBox_2 = QCheckBox(self.checkRowWidget)
        self.checkBox_2.setObjectName(u"checkBox_2")
        self.checkBox_2.setToolTipDuration(5000)

        self.checkRowLayout.addWidget(self.checkBox_2)

        self.checkBox_3 = QCheckBox(self.checkRowWidget)
        self.checkBox_3.setObjectName(u"checkBox_3")
        self.checkBox_3.setToolTipDuration(5000)

        self.checkRowLayout.addWidget(self.checkBox_3)

        self.checkBox_4 = QCheckBox(self.checkRowWidget)
        self.checkBox_4.setObjectName(u"checkBox_4")
        self.checkBox_4.setToolTipDuration(5000)

        self.checkRowLayout.addWidget(self.checkBox_4)

        self.formWidget = QWidget(Guicard)
        self.formWidget.setObjectName(u"formWidget")
        self.formWidget.setGeometry(QRect(110, 60, 465, 328))
        self.formGrid = QGridLayout(self.formWidget)
        self.formGrid.setObjectName(u"formGrid")
        self.formGrid.setHorizontalSpacing(8)
        self.formGrid.setVerticalSpacing(4)
        self.formGrid.setContentsMargins(0, 0, 0, 0)
        self.label_W1 = QLabel(self.formWidget)
        self.label_W1.setObjectName(u"label_W1")
        self.label_W1.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_W1, 0, 0, 1, 1)

        self.combo_W1 = QComboBox(self.formWidget)
        self.combo_W1.setObjectName(u"combo_W1")
        self.combo_W1.setEditable(True)

        self.formGrid.addWidget(self.combo_W1, 0, 1, 1, 1)

        self.label_W2 = QLabel(self.formWidget)
        self.label_W2.setObjectName(u"label_W2")
        self.label_W2.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_W2, 0, 2, 1, 1)

        self.combo_W2 = QComboBox(self.formWidget)
        self.combo_W2.addItem("")
        self.combo_W2.addItem("")
        self.combo_W2.addItem("")
        self.combo_W2.addItem("")
        self.combo_W2.addItem("")
        self.combo_W2.setObjectName(u"combo_W2")
        self.combo_W2.setEditable(True)

        self.formGrid.addWidget(self.combo_W2, 0, 3, 1, 1)

        self.label_support = QLabel(self.formWidget)
        self.label_support.setObjectName(u"label_support")
        self.label_support.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_support, 1, 0, 1, 1)

        self.combo_support = QComboBox(self.formWidget)
        self.combo_support.addItem("")
        self.combo_support.addItem("")
        self.combo_support.addItem("")
        self.combo_support.addItem("")
        self.combo_support.setObjectName(u"combo_support")
        self.combo_support.setEditable(True)

        self.formGrid.addWidget(self.combo_support, 1, 1, 1, 1)

        self.label_material = QLabel(self.formWidget)
        self.label_material.setObjectName(u"label_material")
        self.label_material.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_material, 1, 2, 1, 1)

        self.combo_material = QComboBox(self.formWidget)
        self.combo_material.addItem("")
        self.combo_material.addItem("")
        self.combo_material.addItem("")
        self.combo_material.addItem("")
        self.combo_material.setObjectName(u"combo_material")

        self.formGrid.addWidget(self.combo_material, 1, 3, 1, 1)

        self.label_m_brand = QLabel(self.formWidget)
        self.label_m_brand.setObjectName(u"label_m_brand")
        self.label_m_brand.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_m_brand, 2, 0, 1, 1)

        self.combo_m_brand = QComboBox(self.formWidget)
        self.combo_m_brand.addItem("")
        self.combo_m_brand.addItem("")
        self.combo_m_brand.addItem("")
        self.combo_m_brand.addItem("")
        self.combo_m_brand.setObjectName(u"combo_m_brand")

        self.formGrid.addWidget(self.combo_m_brand, 2, 1, 1, 1)

        self.label_c_brand = QLabel(self.formWidget)
        self.label_c_brand.setObjectName(u"label_c_brand")
        self.label_c_brand.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_c_brand, 2, 2, 1, 1)

        self.combo_c_brand = QComboBox(self.formWidget)
        self.combo_c_brand.addItem("")
        self.combo_c_brand.addItem("")
        self.combo_c_brand.addItem("")
        self.combo_c_brand.addItem("")
        self.combo_c_brand.setObjectName(u"combo_c_brand")

        self.formGrid.addWidget(self.combo_c_brand, 2, 3, 1, 1)

        self.label_c_family = QLabel(self.formWidget)
        self.label_c_family.setObjectName(u"label_c_family")
        self.label_c_family.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_c_family, 3, 0, 1, 1)

        self.combo_c_family = QComboBox(self.formWidget)
        self.combo_c_family.setObjectName(u"combo_c_family")
        self.combo_c_family.setEditable(True)

        self.formGrid.addWidget(self.combo_c_family, 3, 1, 1, 1)

        self.label_size = QLabel(self.formWidget)
        self.label_size.setObjectName(u"label_size")
        self.label_size.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_size, 3, 2, 1, 1)

        self.combo_size = QComboBox(self.formWidget)
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.addItem("")
        self.combo_size.setObjectName(u"combo_size")
        self.combo_size.setEditable(True)

        self.formGrid.addWidget(self.combo_size, 3, 3, 1, 1)

        self.label_e_input = QLabel(self.formWidget)
        self.label_e_input.setObjectName(u"label_e_input")
        self.label_e_input.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_e_input, 4, 0, 1, 1)

        self.combo_e_input = QComboBox(self.formWidget)
        self.combo_e_input.addItem("")
        self.combo_e_input.addItem("")
        self.combo_e_input.addItem("")
        self.combo_e_input.addItem("")
        self.combo_e_input.setObjectName(u"combo_e_input")
        self.combo_e_input.setEditable(True)

        self.formGrid.addWidget(self.combo_e_input, 4, 1, 1, 1)

        self.label_r_input = QLabel(self.formWidget)
        self.label_r_input.setObjectName(u"label_r_input")
        self.label_r_input.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_r_input, 4, 2, 1, 1)

        self.combo_r_input = QComboBox(self.formWidget)
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.addItem("")
        self.combo_r_input.setObjectName(u"combo_r_input")
        self.combo_r_input.setEditable(True)

        self.formGrid.addWidget(self.combo_r_input, 4, 3, 1, 1)

        self.label_vibration = QLabel(self.formWidget)
        self.label_vibration.setObjectName(u"label_vibration")
        self.label_vibration.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_vibration, 5, 0, 1, 1)

        self.combo_vibration = QComboBox(self.formWidget)
        self.combo_vibration.addItem("")
        self.combo_vibration.addItem("")
        self.combo_vibration.addItem("")
        self.combo_vibration.setObjectName(u"combo_vibration")

        self.formGrid.addWidget(self.combo_vibration, 5, 1, 1, 1)

        self.label_RPM = QLabel(self.formWidget)
        self.label_RPM.setObjectName(u"label_RPM")
        self.label_RPM.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_RPM, 5, 2, 1, 1)

        self.combo_RPM = QComboBox(self.formWidget)
        self.combo_RPM.addItem("")
        self.combo_RPM.addItem("")
        self.combo_RPM.addItem("")
        self.combo_RPM.addItem("")
        self.combo_RPM.setObjectName(u"combo_RPM")
        self.combo_RPM.setEditable(True)

        self.formGrid.addWidget(self.combo_RPM, 5, 3, 1, 1)

        self.label_installForm = QLabel(self.formWidget)
        self.label_installForm.setObjectName(u"label_installForm")
        self.label_installForm.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_installForm, 6, 0, 1, 1)

        self.combo_installForm = QComboBox(self.formWidget)
        self.combo_installForm.addItem("")
        self.combo_installForm.addItem("")
        self.combo_installForm.addItem("")
        self.combo_installForm.setObjectName(u"combo_installForm")

        self.formGrid.addWidget(self.combo_installForm, 6, 1, 1, 1)

        self.label_bracket = QLabel(self.formWidget)
        self.label_bracket.setObjectName(u"label_bracket")
        self.label_bracket.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_bracket, 6, 2, 1, 1)

        self.combo_bracket = QComboBox(self.formWidget)
        self.combo_bracket.addItem("")
        self.combo_bracket.addItem("")
        self.combo_bracket.addItem("")
        self.combo_bracket.setObjectName(u"combo_bracket")

        self.formGrid.addWidget(self.combo_bracket, 6, 3, 1, 1)

        self.label_install = QLabel(self.formWidget)
        self.label_install.setObjectName(u"label_install")
        self.label_install.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_install, 7, 0, 1, 1)

        self.combo_install = QComboBox(self.formWidget)
        self.combo_install.addItem("")
        self.combo_install.addItem("")
        self.combo_install.addItem("")
        self.combo_install.addItem("")
        self.combo_install.addItem("")
        self.combo_install.setObjectName(u"combo_install")

        self.formGrid.addWidget(self.combo_install, 7, 1, 1, 1)

        self.label_power = QLabel(self.formWidget)
        self.label_power.setObjectName(u"label_power")
        self.label_power.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_power, 7, 2, 1, 1)

        self.combo_power = QComboBox(self.formWidget)
        self.combo_power.addItem("")
        self.combo_power.addItem("")
        self.combo_power.addItem("")
        self.combo_power.setObjectName(u"combo_power")

        self.formGrid.addWidget(self.combo_power, 7, 3, 1, 1)

        self.label_req_com1 = QLabel(self.formWidget)
        self.label_req_com1.setObjectName(u"label_req_com1")
        self.label_req_com1.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_req_com1, 8, 0, 1, 1)

        self.combo_req_com1 = QComboBox(self.formWidget)
        self.combo_req_com1.addItem("")
        self.combo_req_com1.addItem("")
        self.combo_req_com1.addItem("")
        self.combo_req_com1.addItem("")
        self.combo_req_com1.addItem("")
        self.combo_req_com1.addItem("")
        self.combo_req_com1.setObjectName(u"combo_req_com1")

        self.formGrid.addWidget(self.combo_req_com1, 8, 1, 1, 1)

        self.label_channels = QLabel(self.formWidget)
        self.label_channels.setObjectName(u"label_channels")
        self.label_channels.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_channels, 8, 2, 1, 1)

        self.combo_channels = QComboBox(self.formWidget)
        self.combo_channels.addItem("")
        self.combo_channels.addItem("")
        self.combo_channels.addItem("")
        self.combo_channels.addItem("")
        self.combo_channels.addItem("")
        self.combo_channels.setObjectName(u"combo_channels")

        self.formGrid.addWidget(self.combo_channels, 8, 3, 1, 1)

        self.label_req_com2 = QLabel(self.formWidget)
        self.label_req_com2.setObjectName(u"label_req_com2")
        self.label_req_com2.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_req_com2, 9, 0, 1, 1)

        self.combo_req_com2 = CheckableComboBox(self.formWidget)
        self.combo_req_com2.setObjectName(u"combo_req_com2")

        self.formGrid.addWidget(self.combo_req_com2, 9, 1, 1, 1)

        self.label_battery = QLabel(self.formWidget)
        self.label_battery.setObjectName(u"label_battery")
        self.label_battery.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_battery, 9, 2, 1, 1)

        self.combo_battery = QComboBox(self.formWidget)
        self.combo_battery.addItem("")
        self.combo_battery.addItem("")
        self.combo_battery.setObjectName(u"combo_battery")

        self.formGrid.addWidget(self.combo_battery, 9, 3, 1, 1)

        self.label_required_ex = QLabel(self.formWidget)
        self.label_required_ex.setObjectName(u"label_required_ex")
        self.label_required_ex.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.formGrid.addWidget(self.label_required_ex, 10, 0, 1, 1)

        self.combo_required_ex = QComboBox(self.formWidget)
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.addItem("")
        self.combo_required_ex.setObjectName(u"combo_required_ex")

        self.formGrid.addWidget(self.combo_required_ex, 10, 1, 1, 1)

        self.label_2 = QLabel(Guicard)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(10, 80, 91, 41))
        self.label_2.setFont(font)
        self.label_2.setStyleSheet(u"color: rgb(120, 120, 120)")
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.retranslateUi(Guicard)

        QMetaObject.connectSlotsByName(Guicard)
    # setupUi

    def retranslateUi(self, Guicard):
        Guicard.setWindowTitle(QCoreApplication.translate("Guicard", u"\u65b0\u5efa\u6761\u76ee", None))
        self.label_ID.setText(QCoreApplication.translate("Guicard", u"ID", None))
        self.label_unit.setText(QCoreApplication.translate("Guicard", u"\u5957", None))
        self.label.setText(QCoreApplication.translate("Guicard", u"\u6761\u76ee\u7c7b\u578b\uff1a", None))
        self.comboBox.setItemText(0, QCoreApplication.translate("Guicard", u"\u79f0\u91cd\u6a21\u5757", None))
        self.comboBox.setItemText(1, QCoreApplication.translate("Guicard", u"\u5e73\u53f0\u79e4", None))
        self.comboBox.setItemText(2, QCoreApplication.translate("Guicard", u"\u53f0\u79e4", None))
        self.comboBox.setItemText(3, QCoreApplication.translate("Guicard", u"\u6c7d\u8f66\u8861", None))
        self.comboBox.setItemText(4, QCoreApplication.translate("Guicard", u"\u6570\u5b57\u5f0f\u6c7d\u8f66\u8861", None))

#if QT_CONFIG(tooltip)
        self.comboBox.setToolTip(QCoreApplication.translate("Guicard", u"\u9f20\u6807\u60ac\u505c\u5e76\u6eda\u52a8\u6eda\u8f6e\u53ef\u5feb\u901f\u5207\u6362\u3002\u6253\u5b57\u53ef\u8865\u5168\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.comboBox.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u8bf7\u9009\u62e9\u6761\u76ee\u7c7b\u578b", None))
        self.checkBox.setText(QCoreApplication.translate("Guicard", u"\u662f\u5426\u9700\u8981\u68c0\u5b9a", None))
#if QT_CONFIG(tooltip)
        self.checkBox_2.setToolTip(QCoreApplication.translate("Guicard", u"\u6ce8\u610f\uff1a\u6c7d\u8f66\u8861\u7684\u9ad8\u7cbe\u5ea6\u4e3aC4\u7b49\u7ea7\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_2.setText(QCoreApplication.translate("Guicard", u"\u662f\u5426\u9ad8\u7cbe\u5ea6", None))
#if QT_CONFIG(tooltip)
        self.checkBox_3.setToolTip(QCoreApplication.translate("Guicard", u"\u5982\u52fe\u9009\uff0c\u8bf7\u5728\u4e0b\u65b9\u9009\u62e9\u5177\u4f53\u7684\u9632\u7206\u7b49\u7ea7\u3002\u9ed8\u8ba4\u4e3aIIBT4\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_3.setText(QCoreApplication.translate("Guicard", u"\u662f\u5426\u9632\u7206", None))
#if QT_CONFIG(tooltip)
        self.checkBox_4.setToolTip(QCoreApplication.translate("Guicard", u"\u672a\u5b8c\u5584,\u9700\u4eba\u5de5\u590d\u67e5", None))
#endif // QT_CONFIG(tooltip)
        self.checkBox_4.setText(QCoreApplication.translate("Guicard", u"\u6570\u5b57\u5316\u65b9\u6848", None))
        self.label_W1.setText(QCoreApplication.translate("Guicard", u"\u6700\u5927\u6599\u91cd\uff08kg\uff09", None))
#if QT_CONFIG(tooltip)
        self.combo_W1.setToolTip(QCoreApplication.translate("Guicard", u"\u6700\u5927\u7269\u6599\u91cd\u91cf/\u6599\u91cd\uff1b\u5e73\u53f0\u79e4\u3001\u53f0\u79e4\u53ef\u7559\u7a7a\uff0c\u7531\u989d\u5b9a\u91cf\u7a0b\u517c\u4efb\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_W1.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a3000 \u6216 3\u5428", None))
        self.label_W2.setText(QCoreApplication.translate("Guicard", u"\u76ae\u91cd\uff08kg\uff09", None))
        self.combo_W2.setItemText(0, QCoreApplication.translate("Guicard", u"20", None))
        self.combo_W2.setItemText(1, QCoreApplication.translate("Guicard", u"50", None))
        self.combo_W2.setItemText(2, QCoreApplication.translate("Guicard", u"100", None))
        self.combo_W2.setItemText(3, QCoreApplication.translate("Guicard", u"200", None))
        self.combo_W2.setItemText(4, QCoreApplication.translate("Guicard", u"450", None))

#if QT_CONFIG(tooltip)
        self.combo_W2.setToolTip(QCoreApplication.translate("Guicard", u"\u8bbe\u5907\u672c\u8eab\u91cd\u91cf/\u76ae\u91cd\uff1b\u79f0\u91cd\u6a21\u5757\u5fc5\u586b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_W2.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a450", None))
        self.label_support.setText(QCoreApplication.translate("Guicard", u"\u652f\u70b9\u6570", None))
        self.combo_support.setItemText(0, QCoreApplication.translate("Guicard", u"3", None))
        self.combo_support.setItemText(1, QCoreApplication.translate("Guicard", u"4", None))
        self.combo_support.setItemText(2, QCoreApplication.translate("Guicard", u"6", None))
        self.combo_support.setItemText(3, QCoreApplication.translate("Guicard", u"8", None))

#if QT_CONFIG(tooltip)
        self.combo_support.setToolTip(QCoreApplication.translate("Guicard", u"\u652f\u6491\u70b9/\u652f\u70b9\u6570\uff1b\u79f0\u91cd\u6a21\u5757\u5fc5\u586b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_support.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a4", None))
        self.label_material.setText(QCoreApplication.translate("Guicard", u"\u6a21\u5757\u6750\u8d28", None))
        self.combo_material.setItemText(0, "")
        self.combo_material.setItemText(1, QCoreApplication.translate("Guicard", u"\u78b3\u94a2", None))
        self.combo_material.setItemText(2, QCoreApplication.translate("Guicard", u"\u4e0d\u9508\u94a2", None))
        self.combo_material.setItemText(3, QCoreApplication.translate("Guicard", u"\u6df7\u5408", None))

#if QT_CONFIG(tooltip)
        self.combo_material.setToolTip(QCoreApplication.translate("Guicard", u"\u79e4\u53f0/\u6a21\u5757\u6750\u8d28\uff0c\u5fc5\u586b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_m_brand.setText(QCoreApplication.translate("Guicard", u"\u4f20\u611f\u5668\u54c1\u724c", None))
        self.combo_m_brand.setItemText(0, "")
        self.combo_m_brand.setItemText(1, QCoreApplication.translate("Guicard", u"FT", None))
        self.combo_m_brand.setItemText(2, QCoreApplication.translate("Guicard", u"AW", None))
        self.combo_m_brand.setItemText(3, QCoreApplication.translate("Guicard", u"FAB", None))

#if QT_CONFIG(tooltip)
        self.combo_m_brand.setToolTip(QCoreApplication.translate("Guicard", u"\u4f20\u611f\u5668/\u6a21\u5757\u54c1\u724c\uff1b\u6a21\u5757\u4e0e\u53f0\u79e4\u5fc5\u586b\uff0c\u5e73\u53f0\u79e4\u53ef\u9009\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_c_brand.setText(QCoreApplication.translate("Guicard", u"\u4eea\u8868\u54c1\u724c", None))
        self.combo_c_brand.setItemText(0, "")
        self.combo_c_brand.setItemText(1, QCoreApplication.translate("Guicard", u"FT", None))
        self.combo_c_brand.setItemText(2, QCoreApplication.translate("Guicard", u"AW", None))
        self.combo_c_brand.setItemText(3, QCoreApplication.translate("Guicard", u"FAB", None))

#if QT_CONFIG(tooltip)
        self.combo_c_brand.setToolTip(QCoreApplication.translate("Guicard", u"\u4eea\u8868(\u63a7\u5236\u5668)\u54c1\u724c\uff0c\u5fc5\u586b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_c_family.setText(QCoreApplication.translate("Guicard", u"\u4eea\u8868\u7cfb\u5217", None))
#if QT_CONFIG(tooltip)
        self.combo_c_family.setToolTip(QCoreApplication.translate("Guicard", u"\u7528\u6237\u70b9\u540d\u4eea\u8868\u7cfb\u5217\uff08\u5982 3306/FAB330\uff09\uff0cengine \u6309\u7cfb\u5217\u6536\u655b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_c_family.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a3306", None))
        self.label_size.setText(QCoreApplication.translate("Guicard", u"\u53f0\u9762\u5c3a\u5bf8\uff08\u7c73\uff09", None))
        self.combo_size.setItemText(0, QCoreApplication.translate("Guicard", u"0.6x0.8", None))
        self.combo_size.setItemText(1, QCoreApplication.translate("Guicard", u"0.8x0.8", None))
        self.combo_size.setItemText(2, QCoreApplication.translate("Guicard", u"1x1", None))
        self.combo_size.setItemText(3, QCoreApplication.translate("Guicard", u"1.2x1.2", None))
        self.combo_size.setItemText(4, QCoreApplication.translate("Guicard", u"1.2x1.5", None))
        self.combo_size.setItemText(5, QCoreApplication.translate("Guicard", u"1.5x1.5", None))
        self.combo_size.setItemText(6, QCoreApplication.translate("Guicard", u"1.5x2", None))
        self.combo_size.setItemText(7, QCoreApplication.translate("Guicard", u"2x2", None))

#if QT_CONFIG(tooltip)
        self.combo_size.setToolTip(QCoreApplication.translate("Guicard", u"\u79e4\u53f0\u5c3a\u5bf8\uff0c\u683c\u5f0f \u957fx\u5bbd\uff08\u7c73\uff09\uff1b\u5e73\u53f0\u79e4\u3001\u53f0\u79e4\u5fc5\u586b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_size.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a1.2x1.5", None))
        self.label_e_input.setText(QCoreApplication.translate("Guicard", u"\u5206\u5ea6\u503ce\uff08kg\uff09", None))
        self.combo_e_input.setItemText(0, QCoreApplication.translate("Guicard", u"5", None))
        self.combo_e_input.setItemText(1, QCoreApplication.translate("Guicard", u"10", None))
        self.combo_e_input.setItemText(2, QCoreApplication.translate("Guicard", u"20", None))
        self.combo_e_input.setItemText(3, QCoreApplication.translate("Guicard", u"50", None))

#if QT_CONFIG(tooltip)
        self.combo_e_input.setToolTip(QCoreApplication.translate("Guicard", u"\u7cbe\u5ea6\u8981\u6c42/\u5206\u5ea6\u503c/e\u503c\uff1b\u53f0\u79e4\u53ef\u586b\u514b(g)\u503c\uff0c\u81ea\u52a8\u6362\u7b97\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_e_input.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a20", None))
        self.label_r_input.setText(QCoreApplication.translate("Guicard", u"\u989d\u5b9a\u91cf\u7a0b\uff08kg\uff09", None))
        self.combo_r_input.setItemText(0, QCoreApplication.translate("Guicard", u"60", None))
        self.combo_r_input.setItemText(1, QCoreApplication.translate("Guicard", u"150", None))
        self.combo_r_input.setItemText(2, QCoreApplication.translate("Guicard", u"300", None))
        self.combo_r_input.setItemText(3, QCoreApplication.translate("Guicard", u"600", None))
        self.combo_r_input.setItemText(4, QCoreApplication.translate("Guicard", u"1500", None))
        self.combo_r_input.setItemText(5, QCoreApplication.translate("Guicard", u"3000", None))
        self.combo_r_input.setItemText(6, QCoreApplication.translate("Guicard", u"6000", None))
        self.combo_r_input.setItemText(7, QCoreApplication.translate("Guicard", u"10000", None))

#if QT_CONFIG(tooltip)
        self.combo_r_input.setToolTip(QCoreApplication.translate("Guicard", u"\u989d\u5b9a\u5bb9\u91cf/\u91cf\u7a0b\uff1b\u5e73\u53f0\u79e4\u3001\u53f0\u79e4\u5fc5\u586b(\u91cf\u7a0b\u5411\u4e0a\u53d6\u6863)\uff0c\u6a21\u5757\u7ebf\u4e3a\u8ba1\u91cf\u63a8\u7b97\u5165\u53c2\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_r_input.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a3000", None))
        self.label_vibration.setText(QCoreApplication.translate("Guicard", u"\u6405\u62cc", None))
        self.combo_vibration.setItemText(0, "")
        self.combo_vibration.setItemText(1, QCoreApplication.translate("Guicard", u"\u65e0\u6405\u62cc", None))
        self.combo_vibration.setItemText(2, QCoreApplication.translate("Guicard", u"\u5e26\u6405\u62cc", None))

#if QT_CONFIG(tooltip)
        self.combo_vibration.setToolTip(QCoreApplication.translate("Guicard", u"\u662f\u5426\u5e26\u6405\u62cc\uff1b\u5e26\u6405\u62cc\u65f6\u9700\u586b\u8f6c\u901f\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_RPM.setText(QCoreApplication.translate("Guicard", u"\u6405\u62cc\u8f6c\u901f", None))
        self.combo_RPM.setItemText(0, QCoreApplication.translate("Guicard", u"200", None))
        self.combo_RPM.setItemText(1, QCoreApplication.translate("Guicard", u"500", None))
        self.combo_RPM.setItemText(2, QCoreApplication.translate("Guicard", u"960", None))
        self.combo_RPM.setItemText(3, QCoreApplication.translate("Guicard", u"1450", None))

#if QT_CONFIG(tooltip)
        self.combo_RPM.setToolTip(QCoreApplication.translate("Guicard", u"\u6405\u62cc\u8f6c\u901f\uff08RPM\uff09\uff1b\u9ad8\u901f\u6405\u62cc\u5f71\u54cd\u4f20\u611f\u5668\u9009\u578b\uff08\u62c9\u6746\uff09\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.combo_RPM.setPlaceholderText(QCoreApplication.translate("Guicard", u"\u5982\uff1a960", None))
        self.label_installForm.setText(QCoreApplication.translate("Guicard", u"\u79e4\u4f53-\u4eea\u8868\u8fde\u63a5", None))
        self.combo_installForm.setItemText(0, "")
        self.combo_installForm.setItemText(1, QCoreApplication.translate("Guicard", u"\u4e00\u4f53", None))
        self.combo_installForm.setItemText(2, QCoreApplication.translate("Guicard", u"\u5206\u4f53", None))

#if QT_CONFIG(tooltip)
        self.combo_installForm.setToolTip(QCoreApplication.translate("Guicard", u"\u79e4\u4f53\u4e0e\u4eea\u8868\u7684\u8fde\u63a5\u5f62\u5f0f\uff1a\u4e00\u4f53/\u5206\u4f53\uff1b\u53f0\u79e4\u7f3a\u7701\u4e00\u4f53\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_bracket.setText(QCoreApplication.translate("Guicard", u"\u5206\u4f53\u4eea\u8868\u652f\u67b6", None))
        self.combo_bracket.setItemText(0, "")
        self.combo_bracket.setItemText(1, QCoreApplication.translate("Guicard", u"\u58c1\u6302\u652f\u67b6", None))
        self.combo_bracket.setItemText(2, QCoreApplication.translate("Guicard", u"\u7acb\u6746\u652f\u67b6", None))

#if QT_CONFIG(tooltip)
        self.combo_bracket.setToolTip(QCoreApplication.translate("Guicard", u"\u5206\u4f53\u5b89\u88c5\u65f6\u7684\u4eea\u8868\u652f\u67b6\uff1b\u9009\u300c\u5206\u4f53\u300d\u540e\u53ef\u7528\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_install.setText(QCoreApplication.translate("Guicard", u"\u4eea\u8868\u5b89\u88c5\u65b9\u5f0f", None))
        self.combo_install.setItemText(0, "")
        self.combo_install.setItemText(1, QCoreApplication.translate("Guicard", u"\u9762\u677f\u5f0f", None))
        self.combo_install.setItemText(2, QCoreApplication.translate("Guicard", u"\u5bfc\u8f68\u5f0f", None))
        self.combo_install.setItemText(3, QCoreApplication.translate("Guicard", u"\u9632\u5c18\u5f0f", None))
        self.combo_install.setItemText(4, QCoreApplication.translate("Guicard", u"\u9694\u7206", None))

#if QT_CONFIG(tooltip)
        self.combo_install.setToolTip(QCoreApplication.translate("Guicard", u"\u4eea\u8868(\u63a7\u5236\u5668)\u5b89\u88c5\u65b9\u5f0f\uff0c\u6309\u6b64\u7b5b\u9009\u4eea\u8868\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_power.setText(QCoreApplication.translate("Guicard", u"\u4f9b\u7535\u65b9\u5f0f", None))
        self.combo_power.setItemText(0, "")
        self.combo_power.setItemText(1, QCoreApplication.translate("Guicard", u"AC220V", None))
        self.combo_power.setItemText(2, QCoreApplication.translate("Guicard", u"DC24V", None))

#if QT_CONFIG(tooltip)
        self.combo_power.setToolTip(QCoreApplication.translate("Guicard", u"\u4eea\u8868\u4f9b\u7535\u65b9\u5f0f\uff0c\u6309\u6b64\u7b5b\u9009\u4eea\u8868\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_req_com1.setText(QCoreApplication.translate("Guicard", u"\u4e32\u53e3\u901a\u8baf", None))
        self.combo_req_com1.setItemText(0, "")
        self.combo_req_com1.setItemText(1, QCoreApplication.translate("Guicard", u"RS232", None))
        self.combo_req_com1.setItemText(2, QCoreApplication.translate("Guicard", u"RS485", None))
        self.combo_req_com1.setItemText(3, QCoreApplication.translate("Guicard", u"RS232+RS485", None))
        self.combo_req_com1.setItemText(4, QCoreApplication.translate("Guicard", u"Modbus", None))
        self.combo_req_com1.setItemText(5, QCoreApplication.translate("Guicard", u"Modbus\uff082\u8def\uff09", None))

#if QT_CONFIG(tooltip)
        self.combo_req_com1.setToolTip(QCoreApplication.translate("Guicard", u"\u57fa\u7840\u4e32\u53e3\u9700\u6c42\u7ec4\u5408\uff1b\u7f3a\u7701\uff08\u4e0d\u9009\uff09\u4e3a\u5355\u4e00\u57fa\u7840\u4e32\u53e3\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_channels.setText(QCoreApplication.translate("Guicard", u"\u901a\u9053\u6570", None))
        self.combo_channels.setItemText(0, "")
        self.combo_channels.setItemText(1, QCoreApplication.translate("Guicard", u"1\u901a\u9053", None))
        self.combo_channels.setItemText(2, QCoreApplication.translate("Guicard", u"2\u901a\u9053", None))
        self.combo_channels.setItemText(3, QCoreApplication.translate("Guicard", u"3\u901a\u9053", None))
        self.combo_channels.setItemText(4, QCoreApplication.translate("Guicard", u"4\u901a\u9053", None))

#if QT_CONFIG(tooltip)
        self.combo_channels.setToolTip(QCoreApplication.translate("Guicard", u"\u591a\u901a\u9053\u9700\u6c42\uff1a2\u901a\u9053\u53ca\u4ee5\u4e0a\u6309\u591a\u901a\u9053\u9009\u578b\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_req_com2.setText(QCoreApplication.translate("Guicard", u"\u6269\u5c55\u901a\u8baf", None))
#if QT_CONFIG(tooltip)
        self.combo_req_com2.setToolTip(QCoreApplication.translate("Guicard", u"\u6269\u5c55\u901a\u8baf\u534f\u8bae\uff0c\u53ef\u591a\u9009\uff1b\u65e0\u6269\u5c55\u901a\u8baf\u65f6\u7559\u7a7a\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_battery.setText(QCoreApplication.translate("Guicard", u"\u7535\u6c60\u65b9\u6848", None))
        self.combo_battery.setItemText(0, "")
        self.combo_battery.setItemText(1, QCoreApplication.translate("Guicard", u"\u5e26\u7535\u6c60", None))

#if QT_CONFIG(tooltip)
        self.combo_battery.setToolTip(QCoreApplication.translate("Guicard", u"\u662f\u5426\u9700\u8981\u7535\u6c60\u4f9b\u7535\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_required_ex.setText(QCoreApplication.translate("Guicard", u"\u9632\u7206\u7b49\u7ea7", None))
        self.combo_required_ex.setItemText(0, "")
        self.combo_required_ex.setItemText(1, QCoreApplication.translate("Guicard", u"IIBT4", None))
        self.combo_required_ex.setItemText(2, QCoreApplication.translate("Guicard", u"IICT4", None))
        self.combo_required_ex.setItemText(3, QCoreApplication.translate("Guicard", u"IIBT5", None))
        self.combo_required_ex.setItemText(4, QCoreApplication.translate("Guicard", u"IICT5", None))
        self.combo_required_ex.setItemText(5, QCoreApplication.translate("Guicard", u"IIBT6", None))
        self.combo_required_ex.setItemText(6, QCoreApplication.translate("Guicard", u"IICT6", None))

#if QT_CONFIG(tooltip)
        self.combo_required_ex.setToolTip(QCoreApplication.translate("Guicard", u"\u52fe\u9009\u300c\u662f\u5426\u9632\u7206\u300d\u540e\u53ef\u9009\uff1b\u4e0d\u9009\u65f6\u7f3a\u7701 IIBT4\uff08\u4e1a\u52a1\u6700\u4f4e\u9632\u7206\u7b49\u7ea7\uff09\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_2.setText(QCoreApplication.translate("Guicard", u"\u6761\u76ee", None))
    # retranslateUi

