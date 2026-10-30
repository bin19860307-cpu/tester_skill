# Phase 3.5 覆盖率验证指南

> 适用于 test-pipeline-mvp Phase 3.5 阶段

---

## 覆盖率计算公式

```
节点覆盖率 = 已绑定测试点的节点数 / 流程图总节点数 × 100%
路径覆盖率 = 已覆盖完整路径数 / 流程图可达路径总数 × 100%
```

**评审通过门槛**：
- P0 节点覆盖率 = **100%**（强制，不通过则评审不通过）
- 全量节点覆盖率 ≥ **80%**

---

## 覆盖率报告模板

```markdown
## Phase 3.5 覆盖率验证报告

**生成时间**: 2026-XX-XX
**测试点总数**: X 条
**流程图总节点数**: X 个

### 节点覆盖汇总

| 流程节点 | 节点描述 | 优先级 | 覆盖测试点 | 覆盖状态 |
|---------|---------|------|----------|--------|
| CheckAdmin | 判断是否 admin | P0 | TP-F-071, TP-F-072 | ✅ 已覆盖 |
| AllPass | admin 直接通过 | P0 | TP-F-071 | ✅ 已覆盖 |
| Block | 余额不足拦截 | P0 | （无） | ❌ 未覆盖 |
| Done | 对话完成 | P0 | TP-F-021, TP-F-022 | ✅ 已覆盖 |

### 覆盖率结果

| 指标 | 数值 | 目标 | 是否通过 |
|------|------|------|--------|
| P0 节点覆盖率 | X% | 100% | ✅/❌ |
| 全量节点覆盖率 | X% | ≥80% | ✅/❌ |

### 未覆盖节点（需补充用例）

| 节点 ID | 节点描述 | 优先级 | 建议补充方向 |
|--------|---------|------|------------|
| Block | 余额不足拦截 | P0 | 测试所有 Token 耗尽后系统拦截行为 |

### 冗余路径（可考虑合并）

| 覆盖路径 | 测试点 | 合并建议 |
|---------|------|--------|
| P1→Done | TP-F-021, TP-F-025 | 两条用例覆盖完全相同路径，可合并 |

### 验证结论

✅ 通过（可进入 Phase 4 评审）
或
❌ 不通过：P0 节点 Block 未覆盖，请补充测试点后重新验证
```

---

## Python 覆盖率分析脚本

> 用于从 Excel 测试用例文件（18+1 列格式）中自动统计节点覆盖情况

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3.5 节点覆盖率分析脚本
适用于 excel-testcase-18col 格式（第 19 列为覆盖路径）
"""
import openpyxl
from collections import defaultdict


def analyze_coverage(excel_path, flow_nodes, p0_nodes=None):
    """
    从 Excel 测试用例文件分析流程节点覆盖率

    参数:
        excel_path : str  - Excel 文件路径
        flow_nodes : list - 流程图全部节点 ID 列表
        p0_nodes   : list - P0 优先级节点 ID 列表（默认与 flow_nodes 相同）

    返回:
        dict: 覆盖报告
    """
    if p0_nodes is None:
        p0_nodes = flow_nodes

    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active

    coverage = defaultdict(list)   # 节点 -> [测试用例 ID]

    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] != "测试用例":       # 跳过套件行
            continue
        case_id   = row[1]            # 第 2 列：编号
        path_info = row[18] if len(row) > 18 else None   # 第 19 列：覆盖路径

        if path_info:
            nodes_covered = [n.strip() for n in str(path_info).split("→")]
            for node in nodes_covered:
                if node:
                    coverage[node].append(case_id)

    # 计算全量覆盖率
    covered_all = {n for n in flow_nodes if n in coverage}
    rate_all = len(covered_all) / len(flow_nodes) * 100 if flow_nodes else 0

    # 计算 P0 覆盖率
    covered_p0 = {n for n in p0_nodes if n in coverage}
    rate_p0 = len(covered_p0) / len(p0_nodes) * 100 if p0_nodes else 0

    # 未覆盖节点
    uncovered = [n for n in flow_nodes if n not in coverage]
    uncovered_p0 = [n for n in p0_nodes if n not in coverage]

    # 冗余路径检测（同一路径被 3 条以上用例覆盖）
    redundant = {node: cases for node, cases in coverage.items() if len(cases) >= 3}

    print("=" * 50)
    print(f"节点覆盖率（全量）: {rate_all:.1f}%  ({len(covered_all)}/{len(flow_nodes)})")
    print(f"节点覆盖率（P0）  : {rate_p0:.1f}%  ({len(covered_p0)}/{len(p0_nodes)})")
    print()
    if uncovered_p0:
        print(f"⚠️  P0 未覆盖节点（必须补充）: {uncovered_p0}")
    if uncovered:
        print(f"📋 未覆盖节点（建议补充）  : {uncovered}")
    if redundant:
        print(f"🔁 高冗余节点（≥3 条用例）: {list(redundant.keys())}")

    passed_p0  = rate_p0 >= 100
    passed_all = rate_all >= 80
    print()
    print("验证结论:", "✅ 通过" if (passed_p0 and passed_all) else "❌ 不通过")
    print("=" * 50)

    return {
        "rate_all": rate_all,
        "rate_p0": rate_p0,
        "coverage": dict(coverage),
        "uncovered": uncovered,
        "uncovered_p0": uncovered_p0,
        "passed": passed_p0 and passed_all,
    }


# =====================
#  使用示例（权益控制）
# =====================
if __name__ == "__main__":
    # 流程图全节点（来自 Phase 1.5 节点清单）
    ALL_NODES = [
        "CheckAdmin", "AllPass",
        "CheckTeacher",
        "T1", "T2", "T3", "S1",
        "P1", "P2", "P3",
        "Block", "Done",
    ]

    # P0 节点（对业务影响最大，必须 100% 覆盖）
    P0_NODES = [
        "CheckAdmin", "AllPass",
        "CheckTeacher", "T1", "S1",
        "P1", "Block", "Done",
    ]

    result = analyze_coverage(
        excel_path=r"C:\替换为实际路径\权益控制_测试用例_v1.0.xlsx",
        flow_nodes=ALL_NODES,
        p0_nodes=P0_NODES,
    )
```

---

## 手动核查方法（无脚本时）

若暂时没有运行 Python 脚本的条件，可手动执行：

1. 打开 Excel 测试用例文件
2. 新建一列「节点覆盖汇总」工作表
3. 逐行读取「覆盖路径」列，统计每个节点 ID 出现次数
4. 对照节点清单，标记「未覆盖」节点（次数 = 0）
5. 填写覆盖率报告模板

---

## 注意事项

> **100% 节点覆盖率 ≠ 100% 业务场景覆盖**
>
> 以下场景仍需测试工程师基于经验补充：
> - **边界条件**：Token 数量恰好为 0、为 1、为最大值时的行为
> - **并发场景**：多用户同时消耗同一 Token 池
> - **异常状态**：扣减失败回滚、网络中断中途等
> - **时序问题**：余额实时刷新 vs 缓存延迟

流程覆盖率是**必要条件**，不是充分条件。
