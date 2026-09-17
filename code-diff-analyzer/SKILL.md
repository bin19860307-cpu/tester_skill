---
name: code-diff-analyzer
version: 1.0.3
display_name: Chane · 代码变更影响分析
display_name_en: Code Diff Analyzer
author: Chane
description_zh: 代码变更影响分析技能。解析 git diff、tagdiff.txt、compare_vX_to_Y.md 等变更输入，识别受影响模块、评估风险等级、规划测试范围，支持自动生成 HTML 变更报告与多服务综合 Bug 趋势分析。
description_en: Code diff impact analysis skill. Parse git diff / tagdiff.txt / compare_vX_to_Y.md, identify affected modules, assess risk, plan test scope, and auto-generate HTML change reports with combined multi-service bug-trend analysis.
description: >
  代码变更影响分析技能。当用户提供 Git diff、代码变更记录或版本对比内容，
  需要分析变更影响范围、评估风险等级、规划测试范围时，使用此 Skill。
  触发场景包括：分析 git diff 输出、评估 PR 影响范围、制定回归测试计划、
  CI/CD 流水线中的变更分析、tagdiff.txt 分析、compare_vX_to_Y.md 分析等。
  支持两种输入格式：①CI/CD原始输出（tagdiff.txt）②结构化Markdown报告（compare_vX_to_Y.md）。
  支持区分「新增代码」和「变更代码」两类变更进行分别分析，并可自动生成HTML格式的变更报告。
---

# Code Diff Analyzer — 代码变更影响分析

## 技能概述

分析代码仓库的变更记录（diff/PR/commit log），识别受影响的功能模块，评估风险等级，输出结构化的影响分析报告和测试建议。支持自动生成 HTML 格式的变更报告文件。

## 技能更新记录（变更日志）

> 设计演进可追溯。每次对 Skill 的逻辑 / 脚本 / 文档做实质改动，在此追加一条（最新在上），便于复盘「更新过程」。

- **2026-09-17 · 投稿包合规修正 + 版本升至 1.0.3**
  - 平台投稿 zip 按文件类型白名单校验：剔除各 skill 自带 `.gitignore`；无扩展名文件补 `.txt`（`LICENSE`→`LICENSE.txt`、`scripts/Dockerfile`→`Dockerfile.txt`）。
  - 统一用 `build_upload_zip.py` 重打包；版本 1.0.2 → 1.0.3（规避平台「重投版本须 > 已记录」红线）。
- **2026-09-16 · 综合报告新增「各版本 Bug 数据明细」+ 状态口径修正 + 版本柱状图条件注入**
  - `gen_combined_report.py`：新增 ⑤ 各版本 Bug 数据明细 节，**仅当综合报告含 ≥2 服务时展示**（单服务 Bug 数据见其独立报告，呼应「除非只有一个服务」）；按服务展示「产生版本 / 解决版本」分布 + 严重度分布（数据来自各服务 `version_bugs.json` 的 `found_in_version` / `fixed_in_version`）。原 ⑤ 综合发布建议顺延为 ⑥。⑤ 节内预留 `<!-- BUG_TREND_COMBINED -->` 占位符，供综合柱状图注入。
  - 综合总览「总关联 Bug」口径改为 **已关闭 X / 已解决 Y**（不再把 `已解决` 计入 `已关闭`）。
  - `bug_correlate.py`：修正状态映射——`STATUS_CLOSED` 仅含 `已关闭/关闭`，`已解决` 单列 `resolved`（此前 `已解决` 被误并入 `closed`，导致综合报告「已关闭 23」虚高；实际为 已关闭 6 / 已解决 17）；另补充 `轻微 → low` 严重度映射（此前 `轻微` 落入默认 medium，与 `一般` 同级，语义错误）。
  - `bug_trend.py`：**新增综合模式 `--combined --services A B C --report <综合.html>`**——`build_stats_combined()` 跨服务聚合各 `version_bugs.json` 的「版本堆叠柱状图 + 修复率 + 明细」，经 `<!-- BUG_TREND_COMBINED -->` 占位符幂等注入综合报告。由此实现**条件注入**：综合报告注入「综合跨服务」聚合图，单服务报告注入该服务独立图（用户原话「综合就综合注入，单服务就单服务注入」）。修复率口径统一为「已关闭 + 已解决」占比，卡片显示 `已关闭 / 已解决` 双数。
  - 已端到端验证：综合柱状图成功注入 ⑤ 节（2 个 SVG，幂等可重跑）、单服务 `bug_trend` 刷新数据后一致；综合报告 0 绝对链接、3 相对链接、单 `</html>`。
- **2026-09-10 · Bug 版本系列隔离 + 知识库定位校正**
  - `bug_correlate.py`：`--version` + 版本系列隔离（schema 1.0→1.1）。仅保留目标系列 Bug，其余归档 `_archive/version_bugs_{系列}.json`；顺带回填 `service_metrics.json` 的 `bug_links`（修复摘要卡「关联 Bug」恒为 0）。
  - `SKILL.md`：修正知识库用例集路径为 `初发项目/v{版本}/03-测试用例/`；补充 P1 块落位、lock 文件排除、跨服务关联脆弱性等实测坑。
  - 设计原则新增：**Bug 数据按版本走**，分析 5.3 不应混入 5.2 历史（用户反馈：版本噪音会虚高趋势）。
- **2026-09-10 · 综合报告跳转链接可移植化（相对路径）**
  - `gen_combined_report.py`：独立报告链接默认改为【相对路径】（如 `../portal-backend/xxx.html`）。综合报告在 `_综合/`、服务报告在 `{service}/`，二者同级，整目录拷贝到任意机器后直接双击即可点击跳转，解决「发给同事打不开」的问题。
  - 新增 `--absolute` 开关回退旧的绝对 `file:///d:/...` 路径（仅本地预览用，不可分享）。
  - 已验证：生成报告输出 0 条绝对链接、3 条相对链接且全部可解析；既有 `_综合` 报告与 `code-diff-portable.zip` 已就地改写为相对链接。
- **2026-08-21 · Bug 预测合并呈现**
  - `gen_bug_predict.py`：缺陷倾向预判（H1/H2/H3）与 P1 用例合并进回归用例集，形成「要测什么 / 可能出什么 Bug」互补双维度。
- **2026-08-18 · 量化风险评分 + JIT 缺陷预测整合**
  - `gen_quant_jit.py` / `quant_jit_risk.py`：风险从「高/中/低」升级为「分数(0-100)+JIT 预测」，默认每次都跑，小 diff 但语义关键时更能暴露风险。
- **2026-08-13 · 综合报告跳转链接修复**
  - `gen_combined_report.py`：独立报告链接去掉 `target` 属性（WorkBuddy 预览器拦截 file:// 所致）。
- **2026-04-28 · 格式 A v2**
  - Jenkins `tagdiff.sh v2` 新增变更概览 / 下一层模块分布 / 文件级差异统计分区，解析锚点不变。

## 触发条件

以下任意场景触发本技能：
- 用户提供 `git diff` 或 `git log --oneline` 输出内容
- 用户要求分析版本间的代码改动（如 v1.2.24 → v1.2.25）
- 用户需要评估 PR/MR 的影响范围
- CI/CD 流水线产出的 `tagdiff.txt` 需要分析（**格式 A**）
- 用户提供 `compare_vX_to_Y.md` 格式的结构化代码对比报告（**格式 B**）
- 用户询问"这次改动影响了什么"、"需要测试哪些功能"
- 用户要求生成变更报告（Markdown / HTML）
- 用户要求导入 Bug 数据（`导入Bug数据` / `@bug_list.xlsx 导入Bug数据`）
- 用户要求分析历史数据（`分析 diff-analytics` / `服务风险趋势`）

## 分析工作流

### Step 1 — 接收并识别变更内容

#### 1.1 格式识别（优先执行）

输入的 diff 内容可能有以下两种格式，**先判断格式，再解析内容**：

##### 格式 A：CI/CD 原始输出（tagdiff.txt）

**特征**：
- 头部为 `echo` 输出的纯文本行，如 `构建编号: 19`、`版本比对: v1.2.24 -> v1.2.25`
- 头部第 4 行为 `仓库地址: https://gitlab.example.com/xx/xx/xxxx.git`（含服务名称），**新增字段**（2026-04-28）
- Commit 记录部分紧跟 `======== Commit 记录 =========` 分隔符，格式为 `git log --oneline` 纯文本
- 代码 diff 部分紧跟 `======== 代码差异 ============` 分隔符，内容为原始 `git diff` 输出
- diff 头以 `diff --git a/xxx b/xxx` 开头，文件间无独立标题
- 代码变更行不含代码块包裹
- **格式 A v2（2026-09-10 起，Jenkins `tagdiff.sh v2` 产出）**：
  - 头部在 `仓库地址` 之后**新增** `路径过滤:` / `排除路径:` / `模块统计深度:` 三行（无过滤时显示 `<未启用，全仓库>`）
  - Commit 记录**之前**新增两个分区：`======== 变更概览 ========`（Commit 数 / 变更文件数 / A-M-D-R-C 分布 / +/- 行数）、`======== 下一层模块分布 ========`（按目录聚合的文件数-行数表）
  - 代码差异**之前**新增两个分区：`======== 变更文件列表 ========`（name-status）、`======== 文件级差异统计 ========`（--stat）
  - **解析锚点不变**：仍用 `======== Commit 记录 =========` 与 `======== 代码差异 ============` 切分；上述新增分区可直接跳过
  - 可加利用：`变更概览` 的 A/M/D/R/C 分布与 `下一层模块分布` 是风险评级的优质先验（模块集中度 = 高变更密度模块）
  - 文件名带过滤后缀时（`*_path-apps_manage.txt`）表示该报告**只覆盖指定模块**，分析时不要当成全量变更

**示例结构**：
```
构建编号: 19
构建时间: 2026-04-13 10:09:21 CST
版本比对: v1.2.24 -> v1.2.25
仓库地址: https://gitlab.example.com/acme/acme-frontend.git
======== Commit 记录 =========
f1a2ce5 fix: 页面白屏路由问题
======== 代码差异 ============
diff --git a/packages/base/src/constants/menus.ts b/packages/base/src/constants/menus.ts
@@ -41,9 +41,9 @@
-'manage/operation-management': ...
+'/manage/operation-management': ...
```

##### 格式 B：结构化 Markdown 报告（compare_vX_to_Y.md）

**特征**：
- 头部为 Markdown 表格，包含「仓库名称」「对比类型」「源版本」「目标版本」「生成时间」「对比范围」
- Commit 变更清单为 Markdown 表格，含 Commit ID、提交信息、作者、时间四列
- 每个文件有独立的三级标题 `### 📄 filename`，并包含「变更类型」「变更统计」「文件状态」说明行
- 代码 diff 内容用 ` ```diff ``` ` 代码块包裹，含 `@@ -x,y +x,y @@` 行

**示例结构**：
```
## 1. 对比概览
| 属性 | 值 |
| 仓库名称 | acme/acme-frontend-v |
| 源版本   | v5.0.0.13 |

## 2. Commit 变更清单
| Commit ID | 提交信息 | 作者 | 时间 |
| 14bcb688  | chore: update amis | hejiaming | ... |

## 3. 文件级 Diff 详情
### 📄 package.json
- 变更类型: 修改
- 变更统计: -1 行 / +1 行
```diff
-    "@trufar-sdk/preview": "2.3.24",
+    "@trufar-sdk/preview": "2.3.25",
```
```

#### 1.2 信息提取（按格式分支处理）

| 字段 | 格式 A 提取方式 | 格式 B 提取方式 |
|------|----------------|----------------|
| 服务名称 | 解析 `仓库地址:` 行，提取 URL 末项（去 `.git` 后缀）| 解析「对比概览」表格的「仓库名称」行 |
| 版本信息 | 解析 `版本比对: X -> Y` 纯文本行 | 解析「对比概览」表格的「源版本」「目标版本」行 |
| 构建信息 | 解析 `构建编号`、`构建时间` 纯文本行 | 解析「生成时间」「对比范围」表格字段 |
| Commit 列表 | 解析 `Commit 记录` 段落，`hash message` 格式 | 解析「Commit 变更清单」Markdown 表格，可获取作者和时间 |
| 文件列表 | 解析 `diff --git a/xxx b/xxx` 行提取文件路径 | 解析各 `### 📄 filename` 标题及其变更统计行 |
| 代码 diff | 直接解析原始 diff 行（`+`/`-`/`@@`） | 解析 ` ```diff ``` ` 代码块内容 |
| 作者信息 | ❌ 无（格式 A 不含作者）| ✅ 可从 Commit 表格提取 |

#### 1.3 ⚠️ 版本方向核查（必须执行，不可跳过）

**背景**：`compare_A_to_B.md` 文件名中的 A/B 顺序**不一定**代表实际变更方向。文件名命名方式因工具而异，可能是「新版本_to_旧版本」或「旧版本_to_新版本」，必须通过 Commit 时间线独立核实。

**核查步骤（三步验证法）**：

**Step 1 — 语义版本号比较**：
- 对比文件名中两个版本号的大小（如 `5.1.0.4` vs `5.1.0.3`）
- 版本号较大 = 较新版本；版本号较小 = 较旧版本
- 确定"新版本"和"旧版本"

**Step 2 — Commit 时间线验证**：
- 读取文件中所有 Commit 的提交时间
- 按时间升序排列，最早的 Commit 属于"旧版本"，最晚的属于"新版本"
- 若时间跨度明显（如跨越多天），以时间为主要依据

**Step 3 — diff 内容与版本方向对齐**：
- git diff 语义：`-` 行 = 旧版本（源）中存在但新版本（目标）中移除的内容
- `+` 行 = 新版本（目标）中新增的内容
- 若文件名标注的「源版本」实际是新版本（版本号更大），则说明文件名方向标注是**反置**的
- 在报告中必须使用**验证后的真实方向**，而非文件名字面方向

**输出规范（在报告版本信息区必须包含）**：
```
文件名标注方向：compare_{A}_to_{B}.md （A=源，B=目标）
版本号大小关系：{A} vs {B} → {X} 较新 / {Y} 较旧
Commit 时间线：{最早日期} ~ {最晚日期}
实际变更方向：{旧版本} → {新版本}（正向迭代 / 版本回退）
方向标注状态：✅ 与文件名一致 / ⚠️ 与文件名相反（已在报告中更正）
```

**常见情形说明**：

| 文件名 | 文件名含义 | 版本号大小 | 实际方向 | 标注状态 |
|--------|-----------|-----------|---------|---------|
| compare_5.1.0.3_to_5.1.0.2.md | 源=5.1.0.3, 目=5.1.0.2 | 5.1.0.3 > 5.1.0.2 | 5.1.0.2→5.1.0.3（正向） | ⚠️ 文件名反置 |
| compare_5.0.0.10_to_5.1.0.0.md | 源=5.0.0.10, 目=5.1.0.0 | 5.1.0.0 > 5.0.0.10 | 5.0.0.10→5.1.0.0（正向） | ✅ 与文件名一致 |
| compare_v1.2.25_to_v1.2.24.md | 源=v1.2.25, 目=v1.2.24 | 1.2.25 > 1.2.24 | 1.2.24→1.2.25（正向） | ⚠️ 文件名反置 |

**服务名称提取规则（格式 A）**：
- 从 `仓库地址: https://gitlab.example.com/xx/xx/xxxx.git` 提取
- 取 URL 最后一段路径（`xxxx`），去除 `.git` 后缀
- 示例：`https://gitlab.example.com/acme/acme-frontend.git` → `acme-frontend`
- 若 URL 含多层路径，取最后一层作为服务名（如 `xx/yy/zz.git` → `zz`）

### Step 2 — 变更类型分类

对每个文件/模块的变更进行分类：

| 类型 | 标志 | 说明 |
|------|------|------|
| 新增文件 | `new file mode` / `+++ /dev/null` | 全新添加的文件 |
| 修改文件 | `@@` 差异标记 | 已存在文件的内容变更 |
| 删除文件 | `deleted file mode` / `--- /dev/null` | 文件被移除 |
| 回滚 | Commit 含 `Revert` | 撤销了之前的变更 |

### Step 3 — 变更代码 vs 新增代码分类（重要）

在 Step 2 的基础上，进一步将 diff 中的代码行变化分为两类：

#### 3.1 变更代码（Modified Code）

**定义**：对已有逻辑/行为的修改，可能改变现有功能的行为。

**识别标志**：
- 既有 `-`（删除行）又有 `+`（新增行）的 `@@` 块
- 修改已有变量名、函数参数、条件逻辑
- 修改已有数据结构（字段增减、格式变化）
- 修改配置值、阈值、常量

**分析重点**：
- 变更前后行为差异是什么
- 哪些现有功能的行为会受影响
- 是否存在向后兼容性风险
- 下游依赖方是否需要同步适配

**风险特征**：通常风险较高，可能破坏现有功能

#### 3.2 新增代码（Added Code）

**定义**：纯粹新增的逻辑/功能，不改变已有行为。

**识别标志**：
- 只有 `+`（新增行）没有 `-`（删除行）的 `@@` 块
- 新增函数、新增配置项、新增文件
- 新增 `if/else` 分支（在已有逻辑中新增判断分支）
- 新增日志输出、注释

**分析重点**：
- 新增功能的业务场景覆盖
- 新增代码与已有逻辑的集成点
- 新增代码的边界条件
- 新增配置项的默认值和影响范围

**风险特征**：通常风险较低，但需要覆盖新增功能的测试

#### 3.3 分类增强规则（解决误判问题）

**问题**：仅看 `@@` 块内是否有 `+`/`-` 行容易误判。

**增强判断逻辑**：

| 场景 | 判断规则 | 示例 |
|------|----------|------|
| 修改函数调用 | 同一行既有`-`又有`+`，且功能相似 | `- oldFunc(a)` → `+ newFunc(a)` |
| 修改数据格式 | 删除旧格式，新增新格式 | `- format("%s\|%s", a, b)` → `+ format("%s\|%s\|%s", a, b, c)` |
| 纯新增函数 | 独立的函数定义块 | `+ function newFeature()` |
| 新增配置项 | 在列表/数组中追加 | 仅在末尾追加新项 |
| 混合块 | 部分修改+部分新增 | 需拆分分析 |

**语义判断优先级**：
1. 看变更是否在**同一语义单元**（同函数/同变量/同数据结构）
2. 看变更是否**改变了调用方式**或**返回值格式**
3. 纯新增 → 新增代码；语义修改 → 变更代码

#### 3.4 分类判断示例（增强版）

```
示例1：变更代码（修改数据格式）
- local recordvalue = string.format("%s|%s|%s", a, b, c)
+ local recordvalue = string.format("%s|%s|%s|%s", a, b, d, c)
→ 既有删除又有新增，修改了已有的数据格式 → 变更代码

示例2：变更代码（修改调用）
- await authService.verify(token)
+ await authService.validate(token, options)
→ 函数签名变化，旧调用方式失效 → 变更代码

示例3：新增代码（纯追加）
+ "req_fromnum",  // 在已有列表末尾追加
→ 不改变已有项 → 新增代码

示例4：新增代码（纯新增函数）
+ function newFeature()
+     -- new logic here
+ end
→ 独立新增，不影响已有逻辑 → 新增代码

示例5：变更代码（版本号但语义改变）
- VERSION = "1.0.8"
+ VERSION = "1.0.9"
→ 若这只是版本号递增 → 新增代码
→ 若版本号递增伴随行为变化 → 变更代码（需结合上下文）

示例6：难以判断时的处理
- 当无法确定是"变更"还是"新增"时
- 标记为「混合类型」，在报告中拆分说明
- 风险等级取较高者
```

### Step 4 — 模块依赖分析

根据变更文件的路径和职责，识别模块角色：
- **常量/配置文件**（`constants/`、`config/`）→ 所有引用处都受影响
- **路由文件**（`routes/`、`router/`）→ 页面跳转、微应用集成受影响
- **工具函数**（`utils/`、`helpers/`）→ 调用该函数的所有模块受影响
- **组件文件**（`views/`、`components/`）→ 使用该组件的页面受影响
- **服务/API 文件**（`services/`、`api/`）→ 所有调用该服务的业务模块受影响
- **类型声明**（`types/`、`*.d.ts`）→ 类型变更影响静态检查和运行时行为

### Step 5 — 风险等级评估

| 风险等级 | 判定标准 |
|----------|----------|
| 🔴 高 | 涉及认证/权限/支付/核心路由/共享基础模块/数据格式变更 |
| 🟡 中 | 涉及路由配置/公共工具函数/多处引用的常量/新增复杂功能 |
| 🟢 低 | 仅影响单一页面/纯视觉样式/文案修改/版本号更新 |

#### 5.1 风险评估增强规则

**问题**：仅依赖路径关键词容易误判。

**增强判断逻辑**：

```javascript
// 伪代码规则，实际在 prompt 中体现
if (changesAuthCoreLogic(diff)) risk = "🔴 高";      // 认证核心逻辑
else if (changesPaymentFlow(diff)) risk = "🔴 高";    // 支付流程
else if (changesCoreRoute(diff)) risk = "🔴 高";      // 核心路由
else if (isDataFormatChange(diff)) risk = "🔴 高";    // 数据格式变更
else if (changesRouteConfig(diff)) risk = "🟡 中";    // 路由配置
else if (isPublicUtils(diff)) risk = "🟡 中";         // 公共工具
else if (isComplexNewFeature(diff)) risk = "🟡 中";   // 复杂新功能
else if (isStyleOnly(diff)) risk = "🟢 低";            // 仅样式
else if (isDocOnly(diff)) risk = "🟢 低";             // 仅文档
else risk = "🟢 低";                                  // 默认低风险
```

**上下文增强**：
- 不仅看路径，还要看变更内容本身
- 如 `auth/helper.ts` 新增了一个工具函数 → 低风险
- 如 `auth/service.ts` 修改了验证逻辑 → 高风险

### Step 5b — 专项校验规则（新增）

在进行标准分析的同时，**必须**执行以下专项校验：

#### 5b.1 数据格式变更检测

**触发条件**：diff 中出现 JSON/Schema/接口/协议相关内容

**检测项**：
- JSON 结构变更（字段增减、类型变化）
- API 响应格式变化
- 数据库 schema 变更
- 配置项格式变化

**输出要求**：
- 提供字段级对比表
- 评估向后兼容性
- 标注需要同步更新的下游服务

**示例输出**：
```
| 字段名 | 变更前 | 变更后 | 兼容性 |
|--------|--------|--------|--------|
| userId | string | number | ⚠️ 不兼容 |
| status | - | 新增 | ✅ 兼容 |
```

#### 5b.2 版本回退检测

**触发条件**：版本号从高版本变为低版本

**检测逻辑**：
```javascript
// 比较版本号
if (compareVersions(targetVersion, sourceVersion) < 0) {
  // 版本回退
}
```

**输出要求**：
- 🚨 **警告**：检测到版本回退
- 说明回退原因（基于 commit message 判断）
- 标注回退影响的功能

#### 5b.3 敏感信息泄露检测

**触发条件**：diff 中出现以下关键词

**敏感关键词列表**：
| 类型 | 关键词模式 |
|------|------------|
| 密码/密钥 | `password`、`passwd`、`pwd`、`secret`、`api_key`、`apikey`、`token`、`access_key` |
| 私钥 | `private_key`、`privatekey`、`-----BEGIN` |
| 数据库 | `connection string`、`jdbc:`、`mongodb://` |
| 身份证/手机 | 正则匹配 `^\d{17}[\dXx]$`（身份证）、`^\d{11}$`（手机号） |
| 银行卡 | 正则匹配 `^\d{16,19}$` |

**检测规则**：
```javascript
// 伪代码
const sensitivePatterns = [
  /password\s*=\s*["'][^"']+["']/i,
  /secret\s*=\s*["'][^"']+["']/i,
  /api[_-]?key\s*=\s*["'][^"']+["']/i,
  /-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----/,
  // ... 更多模式
];

if (containsSensitiveInfo(diff, sensitivePatterns)) {
  // 触发告警
}
```

**输出要求**：
- 🚨 **安全警告**：检测到可能的敏感信息泄露
- 标注具体行号和内容（脱敏后）
- 建议使用环境变量或密钥管理服务

#### 5b.4 测试文件同步检测

**触发条件**：业务代码变更但无对应测试文件变更

**检测逻辑**：
```javascript
// 检查是否有对应的测试文件变更
const businessFile = "src/utils/helper.ts";
const testFile = "src/utils/__tests__/helper.test.ts";

if (isBusinessCodeChange(businessFile) && !hasTestChange(testFile)) {
  // 缺少测试同步
}
```

**输出要求**：
- ⚠️ **建议**：业务代码变更但未同步更新测试
- 建议补充测试用例

#### 5b.5 循环依赖检测（适用于模块化项目）

**触发条件**：同一 commit 内同时修改了两个互相引用的模块

**检测逻辑**：
```javascript
// 检查是否存在循环引用变更
const changes = getChangedFiles(diff);
const circularDeps = detectCircularDeps(changes);

if (circularDeps.length > 0) {
  // 检测到循环依赖
}
```

**输出要求**：
- ⚠️ **架构警告**：检测到可能的循环依赖
- 标注涉及的模块
- 建议重构方向

### Step 6 — 数据沉淀（自动执行，不可跳过）

每次完成 Step 1-5 分析后，**必须**将本次分析的结构化指标写入本地数据文件，用于后续历史对比和趋势分析。

#### 6.1 数据存储位置

```
{workspace}/.workbuddy/diff-analytics/{service}/
├── service_metrics.json    ← 每次分析追加一条记录
├── version_chain.json      ← 每次分析追加版本关系
└── file_history.json       ← 每次分析更新文件变更记录
```

- `{service}` 为 Step 1.1 提取的服务名称（如 `portal-backend`、`agent`）
- 若目录或文件不存在，**自动创建**（含空 JSON 骨架）
- 完整 Schema 定义见 `references/analytics-schema.md`

#### 6.2 写入步骤

**Step 6.2.1 — 追加 service_metrics.json**

提取本次分析结果，追加到 `records` 数组末尾：

```json
{
  "version_from": "5.1.0.3",
  "version_to": "5.1.0.4",
  "direction": "forward",
  "analysis_date": "2026-05-21",
  "metrics": {
    "files_changed": 15,
    "lines_added": 230,
    "lines_removed": 45,
    "high_risk": 3,
    "medium_risk": 5,
    "low_risk": 7,
    "risk_score": 72
  },
  "modules": [
    { "name": "auth", "files": 3, "risk": "high" },
    { "name": "user", "files": 2, "risk": "medium" }
  ],
  "detections": {
    "data_format_change": true,
    "version_rollback": false,
    "sensitive_info": false,
    "test_sync_needed": true,
    "circular_dependency": false
  }
}
```

**字段说明**：
- `direction`：来自 Step 1.3 版本方向核查结果，取值 `forward` / `rollback` / `unknown`
- `metrics.risk_score`：综合风险评分（0-100），计算公式：`high_risk * 10 + medium_risk * 5 + low_risk * 1`，上限 100
- `modules`：Step 4 识别的模块及其风险等级
- `detections`：Step 5b 五项专项检测的命中结果

**Step 6.2.2 — 追加 version_chain.json**

将本次版本关系追加到 `versions` 数组：

```json
{
  "version": "5.1.0.4",
  "date": "2026-05-21",
  "parent": "5.1.0.3"
}
```

- `version`：目标版本（较新版本）
- `parent`：源版本（较旧版本）
- `date`：分析日期（ISO 8601）
- 若 `version` 已存在，跳过追加（避免重复）

**Step 6.2.3 — 更新 file_history.json**

对本次变更的每个文件，更新其变更记录：

```json
{
  "src/main/java/AuthController.java": {
    "change_count": 3,
    "appear_in": ["5.1.0.2→5.1.0.3", "5.1.0.3→5.1.0.4"],
    "risk_history": ["high", "high"],
    "change_types": ["modified", "modified"]
  }
}
```

- 若文件已存在：追加 `appear_in`、`risk_history`、`change_types` 对应元素，`change_count +1`
- 若文件不存在：新建条目，`change_count = 1`

#### 6.3 写入校验

- 写入前检查文件是否为合法 JSON（防损坏）
- 追加记录后，验证 `records`/`versions` 数组长度增加 1
- 若写入失败，**不阻塞报告输出**，在控制台提示数据沉淀失败

### Step 7 — 输出分析报告

#### 7.1 报告结构

按照以下结构输出报告（参考 `references/output-examples.md`）：

1. **版本方向核查横幅**（`{{VERSION_DIRECTION_BANNER}}`，**必须是报告第一个可见内容**）
   - 展示：`实际变更方向（旧版本 → 新版本）`、`是否与文件名一致`、`Commit 时间跨度`
   - 若方向与文件名一致：使用 `direction-ok`（绿色横幅），标注 ✅
   - 若方向与文件名相反：使用 `direction-warn`（橙色横幅），标注 ⚠️ 并说明"已按真实方向更正"
2. **版本信息表格**（含服务名称、版本比对、构建信息；格式 B 可补充展示「作者」「变更统计 -N/+N」字段）
3. **风险等级横幅**（🔴高 / 🟡中 / 🟢低）
3.5 **量化风险评分 & JIT 缺陷预测**（由 `gen_quant_jit.py` 注入，apex 能力整合）：分数环(0-100) + JIT 预测标签**合并进顶部「综合风险等级」横幅**（与🔴🟡🟢定性标签一体显示）；维度贡献表 + JIT 依据收为轻量卡，置于「变更总览」之前
4. **变更总览表**（文件 + 变更类型 + 变更统计 + 说明 + 风险等级）
   - 格式 B 可从文件标题下的「变更统计」提取 `-X行/+Y行` 数据直接填入
5. **代码差异详情**（带语法高亮的 diff 展示）
6. **分类影响分析**：
   - **变更代码影响分析**（Modified Code Analysis）
     - 每个变更点的 JSON 结构化分析
     - 变更前后对比说明
     - 向后兼容性评估
   - **新增代码影响分析**（Added Code Analysis）
     - 每个新增点的 JSON 结构化分析
     - 新增功能场景覆盖
     - 集成风险评估
7. **数据格式变更详解**（如有数据格式变化，提供字段级对比表）
8. **专项检测结果**（如有）：
   - 🚨 版本回退警告
   - 🚨 敏感信息泄露警告
   - ⚠️ 测试文件缺失提醒
   - ⚠️ 循环依赖警告
9. **分优先级测试建议表**（P1必测 / P2建议 / P3可选）
10. **资深开发者建议**（代码质量、补充优化方向）

#### 7.2 分类 JSON 格式规范

**变更代码分析格式**：
```json
{
  "分析类型": "变更代码",
  "变更文件": "文件路径",
  "变更描述": "对XX进行了XX修改",
  "变更前": "旧代码片段",
  "变更后": "新代码片段",
  "行为差异": "变更导致XX行为从A变为B",
  "向后兼容": "兼容/不兼容/需验证",
  "影响范围": {
    "直接影响": ["功能1", "功能2"],
    "潜在影响": ["功能3（不确定）"]
  },
  "风险等级": "高/中/低",
  "测试建议": "需验证XX场景下XX行为是否正确"
}
```

**新增代码分析格式**：
```json
{
  "分析类型": "新增代码",
  "变更文件": "文件路径",
  "新增内容": "新增了XX功能/字段/逻辑",
  "业务场景": "用于XX场景",
  "集成点": "与XX模块集成/被XX调用",
  "边界条件": ["条件1", "条件2"],
  "影响范围": {
    "直接影响": ["新增功能X"],
    "潜在影响": ["现有功能Y（不确定）"]
  },
  "风险等级": "高/中/低",
  "测试建议": "需覆盖XX场景的XX测试"
}
```

#### 7.3 HTML 报告生成

当用户要求生成报告文件时，按照 `references/html-report-template.html` 模板生成独立的 HTML 文件。

**HTML 报告要求**：
- 单文件、无外部依赖（CSS 内联）
- 专业视觉设计，包含页面头部、风险横幅、分区卡片
- 代码 diff 带语法高亮（`+` 绿色 / `-` 红色 / 上下文灰色）
- 表格支持响应式布局
- 中文界面
- 输出路径：`{workspace}/diff_report_{项目名}_v{新版本}.html`

**生成流程**：
1. 完成 Step 1-5 的分析
2. 按照报告结构组织内容
3. 使用 HTML 模板的样式和布局
4. 写入 HTML 文件
5. 使用 `preview_url` 在浏览器中预览
6. 告知用户文件路径，可直接分享给团队
7. **【Bug 增强层条件注入】**若 `diff-analytics/{service}/version_bugs.json` 存在且非空（即做过 Bug 导入），在生成比对报告后**必须**追加趋势注入。**注入模式按报告类型区分**：
   - **单服务报告**（条件：`--service`）：
     ```bash
     python scripts/bug_trend.py --service {service} --report {本报告.html}
     ```
     注入位置：模板 `<!-- BUG_TREND_SECTION -->` 占位符（自动替换）；已注入过则整块替换（**幂等，可重复执行**）；老报告无占位符时回退到 `</body>` 前
   - **综合报告**（条件：`--combined --services A B C`）：先由 `gen_combined_report.py` 在 ⑤ 节写入 `<!-- BUG_TREND_COMBINED -->` 占位符，再聚合各服务 `version_bugs.json` 注入「综合跨服务」堆叠柱状图：
     ```bash
     python scripts/bug_trend.py --combined --services {A} {B} {C} --report {综合报告.html}
     ```
     占位符 `<!-- BUG_TREND_COMBINED -->` 自动替换；已注入过则整块替换（**幂等**）；未关联 Bug 列表的服务贡献为 0。
   - 样式使用 `bt-` 作用域前缀，不会与被注入报告冲突；效果：每次分析后趋势随报告一并沉淀、一并预览。
   - 若只想出独立趋势报告（不注入），用 `python scripts/bug_trend.py --service {service} --out <path>`

8. **【P1 用例预测自动追加（必须）】**单服务报告生成后，基于 ①变更总览 / ②~④代码影响 / ⑤隐藏问题 推导 P1 用例，**必须**以「具体卡片版」注入报告的「🎯 P1 用例预测（基于影响范围）」章节（模板已预留 `<!-- P1_CASES_SECTION -->` 占位符）：
   - 用例须**具体可执行**：每条含 编号 / 模块 / 测试场景 / 对应代码点 / 具体测试数据(前置) / 步骤 / 预期；**禁止只写抽象场景名**（用户明确反馈「看不出具体用例」不可接受）
   - 运行注入脚本（幂等，可重复执行，自动替换旧块）：
     ```bash
     python scripts/gen_p1_cases.py --report {本报告.html} --data-file p1_cases.json
     ```
   - **知识库命中核对（必须，逐条）**：所有服务均基于「教学管理域」；**用例集按【版本】划分**（如 `v5.2` / `v5.3` …），**每轮提测按当前分析的「目标版本」动态确定要核对的用例集版本**，并非固定 v5.2。确定版本后，按【修改内容】去该版本下对应模块定位用例集并**逐条核对每条 P1 用例**：
     - 定位路径（2026-09-10 实测校正）：`D:/Obsidian知识库/knowledge/初发项目/v{目标版本}/03-测试用例/{对应模块}/{模块}_v{目标版本}_测试用例.md`
       - ⚠️ 旧文档写的 `knowledge/测试用例/v{版本}/{模块}/用例/全量测试用例.md` **已不存在**，实际在 `初发项目/` 下按版本划分，且子目录为 `03-测试用例`（与 01-需求 / 02-设计文档 / 04-用例评审 并列）
       - 教学管理域模块与编号段：工作台 101xx / 我的班级 103xx / 学生列表 104xx / 课程管理 105xx / 班级管理 106xx / 学习档案 / 未入班
       - 取编号：`grep -oE "^## [0-9]+ [^（(]*" "{模块}_v{版本}_测试用例.md"`
     - 版本=本轮提测目标版本（动态确定，不写死历史版本）；模块由修改内容决定（如本轮「工作台/我的班级/学生列表」对应 `v5.3` 用例集）
     - 命中既有用例 → 该用例填 `kb_ref`（关联的编号），卡片显示绿色「✅ 已命中·关联 XXX」，可直接复用
     - 未命中（新增场景） → 该用例设 `estimated:true`，卡片显示红色「预估」，并注明（用户要求：未命中时注明，并提供部分预估测试用例）
     - 章节顶部统一显示绿色「📚 知识库用例集核对」框（已定位到 v{目标版本} 用例集 + AI 逐条核对结论 + 命中/预估计数），**不再使用「域差异全未命中红框」**（旧逻辑已废弃：所有服务本就同属教学管理域，按提测版本定位即可，不存在整集域不匹配）
   - **⚠️ 综合报告 P1 块会落到末尾（2026-09-10 实测）**：`gen_combined_report.py` 产出的综合报告**没有「开发者建议」章节**，`gen_p1_cases.py` 找不到锚点时会把 P1 卡片追加到 `</body>` 前（在「⑤ 综合发布建议」之后）。
     生成后需手工补：`<h2>⑥ P1 用例预测（基于影响范围 · 跨服务）</h2>` 章节标题，并在 `<!-- P1_CASES_END -->` 后补 `</div>` 闭合。
   - data JSON 结构见 `scripts/gen_p1_cases.py` 头部注释
   - **规模统计注意（2026-09-10）**：前端仓库 diff 常含 `pnpm-lock.yaml` / `package-lock.json`，其行数会严重污染"变更行数"指标（本次 main-frontend lock 占 +264/-39）。
     统计 `total_lines` 与「变更规模」时应**排除 lock 文件**，并在报告脚注注明已排除。

8.5. **【Bug 预测（缺陷倾向预判）与 P1 合并呈现（必须，互补双维度）】**在生成 P1 用例后，**必须**运行 `gen_bug_predict.py`，将「向前看」的缺陷倾向预判（H1/H2/H3）注入到 **P1 章节之前**，形成「预判缺陷 → 可执行 P1 用例」同一回归用例集的双视角呈现（用户 2026-08-18 明确：Bug 预测与「测试范围/P1」互补，应合并进回归用例集）。
   - **与 P1 的关系**：P1 用例 = 「测试范围/可执行」（具体卡片）；Bug 预测 = 「缺陷倾向/风险点」（向前看）。二者维度互补，合并后回归测试者在同一章节即可看到「要测什么」与「可能出什么 Bug」。
   - **展示形态**：🐞 Bug 预测块含 ①预测总览表（优先级/缺陷类型/触发条件/影响模块/置信度）+ ②逐条详情卡（根因+触发+影响+验证建议）+ ③「P1 ↔ Bug 预测」映射表（逐条 P1 关联对应 H 项）+ ④待确认项；置于 P1 用例章节之前（模板 `<!-- BUG_PREDICT_SECTION -->` 占位符；旧报告无占位符时自动插到 P1 章节之前）。
   - **运行**（幂等，可重复执行，自动替换旧块）：
     ```bash
     python scripts/gen_bug_predict.py --report {本报告.html} --data-file bug_predict.json
     ```
   - **data JSON 结构**（见 `scripts/gen_bug_predict.py` 头部注释 + 各服务 `report/code-diff/{service}/` 下 `bug_predict*.json` 样例）：`meta`（service/range/note）+ `items[]`（id/priority/defect_type/root/trigger/affected/confidence/verify）+ `p1_map[]`（p1/scene/bug）+ `confirm[]`。
   - **来源**：本维度首次在 2026-08-18 作为独立《Bug 预测分析》报告产出（文件名含 `_Bug预测分析.html`）；合并后独立报告仍保留作为专项存档，标准变更影响报告通过本脚本内嵌同维度内容。若已有独立 Bug 预测报告，可直接将其 `items`/`p1_map`/`confirm` 提炼为 JSON 供本脚本注入（pdf/html 提取皆可）。

9. **【量化风险评分 & JIT 缺陷预测自动追加（apex 能力整合）· 默认每次都跑】**单服务报告生成后，**必须**运行 `gen_quant_jit.py` 把量化评分 + JIT 预测并入报告。该步骤已**固化默认执行**，无需用户单独要求。
   - **展示形态（已与用户确认）**：分数环(0-100) + JIT 预测标签**合并进顶部「综合风险等级」横幅**（与🔴🟡🟢定性标签一体）；详细维度贡献表 + JIT 依据收为轻量卡，置于「变更总览」之前（模板 `<!-- QUANT_JIT_SECTION -->` 占位符）。**不**作为独立大章节放在报告末尾。
   - **默认零配置（推荐）**：脚本可直接从已生成的报告 HTML 自动派生 stats（解析风险横幅等级 / 变更总览行数 / 代码块 +/- 行数 / 核心模式命中），无需手搓 JSON：
     ```bash
     python scripts/gen_quant_jit.py --report {本报告.html} --auto
     ```
   - **精确控制（可选）**：提供 stats JSON 时以 JSON 为准（仍可叠加 `--service` 自动补历史度量进入增强 10 维）：
     ```bash
     python scripts/gen_quant_jit.py --report {本报告.html} --stats quant_stats.json
     python scripts/gen_quant_jit.py --report {本报告.html} --stats quant_stats.json --service {service} --workspace <工作区>
     ```
   - **stats JSON 结构**（`scripts/quant_jit_risk.py` 头部注释含完整说明）：
     - `base_risk`：high/medium/low（取 Step 5 定性结论）
     - `total_lines` / `file_count` / `core_file_count`（或 `core_ratio`）/ `avg_density`（变更统计）
     - `description` + `files`：用于 JIT 核心模式匹配（权益/降级/禁用/版本/订单/认证/支付/路由/配置）
     - `data_format_change`：可选，触发 JIT 数据格式红标
     - `historical_metrics`：可选（buggy_ratio/churn_rate/mod_count/author_exp/days_since）；提供则进入**增强 10 维**模式（历史度量权重 25%），不提供则**静态 5 维**
   - **输出**：横幅内分数环(0-100) + JIT 预测标签（🔴高风险预测/🟡中等/🟢低）+ 变更总览前轻量卡（维度得分/权重/贡献表 + JIT 预测依据 + 审查建议 + 效果参考：Top-20% 覆盖 75%-88% 缺陷，AUC 0.72-0.83，规则引擎非 ML）
   - **价值**：把风险从「高/中/低」升级为「68 分/中风险」并可预测缺陷倾向；小 diff 但语义关键时（如本次学校版本降级），量化分可能低于定性结论，二者并列展示更能暴露「小而关键」的变更
   - **综合报告同样默认执行**：综合报告生成后，再运行一次按服务注入汇总表（脚本取各服务最新独立报告自动派生 stats）：
     ```bash
     python scripts/gen_combined_report.py --services 服务A 服务B --workspace <工作区>
     python scripts/gen_quant_jit.py --report {综合报告.html} --combined --services 服务A 服务B --workspace <工作区>
     python scripts/gen_bug_predict.py --report {综合报告.html} --combined --services 服务A 服务B --workspace <工作区>
     ```
     - 量化/JIT 注入位置：综合报告「② 各服务摘要卡」内的 `<!-- QUANT_JIT_COMBINED -->` 占位符（各服务一行：定性风险 / 量化评分 / JIT 预测）。
     - **Bug 预测聚合（必须，与上面两步同批）**：`gen_bug_predict.py --combined` 取各服务 `report/code-diff/{service}/bug_predict*.json`（取最新），在 `<!-- BUG_PREDICT_COMBINED -->`（紧接量化块之后）注入「各服务 Bug 预测汇总」表（服务 / 版本区间 / H1 / H2 / H3 / 待确认 / 高优先缺陷摘要）。无 bug_predict 数据的服务会跳过并告警，不会报错。

---

## 综合比对模式（多服务一次性分析）

### 触发条件
- 用户一次性提供 **≥2 个服务**的代码比对文件（格式 A 或 B 可混用），如「主框架 + 前端 + 后端」三份 diff 同时 @skill。
- 单份文件**不触发本模式**，仍走 Step 1-7 单服务流程（行为完全不变）。

### 流程
1. 对每个服务分别执行 Step 1-7 完整单服务分析（含格式识别、版本方向核查、风险评级、Bug 趋势注入），各自沉淀 `diff-analytics/{service}/` 与独立报告 `report/code-diff/{service}/`。
2. 全部单服务分析完成后，运行综合报告脚本汇总：
   ```bash
   python scripts/gen_combined_report.py --services 服务A 服务B 服务C --workspace <工作区>
   # 自定义输出
   python scripts/gen_combined_report.py --services portal-backend manage-frontend \
     --out "report/code-diff/_综合/综合比对分析报告_20260810.html"
   ```

### 综合报告结构（已确认：摘要卡 + 跨服务关联，不整篇拼装）
1. **综合总览**：涉及服务数、**各服务变更版本矩阵**、版本批次、综合风险、总变更文件数、总关联 Bug 数
2. **各服务摘要卡**：每个服务的风险徽章、**变更版本 from→to**、变更规模、Bug 数、专项检测、独立报告链接
3. **跨服务关联与级联风险**：业务概念词典启发式匹配（接口路径/字段/单位/版本号），列出服务间潜在关联与级联高风险点
4. **统一测试优先级**：合并各服务 high-risk 模块去重，输出 P1 必测清单
5. **各版本 Bug 数据明细**：**仅当综合报告含 ≥2 服务时展示**（单服务详见其独立报告）。按服务展示「产生版本 / 解决版本」分布 + 严重度分布，数据来自各服务 `version_bugs.json` 的 `found_in_version` / `fixed_in_version`（2026-09-16 用户建议：综合报告要能看到各版本 Bug 数据）。节内预留 `<!-- BUG_TREND_COMBINED -->` 占位符，由 `bug_trend.py --combined` 注入「综合跨服务」版本堆叠柱状图（条件注入：综合报告画聚合图，单服务报告画独立图）
   - 综合总览的「总关联 Bug」口径改为 **已关闭 X / 已解决 Y**（区分 `已解决` 与 `已关闭`，不再把 `已解决` 计入 `已关闭`，2026-09-16 修正 `bug_correlate.py` 状态映射）
4.5. **P1 用例预测（基于影响范围）**：由 `gen_p1_cases.py` 注入，内容同单服务（具体卡片版 + 知识库命中核对 + 预估标注），重点覆盖跨服务耦合高危点
6. **综合发布建议**：基于综合风险 + 级联 + 同批次给出发布策略

### 风险聚合规则
- 综合风险底线 = `max(各服务最新版本风险)`
- **级联升级**：高风险服务且与其他服务存在跨服务关联 → 综合报告标注「🔥 含级联高风险」，关联段落列出级联路径与验证建议

### 输出位置
- 默认：`report/code-diff/_综合/综合比对分析报告_{服务1}_{服务2}_..._{YYYYMMDD}.html`
- 综合模式下**仍保留各服务独立报告**，综合报告作为总入口

### ⚠️ 独立报告跳转链接（2026-09-10 可移植化）
- **默认用相对路径（推荐，可跨机器分享）**：综合报告在 `report/code-diff/_综合/`，服务报告在 `report/code-diff/{service}/`，二者同级，链接写为 `../{service}/xxx.html`。整目录拷贝到任意机器后直接双击 `_综合/xxx.html` 即可点击跳转，不依赖本机绝对路径。
- **`--absolute` 回退绝对路径（仅本地预览，不可分享）**：加 `--absolute` 时链接回退为 `<a href="file:///d:/.../xxx.html">`，路径写死本机。仍须**不带 `target` 属性**（WorkBuddy 预览器拦截 file:// 链接，带 target 点击失效，2026-08-13 实测）。
- 路径须统一为正斜杠（`report_path.replace("\\","/")`）。
- 若预览面板仍跳不过去，多为 http 渲染沙箱拦截 file:// 所致，改用 present_files 的三张卡片直接打开即可。

---

## 独立流程 A — Bug 数据导入（按需触发，非必须）

Bug 数据是**可选增强层**。没有 Bug 数据，体系照常运转；有了 Bug 数据，分析更精准。

### 触发方式

| 方式 | 触发指令 | 说明 |
|------|----------|------|
| Excel/CSV 导入 | `@bug_list.xlsx 导入Bug数据` | 从测试平台导出后直接导入 |
| 逐条录入 | `添加Bug BUG-0042 严重级别high 模块auth 发现版本5.1.0.3` | 单个 Bug 快速录入 |
| 粘贴表格 | `导入Bug列表` + 粘贴 Markdown 表格 | 从平台页面复制粘贴 |

### A.1 Bug 数据必填字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `bug_id` | ✅ | Bug 唯一标识 |
| `severity` | ✅ | 严重级别：critical / high / medium / low |
| `found_in_version` | ✅ | 发现该 Bug 的版本号 |
| `title` | ❌ | Bug 标题 |
| `module` | ❌ | 所属模块 |
| `fixed_in_version` | ❌ | 修复该 Bug 的版本号 |
| `status` | ❌ | 状态：open / fixed / closed / wontfix |
| `found_date` | ❌ | 发现日期 |
| `fixed_date` | ❌ | 修复日期 |
| `related_files` | ❌ | 关联的变更文件列表 |
| `related_commits` | ❌ | 关联的 Commit ID 列表 |
| `tags` | ❌ | 标签（如 regression、security） |

### A.2 导入处理流程

1. **解析输入**：根据触发方式（Excel/逐条/粘贴）解析 Bug 数据
2. **确定服务**：若用户指定服务名，使用指定值；否则从 `version_chain.json` 中按 `found_in_version` 匹配
3. **写入 version_bugs.json**：将解析后的 Bug 追加到对应服务的 `version_bugs.json`
4. **触发映射**：执行流程 B（映射引擎）

### A.3 Excel 列名映射

用户上传的 Excel 列名可能不同，按以下规则映射：

| 标准字段 | 常见列名变体 |
|----------|-------------|
| `bug_id` | Bug ID、缺陷ID、编号、ID |
| `title` | 标题、缺陷标题、描述、摘要 |
| `severity` | 严重级别、优先级、等级、Severity |
| `found_in_version` | 发现版本、影响版本、版本 |
| `fixed_in_version` | 修复版本、解决版本 |
| `status` | 状态、缺陷状态 |
| `module` | 模块、所属模块、功能模块 |

匹配规则：忽略大小写和空格，包含关键词即可匹配。

### A.4 固化脚本（推荐，替代手工解析）

> 历史教训：手工逐条录入/临时脚本极易把"同文件≠同 Bug"的 bug 误标为未解决（如 81013 实为 5.2.0.8 已关闭）。**现统一用脚本解析，以 xlsx 权威状态为准。**

Bug 列表格式已固化（TAPD 导出，`bug` sheet，17 列）：
`编号 | 标题 | 创建人 | 创建日期 | 解决者 | 解决日期 | 关闭日期 | 状态 | 产生版本 | 解决版本 | bug类型 | 严重程度 | 激活次数 | 处置方式 | 方案 | 详细处理方式 | 模块`

**脚本**：`scripts/bug_correlate.py`（同时完成 Flow A 解析 + Flow B 映射）

```bash
# 指定服务 + 目标版本（推荐：按版本系列隔离）
python scripts/bug_correlate.py --xlsx "5.3.0.0bug列表.xlsx" --service portal-backend --version 5.3.0.2
# 不指定服务时，自动按版本匹配 diff-analytics 中各服务的 version_chain.json 探测
python scripts/bug_correlate.py --xlsx "5.3.0.0bug列表.xlsx"
# 旧行为：保留全部版本系列不做归档（不推荐）
python scripts/bug_correlate.py --xlsx "..." --service portal-backend --keep-all
```

脚本行为（防错设计）：
- **按版本系列隔离（2026-09-10 新增，默认启用）**：Bug 数据**按版本走**——只保留属于「本次分析版本系列」的记录，其余自动归档，
  `version_bugs.json` 不再跨版本堆积历史噪音。
  - **版本系列** = 版本号前两段（`business-5.3.0.2` / `v5.3.0.3` / `5.3.0.0` 均 → `5.3`）
  - **保留条件**：`found_in_version` **或** `fixed_in_version` 属于目标系列。
    后者用于保留「历史 Bug 但在本轮版本修复」的场景（如产生版本 5.0.0.0、解决版本 5.3.0.0），这类本轮必须回归。
  - **归档位置**：`diff-analytics/{service}/_archive/version_bugs_{系列}.json`（如 `version_bugs_5.2.json`），按 `bug_id` 合并去重；
    归档文件带 `version_series` / `archived_at` / `archived_reason`，需要跨版本趋势时可再取回。
  - `--version` 显式指定目标版本（推荐）；缺省时自动探测（xlsx 中出现频次最高的系列，回退 version_chain 最新版本）。
  - `--keep-all` 可恢复旧的全量平铺行为（不推荐）。
- **全量覆写** `version_bugs.json`：每次都以 xlsx 为唯一权威来源重新生成**目标系列**的记录，不 append、不保留"记忆中的旧状态"
- **自动回填 `bug_links`（2026-09-10 新增）**：把本轮 Bug id 写入 `service_metrics.json` 中对应版本记录的 `bug_links`。
  综合报告摘要卡的「关联 Bug」读该字段，**不回填会一直显示 0**（历史遗留问题，已修复）。
- **多服务归属**：一份 Bug 列表常横跨前后端（如 5.3.0.0 列表既有后端统计口径也有前端文案）。综合报告按服务**求和**，同一份列表导入到多个服务会导致 Bug 数**翻倍**。
  建议：整份导入到**主服务**（通常是有历史数据的后端服务），其余服务在报告中做定性引用，不重复导入。
- **状态映射**：`状态` 列 `已关闭/已解决/关闭` → `closed`，其余 → `open`（绝不凭"同文件/同方法"推断未解决）
- **严重程度映射**：`严重`→critical / `高`→high / `一般`·`中`→medium / `低`·`建议`→low；同时保留 `severity_raw` 原文
- **编号清洗**：Excel 浮点 `80729.0` → `80729`
- 自动运行映射引擎，**全量重建** `cross_reference.json`（mapping 规则见流程 B）
- 列名采用"精确匹配 + 关键词兜底"双策略，兼容固化格式与常见变体表头

---

## 独立流程 B — 映射引擎（Bug 导入后自动触发）

### B.1 映射逻辑

> 本映射已由 `scripts/bug_correlate.py` 在导入时自动执行（见流程 A.4），每次**全量重建** `cross_reference.json`（而非追加），确保所有权和派生指标始终与 `version_bugs.json` 一致。

当 Bug 数据写入 `version_bugs.json` 后，自动执行以下映射：

**映射维度 1 — Bug ↔ 变更文件**：
- 按 `found_in_version` 匹配 `version_chain.json`，定位版本区间
- 按 `module`（如有）匹配 `service_metrics.json` 中对应版本的 `modules`
- 按 `related_files`（如有）匹配 `file_history.json`

**映射维度 2 — Bug ↔ Commit**：
- 按 `related_commits`（如有）直接关联
- 若无 `related_commits`，按时间区间匹配 `service_metrics.json` 中该版本的 commit 列表

**映射维度 3 — Bug ↔ 专项检测**：
- 检查 Bug 所在版本的 `detections` 是否命中
- 标记"检测命中且有 Bug"和"检测命中但无 Bug"两类

### B.2 映射输出

写入 `cross_reference.json`，按版本区间组织：

```json
{
  "version_range": "5.1.0.3→5.1.0.4",
  "bugs_found_in_version": ["BUG-2026-0042"],
  "bugs_fixed_in_version": ["BUG-2026-0039"],
  "change_to_bug_ratio": 0.13,
  "high_risk_changes_with_bugs": [
    {
      "file": "AuthController.java",
      "risk": "high",
      "bug_ids": ["BUG-2026-0042"],
      "detection_hit": "data_format_change"
    }
  ],
  "commits_with_bugs": [
    {
      "commit": "a3f2c1d",
      "message": "fix: OAuth2 callback",
      "bug_ids": ["BUG-2026-0042"]
    }
  ]
}
```

**衍生指标计算**：
- `change_to_bug_ratio`：`bugs_found_in_version.length / files_changed`
- `high_risk_hit_rate`：有 Bug 的高风险变更数 / 高风险变更总数
- `detection_precision`：检测命中且有 Bug 的数量 / 检测命中总数量

---

## 独立流程 C — 数据分析（随时触发）

### 触发方式

- `分析 diff-analytics`
- `服务风险趋势`
- `查看变更历史`

### C.1 基础层分析（始终可用）

无论是否有 Bug 数据，均可输出以下 4 个维度：

| # | 维度 | 数据来源 | 输出格式 |
|---|------|----------|----------|
| 1 | 服务风险热力图 | 各服务的 `service_metrics.json` | 表格 + 排名，按 avg(risk_score) 降序 |
| 2 | 版本链趋势 | `version_chain.json` + `service_metrics.json` | 折线图：版本递增 → risk_score 变化 |
| 3 | 高频文件追踪 | `file_history.json` | 排序列表，`change_count >= 2` 的文件优先 |
| 4 | 专项检测命中 | `service_metrics.json` 的 `detections` | 柱状图：5 项检测各版本触发率 |

### C.2 增强层分析（有 Bug 数据时自动激活）

检测 `{service}/version_bugs.json` 是否存在且非空。若存在，在基础层之上额外输出：

| # | 维度 | 数据来源 | 输出格式 |
|---|------|----------|----------|
| 5 | Bug 密度热力图 | `version_bugs.json` + `service_metrics.json` | 各模块 Bug/变更比 |
| 6 | 变更-Bug 关联率 | `cross_reference.json` | 高风险变更是否真的出 Bug |
| 7 | 修复效率追踪 | `version_bugs.json` 的 `found_date`/`fixed_date` | 发现→修复的版本间隔 |
| 8 | 缺陷预测 | `cross_reference.json` + `file_history.json` | 历史识别"易出 Bug 的变更模式" |

### C.2.1 固化脚本（版本 Bug 趋势统计，推荐）

> 维度 5–8 的"版本 Bug 趋势统计"原为纯描述，现已固化为脚本，直接产出可视化报告。

**脚本**：`scripts/bug_trend.py`（依赖：`version_bugs.json`，可选 `version_chain.json` / `service_metrics.json` 做版本排序与变更比）

```bash
# 模式 A：注入到单服务比对分析报告（推荐，每次分析自动追加）
python scripts/bug_trend.py --service portal-backend \
  --report "report/code-diff/portal-backend/portal-backend_xxx_变更影响分析报告.html"

# 模式 B：生成独立趋势报告
python scripts/bug_trend.py --service portal-backend \
  --out "report/code-diff/portal-backend/portal-backend_bug趋势统计.html"

# 模式 C：综合报告「综合跨服务」聚合注入（仅综合报告，--combined + --services）
python scripts/bug_trend.py --combined --services portal-backend main-frontend manage-frontend \
  --report "report/code-diff/_综合/综合比对分析报告_xxx.html"
```

脚本输出（单文件、内联 SVG 图表、**无 CDN 依赖**，适配内网）：
- 概览卡片：Bug 总数 / **已关闭 / 已解决**（双数） / 整体修复率（已关闭+已解决占比）/ 平均修复版本间隔
- 图①：各版本 Bug 数（按严重度堆叠柱状图）
- 图②：各版本修复率（发现版本内已关闭/已解决占比）
- 表③：版本维度明细（发现/修复 Bug 数、严重度、已关闭/解决、修复率、变更文件数、Bug/变更比）
- **单服务注入（`--service --report`）**：以 `bt-` 作用域样式嵌入比对报告，幂等可重复执行，落到「版本 Bug 趋势分析（跨版本累计）」区块
- **综合注入（`--combined --services --report`）**：`build_stats_combined()` 跨服务聚合各 `version_bugs.json`，经 `<!-- BUG_TREND_COMBINED -->` 占位符注入综合报告「各版本 Bug 数据明细」节；**条件注入规则：综合报告→聚合图，单服务报告→独立图**

### C.3 分析输出格式

- 表格类：Markdown 表格
- 趋势类：HTML 内嵌 Chart.js 图表
- 热力图类：HTML 内嵌色阶表格
- 输出路径：`{workspace}/diff_analytics_report_{日期}.html`

### C.4 无数据时的处理

- 若 `diff-analytics/` 目录不存在或所有服务均无数据 → 提示"暂无积累数据，请先执行版本比对分析"
- 若某服务只有 1 条记录 → 输出单条摘要，提示"数据不足，需2次以上分析才能展示趋势"
- 若 `version_bugs.json` 不存在 → 跳过增强层，仅输出基础层 4 维度

---## 注意事项

- **【版本方向】文件名方向 ≠ 实际方向**：`compare_A_to_B.md` 文件名中 A/B 顺序可能与实际变更方向相反。每次分析**必须执行 Step 1.3 的三步验证法**，通过版本号大小 + Commit 时间线双重确认真实方向，并在报告顶部以版本方向横幅明确展示
- **【版本方向】diff 内容语义**：`-` 行始终代表"旧版本中有、新版本中移除"，`+` 行始终代表"新版本中新增"，与文件名无关
- 对不确定的影响范围，在功能后标注 `（不确定，需进一步验证）`
- 仅基于提供的 diff 内容分析，不推断未记录的隐式依赖
- 含有 `Revert` 的提交需额外说明"回滚前后的功能差异"
- 涉及微前端（micro-app/qiankun）的路由变更，需特别标注微应用集成风险
- **变更代码和新增代码必须分开分析**，不要混在一起
- 对于数据格式变更（如 JSON/CSV/协议字段增减），必须提供字段级对比表
- 对于存储格式变更（如 Redis/DB schema），必须评估下游兼容性
- **必须执行专项校验**：版本回退、敏感信息、测试同步、循环依赖
- 敏感信息检测到后，必须明确标注并提供脱敏建议，不可直接展示完整敏感内容
- **【数据沉淀】Step 6 不可跳过**：每次分析完成后必须执行数据沉淀，将结构化指标写入 diff-analytics 目录
- **【Bug 数据】可选增强层**：version_bugs.json 和 cross_reference.json 不存在时，分析仅输出基础层 4 维度；存在时自动叠加增强层 4 维度
- **【映射引擎】Bug 导入后自动触发**：写入 version_bugs.json 后立即运行映射引擎，生成 cross_reference.json
- **【数据完整性】写入前校验**：追加 JSON 记录前需验证文件为合法 JSON，写入后验证数组长度增加

## 参考资源

- 详细输出示例：`references/output-examples.md`
- 提示词模板：`references/prompt-template.md`
- HTML 报告模板：`references/html-report-template.html`
- 数据文件 Schema：`references/analytics-schema.md`
- 目录初始化说明：`references/init-analytics.md`
- **Bug 关联解析脚本（Flow A+B 固化）**：`scripts/bug_correlate.py`
- **版本 Bug 趋势统计脚本（Flow C.2 固化）**：`scripts/bug_trend.py`
- **综合比对报告脚本（多服务汇总）**：`scripts/gen_combined_report.py`
- **P1 用例预测注入脚本（具体卡片版 + 知识库命中核对）**：`scripts/gen_p1_cases.py`
- **Bug 预测（缺陷倾向预判）注入脚本 —— 与 P1 合并呈现（互补双维度）**：`scripts/gen_bug_predict.py`（幂等；`--data-file` 注入 🐞Bug 预测总览 + 逐条详情 + P1↔Bug 映射表，置于 P1 章节之前；模板占位符 `<!-- BUG_PREDICT_SECTION -->`）
- **量化风险评分 & JIT 缺陷预测（ape 能力整合，默认每次都跑）**：`scripts/quant_jit_risk.py`（计算引擎，可选历史度量）/ `scripts/gen_quant_jit.py`（渲染+注入，幂等；`--auto` 零配置从报告派生 stats；`--combined` 按服务注入综合报告汇总表，合并进风险横幅）
