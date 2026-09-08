# 测试工程 Agent Skills

两个互补的代码变更分析技能，把「读 diff → 归类变更 → 评估风险 → 规划测试 → 沉淀数据」固化成 Agent 可执行的流程。

## 技能清单

| 技能 | 定位 | 是否需要脚本 |
|---|---|---|
| [`code-diff-analyzer`](./code-diff-analyzer/) | 代码变更影响分析：双格式 diff 解析、风险评级、回归测试范围、HTML 报告 | 9 个 Python 脚本（可选） |
| [`apex-diff-analyzer`](./apex-diff-analyzer/) | 增强版：量化风险评分（0-100）、JIT 缺陷预测、学术数据支撑 | 纯指令，零依赖 |
| [`bug-analysis`](./bug-analysis/) | Bug 列表 Excel 多维量化分析：返工率、修复周期、一次解决率、模块分布，直出测试报告素材 | 1 个 Python 脚本（pandas） |
| [`excel-testcase-18col`](./excel-testcase-18col/) | 企业 18 列标准测试用例 Excel 生成：基线驱动、步骤与预期 1:1 配对 | 2 个 Python 脚本（可选） |
| [`web-test-case-generator`](./web-test-case-generator/) | 网页自动生成测试用例：UI/功能/流程/异常/权限/兼容性 | 纯指令，零依赖 |

**组合使用**：code-diff-analyzer 分析变更 → excel-testcase-18col 生成正式用例 → web-test-case-generator 补页面级用例 → bug-analysis 沉淀缺陷数据，形成测试工程闭环。

**怎么选**：日常影响分析用基础版；需要量化评分或缺陷倾向预判时用增强版。两者输入格式完全一致，可平滑切换。

## 安装

安装单个技能：

```bash
npx skills add bin19860307-cpu/tester_skill --skill code-diff-analyzer
npx skills add bin19860307-cpu/tester_skill --skill apex-diff-analyzer
```

> 镜像仓库（GitLab）：https://gitlab.com/bin19860307/tester_skill — 技能内容完全一致；技能安装命令基于 GitHub，镜像仅作备份与国内访问加速。

或手动安装：把对应技能目录整个复制到你的 skills 目录。

| 客户端 | 路径 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |

## 支持平台

遵循 Anthropic 于 2025-12 发布的 Agent Skills 开放标准（[agentskills.io](https://agentskills.io)），在 Claude Code、Codex、Cursor、Gemini CLI、GitHub Copilot、VS Code 等约 40 款工具上通用，无需改写。

## 目录结构

```text
tester_skill/
├── code-diff-analyzer/
│   ├── SKILL.md
│   ├── scripts/
│   └── references/
├── apex-diff-analyzer/
│   ├── SKILL.md
│   └── references/
└── README.md
```

## 使用示例

```text
帮我分析这次 v1.2.24 → v1.2.25 的改动，输出影响范围和回归测试建议
```

```text
分析 tagdiff.txt，生成 HTML 变更报告
```

```text
@bug_list.xlsx 导入Bug数据，然后分析 diff-analytics
```

## 许可

MIT
