# Diff Analytics — 目录初始化说明

> 存储根路径：`{workspace}/.workbuddy/diff-analytics/`

---

## 目录结构

```
{workspace}/.workbuddy/diff-analytics/
├── portal-backend/           ← 每个服务一个目录
│   ├── service_metrics.json  ← 自动写入
│   ├── version_chain.json    ← 自动写入
│   ├── file_history.json     ← 自动写入
│   ├── version_bugs.json    ← 手动导入（可选）
│   └── cross_reference.json ← 映射引擎生成（可选）
├── acme-frontend/
├── agent/
├── main-frontend/
└── ...
```

## 初始化时机

1. **Step 6 数据沉淀时**：若目标服务目录不存在，自动创建目录 + 3 个基础 JSON 骨架
2. **Bug 导入时**：若目标服务目录不存在，自动创建目录 + version_bugs.json
3. **手动初始化**：运行 `初始化 diff-analytics` 指令，批量创建所有已知服务

## 已知服务列表

以下服务已在历史分析中出现过，初始化时需预建：

| 服务名 | 首次分析日期 |
|--------|-------------|
| acme-frontend | 2026-04-14 |
| acme-frontend-v | 2026-04-24 |
| portal-backend | 2026-04-28 |
| main-frontend | 2026-04-29 |
| agent | 2026-05-19 |

## 初始化步骤

1. 检查 `{workspace}/.workbuddy/diff-analytics/` 是否存在，不存在则创建
2. 遍历已知服务列表，为每个服务创建目录
3. 为每个服务目录写入 3 个基础 JSON 骨架（metrics/chain/history）
4. 不创建 version_bugs.json 和 cross_reference.json（按需创建）

## 注意事项

- `version_bugs.json` 和 `cross_reference.json` 不在初始化时创建，仅在用户导入 Bug 数据时按需创建
- 所有 JSON 文件使用 UTF-8 编码，2 空格缩进
- 初始化后即可正常使用 Step 6 数据沉淀功能
