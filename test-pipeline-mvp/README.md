# test-pipeline-mvp — 测试工程全流程流水线

从一句话需求到可交付测试用例集：9 个主阶段（Phase 0–8）+ 4 个子阶段（1.5/2.5/3.5/5.5）的自动执行与人工卡点协同流水线。整合了团队协作模式与「PDF 图片提取、三层交叉验证」能力。

**核心设计原则**：

1. **补全优先** — 需求不完整时先追问补全，不跳步骤
2. **交互感知** — 每个阶段主动识别跨模块交互点
3. **人工卡点** — 评审阶段强制等待用户确认，不自动跳过
4. **可追溯** — 每条测试用例都能回溯到原始需求点

> 📖 **第一次用？先看 [`USAGE.md`](./USAGE.md)** —— 从安装、五分钟跑通第一个案例、全流程阶段说明、典型场景到评测基线的完整操作路径。

## 流水线全貌

```
输入：一句话需求 / 需求文档（PDF/Word/Markdown）
  ↓
Phase 0:   测试范围确认          ← 三区域划分（核心/交互/排除）
  ↓
Phase 1:   需求分析 & 补全      ← 追问缺失信息，识别模块边界，规则提取建模
  ↓ 用户确认
Phase 1.5: 流程图绘制           ← Mermaid 业务流程图 + 节点清单
  ↓ 用户确认
Phase 2:   需求拆解              ← 用户故事 + 模块交互矩阵
  ↓ 用户确认
Phase 3:   测试点生成            ← 七维度覆盖 + 跨模块交互点 + 路径绑定
  ↓ 用户确认
Phase 3.5: 覆盖率验证           ← 节点覆盖率计算 + 缺口识别
  ↓ 用户确认/补充
Phase 4:   测试点评审            ← 覆盖度检查 + 优先级打分
  ↓ 用户确认/修改
Phase 5:   测试用例生成          ← 标准用例结构 + 视觉内容处理
  ↓ 用户确认
Phase 6:   测试用例评审          ← 自动评审 + 三层交叉验证
  ↓ 用户确认/修改
Phase 7:   测试用例修改          ← 按评审意见逐条修订
  ↓ 用户确认
Phase 8:   交付确认 & 导出       ← Excel 导出 + 产物清单
```

## 快速开始

安装后，直接对 Agent 说：

```text
用测试流水线分析这个需求：管理员可以创建班级，填写班级名称、学段、年级，保存后出现在班级列表
```

```text
@需求文档.pdf 跑一下测试流水线，最后导出 Excel
```

需求变更后增量补充：

```text
需求变了：班级名称改为必填且限 20 字。基于已有测试点做增量补充，不重跑全流程
```

## 安装

方式一，命令行安装（支持 Claude Code / Codex / Cursor / Gemini CLI 等）：

```bash
npx skills add bin19860307-cpu/tester_skill --skill test-pipeline-mvp
```

方式二，手动安装：把整个 `test-pipeline-mvp/` 目录复制到你的 skills 目录：

| 客户端 | 路径 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |

## 评测体系（可选）

内置一套用例生成质量的量化评测方法（`eval/`）：

- **固定基准测试集**：选 8–12 条最核心、稳定的正向主流程需求作为基准
- **三率指标**：留存率（≈有效率）、修改率、删除率，以首跑生成用例总数为分母
- **基线门禁**：封版前用例不再变动 + 测试人员确认后，才冻结基线快照
- **改动-效果对照**：每次规则/提示词变更后在固定基准集全量重跑，量化改动是否有效

开箱验证（自带通用示例数据，无需准备任何材料）：

```bash
python scripts/eval_metrics.py --first baseline/demo/first-run.csv --final baseline/demo/final.csv
```

> 预期：留存 25.0% / 修改 62.5%（轻改 2、重改 3）/ 删除 12.5% / 缺口 12.5%。
> 目录与指标说明见 [`baseline/README.md`](./baseline/README.md) 与 [`eval/README.md`](./eval/README.md)，完整步骤见 [`USAGE.md`](./USAGE.md) 第 5 节。

## 内置脚本

| 脚本 | 用途 |
|---|---|
| `scripts/eval_metrics.py` | 计算首跑→封版的留存率/修改率/删除率三率指标 |

## 参考资源

- `references/phase1-prompt.md` — Phase 1 需求分析提示词
- `references/phase1_5-flowchart-guide.md` — 流程图绘制指南
- `references/phase2-interaction-modules.md` — 跨模块交互识别
- `references/phase3_5-coverage-analysis.md` — 覆盖率验证方法
- `references/pipeline-state-template.md` — 流水线状态模板

## 目录结构

```text
test-pipeline-mvp/
├── SKILL.md          # 唯一执行规则基线
├── USAGE.md          # 详细使用说明（安装 → 上手 → 全流程 → 评测）
├── CHANGELOG.md      # 评测改动-效果对照（模板）
├── eval/             # 评测体系方法说明
├── baseline/         # 版本基线快照 + 通用示例数据
├── references/       # 各阶段参考文档
├── scripts/          # 评测指标脚本
├── README.md
├── manifest.yaml
└── LICENSE
```

## 版本

当前 v2.7.0。

## 许可

MIT
