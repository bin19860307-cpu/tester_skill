# 报告生成与注入流程（Step 7.3 + Bug 趋势 / P1 / Bug 预测 / 量化 JIT）

> 本文件是 `code-diff-analyzer` 的**细则文档**，普通 diff 分析无需加载。
> 仅在需要对应细节时按需读取；正文由 `SKILL.md` 对应小节外迁而来，保持原文。

---


## HTML 报告生成与各增强层注入

#### 7.3 HTML 报告生成

当用户要求生成报告文件时，按照 `references/html-report-template.html` 模板生成独立的 HTML 文件。

**HTML 报告要求**：
- 单文件、无外部依赖（CSS 内联）
- 专业视觉设计，包含页面头部、风险横幅、分区卡片
- 代码 diff 带语法高亮（`+` 绿色 / `-` 红色 / 上下文灰色）
- 表格支持响应式布局
- 中文界面
- 输出路径：`{workspace}/report/code-diff/{service}/{service}_{旧版本}_to_{新版本}_变更影响分析报告.html`

**生成流程**：
1. 完成 Step 1-5 的分析
2. 按照报告结构组织内容
3. 使用 HTML 模板的样式和布局
4. 写入 HTML 文件
5. 使用当前环境可用的 HTML 预览或浏览器工具检查版式；若没有预览工具，至少校验 HTML 结构和输出路径
6. 告知用户文件路径，可直接分享给团队
7. **【Bug 增强层条件注入】**通过 `_common.load_bugs_doc()` 检测 Bug 数据：优先服务级 `version_bugs.json`，缺失时回退 `_project/version_bugs.json`。存在非空 Bug 数据时，在生成比对报告后按报告类型注入：
   - **单服务报告**（条件：`--service`）：
     ```bash
     # 本次分析「只有 1 个服务」→ 注入
     python scripts/bug_trend.py --service {service} --report {本报告.html}
     # 本次分析「含 ≥2 个服务」→ 必须带上 --services，脚本会拒绝注入（Bug 归口综合报告）
     python scripts/bug_trend.py --service {service} --services {A} {B} --report {本报告.html}
     #   → 输出 [SKIP] …；确需单服务视角时加 --force
     # 已注入过的老报告要撤走：
     python scripts/bug_trend.py --strip --report {本报告.html}
     ```
     注入位置：模板 `<!-- BUG_TREND_SECTION -->` 占位符（自动替换）；已注入过则整块替换（**幂等，可重复执行**）；老报告无占位符时回退到 `</body>` 前。
     **归口规则（2026-09-19 用户决策，必须先判服务数再动手）**：Bug 数据只放在**一处** —— 本次分析含 ≥2 个服务时归**综合报告**；只有 1 个服务时才放**单服务报告**。`--strip` 撤走后留一节「📈 版本 Bug 趋势分析」+ 归口提示（幂等，只认 `BUG_TREND_START/END`）。
   - **综合报告**（条件：`--combined --services A B C`）：先由 `gen_combined_report.py` 在 ⑤ 节写入 `<!-- BUG_TREND_COMBINED -->` 占位符；注入时优先读取项目级池并只统计一次，项目池不存在时才聚合各服务数据：
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
       - 取编号：`rg -o "^## [0-9]+ [^（(]*" "{模块}_v{版本}_测试用例.md"`
     - 版本=本轮提测目标版本（动态确定，不写死历史版本）；模块由修改内容决定（如本轮「工作台/我的班级/学生列表」对应 `v5.3` 用例集）
     - 命中既有用例 → 该用例填 `kb_ref`（关联的编号），卡片显示绿色「✅ 已命中·关联 XXX」，可直接复用
     - 未命中（新增场景） → 该用例设 `estimated:true`，卡片显示红色「预估」，并注明（用户要求：未命中时注明，并提供部分预估测试用例）
     - 章节顶部统一显示绿色「📚 知识库用例集核对」框（已定位到 v{目标版本} 用例集 + AI 逐条核对结论 + 命中/预估计数），**不再使用「域差异全未命中红框」**（旧逻辑已废弃：所有服务本就同属教学管理域，按提测版本定位即可，不存在整集域不匹配）
   - **综合报告无占位符时的兜底**：`gen_p1_cases.py` 会自动生成完整的「P1 用例预测」章节并插入 `</body>` 前；区块由 `P1_CASES_START/END` 完整包裹，可重复运行，不需要手工补标题或闭合标签。
   - data JSON 结构见 `scripts/gen_p1_cases.py` 头部注释
   - **规模统计注意（2026-09-10）**：前端仓库 diff 常含 `pnpm-lock.yaml` / `package-lock.json`，其行数会严重污染"变更行数"指标（本次 main-frontend 占 +264/-39）。
     统计 `total_lines` 与「变更规模」时应**排除 lock 文件**，并在报告脚注注明已排除。

9. **【交付打包（需要把整包发给他人时）】**用 `scripts/pack_reports.py` 打成**结构保真** zip（**不要**用 `arcname=basename` 拍平）：
   ```bash
   python scripts/pack_reports.py \
     --root  "{workspace}/report/code-diff" \
     --bundle "码上{版本}影响变更报告_{日期}" \
     --out    "{workspace}/report/code-diff/码上{版本}影响变更报告_{日期}.zip" \
     --file "portal-backend/xxx_变更影响分析报告.html" \
     --file "manage-frontend/yyy_变更影响分析报告.html" \
     --file "_综合/综合比对分析报告_xxx_{日期}.html"
   ```
   - `--file` 相对 `--root`，**原样保留子目录**（`_综合/`、`{service}/`）；脚本会自动写 `使用说明.txt` 并做**解压后链接自检**（断链退出码 3）。
   - ⚠️ **一旦拍平，综合报告的 `../{service}/xxx.html` 必然断链**，解压后点击报 `ERR_FILE_NOT_FOUND`「无法访问您的文件」。单服务报告自包含可单独打开，只有综合报告的跨服务跳转依赖同级目录结构。

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
   - **首选：`--from-metrics`（与趋势分同源，2026-09-18 起）**：stats 直接取自 `service_metrics.json`
     里对应版本区间的记录，**报告里的量化分与趋势里的 `risk_score` 口径一致**：
     ```bash
     python scripts/gen_quant_jit.py --report {本报告.html} \
         --from-metrics --service {service} --services {service}
     ```
     - `--from-metrics` 用报告文件名里的 `_X_to_Y_` 定位 metrics 记录（跨写法归一，`business-5.3.0.4` 与 `5.3.0.4` 等价）；
       `--services {service}` 额外自动补历史度量 → 进入**增强 10 维**。
     - **为什么不能用 `--auto` 当主力**：`--auto` 是在报告 HTML 里**数 `class="added"/"removed"` 的行数**来估计
       `total_lines`、数变更总览表行数来估 `file_count`，而趋势分用的是 metrics 里权威的
       `lines_added/lines_removed/files_changed`。**两边不同源 → 同一份变更两个分**。实测差距：
       `portal-backend 5.3.0.3→5.3.0.4` HTML 数出 **54 行**、metrics 是 **271 行**（差 5 倍）；
       `manage-frontend 5.3.0.7→5.3.0.8` `base_risk` HTML 判 **low**、metrics 判 **medium**。
     - 匹配不到记录时会**明确告警并回退** `--auto`，不静默出错。
   - **`--auto`（HTML 派生，降级路径）**：仅在历史遗留、report 文件名不含版本区间、或 metrics 不可用时使用：
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
   - **综合报告同样默认执行**：综合报告生成后，再运行一次按服务注入汇总表（**同样优先 metrics 同源**，匹配不到才回退 HTML）：
     ```bash
     python scripts/gen_combined_report.py --services 服务A 服务B --workspace <工作区>
     python scripts/gen_quant_jit.py --report {综合报告.html} --combined --services 服务A 服务B --workspace <工作区>
     python scripts/gen_bug_predict.py --report {综合报告.html} --combined --services 服务A 服务B --workspace <工作区>
     ```
     - 量化/JIT 注入位置：综合报告「② 各服务摘要卡」内的 `<!-- QUANT_JIT_COMBINED -->` 占位符（各服务一行：定性风险 / 量化评分 / JIT 预测）。
     - **Bug 预测聚合（必须，与上面两步同批）**：`gen_bug_predict.py --combined` 取各服务 `report/code-diff/{service}/bug_predict*.json`（取最新），在 `<!-- BUG_PREDICT_COMBINED -->`（紧接量化块之后）注入「各服务 Bug 预测汇总」表（服务 / 版本区间 / H1 / H2 / H3 / 待确认 / 高优先缺陷摘要）。无 bug_predict 数据的服务会跳过并告警，不会报错。

