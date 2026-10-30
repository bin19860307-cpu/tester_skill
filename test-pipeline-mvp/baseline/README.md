# baseline/ — 版本基线快照（示例版）

本目录是**版本基线**的落地位置：冻结「某一版本的 Skill + 模型 + 评测结果」，作为下一次改动的对照基准。

> ⚠️ **公开版说明**：本目录内的数据均为**通用脱敏示例**（虚构的「用户管理」模块，8 条首跑用例 / 8 条封版用例），
> 不含任何真实业务内容。它的作用是让你**开箱就能跑通评测流程**，并看清各个文件的 schema。
> 建立你自己的基线时，把下面的文件整体替换为真实结果即可。

## 文件说明

| 文件 | 含义 |
|---|---|
| `eval-result.json` | 三率评测结果（由 `scripts/eval_metrics.py` 生成） |
| `skill-version.json` | 基线冻结时的 Skill 版本与关键文件清单 |
| `model-version.json` | 基线冻结时使用的模型 / Agent 及版本（换模型后三率不可直接对比） |
| `demo/first-run.csv` | 示例：AI 首跑生成用例（含典型首跑瑕疵） |
| `demo/final.csv` | 示例：人工评审封版用例（标准答案） |

> 示例数据用 **CSV**（纯文本）而非 xlsx：一是任何平台/仓库都接受文本文件，二是读 CSV 走 Python 标准库、**不需要装 openpyxl**，装完即可验证链路。你自己的真实数据仍可用 xlsx，脚本同时支持两种格式。

## 立即验证（三条命令）

```bash
cd test-pipeline-mvp

# 1. 用示例数据重算三率，对比现有 eval-result.json
python scripts/eval_metrics.py \
  --first baseline/demo/first-run.csv \
  --final baseline/demo/final.csv

# 2. 覆盖写入（确认无误后再执行）
python scripts/eval_metrics.py \
  --first baseline/demo/first-run.csv \
  --final baseline/demo/final.csv \
  --out baseline/eval-result.json

# 3. 查看结果
cat baseline/eval-result.json
```

预期输出：留存 2（25.0%）/ 修改 5（轻改 2、重改 3）/ 删除 1（12.5%）/ 封版新增 1（缺口率 12.5%）。

## 建立你自己的基线（4 步）

1. **准备首跑与封版**：流水线首跑产出 `first-run.xlsx`，人工评审确认后的封版产出 `final.xlsx`
2. **算三率**：`python scripts/eval_metrics.py --first ... --final ... --out baseline/eval-result.json`
3. **写版本信息**：把 `skill-version.json`、`model-version.json` 替换为真实版本与模型
4. **记 CHANGELOG**：在 `../CHANGELOG.md` 追加一条「改动-效果对照」，写明本轮改动与三率变化

> **冻结条件**：封版前用例不再变动 + 测试人员最终比对确认后，才冻结基线。冻结后再改 Skill，三率变化才有归因意义。

## 指标口径（简版）

以首跑用例总数 N 为分母：

- **留存率** = 封版未被改、未被删 / N（≈ 有效率，含漏检风险）
- **修改率** = 被封版改动的 / N（细分轻改 / 重改，阈值默认 0.5）
- **删除率** = 被封版删除的 / N
- **缺口率** = 封版新增 / 封版总数（AI 漏生成的覆盖盲区）

详见 `../eval/README.md`。
