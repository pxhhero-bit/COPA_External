"""This is COPA_com_SyncParser, the inverse of Parser: standard parameter dict
-> quote text under the same plain-text syntax(要素中文逗号分隔、部件中文句号
分隔)，供 Desk 下拉菜单输入页与输入框文本输入页双通道并行。下拉值经本模块
同步成标准文本后，仍走 Parser.parse_quote_text 同一解析路径。"""
import json
import os
import re
import sys

# 数据根目录：与 Parser 共用同一规则文件，冻结打包/源码运行定位保持一致
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_RULES_PATH = os.path.join(_ROOT_DIR, "config", "parser_rules.json")

# Modbus 路数口语写法："2路Modbus" / "Modbus*2"
_MODBUS_COUNT_PRE_RE = re.compile(r"(\d+)\s*[路*×xX]\s*modbus")
_MODBUS_COUNT_POST_RE = re.compile(r"modbus\s*[路*×xX]\s*(\d+)")

# 台面尺寸归一后的合法形态 AxB(与 Parser _SIZE_RE 的输出形态一致)
_SIZE_TEXT_RE = re.compile(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?")

# 尺寸分隔符归一(全角×/大写X/星号 -> 半角x)
_SIZE_SEP_TRANS = str.maketrans("×X*", "xxx")

# req_com2 下拉显示层映射：规范名 -> 中文显示名。
# 仅影响 GUI 下拉菜单的条目展示，不改变参数取值——sync 两侧均接受
# 显示名并还原为规范名(com2_canonical)，选型输入仍是规范名协议
COM2_DISPLAY = {
    "ANALOG": "模拟量4-20mA",
    "ANALOG5V": "模拟量0-5V",
    "ANALOG10V": "模拟量0-10V",
}

# 显示名 -> 规范名反查(sync 接受显示名输入时还原，选型输入不变)
COM2_DISPLAY_INVERSE = {text: name for name, text in COM2_DISPLAY.items()}


def _num(value):
    """浮点结果尽量收敛为整数(3400.0 -> 3400)，与 Parser 取值形态对齐"""
    rounded = round(value, 6)
    return int(rounded) if float(rounded).is_integer() else rounded


class SyncParser:
    """逆向同步解析器：标准参数字典 -> 报价输入文本(逆向于 parse_quote_text)。

    输入 values 的键为 Parser 输出的标准参数ID，值为下拉选项：

      W1/W2/e_input/r_input    数值kg(也接受 "3.4t" 式带单位字符串)
      support/RPM/special_req  整数；special_req≥1 产出"通道N"(单通道显式还原)
      m_brand/c_brand          FT/AW/FAB(也接受 富林泰克 等别名，经 rules 归一)
      c_family                 仪表CSV family/nickname 列原文(3306/FT-210/
                               FAB330/AW-220 T1...)，经 CSV 词表反查同时还原
                               c_brand；故片段先于 c_brand 产出
      Ex_P/vibration           布尔双极：真 -> "需要防爆"/"带搅拌"，
                               假 -> "无需防爆"/"无搅拌"(否定前缀由 Parser 识别)
      special_req2             仅真值产出("带电池")；语法无法表达其否定
      required_ex              防爆等级文本(IIBT4)；其存在隐含 Ex_P，与 Parser 一致
      material                 碳钢/不锈钢/混合 裸词，或 SS/CS 等ASCII材质码
      台面尺寸                 "1.2x1.5"(分隔符 ×/X/* 均可) 或 [1.2, 1.5](米)
      安装形式                 一体/分体(可带"式")
      分体仪表支架             壁挂支架/立杆支架/壁挂/立杆(挂墙/立柱别名归一)
      install                  面板式/导轨式/防尘式/隔爆("面板"式省写自动补全)
      power                    AC220V/DC24V
      req_com1                 基础串口协议列表(RS232/RS485/Modbus，"2路Modbus"
                               表两路)；也接受 Parser 产出的规则码列表
                               (basic_1/basic_2/RTU_1/RTU_2)——先反解需求码
                               再重建，缺字面时 basic_1 以 RS485 作代表，
                               重建为原码集合的验收超集(见 _com1_fragments)
      req_com2                 扩展协议规范名列表(TCP/ANALOG/ANALOG5V/DP/...)，
                               顺序随输入列表

    值为 None/""/[] 的键视为未选择，不产出片段；flags 的 False 产出显式否定
    片段(special_req2 除外)。输出与手写需求同语法，可直接回灌
    parse_quote_text 还原参数(sync -> parse 对参数空间封闭，见自测)。
    """

    def __init__(self, rules_path=_DEFAULT_RULES_PATH):
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)

        self._component_delim = self.rules["delimiters"]["component"][0]
        self._parameter_delim = self.rules["delimiters"]["parameter"][0]

        self.parameters = self.rules["parameters"]
        self._weight_units = self.rules["units"]["weight"]
        # 带单位数值串解析：单位词交替长词优先(防 "kg" 被 k/g 拆开误读)
        self._weight_str_re = re.compile(
            r"(\d+(?:\.\d+)?)\s*({})?\s*".format(
                "|".join(
                    re.escape(unit)
                    for unit in sorted(self._weight_units, key=len, reverse=True)
                )
            )
        )

        # 品牌别名归一表(m_brand/c_brand 的 values 合并，别名 -> 规范名)
        self._brand_alias = {}
        for pdef in self.parameters.values():
            if pdef.get("type") == "brand":
                for alias, canonical in pdef.get("values", {}).items():
                    self._brand_alias.setdefault(alias.lower(), canonical)

        # 协议规范名与类别(basic/extended)；类别供 req_com2 混入的
        # 基础协议归位 req_com1，编译正则用于判定规范名能否自匹配
        self._protocol_category = {}
        self._protocol_patterns = []
        for entry in self.rules.get("protocols", []):
            canonical = entry["canonical"]
            self._protocol_patterns.append((canonical, re.compile(entry["pattern"])))
            if entry.get("category"):
                self._protocol_category[canonical] = entry["category"]

        # 规范名无法自匹配其识别正则的协议，重建时改写为可识别文本
        # (BT 的正则只认 bluetooth/蓝牙，ANALOG5V 只认 0-5V)；无映射且
        # 不能自匹配的规范名在产出时报错，不静默丢片段
        self._com_text_override = {
            "ANALOG5V": "0-5V",
            "ANALOG10V": "0-10V",
            "BT": "蓝牙",
        }
        self._com_text_map = {}
        for canonical, pattern in self._protocol_patterns:
            text = self._com_text_override.get(canonical)
            if text is None and pattern.search(canonical):
                text = canonical
            self._com_text_map[canonical] = text

        # req_com1 规则码反解表：Parser 产出的码列表是 expand(需求码) 的
        # 可验收能力集合，而非需求本身。expand(X) = 需求表里含 X 的全部
        # 能力码，据此由码集合反解需求码(键统一小写，与片段文本对齐)
        com1_code = self.rules.get("com1_code", {})
        coverage = com1_code.get("coverage", {})
        self._com1_expand = {
            code.lower(): {
                capability.lower()
                for capability, requirements in coverage.items()
                if code in requirements
            }
            for code in coverage
        }

        # 选项参数的合法选项与用语变体(rules 为准，与 Parser 识别面一致)
        self._material_values = self.parameters["material"].get("values", {})
        self._install_form_options = self.parameters["安装形式"].get("options", [])
        self._bracket_options = self.parameters["分体仪表支架"].get("options", [])
        self._bracket_terms = set(
            self.parameters["分体仪表支架"]["term_pattern"].split("|")
        )
        self._install_options = self.parameters["install"].get("options", [])
        self._power_options = self.parameters["power"].get("options", [])

    # ====1 主入口====

    def sync_quote_text(self, values):
        """标准参数字典 -> 报价输入文本；部件间"。"、要素间"，"，全空得空串"""
        if not isinstance(values, dict):
            raise TypeError(
                "sync 需要标准参数字典，得到: {}".format(type(values).__name__)
            )

        unknown = sorted(str(key) for key in values if key not in self.parameters)
        if unknown:
            raise ValueError(
                "包含 Parser 参数空间之外的键: {}"
                "（检定/高精度/数字化等属卡片开关字段，不在描述文本参数内）".format(
                    "、".join(unknown)
                )
            )

        groups = (
            self._structure_fragments(values),
            self._controller_fragments(values),
            self._condition_fragments(values),
            self._com_fragments(values),
        )
        return self._component_delim.join(
            self._parameter_delim.join(group) for group in groups if group
        )

    sync = sync_quote_text

    # ====2 部件装配(顺序即输出部件顺序)====

    def _structure_fragments(self, values):
        """结构与传感器部件：称重/支点/传感器品牌/材质/台面"""
        fragments = []

        if self._chosen(values, "W1"):
            fragments.append(self._weight_fragment(values["W1"], "料重", "W1"))
        if self._chosen(values, "W2"):
            fragments.append(self._weight_fragment(values["W2"], "皮重", "W2"))

        if self._chosen(values, "support"):
            count = self._int_value(
                values["support"], "support",
                minimum=self.parameters["support"].get("min"),
            )
            fragments.append("支点{}".format(count))

        if self._chosen(values, "m_brand"):
            brand = self._brand_canonical(values["m_brand"], "m_brand")
            fragments.append("{}模块".format(brand))

        if self._chosen(values, "material"):
            fragments.append(self._material_text(values["material"]))

        if self._chosen(values, "台面尺寸"):
            size = self._size_text(values["台面尺寸"])
            fragments.append("台面{}".format(size))

        return fragments

    def _controller_fragments(self, values):
        """仪表部件：系列/品牌/防爆/安装/供电/支架。

        c_family 片段必须先于 c_brand：词表反查会由系列写出兜底品牌，
        显式选择的品牌随后覆盖，保最终值与下拉一致(不一致时 Parser 如实
        记一条覆盖警告)"""
        fragments = []

        if self._chosen(values, "c_family"):
            fragments.append("仪表{}".format(str(values["c_family"]).strip()))

        if self._chosen(values, "c_brand"):
            brand = self._brand_canonical(values["c_brand"], "c_brand")
            fragments.append("{}仪表".format(brand))

        if values.get("Ex_P") is not None and not isinstance(
            values.get("Ex_P"), (list, dict)
        ):
            fragments.append(
                "需要防爆" if values["Ex_P"] else "无需防爆"
            )

        if self._chosen(values, "required_ex"):
            fragments.append(
                "防爆等级{}".format(str(values["required_ex"]).strip().upper())
            )

        if self._chosen(values, "install"):
            fragments.append(self._install_text(values["install"]))

        if self._chosen(values, "power"):
            text = str(values["power"]).strip().upper()
            if text not in self._power_options:
                raise ValueError("power 无法识别的供电选项: {}".format(values["power"]))
            fragments.append("供电{}".format(text))

        if self._chosen(values, "安装形式"):
            base = str(values["安装形式"]).strip()
            if base.rstrip("式") not in self._install_form_options:
                raise ValueError(
                    "安装形式 无法识别的选项: {}".format(values["安装形式"])
                )
            fragments.append("安装形式{}".format(base))

        if self._chosen(values, "分体仪表支架"):
            fragments.append(self._bracket_text(values["分体仪表支架"]))

        return fragments

    def _condition_fragments(self, values):
        """计量与工况部件：量程/分度值/搅拌转速/通道/电池"""
        fragments = []

        if self._chosen(values, "r_input"):
            fragments.append(
                self._weight_fragment(values["r_input"], "额定量程", "r_input")
            )
        if self._chosen(values, "e_input"):
            fragments.append(
                self._weight_fragment(values["e_input"], "分度值", "e_input")
            )

        if values.get("vibration") is not None and not isinstance(
            values.get("vibration"), (list, dict)
        ):
            fragments.append("带搅拌" if values["vibration"] else "无搅拌")

        if self._chosen(values, "RPM"):
            rpm = self._int_value(
                values["RPM"], "RPM", minimum=self.parameters["RPM"].get("min")
            )
            fragments.append("转速{}".format(rpm))

        if self._chosen(values, "special_req"):
            channels = self._int_value(
                values["special_req"], "special_req",
                minimum=self.parameters["special_req"].get("min"),
            )
            # 单通道也显式还原(与文本输入"单通道"同参数形态)，保回环封闭
            fragments.append("通道{}".format(channels))

        if values.get("special_req2"):
            fragments.append("带电池")

        return fragments

    def _com_fragments(self, values):
        """通讯部件：先基础串口(req_com1)后扩展协议(req_com2)"""
        routed = []
        com2_fragments = self._com2_fragments(values.get("req_com2"), routed)

        com1_source = values.get("req_com1")
        if routed:
            # req_com2 混入的基础串口协议归位 req_com1(与 Parser 分类一致)
            merged = (
                [com1_source] if isinstance(com1_source, str)
                else list(com1_source or [])
            )
            merged.extend(routed)
            com1_source = merged

        return self._com1_fragments(com1_source) + com2_fragments

    # ====3 协议重建====

    def _com1_fragments(self, value):
        """req_com1 -> 基础串口片段；协议规范名与规则码双形态接受。

        规则码集合先反解需求码再重建(见 _recover_com1_code)：basic_1
        缺字面协议时以 RS485 作代表、basic_2 补全双串口——重建结果对
        原码集合是验收超集(engine 按规则码成员匹配，不收窄可选型号)，
        真实 Parser 数据(码集合恒为完整展开且自带字面协议)精确还原"""
        serials = set()
        modbus = 0
        codes = set()

        entries = [value] if isinstance(value, str) else list(value or [])
        for entry in entries:
            text = str(entry).strip().lower()
            if not text:
                continue
            if text == "rs232":
                serials.add("RS232")
            elif text == "rs485":
                serials.add("RS485")
            elif text == "modbus":
                modbus = max(modbus, 1)
            elif text in self._com1_expand:
                codes.add(text)
            else:
                count = self._modbus_count_in(text)
                if count is None:
                    raise ValueError(
                        "req_com1 无法识别的串口协议/规则码: {}".format(entry)
                    )
                modbus = max(modbus, count)

        requirement = self._recover_com1_code(codes)
        if requirement is not None:
            if requirement == "basic_1":
                if not serials:
                    serials = {"RS485"}
            elif requirement == "basic_2":
                serials.update(("RS232", "RS485"))
            elif requirement == "rtu_1":
                modbus = max(modbus, 1)
            elif requirement == "rtu_2":
                modbus = max(modbus, 2)

        fragments = [name for name in ("RS232", "RS485") if name in serials]
        if modbus:
            fragments.append(
                "{}路Modbus".format(modbus) if modbus > 1 else "Modbus"
            )
        return fragments

    def _recover_com1_code(self, codes):
        """码集合 -> 需求码：优先还原恰为该集合展开的需求码(真实 Parser
        数据必是其一)；否则取展开覆盖该集合的最小需求码，保验收不收窄"""
        if not codes:
            return None

        for code, expanded in self._com1_expand.items():
            if expanded == codes:
                return code

        best = None
        for code, expanded in self._com1_expand.items():
            if codes <= expanded and (
                best is None or len(expanded) < len(self._com1_expand[best])
            ):
                best = code
        return best

    def _com2_fragments(self, value, com1_sink):
        """req_com2 -> 扩展协议片段；顺序随输入列表(回环时片段顺序即
        Parser 合并顺序)，仅去重。下拉显示名(模拟量4-20mA 等)经
        com2_canonical 还原规范名后参与解析，选型输入不受显示层影响"""
        entries = [value] if isinstance(value, str) else list(value or [])
        selected = []
        for entry in entries:
            canonical = self.com2_canonical(entry).upper()
            category = self._protocol_category.get(canonical)
            if category is None:
                raise ValueError("req_com2 无法识别的协议: {}".format(entry))
            if category == "basic":
                com1_sink.append(canonical)
            elif canonical not in selected:
                selected.append(canonical)

        fragments = []
        for canonical in selected:
            text = self._com_text_map[canonical]
            if text is None:
                raise ValueError(
                    "协议[{}]无法重建为可识别文本，"
                    "请在 _com_text_override 补充映射".format(canonical)
                )
            fragments.append(text)
        return fragments

    @staticmethod
    def _modbus_count_in(text):
        m = _MODBUS_COUNT_PRE_RE.fullmatch(text)
        if m is not None:
            return int(m.group(1))
        m = _MODBUS_COUNT_POST_RE.fullmatch(text)
        if m is not None:
            return int(m.group(1))
        return None

    # ====4 值归一====

    @staticmethod
    def com2_canonical(value):
        """req_com2 取值归一：显示名(模拟量4-20mA 等) -> 规范名；
        非显示名原样返回(交由 _com2_fragments 按规范名校验)"""
        text = str(value).strip()
        return COM2_DISPLAY_INVERSE.get(text, text)

    @staticmethod
    def com2_display(canonical):
        """规范名 -> 下拉显示名(仅 GUI 展示用)；未映射的规范名原样返回"""
        return COM2_DISPLAY.get(str(canonical).strip().upper(), canonical)

    @staticmethod
    def _chosen(values, key):
        """下拉已选择(非 None/空串/空列表)"""
        value = values.get(key)
        return not (value is None or value == "" or value == [])

    def _weight_fragment(self, value, term, param_id):
        kg = self._weight_kg(value, param_id)
        return "{}{}kg".format(term, _num(kg))

    def _weight_kg(self, value, param_id):
        """数值或"N单位"串 -> kg 浮点；单位表与换算系数取自 rules"""
        if isinstance(value, bool):
            kg = None
        elif isinstance(value, (int, float)):
            kg = float(value)
        elif isinstance(value, str):
            m = self._weight_str_re.fullmatch(value.strip())
            if m is not None:
                kg = float(m.group(1))
                unit = m.group(2)
                if unit:
                    kg *= self._weight_units[unit]
            else:
                kg = None
        else:
            kg = None

        if kg is None or kg <= 0:
            raise ValueError(
                "参数[{}]需要正的重量值(kg 数值或带单位串): {}".format(param_id, value)
            )
        return kg

    @staticmethod
    def _int_value(value, param_id, minimum=None):
        if isinstance(value, bool):
            number = None
        elif isinstance(value, int):
            number = value
        elif isinstance(value, float) and value.is_integer():
            number = int(value)
        elif isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
            number = int(value.strip())
        else:
            number = None

        if number is None or (minimum is not None and number < minimum):
            raise ValueError(
                "参数[{}]需要不小于{}的整数: {}".format(
                    param_id, 0 if minimum is None else minimum, value
                )
            )
        return number

    def _brand_canonical(self, value, param_id):
        """品牌下拉值归一：别名表 -> 规范名；未知ASCII与 Parser 同样
        大写透传，非ASCII未知值视为无效(合法性校验归 Engine/数据库)"""
        text = str(value).strip()
        canonical = self._brand_alias.get(text.lower())
        if canonical:
            return canonical
        if text.isascii():
            return text.upper()
        raise ValueError("参数[{}]无法归一的品牌值: {}".format(param_id, value))

    def _material_text(self, value):
        """材质：已知裸词直接产出(用语即值)；其余走"材质"用语取后缀，
        ASCII 先统一大写保回环精确(与 Parser 的 raw.upper() 对齐)"""
        text = str(value).strip()
        if text in self._material_values:
            return text
        if text.isascii():
            text = text.upper()
        return "材质" + text

    @staticmethod
    def _size_text(value):
        """台面尺寸："1.2×1.5"式串归一为 AxB，或 [长, 宽] 序列直接格式化"""
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError("台面尺寸序列需要 [长, 宽] 两个数: {}".format(value))
            return "{}x{}".format(_num(float(value[0])), _num(float(value[1])))

        normalized = str(value).translate(_SIZE_SEP_TRANS)
        normalized = "".join(normalized.split())
        if not _SIZE_TEXT_RE.fullmatch(normalized):
            raise ValueError(
                "台面尺寸需要 AxB 形态(如 1.2x1.5)或 [长, 宽] 序列: {}".format(value)
            )
        return normalized

    def _install_text(self, value):
        """安装形式：面板式/导轨式/防尘式/隔爆；省"式"写法自动补全，
        "隔爆式"等变体原样产出(用语可识别，Parser 归一为规范选项)"""
        text = str(value).strip()
        if text in self._install_options:
            return text
        if text.rstrip("式") in self._install_options:
            return text
        if text + "式" in self._install_options:
            return text + "式"
        raise ValueError("install 无法识别的选项: {}".format(value))

    def _bracket_text(self, value):
        """分体仪表支架：选项本身是业务用语的直接产出，否则补"安装"
        后缀构成用语("壁挂" -> "壁挂安装"，裸"壁挂" Parser 挂不上用语)"""
        text = str(value).strip()
        alias = {"挂墙": "壁挂", "立柱": "立杆"}.get(text, text)
        if alias not in self._bracket_options:
            raise ValueError("分体仪表支架 无法识别的选项: {}".format(value))
        if alias in self._bracket_terms:
            return alias
        return alias + "安装"


# ====便捷入口====
def sync_quote_text(values, rules_path=_DEFAULT_RULES_PATH):
    """函数式便捷入口；常驻 GUI 场景建议复用 SyncParser 实例"""
    return SyncParser(rules_path).sync_quote_text(values)


# ====自测====
if __name__ == "__main__":
    if __package__ in (None, ""):
        from Parser import Parser
    else:
        from COPA.apps.Parser import Parser

    parser = Parser()
    sync_parser = SyncParser()
    failures = []

    def check(name, values, expects, exact=False):
        try:
            text = sync_parser.sync_quote_text(values)
        except Exception as err:
            failures.append((name, "构建异常 {}".format(err)))
            print("[FAIL] {}\n       {}".format(name, err))
            return
        data = parser.parse_quote_text(text)["data"]

        if exact:
            bad = [] if data == expects else [("(全集)", data, expects)]
        else:
            bad = [
                (key, data.get(key), expect)
                for key, expect in expects.items()
                if data.get(key) != expect
            ]

        if bad:
            failures.append((name, bad))
            print("[FAIL] {}\n       文本: {}".format(name, text))
            for key, got, expect in bad:
                print("       {} 期望 {} 实得 {}".format(key, expect, got))
        else:
            print("[OK]  {} -> {}".format(name, text))

    def expect_error(name, values):
        try:
            sync_parser.sync_quote_text(values)
        except (TypeError, ValueError) as err:
            print("[OK]  {} -> 拒绝: {}".format(name, err))
        else:
            failures.append((name, "未按预期报错"))
            print("[FAIL] {} -> 未按预期报错".format(name))

    print("====1 参数级回环====")
    cases = [
        ("W1 数值", {"W1": 3400}, {"W1": 3400}),
        ("W1 带单位串", {"W1": "3.4t"}, {"W1": 3400}),
        ("W2", {"W2": 450}, {"W2": 450}),
        ("support", {"support": 4}, {"support": 4}),
        ("m_brand 别名", {"m_brand": "富林泰克"}, {"m_brand": "FT"}),
        ("c_brand", {"c_brand": "FAB"}, {"c_brand": "FAB"}),
        ("c_family 昵称", {"c_family": "3306"}, {"c_family": "3306"}),
        ("c_family 系列", {"c_family": "FT-210"}, {"c_family": "FT-210"}),
        ("c_family+brand", {"c_family": "3306", "c_brand": "FT"},
            {"c_family": "3306", "c_brand": "FT"}),
        ("Ex_P 真", {"Ex_P": True}, {"Ex_P": True}),
        ("Ex_P 假", {"Ex_P": False}, {"Ex_P": False}),
        ("required_ex 蕴含防爆", {"required_ex": "IIBT4"},
            {"required_ex": "IIBT4", "Ex_P": True}),
        ("material 中文", {"material": "不锈钢"}, {"material": "不锈钢"}),
        ("material ASCII", {"material": "SS"}, {"material": "SS"}),
        ("台面尺寸 串", {"台面尺寸": "1.2×1.5"}, {"台面尺寸": "1.2x1.5"}),
        ("台面尺寸 序列", {"台面尺寸": [1.2, 1.5]}, {"台面尺寸": "1.2x1.5"}),
        ("e_input", {"e_input": 0.5}, {"e_input": 0.5}),
        ("r_input", {"r_input": "3t"}, {"r_input": 3000}),
        ("vibration 真", {"vibration": True}, {"vibration": True}),
        ("vibration 假", {"vibration": False}, {"vibration": False}),
        ("RPM", {"RPM": 200}, {"RPM": 200}),
        ("安装形式", {"安装形式": "分体"}, {"安装形式": "分体"}),
        ("支架 短选项", {"分体仪表支架": "壁挂"}, {"分体仪表支架": "壁挂"}),
        ("支架 全选项", {"分体仪表支架": "立杆支架"}, {"分体仪表支架": "立杆支架"}),
        ("install 省式", {"install": "面板"}, {"install": "面板式"}),
        ("install 隔爆", {"install": "隔爆"}, {"install": "隔爆"}),
        ("power", {"power": "DC24V"}, {"power": "DC24V"}),
        ("special_req 单通道", {"special_req": 1}, {"special_req": 1}),
        ("special_req 多通道", {"special_req": 3}, {"special_req": 3}),
        ("special_req2", {"special_req2": True}, {"special_req2": True}),
        ("req_com2 组合", {"req_com2": ["PROFINET", "DP"]},
            {"req_com2": ["PROFINET", "DP"]}),
    ]
    for name, values, expects in cases:
        check(name, values, expects)

    print("====2 req_com1 协议/规则码重建====")
    # 期望值为 Parser 真实展开语义：expand(需求码)=需求表含该码的全部能力码
    com1_cases = [
        (["RS232"], ["basic_1", "basic_2", "RTU_1", "RTU_2", "RS232"]),
        (["RS485"], ["basic_1", "basic_2", "RTU_1", "RTU_2", "RS485"]),
        (["RS232", "RS485"], ["basic_2", "RTU_2", "RS232", "RS485"]),
        (["Modbus"], ["RTU_1", "RTU_2"]),
        (["2路Modbus"], ["RTU_2"]),
        (["Modbus*2"], ["RTU_2"]),
        (["basic_1"], ["basic_1", "basic_2", "RTU_1", "RTU_2", "RS485"]),
        (["basic_2"], ["basic_2", "RTU_2", "RS232", "RS485"]),
        (["RTU_1"], ["RTU_1", "RTU_2"]),
        (["RTU_2"], ["RTU_2"]),
        (["RTU_2", "RS232"], ["RTU_2", "RS232"]),
    ]
    for source, expected in com1_cases:
        check("req_com1 {}".format(source), {"req_com1": source},
              {"req_com1": expected})

    print("====3 扩展协议规范名全量回环====")
    for entry in sync_parser.rules["protocols"]:
        if entry.get("category") != "extended":
            continue
        canonical = entry["canonical"]
        check("req_com2 [{}]".format(canonical), {"req_com2": [canonical]},
              {"req_com2": [canonical]})

    print("====4 全参数组合 data 级精确还原====")
    full_values = {
        "W1": 3400, "W2": 450, "support": 4, "m_brand": "FT",
        "material": "碳钢", "台面尺寸": [1.2, 1.5],
        "c_family": "3306", "c_brand": "FAB",
        "Ex_P": True, "required_ex": "IIBT4",
        "install": "面板式", "power": "DC24V",
        "安装形式": "分体", "分体仪表支架": "壁挂",
        "r_input": 3000, "e_input": 0.5,
        "vibration": True, "RPM": 200,
        "special_req": 2, "special_req2": True,
        "req_com1": ["RS232", "RS485"], "req_com2": ["PROFINET", "DP"],
    }
    full_expected = {
        "W1": 3400, "W2": 450, "support": 4, "m_brand": "FT",
        "material": "碳钢", "台面尺寸": "1.2x1.5",
        "c_family": "3306", "c_brand": "FAB",
        "Ex_P": True, "required_ex": "IIBT4",
        "install": "面板式", "power": "DC24V",
        "安装形式": "分体", "分体仪表支架": "壁挂",
        "r_input": 3000, "e_input": 0.5,
        "vibration": True, "RPM": 200,
        "special_req": 2, "special_req2": True,
        "req_com1": ["basic_2", "RTU_2", "RS232", "RS485"],
        "req_com2": ["PROFINET", "DP"],
    }
    check("全参数组合", full_values, full_expected, exact=True)

    print("====5 双向闭环：Parser 样例 -> parse -> sync -> parse 参数不变====")
    samples = [
        "报价，料重3.4t，皮重450kg，4支点，FT模块，碳钢。仪表3306，单通道，PN通信。",
        "平台秤，最大物料重量600kg，要检定，台面1米2x1米5，SS。防爆，TCP。",
        "FT模块,搅拌转速200rpm。防爆。DP通讯，FT仪表。",
        "模块，料重3吨，无搅拌，不检定，料重很重，皮重约0.5t，台面600×600。",
        "传感器SLB0。仪表FAB3300。接线盒KE-40，材质304不锈钢。",
        "3吨平台秤,富林泰克,台面1500*1500,碳钢。仪表3306,PN通信。",
        "1.5吨富林泰克平台秤,台面1米2x1米5,不锈钢。仪表3306,单通道。",
    ]
    for index, sample in enumerate(samples, start=1):
        first = parser.parse_quote_text(sample)
        rebuilt = sync_parser.sync_quote_text(first["data"])
        second = parser.parse_quote_text(rebuilt)

        if second["data"] == first["data"]:
            print("[OK]  样例{} -> {}".format(index, rebuilt))
        else:
            failures.append(("样例{} 闭环".format(index), None))
            print("[FAIL] 样例{}\n       原参数: {}".format(index, first["data"]))
            print("       重建文本: {}".format(rebuilt))
            print("       再参数:   {}".format(second["data"]))

    print("====6 非法输入拒绝====")
    expect_error("未知参数键", {"说明": "x"})
    expect_error("卡片字段混入", {"metrology": True})
    expect_error("非法尺寸", {"台面尺寸": "1.2"})
    expect_error("非正重量", {"W1": 0})
    expect_error("未知品牌", {"m_brand": "富林泰"})
    expect_error("未知协议", {"req_com2": ["XXX"]})
    expect_error("未知串口码", {"req_com1": ["USB"]})

    print("=" * 60)
    if failures:
        print("自测失败 {} 项".format(len(failures)))
        sys.exit(1)
    print("自测全部通过")
