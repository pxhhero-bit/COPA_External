# -*- coding: utf-8 -*-
"""sDocBuilder 编排稿：大纲 <-> markdown 序列化 + 默认大纲模板。

大纲数据形态（UI 与渲染器共用）：
  {"kind": "chapter", "title": str, "children": [...]}   # 章节可嵌套<=3层
  {"kind": "block",   "ref": str,    "title": str}       # 块不可嵌套

编排稿 md 约定：章节标题行前缀「#」数量=层级；块行「- ref | 标题」。
"""
from sdoc.core.library_store import KIND_LABEL


def default_template(store, project, brand=""):
    """用户指定章节序：公司介绍-执行标准-系统技术说明-系统方案-业绩-证书。
    真实库取各类目首个 family + 全局块；公司介绍块按抬头品牌选。"""
    def block(ref):
        return {"kind": "block", "ref": ref,
                "title": store.block_title(ref)}

    def chapter(title, children):
        return {"kind": "chapter", "title": title, "children": children}

    def fam_chapter(cat):
        key = store.first_family_key(cat)
        if not key:
            return None
        kids = [block("fam:{}:features".format(key))]
        params = store.block("fam:{}:params".format(key))
        if params is not None:
            kids.append(block("fam:{}:params".format(key)))
        return chapter(key, kids)

    def glob_ref(folder, stems):
        for stem in stems:
            ref = "glob:{}:{}".format(folder, stem)
            if store.block(ref) is not None:
                return ref
        return None

    # 1 公司介绍：抬头品牌优先，缺则按 COPA B/COPA A/富林泰克 回退
    intro_ref = None
    if brand:
        intro_ref = glob_ref("公司介绍", (brand,))
    if intro_ref is None:
        intro_ref = glob_ref("公司介绍", ("COPA B", "COPA A", "富林泰克"))
    ch_intro = chapter("公司介绍", [])
    if intro_ref:
        ch_intro["children"].append(block(intro_ref))

    # 2 执行标准（_global/标准规范）
    ch_std = chapter("执行标准", [])
    std_ref = glob_ref("标准规范", ("form_01", "标准规范"))
    if std_ref:
        ch_std["children"].append(block(std_ref))

    # 3 系统技术说明：有项目条目时按类别分级（传感器-接线盒-模块-仪表），
    # 命中库块按块所属类目归章（不再按条目各起一章、也不再铺选型配置块）；
    # 平台秤/台秤等整机条目保留独立章节，其下分级人工调整
    ch_dev = chapter("系统技术说明", [])
    entries = getattr(project, "entries", []) if project is not None else []
    if entries:
        cat_order = ["传感器", "接线盒", "模块", "仪表"]
        title_map = {"称重模块": "模块"}     # 库类目名 -> 章节名
        by_cat = {}                          # 章节名 -> [family key]（去重）
        machine = {}                         # 整机类型 -> [family key]
        for e in entries:
            if not e.families and hasattr(store, "match_entry"):
                e.families = store.match_entry(e)
            if e.type_cn in ("平台秤", "台秤"):
                keys = machine.setdefault(e.type_cn, [])
                for key, _src in e.families:
                    if key not in keys:
                        keys.append(key)
                continue
            for key, _src in e.families:
                f = store.family_by_key(key)
                cat = title_map.get(f.category, f.category) if f \
                    else title_map.get(e.type_cn, e.type_cn)
                keys = by_cat.setdefault(cat, [])
                if key not in keys:
                    keys.append(key)

        def fam_blocks(keys):
            kids = []
            for key in keys:
                for kind in ("features", "params"):
                    if store.block("fam:{}:{}".format(key, kind)) is not None:
                        kids.append(block("fam:{}:{}".format(key, kind)))
            return kids

        for cat in cat_order + [c for c in by_cat if c not in cat_order]:
            if by_cat.get(cat):
                ch_dev["children"].append(chapter(cat, fam_blocks(by_cat[cat])))
        for type_cn, keys in machine.items():
            kids = fam_blocks(keys)
            if kids:
                ch_dev["children"].append(chapter(type_cn, kids))
    else:
        for cat in ("传感器", "称重模块", "仪表", "接线盒", "电缆"):
            sub = fam_chapter(cat)
            if sub is not None:
                ch_dev["children"].append(sub)

    # 4 系统方案（_global/整体方案说明）
    ch_scheme = chapter("系统方案", [])
    scheme_ref = glob_ref("整体方案说明", ("系统方案", "整体方案说明"))
    if scheme_ref:
        ch_scheme["children"].append(block(scheme_ref))

    # 5 业绩（_global/业绩）
    ch_perf = chapter("业绩", [])
    perf_ref = glob_ref("业绩", ("form_01", "业绩"))
    if perf_ref:
        ch_perf["children"].append(block(perf_ref))

    # 6 证书（媒体待补：保留空章，图入库后从池拖入）
    ch_cert = chapter("证书", [])
    cert_ref = glob_ref("证书", ("images", "general"))
    if cert_ref:
        ch_cert["children"].append(block(cert_ref))

    return [c for c in (ch_intro, ch_std, ch_dev, ch_scheme, ch_perf, ch_cert)
            if c["children"] or c["title"] == "证书"]


# ====序列化====

def serialize(items):
    lines = []

    def walk(nodes, depth):
        for n in nodes:
            if n["kind"] == "chapter":
                lines.append("{} {}".format("#" * (depth + 1), n["title"]))
                walk(n.get("children", []), depth + 1)
            else:
                lines.append("- {} | {}".format(n["ref"], n["title"]))

    walk(items, 0)
    return "\n".join(lines) + "\n"


def parse(text):
    items = []
    stack = {0: items}                 # 章节层级 -> 该层 children 列表
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        hashes = len(line) - len(line.lstrip("#"))
        if hashes and line[hashes:hashes + 1] == " ":
            depth = hashes - 1
            node = {"kind": "chapter", "title": line[hashes + 1:].strip(),
                    "children": []}
            parent = stack.get(depth)
            if parent is None:
                continue               # 层级跳跃：跳过（容错）
            parent.append(node)
            stack[depth + 1] = node["children"]
            for d in [d for d in stack if d > depth + 1]:
                del stack[d]
        elif line.startswith("- "):
            body = line[2:]
            ref, _, title = body.partition("|")
            stack[max(stack)].append(
                {"kind": "block", "ref": ref.strip(),
                 "title": title.strip() or ref.strip()})
    return items
