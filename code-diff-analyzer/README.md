# code-diff-analyzer

代码变更影响分析技能。当用户提供 Git diff、代码变更记录或版本对比内容， 需要分析变更影响范围、评估风险等级、规划测试范围时，使用此 Skill。 触发场景包括：分析 git diff 输出、评估 PR 影响范围、制定回归测试计划、 CI/CD 流水线中的变更分析、tagdiff.txt 分析、compare_vX_to_Y.md 分析等。 支持两种输入格式：①CI/CD原始输出（tagdiff.txt）②结构化Markdown报告（compare_vX_to_Y.md）。 支持区分「新增代码」和「变更代码」两类变更进行分别分析，并可自动生成HTML格式的变更报告。

## 安装
方式一，命令行安装（支持 Claude Code / Codex / Cursor / Gemini CLI 等）：
```bash
npx skills add <your-github-id>/<your-repo> --skill code-diff-analyzer
```

方式二，手动安装：把整个 `code-diff-analyzer/` 目录复制到你的 skills 目录：

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

```text
# Code Diff Analyzer 流水线依赖
# 说明：bug_correlate.py 读 TAPD Bug Excel 需 openpyxl；
#       bug_trend / gen_combined_report / gen_p1_cases / pipeline_wrapper 仅用标准库。
# Phase 4 若嵌入 LLM 语义分析，再追加对应 SDK（如 openai / dashscope）。
openpyxl>=3.1.0
```

纯对话分析不需要任何依赖——只带 SKILL.md 也能完整跑通主流程。

## 内置脚本
| 脚本 | 用途 |
|---|---|
| `scripts/bug_correlate.py` | Code Diff Analyzer · Flow A + Flow B 固化脚本 |
| `scripts/bug_trend.py` | Code Diff Analyzer · Flow C.2 版本 Bug 趋势统计（固化脚本） |
| `scripts/doctor.py` | diff — analytics 一键体检 / 修复 |
| `scripts/gen_bug_predict.py` | 把「Bug 预测（缺陷倾向预判）」维度注入变更影响分析报告（幂等）。 |
| `scripts/gen_combined_report.py` | Code Diff Analyzer · 综合比对分析报告（多服务） |
| `scripts/gen_midscene_yaml.py` | — |
| `scripts/gen_p1_cases.py` | 把结构化 P1 用例预测注入单服务/综合报告（幂等）。 |
| `scripts/gen_quant_jit.py` | 把量化风险评分 + JIT 缺陷预测 注入报告（幂等）。apex 能力整合。 |
| `scripts/pack_reports.py` | 把本轮生成的 code — diff 报告打成「结构保真」的可分享 zip。 |
| `scripts/pipeline_wrapper.py` | Code Diff Analyzer 流水线统一入口（Phase 1 容器化） |
| `scripts/quant_jit_risk.py` | 量化风险评分 + JIT 缺陷预测 计算引擎（apex — diff-analyzer 能力整合版） |
| `scripts/scoring.py` | Code Diff Analyzer · 统一口径模块（单一真源） |
| `scripts/sync_analytics.py` | 数据沉淀确定性重建 + 完整性自检 |
| `scripts/verify_precision.py` | 用真实命中率校准评分权重（把「规则引擎」升级为「项目校准模型」） |

## 参考资源
- `references/analytics-schema.md`
- `references/changelog.md`
- `references/html-report-template.html`
- `references/init-analytics.md`
- `references/output-examples.md`
- `references/prompt-template.md`
- `references/quant-jit-spec.md`

## 目录结构
```text
code-diff-analyzer/
├── SKILL.md
├── scripts/
├── references/
├── README.md
└── manifest.yaml
```

## 版本

当前 v1.1.1。

## 许可

MIT
