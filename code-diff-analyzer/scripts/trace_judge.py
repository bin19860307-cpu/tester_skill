#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trace_judge.py — Agent Trace 四级判断层（缺口②，2026-09-30）

背景（2026-09-23 学习《Jev 与判断层》后的落地）：
  Langfuse 等观测平台只回答「发生了什么」（trace 观测层），不回答「这个 trace
  要不要人来看」。几十条 trace 无人可逐条审查 —— 需要一个**快速判断层**：
  确定性规则先把绝大多数 trace 分流成四级，只有「需人工 / 高风险」才升级给真人。

  这是「规则负责确定性 / 决策模型负责判断 / LLM 负责复杂推理 / 人工负责最终兜底」
  四层分工里的第一层：纯规则、零 LLM 调用、输出结构化结论、完全可复现。

四级定义（severity 从低到高，取 trace 命中的最高级）：
  normal        正常      — 无任何信号命中
  minor         轻微异常  — 有信号但可自愈（慢、略超 Token、评分轻微偏离）
  needs_review  需人工    — 明确失败的环节需要人判断（报错、空产出、评分背离）
  critical      高风险    — 升级处理（连锁失败、敏感面触碰、多信号叠加）

输入（JSON 文件，数组或 {"traces": [...]}）—— 每条 trace 常用字段：
  {
    "trace_id": "req-001",
    "duration_ms": 12340,           # 总时长
    "error": false,                 # 是否报错（或 "error_message": "..."）
    "error_count": 0,               # 或错误次数（多 span 聚合）
    "total_tokens": 1820,
    "tool_calls": 3,                # 工具/子调用次数
    "output_empty": false,          # 产出为空（无答案/无评分）
    "score": 0.82,                  # 可选：评分类输出
    "score_expected": 0.80,         # 可选：预期/基线评分（偏离>0.15 触发）
    "consecutive_errors": 0,        # 可选：连续失败次数（会话级聚合）
    "sensitive": false              # 可选：触碰敏感面（权限/支付/数据导出）
  }
字段全部可选 —— 缺失的维度不参与判定（不臆造信号）。

用法：
    python scripts/trace_judge.py --in traces.json
    python scripts/trace_judge.py --in traces.json --out judgment.json --md report.md
    python scripts/trace_judge.py --in traces.json --threshold-p95 30000

输出：逐条 judgment + 升级清单（needs_review/critical）+ 汇总分布。
判定规则版本号 RULES_VERSION 写进产物；规则一改 +1。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # 统一友好错误层

# 判定规则版本号：规则一改就 +1，写进产物便于跨版本比对
RULES_VERSION = "1.0"

SEVERITY_ORDER = ["normal", "minor", "needs_review", "critical"]
SEVERITY_LABEL = {
    "normal": "🟢 正常", "minor": "🟡 轻微异常",
    "needs_review": "🟠 需人工", "critical": "🔴 高风险",
}

# ---- 阈值（单处定义；报告与判定共用，避免两套口径）----
DEFAULT_SLOW_MS = 20000          # 单条 trace 慢：>20s
DEFAULT_P95_MS = 60000           # 批次 p95 慢：>60s（可用 --threshold-p95 覆盖）
DEFAULT_TOKEN_CAP = 4000         # Token 超用：>4k（轻微），>12k（需人工）
TOKEN_HARD_CAP = 12000
SCORE_DEVIATION = 0.15           # 评分偏离基线 ±0.15 → 需人工
CONSECUTIVE_ERRORS = 3           # 连续失败 ≥3 → 高风险
MANY_SIGNALS = 3                 # 单条命中 ≥3 个轻微信号 → 升级需人工
TOOL_CALL_STORM = 20             # 工具调用次数异常（疑似循环）


def _num(t, key):
    """容错取数值：缺失/非数值返回 None（该维度不参与判定）。"""
    v = (t or {}).get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _truthy(t, key):
    v = (t or {}).get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return bool(v.strip())          # error_message 非空字符串视为真
    return False


def judge_trace(t, slow_ms=DEFAULT_SLOW_MS, p95_ms=DEFAULT_P95_MS):
    """对单条 trace 做确定性四级判定。

    返回 {"trace_id", "severity", "signals": [...], "action": "..."}。
    signals 里每条都是「可读规则名 + 实测值」，供人复核时直接定位。
    """
    signals_minor, signals_major = [], []

    dur = _num(t, "duration_ms")
    tokens = _num(t, "total_tokens")
    score = _num(t, "score")
    expected = _num(t, "score_expected")
    tool_calls = _num(t, "tool_calls")
    err_cnt = _num(t, "error_count")
    consec = _num(t, "consecutive_errors")

    has_error = _truthy(t, "error") or _truthy(t, "error_message") \
        or (err_cnt is not None and err_cnt > 0)
    output_empty = _truthy(t, "output_empty")
    sensitive = _truthy(t, "sensitive")

    # ---- 高风险信号（任一即 critical）----
    if consec is not None and consec >= CONSECUTIVE_ERRORS:
        signals_major.append("连续失败 %d 次（≥%d，疑似系统性故障）"
                             % (int(consec), CONSECUTIVE_ERRORS))
    if has_error and sensitive:
        signals_major.append("敏感面（权限/支付/导出）上发生错误")
    if has_error and dur is not None and dur >= p95_ms:
        signals_major.append("错误且耗时 %.0fms 超批次 p95 阈值 %dms（慢+错，排查成本最高）"
                             % (dur, p95_ms))
    if tool_calls is not None and tool_calls >= TOOL_CALL_STORM:
        signals_major.append("工具调用 %d 次（≥%d，疑似循环调用）"
                             % (int(tool_calls), TOOL_CALL_STORM))

    # ---- 需人工信号（任一即 needs_review）----
    if has_error:
        msg = t.get("error_message")
        signals_major.append("执行出错%s" % ("：%s" % msg if msg else ""))
    if output_empty:
        signals_major.append("产出为空（无答案/无评分，链路可能静默失败）")
    if score is not None and expected is not None \
            and round(abs(score - expected), 6) > SCORE_DEVIATION:
        signals_major.append("评分 %.2f 偏离基线 %.2f（>%s）"
                             % (score, expected, SCORE_DEVIATION))
    if tokens is not None and tokens > TOKEN_HARD_CAP:
        signals_minor.append("Token 用量 %d 超硬上限 %d" % (int(tokens), TOKEN_HARD_CAP))
        signals_major.append("Token 超硬上限（成本异常）")

    # ---- 轻微异常信号（可自愈，只记录）----
    if dur is not None and dur > slow_ms:
        signals_minor.append("耗时 %.0fms 超 %dms" % (dur, slow_ms))
    if tokens is not None and TOKEN_HARD_CAP >= tokens > DEFAULT_TOKEN_CAP:
        signals_minor.append("Token 用量 %d 超 %d（轻微）" % (int(tokens), DEFAULT_TOKEN_CAP))

    # ---- 汇级 ----
    if signals_major:
        severity = "critical" if any("系统性" in s or "敏感面" in s or "循环调用" in s
                                     or "慢+错" in s for s in signals_major) else "needs_review"
    elif len(signals_minor) >= MANY_SIGNALS:
        severity = "needs_review"
        signals_major.append("轻微信号叠加 %d 项（≥%d，升级复核）"
                             % (len(signals_minor), MANY_SIGNALS))
    elif signals_minor:
        severity = "minor"
    else:
        severity = "normal"

    action = {
        "normal": "无需处理，保持观测采样",
        "minor": "不升级，纳入趋势观察（周报维度）",
        "needs_review": "人工复核该条 trace，确认失败环节后归因",
        "critical": "立即升级：暂停同类批量任务，人工介入排查",
    }[severity]

    return {
        "trace_id": t.get("trace_id") or t.get("id") or "(unknown)",
        "severity": severity,
        "signals": signals_major + signals_minor,
        "action": action,
    }


def _percentile(sorted_vals, p):
    """线性插值 p95；空列表返回 None。"""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def judge_batch(traces, slow_ms=DEFAULT_SLOW_MS, p95_ms=DEFAULT_P95_MS):
    """批量判定 + 汇总。p95 阈值可由数据自适应（取批次内 p95 与配置的较大者）。"""
    durs = sorted(v for v in (_num(t, "duration_ms") for t in traces) if v is not None)
    batch_p95 = _percentile(durs, 0.95)
    eff_p95_ms = max(p95_ms, int(batch_p95)) if batch_p95 else p95_ms

    results = [judge_trace(t, slow_ms=slow_ms, p95_ms=eff_p95_ms) for t in traces]
    dist = {s: 0 for s in SEVERITY_ORDER}
    for r in results:
        dist[r["severity"]] += 1
    escalations = [r for r in results if r["severity"] in ("needs_review", "critical")]

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rules_version": RULES_VERSION,
        "thresholds": {"slow_ms": slow_ms, "p95_ms": eff_p95_ms,
                       "batch_p95_actual": int(batch_p95) if batch_p95 else None,
                       "token_cap": DEFAULT_TOKEN_CAP, "token_hard_cap": TOKEN_HARD_CAP,
                       "score_deviation": SCORE_DEVIATION},
        "total": len(results),
        "distribution": dist,
        "escalations": [r["trace_id"] for r in escalations],
        "judgments": results,
    }


def render_md(report):
    """人类可读 Markdown 摘要（升级清单优先）。"""
    L = []
    L.append("# Agent Trace 四级判断报告")
    L.append("")
    L.append(f"> 生成时间：{report['generated_at']}  ")
    L.append(f"> 规则版本：{report['rules_version']}  ")
    L.append(f"> 阈值：慢 >{report['thresholds']['slow_ms']}ms · p95 >{report['thresholds']['p95_ms']}ms · "
             f"Token >{report['thresholds']['token_cap']}（硬上限 {report['thresholds']['token_hard_cap']}）· "
             f"评分偏离 >{report['thresholds']['score_deviation']}")
    L.append("")
    L.append("## 分布")
    L.append("")
    L.append("| 级别 | 条数 | 占比 |")
    L.append("|---|---|---|")
    total = max(report["total"], 1)
    for s in SEVERITY_ORDER:
        n = report["distribution"][s]
        L.append(f"| {SEVERITY_LABEL[s]} | {n} | {n / total:.0%} |")
    L.append("")
    L.append(f"**升级清单（{len(report['escalations'])} 条）**："
             + (", ".join(report["escalations"]) if report["escalations"] else "无 🎉"))
    L.append("")
    flagged = [j for j in report["judgments"] if j["severity"] != "normal"]
    if flagged:
        L.append("## 异常明细")
        L.append("")
        L.append("| Trace | 级别 | 信号 | 建议动作 |")
        L.append("|---|---|---|---|")
        for j in flagged:
            L.append(f"| {j['trace_id']} | {SEVERITY_LABEL[j['severity']]} | "
                     f"{'；'.join(j['signals'])} | {j['action']} |")
    else:
        L.append("全部 trace 无异常信号。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("＊本判断层是纯规则（零 LLM），只做分流不做归因；needs_review/critical "
             "的根因分析仍由人（或 LLM 辅助）完成 —— 四层分工中规则层的位置。")
    return "\n".join(L)


def load_traces(path):
    """读输入 JSON：支持 [...] 或 {"traces": [...]}；读不到有效列表返回 None。"""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("traces"), list):
        return doc["traces"]
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Agent Trace 四级判断层（正常/轻微异常/需人工/高风险）")
    ap.add_argument("--in", dest="infile", required=True, help="trace 聚合 JSON（数组或 {traces:[...]})")
    ap.add_argument("--out", help="判定结果 JSON 输出路径")
    ap.add_argument("--md", dest="md_out", help="Markdown 报告输出路径")
    ap.add_argument("--threshold-slow", type=int, default=DEFAULT_SLOW_MS,
                    help="单条慢阈值 ms（默认 %d）" % DEFAULT_SLOW_MS)
    ap.add_argument("--threshold-p95", type=int, default=DEFAULT_P95_MS,
                    help="批次 p95 阈值 ms（默认 %d）" % DEFAULT_P95_MS)
    args = ap.parse_args()

    traces = load_traces(args.infile)
    if traces is None:
        cdx_errors.die("输入文件不是有效的 trace 集合", "路径: %s" % args.infile,
                       hint="支持 [...] 或 {\"traces\": [...]} 两种结构。", code=4)
    if not traces:
        print("[]")
        return 0

    report = judge_batch(traces, slow_ms=args.threshold_slow, p95_ms=args.threshold_p95)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    if args.md_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.md_out)), exist_ok=True)
        with open(args.md_out, "w", encoding="utf-8") as f:
            f.write(render_md(report))

    # 摘要打到 stdout（全量 JSON 走 --out）
    dist = report["distribution"]
    print("共 %d 条：" % report["total"]
          + " ".join("%s %d" % (SEVERITY_LABEL[s], dist[s]) for s in SEVERITY_ORDER))
    if report["escalations"]:
        print("升级复核 %d 条：%s" % (len(report["escalations"]),
                                     ", ".join(report["escalations"][:10])))
    return 0


if __name__ == "__main__":
    sys.exit(cdx_errors.guard(main))
