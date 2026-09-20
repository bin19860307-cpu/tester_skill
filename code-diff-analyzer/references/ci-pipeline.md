# CI / 容器化流水线（pipeline_wrapper）

> 本文件是 `code-diff-analyzer` 的**细则文档**，普通 diff 分析无需加载。
> 仅在需要对应细节时按需读取；正文由 `SKILL.md` 对应小节外迁而来，保持原文。

---


## CI / 容器化流水线

## CI / 容器化流水线（pipeline_wrapper）

> **现状（2026-09-18 核实）**：编排脚本与容器镜像**已就绪**，但**尚未接入真实 CI 系统**。当前链路是**半自动**：人跑上游 `tagdiff.sh` 产 `tagdiff.txt` → 交给本技能做语义分析 → 产物落盘 → 再由 `pipeline_wrapper.py` 消费出报告。真实 Jenkins / GitLab CI 里目前**没有任何服务于 code-diff-analyzer 的流水线定义**（无 Jenkinsfile / `.gitlab-ci.yml` / Shared Library step）。

### 定位：LLM 前置，流水线只做确定性执行

Step 1-7 的语义分析（格式识别 / 变更分类 / 模块依赖 / 风险评分）由 LLM Agent 在 PR 前置阶段完成，产物 `service_metrics.json` 落盘到 `.workbuddy/diff-analytics/{service}/`。`pipeline_wrapper.py` **只消费**这些结果，不在流水线内做 LLM 推理——避免发布链路被 AI 延迟 / 成本拖累。

### 编排的 4 个脚本

`scripts/` 下包含多个 Python 工具；wrapper **只编排其中 4 个**：

| 脚本 | 职责 | 前置依赖 |
|---|---|---|
| `bug_correlate.py` | Bug 关联（Flow A+B，全量重建 `version_bugs.json` / `cross_reference.json`） | `--xlsx` |
| `bug_trend.py` | 版本 Bug 趋势（内联 SVG，无 CDN） | `version_bugs.json` 已就绪 |
| `gen_combined_report.py` | 综合比对分析报告（多服务聚合） | ≥2 个服务 |
| `gen_p1_cases.py` | P1 用例注入（幂等） | `--p1-data-file` |

> `gen_bug_predict.py` / `gen_quant_jit.py` / `quant_jit_risk.py` / `gen_midscene_yaml.py` **不在 wrapper 范围内**，仍由技能工作流按 Step 8.5 / Step 9 单独调用。

### 分阶段执行（--stage）

```bash
# analyze：准备工作区 + 可选 git 浅克隆 + 写运行元数据 + 交接校验（严格把关）
python scripts/pipeline_wrapper.py --stage analyze --service portal-backend \
    --repo-url git@xxx/portal-backend.git --target-tag v1.1

# score：Bug 关联 + 趋势
python scripts/pipeline_wrapper.py --stage score --service portal-backend --xlsx bug.xlsx

# report：多服务综合报告 + P1 注入
python scripts/pipeline_wrapper.py --stage report --services a b c --p1-data-file p1.json

# all：analyze → score → report（默认）
python scripts/pipeline_wrapper.py --stage all --service portal-backend --xlsx bug.xlsx
```

### 退出码约定（CI 门禁依赖）

| 退出码 | 含义 | CI 处置 |
|---|---|---|
| `0` | 阶段成功 | 放行 |
| `1` | 参数错误（缺 `--service`、`--xlsx` 不存在等） | 失败，检查流水线配置 |
| `2` | **analyze 交接未就绪**（`service_metrics.json` 缺失） | 失败，提示补做前置语义分析 |
| 其他非零 | 子脚本自身退出码（透传） | 失败，看子脚本日志 |

`2` 是 analyze 的专用退出码，让 CI 能区分「前置语义分析没做」与「脚本本身报错」，避免笼统失败。

### 豁免通道

手动 / 开发场景产物尚未生成时，加 `--allow-missing-metrics` 跳过阻断（降级为警告 + 退出码 0）：

```bash
python scripts/pipeline_wrapper.py --stage all --service portal-backend --allow-missing-metrics
```

### 容器化

`scripts/Dockerfile`：`python:3.11-slim` 基础镜像，仅装 `openpyxl`，`ENTRYPOINT` 指向 `pipeline_wrapper.py`。工作区通过 `--workspace` 或环境变量 `$WORKSPACE`（Jenkins 注入）解析，覆盖子脚本里硬编码的 `d:/workbuddy/测试日常`，使容器内也能正确落盘。

```bash
docker build -t code-diff-analyzer scripts/
docker run --rm -v /path/to/workspace:/workspace -e WORKSPACE=/workspace \
    code-diff-analyzer --stage all --service portal-backend --xlsx /workspace/bug.xlsx
```

### 与上游 `tagdiff.sh` 的关系

`tagdiff.sh`（Jenkins 上游脚本，2026-09-10 起为 v2）负责产 `tagdiff.txt`（含变更概览 / 下一层模块分布 / 文件级差异统计），本技能负责**解析与分析**——二者是**上下游**关系，不是同一条流水线。`tagdiff.txt` 解析锚点见「Step 1.1 格式识别 · 格式 A v2」。

### 待补

- 真实 CI 系统里的 `Jenkinsfile` / Shared Library step **尚未编写**；接入后即可把 `--stage analyze` 作为质量门禁的前置步骤。

