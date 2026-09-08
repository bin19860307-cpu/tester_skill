---
name: excel-testcase-18col
display_name: 企业18列测试用例生成器
display_name_en: Excel Testcase 18 Columns
author: Chane
version: 2.0.0
agent_created: true
description: >
  生成符合企业18列标准格式的测试用例Excel文件（参考班级管理测试用例_v2.xlsx模板）。
  触发词：18列格式、企业模板、用例Excel、生成测试用例Excel、班级管理模板、按套件生成用例。
  进阶能力：基线驱动（文案/链接抽单一数据源）+ 步骤与预期 1:1 编号配对（含 "-" 无需验证标记）+ 三表输出（测试用例/文案基线/链接基线）。
description_zh: "生成符合企业 18 列标准格式的测试用例 Excel（基线驱动：文案/链接抽离单一数据源，步骤与预期 1:1 编号配对），支持按套件批量生成正式用例。"
description_en: "Generate enterprise-standard 18-column test case Excel files with baseline-driven single data source and 1:1 step-expectation pairing, supporting per-suite batch generation."
---

# Excel 测试用例生成器（18列企业模板）

## 适用场景

当用户需要生成 Excel 格式的测试用例，且满足以下任一条件时使用本 Skill：
- 提及「班级管理模板」「18列格式」「企业标准格式」
- 提供了参考 `.xlsx` 文件（如 `班级管理测试用例_v2.xlsx`）
- 要求用「用例套件 + 测试用例」层级结构组织用例

> **与 test-pipeline-mvp 的关系**：本 skill 是 `test-pipeline-mvp` Phase 5 的「18 列企业模板执行器」（mvp v2.7 起显式委派）。当 mvp 目标交付为 18 列 AITest 企业模板时，由本 skill 落地用例生成（基线驱动三表 + 16 质量红线 + 生成后机器校验）；mvp 原生的 12 列标准结构（Phase 5.1）为另一可选格式，二者物理列不同、二选一。

---

## 模板规格

### 工作表名称
`测试用例表`

### 18 列结构

| 列 | 列名 | 实体标识=用例套件 | 实体标识=测试用例 |
|----|------|-------------------|-------------------|
| A | 实体标识 | `用例套件` | `测试用例` |
| B | 编号 | 整数（1 / 101~） | 5位整数（10101~） |
| C | 名称 | 套件名称 | 用例名称 |
| D | 归属套件 | 父套件编号（顶层=0，一级=1） | 所属套件编号 |
| E | 版本 | 留空 | `v1.0` |
| F | 类型 | 留空 | 功能测试 / 异常测试 / 边界测试 |
| G | 可测试 | 留空 | `是` |
| H | 基础用例 | 留空 | `否` |
| I | 状态 | 留空 | `待评审` |
| J | 预置条件 | 留空 | 前置条件说明（**多条时按 `1. 2. 3.` 条列展示**，用 `\n` 分隔，禁止单段/分号拼接） |
| K | 测试过程 | 留空 | 步骤（`\n` 分隔） |
| L | 接收标准 | 留空 | 预期结果 |
| M | 创建人 | 留空 | `QA` |
| N | 创建时间 | 留空 | `YYYY-MM-DD` |
| O | 描述 | 可选备注 | 可选备注 |
| P | 脚本名称 | 留空 | 留空 |
| Q | 验证话单 | 留空 | 留空 |
| R | 信令流程 | 留空 | 留空 |
| S | 覆盖路径 | 留空 | `节点A→节点B→节点C`（可选，与 test-pipeline-mvp Phase 1.5 节点 ID 对应） |

> **★ 第 19 列为可选列**。当配合 test-pipeline-mvp Phase 1.5（流程图绘制）使用时启用；
> 不使用流程图时可省略此列（保持 18 列格式）。

### 编号规则

```
顶层套件：编号=1，归属套件=0
一级套件：编号=101/102/103...，归属套件=1
测试用例：编号=10101/10102...，前3位=所属套件编号
```

### 第 19 列「覆盖路径」启用方式（可选）

当配合 test-pipeline-mvp 流程图绑定时，在 `tc()` 函数中增加 `coverage_path` 参数：

```python
def tc(code, name, parent, pre, steps, accept, tc_type="功能测试", desc="", coverage_path=""):
    DATA.append({
        ...
        "覆盖路径": coverage_path,   # 格式：节点A→节点B→节点C
    })
```

示例：
```python
tc(10101, "企业Token充足时优先消耗企业Token", 101,
   "用户已登录，企业Token余额 > 0",
   "1. 发起对话请求\n2. 观察Token扣减记录",
   "企业Token余额减少1，对话完成",
   tc_type="功能测试",
   coverage_path="CheckAdmin→P1→Done")
```

### 样式规范

| 区域 | 背景色 | 字体 |
|------|--------|------|
| 标题行 | `#1F4E79`（深蓝） | 白色粗体 Microsoft YaHei 10 |
| 顶层/一级套件行 | `#D9E1F2`（浅蓝） | `#1F4E79` 粗体 |
| 二级套件行 | `#EDF2F8`（淡蓝） | `#17375E` 粗体 |
| 用例数据行 | 无填充 | 默认 Microsoft YaHei 9 |
| 边框 | `#CCCCCC` 细线全框 | — |

---

## 工作流程

### Step 1：需求分析

从用户提供的需求文档或功能描述中提取：
- 主要功能模块列表（→ 对应一级套件）
- 每个模块的测试场景（→ 对应测试用例）

### Step 2：规划套件结构

输出套件层级表供用户确认：

```
1（顶层） - [项目名称]
  ├── 101 - [模块A]
  ├── 102 - [模块B]
  └── 103 - [模块C]
```

### Step 3：生成 Python 脚本

基于 `scripts/gen_testcases_template.py` 填写用例数据并输出完整脚本。

**关键规则**：
- 测试步骤使用 `\n` 分隔各步骤（Python 字符串内 `\n` 即可，openpyxl 写入后自动换行）
- **预置条件同样用 `\n` 分隔并编号**：多个前置条件必须写成 `1. 条件一\n2. 条件二\n3. 条件三` 的条列形式，不得用分号拼成单段（见质量红线第 15 条）
- `tc_type` 默认为 `"功能测试"`，异常场景改为 `"异常测试"`，边界场景改为 `"边界测试"`
- `OUTPUT_PATH` 根据用户工作区自动填写
- **按钮表示规则**：所有可点击的按钮名称统一使用全角方括号 `【】` 包裹（例如 `【导出 JSON】`、`【发布】`、`【取消】`、`【返回】`）。错误提示语、下拉选项值、占位符等非按钮文本保持原引号或原样，不可用 `【】` 包裹；生成前若源文本中按钮以 `'按钮名'`/`"按钮名"` 形式出现，需转换为 `【按钮名】`。

### 通用质量红线（生成前必检）

以下为 2026-07 在多轮用例生成中反复踩坑沉淀的硬性规则，**生成任何测试用例前必须逐项自检**：

1. **名称体现测试点，步骤不重复**：用例名称直接点明验证点（如 `智能体发布-学校大模型-发布到全国-弹出提醒`）；测试步骤只写操作与导航，禁止在步骤开头复述测试点。
2. **步骤具体可执行**：必须含导航路径（菜单/页面/按钮），不得写「进入详情页」之类模糊表述；应写「在左侧导航点击【智能体管理】→ 列表点击智能体名称进入详情页」。
3. **纯文字表述，不暴露代码/字段**：禁止 `school_id` / `provider_id` / `config.model` / `flowJson` / `<agentId>` 等技术写法；改用业务术语（已绑定学校 / 未绑定学校 / 系统模型 / 学校大模型 / 空间大模型 / 模型配置项 / `{智能体ID}`）。用例面向测试执行人员，非开发。
4. **禁止编造虚构异常 / 过度测试**（最高优先级）：不得为「覆盖全面」编造不真实场景——如空数组/数据被删降级、模型名含特殊字符(XSS)、引号尖括号等。判定原则：① 该异常在真实业务是否真会发生？② 数据是否平台正常录入（不会有特殊字符）？③ 前置条件不满足时（如未配置模型）根本不触发后续校验/弹窗，应写「前置条件负向」（如「未配置不触发提醒」）而非「配置但异常」。
5. **前置条件真实且同套件可比**：同套件用例的预置条件保持一致的基线（如都「存在至少 1 条记录」），差异点只在被测变量。
6. **基础用例标记准确**：正向主流程用例标 `是`，异常/边界/负向标 `否`。**模板默认写死 `否` 是错误的**，须按用例性质判断（见下方 tc 函数 `is_basic` 参数）。
7. **接收标准具体可验证**：预期结果写明具体表现（文件名格式、提示文案、状态变化），不得写「功能正常」「提示错误」等模糊语。
8. **单值/多值语义对齐需求文案**：需求文案含变量（如 `{names}`）时，用例预期须明确该变量是单值（一个）还是多值（多个、顿号分隔），不得含糊。
9. **归属聚焦、按需分组件**：明确用例归属套件/组件，不混入无关用例；多类型时按类型拆子套件（如对话型/应用型/工作流各一组件）。
10. **需求缺口显式标注（不默认假设）**：需求存在不明确处（如默认有效期、权限差异、降级逻辑）时，须列为「需求缺口/待确认」并标注优先级；用例中对应项标记为假设而非既定事实，避免凭空臆造前置或预期。
11. **角色/权限维度系统性覆盖**：涉及多角色（admin/教师/学生/运营等）或多档位时，基于角色/权限矩阵系统性构造用例，覆盖权限差异与豁免场景（如 admin 豁免控制），而非零散列举。
12. **生成后完整性自检（对齐评审清单）**：产出前核对——① 是否覆盖全部需求点；② 是否同时具备正向+反向+异常场景；③ 步骤是否清晰可执行；④ 预期是否明确可验证；⑤ 权限/角色是否覆盖。参考《测试工程流程规范 v1.2》评审检查清单。
13. **步骤与预期 1:1 编号对应（含无需验证标记）**：每条步骤必须有编号一致、可验证的「接收标准」预期结果，渲染为 `1. 步骤 / 1. 预期` 两列严格对齐，不得"有步骤无验证"或省略预期列。**纯导航/前置步骤的预期传 `-`**，渲染即 `N. -`（如「进入引导页」「已进入引导页」「登录平台进入某页面」），既保持 1:1 对齐又不强行编造伪预期；有真实验证价值的导航/状态步骤须保留预期（如「确认左侧选中体验智能体 → 已选中体验智能体」）。生成器须自检：用例内步骤数 == 预期数（含 `-` 也计一条）。
14. **预期具体自洽、禁止引用设计稿/截图**：预期结果必须写入**真实可核对的文案/数据**，不得写「与设计稿(image 7)一致」「与切图一致」「详见设计稿」之类依赖外部资料的引用——因为很多执行测试的人员拿不到设计稿/原型。应把具体预期文案直接写进预期（如「4 步描述依次为：①Step 1: 大赛启动 — 发布规则与报名入口；②…」）。多元素（卡片/步骤/标签）的文案用「①A — a；②B — b」配对列出，或抽取到 `{{T:ID}}` 基线并由生成器内联展开（基线驱动模式下推荐），确保导出到单 sheet（如平台导入模板）后预期仍自洽可读。
15. **预置条件条列化（1. 2. 3.）**：当一条用例有多个前置条件时，必须用 `1. 2. 3.` 编号逐条列出（用 `\n` 分隔），**禁止**写成单段落或用分号 `；` 拼接成一句话（如「系统中存在 admin 校管；使用普通校管账号登录」应拆为两条）。单条件用例可保持单行，但多条件务必条列。生成器行高计算须同时纳入「预置条件」行数，避免条列化后内容被压成单行（行高取 预置条件/测试过程/接收标准 三列最大行数）。

16. **用例→套件归属一致性（生成后机器校验，最高优先级之一）**：每条「测试用例」的「归属套件」列**必须等于其编号 // 100（即编号前 3 位）**，且该编码须在「用例套件」实体中真实存在。生成器 `tc()` 的 `suite_id` 参数极易被误写成 `编号-10000` 之类，导致用例错挂到别的套件（如 S1 的用例被分散挂到 S2–S8），导入平台时归类全乱。**绝不能只数"用例套件"实体数就认为结构正确**——必须逐条核对用例的归属列是否真指向所属套件。生成后务必跑一次机器校验脚本（见 Step 5.5）。

17. **步骤与预期中禁止出现「合并验证/主用例追溯」等内部引用标注**：用例的「测试过程」和「接收标准」只能写**可执行操作**与**可验证结果**，不得写入用于内部关联的元注释，例如 `（合并验证：EC10605）`、`本用例验证点已由主用例 EC11007 在合并验证步骤中一并执行，本行保留独立追溯`、`（合并验证：...）` 等。原因：① 这些标注导入用例系统后不可见/不解析，对执行人员无意义；② 它们污染步骤/预期，导致执行时看到非操作非验证内容；③ 用例之间的关联应通过「归属套件」「需求编号」「覆盖路径」「描述/备注」或平台本身的关联字段维护，而非塞进步骤。如确需说明用例间关系，放入「描述」列或测试点文档，不要放进「测试过程」和「接收标准」。

### Step 4（进阶，推荐）：基线驱动 + 步骤预期 1:1 配对模式

当用例集**需长期维护、文案/链接易变**（如帮助文档、引导页、运营活动页）时，采用本模式：把"测试逻辑"与"测试数据"解耦，后续改文案或换链接只改一个 JSON 文件、重跑脚本即得新版用例，且能单独走查基线表评审影响面。

#### 4.1 单一数据源（baseline.json）

把全部易变文案与链接抽到一份 JSON，用例内只引用不写死：

```json
{
  "meta": {"version":"5.2","owner":"QA","created":"2026-07-09",
           "source":"线上页 http://dev.example.com/core/help","page_url":"http://dev.example.com/core/help"},
  "texts": {
    "BTN_EXPORT": "导出 JSON",
    "NAV_TABS": ["推荐步骤","开发详解","应用场景导引"],
    "REC_DESCS": ["复制已有智能体快速上手","在模板上魔改","从零创作"]
  },
  "links": {
    "LINK_NOVICE": "https://docs.xxx.cn/s/novice",
    "LINK_MARKET": "https://xxx.cn/agent/agent-market"
  }
}
```

#### 4.2 占位符约定

| 占位符 | 含义 | 解析 |
|--------|------|------|
| `{{T:ID}}` | 引用文案（数组自动以「 / 」连接） | 真实文案 |
| `{{T:ID@i}}` | 引用文案数组第 i 项（0 起） | 单条文案 |
| `{{L:ID}}` | 引用链接 | 真实 URL |
| `{{M:key}}` | 引用 meta 字段（如 page_url） | 值 |

#### 4.3 步骤与预期 1:1 配对 + `-` 无需验证

用例步骤改为 `[步骤, 预期]` 配对列表；预期为 `-` 表示无需验证。渲染示例：

```
【测试过程】                   【接收标准】
1. 进入引导页                  1. -              ← 无需验证
2. 点击左侧【实训工作坊】       2. 左侧切换为实训工作坊
3. 查看右侧标题                3. 右侧标题显示「实训工作坊」
4. 整体确认切换互不干扰        4. 三者切换互不干扰、内容正确
```

- 每条步骤必须有编号一致、可验证的预期结果，不得"有步骤无验证"。
- 纯导航/前置步骤的预期传 `-`，渲染即 `N. -`（如「进入引导页」「已进入引导页」），保持 1:1 对齐且不编造伪预期。
- 有真实验证价值的导航/状态步骤保留预期（如「确认左侧选中体验智能体 → 已选中体验智能体」）。
- **预置条件在基线模式同样条列化**：`pre` 参数传入 `1. 条件一\n2. 条件二` 形式，`resolve(pre)` 解析后仍保持编号；多条条件不得写成单段。

#### 4.4 三表输出结构

除【测试用例】外，额外输出两张独立走查表，便于单独评审与维护：

- **【文案基线】**：`元素ID | 位置/说明 | 预期文案 | 适用版本 | 来源`
- **【链接基线】**：`链接ID | 触发元素/说明 | 预期URL | 类型(内/外) | 状态(已核对/待对齐) | 适用版本 | 来源`（URL 含 `<` 占位者标"待对齐"）

#### 4.5 生成器关键代码片段

```python
import json, re, openpyxl
B = json.load(open("baseline.json", encoding="utf-8"))
VERSION = B["meta"]["version"]; CREATOR = B["meta"]["owner"]; TODAY = B["meta"]["created"]
TOKEN_RE = re.compile(r"\{\{([TLM]):([\w@]+)\}\}")

def resolve(t):
    if not isinstance(t, str): return t
    def rep(m):
        kind, rest = m.group(1), m.group(2)
        if kind == "M": return str(B["meta"].get(rest, m.group(0)))
        if kind == "L": return str(B["links"].get(rest, m.group(0)))
        if kind == "T":
            key, idx = (rest.split("@") + [None])[:2] if "@" in rest else (rest, None)
            val = B["texts"].get(key)
            if isinstance(val, list):
                return str(val[int(idx)]) if idx is not None else " / ".join(map(str, val))
            return str(val) if val is not None else m.group(0)
        return m.group(0)
    return TOKEN_RE.sub(rep, t)

# pairs = [[步骤, 预期], ...]，预期可为 "-" 表示无需验证
def tc_pair(code, name, suite, pre, pairs, tc_type="功能测试", is_basic=False, desc="", cov=""):
    pre_r = resolve(pre)
    pairs_r = [[resolve(s), resolve(e)] for s, e in pairs]
    steps_r  = "\n".join(f"{i}. {s}" for i, (s, e) in enumerate(pairs_r, 1))
    accept_r = "\n".join(f"{i}. {e}" for i, (s, e) in enumerate(pairs_r, 1))
    assert len(pairs_r) > 0, f"{code} 步骤为空"          # 步骤数==预期数 自检（"-" 也计一条）
    return {"实体标识":"测试用例","编号":code,"名称":name,"归属套件":suite,
            "版本":VERSION,"类型":tc_type,"可测试":"是","基础用例":"是" if is_basic else "否",
            "状态":"待评审","预置条件":pre_r,"测试过程":steps_r,"接收标准":accept_r,
            "创建人":CREATOR,"创建时间":TODAY,"描述":desc,"覆盖路径":cov}
```

> 完整可运行示例见 `scripts/gen_baseline_template.py`（基于「帮助文档引导页」需求沉淀，含三表渲染、占位符解析、步骤/预期数自检、基线表说明字典）。

#### 4.6 维护方式对比

| 变更场景 | 传统写死模式 | 基线驱动模式 |
|---------|-------------|-------------|
| 文案微调（如「复刻」→「复制」） | 逐条 find/replace 易漏 | 改 baseline.json 1 处，重跑 |
| 链接 URL 定了 | 同上 | 改 baseline 1 处，引用它的用例自动更新 |
| 评审影响面 | 无法快速定位哪些用例受影响 | 基线表单独走查，用例引用 ID 一目了然 |

---

### Step 5：执行脚本生成文件

```bash
python 脚本路径.py
```

执行成功后输出：
- Excel 文件路径
- 套件数 / 测试用例数汇总

---

### Step 5.5：生成后机器校验（必须，防错挂套件）

生成脚本跑通 ≠ 产物正确。生成后必须追加一次脚本级校验，至少覆盖四项：

```python
import openpyxl, re
f = "生成的文件.xlsx"
wb = openpyxl.load_workbook(f, data_only=True)
ws = wb["测试用例表"]
rows = list(ws.iter_rows(values_only=True))
H = ["实体标识","编号","名称","归属套件","版本","类型","可测试","基础用例","状态","预置条件","测试过程","接收标准","创建人","创建时间","描述","脚本名称","验证话单","信令流程","覆盖路径"]
recs = [dict(zip(H, r)) for r in rows if r[0] in ("用例套件","测试用例")]
suites = {r["编号"] for r in recs if r["实体标识"]=="用例套件"}
tcs = [r for r in recs if r["实体标识"]=="测试用例"]
# ① 用例→套件归属一致性（既往真实事故点）
bad = [(t["编号"], t["归属套件"]) for t in tcs if t["归属套件"] != t["编号"]//100 or t["归属套件"] not in suites]
assert not bad, f"归属套件错误: {bad[:10]}"
# ② 占位符残留（基线驱动模式）
pat = re.compile(r"\{\{[^}]+\}\}")
res = [t["编号"] for t in tcs for k in ("预置条件","测试过程","接收标准","名称","描述") if pat.search(str(t[k]))]
assert not res, f"占位符未解析: {res[:10]}"
# ③ 步骤数==预期数（1:1 配对）
badp = [t["编号"] for t in tcs if len(str(t["测试过程"]).split("\n")) != len(str(t["接收标准"]).split("\n"))]
assert not badp, f"步骤/预期未配对: {badp[:10]}"
# ④ 编号唯一
ids = [t["编号"] for t in tcs]
assert len(ids)==len(set(ids)), "编号重复"
# ⑤ 步骤/预期中禁止「合并验证」等内部引用标注
mv_pat = re.compile(r"[（(]\s*合并验证\s*[:：]|已由主用例\s+EC\d+|合并验证点已.*?一并执行")
mv_bad = [t["编号"] for t in tcs for k in ("测试过程","接收标准") if mv_pat.search(str(t[k]))]
assert not mv_bad, f"步骤/预期含合并验证引用: {mv_bad[:10]}"
print("校验通过：归属一致性 / 0残留 / 1:1配对 / 编号唯一 / 无合并验证引用")
```

> 五项中 **① 归属一致性** 是既往真实事故点（曾因 `suite_id` 误写导致 75 条用例错挂套件，仅数套件实体数无法发现），务必执行；**⑤ 合并验证引用** 为新增校验，避免步骤/预期被内部追溯标注污染。

---

### Step 6：Obsidian 知识库同步（默认启用）

Step 5.5 四项校验全过后，将用例摘要与测试点关联同步至 Obsidian 知识库，**按版本组织**（与 test-pipeline-mvp Phase 8.5 协作）。

#### 6.1 目标结构

```
output/testcases
├── 00-v{版本}{模块}-版本总览.md   ← 索引页（wikilink 串联用例/测试点）
├── 用例\
│   ├── 全量测试用例.md            ← 去重合并用例摘要（多源 xlsx 时）
│   └── 生成数据清单.md            ← 索引：生成器 py / baseline json / xlsx 源路径（不复制二进制）
└── 测试点\                        ← 评审产物（测试点梳理/风险地图/合并簇/覆盖率评审/评审报告/产品澄清）
```

#### 6.2 触发与跳过（⚠️ 版本状态门禁：仅正式版入库）

- **核心规则**：仅当交付物标记为「**正式版**」时执行同步；**草稿版一律不入库**（避免草稿污染知识库）。
  - 标记方式：生成时显式传入 `--formal`，或在生成器输出 frontmatter 写入 `version_status: 正式版`。
  - 未标记 / 草稿版 → 跳过，提示「草稿版不入库，正式交付请加 `--formal`」。
- **双重前提**：Step 5.5 四项校验必须全过（校验不过不入库，无论正式/草稿）。
- `--no-sync` 优先级最高，可强制跳过（覆盖 `--formal`）。
- 模块名取需求/模块同名（如 `权益控制`、`发布模型提醒`）；版本取需求版本（如 `v5.2`）。

#### 6.3 产物

- **用例摘要页**：按套件分组，列出编号/名称/类型/基础用例/可测试/状态；多源 xlsx 按编号去重合并（字段跨源补全）
- **生成数据清单**：索引 py/json/xlsx，附 `file:///` 绝对路径与更新时间，**二进制不复制进知识库**（单一真源留在工作区）
- **版本总览**：`00-v{版本}{模块}-版本总览.md`，用 wikilink 串联「用例/」与「测试点/」

#### 6.4 实现要点

- 用 `obsidian-cli create "测试用例/v{版本}/{模块}/用例/全量测试用例" --content "..."` 写入（headless 直连 Vault，勿加 `--open`），或直接 Write 绝对路径
- 测试点评审 md 从源报告目录复制（加 frontmatter：tags 含 `测试用例,v{版本},{模块}` / version / source / created / updated），内容原样保留
- 与 mvp 协作：**18 列模式本步已同步**，mvp Phase 8.5 仅做存在性校验（幂等），不重复写

---

## Python 脚本参考（完整模板）

> 脚本存放在 `scripts/gen_testcases_template.py`

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date

OUTPUT_PATH = r"C:\替换为实际输出路径\测试用例_v2.xlsx"
TODAY = date.today().strftime("%Y-%m-%d")
VERSION = "v1.0"
CREATOR = "QA"

HEADER_FILL  = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT  = Font(name="Microsoft YaHei", bold=True, color="FFFFFF", size=10)
SUITE_FILL   = PatternFill("solid", fgColor="D9E1F2")
SUITE_FONT   = Font(name="Microsoft YaHei", bold=True, color="1F4E79", size=10)
SUITE2_FILL  = PatternFill("solid", fgColor="EDF2F8")
SUITE2_FONT  = Font(name="Microsoft YaHei", bold=True, color="17375E", size=10)
NORMAL_FONT  = Font(name="Microsoft YaHei", size=9)
THIN   = Side(style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP   = Alignment(wrap_text=True, vertical="top")

HEADERS = [
    "实体标识","编号","名称","归属套件","版本","类型","可测试","基础用例",
    "状态","预置条件","测试过程","接收标准","创建人","创建时间","描述",
    "脚本名称","验证话单","信令流程",
    "覆盖路径",   # 第 19 列（可选，配合 test-pipeline-mvp Phase 1.5 使用）
]
COL_WIDTHS = [10, 10, 48, 10, 8, 10, 8, 8, 8, 36, 52, 52, 8, 12, 30, 14, 8, 8, 40]
DATA = []

def suite(code, name, parent, desc=""):
    DATA.append({"实体标识":"用例套件","编号":code,"名称":name,"归属套件":parent,"描述":desc})

def tc(code, name, parent, pre, steps, accept, tc_type="功能测试", is_basic=False, desc="", coverage_path=""):
    DATA.append({
        "实体标识":"测试用例","编号":code,"名称":name,"归属套件":parent,
        "版本":VERSION,"类型":tc_type,"可测试":"是","基础用例":"是" if is_basic else "否","状态":"待评审",
        "预置条件":pre,"测试过程":steps,"接收标准":accept,
        "创建人":CREATOR,"创建时间":TODAY,"描述":desc,
        "覆盖路径":coverage_path,
    })

# ====== 用例数据区域（按需填写）======
suite(1, "项目名称", 0, "顶层套件说明")
suite(101, "功能模块A", 1, "模块A说明")
tc(10101, "用例名称", 101,
   "1. 前置条件一（如已登录平台/已存在目标数据）\n2. 前置条件二（如角色为 admin）",
   "1. 步骤一\n2. 步骤二\n3. 步骤三",
   "1. 预期结果一\n2. 预期结果二\n3. 预期结果三")
# =====================================

def create_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "测试用例表"
    for ci, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.fill=HEADER_FILL; cell.font=HEADER_FONT
        cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
        cell.border=BORDER
    ws.row_dimensions[1].height = 28
    for ci, w in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    row = 2
    suite_cnt = tc_cnt = 0
    for record in DATA:
        is_suite = record.get("实体标识") == "用例套件"
        parent   = record.get("归属套件", 0)
        if is_suite:
            fill = SUITE2_FILL if isinstance(parent,int) and parent > 1 else SUITE_FILL
            font = SUITE2_FONT if isinstance(parent,int) and parent > 1 else SUITE_FONT
            suite_cnt += 1
        else:
            tc_cnt += 1
        for ci, h in enumerate(HEADERS, 1):
            cell = ws.cell(row=row, column=ci, value=record.get(h,""))
            cell.border = BORDER
            if is_suite:
                cell.fill=fill; cell.font=font
                cell.alignment=Alignment(horizontal="left",vertical="center",wrap_text=True)
            else:
                cell.font=NORMAL_FONT; cell.alignment=WRAP
        if is_suite:
            ws.row_dimensions[row].height = 18
        else:
            lines = max(
                str(record.get("预置条件","")).count("\n")+1,
                str(record.get("测试过程","")).count("\n")+1,
                str(record.get("接收标准","")).count("\n")+1
            )
            ws.row_dimensions[row].height = max(lines*14+6, 20)
        row += 1

    ws.freeze_panes = "A2"
    wb.save(OUTPUT_PATH)
    print("[OK] Generated:", OUTPUT_PATH)
    print("[STAT] Suites: %d  TestCases: %d" % (suite_cnt, tc_cnt))

if __name__ == "__main__":
    create_workbook()
```

---

## 注意事项

1. **`\n` 换行**：Python 字符串中的 `\n` 在写入 openpyxl 后自动换行，无需 `chr(10)` 特殊处理
2. **编号唯一性**：套件编号与用例编号不能重复，用例编号前3位需与归属套件编号一致
3. **套件层级最多2级**：顶层（归属=0）→ 一级（归属=1）→ 如需三级则归属=套件编号（样式变淡蓝）
4. **OUTPUT_PATH**：必须是绝对路径，目录必须存在
5. **依赖库**：`openpyxl`，通过 `pip install openpyxl` 安装
6. **按钮表示**：用例中涉及的可点击按钮（如导出、发布、取消、返回、保存、删除等）一律用 `【按钮名】` 表示；错误提示、下拉选项值、提示语等非按钮文本不包裹 `【】`

---

## 历史版本

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-14 | 初始版本，基于班级管理测试用例模板 |
| v1.1 | 2026-05-20 | 新增第 19 列「覆盖路径」（可选），支持 test-pipeline-mvp 流程图绑定；更新 Python 脚本模板；更新历史生成文件记录 |
| v1.2 | 2026-07-07 | 新增按钮表示规则：所有可点击按钮统一用 `【】` 包裹（如 `【导出 JSON】`、`【发布】`），非按钮文本保持原样 |
| v1.3 | 2026-07-08 | 新增「通用质量红线」9条（名称体现测试点、步骤具体化、纯文字表述、禁止虚构异常、前置条件可比、基础用例标记准确、接收标准具体、单多值对齐、归属聚焦）；修正 tc() 默认基础用例写死`否`问题，新增 `is_basic` 参数由调用方按用例性质设置 |
| v1.4 | 2026-07-09 | 新增「进阶模式：基线驱动 + 步骤预期 1:1 配对」：① 单一数据源 baseline.json（文案/链接抽离，占位符引用）；② 步骤改为 `[步骤,预期]` 配对列表，渲染 `1.步骤/1.预期` 严格 1:1；③ 预期 `-` 表示无需验证（渲染 `N. -`）；④ 三表输出（测试用例/文案基线/链接基线）；⑤ 通用质量红线新增第13条「步骤与预期 1:1 编号对应（含无需验证标记）」；新增可运行模板 `scripts/gen_baseline_template.py` |
| v1.5 | 2026-07-09 | 通用质量红线新增第14条「预期具体自洽、禁止引用设计稿/截图」：预期须写入真实可核对文案，不得写「与设计稿(image X)一致」之类外部依赖；多元素文案用「①A — a；②B — b」配对列出或抽基线内联展开，确保平台导入单 sheet 后仍自洽 |
| v1.6 | 2026-07-10 | 通用质量红线新增第15条「预置条件条列化（1. 2. 3.）」：多条前置条件必须用编号逐条列出、禁止单段/分号拼接；Step 3 关键规则、列规格(J)、模板脚本示例同步更新；生成器行高计算纳入预置条件行数；基线模式 4.3 节明确 pre 同样条列化；模板脚本打印改为 ASCII 标记（规避 Windows GBK emoji 崩溃） |
| v1.7 | 2026-07-30 | 通用质量红线新增第16条「用例→套件归属一致性（生成后机器校验）」；新增 Step 5.5 生成后机器校验清单（四项：归属一致性 / 占位符残留 / 步骤预期1:1 / 编号唯一），含可直接复用的校验脚本；版本号升级 1.7.0 |
| v1.8 | 2026-08-04 | Step 5.5 后新增 Step 6「Obsidian 知识库同步（默认启用）」：生成校验通过后按版本(v{版本}/{模块})组织同步用例摘要页(多源xlsx去重合并)+生成数据清单(索引py/json/xlsx,不复制二进制)+版本总览(wikilink串联用例/测试点)；支持 --no-sync 跳过。与 test-pipeline-mvp Phase 8.5 协作（谁生成谁同步，mvp 仅兜底校验） |
| v1.9 | 2026-08-04 | Step 6 同步门禁从「默认启用」调整为「**仅正式版入库、草稿版不入库**」：新增 `--formal` 标记（或生成器 frontmatter `version_status: 正式版`）触发同步；未标记/草稿版跳过并提示；Step 5.5 校验不过或 `--no-sync` 仍跳过（优先级最高）。 |
| v2.0 | 2026-08-12 | 通用质量红线新增第17条「步骤与预期中禁止出现合并验证/主用例追溯等内部引用标注」：用例的「测试过程」「接收标准」只写可执行操作与可验证结果，不得写入 `（合并验证：ECxxxxx）`、`已由主用例 ECxxxxx 在合并验证步骤中一并执行` 等元注释；Step 5.5 机器校验从四项扩展为五项，新增合并验证引用检测；原因：此类标注导入用例系统不可见/不解析，污染执行步骤。 |

---

## 历史生成文件记录

| 时间 | 功能模块 | 文件路径 | 套件数 | 用例数 |
|------|---------|----------|--------|--------|
| 2026-05-14 | 自定义前端+工作流开发向导 | `exercises/自定义前端工作流开发向导_测试用例_v2.xlsx` | 12 | 72 |
