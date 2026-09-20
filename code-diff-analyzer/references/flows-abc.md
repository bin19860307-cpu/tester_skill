# 独立流程 A / B / C 细则

> 本文件是 `code-diff-analyzer` 的**细则文档**，普通 diff 分析无需加载。
> 仅在需要对应细节时按需读取；正文由 `SKILL.md` 对应小节外迁而来，保持原文。

---


## 独立流程 A（Bug 导入）/ B（映射引擎）/ C（数据分析）

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
2. **确定归属范围**：若数据明确只属于一个服务，使用该服务名；若一份提测 Bug 列表混合前后端且没有可靠服务列，使用 `_project` 项目级池，禁止猜测并挂到某个“主服务”
3. **写入 version_bugs.json**：固化脚本以 Excel 为权威源全量覆写目标系列；单服务写入 `{service}/version_bugs.json`，整包数据写入 `_project/version_bugs.json`
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
# 前后端混合的提测整包（推荐：写项目级池，避免重复计数和过度归因）
python scripts/bug_correlate.py --xlsx "5.3.0.0bug列表.xlsx" --service _project --version 5.3.0.2
# 数据确实只属于单个服务时，才写服务级文件
python scripts/bug_correlate.py --xlsx "portal-backend-bug.xlsx" --service portal-backend --version 5.3.0.2
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
- **多服务归属**：一份 Bug 列表常横跨前后端（如 5.3.0.0 列表既有后端统计口径也有前端文案）。同一份列表导入到多个服务会导致 Bug 数翻倍，并造成服务级过度归因。
  规则：无可靠服务列时整份导入 `_project` 项目级池；通过 `side_pre` 做前端/后端/通用预判展示，但不把预判当成精确服务归属或评分依据。
- **状态映射**：`状态` 列 `已关闭/关闭` → `closed`，`已解决` → `resolved`，其余 → `open`（绝不凭"同文件/同方法"推断未解决）
- **严重程度映射**：`严重`→critical / `高`→high / `一般`·`中`→medium / `低`·`建议`→low；同时保留 `severity_raw` 原文
- **编号清洗**：Excel 浮点 `80729.0` → `80729`
- 自动运行映射引擎，**全量重建** `cross_reference.json`（mapping 规则见流程 B）
- 列名采用"精确匹配 + 关键词兜底"双策略，兼容固化格式与常见变体表头

---

## 独立流程 B — 映射引擎（Bug 导入后自动触发）

### B.1 映射逻辑

> 本映射已由 `scripts/bug_correlate.py` 在导入时自动执行（见流程 A.4），每次**全量重建** `cross_reference.json`（而非追加），确保所有权和派生指标始终与 `version_bugs.json` 一致。
> 也可单独重跑：`python scripts/bug_correlate.py --xlsx <bug.xlsx> --service <svc>`

**驱动源**：`service_metrics.json` 的 `records`（**不是**「版本链 ∪ Bug 版本」的并集）。
这样不会产出「没有 metrics 的空壳 mapping」，且 `mapping 数 == 记录数` 恒成立。

**版本键必须先归一（2026-09-18 修的根因）**：三个数据文件对同一版本有三种写法
（`version_bugs` 裸号 `5.3.0.2` / `service_metrics` 与 `version_chain` 带前缀 `business-5.3.0.2`），
比较前一律过 `_common.norm_version()`。**任何新增的跨文件比较都必须先归一**，
否则会重现「49 个 Bug 有效关联 0 个」的断裂。

**映射维度 1 — Bug ↔ 版本区间**：
- `bugs_found_in_version` = `norm_version(found_in_version) == norm_version(record.version_to)`
- `bugs_fixed_in_version` = `norm_version(fixed_in_version) == norm_version(record.version_to)`
  （修复版本落在没有分析区间的版本上时，**不硬塞给相邻区间**，宁缺勿假）
- `bugs_from_parent_version` = 父版本发现的 Bug，**只作上下文，绝不并入分子**
  （口径澄清：`change_to_bug_ratio` = 本版本发现的 Bug / 产出本版本的变更文件数；
  父版本 Bug 属上一次变更的质量债，并入会虚增本区间比值）

**映射维度 2 — 高风险变更 ↔ Bug（含归因方式）**：
- `module_data_coverage > 0` → 走**精确匹配**：Bug `module` 与 `modules[].name` 包含匹配，`attribution = "module"`
- `module_data_coverage == 0`（实测 TAPD 导出的 `module` 列**全为空**）→ 退化为**版本级归因**：
  该区间所有 Bug 记到高风险项下，`attribution = "version"`，并在产物顶部显式标注。
  **不得伪装成精确匹配** —— 归因方式必须能从产物里看出来。

**映射维度 3 — Bug ↔ 专项检测**：
- `detection_precision[k] = {hit_with_bug, hit_total}`，反映「检测命中且该区间确实有 Bug」的真实归因

**结构性缺源（如实标注，不造数据）**：
- `commits_with_bugs` 恒为 `null` + `commits_data_source: "unavailable"`
  —— `service_metrics.json` 里**根本没有** commit 列表，属输入缺失，不是「暂时没算」。

### B.2 映射输出

写入 `cross_reference.json`，按版本区间组织（**实际字段，schema_version 1.1**）：

```json
{
  "service": "portal-backend",
  "schema_version": "1.1",
  "generated_at": "2026-09-18 22:39:12",
  "source": "service_metrics.json (metrics-driven)",
  "version_key_policy": "norm_version: 取首个「数字.数字」连续段，跨文件比较前必须归一",
  "attribution": "version",
  "module_data_coverage": 0.0,
  "module_data_missing": true,
  "high_risk_hit_rate": 0.714,
  "high_risk_total": 7,
  "high_risk_with_bug": 5,
  "mappings": [
    {
      "version_range": "5.3.0.1→5.3.0.2",
      "version_to": "5.3.0.2",
      "version_to_raw": "business-5.3.0.2",
      "bugs_found_in_version": ["BUG-2026-0042"],
      "bugs_fixed_in_version": ["BUG-2026-0039"],
      "bugs_from_parent_version": ["BUG-2026-0035"],
      "change_to_bug_ratio": 0.13,
      "high_risk_changes_with_bugs": [
        {
          "module": "我的班级/实训接口(classIndexByIds)",
          "file": null,
          "files": 2,
          "risk": "high",
          "bug_ids": ["BUG-2026-0042"],
          "detection_hit": ["data_format_change"],
          "attribution": "version"
        }
      ],
      "high_risk_total": 6,
      "high_risk_with_bug": 2,
      "high_risk_hit_rate": 0.333,
      "commits_with_bugs": null,
      "commits_data_source": "unavailable",
      "detections": {"data_format_change": true, "test_sync_needed": true},
      "detection_precision": {
        "data_format_change": {"hit_with_bug": 1, "hit_total": 1},
        "version_rollback": {"hit_with_bug": 0, "hit_total": 0}
      },
      "files_changed": 11,
      "segment": "forward"
    }
  ]
}
```

**衍生指标计算**：
- `change_to_bug_ratio`：`len(bugs_found_in_version) / files_changed`（**不含**父版本 Bug）
- `high_risk_hit_rate`：有 Bug 的高风险变更数 / 高风险变更总数
- `detection_precision`：检测命中且有 Bug 的数量 / 检测命中总数量

**健康检查**：`python scripts/doctor.py --service <svc>` 的 **D4** 会校验
`mapping 数 == 记录数`、`cross_reference` 是否落后于最新分析日期、是否仍有全 `null` 比值；
**D2** 会报出「同一版本多种写法」（修复前必报，修完应为空）。

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

通过 `_common.load_bugs_doc()` 检测 Bug 数据：服务级文件优先，缺失时回退 `_project/version_bugs.json`。若结果非空，在基础层之上额外输出：

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
- **综合注入（`--combined --services --report`）**：`build_stats_combined()` 优先读取 `_project/version_bugs.json` 并只统计一次；项目池不存在时才跨服务聚合各 `version_bugs.json`。结果经 `<!-- BUG_TREND_COMBINED -->` 占位符注入综合报告「各版本 Bug 数据明细」节

### C.3 分析输出格式

- 表格类：Markdown 表格
- 趋势类：HTML 内联 SVG 图表，无 CDN 依赖
- 热力图类：HTML 内嵌色阶表格
- 输出路径：`{workspace}/diff_analytics_report_{日期}.html`

### C.4 无数据时的处理

- 若 `diff-analytics/` 目录不存在或所有服务均无数据 → 提示"暂无积累数据，请先执行版本比对分析"
- 若某服务只有 1 条记录 → 输出单条摘要，提示"数据不足，需2次以上分析才能展示趋势"
- 若服务级与项目级池均无 `version_bugs.json` → 跳过增强层，仅输出基础层 4 维度

