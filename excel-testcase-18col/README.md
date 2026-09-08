# excel-testcase-18col

生成符合企业18列标准格式的测试用例Excel文件（参考班级管理测试用例_v2.xlsx模板）。 触发词：18列格式、企业模板、用例Excel、生成测试用例Excel、班级管理模板、按套件生成用例。 进阶能力：基线驱动（文案/链接抽单一数据源）+ 步骤与预期 1:1 编号配对（含 "-" 无需验证标记）+ 三表输出（测试用例/文案基线/链接基线）。

## 安装
方式一，命令行安装（支持 Claude Code / Codex / Cursor / Gemini CLI 等）：
```bash
npx skills add <your-github-id>/<your-repo> --skill excel-testcase-18col
```

方式二，手动安装：把整个 `excel-testcase-18col/` 目录复制到你的 skills 目录：

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

## 内置脚本
| 脚本 | 用途 |
|---|---|
| `scripts/gen_baseline_template.py` | 基线驱动 + 步骤预期 1:1 配对 — — 测试用例生成模板（excel-testcase-18col v1.4） |
| `scripts/gen_testcases_template.py` | 18列企业标准测试用例 Excel 生成脚本模板 |

## 目录结构
```text
excel-testcase-18col/
├── SKILL.md
├── scripts/
├── README.md
└── manifest.yaml
```

## 版本

当前 v1.0.0。

## 许可

MIT
