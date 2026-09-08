# web-test-case-generator

根据提供的网站页面自动生成测试用例。支持 UI 测试、功能测试、流程测试、异常测试、权限测试和兼容性测试。输出格式支持 Markdown 表格和 CSV。

## 安装
方式一，命令行安装（支持 Claude Code / Codex / Cursor / Gemini CLI 等）：
```bash
npx skills add <your-github-id>/<your-repo> --skill web-test-case-generator
```

方式二，手动安装：把整个 `web-test-case-generator/` 目录复制到你的 skills 目录：

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

## 目录结构
```text
web-test-case-generator/
├── SKILL.md
├── README.md
└── manifest.yaml
```

## 版本

当前 v1.0.0。

## 许可

MIT
