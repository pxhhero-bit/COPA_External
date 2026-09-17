"""This is COPA_com_Parser, a Non-NLP/LLM parser based on plain text under professional input."""
import csv
import json
import os
import re
import sys

# 数据根目录：冻结打包后 config/data 随 exe 同目录手动摆放(保持源码结构)，
# 源码运行时按 Parser 自身位置定位，导入时不依赖工作目录
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_RULES_PATH = os.path.join(_ROOT_DIR, "config", "parser_rules.json")
_DEFAULT_SELECTION_RULES_PATH = os.path.join(_ROOT_DIR, "config", "selection_rules.json")
_DATA_DIR = os.path.join(_ROOT_DIR, "data")

# 全角数字/小数点 -> 半角，统一数值形态
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", "0123456789.")

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)")
# 值token：连续拉丁字母数字(含+-)或连续汉字，用于品牌/材质等文本值
_TOKEN_RE = re.compile(r"[A-Za-z0-9+\-]+|[\u4e00-\u9fff]+")

# CSV 兜底词表规格：(selection_rules 品牌库键, 取词列, 命中后写入的参数, 值取法, 附带列)
# 值取法："column:列名" 从CSV自身品牌列读取，"brand_key" 用品牌库的键(FT/AW/FAB)，
#         "self" 值即词条自身(材质等自描述列，如 mtl模块材质 的 SS/CS)
# 附带列：词条命中时从同行额外带出的字段(仪表词条附带 family 供二次识别仪表系列)
_CSV_VOCAB_SPEC = [
    ("controller_db", ("family", "nickname", "model_full"), "c_brand", "column:brand", ("family",)),
    ("sensor_db", ("family型号", "model型号"), "m_brand", "brand_key", ()),
    ("module_db", ("module模块型号",), "m_brand", "column:品牌", ()),
    ("module_db", ("mtl模块材质",), "material", "self", ()),
    ("jbox_db", ("model型号",), "m_brand", "column:品牌", ()),
]

# 词表中的无效占位值
_VOCAB_INVALID = {"", "0", "NA", "N/A", "-"}

# 永不命中的占位正则：词表未构建/构建失败时 _vocab_regex 仍恒为合法 Pattern(不落回 None)
_NEVER_MATCH_RE = re.compile(r"(?!x)x")

# 尺寸口语小数："1米2"x"1米5" = 1.2x1.5(米+分米口语表达)，匹配前归一为小数
_SIZE_COLLOQUIAL_RE = re.compile(r"(\d)米(\d)")

# text 取值两端可剥离的语气助词(全局filler已废除，仅保留取值边界的最小清理)
_TEXT_TRIM_CHARS = "的哈吧呢啊哦嗯了"


def _num(value):
    """浮点结果尽量收敛为整数(3400.0 -> 3400)，便于与 Engine 的 int 容量字段对齐"""
    rounded = round(value, 6)
    return int(rounded) if float(rounded).is_integer() else rounded


class Parser:

    def __init__(self, rules_path=_DEFAULT_RULES_PATH,
                 selection_rules_path=_DEFAULT_SELECTION_RULES_PATH):
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)

        self._component_re = self._build_delimiter_re(
            self.rules["delimiters"]["component"]
        )
        self._parameter_re = self._build_delimiter_re(
            self.rules["delimiters"]["parameter"]
        )

        self.parameters = self.rules["parameters"]
        self._negation_marks = tuple(self.rules.get("negation_marks", []))
        self._chinese_numerals = self.rules.get("chinese_numerals", {})
        # 中文数字字符类按 chinese_numerals 动态构建，表内加字(如 双)即生效
        self._chinese_num_re = re.compile(
            "[" + "".join(
                re.escape(ch) for ch in self._chinese_numerals
            ) + "]+"
        )

        # 每个参数的业务用语正则，保持 JSON 定义顺序(平手时先定义者优先)；
        # 无 term_pattern 的参数(如词表专供的 c_family)不参与正则识别
        self._term_patterns = [
            (param_id, re.compile(pdef["term_pattern"]))
            for param_id, pdef in self.parameters.items()
            if "term_pattern" in pdef
        ]

        # 裸品牌词表(brand 类参数 values 别名合并)：平台秤/台秤报价常把品牌
        # 写成独立片段或粘连在量程短语里，挂不上 传感器/模块/仪表 用语，
        # 由主流程二次识别扫描补位；词边界防型号前缀误命中(FTRDL 不触发 FT)
        brand_words = {}
        for pdef in self.parameters.values():
            if pdef.get("type") == "brand":
                for alias, canonical in pdef.get("values", {}).items():
                    brand_words[alias.lower()] = canonical

        self._brand_word_map = brand_words
        self._brand_word_re = re.compile(
            "(?<![A-Za-z0-9])(?:{})(?![A-Za-z0-9])".format(
                "|".join(
                    re.escape(alias)
                    for alias in sorted(brand_words, key=len, reverse=True)
                )
            ),
            re.IGNORECASE,
        ) if brand_words else _NEVER_MATCH_RE

        # 通讯协议词表(parser_rules.json 的 protocols 节)；
        # 带category的协议另作裸片段兜底词表(basic->req_com1, extended->req_com2)
        self._com_patterns = []
        self._com_fallback_patterns = []
        self._com_category = {}

        for entry in self.rules.get("protocols", []):
            compiled = re.compile(entry["pattern"])
            self._com_patterns.append((entry["canonical"], compiled))

            if entry.get("category"):
                self._com_category[entry["canonical"]] = entry["category"]
                self._com_fallback_patterns.append(
                    (entry["canonical"], entry["category"], compiled)
                )

        # req_com1 规则码推导配置：基础串口协议组合 -> com_1 词表代码(basic_1/RTU_2等)
        self._com1_code_rules = self.rules.get("com1_code", {})
        self._com1_coverage = self._com1_code_rules.get("coverage", {})
        self._modbus_count_re = re.compile(
            self._com1_code_rules.get(
                "modbus_count_pattern", r"(?!x)x"
            )
        )

        # CSV 兜底词表：首次用到时惰性构建；_vocab_built 为构建标记，
        # _vocab_regex 恒为合法 Pattern，静态类型不引入 Optional
        self._selection_rules_path = selection_rules_path
        self._vocab_built = False
        self._vocab_regex = _NEVER_MATCH_RE
        self._vocab_group_map = {}
        self._vocab_lookup = {}
        self._vocab_loose = {}

    @staticmethod
    def _build_delimiter_re(delimiters):
        chars = "".join(re.escape(d) for d in delimiters)
        return re.compile("[" + chars + "]")

    # ====1 文本切分与处理====

    def split_components(self, text):
        """一级切分：中文句号/换行区分不同组件，仅建立组件级边界"""
        parts = self._component_re.split(text or "")
        return [p.strip() for p in parts if p.strip()]

    def split_parameters(self, component):
        """二级切分：组件内部按逗号/顿号切出参数片段"""
        parts = self._parameter_re.split(component or "")
        return [p.strip() for p in parts if p.strip()]

    def _normalize(self, fragment):
        """片段预处理：全角转半角、去空白；仅用于匹配与取值，诊断保留原文。
        废话容忍不靠全局删除词，由 term_pattern 的容差与数值扫描的无关字符跳过实现"""
        cleaned = fragment.translate(_FULLWIDTH_DIGITS)
        return "".join(cleaned.split())

    # ====2 业务用语正则识别====

    def match_terms(self, cleaned):
        """返回片段内可并存的业务用语命中列表：按命中文本长度降序贪心选取，
        span与已选命中重叠的短用语被抑制("扩展通讯"压制其中的"通讯"、
        "防爆等级"压制"防爆")，不重叠的并存("搅拌转速200rpm" -> vibration + RPM)。
        返回 [(参数ID, match), ...]，同参数至多一个命中(search取最左)"""
        hits = []
        for order, (param_id, pattern) in enumerate(self._term_patterns):
            m = pattern.search(cleaned)
            if m is not None:
                hits.append((-len(m.group()), order, param_id, m))

        hits.sort(key=lambda h: (h[0], h[1]))
        accepted = []
        taken_spans = []

        for _, _, param_id, m in hits:
            start, end = m.span()
            overlaps = any(
                not (end <= s or start >= e) for s, e in taken_spans
            )
            if overlaps:
                continue
            accepted.append((param_id, m))
            taken_spans.append((start, end))

        return accepted

    def match_term(self, cleaned):
        """单个主命中(长度最长者优先)，供兼容调用；多命中场景用 match_terms"""
        terms = self.match_terms(cleaned)
        return terms[0] if terms else None

    def match_protocols(self, cleaned):
        """业务用语未命中时的裸协议兜底：按 com_protocols 的 category 归类，
        basic(RS232/RS485/Modbus)->req_com1，extended(TCP/DP/PN等)->req_com2"""
        found = {"req_com1": [], "req_com2": []}

        for canonical, category, pattern in self._com_fallback_patterns:
            if pattern.search(cleaned):
                bucket = "req_com1" if category == "basic" else "req_com2"
                found[bucket].append(canonical)

        found = {key: value for key, value in found.items() if value}
        return found or None

    def _modbus_count_in(self, cleaned):
        """提取"N路/N* modbus"的路数表达(如 2路modbus/1*modbus)，缺省按1路"""
        m = self._modbus_count_re.search(cleaned)
        return int(m.group(1)) if m else 1

    def _derive_com1_code(self, protocols, modbus_count):
        """基础串口协议组合 -> engine com_1 词表规则码：
        单一RS232/RS485 -> basic_1，RS232+RS485 -> basic_2，
        1路Modbus -> RTU_1，2路Modbus -> RTU_2；有Modbus时优先于串口组合判断"""
        rules = self._com1_code_rules

        if not protocols:
            return None

        if "Modbus" in protocols:
            if modbus_count >= 2:
                return rules.get("modbus_x2")
            return rules.get("modbus_x1")

        if "RS232" in protocols and "RS485" in protocols:
            return rules.get("dual_serial")

        if "RS232" in protocols or "RS485" in protocols:
            return rules.get("single_serial")

        return None

    def _expand_com1_code(self, code):
        """按 coverage 覆盖表把需求码展开为可接受的 com_1 规则码列表：
        RTU_2 覆盖 basic_2/basic_1，RTU_1 覆盖 basic_1(表驱动，engine 只做成员匹配)"""
        coverage = self._com1_coverage
        acceptable = [
            capability for capability, requirements in coverage.items()
            if code in requirements
        ]

        if code not in acceptable:
            acceptable.insert(0, code)

        return acceptable

    def default_req_com1(self):
        """缺省通讯需求：单一基础串口(basic_1)展开后的可接受码列表，供 Desk 兜底"""
        code = self._com1_code_rules.get("single_serial", "basic_1")
        return self._expand_com1_code(code)

    def derive_req_com1(self, protocols, modbus_count=1):
        """结构化输入(GUI下拉录入)的通讯需求推导，与文本解析同一链条：
        协议组合 -> com_1 规则码 -> 可接受码列表(+字面串口)。
        protocols 为基础串口协议(RS232/RS485/Modbus)序列，modbus_count 为
        Modbus 路数；无可推导组合(空协议)时返回 None，由调用方取缺省"""
        code = self._derive_com1_code(list(protocols), modbus_count)

        if not code:
            return None

        acceptable = self._expand_com1_code(code)
        # 字面串口协议随需求码附加，与 parse_quote_text 的出口同构
        acceptable += [p for p in ("RS232", "RS485") if p in protocols]
        return acceptable


    # ====3 未识别业务用语的数据库CSV兜底====

    def _ensure_vocab(self):
        """从 data/ 数据库CSV构建兜底词表：仪表系列/昵称/型号 -> c_brand，
        传感器系列/模块型号/接线盒型号 -> m_brand；文件缺失时跳过该库"""
        if self._vocab_built:
            return

        if not (self._selection_rules_path and os.path.exists(self._selection_rules_path)):
            self._vocab_built = True
            return

        with open(self._selection_rules_path, "r", encoding="utf-8") as f:
            brands = json.load(f).get("brands", {})

        entries = {}

        def add_term(term, param_id, value, source, extra=None):
            key = re.sub(r"\s+", "", term).lower()
            if len(key) < 2 or key in _VOCAB_INVALID:
                return
            entry = {
                "term": term, "parameter": param_id,
                "value": value, "source": source,
            }
            if extra:
                entry.update(extra)
            # 同词多库命中时保留先登记者
            entries.setdefault(key, entry)

        def read_rows(filename):
            path = os.path.join(_DATA_DIR, filename)
            if not os.path.exists(path):
                return []
            # utf-8-sig 兼容带BOM的CSV(如COPA A传感器)
            with open(path, "r", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))

        for db_key, columns, param_id, brand_mode, extra_cols in _CSV_VOCAB_SPEC:
            db_setting = brands.get(db_key)
            if db_setting is None:
                continue
            # 品牌库键可能是 {品牌: 文件} 字典，也可能是单文件字符串
            files = ([(brand, file) for brand, file in db_setting.items()]
                     if isinstance(db_setting, dict) else [(None, db_setting)])
            for brand, filename in files:
                for row in read_rows(filename):
                    if brand_mode == "brand_key":
                        brand_value = brand
                    elif brand_mode == "self":
                        brand_value = None
                    else:
                        brand_value = (row.get(brand_mode.split(":", 1)[1]) or "").strip()
                    for col in columns:
                        term = (row.get(col) or "").strip()
                        value = term if brand_mode == "self" else brand_value
                        if value:
                            extra = {
                                col_name: (row.get(col_name) or "").strip()
                                for col_name in extra_cols
                                if (row.get(col_name) or "").strip()
                            }
                            add_term(term, param_id, value, filename, extra)

        # 单一巨型正则 + 命名分组，匹配一次即可定位词表命中；长词优先。
        # 无横线收编：含"-"的词条同时注册去横线变体(FT-210→FT210)，
        # 手输/口语的无横线写法同样命中并归一到原词条，既有词表不受影响
        pairs = []
        seen_texts = set()
        for key in sorted(entries, key=len, reverse=True):
            entry = entries[key]
            if entry["term"] not in seen_texts:
                pairs.append((key, entry["term"], entry))
                seen_texts.add(entry["term"])
            if "-" in key:
                loose = key.replace("-", "")
                if loose not in seen_texts and loose not in entries:
                    pairs.append((key, loose, entry))
                    seen_texts.add(loose)
        pairs.sort(key=lambda p_: len(p_[1]), reverse=True)

        parts = []
        group_map = {}
        self._vocab_lookup = {}
        for index, (key, text, entry) in enumerate(pairs):
            group = "v{}".format(index)
            group_map[group] = entry
            parts.append("(?P<{}>{})".format(group, re.escape(text)))
            self._vocab_lookup.setdefault(key, entry)

        # 去横线 loose 检索索引(品牌/系列反查用；精确键优先)
        self._vocab_loose = {}
        for key, entry in entries.items():
            if "-" in key:
                self._vocab_loose.setdefault(key.replace("-", ""), entry)

        self._vocab_group_map = group_map
        self._vocab_regex = re.compile(
            "(?<![A-Za-z0-9])(?:{})(?![A-Za-z0-9])".format("|".join(parts)),
            re.IGNORECASE,
        ) if parts else _NEVER_MATCH_RE
        self._vocab_built = True

    def match_vocab(self, cleaned):
        """片段未命中任何 term_pattern 时，在数据库CSV词表中查找产品型号/系列词，
        词表条目自带品牌映射；返回条目或 None"""
        self._ensure_vocab()
        m = self._vocab_regex.search(cleaned)
        if m is None:
            return None
        return self._vocab_group_map[m.lastgroup]

    def _vocab_entry(self, token):
        """词条反查：精确键优先，其次去横线 loose 键(FT210→FT-210词条)；
        供品牌/系列识别容错手输的无横线写法"""
        self._ensure_vocab()
        key = re.sub(r"\s+", "", token).lower()
        entry = self._vocab_lookup.get(key)
        if entry is None:
            entry = self._vocab_loose.get(key.replace("-", ""))
        return entry

    def _brand_word_in(self, text):
        """裸品牌词扫描：返回 (命中别名, 标准品牌) 或 None，供主流程二次识别"""
        m = self._brand_word_re.search(text)
        if m is None:
            return None
        return (m.group(), self._brand_word_map[m.group().lower()])

    # ====5 数值提取====

    def extract_value(self, param_id, match, cleaned):
        """按参数类型从业务用语前/后文本提取值，返回 (值, 附加字段) 或 None"""
        param_def = self.parameters[param_id]
        ptype = param_def["type"]
        prefix = cleaned[:match.start()]
        suffix = cleaned[match.end():]

        if ptype == "flag":
            # 命名即 True；业务用语前紧邻否定词(不带搅拌/无需检定)视为 False
            return (not prefix.endswith(self._negation_marks), {})

        if ptype == "weight":
            unit_table = self.rules["units"]["weight"]
            # 值优先取用语自身携带的数值+单位("2吨平台秤"式量程表达)，
            # 再用语之后("料重3.4吨")，最后回看用语之前("FT模块"式的品牌同理见brand分支)
            value = self._weight_in(match.group(), unit_table, prefer_last=True)
            if value is None:
                value = self._weight_in(suffix, unit_table)
            if value is None:
                value = self._weight_in(prefix, unit_table, prefer_last=True)
            if value is None or value <= 0:
                return None
            return (_num(value), {"unit": "kg"})

        if ptype == "integer":
            # 前缀侧取最后一个数字("3支点"/"三个支点")，后缀侧取第一个("支点数3")
            value = self._int_in(suffix)
            if value is None:
                value = self._int_in(prefix, prefer_last=True)
            if value is None:
                return None
            minimum = param_def.get("min")
            if minimum is not None and value < minimum:
                return None
            return value

        if ptype == "brand":
            token = self._token_in(suffix) or self._token_in(prefix, prefer_last=True)
            if not token:
                return None
            value = self._brand_value(token, param_def)

            if value is None:
                return None

            # 二次识别：品牌token经CSV词表反查命中时(如 仪表3306 -> FAB)，
            # 派生用户点名的系列标识本身("仪表3306" -> c_brand=FAB + c_family=3306)，
            # 不放大到 family 大类(FAB330 同时含 3300/3306，会放宽收敛)；
            # 无横线写法(FT210)经 loose 索引命中后派生规范词条(FT-210)
            if param_id == "c_brand":
                entry = self._vocab_entry(token)

                if entry is not None and entry.get("family"):
                    return (value, {"derived": {
                        "c_family": entry["term"],
                    }})

            return value

        if ptype == "text":
            values = param_def.get("values", {})

            # 用语自身即值(碳钢/不锈钢/混合等裸材质词)，直接归一输出
            if match.group() in values:
                return values[match.group()]

            # 文本值取用语后整段剩余(如"iibt4")，用语后才为空时回看前缀
            raw = (suffix or prefix).strip(_TEXT_TRIM_CHARS)

            if not raw:
                return None

            # 值文本含已知值词则归一("304不锈钢" -> 不锈钢)
            for word, canonical in values.items():
                if word in raw:
                    return canonical

            return raw.upper()

        if ptype == "size":
            # 候选范围：用语前后，必要时含用语自身；口语尺寸("1米2x1米5")先归一为小数
            scope = _SIZE_COLLOQUIAL_RE.sub(r"\1.\2", prefix + match.group() + suffix)
            m = _SIZE_RE.search(scope)

            if not m:
                m = _SIZE_RE.search(_SIZE_COLLOQUIAL_RE.sub(r"\1.\2", cleaned))

            if not m:
                return None
            return "{}x{}".format(m.group(1), m.group(2))

        if ptype == "option":
            # 选项词可能在用语前后("分体安装"/"供电DC24V")，也可能就是用语本身("导轨式"/"壁挂支架")
            scope = prefix + match.group() + suffix
            for option in param_def.get("options", []):
                if option in scope:
                    return option
            return None

        if ptype == "com_list":
            found = [
                canonical for canonical, pattern in self._com_patterns
                if pattern.search(cleaned)
            ]
            if param_id == "req_com1":
                # req_com1 只汇总基础串口协议(RS232/RS485/Modbus)，
                # 主流程跨片段累计后统一推导 com_1 规则码(basic_1/basic_2/RTU_1/RTU_2)
                basics = [
                    canonical for canonical in found
                    if self._com_category.get(canonical) == "basic"
                ]
                if not basics:
                    return None
                count = (self._modbus_count_in(cleaned)
                         if "Modbus" in basics else 0)
                return (basics, {"modbus_count": count})
            return found or None

        return None

    def _read_unit(self, text, pos, unit_table):
        """从 pos 起读取一个单位词，长单位优先(千克/公斤/kg 优先于 g/克)"""
        for unit in sorted(unit_table, key=len, reverse=True):
            if text.startswith(unit, pos):
                return unit
        return None

    def _weight_in(self, text, unit_table, prefer_last=False):
        """在一段文本中提取 数值+单位 并换算为 kg；无单位数值按 kg；找不到返回 None"""
        if not text:
            return None
        matches = list(_NUMBER_RE.finditer(text))
        ordered = reversed(matches) if prefer_last else matches
        for m in ordered:
            unit = self._read_unit(text, m.end(), unit_table)
            if unit:
                return float(m.group()) * unit_table[unit]
        if matches:
            plain = matches[-1] if prefer_last else matches[0]
            return float(plain.group())
        return None

    def _int_in(self, text, prefer_last=False):
        """提取整数：阿拉伯数字优先，其次中文数字(三/双/十/十二/二十三，<=99)"""
        if not text:
            return None
        matches = list(_NUMBER_RE.finditer(text))
        if matches:
            m = matches[-1] if prefer_last else matches[0]
            return int(m.group())
        runs = self._chinese_num_re.findall(text)
        if runs:
            run = runs[-1] if prefer_last else runs[0]
            return self._chinese_to_int(run)
        return None

    def _chinese_to_int(self, text):
        """中文数字转整数，支持 一/两/十/十二/二十/二十三 等两位数表达"""
        table = self._chinese_numerals
        if "十" in text:
            parts = text.split("十")
            if len(parts) != 2:
                return None
            left, right = parts
            tens = self._chinese_to_int(left) if left else 1
            ones = self._chinese_to_int(right) if right else 0
            if tens is None or ones is None:
                return None
            return tens * 10 + ones
        total = 0
        for ch in text:
            if ch not in table:
                return None
            total = total * 10 + table[ch]
        return total

    def _token_in(self, text, prefer_last=False):
        """提取一个连续 token(拉丁数字串或汉字串)，用于品牌/材质等文本值"""
        if not text:
            return None
        matches = list(_TOKEN_RE.finditer(text))
        if not matches:
            return None
        m = matches[-1] if prefer_last else matches[0]
        return m.group()

    def _brand_value(self, token, param_def):
        """品牌取值三级链：参数 values 表 -> 数据库CSV词表(系列/型号反查品牌，如 3306->FAB、SLB->FT)
        -> 拉丁token原样大写透传；中文token不在已知集合则视为无有效值(合法性校验归 Engine/数据库)"""
        values = param_def.get("values", {})
        lookup = {key.lower(): value for key, value in values.items()}
        if token.lower() in lookup:
            return lookup[token.lower()]

        entry = self._vocab_entry(token)
        if entry is not None:
            return entry["value"]

        if token.isascii():
            return token.upper()
        return None

    # ====6 主流程====

    def parse_quote_text(self, text):
        """解析主入口：切分 -> 业务用语识别 -> CSV兜底 -> 诊断收集 -> 数值提取，
        输出标准参数 data 与 recognized/unrecognized/warnings 诊断"""
        data = {}
        recognized = []
        unrecognized = []
        warnings = []
        com1_protocols = []
        modbus_count = 0
        bare_brands = []

        for component in self.split_components(text):
            for fragment in self.split_parameters(component):
                outcomes = self._parse_fragment(fragment) or [None]
                # 片段是否已产出品牌参数：已产出(FT模块/仪表3306/SLB0)时
                # 裸品牌词不再介入，避免把仪表品牌误补成秤台/传感器品牌
                has_brand_param = False
                unresolved = False

                for outcome in outcomes:
                    if outcome is None:
                        continue

                    if outcome["kind"] == "unrecognized":
                        unresolved = True
                        continue

                    if outcome["kind"] == "warning":
                        warnings.append({
                            "text": fragment,
                            "parameter": outcome["parameter"],
                            "reason": outcome["reason"],
                        })
                        continue

                    param_id = outcome["parameter"]

                    if param_id in ("m_brand", "c_brand"):
                        has_brand_param = True

                    entry = {
                        "text": fragment,
                        "parameter": param_id,
                        "term": outcome["term"],
                        "source": outcome["source"],
                        "value": outcome["value"],
                    }
                    entry.update(outcome.get("extra", {}))
                    recognized.append(entry)

                    if param_id == "req_com1":
                        # 基础串口协议跨片段累计(去重保序)，
                        # 全部片段处理完后统一推导 com_1 规则码
                        for protocol in outcome["value"]:
                            if protocol not in com1_protocols:
                                com1_protocols.append(protocol)
                        modbus_count = max(
                            modbus_count, entry.get("modbus_count", 0)
                        )
                        continue

                    if param_id in data:
                        old_value = data[param_id]
                        new_value = outcome["value"]

                        if isinstance(old_value, list) and isinstance(new_value, list):
                            # 列表参数(通讯协议)跨片段合并，去重保序
                            data[param_id] = old_value + [
                                x for x in new_value if x not in old_value
                            ]
                        elif old_value != new_value:
                            warnings.append({
                                "text": fragment,
                                "parameter": param_id,
                                "reason": "参数重复，后值覆盖前值({} -> {})".format(
                                    old_value, new_value
                                ),
                            })
                            data[param_id] = new_value
                    else:
                        data[param_id] = outcome["value"]

                # 裸品牌词二次识别("3吨平台秤,富林泰克"的独立片段、
                # "3吨富林泰克平台秤"的量程粘连短语)：片段未产出品牌参数时
                # 扫描品牌别名词表，全部片段处理完后再归属到空位品牌槽
                if not has_brand_param:
                    hit = self._brand_word_in(self._normalize(fragment))

                    if hit is not None:
                        bare_brands.append((fragment, hit))
                        unresolved = False

                if unresolved:
                    unrecognized.append(fragment)

        # 裸品牌词归属：m_brand 优先(秤台/传感器品牌先于仪表品牌)，已填则
        # 补 c_brand；两槽都已填时无法归属，如实记入未识别
        for fragment, (alias, canonical) in bare_brands:
            if "m_brand" not in data:
                slot = "m_brand"
            elif "c_brand" not in data:
                slot = "c_brand"
            else:
                unrecognized.append(fragment)
                continue

            data[slot] = canonical
            recognized.append({
                "text": fragment,
                "parameter": slot,
                "term": alias,
                "source": "brand_word",
                "value": canonical,
            })

        com1_code = self._derive_com1_code(com1_protocols, modbus_count)

        if com1_code:
            acceptable = self._expand_com1_code(com1_code)
            # 字面串口协议随需求码附加：engine 据此直配 com_1 写作 'RS232'/'RS485'
            # 的单串口仪表(见 engine.m_ctrler_com_fliter 的字面串口兜底)
            acceptable += [p for p in ("RS232", "RS485") if p in com1_protocols]
            data["req_com1"] = acceptable
            recognized.append({
                "text": "",
                "parameter": "req_com1",
                "term": "推导:{}(可接受{})".format(com1_code, "+".join(acceptable)),
                "source": "com1_code",
                "value": acceptable,
            })

        self._apply_required_ex_implication(data, recognized)

        # 总重归一：业务口径"总重=最大料重+皮重"(用户只知总和不知拆分)——
        # 按约定拆为 W1=总重、W2=0 传入 engine(模块线容量/SF 仅用 W1+W2，
        # W2=0 即"皮重未拆分"信号，Desk 开始选型据此弹确认框)；
        # 与料重/皮重同时出现视为口径冲突，以显式拆分值为准并忽略总重
        if "W_total" in data:
            total = data.pop("W_total")

            if "W1" in data or "W2" in data:
                warnings.append({
                    "text": "、".join(
                        e["text"] for e in recognized
                        if e["parameter"] == "W_total"
                    ),
                    "parameter": "W_total",
                    "reason": "总重与料重/皮重同时出现，按料重/皮重为准忽略总重",
                })
            else:
                data["W1"] = total
                data["W2"] = 0

                for e in recognized:
                    if e["parameter"] == "W_total":
                        e["parameter"] = "W1"
                        e["source"] = "total_weight"

                recognized.append({
                    "text": "",
                    "parameter": "W2",
                    "term": "总重拆分",
                    "source": "total_weight",
                    "value": 0,
                })

        return {
            "data": data,
            "recognized": recognized,
            "unrecognized": unrecognized,
            "warnings": warnings,
        }

    def _parse_fragment(self, fragment) -> list[dict]:
        """处理单个参数片段，返回结果字典列表(一个片段可含多个不重叠的业务用语，
        如"搅拌转速200rpm" -> [vibration, RPM])；纯空白片段返回空列表"""
        cleaned = self._normalize(fragment)
        if not cleaned:
            return []

        # 2. 业务用语正则识别(多命中，重叠抑制)
        term_hits = self.match_terms(cleaned)

        # 3. 未识别的业务用语先做裸协议兜底，再到数据库CSV词表匹配
        if not term_hits:
            protocol_hits = self.match_protocols(cleaned)

            if protocol_hits is not None:
                results = []

                for param_id, protocols in protocol_hits.items():
                    extra = ({"modbus_count": self._modbus_count_in(cleaned)}
                             if param_id == "req_com1" and "Modbus" in protocols
                             else {})
                    results.append({
                        "kind": "recognized",
                        "parameter": param_id,
                        "term": "+".join(protocols),
                        "source": "protocols",
                        "value": protocols,
                        "extra": extra,
                    })

                return results

            vocab_hit = self.match_vocab(cleaned)

            if vocab_hit is not None:
                outcomes = [{
                    "kind": "recognized",
                    "parameter": vocab_hit["parameter"],
                    "term": vocab_hit["term"],
                    "source": vocab_hit["source"],
                    "value": vocab_hit["value"],
                }]
                # 二次识别：仪表词条派生用户点名的系列标识(如 3306 -> "3306")，
                # 不放大到 family 大类(FAB330 同时含 3300/3306，会放宽收敛)
                if vocab_hit["parameter"] == "c_brand" and vocab_hit.get("family"):
                    outcomes.append({
                        "kind": "recognized",
                        "parameter": "c_family",
                        "term": vocab_hit["term"],
                        "source": vocab_hit["source"],
                        "value": vocab_hit["term"],
                    })
                return outcomes
            # 4. 依旧无法识别 -> diagnostic
            return [{"kind": "unrecognized"}]

        outcomes = []

        # 5. 逐个识别到的业务用语提取数值
        for param_id, match in term_hits:
            value = self.extract_value(param_id, match, cleaned)

            if value is None:
                outcomes.append({
                    "kind": "warning",
                    "parameter": param_id,
                    "reason": "识别到参数[{}]，但未提取到合法值".format(param_id),
                })
                continue

            extra = {}
            if isinstance(value, tuple):
                value, extra = value

            outcomes.append({
                "kind": "recognized",
                "parameter": param_id,
                "term": match.group(),
                "source": "regex",
                "value": value,
                "extra": extra,
            })

            # 派生参数(如 仪表系列 c_family)并入本片段结果
            for derived_id, derived_value in extra.pop("derived", {}).items():
                outcomes.append({
                    "kind": "recognized",
                    "parameter": derived_id,
                    "term": match.group(),
                    "source": "derived",
                    "value": derived_value,
                })

        return outcomes

    def _apply_required_ex_implication(self, data, recognized):
        """防爆等级蕴含防爆：提取到 required_ex 而 Ex_P 未被显式说明时补 True，
        否则 Engine 会按非防爆筛选而漏掉防爆型号"""
        if "required_ex" in data and "Ex_P" not in data:
            data["Ex_P"] = True
            recognized.append({
                "text": "",
                "parameter": "Ex_P",
                "term": "由防爆等级推断",
                "source": "implication",
                "value": True,
            })

    # ====兼容别名====
    parse = parse_quote_text


# ====便捷入口====
def parse_quote_text(text, rules_path=_DEFAULT_RULES_PATH):
    """函数式便捷入口；Commander 常驻场景建议复用 Parser 实例(CSV词表只构建一次)"""
    return Parser(rules_path).parse_quote_text(text)


# ====自测====
if __name__ == "__main__":
    samples = [
        # 例句1
        "报价，料重3.4t，皮重450kg，4支点，FT模块，碳钢。仪表3306，单通道，PN通信。",
        # 例句2
        "平台秤，最大物料重量600kg，要检定，台面1米2x1米5，SS。防爆，TCP。",
        # 例句3
        "FT模块,搅拌转速200rpm。防爆。DP通讯，FT仪表。",
        # 反义与异常输入
        "模块，料重3吨，无搅拌，不检定，料重很重，皮重约0.5t，台面600×600。",
        # CSV词表兜底
        "传感器SLB0。仪表FAB3300。接线盒KE-40，材质304不锈钢。",
        # 平台秤：裸品牌词二次识别(独立片段 / 量程粘连短语)
        "3吨平台秤,富林泰克,台面1500*1500,碳钢。仪表3306,PN通信。",
        "1.5吨富林泰克平台秤,台面1米2x1米5,不锈钢。仪表3306,单通道。",
    ]

    parser = Parser()

    for sample in samples:
        print("=" * 60)
        print("原文：{}".format(sample))
        result = parser.parse_quote_text(sample)

        for entry in result["recognized"]:
            print("已识别：{} <- [{}|{}] {} = {}".format(
                entry["parameter"], entry["term"], entry["source"],
                entry["text"] or "(推断)", entry["value"]
            ))
        for text in result["unrecognized"]:
            print("未识别：{}".format(text))
        for warning in result["warnings"]:
            print("警告：[{}] {} ({})".format(
                warning["parameter"], warning["text"], warning["reason"]
            ))

        print("-" * 60)
        print(json.dumps(result["data"], ensure_ascii=False, indent=2))
