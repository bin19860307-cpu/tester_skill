# 常见问题 FAQ / 易错点汇总

> 本文件集中收录 `code-diff-analyzer` 使用与维护中的高频问题（现象 → 原因 → 处理）。
> 普通 diff 分析无需加载；排查问题、维护脚本或解释回归时按需读取。
> 下文每条均来自真实缺陷或用户反馈，条目与 `references/changelog.md` 可互相印证。

---

## 一、报告与展示

**Q1 报告里出现裸文本「）。 -->」，页面结构错乱**
- 原因：HTML 注释体内嵌套了 `-->`（如指导性注释写成 `（<!-- X -->）。`），浏览器在第一个 `-->` 处提前终止注释，剩余文本以裸文本渲染。
- 处理：注释体内**禁止出现 `-->`**；`_common.scan_comment_leaks()` + `safe_write_report()` 会在写盘前拦截（发现泄漏直接拒绝落盘）。**修泄漏必须改到模板源头 `references/html-report-template.html`，只修产物必然复现。**

**Q2 报告分（如 77 分）和趋势里的 `risk_score` 对不上**
- 原因：报告侧走了 `gen_quant_jit.py --auto`（在 HTML 里数 `added/removed` 行数），趋势侧用的是 `service_metrics.json` 的权威行数 —— 两边不同源，实测可差 5 倍（54 行 vs 271 行）。
- 处理：统一用 **`gen_quant_jit.py --from-metrics --service <svc>`**（取自 metrics，与趋势同源）。`--auto` 仅作降级兜底。

**Q3 趋势线上出现 `mode_mixed` 警告横幅**
- 原因：同一批数据里混用了「静态 5 维」与「增强 10 维」两种 `risk_score` 口径，权重不同、分数不可比。
- 处理：看到横幅说明趋势线不可信，先跑 `python scripts/doctor.py --all --fix` 统一口径。趋势只连 `metrics.risk_score`（恒 static 口径）。

**Q4 综合报告里「每个服务都显示 49 个 Bug」**
- 原因：项目级 Bug 池被按服务重复计数。
- 处理：多服务场景下 Bug 数据**只归口综合报告**（⑤ 节），项目级池只统计一次；单服务报告不挂 Bug 区块（`bug_trend.py` 会 `[SKIP]`，需 `--force` 才放行）。

**Q5 综合报告的注入区块跑到 `</html>` 之后**
- 原因：注入占位符只在首次存在，二次运行走了裸 `append`。
- 处理：注入优先级固定为「占位符替换 → 回插旧块原位 → 插到 `</body>` 之前」，禁止裸 append（`gen_quant_jit._insert_before_body_end()` 已收敛）。

**Q6 打包发给同事后，点链接报「无法访问您的文件 / ERR_FILE_NOT_FOUND」**
- 原因：综合报告的跨服务跳转是相对路径 `../{service}/xxx.html`，依赖 `_综合/` 与 `{service}/` 同级。**用拍平方式（`arcname=basename`）压缩会把链接全部打断。**
- 处理：用 `scripts/pack_reports.py` 打包（结构保真 + 解压后链接自检）；整包解压，勿手工重排。

---

## 二、数据与关联

**Q7 Bug 有效关联恒为 0、`change_to_bug_ratio` 全 `null`**
- 原因：同一版本在四个数据文件里写法不一（`5.3.0.2` / `business-5.3.0.2` / `v5.3.0.2`），`bug_correlate.py` 做精确字符串比较 → 两边永不交汇。
- 处理：**任何跨文件版本比较前必须过 `_common.norm_version()`**；跑 `sync_analytics.py --all` 重建后 `doctor.py` 的 D2 应为空。

**Q8 数据文件报「缺 `service` / `schema_version`」**
- 原因：早期手工 / LLM 写入只写了业务体，漏了文件头。根因是文档只给了 record 体、没给文件骨架。
- 处理：三个业务文件顶层固定为 `service` + `schema_version` + 业务键（`records` / `versions` / `files`）；**遇到缺头的旧文件只补这两个键，不要动业务内容**。骨架见 `references/analytics-schema.md`。

**Q9 `file_history` 条目数 != `metrics.files_changed`**
- 原因：把「非逻辑文件」（lock / 构建配置 / 静态资源 / 文档 / `*.html`）剔除了。它们**应保留但降权**，剔除会破坏自检。
- 处理：`_common.is_junk_path()` 只硬排除输入产物（`*tagdiff*.txt`、`temp_*`、`_build_*`、`*.bak/.pyc`）；重建用 `sync_analytics.py --service <svc>`。

**Q10 改了评分规则，但历史记录的分数没变**
- 原因：代码改了、数据没重算 —— 这类「沉默失真」D5（血缘标记）仍全绿，但分数已失真。
- 处理：改 `scoring.py` / `quant_jit_risk.py` 后**必须**跑 `doctor.py --all --fix` 重算；**D8 专抓此类问题**（校验落盘值 == 重算值，容差 0.01）。

**Q11 「变更行数」被 lock 文件污染**
- 原因：前端仓库 diff 常含 `pnpm-lock.yaml` / `package-lock.json`，行数极大。
- 处理：统计 `total_lines` 与变更规模时**排除 lock 文件**，并在报告脚注注明已排除。

---

## 三、运行与错误提示

**Q12 出错时看到一堆看不懂的英文 traceback**
- 原因：脚本此前直接 `json.load(open(path))` / `open(path).read()` / `openpyxl.load_workbook(path)`，路径或格式错时抛原生异常。
- 处理：已统一接入 `scripts/cdx_errors.py` 友好错误层 —— 文件/JSON/xlsx 读取改用 `read_json` / `read_text` / `open_xlsx`，并全脚本 `cdx_errors.guard(main)` 顶层兜底；错误会**指明文件、行列、成因与修复建议**（退出码 1/2/3/4）。加 `--debug` 或设 `CDX_DEBUG=1` 可打印完整堆栈。

**Q13 提示「文件被占用 / 读取超时」**
- 原因：目标文件正被 Excel / WPS 打开，或网络/磁盘卡顿。
- 处理：关闭占用程序后重试；CI 场景依赖 `pipeline_wrapper.py` 的超时与可解释提示（子进程超时会明确报出命令与超时值）。

**Q14 xlsx 打不开 / 提示不是有效 Excel**
- 原因：文件其实是 `.xls` 改后缀、下载成了 HTML 错误页、或已损坏。
- 处理：`open_xlsx` 会给出成因与「另存为 .xlsx」建议；同时它对 `.xls/.csv` 扩展名直接拒绝并提示先转换。

---

## 四、分析与口径

**Q15 版本方向标反了（把新版本当成源版本）**
- 原因：`compare_A_to_B.md` 文件名里的 A/B 顺序**不一定**代表真实方向。
- 处理：**必做 Step 1.3 三步验证法**（版本号大小 + Commit 时间线 + diff 语义），报告顶部用版本方向横幅展示真实方向，并标注是否与文件名一致。

**Q16 P1 用例「看不出具体要测什么」**
- 原因：只写了抽象场景名（用户明确反馈不可接受）。
- 处理：P1 用例必须是**具体卡片**：编号 / 模块 / 测试场景 / 对应代码点 / 具体测试数据(前置) / 步骤 / 预期；未命中知识库的场景设 `estimated:true` 并标注「预估」。

**Q17 知识库用例集路径找不到**
- 原因：旧文档写的路径已废弃。
- 处理：实际位于 `D:/Obsidian知识库/knowledge/初发项目/v{目标版本}/03-测试用例/{模块}/{模块}_v{目标版本}_测试用例.md`，**按版本动态确定**（不再写死 v5.2）。

**Q18 手工录入 Bug 把「未解决」标错**
- 原因：手工逐条录入/临时脚本易凭「同文件/同方法」推断状态。
- 处理：**统一用 `scripts/bug_correlate.py` 解析 xlsx**，以 xlsx 权威状态为准（`已关闭/关闭 → closed`、`已解决 → resolved`，绝不推断）。

---

## 五、维护与发布

**Q19 改了脚本但投稿包没带上改动**
- 原因：C 盘 `~/.workbuddy/skills/<skill>` 是唯一真源；发布仓库 `E:\tester_skill` 是副本，二者会漂移。`skill_publish_prep.py` 会用 `shutil.rmtree` **整目录替换** E 盘副本。
- 处理：**只改 C 盘真源**；发布时用 `skill_publish_prep.py` 重新生成；注意该脚本**会覆盖 manifest 的 `display_name` 为裸 `name`**，发布后需补回。

**Q20 投稿 zip 被平台拒收 / 含垃圾文件**
- 处理：用 `工具脚本/build_upload_zip.py`：自动剔除 `.gitignore`、`__pycache__`、`.pyc` 等；无扩展名文件（`LICENSE` / `Dockerfile`）在 zip 内补 `.txt`。注意其黑名单**不含 `.pytest_cache`**，投稿前需手动清理。
