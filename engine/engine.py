"""This is COPA_engine_v2.1, a copilot system prototype(engine part) for selecting weighing sensors by Hero Pang.
v2.1: 增加数字化方案以及AW模块线的选型支持，AW仪表仍为占位待补。
v2.0: 仪表系列收敛——module_data.c_family(Parser 二次识别的用户点名系列标识，如 3306/FAB330)
      在仪表筛选的品类 family_pass 之后按 family/nickname 精确匹配(忽略大小写)，未提供时不生效；
      load_controllers 将 nickname 提升为标准字段供匹配。
"""
import json
import csv
import math
import os
import sys

# 数据根目录：冻结打包后 config/data 随 exe 同目录手动摆放(保持源码结构)，
# 源码运行时按引擎文件自身位置定位，导入时不再依赖工作目录
if getattr(sys, "frozen", False):
    _ROOT_DIR = os.path.dirname(sys.executable)
else:
    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DATA_DIR = os.path.join(_ROOT_DIR, "data")

# ====规则引擎====
class COPAResolver:

    def __init__(self, rules_path=os.path.join(
            _ROOT_DIR, "config", "selection_rules.json")):
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)

    def get_target_sf(self, W1, W2):
        """用于计算皮料比"""
        logic = self.rules['sensor_logic']['SF_adjustment']
        if W2 > 0 and (W1 / W2) < logic['low_ratio_threshold']:
            return logic['optimized_SF']
        return logic['default_SF']
        

    def verify_sf_status(self, current_sf):
        """用于计算sf区间"""
        zones = self.rules['SF_verification']['sf_zones']
        for zone in zones:
            if zone['min'] <= current_sf < zone['max']:
                return zone  # 返回包含 color, status, desc 的字典
        return {"color": "Red", "status": "Extreme", "desc": "安全系数过小（SF<1.3），请立即修改"}

    def get_sag(self, RPM):
        """用于判断是否需要拉杆"""
        vibration = self.rules['sag_logic']['vibration_filter']
        if RPM >= vibration['high_speed_threshold']:
            return True
        return False

    def get_formula_text(self):
        """用于 GUI 显示单传感器容量计算公式"""
        return self.rules['sensor_calculation']['formula_display']

    def resolve_item_type(self, user_input):
        """将条目的产品名称转换为 Engine 内部条目类型(品类代码)"""
        mapping = self.rules["item_types"]
        if user_input not in mapping:
            raise ValueError("暂不支持该品类的选型")
        return mapping[user_input]



# ====数据库自检流程====
def validate_database(resolver, sensors_db, modules_db, jbox_db, controller_db):
    rules = resolver.rules.get("database_validation", {})
    if not rules.get("enabled", False):
        return

    print("\n=== 数据库自检启动 ===")

    module_rules = rules.get("module_database", {})
    if module_rules.get("check_duplicates", False):
        seen = set()
        duplicates = []
        keys = module_rules["duplicate_key"]
        for m in modules_db:
            key = tuple(m[k] for k in keys)
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)

        if duplicates:
            print("\n[警告] 模块数据库存在重复记录，请修复：")
            for d in duplicates:
                print(d)
            raise SystemExit

    sensor_rules = rules.get("sensor_database", {})
    if sensor_rules.get("check_duplicates", False):
        seen = set()
        duplicates = []
        keys = sensor_rules["duplicate_key"]
        for s in sensors_db:
            key = tuple(s[k] for k in keys)
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)

        if duplicates:
            print("\n[警告] 传感器数据库存在重复记录，请修复：")
            for d in duplicates:
                print(d)
            raise SystemExit

    jbox_rules = rules.get("jbox_database", {})
    if jbox_rules.get("check_duplicates", False):
        seen = set()
        duplicates = []
        keys = jbox_rules["duplicate_key"]
        for j in jbox_db:
            key = tuple(j[k] for k in keys)
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)

        if duplicates:
            print("\n[警告] 接线盒数据库存在重复记录，请修复：")
            for d in duplicates:
                print(d)
            raise SystemExit

    print("=== 数据库自检完成，开始选型计算 ===\n")

# ====运算函数====
def calculate_capacity(W1, W2, support):
    return (W1 + W2) * 1.5 / support

def calculate_safety_factor(W1, W2, support, cap):
    return (cap * support) / (W1 + W2)

def difference(sensor, best_sf):
    return round(abs(sensor["SF"] - best_sf), 2)

def float_equal(a, b, tol=0.01):
    return abs(a - b) <= tol

# ====格式函数====
def install_suffix(sensor):
     if sensor['安装方式'] == "盲孔安装":
        return "-BH"
     return ""

#RC3 formatting
def format_capacity(sensor):
    family = sensor["family型号"]
    if family == "RC3" or family.startswith("AW"):
        # RC3 与COPA A(AWB/AWBS/AWC/AWD)系列容量以吨表示(0.1t/0.2t/0.5t/1t…)
        format_t = sensor["capacity容量"] / 1000
        text = "{}t".format(int(format_t) if format_t.is_integer()
                            else format_t)
        return text if family == "RC3" else text + install_suffix(sensor)
    return f'{sensor["capacity容量"]}kg{install_suffix(sensor)}'

def ex_suffix(sensor):
    return " EX" if sensor["EX_bool"] else ""

def y_suffix(sensor, all_sensors):
    y_values = {i["Y值"] for i in all_sensors if i["family型号"] == sensor["family型号"]}
    return f" Y={sensor['Y值']}" if len(y_values) > 1 else ""

def material_suffix(material, module):
    if material in ["CS", "碳钢", "C"] and module["品牌"] == "FT":
        return "CS"
    if material in ["SS", "不锈钢", "S"] and module["品牌"] == "FT":
        return "SS"
    if material in ["CS", "碳钢", "C"] and module["品牌"] == "AW":
        return "C"
    if material in ["SS", "不锈钢", "S"] and module["品牌"] == "AW":
        return "S"
    else:
        return "模块材质数据错误"

def sag_suffix(module, sag_on):
    if sag_on and module.get("sag拉杆", 0) == 1:
        return "L"
    return ""

resolver = COPAResolver()


# ====用户输入====

def parse_list_input(user_input):
    if not user_input.strip():
        return None
    return [x.strip().upper() for x in user_input.split(",")]


# def build_user_input():
#     """统一输入适配层（CLI版，可直接迁移GUI/COPA_com）"""
#  #=====================================================
#     item_type_rules = resolver.rules["item_types"]
#     print("\n可选型产品品类：")
#     for name in item_type_rules:
#         print(name)
#     item_input = input("请输入条目类型：").strip()
#     try:
#         item_type = resolver.resolve_item_type(item_input)
#     except ValueError as e:
#         print(e)
#         exit()

#     Ex_P= input("是否需要防爆？（是/否/y/n）：").strip().lower() in ['是', 'y']
#     requried_ex = (input("请输入具体需要的防爆等级，直接回车为IIBT4：").strip().upper() or "IIBT4"
#                    ) if Ex_P else False
#     if item_type == "module":
#         W1 = float(input("请输入最大物料重量（kg）："))
#         W2 = float(input("请输入设备皮重（kg）："))
#         support = int(input("请输入支撑点数："))
#         material = input("请输入模块材质（中文/缩写）：").strip().upper()
#         Vibration = input("是否带搅拌？（是/否/y/n）：").strip().lower() in ['是', 'y']
#         RPM = int(input("请输入搅拌转速（RPM）：")) if Vibration else 0
#         metrology = input("是否需要检定?（是/否/y/n）：").strip().lower() in ['是', 'y']
#         special_req = input("是否需要多通道仪表？（y/n，默认n，回车跳过）：").strip().lower() == "y"
#         special_req2 = False
#         platform_size = None
#         high_precision = False
#         e_input = None

#     elif item_type == "platform":
#         W1 = float(input("请输入最大物料重量（kg）："))
#         platform_size = input("请输入台面尺寸（如600x600，回车跳过）：").strip() or None
#         material = input("请输入材质要求（中文/缩写）：").strip().upper()
#         high_precision = input("是否需要高精度平台秤？（是/否/y/n，默认否）：").strip().lower() in ['是', 'y']
#         e_req_raw = input("是否有精度（e值）要求?（kg，回车跳过）").strip()
#         e_input = float(e_req_raw) if e_req_raw else None
#         metrology = input("是否需要检定?（是/否/y/n）：").strip().lower() in ['是', 'y']
#         special_req = input("是否需要多通道仪表？（y/n，默认n，回车跳过）：").strip().lower() == "y"
#         special_req2 = input("仪表是否需要电池供电？（y/n，默认n，回车跳过）：").strip().lower() == "y"
#         Vibration = False
#         RPM = None
#         support = None
#         W2 = None

#     elif item_type == "bench":
#         W1 = float(input("请输入最大物料重量（kg）："))
#         platform_size = input("请输入台面尺寸（如600x600，回车跳过）：").strip() or None
#         material = input("请输入材质要求（中文/缩写）：").strip().upper()
#         high_precision = input("是否需要高精度台秤？（是/否/y/n，默认否）：").strip().lower() in ['是', 'y']
#         e_req_raw1 = input("是否有精度（e值）要求?（g，回车跳过）").strip()
#         e_input = float(e_req_raw1) * 0.001 if e_req_raw1 else None
#         metrology = input("是否需要检定?（是/否/y/n）：").strip().lower() in ['是', 'y']
#         install_form = input("一体安装还是分体安装？（一体/分体，回车默认一体）：").strip() or "一体"
#         if install_form == "分体":
#             split_bracket = input("分体安装请选择仪表支架（壁挂支架/立杆支架）：").strip() or None
#         else:
#             split_bracket = None
#         # 台秤不问多通道，直接问电池选项(special_req2)
#         special_req = False
#         special_req2 = input("仪表是否需要电池供电？（y/n，默认n，回车跳过）：").strip().lower() == "y"
#         Vibration = False
#         RPM = None
#         support = None
#         W2 = None

#     elif item_type in ["truck_A","truck_D"]:
#         W1 = float(input("请输入最大车重（t）："))
#         platform_lenth = input("请输入秤台长度（如18m）：").strip() or None
#         material = input("请输入材质要求（中文/缩写）：").strip().upper()
#         metrology = True
#         special_req = False
#         special_req2 = False
#         Vibration = False
#         RPM = None
#         support = None
#         W2 = None
#         platform_size = None
#         high_precision = False
#         e_input = None
#     else:
#         print("条目类型错误，请检查输入及条目类型是否受支持。")
#         exit()

#     if item_type != "bench":
#         install_form = "一体"
#         split_bracket = None

#     # ====品牌选择====
#     brand_rules = resolver.rules["brands"]
#     available_brands = brand_rules["available_brands"]

#     m_brand = input(f"请选择传感器品牌 {available_brands}：").strip().upper()
#     if m_brand not in available_brands:
#         print("目前仅支持FT与AW相关品牌，请更新数据库后再试。")
#         exit()
#     c_brand = input(f"请选择仪表品牌{available_brands}：").strip().upper()
#     if c_brand not in available_brands:
#         print("目前仅支持FT与AW相关品牌，请更新数据库后再试。")
#         exit()

#     # ===== 仪表参数输入 =====
#     req_com1 = parse_list_input(
#         input("请输入基础通讯需求（RS232/RS485/逗号分隔，回车跳过）：")
#     )
#     req_com2 = parse_list_input(
#         input("请输入扩展通讯需求（['TCP','ANALOG','DP','PROFINET','IP','CAT']，回车跳过）：")
#     )
#     install = input("仪表安装方式（回车跳过）：").strip() or None
#     power = input("仪表供电方式（默认AC220V）：").strip() or "AC220V"

#     bracket_input = input("支架类型？（立杆支架/壁挂支架，回车跳过支架要求）：").strip() or None

#     #输入结果返回
#     return {
#         "module_data":{
#             "item_type": item_type,
#             "W1": W1,
#             "W2": W2,
#             "support": support,
#             "Ex_P": Ex_P,
#             "required_ex": requried_ex,
#             "material": material,
#             "vibration": Vibration,
#             "RPM": RPM,
#             "台面尺寸": platform_size,
#             "高精度": high_precision,
#             "e_input": e_input,
#             "安装形式": install_form,
#             "分体仪表支架": split_bracket,
#             "m_brand": m_brand,
#             "c_brand": c_brand,
#         },
#         "metrology": {
#             "metrology": metrology,
#             "r_input": None,
#             "e_input": e_input
#         },
#         "com": {
#             "req_com1": req_com1,
#             "req_com2": req_com2,
#             "special_req": special_req,
#             "special_req2": special_req2
#         },
#         "hardware": {
#             "install": install,
#             "power": power,
#             "bracket": bracket_input
#         }
#     }


#     if support is not None and support <= 0:
#         print("支撑点数必须大于0")
#         exit()

#产品线流程分层定义
def run_engine(
    user_input,
    resolver,
    databases,
    quote_id = None,
):
    sensors_db = databases["sensors"]
    modules_db = databases.get("modules")
    jbox_db = databases["jbox"]
    platforms_db = databases.get("platforms")
    benches_db = databases.get("benches")
    controller_db = databases["controllers"]
    module_data = user_input["module_data"]
    item_type = user_input["module_data"]["item_type"]
    # 1.计量模块（平台秤/台秤的量程与分度值直接取自通表，跳过metrology）
    if item_type in ["platform", "bench"]:
        metrology_result = {
            "status": "SKIPPED",
            "reason": "平台秤/台秤不走metrology模块，量程与分度值取自通表",
        }
    else:
        metrology_engine = MetrologyEngine(resolver.rules)
        metrology_data = user_input["metrology"]
        try:
            metrology_result = metrology_engine.run(
                W1=module_data["W1"],
                r_input=metrology_data["r_input"],
                e_input=metrology_data["e_input"],
                metrology=metrology_data["metrology"]
            )
        except ValueError as err:
            metrology_result = {"error": str(err)}
    # 2.产品线pipeline
    if item_type == "module":
        product_result = run_module(
            user_input=user_input,
            resolver=resolver,
            sensors_db=sensors_db,
            modules_db=modules_db,
            jbox_db=jbox_db,
            controller_db=controller_db,
        )
    elif item_type == "platform":
        product_result = run_platform(
            user_input=user_input,
            resolver=resolver,
            platforms_db=platforms_db,
            sensors_db=sensors_db,
            jbox_db=jbox_db,
            controller_db=controller_db,
        )
    elif item_type == "bench":
        product_result = run_bench(
            user_input=user_input,
            resolver=resolver,
            benches_db=benches_db,
            controller_db=controller_db,
        )
    elif item_type == "truck_A":
        product_result = run_truck_A(
            user_input=user_input,
            resolver=resolver,
            sensors_db=sensors_db,
            jbox_db=jbox_db,
            controller_db=controller_db,
        )
    elif item_type == "truck_D":
            product_result = run_truck_D(
                user_input=user_input,
                resolver=resolver,
                sensors_db=sensors_db,
                jbox_db=jbox_db,
                controller_db=controller_db,
            )
    else:
        raise ValueError(
            f"不支持的条目类型：{item_type}"
        )
    #3. 统一返回选型结果清单
    return {
        "item_type": item_type,
        "quote_id": quote_id,
        "metrology": metrology_result,
        "status": "OK",
        **product_result
    }


# 传感器理论容量
# if __name__ == "__main__":
#     T_capacity = calculate_capacity(W1, W2, support) if item_type == "module" else None
#     #可选：print(f"\n单只传感器理论容量：{T_capacity:.0f} kg")

# ====读取数据库====
class DatabaseLoader:
    def __init__(self, rules, brand):
        self.rules = rules
        self.brand = brand
        self.brand_rules = rules["brands"]

    # =====通用CSV读取=====
    def load_csv(self, file_path):
        data = []
        with open(os.path.join(_DATA_DIR, file_path), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data

    def load_sensors(self):
        """读取传感器数据并返回列表"""
        sensor_file = self.brand_rules["sensor_db"][self.brand]
        rows = self.load_csv(sensor_file)
        sensors = []
        for row in rows:
            sensors.append({
                "family型号": row['family型号'].strip(),
                "capacity容量": int(row['capacity容量']),
                "Mtl材质": row['Mtl材质'].strip(),
                "EX_level": row['EX防爆等级'].strip(),
                "Y值": int(row['Y值']),
                "AC准确度等级": row['AC准确度等级'].strip(),
                "安装方式": row['安装方式'].strip(),
                "安装孔距": float(row['安装孔距']),
                "IP防护等级": row['IP防护等级'],
                "Seal密封方式": row['Seal密封方式'],
                "线制": int(row['线制'])
            })
        return sensors

    def load_modules(self):
        """读取模块数据并返回列表"""
        module_file = self.brand_rules["module_db"]
        rows = self.load_csv(module_file)
        modules = []
        for row in rows:
            modules.append({
                "module模块型号": row['module模块型号'].strip(),
                "mtl模块材质": row['mtl模块材质'].strip(),
                "sag拉杆": int(row['sag拉杆']),
                "模块孔距": float(row['模块孔距']),
                "适用传感器": row['适用传感器'].strip(),
                "过渡板": row['过渡板'].strip(),
                "EX_level": row['防爆等级'].strip(),
                "品牌": row["品牌"].strip()
            })

        return modules

    def load_jbox(self):
        """读取接线盒数据并返回列表"""
        jbox_file = self.brand_rules["jbox_db"]
        rows = self.load_csv(jbox_file)
        jboxes = []
        for row in rows:
            jboxes.append({
                "model型号": row["model型号"].strip(),
                "EX_level": row["EX防爆等级"].strip(),
                "出线数": int(row["出线数"]),
                "线制": int(row["线制"]),
                "信号模式": row["信号模式"].strip(),
                "mtl材质": row["mtl材质"].strip(),
                "品牌": row["品牌"].strip()
            })
        return jboxes

    def load_platforms(self, platform_file="平台秤通表.csv"):
        """读取平台秤通表数据并返回列表"""
        rows = self.load_csv(platform_file)
        platforms = []
        for row in rows:
            platforms.append({
                "具体型号": row['具体型号'].strip(),
                "型批型号": row['型批型号'].strip(),
                "品牌": row['品牌'].strip().upper(),
                "量程": int(row['kg量程']),
                "台面尺寸": row['台面尺寸'].strip(),
                "可用传感器": row['可用传感器'].strip(),
                "材质": row['材质'].strip(),
                "细分品种": row['细分品种'].strip(),
                "防爆": row['防爆'].strip(),
                "分度值": float(row['kg分度值']),
                # 信号协议：A=模拟式；RS485/CAN=数字式(数字化方案筛选用)，
                # 列未加或单元格为空时按模拟式处理
                "信号协议": (row.get("信号协议") or "A").strip(),
            })
        return platforms

    def load_benches(self, bench_file="台秤通表.csv"):
        """读取台秤通表数据并返回列表（无可用传感器列，g分度值转为kg存储）"""
        rows = self.load_csv(bench_file)
        benches = []
        for row in rows:
            benches.append({
                "具体型号": row['具体型号'].strip(),
                "型批型号": row['型批型号'].strip(),
                "品牌": row['品牌'].strip().upper(),
                "量程": int(row['kg量程']),
                "台面尺寸": row['台面尺寸'].strip(),
                "材质": row['材质'].strip(),
                "细分品种": row['细分品种'].strip(),
                "防爆": row['防爆'].strip(),
                "分度值": float(row['g分度值']) / 1000,
            })
        return benches

    def load_controllers(self):
        """读取仪表数据并返回标准字段与拓展字段列表"""
        controller_file = self.brand_rules["controller_db"][self.brand]
        rows = self.load_csv(controller_file)
        controllers = []
        standard_fields = {
        "brand", "family", "model_full",
        "com_1", "com_2", "com_3",
        "防爆等级", "安装方式", "支架", "power"
    }
        for row in rows:
            extra = {x: y for x, y in row.items() if x not in standard_fields}

            controllers.append({
                "brand": row.get("brand", self.brand).strip().upper(),
                "family": row.get("family", "").strip(),
                "nickname": row.get("nickname", "").strip(),
                "详细型号": row.get("model_full", "").strip(),
                "com_1": row.get("com_1","").strip(),
                "com_2": row.get("com_2","").strip(),
                "com_3": row.get("com_3","").strip(),
                "EX_level": row.get("防爆等级", 0).strip(),
                "安装方式": row.get("安装方式", "").strip(),
                "支架": row.get("支架", None),
                "Power": row.get("power", None),
                # 信号协议：A=模拟式；RS485/CAN=数字式(数字化方案筛选用)，
                # 列未加或单元格为空时按模拟式处理
                "信号协议": (row.get("信号协议") or "A").strip(),
                "extra": extra
            })
        return controllers

# if __name__ == "__main__":
#     # =====初始化数据库=====
#     db_sensor = DatabaseLoader(resolver.rules, m_brand)
#     db_controller = DatabaseLoader(resolver.rules, c_brand)
#     sensors_db = db_sensor.load_sensors()
#     modules_db = db_sensor.load_modules()
#     jbox_db = db_sensor.load_jbox()
#     platforms_db = db_sensor.load_platforms()
#     benches_db = db_sensor.load_benches()
#     controller_db = db_controller.load_controllers()


#     # ====自检模块====
#     validate_database(resolver, sensors_db, modules_db, jbox_db, controller_db)


# 传感器选型定义
def select_sensors(
    sensors_db,
    W1,
    W2,
    support,
    Ex_P,
    resolver
):
    sensor_candidates = []
    for sensor in sensors_db:
            sensor["EX_bool"] = False if sensor["EX_level"] == "0" else True  # 0表示非防爆，非0表示防爆
            SF = calculate_safety_factor(W1, W2, support, sensor['capacity容量'])
            sensor_candidates.append({
                **sensor,
                "SF": SF,
            })

    best_SF = resolver.get_target_sf(W1, W2)
    # diagnostic
    diagnostic = {
        "input_count": len(sensors_db),
        "stage_counts":{
            "initial": len(sensors_db),
            "ex_pass": 0,
            "sf_pass": 0,
            "final": 0
        },

        "rejection": {
            "防爆不匹配": 0,
            "SF过低": 0,
            "SF过高": 0,
            "SF警告": 0,
        },
        "status":"OK",
        "evidence": {}
    }

    # 记录所有传感器的 SF 范围
    if sensor_candidates:
        diagnostic["evidence"]["sf_min"] = min(
            s["SF"] for s in sensor_candidates
        )
        diagnostic["evidence"]["sf_max"] = max(
            s["SF"] for s in sensor_candidates
        )
    # ===== 第一层筛选 =====
    first_filter = []

    for sensor in sensor_candidates:
        if sensor["EX_bool"] != Ex_P:
            diagnostic["rejection"]["防爆不匹配"] += 1
            continue
        diagnostic["stage_counts"]["ex_pass"] += 1
        sf_info = resolver.verify_sf_status(sensor["SF"])
        status = sf_info["status"]

        if status in ["Normal", "Reminder"]:
            diagnostic["stage_counts"]["sf_pass"] += 1
            first_filter.append({
                **sensor,
                "difference": difference(sensor, best_SF)
            })
        elif status == "Warning":
            diagnostic["rejection"]["SF警告"] += 1
            first_filter.append({
                **sensor,
                "difference": difference(sensor, best_SF)})
        elif status in ["Danger"]:
            diagnostic["rejection"]["SF过高"] += 1
        else:
            diagnostic["rejection"]["SF过低"] += 1


    # 硬性门槛(防爆/SF)之外的默认收敛(每family+安装方式取精度最优、
    # 再取Y值最小/首个)已取消：选型确认已由 Commander/Checklist 人工
    # 兜底，所有可用Y值与精度等级的传感器全量返回，仅按贴近最优SF
    # 排序(首位即推荐项)
    filtered_sensors = first_filter
    filtered_sensors.sort(key=lambda x: x["difference"])
    diagnostic["stage_counts"]["final"] = len(filtered_sensors)
    if not filtered_sensors: diagnostic["status"] = "NO_MATCH"

    return {
        "sensors": filtered_sensors,
        "all_sensors": sensor_candidates,
        "best_SF": best_SF,
        "selection_status": diagnostic["status"],
        "diagnostic": diagnostic,
    }

#接线盒选型定义
def match_jbox(item_type, m_brand, Ex_P, rules, jbox_db, digital=False):
    """按 品类×品牌×(数字化×防爆) 模式查表选接线盒：数字化映射(digital/
    digital_explosion)与普通模式同级并列，仍按传感器品牌 m_brand 取键；
    映射键缺失或型号数据未录入时返回 None(无匹配)，不影响普通模式选型"""
    jbox_rules = rules["jbox_selection"]

    if digital and Ex_P:
        jboxmode = "digital_explosion"
    elif digital:
        jboxmode = "digital"
    else:
        jboxmode = "explosion" if Ex_P else "normal"

    try:
        target_jbox = jbox_rules[item_type][m_brand][jboxmode]
        for jbox in jbox_db:
            if jbox["model型号"] == target_jbox:
                return jbox
    except KeyError:
        return None
    return None

#模块选型定义
def run_module(
    user_input,
    resolver,
    sensors_db,
    modules_db,
    jbox_db,
    controller_db
):

    module_data = user_input["module_data"]

    W1 = module_data["W1"]
    W2 = module_data["W2"]
    support = module_data["support"]
    Ex_P = module_data["Ex_P"]
    # 数字化方案：接线盒换映射 + 仪表池按信号协议收窄(传感器/模块选型不变)
    digital = bool(module_data.get("数字化", False))
    material = module_data["material"]
    RPM = module_data["RPM"]
    # 高速搅拌判定(RPM>=阈值需拉杆)：结果侧带出 sag_on 供 GUI/输出侧拼接 L 后缀
    sag_on = resolver.get_sag(RPM)

    m_brand = module_data["m_brand"]
    c_brand = module_data["c_brand"]

    # 数字化方案：数字式专用仪表仅 FAB 提供，仪表品牌强制 FAB(无视解析输入)
    if digital:
        c_brand = "FAB"

    # 1. Sensor
    sensor_result = select_sensors(
        sensors_db=sensors_db,
        W1=W1,
        W2=W2,
        support=support,
        Ex_P=Ex_P,
        resolver=resolver
    )

    filtered_sensors = sensor_result["sensors"]

    module_diagnostic = {
        "status": "OK",

        "input": {
            "sensor_count": len(filtered_sensors),
            "module_db_count": len(modules_db)
        },

        "stage_counts": {
            "sensor_with_module_family": 0,
            "module_candidates": 0,
            "ex_pass": 0,
            "material_pass": 0,
            "孔距_pass": 0,
            "final": 0
        },

        "rejection": {
            "传感器无匹配模块": 0,
            "模块防爆不匹配": 0,
            "模块材质不匹配": 0,
            "模块孔距不匹配": 0
        },

        "evidence": {}
    }

    if not filtered_sensors:
        module_diagnostic["status"] = "NO_MATCH"
        module_diagnostic["evidence"]["reason"] = "上游无传感器匹配"
        return {
            "item_type": "module",
            "sensor": sensor_result,
            "module": [],
            "module_free": [],
            "sag_on": sag_on,
            "jbox": match_jbox(
                item_type="module",
                m_brand=m_brand,
                Ex_P=Ex_P,
                rules=resolver.rules,
                jbox_db=jbox_db,
                digital=digital
            ),
            "controller": [],
            "controller_diagnostic": {
                "status": "SKIPPED",
                "reason": "上游无传感器匹配",
            },
            "module_diagnostic": module_diagnostic,
            "status": "NO_MATCH",
        }
    # 2. Module
    T_capacity = calculate_capacity(
        W1,
        W2,
        support
    )

    modules_by_sensor = {}
    for module in modules_db:
        sensor_list = (
            module["适用传感器"]
            .split("|")
        )
        for family in sensor_list:
            modules_by_sensor.setdefault(
                family,
                []
            ).append(module)

    module_results = []
    # 自由搭配候选：family+防爆+孔距通过的全部组合，材质不设门槛；
    # module_results 仅是其中按用户材质命中(material_ok)的推荐子集，
    # GUI 传感器下拉据此与材质解耦，跨材质搭配由人工决定
    module_free = []
    for sensor in filtered_sensors:
        sensor_family = sensor["family型号"]
        if sensor_family not in modules_by_sensor:
            module_diagnostic["rejection"][
                "传感器无匹配模块"
            ] += 1
            continue
        module_diagnostic["stage_counts"]["sensor_with_module_family"] += 1
        for module in modules_by_sensor[sensor_family]:
            module_diagnostic["stage_counts"]["module_candidates"] += 1
            module["EX_bool"] = (
                False
                if module["EX_level"] == "0"
                else True
            )
            if module["EX_bool"] != Ex_P:
                module_diagnostic["rejection"][
                    "模块防爆不匹配"
                ] += 1
                continue
            module_diagnostic["stage_counts"]["ex_pass"]+= 1
            # 材质筛选降级为推荐标记：不再中断配对，仅决定该组合
            # 进推荐结果(module_results)还是只进自由候选(module_free)
            if (module["mtl模块材质"]!= material_suffix(
                    material,
                    module
                )
            ):
                module_diagnostic["rejection"][
                    "模块材质不匹配"
                ] += 1
                material_ok = False
            else:
                material_ok = True
                module_diagnostic["stage_counts"]["material_pass"] += 1
            if not float_equal(
                module["模块孔距"],
                sensor["安装孔距"]
            ):
                module_diagnostic["rejection"][
                    "模块孔距不匹配"
                ] += 1
                continue
            module_diagnostic["stage_counts"]["孔距_pass"] += 1
            pair = {
                "sensor": sensor,
                "module": module,
                "info": {
                    "support": support,
                    "T_capacity": T_capacity,
                    "best_SF": sensor_result["best_SF"]
                },
            }

            if material_ok:
                module_results.append(pair)

            module_free.append(pair)

    module_diagnostic["stage_counts"]["final"] = len(module_results)
    module_diagnostic["evidence"]["free_pairs"] = len(module_free)
    if not module_results:
        module_diagnostic["status"] = "NO_MATCH"
    # 3. J-box
    jbox_result = match_jbox(
        item_type="module",
        m_brand=m_brand,
        Ex_P=Ex_P,
        rules=resolver.rules,
        jbox_db=jbox_db,
        digital=digital
    )

    # 4. Controller
    controllers = select_controllers(
        item_type="module",
        brand=c_brand,
        controller_db=controller_db,
        rules=resolver.rules,
        user_input=user_input,
        Ex_P=Ex_P,
        required_ex=module_data["required_ex"],
        digital=digital
    )

    # 5. 返回模块选型结果
    return {
        "item_type": "module",
        "sensor": sensor_result,
        "module": module_results,
        "module_free": module_free,
        "sag_on": sag_on,
        "jbox": jbox_result,
        "controller": controllers["results"],
        "controller_diagnostic": controllers["diagnostic"],
        "module_diagnostic": module_diagnostic,
        "status": "OK" if module_results else "NO_MATCH",
    }

#平台秤选型定义
PLATFORM_SUBTYPE = {
    True: "高精度平台秤",
    False: "护框型电子平台秤",
}
# CSV材质列取值归组：C=碳钢系，S=不锈钢系，H前缀为高精度系列同规则
PLATFORM_MATERIAL_GROUPS = {
    "碳钢": {"C", "HC"},
    "不锈钢": {"S", "HS"},
    "混合": {"CS", "HCS"},
}

def normalize_platform_material(material):
    """平台秤材质输入归一化：中文/缩写 -> 碳钢/不锈钢/混合，非法输入返回None"""
    if material in ["碳钢", "C"]:
        return "碳钢"
    if material in ["SS", "不锈钢", "S"]:
        return "不锈钢"
    if material in ["CS", "HCS", "混合"]:
        return "混合"
    return None

def parse_platform_sensor_token(token):
    """通表可用传感器字段拆解：'SLB-227kg'/'AWB-1t' -> ('SLB', 227)"""
    try:
        family, cap = token.rsplit("-", 1)
        if cap.endswith("kg"):
            return family, int(float(cap[:-2]))
        if cap.endswith("t"):
            return family, int(float(cap[:-1]) * 1000)
    except ValueError:
        pass
    return None, None

def assemble_platform_sensors(platform, sensors_db, Ex_P, diagnostic=None):
    """将通表可用传感器按family+容量对照传感器库，拼接具体传感器型号；
    匹配失败时不输出该传感器，仅计入diagnostic(不做兜底直返——传感器
    显示跟随传感器库匹配结果，库数据待补时对应选项暂缺)"""
    models = []
    for token in platform["可用传感器"].split("|"):
        token = token.strip()
        if not token:
            continue
        family, capacity = parse_platform_sensor_token(token)
        matched = []
        if family:
            matched = [
                s for s in sensors_db
                if s["family型号"] == family and s["capacity容量"] == capacity
                and (s["EX_level"] != "0") == Ex_P  # 防爆筛选：仅保留与需求一致的版本
            ]
        if matched:
            ex_str = " EX" if Ex_P else ""
            for s in matched:
                y_str = y_suffix(s, sensors_db)
                models.append(
                    f"{s['family型号']}-"
                    f"{format_capacity(s)}-"
                    f"{s['AC准确度等级']}{ex_str}{y_str}"
                )
        else:
            if diagnostic is not None:
                diagnostic["rejection"]["数据表中可用传感器匹配失败"] += 1
    return models

def run_platform(
    user_input,
    resolver,
    platforms_db,
    sensors_db,
    jbox_db,
    controller_db
):
    """平台秤选型pipeline：
    品牌 -> 细分品种(由是否高精度映射) -> 材质 -> 防爆 -> 量程向上取档 -> 台面尺寸 -> 分度值要求，
    整机/分度值直接取自通表，传感器拆family+容量对照传感器库拼接具体型号，
    jbox与仪表复用module线规则与筛选，不考虑W2/安全系数/支撑点数"""
    module_data = user_input["module_data"]
    W1 = module_data["W1"]
    Ex_P = module_data["Ex_P"]
    # 数字化方案：接线盒换映射 + 仪表池按信号协议收窄(与模块线同规则)
    digital = bool(module_data.get("数字化", False))
    material = normalize_platform_material(module_data["material"])
    subtype = PLATFORM_SUBTYPE[bool(module_data.get("高精度"))]
    size = module_data.get("台面尺寸")
    e_input = module_data.get("e_input")
    m_brand = module_data["m_brand"]
    c_brand = module_data["c_brand"]

    # 数字化方案：数字式专用仪表仅 FAB 提供，仪表品牌强制 FAB(无视解析输入)。
    # m_brand(传感器品牌)不在此处默认：写AW/写FT/没写分别决定传感器库范围
    if digital:
        c_brand = "FAB"

    diagnostic = {
        "status": "OK",
        "input": {
            "platform_db_count": len(platforms_db) if platforms_db else 0,
            "W1": W1,
            "细分品种": subtype,
            "材质": material,
            "e_input": e_input,
        },
        "stage_counts": {
            "brand_pass": 0,
            "subtype_pass": 0,
            "material_pass": 0,
            "ex_pass": 0,
            "range_pass": 0,
            "size_pass": 0,
            "e_pass": 0,
            "final": 0,
        },
        "rejection": {
            "品牌不匹配": 0,
            "细分品种不匹配": 0,
            "材质不匹配": 0,
            "防爆不匹配": 0,
            "量程不满足W1": 0,
            "台面尺寸不匹配": 0,
            "分度值不满足": 0,
            "数据表中可用传感器匹配失败": 0,
        },
        "evidence": {},
    }

    def _no_match(reason):
        diagnostic["status"] = "NO_MATCH"
        diagnostic["evidence"]["reason"] = reason
        diagnostic["stage_counts"]["final"] = 0
        return {
            "item_type": "platform",
            "platform": [],
            "jbox": match_jbox(
                item_type="platform",
                m_brand=m_brand or ("AW" if digital else None),
                Ex_P=Ex_P,
                rules=resolver.rules,
                jbox_db=jbox_db,
                digital=digital
            ),
            "controller": [],
            "controller_diagnostic": {
                "status": "SKIPPED",
                "reason": reason,
            },
            "platform_diagnostic": diagnostic,
            "status": "NO_MATCH",
        }

    if not platforms_db:
        return _no_match("平台秤数据库为空或未加载")

    # 1. 品牌(数字化方案不按传感器品牌收敛——孪生行仅 AW，FT 传感器亦可
    #    配 AW 数字整秤；品牌未填写时 FT/AW 模拟行均参选)
    if digital or not m_brand:
        candidates = list(platforms_db)
        diagnostic["rejection"]["品牌不匹配"] = 0
    else:
        candidates = [p for p in platforms_db if p["品牌"] == m_brand]
        diagnostic["rejection"]["品牌不匹配"] = (
            len(platforms_db) - len(candidates))
        if not candidates:
            return _no_match(f"平台秤数据库中无 {m_brand} 品牌记录")
    diagnostic["stage_counts"]["brand_pass"] = len(candidates)

    # 1.5 数字化信号池(双向收窄，与仪表同规则)：数字化平台秤(信号协议
    # RS485/CAN)仅在勾选数字化时参选，模拟行仅在未勾选时参选；
    # 列缺省按模拟式处理
    protocols = resolver.rules["controller_selection"].get(
        "digital_protocols", ("RS485", "CAN"))

    if digital:
        passed = [p for p in candidates
                  if p.get("信号协议", "A") in protocols]
    else:
        passed = [p for p in candidates
                  if p.get("信号协议", "A") not in protocols]
    diagnostic["rejection"]["信号协议不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["digital_pass"] = len(candidates)
    if not candidates:
        return _no_match("平台秤数据库中无{}信号协议记录".format(
            "数字化" if digital else "模拟式"))

    # 2. 细分品种（是否高精度映射）
    passed = [p for p in candidates if p["细分品种"] == subtype]
    diagnostic["rejection"]["细分品种不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["subtype_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"无 {subtype} 品类记录")

    # 3. 材质
    if material is None:
        return _no_match("材质输入非法（请输入C/碳钢、S/不锈钢 或 CS/混合）")
    material_group = PLATFORM_MATERIAL_GROUPS[material]
    passed = [p for p in candidates if p["材质"] in material_group]
    diagnostic["rejection"]["材质不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["material_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"{subtype}下无 {material} 材质平台秤")

    # 4. 防爆
    passed = [p for p in candidates if (p["防爆"] != "0") == Ex_P]
    diagnostic["rejection"]["防爆不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["ex_pass"] = len(candidates)
    if not candidates:
        return _no_match("该组合下无匹配防爆要求的平台秤")

    # 5. 量程向上取档：取满足 W1<=量程的最小档位
    in_range = [p for p in candidates if p["量程"] >= W1]
    diagnostic["rejection"]["量程不满足W1"] = len(candidates) - len(in_range)
    if not in_range:
        diagnostic["evidence"]["max_range"] = max(p["量程"] for p in candidates)
        return _no_match(f"W1={W1}kg 超出该组合下平台秤最大量程档位")
    target_range = min(p["量程"] for p in in_range)
    candidates = [p for p in in_range if p["量程"] == target_range]
    diagnostic["stage_counts"]["range_pass"] = len(candidates)
    diagnostic["evidence"]["target_range"] = target_range

    # 6. 台面尺寸（未输入则不过滤，展示该档位全部可选台面）
    if size:
        passed = [p for p in candidates if p["台面尺寸"] == size]
        diagnostic["rejection"]["台面尺寸不匹配"] = len(candidates) - len(passed)
        candidates = passed
    diagnostic["stage_counts"]["size_pass"] = len(candidates)
    if not candidates:
        available = [p["台面尺寸"] for p in platforms_db
                     if p["品牌"] == m_brand and p["量程"] == target_range]
        diagnostic["evidence"]["available_sizes"] = available
        return _no_match(f"台面尺寸不匹配，该档位可选台面：{available}")

    # 7. e_input分度值要求：保留分度值不劣于要求的行（未输入则不过滤）
    if e_input is not None:
        passed = [p for p in candidates if p["分度值"] <= e_input + 1e-9]
        diagnostic["rejection"]["分度值不满足"] = len(candidates) - len(passed)
        candidates = passed
    diagnostic["stage_counts"]["e_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"该组合下平台秤分度值无法满足 {e_input}kg 的要求")

    diagnostic["stage_counts"]["final"] = len(candidates)

    platform_results = [
        {
            "platform": p,
            "sensors": assemble_platform_sensors(
                p, sensors_db, Ex_P, diagnostic
            ),
        }
        for p in candidates
    ]

    # 接线盒：复用规则表
    jbox_result = match_jbox(
        item_type="platform",
        m_brand=m_brand or ("AW" if digital else None),
        Ex_P=Ex_P,
        rules=resolver.rules,
        jbox_db=jbox_db,
        digital=digital
    )

    # 仪表：复用仪表选型模块
    controllers = select_controllers(
        item_type="platform",
        brand=c_brand,
        controller_db=controller_db,
        rules=resolver.rules,
        user_input=user_input,
        Ex_P=Ex_P,
        required_ex=module_data["required_ex"],
        digital=digital
    )

    return {
        "item_type": "platform",
        "platform": platform_results,
        "jbox": jbox_result,
        "controller": controllers["results"],
        "controller_diagnostic": controllers["diagnostic"],
        "platform_diagnostic": diagnostic,
        "status": "OK" if platform_results else "NO_MATCH",
    }

#台秤选型定义
BENCH_SUBTYPE = {
    True: "高精度电子台秤",
    False: "电子台秤",
}

def run_bench(
    user_input,
    resolver,
    benches_db,
    controller_db
):
    """台秤选型pipeline：
    品牌 -> 细分品种(由是否高精度映射) -> 材质 -> 防爆 -> W1向上取档 -> 台面尺寸 -> e_input分度值
    -> 安装形式(一体=仪表立杆支架；分体=按用户选择的壁挂/立杆支架) -> Controller，
    量程/分度值直接取自通表"""
    module_data = user_input["module_data"]
    W1 = module_data["W1"]
    Ex_P = module_data["Ex_P"]
    material = normalize_platform_material(module_data["material"])
    subtype = BENCH_SUBTYPE[bool(module_data.get("高精度"))]
    size = module_data.get("台面尺寸")
    e_input = module_data.get("e_input")
    install_form = module_data.get("安装形式") or "一体"
    split_bracket = module_data.get("分体仪表支架")
    m_brand = module_data["m_brand"]
    c_brand = module_data["c_brand"]

    # 安装形式决定仪表支架筛选条件：一体 -> 立杆支架；分体 -> 用户选择的壁挂/立杆
    if install_form == "一体":
        ctrl_bracket = "立杆支架"
    else:
        ctrl_bracket = split_bracket

    diagnostic = {
        "status": "OK",
        "input": {
            "bench_db_count": len(benches_db) if benches_db else 0,
            "W1": W1,
            "细分品种": subtype,
            "材质": material,
            "e_input": e_input,
            "安装形式": install_form,
            "仪表支架": ctrl_bracket,
        },
        "stage_counts": {
            "brand_pass": 0,
            "subtype_pass": 0,
            "material_pass": 0,
            "ex_pass": 0,
            "range_pass": 0,
            "size_pass": 0,
            "e_pass": 0,
            "final": 0,
        },
        "rejection": {
            "品牌不匹配": 0,
            "细分品种不匹配": 0,
            "材质不匹配": 0,
            "防爆不匹配": 0,
            "量程不满足W1": 0,
            "台面尺寸不匹配": 0,
            "分度值不满足": 0,
        },
        "evidence": {},
    }

    def _no_match(reason):
        diagnostic["status"] = "NO_MATCH"
        diagnostic["evidence"]["reason"] = reason
        diagnostic["stage_counts"]["final"] = 0
        return {
            "item_type": "bench",
            "bench": [],
            "controller": [],
            "controller_diagnostic": {
                "status": "SKIPPED",
                "reason": reason,
            },
            "bench_diagnostic": diagnostic,
            "status": "NO_MATCH",
        }

    if not benches_db:
        return _no_match("台秤数据库为空或未加载")

    # 1. 品牌
    candidates = [p for p in benches_db if p["品牌"] == m_brand]
    diagnostic["rejection"]["品牌不匹配"] = len(benches_db) - len(candidates)
    diagnostic["stage_counts"]["brand_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"台秤数据库中无 {m_brand} 品牌记录")

    # 2. 细分品种（是否高精度映射）
    passed = [p for p in candidates if p["细分品种"] == subtype]
    diagnostic["rejection"]["细分品种不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["subtype_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"无 {subtype} 品类记录")

    # 3. 材质
    if material is None:
        return _no_match("材质输入非法（请输入C/碳钢、S/不锈钢 或 CS/混合）")
    material_group = PLATFORM_MATERIAL_GROUPS[material]
    passed = [p for p in candidates if p["材质"] in material_group]
    diagnostic["rejection"]["材质不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["material_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"{subtype}下无 {material} 材质台秤")

    # 4. 防爆
    passed = [p for p in candidates if (p["防爆"] != "0") == Ex_P]
    diagnostic["rejection"]["防爆不匹配"] = len(candidates) - len(passed)
    candidates = passed
    diagnostic["stage_counts"]["ex_pass"] = len(candidates)
    if not candidates:
        return _no_match("该组合下无匹配防爆要求的台秤")

    # 5. 量程向上取档
    in_range = [p for p in candidates if p["量程"] >= W1]
    diagnostic["rejection"]["量程不满足W1"] = len(candidates) - len(in_range)
    if not in_range:
        diagnostic["evidence"]["max_range"] = max(p["量程"] for p in candidates)
        return _no_match(f"W1={W1}kg 超出该组合下台秤最大量程档位")
    target_range = min(p["量程"] for p in in_range)
    candidates = [p for p in in_range if p["量程"] == target_range]
    diagnostic["stage_counts"]["range_pass"] = len(candidates)
    diagnostic["evidence"]["target_range"] = target_range

    # 6. 台面尺寸
    if size:
        passed = [p for p in candidates if p["台面尺寸"] == size]
        diagnostic["rejection"]["台面尺寸不匹配"] = len(candidates) - len(passed)
        candidates = passed
    diagnostic["stage_counts"]["size_pass"] = len(candidates)
    if not candidates:
        available = [p["台面尺寸"] for p in benches_db
                     if p["品牌"] == m_brand and p["量程"] == target_range]
        diagnostic["evidence"]["available_sizes"] = available
        return _no_match(f"台面尺寸不匹配，该档位可选台面：{available}")

    # 7. e_input分度值
    if e_input is not None:
        passed = [p for p in candidates if p["分度值"] <= e_input + 1e-9]
        diagnostic["rejection"]["分度值不满足"] = len(candidates) - len(passed)
        candidates = passed
    diagnostic["stage_counts"]["e_pass"] = len(candidates)
    if not candidates:
        return _no_match(f"该组合下台秤分度值无法满足 {e_input}kg 的要求")

    diagnostic["stage_counts"]["final"] = len(candidates)

    # 仪表：按安装形式注入支架筛选条件后复用仪表选型模块
    if ctrl_bracket:
        ui = dict(user_input)
        ui["hardware"] = dict(user_input["hardware"], bracket=ctrl_bracket)
    else:
        ui = user_input
    controllers = select_controllers(
        item_type="bench",
        brand=c_brand,
        controller_db=controller_db,
        rules=resolver.rules,
        user_input=ui,
        Ex_P=Ex_P,
        required_ex=module_data["required_ex"]
    )

    return {
        "item_type": "bench",
        "bench": candidates,
        "jbox": None,
        "controller": controllers["results"],
        "controller_diagnostic": controllers["diagnostic"],
        "bench_diagnostic": diagnostic,
        "status": "OK" if candidates else "NO_MATCH",
    }

#汽车衡选型定义
def run_truck_A(
    user_input,
    resolver,
    sensors_db,
    jbox_db,
    controller_db
):
    raise NotImplementedError(
        "汽车衡选型流程尚未实现"
    )
#数字式汽车衡选型定义
def run_truck_D(
    user_input,
    resolver,
    sensors_db,
    jbox_db,
    controller_db
):
    raise NotImplementedError(
        "数字式汽车衡选型流程尚未实现"
    )

# print("sensor candidates:", len(sensor_candidates))           调试用
# print("after filter:", len(first_filter))

# if __name__ == "__main__":
#     jbox_results = match_jbox(item_type, m_brand, Ex_P, resolver.rules, jbox_db)

#     controller_results =[]
#     controller_failed = 0


def filter_controller_family(item_type, rules, controller_db):
    family_map = rules["controller_selection"]["family_mapping"]
    if item_type not in family_map:
        return []
    filter_result_1 = family_map[item_type]
    return [
        c for c in controller_db
        if c["family"] in filter_result_1
    ]

def filter_controller_series(controllers, c_family):
    """按用户点名系列收敛仪表：family/nickname 与 c_family 精确匹配(忽略大小写)。
    匹配不到即返回空(如实反映无同系列仪表，不回退放大到大类)"""
    target = (c_family or "").strip().lower()

    if not target:
        return controllers

    return [
        c for c in controllers
        if c.get("family", "").strip().lower() == target
        or c.get("nickname", "").strip().lower() == target
    ]


def parse_com1_rule(com1_value, config):
    """com_1拆解"""
    rule = config["com1_rules"].get(str(com1_value))
    return rule

def match_com1(rule, req_com1):
    if not req_com1:
        return True  # 无要求
    if not rule:
        return False

    need_232 = "RS232" in req_com1
    need_485 = "RS485" in req_com1
    # 单选
    if need_232 and not need_485:
        return rule.get("RS232", False)
    if need_485 and not need_232:
        return rule.get("RS485", False)

    # 双选（RS232 + RS485）
    if need_232 and need_485:
        return (
            rule.get("RS232", False)
            and rule.get("RS485", False)
        )

    return False

def m_ctrler_com_fliter(
    controllers,
    config,
    req_com1=None,
    req_com2=None,
    special_req=False,
    special_req2=False
):
    """通讯分层筛选，special为多通道,默认单通道；
    com_3为数值时按通道数判断(special_req)，为字符串(如电池配置)时按电池选项判断(special_req2)"""

    diagnostic = {
        "input": len(controllers),
        "stage_counts": {
            "com2_pass": 0,
            "com1_pass": 0,
            "com3_pass": 0,
        }
    }

    # ===== COM2 =====
    # 数据库com_2可能为多值写法（如"TCP|UDP"），按"|"拆成集合后与需求取交集
    com2_result = []
    for c in controllers:
        com2_set = {
            x.strip()
            for x in c.get("com_2", "").split("|")
            if x.strip() and x.strip() != "0"
        }
        if req_com2:
            if not (com2_set & set(req_com2)):
                continue
        else:
            if com2_set:
                continue
        com2_result.append(c)
    diagnostic["stage_counts"]["com2_pass"] = len(com2_result)

    # ===== COM1 =====
    # req_com1 由 Parser 按 parser_rules.json 的 com1_code 节直接推导为
    # 可接受 com_1 规则码列表(含覆盖关系，如 RTU_2 覆盖 basic_2/basic_1)，
    # 此处按控制器 com_1 结果码做成员匹配；另兼容字面串口写法：
    # 需求中出现 RS232/232 时同时放行 com_1 为 'RS232' 的仪表，
    # 出现 RS485/485 时放行 'RS485'(单串口仪表按字面协议命名的写法)
    com1_literal = set()
    for code in req_com1 or []:
        text = str(code)
        if "232" in text:
            com1_literal.add("RS232")
        if "485" in text:
            com1_literal.add("RS485")

    com1_result = []
    for c in com2_result:
        if req_com1:
            if c["com_1"] not in req_com1 and c["com_1"] not in com1_literal:
                continue
        com1_result.append(c)
    diagnostic["stage_counts"]["com1_pass"] = len(com1_result)

    # ===== COM3 =====
    # com_3为整数 -> 通道数逻辑(special_req多通道)；com_3为字符串 -> 电池逻辑(special_req2)
    com3_result = []
    for c in com1_result:
        com3_raw = c.get("com_3", "0")
        try:
            com3 = int(com3_raw)
        except (ValueError, TypeError):
            if special_req2:
                if com3_raw == "无电池":
                    continue
            else:
                if com3_raw != "无电池":
                    continue
            com3_result.append(c)
            continue
        if special_req:
            if not (2 <= com3 < 5):
                continue
        else:
            if not (com3 < 2):
                continue
        com3_result.append(c)
    diagnostic["stage_counts"]["com3_pass"] = len(com3_result)

    return {
        "results": com3_result,
        "diagnostic": diagnostic
    }

def filter_by_hardware(controllers, install, power, bracket,brand):
    """仪表安装方式、供电、支架筛选，需有对应参数输入；隔爆款无支架概念，跳过支架筛选"""
    hard_result = []
    for c in controllers:
        if install and c["安装方式"] != install:
            continue
        if power and c["Power"] != power:
            continue
        if brand == "FAB":
            pass
        else:
            if bracket and c["安装方式"] != "隔爆" and c["支架"] != bracket:
                continue
        hard_result.append(c)
    return hard_result
# if __name__ == "__main__":
#     controller_1_filter = filter_controller_family(
#         item_type,
#         resolver.rules,
#         controller_db
#     )

def filter_ctrler_ex(controllers, Ex_P, required_ex,):
    EX_map = resolver.rules["controller_selection"]["ex_mapping"]
    if not Ex_P:
        return [
            c for c in controllers
            if EX_map.get(c["EX_level"], 0) == 0
            ]

    ex_result = []
    for c in controllers:
            if EX_map.get(
                c["EX_level"], 0) >= EX_map.get(required_ex, 0):
                ex_result.append(c)
    return ex_result

def select_controllers(
    item_type,
    brand,
    controller_db,
    rules,
    user_input,
    Ex_P=False,
    required_ex=None,
    digital=False
):
    """仪表选型入口"""
    controllers = controller_db
    com_input = user_input["com"]
    hw_input = user_input["hardware"]

    req_com1 = com_input["req_com1"]
    req_com2 = com_input["req_com2"]
    special_req = com_input["special_req"]
    install = hw_input["install"]
    power = hw_input["power"]
    bracket = hw_input["bracket"]
    diagnostic = {
        "status": "OK",
        "input": {
            "count": len(controller_db)
        },
        "stage_counts": {
            "initial": len(controller_db),
            "brand_pass": 0,
            "family_pass": 0,
            "digital_pass": 0,
            "communication_pass": 0,
            "hardware_pass": 0,
            "power_pass": 0,
            "ex_pass": 0,
            "final": 0
        },
    }

    controllers = [c for c in controllers if c.get("brand", brand) == brand]
    diagnostic["stage_counts"]["brand_pass"] = len(controllers)
    controllers = filter_controller_family(item_type, rules, controllers)
    diagnostic["stage_counts"]["family_pass"] = len(controllers)

    # 数字化方案切换仪表信号池(双向收窄)：勾选 -> 仅数字协议专用仪表
    # (如 FAB3306DR 系列)；未勾选 -> 仅模拟式(A)，数字专用行不落入模拟候选。
    # 协议集合规则可配(controller_selection.digital_protocols)，
    # 行缺 信号协议 列按模拟式("A")处理
    protocols = rules["controller_selection"].get(
        "digital_protocols", ("RS485", "CAN"))

    if digital:
        controllers = [
            c for c in controllers
            if c.get("信号协议", "A") in protocols
        ]
    else:
        controllers = [
            c for c in controllers
            if c.get("信号协议", "A") not in protocols
        ]
    diagnostic["stage_counts"]["digital_pass"] = len(controllers)

    # 用户点名系列收敛(c_family 由 Parser 二次识别，如 3306/FAB330)
    c_family = (user_input.get("module_data", {}) or {}).get("c_family")
    controllers = filter_controller_series(controllers, c_family)
    diagnostic["stage_counts"]["series_pass"] = len(controllers)

    communication = m_ctrler_com_fliter(
        controllers,
        rules["controller_selection"],
        req_com1=req_com1,
        req_com2=req_com2,
        special_req=special_req,
        special_req2=com_input.get("special_req2", False)
    )
    controllers = communication["results"]
    diagnostic["communication"] = communication["diagnostic"]
    diagnostic["stage_counts"]["communication_pass"] = len(controllers)

    controllers = filter_by_hardware(
        controllers,
        install,
        power,
        bracket,
        brand
    )
    diagnostic["stage_counts"]["hardware_pass"] = len(controllers)

    controllers = filter_ctrler_ex(
        controllers,
        Ex_P,
        required_ex,
    )
    diagnostic["stage_counts"]["ex_pass"] = len(controllers)

    diagnostic["stage_counts"]["final"] =len(controllers)
    return {
        "results": controllers,
        "diagnostic": diagnostic
    }


def controller_output(controller):
    """仪表输出接口"""
    return controller["详细型号"]

# if __name__ == "__main__":
#     controller_list = select_controllers(
#         item_type=item_type,
#         brand=c_brand,
#         controller_db=controller_db,
#         rules=resolver.rules,
#         user_input=user_input,
#         Ex_P=Ex_P,
#         required_ex=requried_ex
#     )


# ====计量模块====
class MetrologyEngine:
    def __init__(self, rules):
        self.rules = rules["metrology_rules"]

    def _find_by_range(self, value, mapping, key):
        for item in mapping:
            if item["min"] < value <= item["max"]:
                return item[key]
        raise ValueError(f"{key} not found for value={value}")

    def parse_e(self, e_dict):
        return e_dict["value"] * (10 ** e_dict["exp"])
    def get_e_from_W(self, W):
        e_dict = self._find_by_range(
        W,
        self.rules["standard_e_mapping"],
        "e"
    )
        return self.parse_e(e_dict)

    def get_P(self, W):
        return self._find_by_range(W, self.rules["P_mapping"], "P")

    def get_G(self, W):
        return self._find_by_range(W, self.rules["grid_mapping"], "G")

    def is_valid_e(self, e_value):
        base_set = self.rules["e_set"]["base"]
        exp = int(math.floor(math.log10(e_value)))
        base = e_value / (10 ** exp)
        base = round(base, 6)
        return base in base_set

    def validate_n(self, rated_range, e, metrology=False):
        limits = self.rules["n_limits"]
        n = rated_range / e
        if metrology:
            if limits["min"] <= n <= limits["preferred_max"]:
                return n
            else:
                raise ValueError(f"分度数n={n:.2f}超出区间（{limits['min']} <= n <= {limits['preferred_max']}）")
        else:
            if limits["min"] <= n <= limits["max"]:
                return n
            else:
                raise ValueError(f"分度数n={n:.2f}超出区间（{limits['min']} <= n <= {limits['max']}）")

    def calculate_buffered_range(self, W):
        P = self.get_P(W)
        return W * (1 + P)

    def round_range(self, value):
        G = self.get_G(value)
        R_low = math.floor(value / G) * G
        R_high = math.ceil(value / G) * G
        return R_low, R_high

    def calculate_rated_range(self, W):
        buffered = self.calculate_buffered_range(W)
        R_low, R_high = self.round_range(buffered)

        if R_low >= W:
            if abs(buffered - R_low) <= abs(R_high - buffered):
                rated = R_low
            else:
                rated = R_high
        else:
            rated = R_high

        return rated

    def process_full_input(self, rated_range, e, metrology=False):

        if not self.is_valid_e(e):
            return {"error": "非法e值，请重新检查并输入"}

        n = self.validate_n(rated_range, e, metrology)

        return {
            "rated_range": rated_range,
            "e": e,
            "n": n,
            "metrology": metrology
        }

    def process_only_range(self, rated_range, metrology=False):

        e = self.get_e_from_W(rated_range)
        n = rated_range / e
        return {
            "rated_range": rated_range,
            "e": e,
            "n": n,
            "metrology": metrology
        }

    def process_only_e(self, W1, e, metrology=False):

        if not self.is_valid_e(e):
            return {"error": "非法e值，请重新检查并输入"}

        C2 = e * 3000
        if C2 < W1:
            r = self.calculate_rated_range(W1)
        else:
            r = C2
        n = r / e
        return {
            "rated_range": r,
            "e": e,
            "n": n,
            "metrology": metrology
        }

    def process_full_auto(self, W1, metrology=False):
        r = self.calculate_rated_range(W1)
        e = self.get_e_from_W(W1)
        n = self.validate_n(r, e, metrology)
        return {
            "rated_range": r,
            "e": e,
            "n": n,
            "metrology": metrology
        }

    #计量模块主流程
    def run(self, W1,r_input, e_input, metrology=False):
        if r_input is not None and e_input is not None:
            m_set = self.process_full_input(r_input, e_input,metrology)
        elif r_input is not None and e_input is None:
            m_set = self.process_only_range(r_input, metrology)
        elif e_input is not None and r_input is None:
            m_set = self.process_only_e(W1, e_input, metrology)
        else:
           m_set = self.process_full_auto(W1,metrology)
        return m_set



# if __name__ == "__main__":
#     # ====输出====
#     result = run_engine(
#         user_input=user_input,
#         resolver=resolver,
#         databases={
#             "sensors": sensors_db,
#             "modules": modules_db,
#             "jbox": jbox_db,
#             "platforms": platforms_db,
#             "benches": benches_db,
#             "controllers": controller_db,
#         },
#         quote_id=None  #未来要改
#     )
#     #CLI输出:
#     if item_type == "module":
#         print("\n=== sensor diagnostic ===")
#         all_sensors_count = len(result.get("sensor",{}).get("all_sensors",[]))
#         filtered_sensors_count = len(result.get("sensor",{}).get("sensors",[]))
#         sensor_diag = result["sensor"]["diagnostic"]
#         sf_pass = sensor_diag["stage_counts"]["sf_pass"]
#         ex_pass = sensor_diag["stage_counts"]["ex_pass"]
#         failure_reason = result.get("sensor",{}).get("failure_reason",[])
#         print("sensor candidates:", all_sensors_count)
#         print("ex pass:", ex_pass)
#         print("sf pass:", sf_pass)
#         print("final:", filtered_sensors_count)
#         print("\n=== module diagnostic ===")
#         module_rejection2 = result.get("module_diagnostic",{}).get("rejection",{})
#         print("模块防爆不匹配:",  module_rejection2.get("模块防爆不匹配"))
#         print("模块材质不匹配:", module_rejection2.get("模块材质不匹配"))
#         print("模块孔距不匹配:", module_rejection2.get("模块孔距不匹配"))
#         print("传感器无匹配模块:", module_rejection2.get("传感器无匹配模块"))
#         print("matched:", result.get("module_diagnostic",{}).get("stage_counts",{}).get("final", 0))
#     elif item_type == "platform":
#         print("\n=== platform diagnostic ===")
#         platform_diag = result.get("platform_diagnostic", {})
#         print("platform db count:", platform_diag.get("input", {}).get("platform_db_count", 0))
#         print("W1:", platform_diag.get("input", {}).get("W1"))
#         print("细分品种:", platform_diag.get("input", {}).get("细分品种"),
#               "材质:", platform_diag.get("input", {}).get("材质"),
#               "e_input:", platform_diag.get("input", {}).get("e_input"))
#         platform_stages = platform_diag.get("stage_counts", {})
#         print("brand pass:", platform_stages.get("brand_pass", 0))
#         print("subtype pass:", platform_stages.get("subtype_pass", 0))
#         print("material pass:", platform_stages.get("material_pass", 0))
#         print("ex pass:", platform_stages.get("ex_pass", 0))
#         print("range pass:", platform_stages.get("range_pass", 0),
#               "(目标档位: %s)" % platform_diag.get("evidence", {}).get("target_range"))
#         print("size pass:", platform_stages.get("size_pass", 0))
#         print("e pass:", platform_stages.get("e_pass", 0))
#         print("final:", platform_stages.get("final", 0))
#         platform_rejection = platform_diag.get("rejection", {})
#         print("拒绝统计:", platform_rejection)
#         if platform_diag.get("status") != "OK":
#             print("原因:", platform_diag.get("evidence", {}).get("reason"))
#     elif item_type == "bench":
#         print("\n=== bench diagnostic ===")
#         bench_diag = result.get("bench_diagnostic", {})
#         print("bench db count:", bench_diag.get("input", {}).get("bench_db_count", 0))
#         print("W1:", bench_diag.get("input", {}).get("W1"))
#         print("细分品种:", bench_diag.get("input", {}).get("细分品种"),
#               "材质:", bench_diag.get("input", {}).get("材质"),
#               "e_input:", bench_diag.get("input", {}).get("e_input"))
#         print("安装形式:", bench_diag.get("input", {}).get("安装形式"),
#               "仪表支架:", bench_diag.get("input", {}).get("仪表支架"))
#         bench_stages = bench_diag.get("stage_counts", {})
#         print("brand pass:", bench_stages.get("brand_pass", 0))
#         print("subtype pass:", bench_stages.get("subtype_pass", 0))
#         print("material pass:", bench_stages.get("material_pass", 0))
#         print("ex pass:", bench_stages.get("ex_pass", 0))
#         print("range pass:", bench_stages.get("range_pass", 0),
#               "(目标档位: %s)" % bench_diag.get("evidence", {}).get("target_range"))
#         print("size pass:", bench_stages.get("size_pass", 0))
#         print("e pass:", bench_stages.get("e_pass", 0))
#         print("final:", bench_stages.get("final", 0))
#         bench_rejection = bench_diag.get("rejection", {})
#         print("拒绝统计:", bench_rejection)
#         if bench_diag.get("status") != "OK":
#             print("原因:", bench_diag.get("evidence", {}).get("reason"))
#     print("\n=== Jbox diagnostic ===")
#     print("jbox data:", len(jbox_db))
#     print("matched:", jbox_results["model型号"] if jbox_results else "None")
#     print("\n=== Controller diagnostic ===")
#     controller_diag = result.get("controller_diagnostic", {})
#     stage = controller_diag.get("stage_counts", {})
#     communication = controller_diag.get("communication", {})
#     com_stage = communication.get("stage_counts", {})
#     com_rejection = communication.get("rejection", {})
#     print("initial:", stage.get("initial", 0))
#     print("brand pass:", stage.get("brand_pass", 0))
#     print("family pass:", stage.get("family_pass", 0))
#     print("\n--- Communication ---")
#     print("COM2 pass:", com_stage.get("com2_pass", 0))
#     print("COM1 pass:", com_stage.get("com1_pass", 0))
#     print("COM3 pass:", com_stage.get("com3_pass", 0))
#     print("\n--- Hardware / EX ---")
#     print("hardware pass:", stage.get("hardware_pass", 0))
#     print("EX pass:", stage.get("ex_pass", 0))
#     print("final:", stage.get("final", 0))

#     print("\n=== 计量参数 ===")

#     m = result["metrology"]

#     if "error" in m:
#         print(f"计量计算错误：{m['error']}")
#     elif "rated_range" in m:
#         print(f"检定：{'是' if m['metrology'] else '否'}")
#         print(f"额定量程：{m['rated_range']} kg")
#         print(f"分度值：{m['e']} kg")
#         print(f"分度数 n：{m['n']:.0f}")
#     else:
#         print(f"计量模块已跳过：{m.get('reason', '')}")
#     if item_type == "module":
#         print("\n=== 模块选型 ===")
#         print("\n符合要求的模块型号：")
#         module_results = result["module"]
#         for item in module_results:
#             sensor = item["sensor"]
#             module = item["module"]
#             capacity_str = format_capacity(sensor)
#             ex_str = ex_suffix(sensor)
#             y_str = y_suffix(
#                 sensor,
#                 result["sensor"]["all_sensors"]
#             )
#             sag = sag_suffix(
#                 module,
#                 resolver.get_sag(
#                     module_data["RPM"]
#                 )
#             )
#             print(
#                 f"{module['module模块型号']}{sag} "
#                 f"{module['mtl模块材质']} "
#                 f"{sensor['family型号']}-{capacity_str}-"
#                 f"{sensor['AC准确度等级']}"
#                 f"{ex_str}{y_str}, "
#                 f"安全系数={sensor['SF']:.2f}"
#             )
#     elif item_type == "platform":
#         print("\n=== 平台秤选型 ===")
#         print("\n符合要求的平台秤型号：")
#         if result["platform"]:
#             for item in result["platform"]:
#                 p = item["platform"]
#                 print(
#                     f"{p['具体型号']} "
#                     f"(量程{p['量程']}kg 分度值{p['分度值']}kg "
#                     f"台面{p['台面尺寸']} 型批{p['型批型号']})"
#                 )
#                 for s in item["sensors"]:
#                     print(f"  传感器：{s}")
#         else:
#             reason = result.get("platform_diagnostic", {}).get("evidence", {}).get("reason", "")
#             print(f"无匹配平台秤。{reason}")
#     elif item_type == "bench":
#         print("\n=== 台秤选型 ===")
#         print("\n符合要求的台秤型号：")
#         if result["bench"]:
#             for p in result["bench"]:
#                 print(
#                     f"{p['具体型号']} "
#                     f"(量程{p['量程']}kg 分度值{p['分度值'] * 1000:g}g "
#                     f"台面{p['台面尺寸']} 型批{p['型批型号']})"
#                 )
#         else:
#             reason = result.get("bench_diagnostic", {}).get("evidence", {}).get("reason", "")
#             print(f"无匹配台秤。{reason}")

#     if result["jbox"]:
#         print(
#             f"接线盒："
#             f"{result['jbox']['model型号']}"
#         )

#     print("\n可选仪表型号：")
#     if result["controller"]:
#         for controller in result["controller"]:
#             print(controller_output(controller))
#     else:
#         print("无匹配仪表。")
