# apex-diff-analyzer

Apex Diff Analyzer — 巅峰代码变更影响分析技能。 在 code-diff-analyzer 基础上深度增强，集成量化风险评分模型（Phase 1）、JIT 缺陷预测洞察（Phase 2）和学术数据深度支撑（Phase 3）。 核心增强： - Phase 1 量化风险评分：基于 CHID 实践模型的 5 维度综合评分（0-100 分） - Phase 2 JIT 预测洞察：基于 CC2Vec/JITLine 研究的预测性分析 - Phase 3 学术数据支撑：Kamei et al. (2013)、Zhou et al. (2021)、SZZ基准数据等权威研究 触发场景：分析 git diff、评估 PR 影响范围、制定回归测试计划、CI/CD 变更分析、量化风险评估。 支持两种输入格式：①CI/CD原始输出（tagdiff.txt）②结构化Markdown报告（compare_vX_to_Y.md）。 支持区分「新增代码」和「变更代码」两类变更进行分别分析。

## 安装
方式一，命令行安装（支持 Claude Code / Codex / Cursor / Gemini CLI 等）：
```bash
npx skills add bin19860307-cpu/tester_skill --skill apex-diff-analyzer
```

方式二，手动安装：把整个 `apex-diff-analyzer/` 目录复制到你的 skills 目录：

| 客户端 | 路径 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |

## 它解决什么问题
发版前拿到一堆 diff，靠人眼看不出改动波及哪些模块、该测哪些范围。本技能把「读 diff → 归类变更 → 评估风险 → 规划测试 → 沉淀数据」固化成可执行流程，输出结构化影响分析报告与 HTML 报告。

## 快速开始
安装后，直接把 diff 内容或文件路径给 Agent：
```text
帮我分析这次 v1.2.24 → v1.2.25 的改动，输出影响范围和回归测试建议
```
```text
分析 tagdiff.txt，生成 HTML 变更报告
```
```text
@bug_list.xlsx 导入Bug数据，然后分析 diff-analytics
```

支持的输入格式：
- **格式 A**：CI/CD 原始输出（`tagdiff.txt`，含 `======== Commit 记录 =========` 分隔）
- **格式 B**：结构化 Markdown 报告（`compare_vX_to_Y.md`，含 `### 📄 文件名` 标题）

## 前置依赖
- Python 3.9+（仅在使用 `scripts/` 下的脚本时需要）
- 可选：pandas / openpyxl（Bug 数据导入与趋势分析脚本）

纯对话分析不需要任何依赖——只带 SKILL.md 也能完整跑通主流程。

## 参考资源
- `references/html-report-template.html`
- `references/output-examples.md`
- `references/prompt-template.md`

## 目录结构
```text
apex-diff-analyzer/
├── SKILL.md
├── references/
├── README.md
└── manifest.yaml
```

## 版本

当前 v1.0.0。

## 许可

MIT
