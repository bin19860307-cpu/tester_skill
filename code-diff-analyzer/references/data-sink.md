# 数据沉淀细则（Step 6）

> 本文件是 `code-diff-analyzer` 的**细则文档**，普通 diff 分析无需加载。
> 仅在需要对应细节时按需读取；正文由 `SKILL.md` 对应小节外迁而来，保持原文。

---


## Step 6 — 数据沉淀（存储位置 / 不变量 / 工具 / 写入步骤 / 校验）

### Step 6 — 数据沉淀（生成产物时执行）

当用户要求生成报告、执行趋势分析、维护历史指标，或明确要求沉淀本次结果时，
将 Step 1-5 的结构化指标写入本地数据文件，用于后续历史对比和趋势分析。
如果用户只要求只读审查、解释 diff 或给出文字结论，默认不创建或修改 `diff-analytics`；
可在回复中说明尚未沉淀，并在用户确认需要持久化后再执行本步骤。

#### 6.1 数据存储位置

```
{workspace}/.workbuddy/diff-analytics/{service}/
├── service_metrics.json    ← 每次分析追加一条记录
├── version_chain.json      ← 每次分析追加版本关系
├── file_history.json       ← 每次分析更新文件变更记录
├── version_bugs.json       ← 流程 A 导入（可无）
└── cross_reference.json    ← 流程 B 映射产物（可无，由脚本全量重建）
```

- `{service}` 为 Step 1.1 提取的服务名称（如 `portal-backend`、`agent`）
- 启用数据沉淀时，若目录或文件不存在，自动创建（含空 JSON 骨架）
- 完整 Schema 定义见 `references/analytics-schema.md`

#### 6.1.1 三条不变量（2026-09-18 体检修复，写入时必须遵守）

1. **版本键唯一写法**：同一版本在四个文件里必须只有一种写法。
   跨文件比较**必须**先过 `_common.norm_version()`（`business-5.3.0.2` / `v5.3.0.2` / `5.3.0.2` → `5.3.0.2`）。
   违反后果：实测曾出现 **49 个 Bug 有效关联 0 个**、`change_to_bug_ratio` 全 `null`。
2. **`risk_score` 由脚本产出，禁止手填**：一律走 `scoring.canonical_risk_score()`，
   并写入血缘字段 `risk_score_source = "script:scoring.canonical_risk_score(...)"`。
   旧公式（`min(100, high*10+medium*5+low*1)`）的值**不删除**，改名 `risk_score_legacy` 留档审计。
3. **变更文件清单不含输入产物**：`*tagdiff*.txt`、`temp_*`、`_build_*`、`*.bak/.pyc`
   一律不进 `file_history`（`_common.is_junk_path()` 硬排除）。
   非逻辑文件（lock / 构建配置 / 静态资源 / 文档 / `*.html`）**保留但降权**，不得剔除
   —— 剔除会破坏「`file_history` 条目数 == `metrics.files_changed`」自检。

#### 6.1.2 维护工具（做完分析后按需调用）

```bash
python scripts/sync_analytics.py --service <svc>     # 重建 file_history + 归一版本键 + 重算 risk_score
python scripts/sync_analytics.py --all --backfill    # 全部服务；--backfill 从历史报告回填 files（仅限可完整还原的）
python scripts/sync_analytics.py --service <svc> --check    # 只自检不改动
python scripts/doctor.py --all                       # 一键体检 D1–D9（只读）
python scripts/doctor.py --all --fix --move-temp     # 体检 + 自动修复 + 临时产物移入 _trash/（可逆）
python scripts/verify_precision.py --all             # 精度标定（样本 < 30 时拒绝给权重建议）
python -m pytest scripts/tests/ -q                   # 回归；项数以当前测试输出为准
```

**何时必跑**：① 改了 `scoring.py` / `quant_jit_risk.py` 的评分规则后 → 必须 `--all --fix` 重算；
② 报告里的分数与最新代码不一致（**D8 会报**）→ 同上；③ 交报告前跑一次 `doctor --all`，问题数应为已知且可解释。

#### 6.1.3 两个 `risk_score` 的口径（不可混用）

| 字段 | 口径 | 用途 |
|------|------|------|
| `metrics.risk_score` | **静态 5 维**（`risk_score_mode: "static"`） | **趋势连线的唯一口径**，跨版本可比 |
| `metrics.risk_score_enhanced` | 增强 10 维（有历史度量时） | 单份报告展示，**禁止参与趋势连线** |
| `metrics.risk_score_legacy` | 旧公式 `min(100, high*10+medium*5+low*1)` | 仅历史审计，不再使用 |

> ⚠️ 同一组 stats 下静态与增强权重不同（`base` 0.30→0.20、`core` 0.25→0.20），
> **分数必然不同**（实测 87.0 vs 77.4）。`bug_trend.py` 检测到两种口径混用时会打
> `mode_mixed` 警告横幅 —— 看到横幅说明趋势线不可信，先跑 `--fix` 统一口径。

#### 6.2 写入步骤

> **⚠️ 三个文件都有统一的「文件头」**：顶层固定为 `service` + `schema_version` + 业务键（`service_metrics.json` → `records`、`version_chain.json` → `versions`、`file_history.json` → `files`），见 `references/analytics-schema.md` §「初始化骨架」。下面各步给出的是**业务体的写入格式**；创建新文件时**先按骨架建好文件头**，再写业务体。

**Step 6.2.1 — 追加 service_metrics.json**

先确保文件是**三键骨架**（不是裸的 `{"records": []}`）：

```json
{
  "service": "{service}",
  "schema_version": "1.0",
  "records": []
}
```

- `service` 必须与 `{service}` 目录名一致；`schema_version` 当前固定 `"1.0"`
- **历史坑（2026-09-18 实测）**：早期手工 / LLM 写入的文件漏掉了 `service` 与 `schema_version`，只剩 `{"records": [...]}`（而由脚本 `bug_correlate.py` 写的 `version_bugs.json` / `cross_reference.json` 反倒是齐的——因为脚本自己会建骨架）。根因是本步骤此前**只给了 record 体、没给文件骨架**。
- **遇到缺文件头的旧文件：只补这两个顶层键，不要动 `records` 内容。**

然后把本次分析结果作为**一条记录**追加到 `records` 数组末尾：

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
    "risk_score": 72,
    "risk_score_mode": "static",
    "risk_score_source": "script:scoring.canonical_risk_score(静态5维)",
    "risk_score_legacy": 72,
    "risk_score_legacy_formula": "min(100, high*10 + medium*5 + low*1)",
    "rating_rules_version": "1.1"
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
- `metrics.risk_score`：**由脚本确定性产出**（`scoring.canonical_risk_score()`），
  **不是** `high*10 + medium*5 + low*1`。后者是旧公式，其值只以 `risk_score_legacy` 形式留档审计。
  **禁止手工填写 `risk_score`** —— 写完跑 `doctor.py --service <svc>`，D8 会校验落盘值是否等于重算值。
  写入时用 `python scripts/sync_analytics.py --service <svc>` 自动补全上述血缘字段。
- `metrics.rating_rules_version` / 顶层 `rating`：确定性评级及其规则版本（见 Step 5.1）
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

对本次变更的每个文件，在 **`files`** 对象下更新其变更记录（下面的内容属于 `files`，**不是文件顶层**）：

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

> **写入后的完整文件长这样**：`{"service": "<服务名>", "schema_version": "1.0", "files": { ...上面的条目... }}`。
> `recent_changes` 等摘要字段与 `service` / `schema_version` **并列在顶层**，不要混进 `files`。
> 历史坑（2026-09-18 实测）：早期手工写入把「路径 → 记录」直接放在顶层、漏掉了 `files` 包裹，
> 导致 `quant_jit_risk.py` 的历史度量提取失效 → 已修复脚本为双结构兼容，但**新写入一律按规范结构**。

- 若文件已存在：追加 `appear_in`、`risk_history`、`change_types` 对应元素，`change_count +1`
- 若文件不存在：新建条目，`change_count = 1`

#### 6.3 写入校验

- 写入前检查文件是否为合法 JSON（防损坏）
- **校验文件头**：顶层必须存在 `service` 与 `schema_version`；缺失则**先补齐再写**（`service` 取 `{service}` 目录名，`schema_version` 取 `"1.0"`）。这两个键是后续「产物完整性门禁」与多服务归属判定的依据
- 追加记录后，验证 `records`/`versions` 数组长度增加 1
- 若写入失败，**不阻塞报告输出**，在控制台提示数据沉淀失败

