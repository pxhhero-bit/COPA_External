"""COPA_com_Checklist v2.2, 选型清单窗口 by Hero Pang.
承接 Desk/Engine 的选型结果：容器内按 quote_id(Desk 传 Engine 时定下的编号)升序
逐条显示 QuoteListItem；listitem 的标签/显隐随 module/platform/bench 等业务 pipeline 实时切换；
engine 回传多个选型选项时，各产品 combobox 据结果构建下拉选项供人工确认。


v1.5 起 Checker/Diagnostic 模块挂起：自动解决方案与诊断徽章相关代码注释停用，
Diagnostic.missing_models(选型数据缺失提示)迁入本模块并改为 CLI 输出。"""
import csv
import functools
import os
import sys

# 直接以脚本方式运行时，把项目根目录加入 sys.path，使 COPA 包可以常规导入
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

# import Checker      # v1.5: Checker 模块挂起，恢复时取消注释
# import Diagnostic   # v1.5: Diagnostic 模块挂起，missing_models 已迁入本模块
from COPA.apps import Writer, app_icon
from COPA.apps.Ui_quoteChecklist import Ui_quoteChecklist
from COPA.apps.Ui_quoteListItem import Ui_Form as Ui_QuoteListItem
from COPA.apps.Ui_secDisplay import Ui_secDisplay
from COPA.engine import engine

# engine内部码 -> listitem类型下拉的中文名
_TYPE_NAMES = {
    "module": "称重模块",
    "platform": "平台秤",
    "bench": "台秤",
    "truck_A": "汽车衡",
    "truck_D": "数字汽车衡",
}

# 中文名 -> engine内部码(输出报价时反向解析)
_TYPE_CODES = {name: code for code, name in _TYPE_NAMES.items()}

# langComBox 选项 -> 输出语言码(英文走 *_英文版 模板)
_LANG_CODES = {"中文": "zh", "英文": "en"}

# 附件下拉(1/2/3共用，选项一致可重复选)按业务类型动态构建；「无」= 不选该附件
_ACCESSORY_OPTIONS = {
    "称重模块": ["上过渡板", "下过渡板", "大屏幕", "防爆大屏幕"],
    "平台秤": ["分体式仪表立杆", "一体式仪表立杆", "引坡",
               "分体式预埋框", "一体式预埋框", "大屏幕", "防爆大屏幕"],
    "台秤": ["移动小车", "分体式仪表立杆"],
}

# 各业务pipeline的标签配置：值为None的行隐藏(如台秤整机选型无传感器/接线盒下拉；
# 衍生品种行仅平台秤/台秤开放，汽车衡类与模块业务隐藏)
_PIPELINE_LABELS = {
    "称重模块": {
        "product": "模块型号：", "sensor": "传感器型号：", "jbox": "接线盒型号：",
        "controller": "仪表型号：", "install": "仪表安装方式：", "unit": "套",
    },
    "平台秤": {
        "product": "平台秤型号：", "sensor": "传感器型号：", "jbox": "接线盒型号：",
        "controller": "仪表型号：", "install": "仪表安装方式：", "unit": "台",
        "derivative": "衍生品种：",
    },
    "台秤": {
        "product": "台秤型号：", "sensor": None, "jbox": None,
        "controller": "仪表型号：", "install": "仪表支架：", "unit": "台",
        "derivative": "衍生品种：",
    },
    "汽车衡": {
        "product": "汽车衡型号：", "sensor": "传感器型号：", "jbox": "接线盒型号：",
        "controller": "仪表型号：", "install": None, "unit": "台",
    },
    "数字汽车衡": {
        "product": "数字式汽车衡型号：", "sensor": "传感器型号：", "jbox": "接线盒型号：",
        "controller": "仪表型号：", "install": None, "unit": "台",
    },
}

# 输出前必检字段(附件1/2/3除外)；第二列对应 _PIPELINE_LABELS 的配置键
_NECESSARY_FIELDS = (
    ("productComBox", "product"),
    ("sensorComBox", "sensor"),
    ("jBoxComBox", "jbox"),
    ("controllerComboBox_1", "controller"),
    ("controllerComBox_2", "install"),
)


# ---------------------------------------------------------------------------
# 选型数据缺失调试：自 Diagnostic v1.0 迁入(Diagnostic 模块挂起期由本模块承接)，
# 结果改为 CLI(控制台)输出，不再驱动 GUI 徽章
# ---------------------------------------------------------------------------

# 模块业务四类型号 -> engine结果取值判定是否为空
_MODULE_MODEL_CHECKS = (
    ("传感器", lambda r: r.get("sensor") or []),
    ("模块", lambda r: r.get("module") or []),
    ("接线盒", lambda r: r.get("jbox") and [r["jbox"]] or []),
    ("仪表", lambda r: r.get("controller") or []),
)


def missing_models(result):
    """模块业务下传感器/模块/接线盒/仪表有空缺时返回缺项名列表，否则空列表。
    传感器与模块共用 engine 的 module 组合列表：上游传感器为空则两者皆空。"""
    if not isinstance(result, dict) or result.get("item_type") != "module":
        return []

    missing = []
    sensor_empty = not (result.get("sensor") or {}).get("sensors")

    for name, getter in _MODULE_MODEL_CHECKS:
        if name == "传感器" and sensor_empty:
            missing.append(name)
        elif name == "模块" and not getter(result):
            missing.append(name)
        elif name in ("接线盒", "仪表") and not getter(result):
            missing.append(name)

    return missing


def format_missing_models(results):
    """engine结果列表 -> CLI缺项报告文本；按 quote_id 升序，无缺项返回空串"""
    lines = []

    for result in sorted(results or [],
                         key=lambda r: r.get("quote_id") or 0):
        missing = missing_models(result)

        if missing:
            lines.append("条目 {}：{}".format(
                result.get("quote_id", "?"), "、".join(missing)))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 衍生品种映射：data/衍生品种映射.csv 是品种下拉选项与型号解析的唯一来源
# (列：业务类型/品牌/品种名称/基础family/衍生family/备注)。产品编码变化时只
# 维护该表；品种仅替换型号的 family 段(如 FTPD-S-003-0606 -> FTPE-S-003-0606)，
# 材质/量程/台面段与传感器等其余选型不受影响。
# ---------------------------------------------------------------------------

# 冻结打包后 data 随 exe 同目录摆放；源码运行时按本文件位置上溯定位
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_VARIANT_CSV = os.path.join(_ROOT_DIR, "data", "衍生品种映射.csv")

# 品种下拉的默认项：不衍生，输出基础型号
_STANDARD_VARIANT = "标准型"


def load_variants(path=_VARIANT_CSV):
    """衍生品种映射表 -> {业务类型中文: [{brand, name, from_family, to_family}...]}。
    文件缺失/无行时返回空dict：品种下拉仅剩标准型，行为等同 v1.0。
    读取用 utf-8-sig，兼容 Excel 另存时带 BOM 的表。"""
    table = {}

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ptype = (row.get("业务类型") or "").strip()
                name = (row.get("品种名称") or "").strip()

                if not ptype or not name:
                    continue

                table.setdefault(ptype, []).append({
                    "brand": (row.get("品牌") or "").strip(),
                    "name": name,
                    "from_family": (row.get("基础family") or "").strip(),
                    "to_family": (row.get("衍生family") or "").strip(),
                })
    except OSError:
        pass

    return table


_VARIANTS = load_variants()


# ---------------------------------------------------------------------------
# 大屏幕选型：附件选「大屏幕/防爆大屏幕」后弹子对话框(Ui_secDisplay)，按
# 品牌+防爆分流前缀(FT→FTRDL仅非防爆、AW→AWRL/AWRD)，确认时读取各段下拉
# 编译出具体型号，带出到 listitem 的大屏幕型号行，输出按该型号落行
# ---------------------------------------------------------------------------

_DISPLAY_OPTIONS = ("大屏幕", "防爆大屏幕")

# 支架类型(防尘式仪表专用；无支架不落任何前缀)
_BRACKETS = ("立杆支架", "壁挂支架")


class DisplayDialog(QDialog, Ui_secDisplay):
    """大屏幕选型子对话框。编译规则：各段下拉取文本首位字符、按
    尺寸-颜色-通讯-[协议-通道]-电源 拼接；FT 无协议/通道段且尺寸补前导0
    (3->03)；多通道仪表时协议仅F、通道仅4(命名规则：多通道仪表选F4)。"""

    # (品牌, 防爆入口) -> 型号前缀；FT 只有非防爆，AW 防爆/非防爆由入口决定
    _PREFIX = {("FT", False): "FTRDL", ("AW", False): "AWRL", ("AW", True): "AWRD"}

    def __init__(self, ex, current="", channels=1, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._ex = ex
        self._model = ""
        self.setWindowTitle("防爆大屏幕选型" if ex else "大屏幕选型")

        # 品牌分流：防爆入口仅AW可选；普通入口 FT/AW 皆可(FT 恒非防爆)
        self.brandComBox.blockSignals(True)
        self.brandComBox.clear()

        for brand in (["AW"] if ex else ["FT", "AW"]):
            self.brandComBox.addItem(
                "FT (富林泰克)" if brand == "FT" else "AW (COPA A)", brand)

        self.brandComBox.blockSignals(False)
        self.brandComBox.currentTextChanged.connect(self._on_brand_changed)
        self._on_brand_changed(self.brandComBox.currentText())

        # 多通道仪表：协议仅可选F、通道仅可选4
        if channels > 1:
            self._filter_items(self.comPotComBox, ("F",))
            self._filter_items(self.comChenComBox, ("4",))

        self._apply_current(current)
        self.pushButton.clicked.connect(self._compose_and_accept)

    # ====分流与联动====

    def _on_brand_changed(self, _text):
        is_ft = self.brandComBox.currentData() == "FT"

        # FT无协议/通道段：隐藏对应标签与下拉
        for widget in (self.label_6, self.comPotComBox,
                       self.label_7, self.comChenComBox):
            widget.setVisible(not is_ft)

    @staticmethod
    def _filter_items(combo, keys):
        """仅保留首位字符命中 keys 的选项"""
        keys = set(keys)

        for i in range(combo.count() - 1, -1, -1):

            if combo.itemText(i).lstrip()[:1] not in keys:
                combo.removeItem(i)

    # ====型号编译(确认时触发)====

    def _compose_and_accept(self):
        is_ft = self.brandComBox.currentData() == "FT"
        prefix = self._PREFIX[("FT" if is_ft else "AW", self._ex)]
        size = self.sizeComBox.currentText().strip()

        if is_ft and len(size) == 1:
            size = "0" + size            # FT 尺寸两位(3 -> 03)

        def head(combo):
            return combo.currentText().strip()[:1]

        segments = [size, head(self.colorComBox), head(self.comComBox)]

        if not is_ft:
            segments += [head(self.comPotComBox), head(self.comChenComBox)]

        segments.append(head(self.powerComBox))
        self._model = "{}-{}".format(prefix, "".join(segments))
        self.accept()

    # ====回填====

    def _apply_current(self, model):
        """打开时按已有具体型号回填各下拉(前缀-尺寸..逐位匹配，尽力解析)"""
        prefix, _, tail = (model or "").strip().partition("-")

        if prefix not in self._PREFIX.values():
            return

        brand = "FT" if prefix == "FTRDL" else "AW"
        index = self.brandComBox.findData(brand)

        if index >= 0:
            self.brandComBox.setCurrentIndex(index)

        size = ""

        while tail[:1].isdigit():
            size += tail[:1]
            tail = tail[1:]

        if size:
            index = self.sizeComBox.findText(size)

            if index < 0 and size.startswith("0"):
                index = self.sizeComBox.findText(size[1:])

            if index >= 0:
                self.sizeComBox.setCurrentIndex(index)

        for combo in (self.colorComBox, self.comComBox,
                      self.comPotComBox, self.comChenComBox,
                      self.powerComBox):
            char, tail = tail[:1], tail[1:]

            if not char:
                break

            for i in range(combo.count()):

                if combo.itemText(i).lstrip()[:1] == char:
                    combo.setCurrentIndex(i)
                    break

    @classmethod
    def select(cls, ex, current="", channels=1, parent=None):
        """弹窗选型 -> (是否确认, 编译出的具体型号)"""
        dialog = cls(ex, current=current, channels=channels, parent=parent)
        ok = dialog.exec() == QDialog.DialogCode.Accepted
        return ok, dialog._model


class QuoteListItem(QWidget, Ui_QuoteListItem):

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # 状态复选框(检定/高精度/防爆)只读展示：状态由 Desk 卡片经
        # load_result 的 setChecked 写入，不允许清单内修改。
        # 必须保持 checkable——Ui 里的 setCheckable(False) 会让 setChecked
        # 失效、指示框也不画(Desk状态带不进来)，在此改回；只读用
        # 无焦点+鼠标穿透实现，观感与普通复选框一致
        for checkbox in (self.metroCheckBox, self.highPresCheckBox,
                         self.exCheckBox, self.digiCheckBox):
            checkbox.setCheckable(True)
            checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            checkbox.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 边框参照 Desk 卡片：QWidget 样式表描边需显式开启 StyledBackground
        self.setObjectName("QuoteListItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#QuoteListItem { border: 1px solid black; }")

        # engine原始结构化结果(load_result时保存)，供输出报价回查支点数等
        self._result = None

        # Desk解析出的标准参数(W1/W2/support等，load_result时保存)，
        # 输出报价时分项段header的重量/支点数据来源
        self._params = {}

        # 快照恢复的原始条目数据(load_snapshot_item 时保存)：重输出时
        # 回填快照留存的安装前缀与量程/分度值(无 engine 结果可查)
        self._snapshot_restore = None

        # 衍生品种机制状态：基础产品文本记忆 + 程序改写产品文本的信号屏蔽标志
        self._base_product = None
        self._product_sync = False

        # 类型下拉切换时实时重排标签/显隐/附件选项
        self.comboBox.currentTextChanged.connect(self._apply_pipeline)
        self._apply_pipeline(self.comboBox.currentText())

        # 产品下拉(不可编辑)：模块业务仅显示单项、随传感器联动；
        # 平台秤/台秤为engine候选列表，人工从下拉确认
        self.productComBox.currentTextChanged.connect(self._on_product_changed)

        # 传感器选择 -> 模块型号实时跟随
        self.sensorComBox.currentTextChanged.connect(self._on_sensor_changed)
        self.derivativeComBox.currentTextChanged.connect(self._on_variant_changed)

        # 附件选大屏幕类 -> 弹选型子对话框；任何附件变化同步大屏幕型号行显隐
        # (partial 显式携带对应下拉，避免 sender() 的 QObject 类型不确定)
        for combo in (self.accessoryComBox_1, self.accessoryComBox_2,
                      self.accessoryComBox_3):
            combo.currentTextChanged.connect(
                functools.partial(self._on_accessory_changed, combo))

        # 安装方式(支架)选择 -> 收窄仪表下拉选项组并影响输出描述前缀
        self.controllerComBox_2.currentTextChanged.connect(
            self._on_install_changed)
        self._bracket_models = set()

        # 首次 _apply_pipeline 早于附件接线，这里补一次大屏幕型号行初始显隐
        self._sync_display_row()

    def set_quote_id(self, quote_id):
        self.label_ID.setText("{}".format(quote_id))

    def result(self):
        """engine原始结构化结果(load_result时保存)，供诊断控件/输出报价读取"""
        return self._result

    def _apply_pipeline(self, type_text):
        config = _PIPELINE_LABELS.get(type_text)

        if config is None:
            return

        self.unitLb.setText(config["unit"])

        for key, label, combo in (
            ("product", self.productLb, self.productComBox),
            ("sensor", self.sensorLb, self.sensorComBox),
            ("jbox", self.jBoxLb, self.jBoxComBox),
            ("controller", self.controllerLb, self.controllerComboBox_1),
            ("install", self.controllerLb_2, self.controllerComBox_2),
            ("derivative", self.derivativeLb, self.derivativeComBox),
        ):
            text = config.get(key)
            label.setVisible(text is not None)
            combo.setVisible(text is not None)

            if text is not None:
                label.setText(text)

        # 附件下拉1/2/3：同一套选项，可重复选择；未配置的业务(汽车衡类)仅「无」
        for combo in (self.accessoryComBox_1,
                      self.accessoryComBox_2,
                      self.accessoryComBox_3):
            combo.clear()
            combo.addItems(["无"] + _ACCESSORY_OPTIONS.get(type_text, []))

        self._rebuild_derivative_options(config)

    # ====衍生品种====

    def _rebuild_derivative_options(self, config):
        """按当前业务类型重建衍生品种下拉。类型无衍生行时清空选择。"""
        if config.get("derivative") is None:
            self.derivativeComBox.blockSignals(True)
            self.derivativeComBox.setCurrentIndex(-1)
            self.derivativeComBox.blockSignals(False)
            return

        self._fill_derivative_options()

    def _on_product_changed(self, text):
        """用户改选/手改产品型号 -> 记忆为基础文本；衍生行开放时按新family重筛品种"""
        if self._product_sync:
            return

        self._base_product = text

        if not self.derivativeLb.isHidden():
            self._fill_derivative_options()

    def _on_variant_changed(self):
        if self.derivativeLb.isHidden():
            return

        self._apply_derivative()

    def _fill_derivative_options(self):
        """重建衍生品种下拉选项：标准型 + 适用于基础型号 family 的品种
        (衍生改写不落在基础文本上，family 恒取 _base_product)。
        被过滤掉的原选择回退标准型(CLI提示)；重建期间屏蔽信号防抖。"""
        base = self._base_model()
        family = base.split("-")[0] if base else ""
        entries = [v for v in _VARIANTS.get(self.comboBox.currentText(), [])
                   if not family or v["from_family"] == family]
        names = [_STANDARD_VARIANT] + [v["name"] for v in entries]
        current = self.derivativeComBox.currentText()

        if current and current != _STANDARD_VARIANT and current not in names:
            print("[Checklist] 报价项目 {}：品种「{}」不适用于基础型号 {}，已回退标准型".format(
                self.label_ID.text(), current, base or "(空)"))

        self.derivativeComBox.blockSignals(True)
        self.derivativeComBox.clear()
        self.derivativeComBox.addItems(names)
        self.derivativeComBox.setCurrentText(
            current if current in names else _STANDARD_VARIANT)
        self.derivativeComBox.blockSignals(False)
        self._apply_derivative()

    def _apply_derivative(self):
        """按当前品种实时改写产品下拉文本：标准型还原基础型号，衍生品种替换
        family 段(量程/台面说明后缀原样保留)。型号段的最终裁决权在产品下拉
        (可手改)，本方法只做品种驱动的自动改写。"""
        variant = self.derivativeComBox.currentText().strip()

        if not variant or variant == _STANDARD_VARIANT:
            if self._base_product is not None:
                self._set_product_text(self._base_product)
            return

        base = self._base_product or ""
        base_model = base.split(" ")[0].strip()

        if not base_model:
            return

        parts = base_model.split("-")
        entry = next(
            (v for v in _VARIANTS.get(self.comboBox.currentText(), [])
             if v["name"] == variant and v["from_family"] == parts[0]), None)

        if entry is None:
            print("[Checklist] 报价项目 {}：品种「{}」不适用于基础型号 {}，已回退标准型".format(
                self.label_ID.text(), variant, base_model))
            self.derivativeComBox.setCurrentText(_STANDARD_VARIANT)
            return

        derived = "-".join([entry["to_family"]] + parts[1:])
        suffix = base[len(base_model):]      # " (量程300kg 台面600x600)" 等说明后缀
        self._set_product_text(derived + suffix)

    def _set_product_text(self, text):
        """程序改写产品下拉当前文本(改写当前条目而非 setCurrentText，兼容
        不可编辑模式)：屏蔽信号，避免触发 _on_product_changed 回环"""
        self._product_sync = True

        try:
            if self.productComBox.count() == 0:
                self.productComBox.addItem(text)

            self.productComBox.setItemText(
                self.productComBox.currentIndex(), text)
        finally:
            self._product_sync = False

    def _base_model(self):
        """基础型号段(去掉量程/台面说明后缀)；衍生状态下取记忆的基础文本"""
        return (self._base_product or self.productComBox.currentText()
                ).split(" ")[0].strip()

    def derivative_info(self):
        """当前衍生选择摘要(CLI回显用)；未衍生时返回None。
        产品下拉文本即最终输出型号，人工可直接修改。"""
        if self.derivativeLb.isHidden():
            return None

        variant = self.derivativeComBox.currentText().strip()

        if not variant or variant == _STANDARD_VARIANT:
            return None

        model = self.productComBox.currentText().split(" ")[0].strip()
        base = self._base_model()

        if model and base:
            return {"variant": variant, "base": base, "model": model}

        return None

    # ====大屏幕附件====

    def _on_accessory_changed(self, combo, text):
        """附件选择变化：选大屏幕/防爆大屏幕 -> 弹子对话框定具体型号，
        取消则该附件框退回「无」；任何变化后同步大屏幕型号行显隐。"""
        text = (text or "").strip()

        if text in _DISPLAY_OPTIONS:
            ok, model = DisplayDialog.select(
                ex=text == "防爆大屏幕",
                current=self.displayEdit.text().strip(),
                channels=self._controller_channels(),
                parent=self,
            )

            if ok and model:
                self.displayEdit.setText(model)

                if not Writer.lookup_desc(model):
                    print("[Checklist] 报价项目 {}：大屏幕「{}」未在描述通表中，输出描述为空".format(
                        self.label_ID.text(), model))
            else:
                combo.setCurrentText("无")

        self._sync_display_row()

    def _sync_display_row(self):
        """大屏幕型号行：任一附件框选着大屏幕类附件时显示，否则隐藏并清空"""
        selected = any(
            c.currentText().strip() in _DISPLAY_OPTIONS
            for c in (self.accessoryComBox_1, self.accessoryComBox_2,
                      self.accessoryComBox_3))
        self.displayLb.setVisible(selected)
        self.displayEdit.setVisible(selected)

        if not selected:
            self.displayEdit.clear()

    def _controller_channels(self):
        """当前选定仪表的通道数：大屏幕选型默认协议依据(单通道M1/多通道F4)"""
        info = Writer.lookup_instrument(
            self.controllerComboBox_1.currentText().strip())
        return info["channels"] if info else 1

    # ====结果装载====

    def load_result(self, result, quantity=None,
                    metrology=False, high_precision=False, ex_p=False,
                    digi=False, params=None):
        """将单条engine选型结果装入listitem；quantity/复选框状态来自Desk卡片条目；
        params 为 Desk 解析出的标准参数(W1/W2/support等)，输出报价时分项段header用"""
        self._result = result
        self._params = params or {}
        self.set_quote_id(result.get("quote_id") or 0)

        if quantity is not None:
            self.qtyBox.setText(str(quantity))

        self.metroCheckBox.setChecked(metrology)
        self.highPresCheckBox.setChecked(high_precision)
        self.exCheckBox.setChecked(ex_p)
        self.digiCheckBox.setChecked(digi)

        code = result.get("item_type") or ""
        self.comboBox.setCurrentText(_TYPE_NAMES.get(code, code))

        if result.get("status") == "ERROR":
            self._fill(self.productComBox, [
                "选型失败：{}".format(result.get("error", ""))
            ])
            return

        loaders = {
            "module": self._load_module,
            "platform": self._load_platform,
            "bench": self._load_bench,
        }
        loader = loaders.get(code)

        if loader is not None:
            loader(result)

    def load_snapshot_item(self, data):
        """从快照条目JSON(build_item 输出 + 快照状态表字段)恢复单条已确认
        选型：各下拉直接装配为快照值。_result 恒为 None——依赖 engine 结果
        的联动(传感器->模块联动/支架收窄)不会触发，快照值即最终值。
        平台秤的传感器候选不在快照记录范围，相应下拉留空(输出预检会提示)。
        快照数据留存 _snapshot_restore：重输出时回填安装前缀与量程/分度值"""
        self._snapshot_restore = data
        saved_header = data.get("header") or {}
        self._params = {"W1": saved_header.get("W1"),
                        "W2": saved_header.get("W2")}
        self.set_quote_id(data.get("quote_id") or 0)
        self.qtyBox.setText(str(data.get("qty") or 1))
        self.metroCheckBox.setChecked(bool(data.get("metrology")))
        self.highPresCheckBox.setChecked(bool(data.get("high_precision")))
        self.exCheckBox.setChecked(bool(data.get("ex")))
        self.digiCheckBox.setChecked(bool(data.get("digital")))

        code = data.get("type") or ""
        self.comboBox.setCurrentText(_TYPE_NAMES.get(code, code))

        product = ""

        if code == "module":
            product = (data.get("module") or [""])[0]
        elif code == "platform":
            product = data.get("platform") or ""
        elif code == "bench":
            product = data.get("bench") or ""

        if product:
            self._fill(self.productComBox, [product])

        if code == "module":
            tokens = product.split(" ")

            if len(tokens) > 2:
                self._fill(self.sensorComBox, [" ".join(tokens[2:])])

        if data.get("jbox"):
            self._fill(self.jBoxComBox, [data["jbox"]])

        if data.get("controller"):
            self._fill(self.controllerComboBox_1, [data["controller"]])

        install = data.get("controller_install") or ""
        bracket = ("立杆支架" if install.startswith("立杆")
                   else "壁挂支架" if install.startswith("壁挂") else "")

        if bracket:
            combo = self.controllerComBox_2

            if combo.findText(bracket) < 0:
                combo.addItem(bracket)

            combo.setCurrentText(bracket)

        # 附件/大屏幕：屏蔽信号装配，避免触发大屏幕选型子对话框；
        # 下拉选项集由 _apply_pipeline 按类型重建，快照值缺失时补入
        combos = (self.accessoryComBox_1, self.accessoryComBox_2,
                  self.accessoryComBox_3)

        for combo, value in zip(combos, data.get("accessories") or []):
            if not value:
                continue

            if combo.findText(value) < 0:
                combo.addItem(value)

            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)

        if data.get("display"):
            combo = self.accessoryComBox_1

            if combo.findText("大屏幕") < 0:
                combo.addItem("大屏幕")

            combo.blockSignals(True)
            combo.setCurrentText("大屏幕")
            combo.blockSignals(False)
            self.displayEdit.setText(data["display"])
            self._sync_display_row()

    def _on_sensor_changed(self, text):
        """传感器选择 -> 模块型号行实时跟随(匹配该传感器的首个模块组合)。
        产品行为只读展示，模块业务的实际选择权在传感器下拉。
        联动池先查按用户材质收敛的推荐组合(module)，未命中再查自由
        搭配候选(module_free，不限材质)——下拉已是engine全量传感器，
        跨材质组合也如实带出"""
        if self._result is None:
            return

        if _TYPE_CODES.get(self.comboBox.currentText()) != "module":
            return

        result = self._result or {}
        pairs = (result.get("module") or []) + (result.get("module_free") or [])

        for m in pairs:
            if self._sensor_option_text(m["sensor"]) == text:
                self._set_product_text(self._format_module_option(m))
                return

        # 所选传感器无任何兼容模块(family/防爆/孔距均未命中)：如实提示
        self._set_product_text("无匹配模块")

    def _load_module(self, result):
        module_items = result.get("module") or []
        # 传感器下拉直接采用 engine 选型结果(EX/SF 通过的全量传感器，已按
        # 贴近最优SF排序)，不再从配对结果反推——模块材质筛选不影响传感器
        # 可见性(如 AW 的 AWB/AWBS 跨材质变体)；旧结构无传感器结果时回退
        # 配对结果导出
        sensor_rows = ((result.get("sensor") or {}).get("sensors")) or []

        if sensor_rows or module_items:
            source = sensor_rows or [m["sensor"] for m in module_items]
            # 传感器下拉去重(多组合可能共用传感器)；同family不同Y值/不同防爆
            # 状态是不同选型，去重键须带上。填充后模块型号行随传感器联动
            sensors = []
            seen = set()

            for s in source:
                key = (s["family型号"], s["capacity容量"],
                       s["AC准确度等级"], str(s.get("Y值") or ""),
                       self._sensor_is_ex(s))

                if key in seen:
                    continue
                seen.add(key)
                sensors.append(self._sensor_option_text(s))

            self._fill(self.sensorComBox, sensors)
            self._on_sensor_changed(self.sensorComBox.currentText())
        else:
            self._fill(self.productComBox, ["无匹配"])
            self._fill(self.sensorComBox, ["无匹配"])

        jbox = result.get("jbox")
        self._fill(
            self.jBoxComBox,
            [jbox["model型号"]] if jbox else ["无匹配"]
        )
        self._load_controllers(result)

    def _load_platform(self, result):
        rows = result.get("platform") or []
        self._fill(self.productComBox, [
            "{} (量程{}kg 台面{})".format(
                p["platform"]["具体型号"],
                p["platform"]["量程"],
                p["platform"]["台面尺寸"],
            ) for p in rows
        ] or ["无匹配"])

        sensors = []

        for p in rows:
            for s in p.get("sensors") or []:
                if s not in sensors:
                    sensors.append(s)

        self._fill(self.sensorComBox, sensors or ["无匹配"])

        jbox = result.get("jbox")
        self._fill(
            self.jBoxComBox,
            [jbox["model型号"]] if jbox else ["无匹配"]
        )
        self._load_controllers(result)

    def _load_bench(self, result):
        rows = result.get("bench") or []
        self._fill(self.productComBox, [
            "{} (量程{}kg 台面{})".format(
                r["具体型号"], r["量程"], r["台面尺寸"],
            ) for r in rows
        ] or ["无匹配"])
        self._load_controllers(result)

    def _load_controllers(self, result):
        controllers = result.get("controller") or []
        self._fill(
            self.controllerComboBox_1,
            [c["详细型号"] for c in controllers] or ["无匹配"]
        )

        code = _TYPE_CODES.get(self.comboBox.currentText())

        if code == "bench":
            # 台秤：engine行的支架值(FT230 立杆/壁挂)即选项，沿用原语义
            installs = []

            for c in controllers:
                value = (c.get("支架") or c.get("安装方式") or "").strip()

                if value and value not in installs:
                    installs.append(value)

            self._fill(self.controllerComBox_2, installs or ["无匹配"])
            return

        # 模块/平台秤：安装方式语义为支架选择——engine结果含防尘式仪表
        # (或描述带支架关键词)时 [壁挂支架(默认), 立杆支架, 无支架]，否则仅无支架
        capable = any(self._bracket_capable(c) for c in controllers)
        self._fill(self.controllerComBox_2,
                   ["壁挂支架", "立杆支架", "无支架"] if capable else ["无支架"])

    # ====安装方式(支架)====

    @staticmethod
    def _bracket_capable(row):
        """仪表是否支架可选：engine行安装方式为防尘式(第一依据)，
        或品牌通表描述带支架关键词(AW系列兜底)"""
        if (row.get("安装方式") or "").strip() == "防尘式":
            return True

        desc = Writer.lookup_desc((row.get("详细型号") or "").strip())
        return "立杆支架" in desc or "壁挂支架" in desc

    def _on_install_changed(self, _text):
        if self._result is None:
            return

        self._apply_bracket()

    def _apply_bracket(self):
        """安装方式(支架)选择 -> 收窄仪表下拉选项组：支架可选的AW型号换对应
        支架尾码变体(品牌通表数据校验)，FT/FAB与其他型号原样；无支架=原始型号。
        当前选择随档位映射到对应变体，手输型号保留。"""
        code = _TYPE_CODES.get(self.comboBox.currentText())

        if code not in ("module", "platform"):
            return

        bracket = self.controllerComBox_2.currentText().strip()
        controllers = (self._result or {}).get("controller") or []
        current = self.controllerComboBox_1.currentText().strip()
        options = []
        rewritten = {}                      # 原型号 -> 当前档位型号
        self._bracket_models = set()

        for c in controllers:
            model = (c.get("详细型号") or "").strip()

            if not model:
                continue

            if bracket in _BRACKETS and self._bracket_capable(c):
                model = Writer.bracket_variant(model, bracket)
                self._bracket_models.add(model)

            if model not in options:      # 001/002双候选收窄后可能同码，去重保序
                options.append(model)

            rewritten[(c.get("详细型号") or "").strip()] = model

        if not options:
            return

        self._fill(self.controllerComboBox_1, options)
        target = rewritten.get(current, current)

        if target in options:
            self.controllerComboBox_1.setCurrentText(target)
        elif current and current != "无匹配":
            self.controllerComboBox_1.setCurrentText(current)   # 保留手输

    # ====输出报价采集====

    def build_item(self):
        """采集人工确认后的选择 -> (Writer项目dict, 警告列表)。

        型号取各下拉当前文本；模块支点数/传感器参数优先回查保存的
        engine结构化结果，用户手改文本时回退为文本解析。
        """
        warnings = []
        code = _TYPE_CODES.get(self.comboBox.currentText())

        if code is None:
            return None, ["条目 {}：无法识别的条目类型「{}」".format(
                self.label_ID.text(), self.comboBox.currentText())]

        if code in ("truck_A", "truck_D"):
            return None, ["条目 {}({})：汽车衡类暂无CSV描述库，已跳过".format(
                self.label_ID.text(), self.comboBox.currentText())]

        try:
            qty = int(float(self.qtyBox.text().strip()))
        except ValueError:
            qty = 1
            warnings.append("条目 {}：数量非数字，按1处理".format(self.label_ID.text()))

        project = {
            "quote_id": int(self.label_ID.text() or 0),
            "type": code,
            "qty": qty,
            "ex": self.exCheckBox.isChecked(),
            # 数字化方案：Writer 据此切换通讯电缆(选型侧已强制FAB/换jbox映射)
            "digital": self.digiCheckBox.isChecked(),
        }
        result = self._result or {}

        if code == "module":
            # 回查池=推荐组合+自由搭配候选：跨材质组合(如碳钢输入配
            # AWBS 的 S 材质模块)同样能精确回查；推荐组合在前，同文本优先
            module_items = (result.get("module") or []) \
                + (result.get("module_free") or [])
            support = None

            if module_items:
                support = module_items[0].get("info", {}).get("support")

            if support is None:
                support = 4
                warnings.append("条目 {}：结构化数据缺少支点数，按4支点处理".format(
                    self.label_ID.text()))

            project["support"] = int(support)

            # 精确回查结构化条目(模块行文本由 _format_module_option 生成并随
            # 传感器联动写入，无手改途径；回查失败按原文输出并警告)
            text = self.productComBox.currentText()
            entry = next(
                (m for m in module_items
                 if self._format_module_option(m) == text), None
            )

            if entry is not None:
                # 输出型号同样拼接L后缀(sag_on时)，与下拉文本/描述通表L行对齐
                module_model = entry["module"]["module模块型号"] + engine.sag_suffix(
                    entry["module"], (self._result or {}).get("sag_on"))
                model, desc = Writer.lookup_module(
                    module_model,
                    entry["module"]["mtl模块材质"],
                    entry["sensor"]["family型号"],
                    entry["sensor"]["capacity容量"],
                    self._sensor_is_ex(entry["sensor"]),
                    y=entry["sensor"].get("Y值"),
                    accuracy=entry["sensor"]["AC准确度等级"],
                )
            else:
                model, desc = text, ""

            if not desc:
                warnings.append("条目 {}：模块「{}」未匹配到描述".format(
                    self.label_ID.text(), model))

            project["module"] = (model, desc)

        elif code in ("platform", "bench"):
            # 产品下拉当前项即最终型号：候选由engine提供，品种选择时当前项
            # 文本被实时改写为衍生型号
            model = self.productComBox.currentText().split(" ")[0]
            project[code] = model

            if self.derivative_info() is not None:
                desc = (Writer.lookup_platform(model) if code == "platform"
                        else Writer.lookup_bench(model))

                if not desc:
                    warnings.append("条目 {}：衍生型号「{}」未匹配到描述库".format(
                        self.label_ID.text(), model))

        if code in ("module", "platform"):
            jbox = self.jBoxComBox.currentText()

            if jbox and jbox != "无匹配":
                project["jbox"] = jbox
            else:
                warnings.append("条目 {}：接线盒未选定".format(self.label_ID.text()))

        controller = self.controllerComboBox_1.currentText()

        if controller and controller != "无匹配":
            project["controller"] = controller
        else:
            warnings.append("条目 {}：仪表未选定".format(self.label_ID.text()))

        # 支架安装前缀：选定仪表属支架可选(当前档位收窄集内)且选了立杆/壁挂时，
        # 描述开头插入安装方式；台秤按engine行支架值与选择一致时生效
        bracket = self.controllerComBox_2.currentText().strip()

        if bracket in _BRACKETS and controller and controller != "无匹配":
            prefix = "立杆安装，" if bracket == "立杆支架" else "壁挂安装，"

            if code == "bench":
                row = next(
                    (c for c in result.get("controller") or []
                     if (c.get("详细型号") or "").strip() == controller), None)

                if row is not None and (row.get("支架") or "").strip() == bracket:
                    project["controller_install"] = prefix
            elif controller in self._bracket_models:
                project["controller_install"] = prefix

        # 附件选择：1/2/3 三框统一采集去重(可跨框重复选同一件，按一件处理)。
        # 过渡板(模块)与大屏幕类已接入报价输出；大屏幕以选型确认的具体型号
        # 走 display 字段落行；其余附件暂未接入，警告防静默丢失
        accessories = []

        for combo in (self.accessoryComBox_1, self.accessoryComBox_2,
                      self.accessoryComBox_3):
            text = combo.currentText().strip()

            if (text and text != "无" and text not in accessories
                    and text not in _DISPLAY_OPTIONS):
                accessories.append(text)

        wired = ("上过渡板", "下过渡板") if code == "module" else ()

        for text in accessories:
            if text not in wired:
                warnings.append("条目 {}：附件「{}」暂未接入报价输出".format(
                    self.label_ID.text(), text))

        if accessories:
            project["accessories"] = accessories

        display = self.displayEdit.text().strip()

        if display:
            project["display"] = display

        # 分项段header参数：Desk采集的W1/W2(全业务通用，秤业务通常无料重/自重
        # 则留空) + engine的量程/分度值计算结果(模块取metrology，平台秤/台秤取
        # 通表行) + 仪表行的com_2/供电
        header = {
            "W1": self._params.get("W1"),
            "W2": self._params.get("W2"),
        }

        if code == "module":
            metrology = result.get("metrology")

            if isinstance(metrology, dict) and metrology.get("rated_range") is not None:
                header["range"] = metrology.get("rated_range")
                header["e"] = metrology.get("e")
        else:
            rows = result.get("platform") or result.get("bench") or []
            first = (rows[0].get("platform") if code == "platform" else rows[0]) if rows else None

            if first is not None:
                header["range"] = first.get("量程")
                header["e"] = first.get("分度值")

        row = self._controller_row_info(controller)

        if row is not None:
            header["com2"] = (str(row.get("com_2") or "")
                              .split("|")[0].strip())
            header["power"] = row.get("Power")

        if any(v is not None and v != "" for v in header.values()):
            project["header"] = header

        # 快照恢复的条目：无 engine 结果可查，回填快照留存的安装前缀与
        # 量程/分度值(com2/power属仪表行数据，改选仪表后会失配，不回填)
        restore = self._snapshot_restore

        if restore:
            if (restore.get("controller_install")
                    and "controller_install" not in project):
                project["controller_install"] = restore["controller_install"]

            saved = restore.get("header") or {}
            proj_header = project.setdefault("header", {})

            for key in ("range", "e"):
                if proj_header.get(key) is None and saved.get(key) is not None:
                    proj_header[key] = saved[key]

        return project, warnings

    def _controller_row_info(self, controller):
        """当前选定仪表对应的engine行：精确匹配详细型号 -> 支架变体后的
        型号匹配(bracket改写过) -> 首行兜底；无仪表行返回None"""
        controllers = (self._result or {}).get("controller") or []

        if not controllers or not controller or controller == "无匹配":
            return None

        for c in controllers:
            if (c.get("详细型号") or "").strip() == controller:
                return c

        bracket = self.controllerComBox_2.currentText().strip()

        for c in controllers:
            model = (c.get("详细型号") or "").strip()

            if model and Writer.bracket_variant(model, bracket) == controller:
                return c

        return controllers[0]

    def _format_module_option(self, m):
        """模块下拉选项文本(与描述通表规格型号同构，无+号)；build_item
        依赖同一格式做精确回查。格式函数与engine CLI输出同源
        (format_capacity/ex_suffix/y_suffix)，不在此处镜像拼接；
        高速搅拌(engine结果带sag_on)且模块行支持拉杆时，型号拼接L后缀。"""
        s = m["sensor"]
        sag = engine.sag_suffix(
            m["module"], (self._result or {}).get("sag_on"))
        return "{}{} {} {}-{}-{}{}".format(
            m["module"]["module模块型号"],
            sag,
            m["module"]["mtl模块材质"],
            s["family型号"],
            engine.format_capacity(s),
            s["AC准确度等级"],
            engine.ex_suffix(s),
        ) + engine.y_suffix(s, self._all_sensors())

    @staticmethod
    def _sensor_is_ex(sensor):
        """传感器行是否防爆：优先engine注入的EX_bool，否则按EX防爆等级判定"""
        ex = sensor.get("EX_bool")

        if ex is not None:
            return bool(ex)

        return str(sensor.get("EX防爆等级") or "").strip() not in ("", "0", "NA")

    def _sensor_option_text(self, sensor):
        """传感器下拉文本：family-容量[BH]-精度[ EX][ Y=..]，段序与模块行
        传感器段一致；格式函数与engine CLI输出同源，不在此处镜像拼接"""
        return "{}-{}-{}{}{}".format(
            sensor["family型号"],
            engine.format_capacity(sensor),
            sensor["AC准确度等级"],
            engine.ex_suffix(sensor),
            engine.y_suffix(sensor, self._all_sensors()),
        )

    def _all_sensors(self):
        """y_suffix 的参照集：engine 全量传感器候选(含未过筛)；旧结构
        无 all_sensors 时退回筛选结果集"""
        sensor_result = (self._result or {}).get("sensor") or {}
        return sensor_result.get("all_sensors") \
            or sensor_result.get("sensors") or []

    @staticmethod
    def _fill(combo, items):
        combo.clear()
        combo.addItems(items)

        if items:
            combo.setCurrentIndex(0)


class Checklist(QWidget, Ui_quoteChecklist):

    # 回退请求：Commander 隐藏清单并复显该项目的 Desk 供修改
    # (窗口显隐编排归上层，本模块只发信号)
    rollbackRequested = Signal()

    # 报价输出成功：Commander 更新状态提示；清单窗口保留(可换抬头再
    # 输出)，已输出状态下关闭清单窗口即整体收尾
    outputSucceeded = Signal()

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(app_icon())

        self.scrollArea.setWidgetResizable(True)

        # 公司名称/联系人输入框与报价抬头下拉同高(单行输入观感)；
        # Ui 文件重新生成也不丢此约束，故在此重复设定
        combo_height = self.titalComBox.sizeHint().height()
        self.editCompanyName.setFixedHeight(combo_height)
        self.editContactPerson.setFixedHeight(combo_height)

        # listitem 容器
        self.checklistLayout = QVBoxLayout(self.ChecklistContainer)
        self.checklistLayout.setContentsMargins(10, 10, 10, 10)
        self.checklistLayout.setSpacing(10)

        self.pushButtonOutput.clicked.connect(self._output_quote)

        # 现场服务：状态只读展示(决策在Desk整单开关)，与其他状态复选框同样
        # 不可在清单内更改——保持checkable(setChecked回填需要)并鼠标穿透
        self.serviceCheckBox_1.setCheckable(True)
        self.serviceCheckBox_1.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.serviceCheckBox_1.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 输出语言联动：英文模板无现场服务行——选英文时禁用服务复选框
        # (Desk 选了也不生效，输出侧对 lang=en 强制不提供服务费)
        self.langComBox.currentTextChanged.connect(self._on_lang_changed)
        self._on_lang_changed(self.langComBox.currentText())

        # 回退按钮已入 Ui(抬头按钮行末尾)：这里只接信号——点击即请求上层回退
        self.pushButtonRollback.clicked.connect(self.rollbackRequested.emit)

        # 是否已完成过一次报价输出：已输出时关闭窗口=项目整体完成；
        # 重载新选型结果时复位(load_results)
        self.output_completed = False

        # 诊断控件：缺项警告徽章/悬停提示/诊断子窗，按 item 逐个挂接评估
        # (v1.5: Diagnostic 模块挂起，数据缺失提示改走 CLI，恢复时取消注释)
        # self._diagnostic = Diagnostic.Diagnostic(self)

        # 自动解决方案检查器：engine diagnostic -> problem_shooting.json 映射
        # (v1.5: Checker 模块挂起，恢复时取消注释)
        # self._checker = Checker.Checker()

    def _iter_items(self):
        for i in range(self.checklistLayout.count()):
            # itemAt 可返回 None(空槽位/间隔项)，先判空再取 widget
            layout_item = self.checklistLayout.itemAt(i)

            if layout_item is None:
                continue

            widget = layout_item.widget()

            if isinstance(widget, QuoteListItem):
                yield widget

    def dump_state(self):
        """反馈导出：逐条汇总清单条目的人工确认状态(只读，不影响界面)。
        每条含 quote_id/类型/数量/状态复选框与各下拉当前文本，并经输出
        报价同一函数 build_item() 生成最终条目dict与警告，保证反馈
        附件与实际报价输出内容一致。"""
        states = []

        for item in self._iter_items():
            try:
                item_out, warnings = item.build_item()
            except Exception as err:
                item_out, warnings = None, ["build_item 异常：{}".format(err)]

            states.append({
                "quote_id": item.label_ID.text(),
                "type": item.comboBox.currentText(),
                "qty": item.qtyBox.text(),
                "metrology": item.metroCheckBox.isChecked(),
                "high_precision": item.highPresCheckBox.isChecked(),
                "ex": item.exCheckBox.isChecked(),
                "digital": item.digiCheckBox.isChecked(),
                "selections": (
                    ("产品", item.productComBox.currentText()),
                    ("传感器", item.sensorComBox.currentText()),
                    ("接线盒", item.jBoxComBox.currentText()),
                    ("仪表", item.controllerComboBox_1.currentText()),
                    ("安装方式", item.controllerComBox_2.currentText()),
                    ("衍生品种", item.derivativeComBox.currentText()),
                    ("附件1", item.accessoryComBox_1.currentText()),
                    ("附件2", item.accessoryComBox_2.currentText()),
                    ("附件3", item.accessoryComBox_3.currentText()),
                    ("大屏幕", item.displayEdit.text()),
                ),
                "item": item_out,
                "warnings": warnings,
            })

        return states

    def _collect_issues(self):
        """输出前预检：必要项空值(附件1/2/3除外，隐藏项不算)。
        返回 [(item, {"empty": [字段名...], "warn": [缺项名...]})]；
        warn 通道随 Diagnostic 挂起停用(数据缺失提示改走 CLI)，键保留空列表
        以兼容 _format_issues。"""
        # warned = {id(w) for w in self._diagnostic.warning_items()}
        issues = []

        for item in self._iter_items():
            type_text = item.comboBox.currentText()

            if type_text in ("汽车衡", "数字汽车衡"):
                continue      # 不参与报价输出的业务不阻塞预检

            config = _PIPELINE_LABELS.get(type_text, {})
            empty = []

            for attr, key in _NECESSARY_FIELDS:
                combo = getattr(item, attr)

                if combo.isHidden():
                    continue

                text = combo.currentText().strip()

                if text == "" or text == "无匹配" or text.startswith("选型失败"):
                    empty.append((config.get(key) or key).rstrip("："))

            try:
                if int(float(item.qtyBox.text().strip() or 0)) <= 0:
                    raise ValueError
            except ValueError:
                empty.append("数量")

            # warn = (Diagnostic.missing_models(item.result())
            #         if id(item) in warned else [])

            if empty:
                issues.append((item, {"empty": empty, "warn": []}))

        return issues

    @staticmethod
    def _format_issues(issues):
        lines = []

        for item, info in issues:
            parts = []

            if info["empty"]:
                parts.append("空值：" + "、".join(info["empty"]))

            if info["warn"]:
                parts.append("诊断警告：" + "、".join(info["warn"]))

            lines.append("条目 {}：{}".format(
                item.label_ID.text(), "；".join(parts)))

        return "\n".join(lines)

    def _warn_derivative_output(self):
        """衍生型号输出提示：当前衍生型号按标准型描述输出，需人工改动描述。
        无衍生选择时不弹窗直接放行；返回False表示用户退回修改。"""
        derivs = []

        for w in self._iter_items():
            info = w.derivative_info()

            if info is not None:
                derivs.append((w.label_ID.text(), info))

        if not derivs:
            return True

        lines = "\n".join("项目 {}：{} → {}（{}）".format(
            qid, info["base"], info["model"], info["variant"])
            for qid, info in derivs)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("衍生型号提示")
        box.setText("以下条目使用了衍生型号：\n\n{}\n\n"
                    "目前衍生型号仅支持按标准型描述输出，请输出后人工改动描述。".format(lines))
        box.addButton("退回修改", QMessageBox.ButtonRole.RejectRole)
        btn_go = box.addButton("继续输出", QMessageBox.ButtonRole.YesRole)
        box.exec()
        return box.clickedButton() is btn_go

    def _confirm_output(self, issues):
        """输出前整体确认：一句「请确认选型无误」+ 再看一眼/输出吧。
        有空值警告时仅图标示警，明细在 CLI 提示。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if issues
                     else QMessageBox.Icon.Question)
        box.setWindowTitle("输出确认")
        box.setText("请确认选型无误")
        box.addButton("再看一眼", QMessageBox.ButtonRole.RejectRole)
        btn_ok = box.addButton("输出吧", QMessageBox.ButtonRole.YesRole)
        box.exec()
        return box.clickedButton() is btn_ok

    # def _show_auto_solution(self, issues):
    #     """查看自动解决方案：QuoteChecker 读取 engine diagnostic，
    #     按 problem_shooting.json 映射生成问题清单(按quote_id排列)并展示"""
    #     results = [w.result() for w in self._iter_items()
    #                if w.result() is not None]
    #     problems = self._checker.check(results)
    #
    #     if not problems:
    #         QMessageBox.information(
    #             self, "自动解决方案",
    #             "engine诊断中未发现可自动定位的问题；空值可能来自手动清空的"
    #             "字段，请逐项检查清单。\n\n{}".format(self._format_issues(issues))
    #         )
    #         return
    #
    #     Checker.CheckerDialog(problems, parent=self).exec()

    def _on_lang_changed(self, text):
        """语言联动：英文版不提供现场服务选项——选英文时禁用服务复选框，
        切回中文恢复(勾选状态仍由 Desk 回填，英文输出侧一律不生效)。"""
        lang = _LANG_CODES.get((text or "").strip(), "zh")
        self.serviceCheckBox_1.setEnabled(lang == "zh")

    def _output_quote(self):
        """输出报价：公司信息检查 -> 预检 -> 保存位置确认 -> 模板填充。"""
        # 公司名称/联系人是报价单必填信息：任一为空即提示补填，不进入输出流程
        company = self.editCompanyName.toPlainText().strip()
        contact = self.editContactPerson.toPlainText().strip()

        if not company or not contact:
            QMessageBox.warning(self, "输出报价", "报价前请提供公司名称与联系人")
            return

        title = self.titalComBox.currentText()
        brands = ("COPA B", "COPA A")

        if title not in brands:
            QMessageBox.information(
                self, "输出报价",
                "「{}」抬头暂未接入报价输出，当前支持：{}。".format(
                    title, "、".join(brands))
            )
            return

        # 输出语言：langComBox 中文/英文——英文走 *_英文版 模板与英文文案
        lang = _LANG_CODES.get(self.langComBox.currentText().strip(), "zh")

        # 衍生型号提示：描述按标准型号输出，需人工后续改动(无衍生则直接过)
        if not self._warn_derivative_output():
            return

        # 整体确认：一句确认 + 再看一眼/输出吧；空值明细改在 CLI 提示
        issues = self._collect_issues()

        if issues:
            print("[Checklist] 空值警告：\n{}".format(self._format_issues(issues)))

        if not self._confirm_output(issues):
            return

        items, warnings = [], []

        for widget in self._iter_items():
            item_out, item_warnings = widget.build_item()
            warnings.extend(item_warnings)

            if item_out is not None:
                items.append(item_out)

        if not items:
            QMessageBox.warning(
                self, "输出报价",
                "没有可输出的条目。\n" + "\n".join(warnings[:6])
            )
            return

        # 整单信息随各条目dict下发：Writer 侧可直接读取公司名称/联系人
        for project in items:
            project["company"] = company
            project["contact"] = contact

        # CLI回显衍生override，便于人工核对与调试
        for widget in self._iter_items():
            info = widget.derivative_info()

            if info is not None:
                print("[Checklist] 衍生override 条目 {}：{} -> {} ({})".format(
                    widget.label_ID.text(), info["base"], info["model"],
                    info["variant"]))

        # 先让用户确认保存位置(默认 output/ 下按抬头+条目数+时间戳预填)，取消则不输出
        chosen, _ = QFileDialog.getSaveFileName(
            self, "保存报价单",
            Writer.suggest_path(items, brand=title, lang=lang),
            "Excel 文件 (*.xlsx)",
        )

        if not chosen:
            return

        if not chosen.lower().endswith(".xlsx"):
            chosen += ".xlsx"

        try:
            path = Writer.build_quote(
                items, brand=title, out_path=chosen,
                # 英文版无现场服务选项：Desk 选了也不生效，强制不提供服务费
                service=(self.serviceCheckBox_1.isChecked()
                         and lang == "zh"),
                lang=lang,
            )
        except Exception as err:
            QMessageBox.critical(self, "输出报价", "报价单生成失败：{}".format(err))
            return

        message = "报价单已生成：\n{}".format(path)

        if warnings:
            message += "\n\n提示：\n" + "\n".join(warnings)

        QMessageBox.information(self, "输出报价", message)
        # 用户确认输出完成：窗口保留(可换抬头再输出)，仅置位并通知上层
        self.output_completed = True
        self.outputSucceeded.emit()

    def load_results(self, results, entries=None):
        """按 quote_id 升序重建清单；results 为 Desk 选型结果列表，
        entries 为对应卡片条目(提供数量/复选框状态)，按 quote_id 关联"""
        entries_by_id = {
            e["quote_info"]["quote_id"]: e
            for e in (entries or []) if "quote_info" in e
        }
        self._clear_items()
        # 重载新结果：此前的输出不再对应本次选型，输出状态复位
        self.output_completed = False

        # 现场服务为整单开关：entries 逐条携带Desk状态，任一为真即回填只读展示
        self.serviceCheckBox_1.setChecked(
            any(e.get("onsite_service") for e in (entries or [])))

        for result in sorted(results, key=lambda r: r.get("quote_id") or 0):
            entry = entries_by_id.get(result.get("quote_id"), {})
            quote_info = entry.get("quote_info", {})
            item = QuoteListItem()
            item.load_result(
                result,
                quantity=quote_info.get("quantity"),
                metrology=entry.get("metrology", False),
                high_precision=entry.get("high_precision", False),
                ex_p=entry.get("Ex_P", False),
                digi=entry.get("digital", False),
                params=(entry.get("parsed") or {}).get("data"),
            )
            self.checklistLayout.addWidget(item)
            # Diagnostic 挂起：徽章挂接/评估停用，恢复时取消注释
            # (原顺序说明：addWidget 重设父窗口会把 item 重新置隐，
            #  必须先入容器再挂徽章，否则 badge.show() 的可见状态会在重父化时丢失)
            # self._diagnostic.attach(item)
            # self._diagnostic.evaluate(item)

        self._refresh_scroll_area()

        # Diagnostic 挂起：选型数据缺失提示改在 CLI 输出
        report = format_missing_models(results)

        if report:
            print("[Checklist] 选型数据缺失：\n{}".format(report))

    def load_snapshot(self, meta, items):
        """从快照恢复清单(「打开快照」)：items 为 Snapshot.parse_snapshot
        解析出的条目JSON列表(含状态表字段)，逐条直接装配确认值；清单级
        恢复抬头/语言/现场服务/客户信息。此前的输出状态复位"""
        self._clear_items()
        self.output_completed = False

        meta = meta or {}
        self.serviceCheckBox_1.setChecked(bool(meta.get("onsite_service")))

        for key, combo in (("title", self.titalComBox),
                           ("lang", self.langComBox)):
            value = (meta.get(key) or "").strip()

            if value and combo.findText(value) >= 0:
                combo.setCurrentText(value)

        for attr, key in (("editCompanyName", "company"),
                          ("editContactPerson", "contact")):
            widget = getattr(self, attr, None)

            if widget is not None:
                widget.setPlainText(meta.get(key) or "")

        for data in items:
            item = QuoteListItem()
            item.load_snapshot_item(data)
            self.checklistLayout.addWidget(item)

        self._refresh_scroll_area()

    def _clear_items(self):
        while self.checklistLayout.count():
            # takeAt 可返回 None，判空防止空指针
            layout_item = self.checklistLayout.takeAt(0)

            if layout_item is None:
                continue

            widget = layout_item.widget()

            if widget is not None:
                widget.deleteLater()

    def _refresh_scroll_area(self):
        # 布局尺寸提示要等事件循环处理 LayoutRequest 后才会更新，
        # 同步调用 adjustSize 拿到的是旧值，必须推迟到下一轮事件循环
        contents = self.scrollArea.widget()

        if contents is not None:
            QTimer.singleShot(0, contents.adjustSize)


# ====演示：模拟engine回传多选项结果====
_SIM_RESULTS = [
    {
        "quote_id": 1, "item_type": "module", "status": "OK",
        "metrology": {"status": "OK", "rated_range": 5000, "e": 2, "n": 2500},
        "sensor": {"sensors": [
                       {"family型号": "SLB", "capacity容量": 227, "AC准确度等级": "C3",
                        "安装方式": "盲孔安装", "Y值": 11500, "EX防爆等级": "0"},
                       {"family型号": "SB14", "capacity容量": 227, "AC准确度等级": "C3",
                        "安装方式": "盲孔安装", "Y值": 11500, "EX防爆等级": "0"},
                   ],
                   "selection_status": "OK",
                   "diagnostic": {"status": "OK", "input_count": 24}},
        "module": [
            {"module": {"module模块型号": "52-30M", "mtl模块材质": "SS"},
             "sensor": {"family型号": "SLB", "capacity容量": 227, "AC准确度等级": "C3",
                        "安装方式": "盲孔安装", "Y值": 11500, "EX防爆等级": "0"},
             "info": {"support": 3}},
            {"module": {"module模块型号": "52-30M", "mtl模块材质": "SS"},
             "sensor": {"family型号": "SB14", "capacity容量": 227, "AC准确度等级": "C3",
                        "安装方式": "盲孔安装", "Y值": 11500, "EX防爆等级": "0"},
             "info": {"support": 3}},
            {"module": {"module模块型号": "52-30M", "mtl模块材质": "SS"},
             "sensor": {"family型号": "SB14", "capacity容量": 454, "AC准确度等级": "C3",
                        "安装方式": "盲孔安装", "Y值": 11500, "EX防爆等级": "0"},
             "info": {"support": 3}},
        ],
        "jbox": {"model型号": "KE-4"},
        "controller": [
            {"详细型号": "FT210PA000000A", "安装方式": "面板式",
             "com_1": "RTU_2", "com_2": "0", "com_3": "0", "Power": "AC220V"},
            {"详细型号": "FT210DA000000D", "安装方式": "导轨式",
             "com_1": "RTU_2", "com_2": "0", "com_3": "0", "Power": "DC24V"},
            {"详细型号": "FT210HA000010A", "安装方式": "防尘式",
             "com_1": "RTU_2", "com_2": "0", "com_3": "0", "Power": "AC220V"},
        ],
    },
    {
        "quote_id": 2, "item_type": "platform", "status": "OK",
        "platform": [
            {"platform": {"具体型号": "FTPD-S-003-0606", "量程": 300,
                          "台面尺寸": "600x600", "分度值": 0.1},
             "sensors": ["SLB-227kg-C3", "SB14-227kg-C3"]},
            {"platform": {"具体型号": "FTPD-S-003-0808", "量程": 300,
                          "台面尺寸": "800x800", "分度值": 0.1},
             "sensors": ["SLB-227kg-C3", "SB14-227kg-C3"]},
        ],
        "jbox": {"model型号": "KE-4"},
        "controller": [
            {"详细型号": "FT210PA000000A", "安装方式": "面板式",
             "com_1": "RTU_2", "com_2": "0", "com_3": "0", "Power": "AC220V"},
            {"详细型号": "FT210HA000010A", "安装方式": "防尘式",
             "com_1": "RTU_2", "com_2": "0", "com_3": "0", "Power": "AC220V"},
        ],
    },
    {
        "quote_id": 3, "item_type": "bench", "status": "OK",
        "bench": [
            {"具体型号": "FTBR-C-030-3040", "量程": 30, "台面尺寸": "300x400",
             "分度值": 0.01},
            {"具体型号": "FTBR-C-030-2430", "量程": 30, "台面尺寸": "240x300",
             "分度值": 0.01},
        ],
        "controller": [
            {"详细型号": "FT230HA002A", "支架": "立杆支架",
             "com_1": "RTU_1", "com_2": "0", "com_3": "0", "Power": "AC220V"},
            {"详细型号": "FT230HA001A", "支架": "壁挂支架",
             "com_1": "RTU_1", "com_2": "0", "com_3": "0", "Power": "AC220V"},
        ],
    },
]

_SIM_ENTRIES = [
    {"quote_info": {"quote_id": 1, "quantity": 12},
     "metrology": True, "high_precision": False, "Ex_P": False,
     "parsed": {"data": {"W1": 3400, "W2": 450, "support": 3}}},
    {"quote_info": {"quote_id": 2, "quantity": 2},
     "metrology": False, "high_precision": True, "Ex_P": False},
    {"quote_info": {"quote_id": 3, "quantity": 1},
     "metrology": False, "high_precision": False, "Ex_P": False},
]


if __name__ == "__main__":
    app = QApplication([])
    window = Checklist()
    window.load_results(_SIM_RESULTS, _SIM_ENTRIES)
    window.show()
    app.exec()
