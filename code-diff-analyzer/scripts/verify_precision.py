#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_precision.py — 用真实命中率校准评分权重（把「规则引擎」升级为「项目校准模型」）

这是 2026-09-18 体检里唯一能**让模型自我校准**的闭环：
在此之前，「风险评级准不准」系统从来没度量过 —— `high_risk_hit_rate` 只写在
SKILL.md:950 里，全代码库查无实现；实测 49 个 Bug 的有效关联数为 0，等于连
"分得准不准"这个问题的输入都不存在。

本脚本做三件事：

  ① 聚合真实命中率
       · `high_risk_hit_rate`  = 有 Bug 的高风险变更 / 高风险变更总数
       · `detection_precision` = 每项专项检测「命中且有 Bug / 命中总数」
       · `change_to_bug_ratio` = 每区间 Bug 数 / 变更文件数

  ② 分桶校准检验（关键）
       把历史变更按 risk_score 分桶，统计每桶的**真实出 Bug 率**。
       若分数有效，出 Bug 率应随分数单调递增；否则说明权重需要调。
       同时输出单调性判定（单调 / 逆序对数量），并明确标注样本量是否足够。

  ③ 权重建议
       基于 ① 的实测精度给出 W10 的调整建议。**样本不足时只给诊断不给建议**
       —— 避免用 3 个样本"校准"出一套看似权威的权重。

输出：JSON（--json）+ 人类可读报告（默认）。

用法：
    python scripts/verify_precision.py --all
    python scripts/verify_precision.py --all --json
    python scripts/verify_precision.py --service portal-backend --out report.md
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # 统一友好错误层
from _common import norm_version  # noqa: E402
import sync_analytics as sa  # noqa: E402

DEFAULT_WORKSPACE = r"d:/workbuddy/测试日常"
DETECTION_KEYS = ["data_format_change", "version_rollback", "sensitive_info",
                  "test_sync_needed", "circular_dependency"]
DETECTION_LABEL = {
    "data_format_change": "数据格式变更", "version_rollback": "版本回退",
    "sensitive_info": "敏感信息", "test_sync_needed": "测试同步",
    "circular_dependency": "循环依赖",
}
# 最小可信样本量：低于此值只诊断、不调权重
MIN_SAMPLES_FOR_CALIBRATION = 30
BUCKET_EDGES = [0, 40, 55, 70, 85, 101]      # 低/较低/中/较高/高


def collect_samples(services, analytics_root):
    """从各服务 cross_reference + service_metrics 汇总样本。

    每个样本 = 一个版本区间（一次变更）：
      {service, range, risk_score, has_bug, found, fixed, files_changed,
       change_to_bug_ratio, detections, high_risk_*}
    """
    samples = []
    for svc in services:
        svc_dir = os.path.join(analytics_root, svc)
        cr = sa.load_json(os.path.join(svc_dir, "cross_reference.json"))
        sm = sa.load_json(os.path.join(svc_dir, "service_metrics.json")) or {}
        recs = {norm_version(r.get("version_to")): r for r in sm.get("records", [])}
        if not cr:
            continue
        for m in cr.get("mappings", []):
            ck = norm_version(m.get("version_to"))
            rec = recs.get(ck) or {}
            mm = rec.get("metrics") or {}
            found = m.get("bugs_found_in_version") or []
            fixed = m.get("bugs_fixed_in_version") or []
            samples.append({
                "service": svc,
                "range": m.get("version_range"),
                "risk_score": mm.get("risk_score"),
                "risk_score_enhanced": mm.get("risk_score_enhanced"),
                "mapped": mm.get("risk_score") is not None,
                "has_bug": bool(found or fixed),
                "found": len(found),
                "fixed": len(fixed),
                "files_changed": m.get("files_changed"),
                "change_to_bug_ratio": m.get("change_to_bug_ratio"),
                "detections": m.get("detections") or {},
                "high_risk_total": m.get("high_risk_total") or 0,
                "high_risk_with_bug": m.get("high_risk_with_bug") or 0,
                "attribution": cr.get("attribution"),
            })
    return samples


def aggregate(samples):
    """① 聚合真实命中率。"""
    hr_total = sum(s["high_risk_total"] for s in samples)
    hr_with = sum(s["high_risk_with_bug"] for s in samples)
    det = {}
    for k in DETECTION_KEYS:
        hit = sum(1 for s in samples if s["detections"].get(k))
        hit_bug = sum(1 for s in samples if s["detections"].get(k) and s["has_bug"])
        det[k] = {
            "label": DETECTION_LABEL[k],
            "hit_total": hit,
            "hit_with_bug": hit_bug,
            "precision": round(hit_bug / hit, 3) if hit else None,
            "support_enough": hit >= 5,
        }
    n = len(samples)
    buggy = sum(1 for s in samples if s["has_bug"])
    return {
        "samples": n,
        "changes_with_bug": buggy,
        "bug_rate": round(buggy / n, 3) if n else None,
        "high_risk_total": hr_total,
        "high_risk_with_bug": hr_with,
        "high_risk_hit_rate": round(hr_with / hr_total, 3) if hr_total else None,
        "detection_precision": det,
        "attribution": samples[0]["attribution"] if samples else None,
        "samples_enough": n >= MIN_SAMPLES_FOR_CALIBRATION,
        "min_samples_for_calibration": MIN_SAMPLES_FOR_CALIBRATION,
    }


def bucket_calibration(samples, edges=None):
    """② 分桶校准：按 risk_score 分桶，统计真实出 Bug 率与单调性。

    分数有效 ⇒ 出 Bug 率随分数桶递增。逆序对越多，说明权重越需要调。
    """
    edges = edges or BUCKET_EDGES
    scored = [s for s in samples if s.get("risk_score") is not None]
    buckets = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        grp = [s for s in scored if lo <= s["risk_score"] < hi]
        if not grp:
            buckets.append({"bucket": f"[{lo},{hi})", "n": 0, "bug_rate": None,
                            "avg_score": None})
            continue
        b = sum(1 for s in grp if s["has_bug"])
        buckets.append({
            "bucket": f"[{lo},{hi})", "n": len(grp), "with_bug": b,
            "bug_rate": round(b / len(grp), 3),
            "avg_score": round(sum(s["risk_score"] for s in grp) / len(grp), 1),
        })
    # 单调性：相邻有效桶的 bug_rate 是否非递减
    valid = [b for b in buckets if b["n"] > 0 and b["bug_rate"] is not None]
    inversions = sum(1 for a, b in zip(valid, valid[1:]) if b["bug_rate"] < a["bug_rate"])
    monotonic = inversions == 0
    # Spearman 近似（样本很少时仅供参考）
    rho = None
    if len(scored) >= 5:
        pairs = [(s["risk_score"], 1 if s["has_bug"] else 0) for s in scored]
        rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
    return {
        "buckets": buckets,
        "non_empty_buckets": len(valid),
        "inversions": inversions,
        "monotonic": monotonic,
        "spearman_rho": rho,
        "note": ("桶数或桶内样本过少时，单调性与 rho 不具统计意义，仅供定性参考"
                 if len(scored) < MIN_SAMPLES_FOR_CALIBRATION else None),
    }


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(x, y):
    n = len(x)
    if n < 2:
        return None
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(num / (dx * dy), 3) if dx and dy else None


def suggest_weights(agg, calib):
    """③ 权重建议。样本不足时**只给诊断，不给建议**。"""
    if not agg["samples_enough"]:
        return {
            "available": False,
            "reason": (f"有效样本仅 {agg['samples']} 个，低于校准门槛 "
                       f"{MIN_SAMPLES_FOR_CALIBRATION} 个 → 不做权重调整建议，"
                       "避免用少量样本拟合出看似权威的参数"),
            "next_step": "继续按规范落盘分析记录（每次分析都会被映射引擎消费），样本充足后重跑本脚本",
        }

    recs = []
    # 检测项：精度 < 0.3 且样本足够 → 建议降权或复核规则
    for k, d in agg["detection_precision"].items():
        if not d["support_enough"]:
            recs.append({"item": d["label"], "action": "observe",
                         "reason": f"命中样本仅 {d['hit_total']} 次，不足以判断"})
            continue
        p = d["precision"]
        if p is not None and p < 0.3:
            recs.append({"item": d["label"], "action": "review",
                         "reason": f"命中 {d['hit_total']} 次、其中有 Bug 仅 {d['hit_with_bug']} 次"
                                   f"（精度 {p:.0%}）→ 该检测规则可能误报偏高，建议复核阈值"})
        else:
            recs.append({"item": d["label"], "action": "keep",
                         "reason": f"精度 {p:.0%}（{d['hit_with_bug']}/{d['hit_total']}）"})
    # Bug 维度：实测 hit_rate 偏离先验（0.5）越远，权重越该调
    hr = agg["high_risk_hit_rate"]
    if hr is not None:
        recs.append({
            "item": "Bug未解决率维度权重(buggy=0.15)",
            "action": "keep" if hr >= 0.5 else "reduce",
            "reason": f"实测高风险变更命中率 {hr:.0%}（{agg['high_risk_with_bug']}/"
                      f"{agg['high_risk_total']}）"
                      + ("，区分度良好" if hr >= 0.5 else "，区分度不足，建议下调该维权重"),
        })
    return {"available": True, "recommendations": recs,
            "calibration_ok": calib["monotonic"],
            "note": ("分桶单调性未通过 → 权重需整体重估" if not calib["monotonic"]
                     else "分桶单调性通过 → 现有权重排序有效")}


def render(agg, calib, sug, services):
    L = []
    L.append("# 评分精度校准报告")
    L.append("")
    L.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    L.append(f"> 覆盖服务：{', '.join(services)}  ")
    L.append(f"> 样本量：**{agg['samples']}** 个版本区间"
             f"（校准门槛 {agg['min_samples_for_calibration']}）")
    L.append("")
    L.append("## 一、真实命中率")
    L.append("")
    L.append("| 指标 | 实测值 | 说明 |")
    L.append("|---|---|---|")
    hr = agg["high_risk_hit_rate"]
    L.append(f"| 高风险变更命中率 | {hr if hr is not None else '—（无高风险变更项）'} | "
             f"{agg['high_risk_with_bug']}/{agg['high_risk_total']}；归因方式 "
             f"`{agg['attribution']}` |")
    L.append(f"| 变更出 Bug 率 | {agg['bug_rate']} | "
             f"{agg['changes_with_bug']}/{agg['samples']} 个区间有 Bug |")
    L.append("")
    L.append("## 二、专项检测精度")
    L.append("")
    L.append("| 检测项 | 命中次数 | 其中有 Bug | 精度 | 样本是否足够 |")
    L.append("|---|---|---|---|---|")
    for k, d in agg["detection_precision"].items():
        p = f"{d['precision']:.0%}" if d["precision"] is not None else "—"
        L.append(f"| {d['label']} | {d['hit_total']} | {d['hit_with_bug']} | {p} | "
                 f"{'是' if d['support_enough'] else '否'} |")
    L.append("")
    L.append("## 三、分桶校准检验（分数排序有效性）")
    L.append("")
    L.append("| 分数桶 | 样本数 | 出 Bug 数 | 真实出 Bug 率 | 桶内均分 |")
    L.append("|---|---|---|---|---|")
    for b in calib["buckets"]:
        br = f"{b['bug_rate']:.0%}" if b["bug_rate"] is not None else "—"
        L.append(f"| {b['bucket']} | {b['n']} | {b.get('with_bug', '—')} | {br} | "
                 f"{b['avg_score'] if b['avg_score'] is not None else '—'} |")
    L.append("")
    L.append(f"- 单调性：**{'通过' if calib['monotonic'] else '未通过'}**"
             f"（逆序对 {calib['inversions']} 个，非空桶 {calib['non_empty_buckets']} 个）")
    if calib.get("spearman_rho") is not None:
        L.append(f"- 秩相关 ρ（risk_score ↔ 是否出 Bug）：**{calib['spearman_rho']}**")
    if calib.get("note"):
        L.append(f"- ⚠️ {calib['note']}")
    L.append("")
    L.append("## 四、权重建议")
    L.append("")
    if not sug["available"]:
        L.append(f"**不提供权重调整建议。** 原因：{sug['reason']}")
        L.append("")
        L.append(f"下一步：{sug['next_step']}")
    else:
        L.append(f"- 分桶单调性：{'通过' if sug['calibration_ok'] else '未通过'}")
        L.append(f"- 结论：{sug['note']}")
        L.append("")
        L.append("| 项 | 建议动作 | 依据 |")
        L.append("|---|---|---|")
        for r in sug["recommendations"]:
            act = {"keep": "保持", "reduce": "下调", "review": "复核", "observe": "观察"}[r["action"]]
            L.append(f"| {r['item']} | {act} | {r['reason']} |")
    L.append("")
    L.append("---")
    L.append("")
    L.append("＊样本量决定可信度：本报告的所有结论仅在样本充足时才具统计意义。"
             "样本量偏少时，请把本报告当作「数据链路已通」的证明，而非权重结论。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="评分精度校准（用真实命中率检验权重）")
    ap.add_argument("--service")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    ap.add_argument("--analytics-root")
    ap.add_argument("--out", help="Markdown 报告输出路径")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")
    if args.all:
        services = sorted(d for d in os.listdir(analytics_root)
                          if os.path.isdir(os.path.join(analytics_root, d))
                          and not d.startswith("_"))
    elif args.service:
        services = [args.service]
    else:
        print("[ERROR] 需要 --service 或 --all")
        sys.exit(1)

    samples = collect_samples(services, analytics_root)
    if not samples:
        print("[WARN] 未采集到任何变更样本（各服务尚无 cross_reference.json）")
        return 0
    agg = aggregate(samples)
    calib = bucket_calibration(samples)
    sug = suggest_weights(agg, calib)
    result = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "services": services, "aggregate": agg, "calibration": calib,
              "weight_suggestion": sug}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        md = render(agg, calib, sug, services)
        print(md)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"\n[OK] 报告已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(cdx_errors.guard(main))
