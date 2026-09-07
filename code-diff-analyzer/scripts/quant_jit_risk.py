#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quant_jit_risk.py — 量化风险评分 + JIT 缺陷预测 计算引擎（apex-diff-analyzer 能力整合版）

把 apex-diff-analyzer 的 Step 5c 量化评分模型 与 Step 5d JIT 缺陷预测洞察，
以「可复用的 Python 引擎」形式落到 code-diff-analyzer，使其既能定性(🔴🟡🟢)
又能定量(0-100 分) + 预测性(缺陷倾向) 评估一次变更。

==================== 评分模型 ====================
【模式 A：静态 5 维】（离线 compare 模式、无 git 历史时）
  Risk = 0.30*基础风险 + 0.20*变更规模 + 0.15*模块跨度 + 0.25*核心模块占比 + 0.10*变更密度
  各维得分上限 5 → Risk 上限 5.0；百分制 = Risk/5*100

【模式 B：增强 10 维】（提供 historical_metrics 或 --service 自动从 diff-analytics 取数时）
  Risk = 0.20*基础风险 + 0.15*变更规模 + 0.10*模块跨度 + 0.20*核心模块占比 + 0.05*变更密度
       + 0.15*历史Bug频率 + 0.10*代码流失率 + 0.03*修改频率 + 0.01*作者经验 + 0.01*距上次修改
  历史度量权重合计 25%（≈核心模块占比），符合 CHID 实践结论。

等级：百分制 >=75 🔴高风险；>=50 🟡中风险；其余 🟢低风险

各维映射（map_to_score 升序边界）：
  基础风险    ：high=5, medium=3, low=1
  变更规模    ：lines  [20,50,100,200] → [1,2,3,4,5]
  模块跨度    ：files [1,2,3,5,10]    → [1,2,3,4,5]
  核心模块占比：ratio% [10,30,50]     → [1,3,4,5]
  变更密度    ：/file [5,10,30,50]    → [1,2,3,4,5]
  历史Bug频率 ：buggyRatio% [0,10,40,70] → [1,2,4,5]
  代码流失率  ：churn [0,2,5,10]     → [1,2,4,5]
  修改频率    ：modCount [0,5,20,50]  → [1,2,3,5]
  作者经验    ：authorExp [0,10,50,200] → [5,3,2,1]（反向：经验越少风险越高）
  距上次修改  ：days [0,30,90,365]   → [1,2,3,5]（越久越危险）

==================== JIT 缺陷预测 ====================
基于 CC2Vec/JITLine (Zhou et al. 2021)：
  - 核心模块变更（认证/权限/支付/路由/配置 + 本域：权益/降级/禁用/版本/订单）→ 🔴 最强缺陷指示器
  - 变更规模 >400 行 → 🟡 建议拆 PR；>200 行 → 中规模指标
  - 跨文件 >10 → 🔴；>5 → 多文件指标
  - 数据格式/协议变更 → 🔴 下游兼容性
  - 高优(🔴)命中数 >=2 → 高风险预测；==1 → 中等；否则 → 低
效果参考：Top-20% 高风险变更覆盖 75%-88% 真实缺陷；AUC 0.72-0.83（规则引擎推断，非 ML 模型）

用法：
  python scripts/quant_jit_risk.py --stats stats.json            # 计算并打印结果 JSON
  python scripts/quant_jit_risk.py --stats stats.json --service portal-backend --workspace <ws>  # 尝试自动补历史度量
也可被 gen_quant_jit.py 直接 import： compute(stats) / generate_jit(stats)
"""
import argparse
import json
import os
import re
import sys

# ---------- 权重 ----------
W5 = {"base": 0.30, "size": 0.20, "span": 0.15, "core": 0.25, "density": 0.10}
W10 = {"base": 0.20, "size": 0.15, "span": 0.10, "core": 0.20, "density": 0.05,
       "buggy": 0.15, "churn": 0.10, "modfreq": 0.03, "authorexp": 0.01, "dormancy": 0.01}

BASE_MAP = {"high": 5, "medium": 3, "low": 1, "🔴 高": 5, "🟡 中": 3, "🟢 低": 1}


def map_to_score(v, edges, scores):
    """v <= edges[i] → scores[i]；全部超出 → scores[-1]"""
    for i, e in enumerate(edges):
        if v <= e:
            return scores[i]
    return scores[-1]


# JIT 核心模式（含本域：权益/降级/禁用/版本/订单）
CORE_PATTERNS = [
    (r"auth|permission|role|acl|权限|认证|登录|禁用", "认证权限/禁用"),
    (r"payment|billing|order|transaction|支付|订单|交易|权益", "支付/权益"),
    (r"router|route|navigation|路由|导航", "路由导航"),
    (r"config|constants|settings|配置|常量", "配置常量"),
    (r"降级|版本|version", "版本/降级"),
]


def compute(stats):
    """返回量化评分结果 dict（含模式、维度、分数、等级、贡献）。"""
    base = BASE_MAP.get(stats.get("base_risk"), 1)
    total = max(int(stats.get("total_lines", 0)), 0)
    fc = max(int(stats.get("file_count", 1)), 1)

    # 核心模块占比
    if "core_file_count" in stats and stats["core_file_count"] is not None:
        core_ratio = float(stats["core_file_count"]) / fc
    elif "core_ratio" in stats and stats["core_ratio"] is not None:
        core_ratio = float(stats["core_ratio"])
    else:
        core_ratio = 0.1
    core_ratio = min(max(core_ratio, 0.0), 1.0)

    # 变更密度
    if "avg_density" in stats and stats["avg_density"] is not None:
        density = float(stats["avg_density"])
    else:
        density = total / fc

    size_score = map_to_score(total, [20, 50, 100, 200], [1, 2, 3, 4, 5])
    span_score = map_to_score(fc, [1, 2, 3, 5, 10], [1, 2, 3, 4, 5])
    core_score = map_to_score(core_ratio * 100, [10, 30, 50], [1, 3, 4, 5])
    density_score = map_to_score(density, [5, 10, 30, 50], [1, 2, 3, 4, 5])

    hist = stats.get("historical_metrics")
    if hist:
        buggy = map_to_score(float(hist.get("buggy_ratio", 0)) * 100, [0, 10, 40, 70], [1, 2, 4, 5])
        churn = map_to_score(float(hist.get("churn_rate", 0)), [0, 2, 5, 10], [1, 2, 4, 5])
        modf = map_to_score(float(hist.get("mod_count", 0)), [0, 5, 20, 50], [1, 2, 3, 5])
        aexp = map_to_score(float(hist.get("author_exp", 0)), [0, 10, 50, 200], [5, 3, 2, 1])
        dorm = map_to_score(float(hist.get("days_since", 0)), [0, 30, 90, 365], [1, 2, 3, 5])
        dims = {
            "基础风险": base, "变更规模": size_score, "模块跨度": span_score,
            "核心模块占比": core_score, "变更密度": density_score,
            "历史Bug频率": buggy, "代码流失率": churn, "修改频率": modf,
            "作者经验": aexp, "距上次修改": dorm,
        }
        score = (W10["base"] * base + W10["size"] * size_score + W10["span"] * span_score +
                 W10["core"] * core_score + W10["density"] * density_score +
                 W10["buggy"] * buggy + W10["churn"] * churn + W10["modfreq"] * modf +
                 W10["authorexp"] * aexp + W10["dormancy"] * dorm)
        weights = W10
        mode = "enhanced"
    else:
        dims = {
            "基础风险": base, "变更规模": size_score, "模块跨度": span_score,
            "核心模块占比": core_score, "变更密度": density_score,
        }
        score = (W5["base"] * base + W5["size"] * size_score + W5["span"] * span_score +
                 W5["core"] * core_score + W5["density"] * density_score)
        weights = W5
        mode = "static"

    percent = round(score / 5.0 * 100, 1)
    level = "🔴 高风险" if percent >= 75 else ("🟡 中风险" if percent >= 50 else "🟢 低风险")

    # 贡献（维度分 * 权重）
    contributions = {k: round(v * weights.get(k.lower().replace("历史bug频率", "buggy")
                                               .replace("代码流失率", "churn").replace("修改频率", "modfreq")
                                               .replace("作者经验", "authorexp").replace("距上次修改", "dormancy")
                                               .replace("基础风险", "base").replace("变更规模", "size")
                                               .replace("模块跨度", "span").replace("核心模块占比", "core")
                                               .replace("变更密度", "density"), 0), 2) for k, v in dims.items()}
    return {
        "mode": mode,
        "score": round(score, 2),
        "percent": percent,
        "level": level,
        "dimensions": dims,
        "weights": weights,
        "contributions": contributions,
        "inputs": {
            "base_risk": stats.get("base_risk"), "total_lines": total, "file_count": fc,
            "core_ratio": round(core_ratio, 3), "avg_density": round(density, 2),
            "has_historical": bool(hist),
        },
    }


def generate_jit(stats):
    """返回 JIT 缺陷预测洞察 dict。"""
    desc = " ".join([
        stats.get("description", "") or "",
        " ".join(stats.get("files", []) or []),
    ])
    indicators, predictions = [], []
    for pat, label in CORE_PATTERNS:
        if re.search(pat, desc, re.I):
            indicators.append("涉及%s变更" % label)
            predictions.append("🔴 核心模块(%s)变更 — JIT研究(CC2Vec/JITLine)表明此类变更是最强缺陷指示器" % label)

    lines = max(int(stats.get("total_lines", 0)), 0)
    if lines > 400:
        predictions.append("🟡 变更规模 %d 行超过 400 行阈值，建议拆分为更小的 PR" % lines)
    elif lines > 200:
        indicators.append("中等规模变更(%d行)" % lines)

    fc = max(int(stats.get("file_count", 1)), 1)
    if fc > 10:
        predictions.append("🔴 涉及 10+ 文件变更，跨文件风险较高")
    elif fc > 5:
        indicators.append("涉及多个文件(%d)" % fc)

    if stats.get("data_format_change"):
        predictions.append("🔴 数据格式/协议变更，下游兼容性风险高")

    # 量化分数反向佐证
    q = compute(stats)
    if q["percent"] >= 75:
        predictions.append("🔴 量化评分 %s 分处于高风险区间，建议资深开发者参与 Code Review" % q["percent"])

    high = sum(1 for p in predictions if p.startswith("🔴"))
    label = "🔴 高风险预测" if high >= 2 else ("🟡 中等风险预测" if high == 1 else "🟢 低风险预测")
    rec = ("建议资深开发者参与 Code Review，增加回归测试覆盖，重点验证核心模块行为"
           if high >= 2 else
           ("建议投入额外代码审查资源，关注回归测试覆盖" if high == 1 else "可按常规流程处理，常规回归即可"))

    return {
        "prediction": label,
        "indicators": indicators,
        "basis": predictions,
        "recommendation": rec,
        "effectiveness": {
            "description": "基于 JIT 缺陷预测研究 (CC2Vec / JITLine, Zhou et al. 2021)",
            "top20_recall": "75%-88%",
            "auc": "0.72-0.83",
            "note": "本报告为规则引擎推断（非 ML 模型训练），实际需结合项目数据校准权重",
        },
    }


def auto_historical(service, workspace):
    """尝试从 diff-analytics 自动取历史度量（file_history 改次数→修改频率；version_bugs→Bug频率）。
    取不到则返回 None（引擎退化为静态模式）。"""
    base = os.path.join(workspace, ".workbuddy", "diff-analytics", service)
    fh = os.path.join(base, "file_history.json")
    vb = os.path.join(base, "version_bugs.json")
    try:
        mod_count = 0
        n = 0
        if os.path.exists(fh):
            data = json.load(open(fh, encoding="utf-8"))
            files = data if isinstance(data, dict) else data.get("files", {})
            for v in files.values():
                cc = v.get("change_count", 0) if isinstance(v, dict) else 0
                mod_count += cc
                n += 1
            if n:
                mod_count = round(mod_count / n, 1)
        buggy_ratio = 0.0
        if os.path.exists(vb):
            data = json.load(open(vb, encoding="utf-8"))
            bugs = data.get("bugs", data) if isinstance(data, dict) else data
            if isinstance(bugs, list) and bugs:
                buggy_ratio = round(sum(1 for b in bugs if b.get("status") not in ("closed", "关闭", "已关闭")) / len(bugs), 3)
        if mod_count or buggy_ratio:
            return {"mod_count": mod_count, "buggy_ratio": buggy_ratio,
                    "churn_rate": 0.0, "author_exp": 0, "days_since": 0}
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", required=True, help="stats JSON 文件路径")
    ap.add_argument("--service", help="服务名（尝试从 diff-analytics 自动补历史度量）")
    ap.add_argument("--workspace", help="工作区根目录（配合 --service）")
    args = ap.parse_args()
    stats = json.load(open(args.stats, encoding="utf-8"))
    if args.service and args.workspace:
        h = auto_historical(args.service, args.workspace)
        if h and "historical_metrics" not in stats:
            stats["historical_metrics"] = h
            print("INFO: 已从 diff-analytics/%s 自动补历史度量: %s" % (args.service, h), file=sys.stderr)
    q = compute(stats)
    jit = generate_jit(stats)
    print(json.dumps({"quantitative_risk": q, "jit_prediction": jit}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
