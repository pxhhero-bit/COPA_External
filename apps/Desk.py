import os
import re
import sys
from types import ModuleType

# 直接以脚本方式运行时，把项目根目录加入 sys.path，使 COPA 包可以常规导入
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPlainTextEdit, QPushButton, QCheckBox, QMessageBox

from COPA.engine import engine
from COPA.apps import app_icon
from COPA.apps.MultiCombo import CheckableComboBox
from COPA.apps.Parser import Parser
from COPA.apps.SyncParser import SyncParser
from COPA.apps.Ui_quotecard import Ui_Quotecard
from COPA.apps.Ui_guicard import Ui_Guicard
from COPA.apps.Ui_quoteDesk import Ui_quoteDesk

# Commander「设置 -> 默认输入方式」写入 QSettings，Desk 创建时读取
DEFAULT_INPUT_TEXT = "输入框输入"
DEFAULT_INPUT_GUI = "下拉菜单输入"

_SETTINGS_ORG = "COPA"
_SETTINGS_APP = "COPA"
_INPUT_MODE_KEY = "desk/default_input"


def default_input_mode():
    """设置菜单记忆的 Desk 默认输入页签名；无记忆或值非法时
    回落输入框输入(原有录入方式)"""
    saved = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(
        _INPUT_MODE_KEY, DEFAULT_INPUT_TEXT
    )
    return saved if saved in (DEFAULT_INPUT_TEXT, DEFAULT_INPUT_GUI) \
        else DEFAULT_INPUT_TEXT


def set_default_input_mode(mode):
    """设置菜单写入默认输入页签；对之后创建的 Desk 生效"""
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_INPUT_MODE_KEY, mode)


# GUI 串口通讯组合选项 -> (基础串口协议组, Modbus路数)：与文本解析的
# com1 推导输入同构(单一串口/双串口/Modbus路数)，推导链共用 Parser
_GUI_COM1_OPTIONS = {
    "RS232": (("RS232",), 1),
    "RS485": (("RS485",), 1),
    "RS232+RS485": (("RS232", "RS485"), 1),
    "Modbus": (("Modbus",), 1),
    "Modbus（2路）": (("Modbus",), 2),
}

# GUI 数值输入的重量单位后缀 -> kg 换算系数(口径同 Parser 单位表)
_GUI_WEIGHT_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(吨|千克|公斤|克|[kK][gG]|[tT])?$"
)
_GUI_WEIGHT_FACTORS = {
    "吨": 1000.0, "t": 1000.0, "T": 1000.0,
    "千克": 1.0, "公斤": 1.0, "kg": 1.0,
    "克": 0.001, "g": 0.001,
}

# 仪表线字段(各品类通用)：品牌/系列/通讯/硬件/防爆等级
_COMMON_VISIBLE = frozenset((
    "c_brand", "c_family", "req_com1", "req_com2",
    "install", "power", "required_ex",
))

# 汽车衡暂不支持选型，字段全部隐藏。隐藏字段不采集(输出缺省=
# 未提及)，缺省语义由 build_engine_input/engine 侧兜底
_TYPE_TABLE = {
    "称重模块": {
        "visible": _COMMON_VISIBLE | frozenset((
            "W1", "W2", "support", "material", "m_brand",
            "e_input", "r_input", "vibration", "RPM", "special_req",
        )),
        "required": frozenset((
            "W1", "W2", "support", "material", "m_brand", "c_brand",
        )),
    },
    "平台秤": {
        "visible": _COMMON_VISIBLE | frozenset((
            "W1", "r_input", "material", "m_brand", "台面尺寸", "e_input",
            "安装形式", "分体仪表支架", "special_req", "special_req2",
        )),
        # 量程档位是平台/台秤线的业务输入：额定量程必填(量程向上取档)，
        # W1 降级为可选覆盖项(未填时由额定量程兼任，见 build_engine_input)
        "required": frozenset(("r_input", "material", "台面尺寸", "c_brand")),
    },
    "台秤": {
        "visible": _COMMON_VISIBLE | frozenset((
            "W1", "r_input", "material", "m_brand", "台面尺寸", "e_input",
            "安装形式", "分体仪表支架", "special_req2",
        )),
        "required": frozenset((
            "r_input", "material", "m_brand", "台面尺寸", "c_brand",
        )),
    },
    "汽车衡": {
        "visible": frozenset(),
        "required": frozenset(),
    },
    "数字式汽车衡": {
        "visible": frozenset(),
        "required": frozenset(),
    },
}

# 结构化取值的空值(=未提及)：类型联动隐藏的字段按此输出缺省
_STRUCT_EMPTY = {
    "W1": None, "W2": None, "support": None,
    "m_brand": "", "c_brand": "", "c_family": "",
    "material": "", "台面尺寸": "",
    "e_input": None, "r_input": None,
    "vibration": False, "RPM": 0,
    "安装形式": "", "分体仪表支架": "",
    "install": "", "power": "",
    "req_com1": "", "req_com2": [],
    "special_req": None, "special_req2": False,
    "required_ex": "",
}

# 下拉字段注册表：结构化键 -> (label控件名, 值控件名, 基础文案)。
# 基础文案与 guicard.ui 的 label 静态文本一致(engine 参数名 W1/W2
# 不对用户展示)；类型切换时按必填性在基础文案前加红*
_GUI_FIELDS = (
    ("W1", "label_W1", "combo_W1", "最大料重（kg）"),
    ("W2", "label_W2", "combo_W2", "皮重（kg）"),
    ("support", "label_support", "combo_support", "支点数"),
    ("material", "label_material", "combo_material", "模块材质"),
    ("m_brand", "label_m_brand", "combo_m_brand", "传感器品牌"),
    ("c_brand", "label_c_brand", "combo_c_brand", "仪表品牌"),
    ("c_family", "label_c_family", "combo_c_family", "仪表系列"),
    ("台面尺寸", "label_size", "combo_size", "台面尺寸（米）"),
    ("e_input", "label_e_input", "combo_e_input", "分度值e（kg）"),
    ("r_input", "label_r_input", "combo_r_input", "额定量程（kg）"),
    ("vibration", "label_vibration", "combo_vibration", "搅拌"),
    ("RPM", "label_RPM", "combo_RPM", "搅拌转速"),
    ("安装形式", "label_installForm", "combo_installForm", "秤体-仪表连接"),
    ("分体仪表支架", "label_bracket", "combo_bracket", "分体仪表支架"),
    ("install", "label_install", "combo_install", "仪表安装方式"),
    ("power", "label_power", "combo_power", "供电方式"),
    ("req_com1", "label_req_com1", "combo_req_com1", "串口通讯"),
    ("special_req", "label_channels", "combo_channels", "通道数"),
    ("req_com2", "label_req_com2", "combo_req_com2", "扩展通讯"),
    ("special_req2", "label_battery", "combo_battery", "电池方案"),
    ("required_ex", "label_required_ex", "combo_required_ex", "防爆等级"),
)


def unit_for_type(item_type_text):
    """数量单位：称重模块为套，其余类型为台，未选类型为空"""
    if item_type_text == "称重模块":
        return "套"
    if item_type_text:
        return "台"
    return ""


def _weight_value(text):
    """GUI 数值输入 -> kg 数值(带常用重量单位换算)；空/非法返回
    None(=未提及，缺省语义由 engine 侧兜底)"""
    m = _GUI_WEIGHT_RE.match((text or "").strip())

    if m is None:
        return None

    value = float(m.group(1)) * _GUI_WEIGHT_FACTORS.get(m.group(2) or "", 1.0)
    rounded = round(value, 6)
    return int(rounded) if float(rounded).is_integer() else rounded


def _int_value(text):
    """GUI 整数输入 -> int；空/非法返回 None"""
    m = re.match(r"^(\d+)", (text or "").strip())
    return int(m.group(1)) if m else None


class QuoteCard(QWidget, Ui_Quotecard):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # QWidget 子类默认不绘制样式表里的边框/背景，必须显式开启
        self.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True
        )

        self.comboBox.currentTextChanged.connect(self._update_unit)
        self.comboBox.currentTextChanged.connect(self._on_type_changed)
        self._update_unit(self.comboBox.currentText())
        self._on_type_changed(self.comboBox.currentText())

        self.quote_id = 0

    def _update_unit(self, text):
        self.label_unit.setText(unit_for_type(text))

    def _on_type_changed(self, text):
        # 数字化方案仅模块/平台秤业务存在(台秤无、汽车衡类未接入)：
        # 其余类型置灰并清勾，避免产生无效开关状态
        digital_ok = text in ("称重模块", "平台秤")
        self.checkBox_4.setEnabled(digital_ok)

        if not digital_ok:
            self.checkBox_4.setChecked(False)

    def set_quote_id(self, quote_id):
        self.quote_id = quote_id
        self.label_ID.setText(
            "{}".format(quote_id)
        )

    def getEntryData(self):
        return {
        "item_type": self.comboBox.currentText(),
        "metrology": self.checkBox.isChecked(),
        "high_precision": self.checkBox_2.isChecked(),
        "Ex_P": self.checkBox_3.isChecked(),
        "digital": self.checkBox_4.isChecked(),
        "description": self.plainTextEdit.toPlainText()
        }


class GuiCard(QWidget, Ui_Guicard):
    """下拉菜单输入卡片：条目参数全部由下拉选择(可编辑下拉可自由输入)，
    与输入框输入(QuoteCard，自由文本+Parser解析)并行的第二条录入路径。
    结构化取值经 getEntryData()["structured"] 交 Desk 装配为标准参数，
    不经 Parser 文本解析；空选一律输出 None/空串/False(=未提及)，
    缺省语义与文本未提及同一口径"""

    def __init__(self, ext_protocols=()):
        super().__init__()
        self.setupUi(self)

        # QWidget 子类默认不绘制样式表里的边框/背景，必须显式开启
        self.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True
        )

        self.comboBox.currentTextChanged.connect(self._update_unit)
        self.comboBox.currentTextChanged.connect(self._on_type_changed)
        self._update_unit(self.comboBox.currentText())
        self._on_type_changed(self.comboBox.currentText())

        # 扩展通讯词表由 Desk 注入(经 SyncParser 显示层映射的中文条目，
        # 取值经 com2_canonical 还原规范名)，不在 .ui 二次硬编码；装载
        # 条目会把索引带到首项，复位为未选中(空)，行编辑器只显示勾选摘要
        self.combo_req_com2.addItems(list(ext_protocols))
        self.combo_req_com2.setCurrentIndex(-1)
        line_edit = self.combo_req_com2.lineEdit()

        if line_edit is not None:
            line_edit.setPlaceholderText("可多选，留空为无")

        for combo in (self.combo_W1, self.combo_W2, self.combo_support,
                      self.combo_c_family, self.combo_size,
                      self.combo_e_input, self.combo_r_input,
                      self.combo_RPM):
            combo.setCurrentIndex(-1)

        # 材质全选项快照：按类型收缩(称重模块/台秤无混合材质)
        self._material_all_options = [
            self.combo_material.itemText(i)
            for i in range(self.combo_material.count())
        ]

        # 字段联动注册：条目类型切换 -> 按类型表显隐 label+值控件、
        # 必填项 label 加红*、隐藏项清值(输出缺省=未提及)
        self._field_specs = [
            (key, getattr(self, label_name), getattr(self, combo_name),
             caption)
            for key, label_name, combo_name, caption in _GUI_FIELDS
        ]
        self.comboBox.currentTextChanged.connect(self._apply_type_fields)
        self._apply_type_fields(self.comboBox.currentText())

        self.combo_vibration.currentTextChanged.connect(self._sync_fields)
        self.combo_installForm.currentTextChanged.connect(self._sync_fields)
        self.checkBox_3.toggled.connect(self._sync_fields)
        self._sync_fields()

        self.quote_id = 0

    def _update_unit(self, text):
        self.label_unit.setText(unit_for_type(text))

    def _on_type_changed(self, text):
        # 与 QuoteCard 同一规则：数字化方案仅模块/平台秤业务存在(台秤无、
        # 汽车衡类未接入)：其余类型置灰并清勾，避免产生无效开关状态
        digital_ok = text in ("称重模块", "平台秤")
        self.checkBox_4.setEnabled(digital_ok)

        if not digital_ok:
            self.checkBox_4.setChecked(False)

    def _apply_type_fields(self, item_type):
        """条目类型联动：按类型表显隐下拉字段(label+值控件整对隐藏，
        网格行随之收起)；隐藏字段同步清值 -> 输出缺省(=未提及，缺省
        语义由 engine 侧兜底)。必填字段 label 在基础文案前加红*。
        未选/未知类型时全字段可见且无必填标注(未知品类由 engine 在
        发起选型时报错)"""
        table = _TYPE_TABLE.get(item_type)

        if table is None:
            visible = frozenset(_STRUCT_EMPTY)
            required = frozenset()
        else:
            visible = table["visible"]
            required = table["required"]

        for key, label, combo, caption in self._field_specs:
            if key in visible:
                label.setText(self._label_text(caption, key in required))
                label.show()
                combo.show()
            else:
                label.hide()
                combo.hide()
                self._clear_combo(combo)

        self._apply_material_options(item_type)

        # 隐藏清值可能改变了搅拌/分体等联动源的取值，刷新启停状态
        self._sync_fields()

    def _apply_material_options(self, item_type):
        """按类型收缩材质选项：称重模块/台秤不提供混合材质(混合为
        秤台材质语义)；当前选中值不在收缩后选项内时复位为未选"""
        combo = self.combo_material
        current = combo.currentText()
        options = [
            option for option in self._material_all_options
            if not (item_type in ("称重模块", "台秤") and option == "混合")
        ]

        combo.clear()
        combo.addItems(options)

        if current in options:
            combo.setCurrentText(current)
        else:
            combo.setCurrentIndex(0)

    @staticmethod
    def _label_text(caption, required):
        """label 文案：必填字段前置红*(QLabel 富文本)，其余原样"""
        if required:
            return '<span style="color:#ff0000;">*</span>{}'.format(caption)
        return caption

    @staticmethod
    def _clear_combo(combo):
        """隐藏前清值：可勾选下拉清勾选；可编辑下拉回未选(空)；
        固定下拉回空首项，保证复显时不带残留取值"""
        if isinstance(combo, CheckableComboBox):
            combo.setCheckedItems([])
            combo.setCurrentIndex(-1)
        elif combo.isEditable():
            combo.setCurrentIndex(-1)
            combo.setEditText("")
        else:
            combo.setCurrentIndex(0)

    def _sync_fields(self):
        # 搅拌转速：仅带搅拌时可填，恢复无搅拌时清空(缺省转速0)
        vibration = self.combo_vibration.currentText() == "带搅拌"
        self.combo_RPM.setEnabled(vibration)

        if not vibration:
            self.combo_RPM.setEditText("")

        # 分体仪表支架：仅秤体分体安装时可选
        split = self.combo_installForm.currentText() == "分体"
        self.combo_bracket.setEnabled(split)

        if not split:
            self.combo_bracket.setCurrentIndex(0)

        # 防爆等级：仅勾选防爆时可选；不选时缺省 IIBT4 由 engine 侧兜底
        ex_checked = self.checkBox_3.isChecked()
        self.combo_required_ex.setEnabled(ex_checked)

        if not ex_checked:
            self.combo_required_ex.setCurrentIndex(0)

    def set_quote_id(self, quote_id):
        self.quote_id = quote_id
        self.label_ID.setText(
            "{}".format(quote_id)
        )

    def getEntryData(self):
        return {
        "item_type": self.comboBox.currentText(),
        "metrology": self.checkBox.isChecked(),
        "high_precision": self.checkBox_2.isChecked(),
        "Ex_P": self.checkBox_3.isChecked(),
        "digital": self.checkBox_4.isChecked(),
        # 下拉菜单输入不产生描述文本
        "description": "",
        # 输入方式标记：上层按此区分两条录入路径(文本卡片条目无此键)
        "input_mode": "gui",
        "structured": self._collect_structured(),
        }

    def get_structured(self):
        """结构化取值(标准参数字典)：SyncParser 逆向同步与选型回填的
        统一输入形态"""
        return self._collect_structured()

    def _collect_structured(self):
        """下拉选择 -> 结构化取值：数值带常用重量单位换算，空选为
        None/空串/False(=未提及)；类型联动隐藏的字段直接输出缺省值，
        与「不显示即不输入」的口径一致(防御切换类型前的残留输入)"""
        vibration = self.combo_vibration.currentText() == "带搅拌"

        values = {
            "W1": _weight_value(self.combo_W1.currentText()),
            "W2": _weight_value(self.combo_W2.currentText()),
            "support": _int_value(self.combo_support.currentText()),
            "m_brand": self.combo_m_brand.currentText().strip(),
            "c_brand": self.combo_c_brand.currentText().strip(),
            "c_family": self.combo_c_family.currentText().strip(),
            "material": self.combo_material.currentText().strip(),
            "台面尺寸": self.combo_size.currentText().strip(),
            "e_input": _weight_value(self.combo_e_input.currentText()),
            "r_input": _weight_value(self.combo_r_input.currentText()),
            "vibration": vibration,
            "RPM": (
                _int_value(self.combo_RPM.currentText())
                if vibration else 0
            ),
            "安装形式": self.combo_installForm.currentText().strip(),
            "分体仪表支架": self.combo_bracket.currentText().strip(),
            "install": self.combo_install.currentText().strip(),
            "power": self.combo_power.currentText().strip(),
            "req_com1": self.combo_req_com1.currentText().strip(),
            "req_com2": self.combo_req_com2.checkedItems(),
            "special_req": self._channels_value(),
            "special_req2": self.combo_battery.currentText() == "带电池",
            "required_ex": (
                self.combo_required_ex.currentText().strip()
                if self.checkBox_3.isChecked() else ""
            ),
        }

        table = _TYPE_TABLE.get(self.comboBox.currentText())

        if table is not None:
            for key, empty in _STRUCT_EMPTY.items():
                if key not in table["visible"]:
                    values[key] = empty

        return values

    def _channels_value(self):
        """通道数选项 -> int；空选返回 None。
        仅 >=2 才是 engine 的多通道语义，Desk 装配时按此过滤"""
        text = self.combo_channels.currentText().strip()

        if not text:
            return None

        return _int_value(text)


def build_engine_input(entry):
    """卡片条目 -> engine 需求格式参数（EngineService._build_input 的纯函数版）。

    仅依赖 engine 模块导入时的 resolver（规则JSON），不装载数据库即可生成，
    快照导出与实际计算共用同一构建逻辑。参数全部由卡片输入决定：结构化字段
    (item_type/metrology/high_precision/Ex_P) + Parser 从 description 解析出的
    标准参数(req_com1 缺省已在解析步归一)。约定缺省：req_com2 -> 空，多通道 ->
    单通道，量程/e值 -> 空，防爆未给等级 -> IIBT4(业务最低防爆等级)，
    搅拌缺省/无搅拌 -> 转速0，电池未提及 -> 无电池
    """
    parsed = entry.get("parsed", {}).get("data", {})

    item_type = engine.resolver.resolve_item_type(
        entry["item_type"]
    )
    # platform/bench：只报量程未报W1时，量程兼任W1(量程向上取档的输入)；
    # platform/bench 的选型不走 metrology 模块，r_input 不作替代将无处生效。
    # 模块通道量程与W1并存，不做替代
    w1 = parsed.get("W1")
    r_input = parsed.get("r_input")

    if item_type in ("platform", "bench") and w1 is None:
        w1 = r_input

    ex_p = entry["Ex_P"] or bool(parsed.get("Ex_P", False))
    bracket = parsed.get("分体仪表支架")
    # 无搅拌时压掉可能杂散解析出的转速("不带搅拌，转速200"以无搅拌为准)
    vibration = bool(parsed.get("vibration", False))
    # special_req 解析为通道数，>=2 才是 engine 的多通道语义
    channels = parsed.get("special_req") or 0

    return {
        "module_data": {
            "item_type": item_type,
            "W1": w1,
            "W2": parsed.get("W2"),
            "support": parsed.get("support"),
            "Ex_P": ex_p,
            "required_ex": (
                parsed.get("required_ex") or "IIBT4"
            ) if ex_p else False,
            "material": parsed.get("material"),
            "vibration": vibration,
            "RPM": parsed.get("RPM", 0) if vibration else 0,
            "台面尺寸": parsed.get("台面尺寸"),
            "高精度": entry["high_precision"] or bool(parsed.get("高精度", False)),
            # 数字化方案：仅卡片开关通道(不在描述文本中解析)
            "数字化": bool(entry.get("digital", False)),
            "e_input": parsed.get("e_input"),
            "安装形式": parsed.get("安装形式"),
            "分体仪表支架": bracket,
            "m_brand": parsed.get("m_brand"),
            "c_brand": parsed.get("c_brand"),
            # 用户点名仪表系列(Parser 二次识别，如 3306/FAB330)，engine 按系列收敛
            "c_family": parsed.get("c_family"),
        },
        "metrology": {
            "metrology": entry["metrology"] or bool(parsed.get("metrology", False)),
            "r_input": parsed.get("r_input"),
            "e_input": parsed.get("e_input")
        },
        "com": {
            "req_com1": parsed.get("req_com1"),
            "req_com2": parsed.get("req_com2"),
            "special_req": channels >= 2,
            "special_req2": bool(parsed.get("special_req2", False))
        },
        "hardware": {
            "install": parsed.get("install"),
            "power": parsed.get("power"),
            "bracket": bracket
        }
    }


# 缺参提示中文映射：engine 标准参数ID -> 中文名(表外键原样显示，
# 如"台面尺寸"本就是中文)
_PARAM_CN = {
    "m_brand": "传感器品牌",
    "c_brand": "仪表品牌",
    "support": "支点数",
    "material": "模块材质",
    "W1": "最大物料重量",
    "W2": "设备自重",
}


class EngineService:
    """engine 选型计算服务：规则与数据库懒加载，逐条串行计算。

    计算从 Desk 层上移后由 Commander 持有全局共享的一份(多项目共用
    数据库，只加载一次)；Desk 独立运行时在 __main__ 自建一份。
    串行执行：engine 为纯 Python 计算，并行无收益(GIL)，且免去多线程
    共享 resolver/databases 的安全隐患。
    """

    def __init__(self):
        # engine 模块懒加载(_load)；ModuleType 属性动态，静态检查器不报未知属性
        self._engine: ModuleType | None = None
        self._databases: dict | None = None
        self.default_brand = None
        # 传感器表按品牌分文件装载：行数据无 brand 字段，品牌隔离只能
        # 靠文件，不能合并(合并会混出跨品牌的选型)，运行时按条目 m_brand 取用
        self._sensors_by_brand = {}

    @property
    def ready(self):
        return self._engine is not None

    def _load(self):
        """首次计算时装载规则与数据库(耗时较长)"""
        rules = engine.resolver.rules
        brands = rules["brands"]
        first_brand = brands["available_brands"][0]
        db_m = engine.DatabaseLoader(rules, first_brand)

        controllers = []

        for brand in brands["controller_db"]:
            try:
                loader = engine.DatabaseLoader(rules, brand)
                controllers += loader.load_controllers()
            except Exception:
                continue

        for brand in brands["sensor_db"]:
            try:
                loader = engine.DatabaseLoader(rules, brand)
                self._sensors_by_brand[brand] = loader.load_sensors()
            except Exception:
                continue

        self._engine = engine
        self.default_brand = first_brand
        self._databases = {
            "sensors": self._sensors_by_brand.get(first_brand, []),
            "modules": db_m.load_modules(),
            "jbox": db_m.load_jbox(),
            "platforms": db_m.load_platforms(),
            "benches": db_m.load_benches(),
            "controllers": controllers,
        }

    def run_batch(self, entries):
        """逐条串行选型 -> 与 entries 同序的结果列表。
        条目缺参或引擎异常均转为 status=ERROR 的结果返回，不中断批次"""
        if not self.ready:
            self._load()

        results = []

        for entry in entries:
            result = self._run_one(entry)
            results.append(result)

            print(
                "=== 选型结果 quote_id={} item_type={} status={} ===".format(
                    result.get("quote_id"),
                    result.get("item_type"),
                    result.get("status")
                )
            )

            if "error" in result:
                print("错误: {}".format(result["error"]))

        return results

    def _run_one(self, entry):
        quote_id = entry["quote_info"]["quote_id"]

        engine = self._engine
        databases_base = self._databases

        if engine is None or databases_base is None:
            return {
                "quote_id": quote_id,
                "item_type": entry["item_type"],
                "status": "ERROR",
                "error": "engine 尚未加载"
            }

        try:
            engine_input = self._build_input(entry)
            missing = self._missing_required(engine_input)

            if missing:
                return {
                    "quote_id": quote_id,
                    "item_type": entry["item_type"],
                    "status": "ERROR",
                    "error": "缺少必要参数：{}（请在项目描述中补充）".format(
                        "、".join(_PARAM_CN.get(key, key) for key in missing)
                    )
                }

            # 传感器表按条目 m_brand 取用；品牌未填写(平台秤可选)时合并
            # AW+FT 传感器库(两品牌传感器均可配)；库数据缺失的品牌为空表
            m_brand = engine_input["module_data"]["m_brand"]
            databases = dict(databases_base)
            if m_brand:
                databases["sensors"] = self._sensors_by_brand.get(m_brand, [])
            else:
                merged = []
                for brand_rows in self._sensors_by_brand.values():
                    merged.extend(brand_rows)
                databases["sensors"] = merged

            return engine.run_engine(
                user_input=engine_input,
                resolver=engine.resolver,
                databases=databases,
                quote_id=quote_id
            )
        except Exception as err:
            return {
                "quote_id": quote_id,
                "item_type": entry["item_type"],
                "status": "ERROR",
                "error": str(err)
            }

    def _build_input(self, entry):
        if self._engine is None:
            # 调用链上 run_batch 已先触发 _load，此处仅为静态收窄与兜底
            raise RuntimeError("engine 尚未加载")

        return build_engine_input(entry)

    @staticmethod
    def _missing_required(engine_input):
        # 引擎对空值敏感的必填参数预检：缺失时给出可读错误，
        # 而不是让引擎在计算中途抛 TypeError。
        # platform/bench 的W1已在 _build_input 中由量程兼任，
        # 故此处 W1 有值即代表 量程/W1 至少其一满足。
        # m_brand(传感器品牌)：模块/台秤必填；平台秤可选——未填写时
        # 双品牌平台均参选、传感器库合并(AW+FT)
        module_data = engine_input["module_data"]
        required = ["W1", "c_brand", "material"]

        if module_data["item_type"] == "module":
            required += ["m_brand", "support"]
        elif module_data["item_type"] == "bench":
            required += ["m_brand"]

        missing = [
            key for key in required
            if module_data.get(key) is None
        ]

        if module_data["item_type"] in ("platform", "bench"):
            # 台面尺寸在 module_data；电池未提及时已在 _build_input 缺省为无电池
            if module_data.get("台面尺寸") is None:
                missing.append("台面尺寸")

        return missing


class Desk(QWidget, Ui_quoteDesk):

    # 选型发起信号：携带已解析的卡片条目列表；engine 计算由上层
    # (Commander，后台串行)或本地 EngineService(__main__ 独立运行)执行
    selectionRequested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(app_icon())

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(226, 226, 226))
        palette.setColor(QPalette.ColorRole.Base, QColor("white"))
        palette.setColor(QPalette.ColorRole.Button, QColor("white"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("black"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("black"))
        self.setPalette(palette)

        self.scrollArea.viewport().setBackgroundRole(QPalette.ColorRole.Window)
        self.guiScrollArea.viewport().setBackgroundRole(QPalette.ColorRole.Window)

        for page in (self.tabText, self.tabGui):
            page.setAutoFillBackground(True)

        tab_bar = self.inputTabs.tabBar()
        tab_font = tab_bar.font()

        if tab_font.pointSize() > 0:
            tab_font.setPointSize(tab_font.pointSize() + 1)
        else:
            tab_font.setPointSize(10)

        tab_font.setBold(True)
        tab_bar.setFont(tab_font)

        self.cardIndex = 0
        self.guiCardIndex = 0

        # ScrollArea
        self.scrollArea.setWidgetResizable(True)
        self.guiScrollArea.setWidgetResizable(True)

        # Card 容器（输入框输入页签）
        self.cardContainerLayout = QVBoxLayout(
            self.cardContainer
        )

        self.cardContainerLayout.setContentsMargins(
            10, 10, 10, 10
        )

        self.cardContainerLayout.setSpacing(10)

        # Card 容器（下拉菜单输入页签）
        self.guiCardContainerLayout = QVBoxLayout(
            self.guiCardContainer
        )

        self.guiCardContainerLayout.setContentsMargins(
            10, 10, 10, 10
        )

        self.guiCardContainerLayout.setSpacing(10)

        # 新建为双页签联动(1信号多槽)：一次点击在两页签各建一张卡片并
        # 配对镜像，条目数与序号保持一致；删除走单一入口(delete_entry)，
        # 守卫提示与双侧删除必须原子完成，多槽会各弹一次提示
        self.pushButton_add.clicked.connect(self.add_card)
        self.pushButton_add.clicked.connect(self.add_gui_card)
        self.pushButton_add.clicked.connect(self._pair_last_cards)
        self.pushButton_gui_add.clicked.connect(self.add_card)
        self.pushButton_gui_add.clicked.connect(self.add_gui_card)
        self.pushButton_gui_add.clicked.connect(self._pair_last_cards)
        self.pushButton_del.clicked.connect(self.delete_entry)
        self.pushButton_gui_del.clicked.connect(self.delete_entry)
        self.pushButton_start.clicked.connect(self.start_selection)

        # description 文本解析器（规则JSON即时加载，CSV词表惰性构建）
        self._parser = Parser()

        # description 逆向同步解析器(下拉 -> 标准文本，与 Parser 共用
        # 同一规则文件)；_bridge_lock 为选型回填期间的桥接锁(回填写入
        # 下拉字段时不逆向再生描述，用户原文不被覆盖)
        self._sync_parser = SyncParser()
        self._bridge_lock = False

        # 扩展通讯词表(Parser 规则的 extended 类协议)注入 GUI 卡片；
        # 下拉条目显示走 SyncParser 显示层映射(模拟量4-20mA 等中文)，
        # 规范名清单另行保留(恢复/回填时显示名<->规范名互转用)
        self._ext_protocols = [
            entry["canonical"]
            for entry in self._parser.rules.get("protocols", [])
            if entry.get("category") == "extended"
        ]
        self._ext_protocol_display = [
            self._sync_parser.com2_display(name)
            for name in self._ext_protocols
        ]

        # 默认输入页签：设置菜单可调(Commander「设置 -> 默认输入方式」)，
        # 缺省输入框输入(原有录入方式)；快照恢复时由 restore_entries 切回
        self.inputTabs.setCurrentIndex(
            1 if default_input_mode() == DEFAULT_INPUT_GUI else 0
        )

        # 默认 Card：两页签同步建一对并配对，与「至少保留一个条目」约定一致
        self.add_card()
        self.add_gui_card()
        self._pair_last_cards()

    def add_card(self):
        card = QuoteCard()

        self.cardContainerLayout.insertWidget(
            self.cardIndex,
            card
        )

        card.set_quote_id(self.cardIndex + 1)

        self.cardIndex += 1

        self._refresh_scroll_area()

    def delete_entry(self):
        """双页签同步删除最后一对条目：守卫提示只弹一次，两页签的
        尾条目同删，保持条目数与序号始终一致"""
        if (self.cardContainerLayout.count() <= 1
                or self.guiCardContainerLayout.count() <= 1):
            QMessageBox.information(
                self,
                "提示",
                    "至少需保留一个条目。"
            )
            return

        for layout in (self.cardContainerLayout,
                       self.guiCardContainerLayout):
            item = layout.takeAt(layout.count() - 1)

            if item is not None:
                widget = item.widget()

                if widget is not None:
                    widget.deleteLater()

        self.cardIndex -= 1
        self.guiCardIndex -= 1

        self._refresh_scroll_area()
        self._refresh_scroll_area(self.guiScrollArea)

    def _link_card_pair(self, text_card, gui_card):
        """配对同一序号的文本/下拉卡片，两条同步通道：
        1. 共享字段(条目类型/数量/四个勾选)双向实时镜像——回写同值
           不触发信号，镜像链天然无递归；
        2. 下拉 -> 描述文本单向桥——任一下拉字段变更即经 SyncParser
           重建文本卡片描述(逆向同步)；描述 -> 下拉方向不在编辑期
           接线，由选型确认信号一次性回填(_backfill_gui_from_text)，
           结构上排除无限回填。"""
        for src, dst in ((text_card, gui_card), (gui_card, text_card)):
            src.comboBox.currentTextChanged.connect(
                dst.comboBox.setCurrentText
            )
            src.spinBox.valueChanged.connect(
                dst.spinBox.setValue
            )

            for index, src_check in enumerate(
                    (src.checkBox, src.checkBox_2, src.checkBox_3,
                     src.checkBox_4), start=1):
                dst_check = (dst.checkBox if index == 1
                             else getattr(dst, "checkBox_{}".format(index)))
                src_check.toggled.connect(dst_check.setChecked)

        # 下拉 -> 文本：桥接锁期间(选型回填)不再生
        for _key, _label, combo_name, _caption in _GUI_FIELDS:
            getattr(gui_card, combo_name).currentTextChanged.connect(
                lambda *_args, gc=gui_card, tc=text_card:
                    self._regen_description(gc, tc)
            )

    def _regen_description(self, gui_card, text_card):
        """下拉 -> 描述文本(SyncParser 逆向同步)：以结构化取值重建
        配对文本卡片的描述。空选/缺省值(含类型联动隐藏字段的缺省)
        不产出片段；勾选防爆才产出防爆片段。结构化值非法(自由手输
        不被规则接受)时跳过本次同步并保留原描述，不打断输入"""
        if self._bridge_lock:
            return

        values = gui_card.get_structured()

        if gui_card.checkBox_3.isChecked():
            values["Ex_P"] = True

        # 串口通讯组合选项是 gui 侧表达，转成 SyncParser/Parser 认可的
        # 协议列表形态("Modbus（2路）" -> ["2路Modbus"])；未知自由值不
        # 产出该片段
        com1_option = values.get("req_com1")
        if com1_option:
            option = _GUI_COM1_OPTIONS.get(com1_option)

            if option is None:
                values.pop("req_com1", None)
            else:
                protocols, modbus_count = option
                values["req_com1"] = (
                    ["2路Modbus"] if "Modbus" in protocols and modbus_count > 1
                    else ["Modbus"] if "Modbus" in protocols
                    else list(protocols)
                )

        values = {
            key: value for key, value in values.items()
            if value not in (None, "", False, 0, [])
        }

        try:
            text = self._sync_parser.sync_quote_text(values)
        except (TypeError, ValueError) as err:
            print("[Desk] 描述同步跳过：{}".format(err))
            return

        text_card.plainTextEdit.setPlainText(text)

    def _pair_last_cards(self):
        """新建联动收尾：把两页签最新的两张卡片配对为镜像(同序号
        条目)，并以文本卡片为准回放一次共享字段。新建场景两侧均为
        默认值；恢复快照路径在配对后写入文本卡片，经镜像信号自动
        同步到下拉卡片"""
        text_item = self.cardContainerLayout.itemAt(
            self.cardContainerLayout.count() - 1)
        gui_item = self.guiCardContainerLayout.itemAt(
            self.guiCardContainerLayout.count() - 1)

        text_card = text_item.widget() if text_item is not None else None
        gui_card = gui_item.widget() if gui_item is not None else None

        if not isinstance(text_card, QuoteCard) \
                or not isinstance(gui_card, GuiCard):
            return

        self._link_card_pair(text_card, gui_card)

        gui_card.comboBox.setCurrentText(text_card.comboBox.currentText())
        gui_card.spinBox.setValue(text_card.spinBox.value())
        gui_card.checkBox.setChecked(text_card.checkBox.isChecked())
        gui_card.checkBox_2.setChecked(text_card.checkBox_2.isChecked())
        gui_card.checkBox_3.setChecked(text_card.checkBox_3.isChecked())
        gui_card.checkBox_4.setChecked(text_card.checkBox_4.isChecked())

    def add_gui_card(self):
        """下拉菜单输入页签：新建一张结构化卡片"""
        card = GuiCard(self._ext_protocol_display)

        self.guiCardContainerLayout.insertWidget(
            self.guiCardIndex,
            card
        )

        card.set_quote_id(self.guiCardIndex + 1)

        self.guiCardIndex += 1

        self._refresh_scroll_area(self.guiScrollArea)

    def _refresh_scroll_area(self, area=None):
        # 布局的尺寸提示要等事件循环处理 LayoutRequest 后才会更新，
        # 同步调用 adjustSize 拿到的是旧值，必须推迟到下一轮事件循环
        contents = (area or self.scrollArea).widget()

        if contents is not None:
            QTimer.singleShot(
                0,
                contents.adjustSize
            )

    def start_selection(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("开始选型")
        box.setText("确认输入无误后将开始选型")

        btn_continue = box.addButton("继续", QMessageBox.ButtonRole.YesRole)
        box.addButton("再看一眼", QMessageBox.ButtonRole.NoRole)

        box.exec()

        if box.clickedButton() is btn_continue:
            # 文本页签发起时先做一次性 文本->下拉 回填：描述经既有解析
            # 写入配对下拉卡片(桥接锁定，用户原文不被逆向再生覆盖)；
            # 下拉页签发起时跳过(下拉即当前权威输入，且描述已实时同步)
            if not self._gui_tab_active():
                self._backfill_gui_from_text()

            entries = self.collect_entries()

            # 皮重=0 视为"只知总重"的人工约定信号(W1=总重、W2=0，
            # 文本路径由 Parser 总重归一产生，GUI 路径为手动约定)：
            # 发起前弹确认框，确认才继续，返回修改则中止本次选型
            zero_tare = [
                (e["quote_info"]["quote_id"],
                 (e.get("parsed") or {}).get("data", {}).get("W1"))
                for e in entries
                if e.get("item_type") == "称重模块"
                and (e.get("parsed") or {}).get("data", {}).get("W2") == 0
                and (e.get("parsed") or {}).get("data", {}).get("W1") is not None
            ]

            if zero_tare:
                detail = "、".join(
                    "条目{}(总重{}kg)".format(qid, w1)
                    for qid, w1 in zero_tare
                )
                confirm = QMessageBox(self)
                confirm.setIcon(QMessageBox.Icon.Warning)
                confirm.setWindowTitle("皮重为0确认")
                confirm.setText(
                    "{}：皮重输入为0，将按照最大料重=总重计算。".format(detail))

                btn_ok = confirm.addButton(
                    "确认", QMessageBox.ButtonRole.YesRole)
                confirm.addButton("返回修改", QMessageBox.ButtonRole.NoRole)
                confirm.exec()

                if confirm.clickedButton() is not btn_ok:
                    return

            self._print_entries(entries)
            # 解析完成的条目交上层发起计算(Commander 后台串行执行并归档)；
            # 独立运行时由 __main__ 连接的本地 EngineService 执行
            self.selectionRequested.emit(entries)

    def _gui_tab_active(self):
        """当前是否处于下拉菜单输入页签"""
        return self.inputTabs.currentIndex() == 1

    def _backfill_gui_from_text(self):
        """选型确认时一次性 文本->下拉 同步：解析各描述并写入配对的
        下拉卡片，两页签条目保持一致。回填期间桥接锁定(写入不触发
        逆向再生)，描述保持用户原文；以解析数据全量覆盖下拉字段，
        描述未提及的参数复位为未选(此时文本为权威输入)"""
        entries = self._parse_descriptions(self._collect_card_data())
        gui_cards = []

        for i in range(self.guiCardContainerLayout.count()):
            item = self.guiCardContainerLayout.itemAt(i)

            if item is None:
                continue

            widget = item.widget()

            if isinstance(widget, GuiCard):
                gui_cards.append(widget)

        self._bridge_lock = True
        try:
            for entry, gui_card in zip(entries, gui_cards):
                self._apply_parsed_to_gui_card(
                    (entry.get("parsed") or {}).get("data") or {},
                    gui_card,
                )
        finally:
            self._bridge_lock = False

    def _apply_parsed_to_gui_card(self, data, card):
        """解析参数 -> 下拉卡片回填：以未选状态为底、解析数据覆盖；
        共享字段(如防爆勾选)经既有镜像与文本卡片保持一致，类型联动
        (字段显隐/清值)随写入自然生效。隐藏字段照常写入，采集时本就
        按可见性过滤"""
        values = dict(_STRUCT_EMPTY)

        for key in ("W1", "W2", "e_input", "r_input", "support", "RPM"):
            if data.get(key) is not None:
                values[key] = data[key]

        for key in ("m_brand", "c_brand", "c_family", "material",
                    "台面尺寸", "安装形式", "分体仪表支架", "install",
                    "power", "required_ex"):
            if data.get(key):
                values[key] = str(data[key])

        if "vibration" in data:
            values["vibration"] = bool(data["vibration"])

        if data.get("special_req") is not None:
            values["special_req"] = data["special_req"]

        if data.get("special_req2"):
            values["special_req2"] = True

        if data.get("req_com1"):
            values["req_com1"] = self._com1_option(data["req_com1"])

        if data.get("req_com2"):
            values["req_com2"] = [str(x) for x in data["req_com2"]]

        card.checkBox_3.setChecked(bool(data.get("Ex_P")))

        for key, combo in (("W1", card.combo_W1), ("W2", card.combo_W2),
                           ("support", card.combo_support),
                           ("e_input", card.combo_e_input),
                           ("r_input", card.combo_r_input),
                           ("RPM", card.combo_RPM)):
            combo.setEditText(
                "" if values[key] is None else str(values[key]))

        for key, combo in (("m_brand", card.combo_m_brand),
                           ("c_brand", card.combo_c_brand),
                           ("material", card.combo_material),
                           ("安装形式", card.combo_installForm),
                           ("分体仪表支架", card.combo_bracket),
                           ("install", card.combo_install),
                           ("power", card.combo_power),
                           ("required_ex", card.combo_required_ex)):
            combo.setCurrentText(str(values[key] or ""))

        card.combo_c_family.setEditText(str(values["c_family"] or ""))
        card.combo_size.setEditText(str(values["台面尺寸"] or ""))
        card.combo_vibration.setCurrentText(
            "带搅拌" if values["vibration"] else "无搅拌")

        channels = values["special_req"]
        card.combo_channels.setCurrentText(
            "" if channels is None else "{}通道".format(channels))
        card.combo_battery.setCurrentText(
            "带电池" if values["special_req2"] else "")
        card.combo_req_com1.setCurrentText(str(values["req_com1"] or ""))
        # 结构化/解析产物里是规范名，下拉条目显示的是中文映射名：
        # 转显后再勾选，避免规范名对不上条目被忽略
        card.combo_req_com2.setCheckedItems([
            self._sync_parser.com2_display(name)
            for name in values["req_com2"]
        ])

    @staticmethod
    def _com1_option(codes):
        """req_com1 解析产物(规则码+字面串口列表) -> 串口通讯组合选项
        文本，供回填反推。缺省单一基础串口(未提及通讯)在 Parser 产出
        为全能力码集合且无字面协议，映射为未选；字面串口优先(RS232+
        RS485 组合即双串口需求)，纯 Modbus 按 RTU_2 独在/并存区分路数"""
        upper = {str(code).strip().upper() for code in (codes or [])}

        if not upper or upper == {"BASIC_1", "BASIC_2", "RTU_1", "RTU_2"}:
            return ""

        if "RS232" in upper and "RS485" in upper:
            return "RS232+RS485"
        if "RS232" in upper:
            return "RS232"
        if "RS485" in upper:
            return "RS485"

        if "RTU_2" in upper and "RTU_1" not in upper:
            return "Modbus（2路）"
        if "RTU_1" in upper or "MODBUS" in upper:
            return "Modbus"
        if "BASIC_2" in upper:
            return "RS232+RS485"
        return ""

    def _parse_descriptions(self, entries):
        # description 文本 -> 标准参数（Parser），在传 Engine 之前挂到条目上；
        # Engine 只接收标准参数，不接触原始文本。
        # 通讯缺省(req_com1)在此一并归一，使条目对上层计算完全自包含
        for entry in entries:
            parsed = self._parser.parse_quote_text(entry["description"])
            parsed["data"]["req_com1"] = (
                parsed["data"].get("req_com1")
                or self._parser.default_req_com1()
            )
            entry["parsed"] = parsed
        return entries

    def _collect_card_data(self):
        entries = []

        for i in range(self.cardContainerLayout.count()):
            item = self.cardContainerLayout.itemAt(i)

            if item is None:
                continue

            card = item.widget()

            if not isinstance(card, QuoteCard):
                continue

            entry = card.getEntryData()
            entry["quote_info"] = {
                "quote_id": card.quote_id,
                "quantity": card.spinBox.value()
            }
            # 现场服务为整单开关(Desk 按钮行 serviceCheckBox)，随每条entry透传，
            # Checklist 只读展示，Writer 按开关决定服务费行(数量1/次)写不写
            entry["onsite_service"] = self.serviceCheckBox.isChecked()
            entries.append(entry)

        return entries

    def collect_entries(self):
        """采集当前输入页签的全部条目并完成参数装配（快照导出等只读
        场景用）：输入框输入走 Parser 文本解析，下拉菜单输入由结构化
        取值直接装配标准参数，两条路径的条目对上层完全自包含"""
        if self._gui_tab_active():
            return self._collect_gui_data()

        entries = self._collect_card_data()
        return self._parse_descriptions(entries)

    def _collect_gui_data(self):
        """采集下拉菜单输入卡片条目：结构化取值就地装配 parsed
        (不经文本解析)，与输入框输入同一 entry 形状"""
        entries = []

        for i in range(self.guiCardContainerLayout.count()):
            item = self.guiCardContainerLayout.itemAt(i)

            if item is None:
                continue

            card = item.widget()

            if not isinstance(card, GuiCard):
                continue

            entry = card.getEntryData()
            entry["quote_info"] = {
                "quote_id": card.quote_id,
                "quantity": card.spinBox.value()
            }
            # 现场服务为整单开关(Desk 按钮行 serviceCheckBox)，随每条entry透传，
            # Checklist 只读展示，Writer 按开关决定服务费行(数量1/次)写不写
            entry["onsite_service"] = self.serviceCheckBox.isChecked()
            entry["parsed"] = self._gui_structured_to_parsed(
                entry["structured"]
            )
            entries.append(entry)

        return entries

    def _gui_structured_to_parsed(self, structured):
        """GUI 结构化取值 -> 条目 parsed(标准参数 + 识别诊断)，与文本解析
        输出同构：只登记显式选择的参数，缺省语义交 build_engine_input/
        EngineService 兜底；req_com1 空选与文本录入同一缺省(单一基础串口)"""
        data = {}
        recognized = []

        def put(param_id, value):
            # 空选(None/空串/False/空列表)=未提及，不登记；
            # 0 为显式填写值(RPM)，照常登记
            if value is None or value == "" or value is False or value == []:
                return

            data[param_id] = value
            recognized.append({
                "text": "",
                "parameter": param_id,
                "term": str(value),
                "source": "gui",
                "value": value,
            })

        put("W1", structured.get("W1"))
        put("W2", structured.get("W2"))
        put("support", structured.get("support"))
        put("m_brand", structured.get("m_brand"))
        put("c_brand", structured.get("c_brand"))
        put("c_family", structured.get("c_family"))
        put("material", structured.get("material"))
        put("台面尺寸", structured.get("台面尺寸"))
        put("e_input", structured.get("e_input"))
        put("r_input", structured.get("r_input"))

        if structured.get("vibration"):
            put("vibration", True)
            put("RPM", structured.get("RPM"))

        put("安装形式", structured.get("安装形式"))
        put("分体仪表支架", structured.get("分体仪表支架"))
        put("install", structured.get("install"))
        put("power", structured.get("power"))

        # 多通道语义：special_req >=2 才登记(单通道/空选同义于默认单通道)
        channels = structured.get("special_req") or 0

        if channels >= 2:
            put("special_req", channels)

        put("special_req2", structured.get("special_req2"))
        put("required_ex", structured.get("required_ex"))

        # 基础串口：组合选项 -> 与文本解析同一推导链；空选取缺省
        com1_text = structured.get("req_com1") or ""
        protocols, modbus_count = _GUI_COM1_OPTIONS.get(com1_text, ((), 0))
        acceptable = self._parser.derive_req_com1(protocols, modbus_count)

        if acceptable is None:
            acceptable = self._parser.default_req_com1()

        data["req_com1"] = acceptable
        recognized.append({
            "text": "",
            "parameter": "req_com1",
            "term": com1_text or "缺省(单一基础串口)",
            "source": "gui",
            "value": acceptable,
        })

        # 扩展通讯：下拉取值为显示名(模拟量4-20mA 等)，先还原规范名
        # 再入参——显示层只影响展示，不影响选型输入
        put("req_com2", [
            self._sync_parser.com2_canonical(name)
            for name in (structured.get("req_com2") or [])
        ])

        return {
            "data": data,
            "recognized": recognized,
            "unrecognized": [],
            "warnings": [],
        }

    def restore_entries(self, entries, onsite_service=False):
        """从快照条目重建卡片（「打开快照」）：清空两页签现有卡片后
        按快照逐条同步重建并配对，快照值写入文本卡片后经镜像信号
        自动同步到下拉卡片；描述解析仍延后到发起选型时，与手工录入
        同一数据路径"""
        for layout in (self.cardContainerLayout,
                       self.guiCardContainerLayout):
            while layout.count():
                layout_item = layout.takeAt(0)

                if layout_item is None:      # itemAt 越界/空槽位返回 None，防御收敛
                    continue

                widget = layout_item.widget()

                if widget is not None:
                    widget.deleteLater()

        self.cardIndex = 0
        self.guiCardIndex = 0

        for entry in entries:
            self.add_card()
            self.add_gui_card()
            self._pair_last_cards()

            item = self.cardContainerLayout.itemAt(
                self.cardContainerLayout.count() - 1)

            if item is None:      # itemAt 越界/空槽位返回 None，防御收敛
                continue

            card = item.widget()

            if not isinstance(card, QuoteCard):
                continue

            card.comboBox.setCurrentText(entry.get("item_type") or "")

            try:
                card.spinBox.setValue(int(entry.get("quantity") or 1))
            except (TypeError, ValueError):
                card.spinBox.setValue(1)

            card.checkBox.setChecked(bool(entry.get("metrology")))
            card.checkBox_2.setChecked(bool(entry.get("high_precision")))
            card.checkBox_3.setChecked(bool(entry.get("Ex_P")))
            card.checkBox_4.setChecked(bool(entry.get("digital")))
            card.plainTextEdit.setPlainText(entry.get("description") or "")

        self.serviceCheckBox.setChecked(bool(onsite_service))
        # 快照条目为文本录入格式：恢复后切回输入框输入页签
        self.inputTabs.setCurrentIndex(0)
        self._refresh_scroll_area()
        self._refresh_scroll_area(self.guiScrollArea)

    def _print_entries(self, entries):
        for entry in entries:
            quote_info = entry["quote_info"]
            print("=" * 40)
            print("quote_id: {}".format(quote_info["quote_id"]))
            print("数量: {}".format(quote_info["quantity"]))
            print("条目类型: {}".format(entry["item_type"]))
            print("输入方式: {}".format(
                "下拉菜单输入" if entry.get("input_mode") == "gui"
                else "输入框输入"
            ))
            print("是否需要检定: {}".format("是" if entry["metrology"] else "否"))
            print("是否高精度: {}".format("是" if entry["high_precision"] else "否"))
            print("是否防爆: {}".format("是" if entry["Ex_P"] else "否"))
            print("是否数字化: {}".format("是" if entry.get("digital") else "否"))
            print("其他条目需求: {}".format(entry["description"]))

            parsed = entry.get("parsed")
            if parsed is not None:
                for item in parsed["recognized"]:
                    print("已识别：{} <- [{}|{}] {} = {}".format(
                        item["parameter"], item["term"], item["source"],
                        item["text"] or "(推断)", item["value"]
                    ))
                for text in parsed["unrecognized"]:
                    print("未识别：{}".format(text))
                for warning in parsed["warnings"]:
                    print("警告：[{}] {} ({})".format(
                        warning["parameter"], warning["text"],
                        warning["reason"]
                    ))
                print("解析参数: {}".format(parsed["data"]))

        print("=" * 40)
        print("共 {} 个条目".format(len(entries)))


if __name__ == "__main__":
    # 独立运行调试：本地 EngineService 同步执行选型(结果打印到控制台)
    app = QApplication([])
    window = Desk()
    service = EngineService()
    window.selectionRequested.connect(service.run_batch)
    window.show()
    app.exec()