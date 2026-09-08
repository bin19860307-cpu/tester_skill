# -*- coding: utf-8 -*-
"""基线驱动 + 步骤预期 1:1 配对 —— 测试用例生成模板（excel-testcase-18col v1.4）

用法：
  1) 直接运行：python gen_baseline_template.py  -> 用内嵌 SAMPLE_BASELINE 生成演示用例
  2) 接入真实数据：在同目录放 baseline.json（结构见 SAMPLE_BASELINE），
     脚本优先读取它；改 JSON 一处、重跑即得新版用例。

特性：
  - 单一数据源 baseline（meta + texts + links），易变文案/链接只在 JSON 里维护
  - 用例内用占位符引用：{{T:ID}} / {{T:ID@i}} / {{L:ID}} / {{M:key}}
  - 步骤= [步骤, 预期] 配对列表；预期传 "-" 表示无需验证（渲染为 "N. -"）
  - 渲染【测试用例】+【文案基线】+【链接基线】三表
  - 自检：占位符残留、步骤数==预期数（"-" 也计一条）
"""
import os, json, re, openpyxl
from openpyxl.styles import Font, PatternFill, Border, Alignment, Side

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(HERE, "baseline.json")
OUT = os.path.join(HERE, "测试用例_基线驱动版.xlsx")

# ===== 内嵌示例数据源（真实使用时改为读取 baseline.json）=====
SAMPLE_BASELINE = {
    "meta": {"version": "v1.0", "owner": "QA", "created": "2026-07-09",
             "source": "示例需求", "page_url": "http://example.com/help"},
    "texts": {
        "PAGE_TITLE": "快速开始",
        "NAV_TABS": ["推荐步骤", "开发详解", "应用场景导引"],
        "BTN_EXPORT": "导出 JSON",
        "REC_DESCS": ["复制已有智能体快速上手", "在模板上魔改", "从零创作"],
    },
    "links": {
        "LINK_NOVICE": "https://docs.example.cn/s/novice",
        "LINK_MARKET": "https://example.cn/agent/agent-market",
    },
}

if os.path.exists(BASELINE_PATH):
    with open(BASELINE_PATH, encoding="utf-8") as f:
        B = json.load(f)
    print("✅ 已读取 baseline.json")
else:
    B = SAMPLE_BASELINE
    print("⚠️ 未找到 baseline.json，使用内嵌 SAMPLE_BASELINE 演示")

META = B["meta"]
VERSION = META["version"]; CREATOR = META["owner"]; TODAY = META["created"]

# ===== 占位符解析 =====
TOKEN_RE = re.compile(r"\{\{([TLM]):([\w@]+)\}\}")
def resolve(t):
    if not isinstance(t, str):
        return t
    def rep(m):
        kind, rest = m.group(1), m.group(2)
        if kind == "M":
            return str(META.get(rest, m.group(0)))
        if kind == "L":
            return str(B["links"].get(rest, m.group(0)))
        if kind == "T":
            key, idx = (rest.split("@") + [None])[:2] if "@" in rest else (rest, None)
            val = B["texts"].get(key)
            if isinstance(val, list):
                return str(val[int(idx)]) if idx is not None else " / ".join(map(str, val))
            return str(val) if val is not None else m.group(0)
        return m.group(0)
    return TOKEN_RE.sub(rep, t)

# ===== 套件定义：(编号, 名称, 父套件) =====
SUITES = [
    (1,    "示例项目",              0),
    (101,  "页面入口",              1),
    (102,  "推荐步骤",              1),
]

# ===== 用例定义：(编号, 名称, 归属套件, 预置条件, 步骤配对, 类型, 基础用例, 描述, 覆盖路径) =====
# 步骤配对：[[步骤, 预期], ...]  预期="-" 表示无需验证
CASES = [
    ("10101", "入口-菜单可见且跳转", 101,
     "已登录平台；可访问 {{M:page_url}}",
     [
        ["登录平台进入任意功能页面", "已登录并进入功能页面，左侧导航栏可见"],
        ["点击左侧【帮助文档】图标", "在新标签页跳转至 {{M:page_url}}，页面正常加载无报错"],
     ],
     "功能测试", "是", "核心入口路径", "10101"),

    ("10201", "推荐步骤-三卡片文案正确", 102,
     "已进入引导页",
     [
        ["进入引导页", "-"],
        ["定位到推荐学习步骤区域", "推荐学习步骤区域可见"],
        ["依次查看三张卡片描述", "三张卡片描述与真实页面一致：{{T:REC_DESCS}}"],
     ],
     "功能测试", "否", "文案一致性校验", "10201"),

    ("10202", "推荐步骤-卡片点击跳转教程", 102,
     "已进入引导页；外部文档可用",
     [
        ["进入引导页", "-"],
        ["点击「复制」卡片", "跳转至新手教程文档 {{L:LINK_NOVICE}}，正常加载"],
     ],
     "功能测试", "是", "卡片跳转", "10202"),
]

# ===== 基线表说明（稳定描述，与易变值分离）=====
TEXT_DESC = {
    "PAGE_TITLE": "页面标题",
    "NAV_TABS": "左侧分类导航",
    "BTN_EXPORT": "导出按钮文字",
    "REC_DESCS": "推荐步骤三卡片描述",
}
LINK_DESC = {
    "LINK_NOVICE": "新手教程文档",
    "LINK_MARKET": "智能体市场首页",
}

def render_text(v):
    return " / ".join(map(str, v)) if isinstance(v, list) else str(v)

# ===== 样式 =====
HDR_FILL = PatternFill("solid", fgColor="4472C4")
HDR_FONT = Font(bold=True, color="FFFFFF", size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")
HEADERS = ["实体标识","编号","名称","归属套件","版本","类型","可测试","基础用例","状态",
           "预置条件","测试过程","接收标准","创建人","创建时间","描述","脚本名称","验证话单","信令流程","覆盖路径"]

# ===== 构建工作簿 =====
wb = openpyxl.Workbook()

# --- Sheet1: 测试用例 ---
ws = wb.active
ws.title = "测试用例"
for c, h in enumerate(HEADERS, 1):
    cell = ws.cell(1, c, h); cell.fill = HDR_FILL; cell.font = HDR_FONT
    cell.alignment = CENTER; cell.border = BORDER

r = 2
for code, name, parent in SUITES:
    ws.cell(r, 1, "用例套件"); ws.cell(r, 2, code); ws.cell(r, 3, name); ws.cell(r, 4, parent)
    for c in range(1, 20):
        cell = ws.cell(r, c); cell.border = BORDER
    r += 1

residual = []; mismatch = []
for row_data in CASES:
    (code, name, suite, pre, pairs, tc_type, is_basic, desc, cov) = row_data
    pre_r = resolve(pre)
    pairs_r = [[resolve(s), resolve(e)] for s, e in pairs]
    steps_r = "\n".join(f"{i}. {s}" for i, (s, e) in enumerate(pairs_r, 1))
    accept_r = "\n".join(f"{i}. {e}" for i, (s, e) in enumerate(pairs_r, 1))
    if len(pairs_r) == 0:
        mismatch.append((code, name, "空步骤"))
    for fld, val in [("预置条件", pre_r), ("测试过程", steps_r), ("接收标准", accept_r)]:
        if isinstance(val, str) and TOKEN_RE.search(val):
            residual.append((code, name, fld, val[:60]))
    vals = ["测试用例", code, name, suite, VERSION, tc_type, "是", is_basic, "待评审",
            pre_r, steps_r, accept_r, CREATOR, TODAY, desc, "", "", "", cov]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(r, c, v); cell.border = BORDER; cell.alignment = WRAP
    r += 1

widths = [10, 9, 36, 8, 8, 9, 7, 8, 8, 38, 44, 42, 8, 12, 18, 10, 10, 10, 8]
for i, w in enumerate(widths, 1):
    ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
ws.freeze_panes = "A2"

# --- Sheet2: 文案基线 ---
ws_t = wb.create_sheet("文案基线")
t_headers = ["元素ID", "位置/说明", "预期文案", "适用版本", "来源"]
for c, h in enumerate(t_headers, 1):
    cell = ws_t.cell(1, c, h); cell.fill = HDR_FILL; cell.font = HDR_FONT
    cell.alignment = CENTER; cell.border = BORDER
rr = 2
for tid, val in B["texts"].items():
    ws_t.cell(rr, 1, tid); ws_t.cell(rr, 2, TEXT_DESC.get(tid, ""))
    ws_t.cell(rr, 3, render_text(val)); ws_t.cell(rr, 4, VERSION); ws_t.cell(rr, 5, META.get("source", ""))
    for c in range(1, 6):
        cell = ws_t.cell(rr, c); cell.border = BORDER; cell.alignment = WRAP
    rr += 1
for i, w in enumerate([22, 30, 60, 10, 34], 1):
    ws_t.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
ws_t.freeze_panes = "A2"

# --- Sheet3: 链接基线 ---
ws_l = wb.create_sheet("链接基线")
l_headers = ["链接ID", "触发元素/说明", "预期URL", "类型", "状态", "适用版本", "来源"]
for c, h in enumerate(l_headers, 1):
    cell = ws_l.cell(1, c, h); cell.fill = HDR_FILL; cell.font = HDR_FONT
    cell.alignment = CENTER; cell.border = BORDER
rr = 2
for lid, url in B["links"].items():
    ws_l.cell(rr, 1, lid); ws_l.cell(rr, 2, LINK_DESC.get(lid, "")); ws_l.cell(rr, 3, url)
    ws_l.cell(rr, 4, "外"); ws_l.cell(rr, 5, "待对齐" if "<" in url else "已核对")
    ws_l.cell(rr, 6, VERSION); ws_l.cell(rr, 7, META.get("source", ""))
    for c in range(1, 8):
        cell = ws_l.cell(rr, c); cell.border = BORDER; cell.alignment = WRAP
    rr += 1
for i, w in enumerate([22, 30, 52, 6, 10, 10, 34], 1):
    ws_l.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
ws_l.freeze_panes = "A2"

wb.save(OUT)

# ===== 自检 =====
print(f"=== 基线驱动版生成完成（步骤-预期 1:1 配对）===")
print(f"套件数: {len(SUITES)}  用例数: {len(CASES)}")
print(f"文案基线条目: {len(B['texts'])}  链接基线条目: {len(B['links'])}")
print(f"残留未解析占位符: {len(residual)} 条")
print(f"步骤/预期数不一致用例: {len(mismatch)} 条")
if residual:
    print("\n!! 残留占位符:"); [print("  ", x) for x in residual]
if mismatch:
    print("\n!! 步骤与预期数不一致:"); [print("  ", x) for x in mismatch]
print(f"\n输出: {OUT}")
