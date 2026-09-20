# Code Diff Analyzer 变更记录

> 保存历史设计决策、用户口径和修复背景。普通代码变更分析无需加载；
> 仅在排查历史行为、维护脚本或解释回归原因时读取。最新记录在上。

> 设计演进可追溯。每次对 Skill 的逻辑 / 脚本 / 文档做实质改动，在此追加一条（最新在上），便于复盘「更新过程」。

- **2026-09-20 · v1.1.1 · HTML 注释泄漏防护（模板源头修复 + 写盘守卫）**
  - 问题：用户截图反馈本轮报告（portal-backend 5.3.0.4→5.3.0.5）P1 用例预测标题下出现裸文本「）。 -->」。根因：`html-report-template.html` 两处指导性注释用了「（`<-- X_START/END -->`）。」嵌套写法，浏览器在嵌套的 `-->` 处**提前终止注释**，剩余文本以裸文本渲染。2026-09-18 修过同类泄漏，但只修了已生成报告、**模板源头漏修**，从模板重建报告时复现。
  - 修复：① 模板两处注释改为「X_START/END 标记对」文字表述（注释体内不再出现 `-->`）；② `_common.py` 新增 `scan_comment_leaks()`（扫描注释体内 `<--`/`--!>` 嵌套）与 `safe_write_report()`（**发现泄漏拒绝落盘并 SystemExit**）；③ 接入全部 5 个 HTML 写盘方（gen_p1_cases / gen_bug_predict / gen_quant_jit / bug_trend / gen_combined_report）；④ 新增回归 `tests/test_comment_leaks.py`（模板必须干净 + 扫描识别 + 拒绝落盘）。
  - 波及修补：本轮报告 + 存量在册报告 `trufar-frontend_mashang-5.2.0.6_to_5.2.0.7` 同模式泄漏已就地修补并复扫 0 泄漏（`_bak_*` 备份目录按设计保留原样）。
  - 教训：**修泄漏类缺陷必须修到「源头模板/生成器」，只修产物必然复现**；且写盘方要有机器守卫，不能只靠人工肉眼。

- **2026-09-19 · 文档口径修正：`references/analytics-schema.md` 的 risk_score 段**
  - 问题：该文档仍在「risk_score 计算公式」标题下把 `min(100, high*10 + medium*5 + low*1)` 当作**当前公式**。该式已于 2026-09-18 评分口径统一时降级为 `risk_score_legacy`（仅留档审计），但文档未同步 → 外部材料按旧式标注。实测后果：培训 PPT 的「真实产物摘录」配图写成 `risk_score: 37 // 高*10+中*5+低*1`，而真实记录已是 `risk_score: 80.0`（static）/ `risk_score_legacy: 32`。
  - 修正：改写为「risk_score 口径（2026-09-18 起）」，明确 `risk_score` = 静态 5 维确定性分（`scoring.canonical_risk_score()` 产出，趋势唯一口径、跨版本可比）、`risk_score_enhanced` = 增强 10 维（有历史度量时写入，禁止参与趋势连线）、`risk_score_legacy` = 旧公式值（仅审计）。
  - 补齐字段表：`risk_score_mode`（固定 `"static"`）、`risk_score_source`（血缘）、`risk_score_enhanced`、`risk_score_legacy`，并注明由 `scripts/doctor.py` 的 D5 检查项机器校验「落盘值 == 重算值（容差 0.01）」。
  - 触发来源：PPT 通篇体检时发现配图沿用旧式 → 回到文档逐字核对，确认是**文档漂移**而非配图笔误。教训：口径变更要连同 `references/` 一起改，否则过期文档会持续污染下游材料。

- **2026-09-19 · 版本升级至 v1.1.0（Codex 优化收口）**
  - 首次为 Skill 引入 `version` 字段（SKILL.md frontmatter `version: "1.1.0"`），作为「技能包」整体版本号，与脚本内部子版本（如 `scoring.RATING_RULES_VERSION=1.1`、`quant_jit_risk.WEIGHTS_VERSION=1.1`）解耦，避免误读为同一套口径。
  - 本次 v1.1.0 对应的一轮实质改动即上方「2026-09-19 · 全面审查修正」条目（P1 注入落位硬化、知识库核对版本动态化、Bug 归口综合报告、状态映射统一、UTF-8 输出）；该轮由 Codex 进一步审查并加固代码，本条目仅做版本归档与口径收口登记。
  - 配套动作：用优化后代码重跑本轮 3 份报告（`portal-backend 5.3.0.3→5.3.0.4`、`manage-frontend 5.3.0.7→5.3.0.8`、综合报告），将 P1 用例集版本引用由写死的 v5.2 修正为从 `kb_check.kb_location` 推断的 v5.3（实测数据 `kb_location` 含 `初发项目/v5.3`）。重跑前备份至 `report/code-diff/_bak_20260919_codex优化前/`。

- **2026-09-19 · 全面审查修正：P1 注入、动态版本、Bug 归口与文档口径收口**
  - `gen_p1_cases.py` 无模板锚点时改为生成自包含章节并插入 `</body>` 前，不再把内容追加到 `</html>` 之后；新增幂等与结构回归测试。
  - 知识库核对版本改读 `kb_check.target_version`，缺省时从 `kb_location` 推断；移除写死的 v5.2 和废弃路径。
  - 多服务分析统一为「单服务报告不承载 Bug 区块，项目级 Bug 只在综合报告展示」；单服务分析仍可使用服务级数据或项目池回退。
  - 状态映射统一为 `已关闭/关闭 → closed`、`已解决 → resolved`；趋势图统一描述为内联 SVG、无 CDN。
  - 只读审查/解释默认不写 `diff-analytics`；生成报告、趋势分析或用户明确要求沉淀时才启用 Step 6。
  - `scoring.py` 命令行输出显式使用 UTF-8，修复 Windows GBK 控制台的 emoji 编码异常。

- **2026-09-19 · Bug 数据归口综合报告 + 端归属拆分落地（用户决策）**
  - **决策原文**：「把所有 bug 相关的数据都移至综合报告中，除非当前分析服务只有一个。那就展示在单服务中。」配套的更早诉求是「只按综合的提测版本关联 bug，不区分前后端服务……或者是否有方法能区分出关联关系，每份报告都能输出」。
  - **① 归口规则（三条固化行为）**：
    - **≥2 个服务**时，`bug_trend.py` **拒绝**往单服务报告注入 Bug 区块（打印 `[SKIP]`，需 `--force` 才放行）；判定依据是显式 `--services`（本次分析的服务清单），缺省视为单服务。
    - **`--strip`**（新增）反向撤走单服务报告里已注入的区块，并留一节「📈 版本 Bug 趋势分析」+ 归口提示；幂等（第二次返回「无区块」），只认 `BUG_TREND_START/END` 标记、不会误删正文。
    - **综合报告成为 Bug 数据唯一归口**：① 总览保留「项目级 Bug 49（已关闭 39 / 已解决 6）」，⑤ 节承载完整趋势，② 各服务摘要卡**不再各挂一个 49**（改为「前后端共用同一池；明细与前端/后端拆分见 ⑤」），避免「每个服务都有 49 个 Bug」的误读。
  - **② 端归属拆分（回应「每份报告都能输出关联关系」）**：`bug_trend.py` 趋势区块新增 **④ 端归属预判拆分（按发现版本）** 表 —— 按 `side_pre` 把每个发现版本的 Bug 拆成 **前端 / 后端 / 通用（端归属待定）** 并给合计行。`build_stats()` 与 `build_stats_combined()` **都产出** `side_breakdown`，因此综合报告与「只分析 1 个服务」的单服务报告都能看到前后端拆分。实测本次批次：5.0.0.0 前1/后0/通1、5.3.0.0 前7/后10/通4、5.3.0.1 前9/后6/通0、5.3.0.2 前1/后4/通0、5.3.0.3 前1/后2/通3，**合计 前端19 / 后端22 / 通用8**。
  - **③ `_common.py` 新增服务侧判定**：`SERVICE_SIDE_NAME_RULES`（`*-backend`→后端、`*-frontend`→前端）、`SERVICE_SIDE_EXT_RULES`（`.java`→后端，`.vue/.ts/.js/.css/.html`→前端）、`service_side()`、`bugs_side_breakdown()`、`side_relevant_count()`。为后续「按服务所在端过滤关联 Bug」预留，本轮未启用。
  - **④ 明确保留项（不要误删）**：单服务报告量化表里的「**Bug 未解决率**」是**风险评分输入项**，不是 Bug 展示数据，两侧都保留 —— 否则单服务报告分与综合表分（77.2 / 58.2）会再次出现「结论不一致」。
  - **本次批次落地结果**：`portal-backend 5.3.0.3→5.3.0.4`、`manage-frontend 5.3.0.7→5.3.0.8` 两份单服务报告的 Bug 区块已撤走（留归口提示，备份在 `_bak_20260919_归口综合前/`）；`_综合/综合比对分析报告_portal-backend_manage-frontend_20260919.html` 重新生成并注入量化表 + 含 ④ 拆分表的趋势区块。
  - 回归：pytest **178 → 196 项**（新增 `tests/test_bug_consolidation.py`：服务侧判定、端归属拆分守恒、综合报告承载拆分表、`--strip` 幂等与提示落位、`SKIP` 规则与 `--force` 放行）；doctor 复跑 7 项（均为既有良性项，无新增）。

- **2026-09-18 · 用户反馈三问题修复：注释泄漏 + 项目级 Bug 池 + 评级口径统一**
  - **① 报告裸文本泄漏（`）。 -->` 明文显示）**：报告模板注释里写了「重复注入自动替换（`<-- BUG_PREDICT_START/END -->`）」—— 注释内第一个 `-->` 会**提前终止注释**，剩余 `）。 -->` 以明文渲染（3 份报告各 2 处，P1 块带数字 `1` 导致首轮正则漏修，已补齐）。已修复全部报告，并在 `gen_bug_predict.py` / `gen_p1_cases.py` 文档与本文档固化守则：**HTML 注释内禁止出现 `-->`**。
  - **② Bug 关联只有后端服务（用户决策：按提测版本整包关联，不区分前后端）**：实测 49 条 Bug 是 5.3 提测整包（前端 UI 类与后端类混在一起，源表无服务/模块列），原全挂在 `portal-backend/version_bugs.json` 名下属**过度归因**——前端服务关联缺失，portal 自身 Bug/变更比也被虚高。改造：
    - 新增**项目级 Bug 池** `.workbuddy/diff-analytics/_project/version_bugs.json`（`scope: "project"`），portal 服务级副本移除（备份留档）；导入端 `bug_correlate.py --service _project` 即写池。
    - `_common.py` 新增 `load_bugs_doc()`（服务级优先、项目池回退）与 `classify_bug_side()`（**端归属预判**：前端 19 / 后端 22 / 通用 8，关键词规则、报告中必须带「预判」字样、可在池中人工覆盖 `side_pre` 字段，不参与评分）。
    - `bug_trend.py`：单服务缺服务级数据时可回退项目池（标注「项目级（按提测版本整包关联，不区分前后端服务）」）；项目口径下单服务视角「Bug/变更比」标 `—`（不可归因），综合表口径下文件数按服务求和、比值恢复有效。该条为 2026-09-18 行为，已被 2026-09-19 的“多服务只归口综合报告”规则进一步收口。
    - `gen_combined_report.py`：摘要卡改「项目级 Bug：49（预判 前端19/后端22/通用8）」；「各版本 Bug 数据明细」项目口径下只渲染一次（避免同池重复）；**坑**：项目池的 Bug 标题被所有服务共享，会把概念指纹污染成假跨服务关联（实测 0→1），已改为 scope=project 时不并入指纹。
    - 其余消费方（`quant_jit_risk.py` 未解决率、`doctor.py` D2/D4/D6、`pipeline_wrapper.py`）全部接入池回退；各服务 cross_reference 已按池重建。
  - **③ 评级口径不一致（综合卡「中」vs 单服务横幅「低」）**：新增 `gen_quant_jit.py sync_banner_rating()` —— `--from-metrics` 注入时把横幅（class + icon + 等级行）**同步为确定性评级**（rules 1.1），原定性结论保留在括号内（「综合风险等级：中（…；量化确定性评级 rules 1.1，原定性「低」）」）+ 正文口径说明一行；幂等，等级一致时 no-op。实测 manage-frontend 横幅 低→中 已同步、portal-backend 高不变。
    - **连带发现**：综合报告量化表此前用**静态分**（78.0/50.0）而单服务横幅是**增强分**（77.0/58.0）——综合模式漏补历史度量。已在 `--combined` 循环补 `auto_historical`，两表同一模式并在每行标注口径（增强10维）。
    - 注：manage-frontend 报告分 49.0→**58.0** 属「变准」——历史度量的 Bug 未解决率此前无数据源（恒 0），项目池建立后取到真实值 0.204。
  - 回归：pytest **156 → 173 项**（新增 `tests/test_project_bug_pool.py`：池回退、端归属预判、项目口径趋势、横幅同步幂等）；doctor 复跑 7 项（均为既有良性：C5 历史 files 缺清单 ×4、acme-login-script 不完整 ×3）。

- **2026-09-18 · 综合报告展示异常修复：注入块被追加到 `</html>` 之后 + ⑤ 节重复渲染**
  - **① 注入定位幂等缺陷（根因）**：`gen_quant_jit.inject_combined()` 的占位符只在**首次**存在；二次运行时判定「无占位符」，走 `html + frag` 分支 → 区块落到 `</html>` 之后，综合报告的「各服务量化风险评分 & JIT 预测」表因此显示在「⑥ 综合发布建议」之后（文档结构损坏）。修复：先记旧块位置，优先级 `占位符替换 → 回插旧块原位 → 插到 </body> 之前`，并抽出 `_insert_before_body_end()` **禁止裸 append**；单服务 `inject()` 兜底同样收敛。回归测试 `TestInjectIdempotentPlacement` 锁死「任何情况下不得出现在 </html> 之后」。
  - **② ⑤ 各版本 Bug 数据明细重复渲染**：项目级口径下，本节同时渲染 bug_trend 注入的趋势区块（含 ③ 版本维度明细）**和** gen_combined_report 自己的「产生版本 / 解决版本」两张表，内容 100% 重复，且「服务」列每行重复 20 字标签「项目级（5.3 提测整包，含前后端）」。修复：项目级口径下本节只保留 intro + 趋势区块占位符，不再另出汇总表；服务级口径维持原两张表。综合报告体积 24.0KB → 20.2KB。
  - **③ 端归属展示顺序**：`side_pre_dist` 原按 dict 插入序显示（通用/前端/后端），统一为 **前端 / 后端 / 通用**（摘要卡与趋势口径提示两处）。
  - 回归：pytest **173 → 178 项**。

- **2026-09-18 · 重跑上轮报告时发现并修掉的「报告与趋势不同源」+ CORE_PATTERNS 二次过宽**
  - **真问题：报告里的量化分与趋势里的 `risk_score` 用的不是同一组输入。** 报告侧走 `gen_quant_jit.py --auto`（在 HTML 里数 `class="added"/"removed"` 的行数），趋势侧走 `service_metrics.json` 的权威 `lines_added/lines_removed/files_changed`。实测同一份变更**差 5 倍**：`portal-backend 5.3.0.3→5.3.0.4` HTML 数出 **54 行** / metrics **271 行**；`manage-frontend 5.3.0.7→5.3.0.8` 的 `base_risk` HTML 判 **low** / metrics 判 **medium**。
    → 新增 `gen_quant_jit.py --from-metrics --service <svc>`：用报告文件名里的 `_X_to_Y_` 定位 metrics 记录（跨写法归一），**报告分与趋势分从此同源**；`--combined` 综合模式同样优先 metrics。匹配不到时明确告警并回退 `--auto`，不静默出错。**`--auto` 降级为兜底路径。**
  - **CORE_PATTERNS 二次收窄**：上一版改成的 `降级|回退|回滚|rollback|downgrade` **仍然过宽** —— 裸「回退」命中「**表格样式回退**」「UI 回退」这类前端样式还原。实测 `manage-frontend 5.3.0.7→5.3.0.8` 有三个 low 风险的样式模块被判核心模块，`core 4/6` → 趋势分 70.0 虚高。现收窄为 `降级|版本回退|版本降级|回滚|rollback|downgrade`（`回退` 必须带「版本」前缀）→ 该区间趋势分 **70.0 → 50.0**。
  - **`sync_analytics.py --all` 跳过 `_` 开头目录**：此前会把 `_trash`（脚本自己移入的残留）当成服务扫描，输出噪音且可能被误建数据文件。与 `doctor.py` 的过滤口径对齐。
  - **重跑结果（上轮 2026-09-18 09:35–09:41 那一批）**：
    | 报告 | 量化分 | 口径 |
    |---|---|---|
    | `portal-backend 5.3.0.3→5.3.0.4` | 76.0 → **77.0** | 静态5维（无历史度量）→ **增强10维（含历史度量）** |
    | `manage-frontend 5.3.0.7→5.3.0.8` | 36.0 → **49.0** | 静态5维 → 增强10维 |
    | `_综合/综合比对分析报告` | 重新生成并注入 2 服务汇总 | — |
    **对照结果（如实记录，勿再声称「全部一致」）**：`portal-backend` 横幅「高」↔ 确定性评级 `high` ↔ 报告分 77.0，**三者一致**；`manage-frontend` 横幅仍是「低」（正文定性未重跑），而确定性评级已为 `🟡 中`（static 50.0 / enhanced 49.0）→ **存在残留分歧**。
    - 根因：`derive_stats_from_report()` 把横幅 `class="risk-banner (high|medium|low)"` 当作 `base_risk` 的**输入**，而 `--from-metrics` 的 `stats_from_metrics()` 改从 metrics 的模块风险推 `base_risk`。两条路径对同一份变更有不同结论时，**横幅不会自动改写**。
    - 性质：横幅评级是**定性正文**，属「未重跑」范畴（见下方遗留项），不是数据错误；报告分与趋势分的**数值**差异（增强10维 vs 静态5维）是设计使然，但**评级标签出现两个值**应视为待收口项。
    - 收口方式（待定）：① 重跑定性正文使横幅与确定性评级对齐；② 在横幅内并排标注「定性：低 / 量化：中」，明示两个口径，不覆盖原文。
  - 回归：pytest **135 → 156 项**（新增 `tests/test_gen_quant_jit.py`：版本区间解析、跨写法命中、取最新记录、失败可解释，以及 CORE_PATTERNS 过宽匹配回归）。

- **2026-09-18 · 能力体检修复（P0–P2 全部落地）· 4 个「能力空转」项整改**
  - **缺陷根因（实测）**：`version_bugs.json` 用裸号 `5.3.0.2`、`service_metrics.json` / `version_chain.json` 用 `business-5.3.0.2`，而 `bug_correlate.py` 做**精确字符串相等**匹配 → **49 个 Bug 有效关联 0 个**，`change_to_bug_ratio` 全 `null`。这是「两端永不交汇」的真因，此前只被描述为「join 偶尔漏」。
  - **新增 `scripts/_common.py`（全技能唯一实现）**：`norm_version()` 版本键归一（取首个「数字.数字」连续段，三种写法归一为同一键）+ `version_key()` 补 4 段可排序 + 路径过滤两级（`JUNK_PATTERNS` 硬排除输入产物 `*tagdiff*.txt`/临时文件；`NON_LOGIC_PATTERNS` 软标记 lock/资源/文档，**保留不剔除**，否则会破坏「条目数 == files_changed」自检）。
  - **新增 `scripts/scoring.py`（统一口径）**：`canonical_risk_score()` 摒弃 LLM 手填、由记录确定性推出 0-100 分；旧公式值不删、改名 `risk_score_legacy` 留档。`rate_change()` 把 Step 5.1 的伪代码固化为 **R1–R7 确定性规则（rules 1.1）**。**关键性质：增强 10 维分与静态 5 维分不可比**（同一 stats 下 87.0 vs 77.4，权重不同）→ 趋势只连 `risk_score`（恒 static 口径），增强分另存 `risk_score_enhanced`。
  - **评级阈值重标定（rules 1.0 → 1.1）**：1.0 的 R3「>5 文件」与 R4「存在高风险模块」实测**几乎无差别触发**（8 条记录 7 条判高）。反例：`manage-frontend 5.3.0.7→5.3.0.8`（6 文件 / 44 行 / 高风险模块 0 个）、`trufar-landing-page 1.0.9→1.0.10`（7 文件 / 37 行 / 0 个），只因「文件数 > 5」被判高。改为：规模阈值统一到 `quant_jit_risk` 已公开的 400 行 / 10 文件 / 5 文件；R4 由「存在」改「占比 ≥ 1/3 且 ≥2 个」；原样式规则顺延 R7。重算后分布 **高 4 / 中 3 / 低 1**。
  - **`bug_correlate.py` 重写映射引擎**：驱动源由「版本链 ∪ Bug 版本」并集改为 **metrics 记录驱动**（不再产出空壳 mapping）；跨文件比较一律先归一；**首次实现 `high_risk_hit_rate`**（此前仅文档有定义，代码全库查无实现）；父版本 Bug 只作上下文、**不并入分子**；Bug 模块列全空时诚实退化为「版本级归因」并标注 `attribution`。
  - **`quant_jit_risk.py`**：`auto_historical()` 原先硬编码返回 `0.0/0/0`（假的「零风险历史」）→ 改为从最新 metrics 真实计算 `churn_rate`；`author_exp` 默认中性 3（不再让缺失值变成最高风险）；`CORE_PATTERNS` 的 `版本|version` 过宽（每个版本都有「版本号 pom」模块 → 每条记录都被判核心模块、分数失去区分度）收窄为 `降级|版本回退|版本降级|回滚|rollback|downgrade`（详见上方「CORE_PATTERNS 二次收窄」条目）。
  - **新增 `scripts/sync_analytics.py`**：`file_history` 确定性重建（含**无条件清除**历史混入的输入产物）、**存储层**版本键归一、历史 HTML 报告回填 `files`（**仅在能完整还原时**，聚合摘要如 `views/home/* (33 文件)` 一律拒绝，不猜文件名）、`risk_score` 重算（`risk_score_legacy` 只在首次捕获、绝不被二次运行覆盖）。
  - **新增 `scripts/doctor.py`（一键体检/修复）**：D1–D9，其中 **D8 分数可复现性**是新增的关键探针——「评分代码改了、数据没重算」时 D5（血缘标记）仍全绿但分数已失真，D8 专抓此类沉默失真；`--move-temp` 把临时产物与数据目录 `*.bak` 残留**移入 `_trash/`（可逆，不删除）**。
  - **新增 `scripts/verify_precision.py`（精度标定）**：真实计算 `high_risk_hit_rate` / `detection_precision` / 分桶单调性；**样本 < 30 时拒绝给出权重建议**，避免用小样本拟合出看似权威的参数。
  - **新增 `scripts/tests/`（pytest 156 项）**：合成工作区复刻上述全部缺陷特征，锁死「mapping 数 == 记录数」「跨写法 join 必须命中」「父版本 Bug 不进分子」「模块全空诚实降级」等核心性质。
  - **闭环验证**：`sync_analytics --all --backfill` 后 `doctor --all` 问题数 **26 → 6**；剩余 6 项为 **2 个空骨架服务的必填文件缺失** + **4 个历史区间无 `files` 清单**（原始输入产物已删除，属结构性不可恢复，主动保留不猜）；剔除时间戳字段后 `sync` / `doctor --fix` 二次运行 **0 变化**（幂等）。

- **2026-09-18 · 报告打包「结构保真」+ 新增 pack_reports.py（修复解压后链接打不开）**
  - 新增 `scripts/pack_reports.py`：把本轮报告打成**结构保真** zip——原样保留 `_综合/`、`{service}/` 等子目录层级，并内置「解压后链接自检」（断链则退出码 3）+ 自动写入 `使用说明.txt`。
  - 修复的坑：综合报告的跨服务跳转链接是**相对路径** `../{service}/xxx.html`（见 2026-09-10「跳转链接可移植化」条目），其前提是「服务报告在 `{service}/`、综合报告在 `_综合/`，二者同级」。**若打包时把文件拍平到根目录（`arcname=os.path.basename(...)`），解压后 `../{service}/` 指向不存在的目录，点击即报 `ERR_FILE_NOT_FOUND`「无法访问您的文件」。** 单服务报告本身自包含、可单独打开，只有综合报告的跨服务跳转依赖目录结构。
  - 规范：报告包**必须整包解压并保持同级结构**，禁止只解压/重排部分文件；分享前用 `pack_reports.py` 打包，勿用「拍平」方式手工压缩。
- **2026-09-18 · 数据文件「文件头」规范落地 + file_history 结构修正 + 历史度量读取修复**
  - `SKILL.md` Step 6.2 / 6.2.1 / 6.2.3：明确三个业务文件（`service_metrics` / `version_chain` / `file_history`）的**统一文件头**（`service` + `schema_version` + 业务键），补齐三键骨架 JSON 与「校验文件头」步骤；并说明 `file_history` 的条目必须写在 **`files`** 对象内（早期写入漏掉包裹层，导致 4 个服务数据不合 schema）。
  - `scripts/quant_jit_risk.py`：抽出 `extract_files()` 修复 `auto_historical()` 的读取缺陷——原式 `files = data if isinstance(data, dict) else data.get("files", {})` 的 else 分支**永不可达**，实际后果是「合规结构读不到（`mod_count` 恒 0）、扁平结构被 `service`/`schema_version`/`recent_changes` 等元数据键稀释均值」。现兼容两种结构：优先取 `files`，否则回退为「含 `change_count` 的条目」。
  - 数据侧：13 个文件补齐顶层 `service` / `schema_version`，4 个 `file_history.json` 补齐 `files` 包裹（`recent_changes` 保留顶层）；补齐后 schema 定义的 **17 个文件全部合规**，逐文件与备份比对**内容零改动**。
  - 回归：`analyze` / `score` / `report` 三阶段端到端退出码 0；`auto_historical()` 对 5 个服务全部返回有效值（portal-backend `mod_count=1.7`，其余 1.0）。
- **2026-09-18 · 补记 CI / 容器化流水线（pipeline_wrapper）+ analyze 交接严格把关**
  - `scripts/pipeline_wrapper.py`：**analyze 阶段交接校验由「只告警」改为「严格阻断」**——`service_metrics.json` 未就绪时以**退出码 2**（`EXIT_HANDOFF_MISSING`）结束，供 CI 门禁拦截「语义分析产物缺失却继续出报告」；新增 `--allow-missing-metrics` 豁免开关（手动 / 开发场景降级为警告 + 退出码 0）。
  - `--stage all` 默认链由 `score → report` 修正为 **`analyze → score → report`**（此前 all 反而不含 analyze，与「先校验再算」直觉相反）。
  - `SKILL.md`：**补记此前遗漏的 CI / 容器化流水线章节**（`pipeline_wrapper.py` 四脚本编排、`Dockerfile` 用法、退出码约定、与上游 `tagdiff.sh` 的上下游关系、以及「真实 CI 尚未接入」的现状）。
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

