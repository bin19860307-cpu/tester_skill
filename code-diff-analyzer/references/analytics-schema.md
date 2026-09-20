# Diff Analytics — 数据文件 Schema 定义

> 版本：v1.0 | 更新：2026-05-27
> 存储路径：`{workspace}/.workbuddy/diff-analytics/{service}/`

---

## 1. service_metrics.json

服务级度量记录，每次版本分析后追加一条。

```json
{
  "service": "portal-backend",
  "schema_version": "1.0",
  "records": [
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
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `service` | string | ✅ | 服务名称，与目录名一致 |
| `schema_version` | string | ✅ | Schema 版本，当前 `1.0` |
| `records[]` | array | ✅ | 分析记录数组，按时间追加 |
| `records[].version_from` | string | ✅ | 源版本（旧版本） |
| `records[].version_to` | string | ✅ | 目标版本（新版本） |
| `records[].direction` | string | ✅ | 版本方向：`forward` / `rollback` / `unknown` |
| `records[].analysis_date` | string | ✅ | 分析日期，ISO 8601 格式 |
| `records[].metrics.files_changed` | number | ✅ | 变更文件数 |
| `records[].metrics.lines_added` | number | ✅ | 新增行数 |
| `records[].metrics.lines_removed` | number | ✅ | 删除行数 |
| `records[].metrics.high_risk` | number | ✅ | 高风险项数 |
| `records[].metrics.medium_risk` | number | ✅ | 中风险项数 |
| `records[].metrics.low_risk` | number | ✅ | 低风险项数 |
| `records[].metrics.risk_score` | number | ✅ | 综合风险评分（0-100）· **静态五维**，趋势唯一口径 |
| `records[].metrics.risk_score_mode` | string | ✅ | 固定 `"static"`；被写进 `"enhanced"` 即为口径污染 |
| `records[].metrics.risk_score_source` | string | ✅ | 血缘：`script:scoring.canonical_risk_score(静态5维)` |
| `records[].metrics.risk_score_enhanced` | number\|null | ❌ | 增强十维分（有历史度量时写入），**禁止参与趋势连线** |
| `records[].metrics.risk_score_legacy` | number | ❌ | 旧公式值，**仅留审计**，不得当作当前分使用 |
| `records[].modules` | array | ❌ | 模块级汇总 |
| `records[].detections` | object | ✅ | 五项专项检测命中结果 |

### risk_score 口径（2026-09-18 起）

`risk_score` 由 `scripts/scoring.py::canonical_risk_score()` **确定性产出**，不再由 LLM 手填：

```
metrics.risk_score            ← 静态 5 维确定性分（0-100），趋势唯一口径，跨版本可比
metrics.risk_score_enhanced   ← 增强 10 维分（有历史度量时才写），不可与上者混用
metrics.risk_score_legacy     ← 旧公式值 min(100, high*10 + medium*5 + low*1)，仅留档审计
```

> ⚠️ `min(100, high*10 + medium*5 + low*1)` 是**已弃用的旧公式**，其值只以
> `risk_score_legacy` 形式留档。任何文档、报告或 PPT 若把该公式当作 `risk_score` 的口径，
> 都属于过期口径。写盘后必须满足：`risk_score_mode == "static"`，且落盘值 == 用当前
> 评分代码重算的结果（容差 0.01）——由 `scripts/doctor.py` 的 D5 检查项机器校验。

---

## 2. version_chain.json

版本链路追踪，记录服务所有版本的父子关系。

```json
{
  "service": "portal-backend",
  "schema_version": "1.0",
  "versions": [
    { "version": "5.1.0.2", "date": "2026-04-28", "parent": "5.1.0.1" },
    { "version": "5.1.0.3", "date": "2026-05-19", "parent": "5.1.0.2" },
    { "version": "5.1.0.4", "date": "2026-05-21", "parent": "5.1.0.3" }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `versions[].version` | string | ✅ | 版本号 |
| `versions[].date` | string | ✅ | 分析日期 |
| `versions[].parent` | string | ✅ | 父版本号 |

### 去重规则

- 若 `version` 已存在，**跳过追加**（不覆盖）
- 若 `parent` 不在已有版本中，仍可正常追加（允许非连续导入）

---

## 3. file_history.json

文件级变更历史，追踪每个文件在哪些版本中被修改。

```json
{
  "service": "portal-backend",
  "schema_version": "1.0",
  "files": {
    "src/main/java/AuthController.java": {
      "change_count": 3,
      "appear_in": ["5.1.0.2→5.1.0.3", "5.1.0.3→5.1.0.4"],
      "risk_history": ["high", "high"],
      "change_types": ["modified", "modified"]
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | object | ✅ | 键为文件路径，值为变更记录 |
| `files[].change_count` | number | ✅ | 累计变更次数 |
| `files[].appear_in` | array | ✅ | 出现在哪些版本区间 |
| `files[].risk_history` | array | ✅ | 每次变更的风险等级 |
| `files[].change_types` | array | ✅ | 每次变更的类型（modified/added/deleted） |

### 更新规则

- 文件已存在：追加 `appear_in`、`risk_history`、`change_types` 元素，`change_count +1`
- 文件不存在：新建条目，`change_count = 1`

---

## 4. version_bugs.json（可选，手动导入）

Bug 数据记录，手动导入后自动触发映射引擎。

```json
{
  "service": "portal-backend",
  "schema_version": "1.0",
  "bugs": [
    {
      "bug_id": "BUG-2026-0042",
      "title": "OAuth2 回调地址校验失败",
      "severity": "high",
      "status": "fixed",
      "module": "auth",
      "found_in_version": "5.1.0.3",
      "fixed_in_version": "5.1.0.4",
      "found_date": "2026-05-20",
      "fixed_date": "2026-05-21",
      "related_files": ["AuthController.java", "OAuth2Config.java"],
      "related_commits": ["a3f2c1d"],
      "tags": ["regression", "security"]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bugs[].bug_id` | string | ✅ | Bug 唯一标识 |
| `bugs[].severity` | string | ✅ | critical / high / medium / low |
| `bugs[].found_in_version` | string | ✅ | 发现该 Bug 的版本号 |
| `bugs[].title` | string | ❌ | Bug 标题 |
| `bugs[].module` | string | ❌ | 所属模块 |
| `bugs[].fixed_in_version` | string | ❌ | 修复版本号 |
| `bugs[].status` | string | ❌ | open / fixed / closed / wontfix |
| `bugs[].found_date` | string | ❌ | 发现日期 |
| `bugs[].fixed_date` | string | ❌ | 修复日期 |
| `bugs[].related_files` | array | ❌ | 关联文件列表 |
| `bugs[].related_commits` | array | ❌ | 关联 Commit 列表 |
| `bugs[].tags` | array | ❌ | 标签 |

### 脚本扩展字段（由 `scripts/bug_correlate.py` 写入，兼容既有消费方）

| 字段 | 类型 | 说明 |
|------|------|------|
| `bugs[].severity_raw` | string | 严重程度原始文案（如 `一般`），便于回溯 |
| `bugs[].creator` | string | 创建人（来自 `创建人` 列） |
| `bugs[].resolver` | string | 解决者（来自 `解决者` 列） |
| `bugs[].found_date` | string | 发现日期（来自 `创建日期` 列，仅日期） |
| `bugs[].fixed_date` | string | 修复日期（来自 `解决日期` 列） |
| `bugs[].closed_date` | string | 关闭日期（来自 `关闭日期` 列） |
| `bugs[].bug_type` | string | Bug 类型（来自 `bug类型` 列） |
| `bugs[].activation` | string | 激活次数（来自 `激活次数` 列） |
| `bugs[].disposition` | string | 处置方式（来自 `处置方式` 列） |
| `bugs[].plan` | string | 方案（来自 `方案` 列） |
| `bugs[].detail` | string | 详细处理方式（来自 `详细处理方式` 列） |

> `source_xlsx` / `imported_at` 也会写在 `version_bugs.json` 根级，记录数据来源与导入时间。

### 去重规则

- 若 `bug_id` 已存在，**更新**该条记录（支持修正 Bug 状态）

---

## 5. cross_reference.json（可选，映射引擎自动生成）

Bug 与代码变更的交叉引用，由映射引擎自动生成和维护。

```json
{
  "service": "portal-backend",
  "schema_version": "1.0",
  "mappings": [
    {
      "version_range": "5.1.0.3→5.1.0.4",
      "bugs_found_in_version": ["BUG-2026-0042", "BUG-2026-0043"],
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
      ],
      "detection_precision": {
        "data_format_change": { "hit_with_bug": 1, "hit_total": 2 },
        "version_rollback": { "hit_with_bug": 0, "hit_total": 0 },
        "sensitive_info": { "hit_with_bug": 0, "hit_total": 0 },
        "test_sync_needed": { "hit_with_bug": 1, "hit_total": 1 },
        "circular_dependency": { "hit_with_bug": 0, "hit_total": 0 }
      }
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `mappings[].version_range` | string | 版本区间 |
| `mappings[].bugs_found_in_version` | array | 在该版本中发现的 Bug ID 列表 |
| `mappings[].bugs_fixed_in_version` | array | 在该版本中修复的 Bug ID 列表 |
| `mappings[].change_to_bug_ratio` | number | Bug/变更比 |
| `mappings[].high_risk_changes_with_bugs` | array | 有 Bug 关联的高风险变更 |
| `mappings[].commits_with_bugs` | array | 有 Bug 关联的 Commit |
| `mappings[].detection_precision` | object | 5 项检测的精度统计 |

### 更新规则

- 映射引擎每次运行时，**全量重建** `mappings` 数组（而非追加），确保数据一致性
- 若 `version_bugs.json` 被删除，同步删除 `cross_reference.json`

---

## 初始化骨架

新建服务目录时，各文件使用以下空骨架：

**service_metrics.json**：
```json
{
  "service": "{service_name}",
  "schema_version": "1.0",
  "records": []
}
```

**version_chain.json**：
```json
{
  "service": "{service_name}",
  "schema_version": "1.0",
  "versions": []
}
```

**file_history.json**：
```json
{
  "service": "{service_name}",
  "schema_version": "1.0",
  "files": {}
}
```

**version_bugs.json**（仅在用户导入 Bug 时创建）：
```json
{
  "service": "{service_name}",
  "schema_version": "1.0",
  "bugs": []
}
```

**cross_reference.json**（仅在映射引擎首次运行时创建）：
```json
{
  "service": "{service_name}",
  "schema_version": "1.0",
  "mappings": []
}
```
