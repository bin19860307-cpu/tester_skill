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
       + 0.15*Bug未解决率 + 0.10*代码流失率 + 0.03*修改频率 + 0.01*作者经验 + 0.01*距上次修改
  历史度量权重合计 25%（≈核心模块占比），符合 CHID 实践结论。

  ⚠️ 跨模式不可比（2026-09-18 明确）：同一份 stats 下，静态模式因权重不同
     （base 0.30→0.20、core 0.25→0.20）会产生不同分数。实测同一 stats：
     静态 87.0 分 vs 增强 77.4 分（-9.6 分，与变更本身无关）。
     → 因此 compute() 一定返回 `mode`，消费方**禁止跨模式连线做趋势**，
       趋势必须按 scoring_mode 分组（见 scoring.py / bug_trend.py）。

等级：百分制 >=75 🔴高风险；>=50 🟡中风险；其余 🟢低风险

各维映射（map_to_score 升序边界）：
  基础风险    ：high=5, medium=3, low=1
  变更规模    ：lines  [20,50,100,200] → [1,2,3,4,5]
  模块跨度    ：files [1,2,3,5,10]    → [1,2,3,4,5]
  核心模块占比：ratio% [10,30,50]     → [1,3,4,5]
  变更密度    ：/file [5,10,30,50]    → [1,2,3,4,5]
  Bug未解决率 ：unresolved% [0,10,40,70] → [1,2,4,5]
                 （2026-09-18 更名：原称「历史Bug频率」名实不符 —— 该值语义是
                   `未关闭数/总数`，是**未解决率**，不是"该模块的历史 Bug 频率"）
  代码流失率  ：churn [0,2,5,10]     → [1,2,4,5]
  修改频率    ：modCount [0,5,20,50]  → [1,2,3,5]
  作者经验    ：authorExp [0,10,50,200] → [5,3,2,1]（反向：经验越少风险越高）
                 （取不到时置中性 3 分；**不得默认 0 → 映射成 5 分最高风险**，那是方向性错误）
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_bugs_doc  # noqa: E402

# ---------- 权重 ----------
WEIGHTS_VERSION = "1.1"      # 1.1: 维度更名「历史Bug频率」→「Bug未解决率」；author_exp 中性化
W5 = {"base": 0.30, "size": 0.20, "span": 0.15, "core": 0.25, "density": 0.10}
W10 = {"base": 0.20, "size": 0.15, "span": 0.10, "core": 0.20, "density": 0.05,
       "buggy": 0.15, "churn": 0.10, "modfreq": 0.03, "authorexp": 0.01, "dormancy": 0.01}

# 维度中文名 -> 权重键（唯一实现；渲染脚本一律用 compute() 返回的 dimension_weights，
# 不要再各自维护一份映射 —— 历史上有两份，改一处漏一处）
DIM_KEY = {
    "基础风险": "base", "变更规模": "size", "模块跨度": "span",
    "核心模块占比": "core", "变更密度": "density",
    "Bug未解决率": "buggy", "代码流失率": "churn", "修改频率": "modfreq",
    "作者经验": "authorexp", "距上次修改": "dormancy",
}
# 旧维度名 -> 新维度名（向后兼容历史 stats / 报告）
DIM_ALIAS = {"历史Bug频率": "Bug未解决率"}

BASE_MAP = {"high": 5, "medium": 3, "low": 1, "🔴 高": 5, "🟡 中": 3, "🟢 低": 1}


def map_to_score(v, edges, scores):
    """v <= edges[i] → scores[i]；全部超出 → scores[-1]"""
    for i, e in enumerate(edges):
        if v <= e:
            return scores[i]
    return scores[-1]


# JIT 核心模式（含本域：权益/降级/禁用/订单）
#
# ⚠️ 「版本」条目的口径修订（2026-09-18，两次）：
#   ① 原为 `降级|版本|version`，过宽 —— 每次发版都会有一个叫「版本号 pom」的模块，
#      于是**每条记录**都被判为「核心模块变更」，core_ratio 恒被抬高、风险分失去区分度，
#      JIT 也会对每个版本都吐「涉及版本/降级变更」的假阳性指示器。
#   ② 改成 `降级|回退|回滚|rollback|downgrade` 后**仍然过宽** —— 裸「回退」会命中
#      「表格样式回退」「UI 回退」这类**前端样式还原**。实测 manage-frontend
#      5.3.0.7→5.3.0.8 有三个 low 风险的样式模块被判核心，core 4/6 → 分数被抬高。
#      本域里「回退」是高频词（样式回退 / 需求回退 / 代码回退），不能裸匹配。
#   现收窄为「版本降级/回滚」语义：`降级` 保留（业务上就是降级，如「版本到期降级逻辑」），
#   `回退` 必须带「版本」前缀才计为版本级风险。
CORE_PATTERNS = [
    (r"auth|permission|role|acl|权限|认证|登录|禁用", "认证权限/禁用"),
    (r"payment|billing|order|transaction|支付|订单|交易|权益", "支付/权益"),
    (r"router|route|navigation|路由|导航", "路由导航"),
    (r"config|constants|settings|配置|常量", "配置常量"),
    (r"降级|版本回退|版本降级|回滚|rollback|downgrade", "版本降级/回退"),
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
        # 未解决率：优先新字段名 unresolved_ratio，兼容旧名 buggy_ratio
        unresolved = hist.get("unresolved_ratio")
        if unresolved is None:
            unresolved = hist.get("buggy_ratio", 0)
        buggy = map_to_score(float(unresolved) * 100, [0, 10, 40, 70], [1, 2, 4, 5])
        churn = map_to_score(float(hist.get("churn_rate", 0)), [0, 2, 5, 10], [1, 2, 4, 5])
        modf = map_to_score(float(hist.get("mod_count", 0)), [0, 5, 20, 50], [1, 2, 3, 5])
        # 作者经验：取不到时必须是中性 3 分（原实现用 0 → 映射成 5 分最高风险，方向反了）
        aexp = map_to_score(float(hist.get("author_exp", 3)), [0, 10, 50, 200], [5, 3, 2, 1])
        dorm = map_to_score(float(hist.get("days_since", 0)), [0, 30, 90, 365], [1, 2, 3, 5])
        dims = {
            "基础风险": base, "变更规模": size_score, "模块跨度": span_score,
            "核心模块占比": core_score, "变更密度": density_score,
            "Bug未解决率": buggy, "代码流失率": churn, "修改频率": modf,
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

    # 贡献 + 维度权重（渲染方直接用，不再各自维护映射）
    contributions = {k: round(v * weights.get(DIM_KEY.get(k, k.lower()), 0), 2)
                     for k, v in dims.items()}
    dimension_weights = {k: weights.get(DIM_KEY.get(k, k.lower()), 0) for k in dims}

    # 历史度量中「恒定偏移」占比（供报告如实提示"这部分分数不含信息"）
    flat_share = None
    if hist:
        flat_keys = ("代码流失率", "作者经验", "距上次修改")
        flat_share = round(sum(dimension_weights.get(k, 0) for k in flat_keys), 3)

    return {
        "mode": mode,
        "scoring_mode": mode,            # 别名（统一口径起见，报与存都用这个键）
        "weights_version": WEIGHTS_VERSION,
        "score": round(score, 2),
        "percent": percent,
        "level": level,
        "dimensions": dims,
        "dimension_weights": dimension_weights,
        "weights": weights,
        "contributions": contributions,
        "inputs": {
            "base_risk": stats.get("base_risk"), "total_lines": total, "file_count": fc,
            "core_ratio": round(core_ratio, 3), "avg_density": round(density, 2),
            "has_historical": bool(hist),
            "historical_flat_weight_share": flat_share,
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


def extract_files(data):
    """从 file_history.json 中取出「文件路径 → 变更记录」映射。

    兼容两种历史结构：
      - 规范结构: {"service": ..., "schema_version": ..., "files": {...}}
      - 旧扁平结构: {"src/a.py": {...}, "src/b.py": {...}}（早期未按骨架建文件头）
    旧结构下混在顶层的元数据键（service / schema_version / recent_changes 等）
    会被过滤掉，避免污染 change_count 均值。
    """
    if not isinstance(data, dict):
        return {}
    files = data.get("files")
    if isinstance(files, dict):
        return files
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and "change_count" in v
    }


def auto_historical(service, workspace, analytics_root=None):
    """从 diff-analytics 自动取历史度量。

    【2026-09-18 修复】原实现三个维度是**硬编码占位**：
        return {..., "churn_rate": 0.0, "author_exp": 0, "days_since": 0}
    实测后果（同一 stats）：`author_exp=0` 反向映射成 **5 分（最高风险）**、
    `churn_rate/days_since` 恒为 1 分 → 历史权重 25% 中有 12% 是**与变更无关的
    固定偏移**（恒贡献 3.2 分），等于给所有变更加了个常数，趋势因此不可比。

    现在改为真实可得就用真实值：
      · churn_rate  = (lines_added + lines_removed) / files_changed   ← 来自最新 service_metrics 记录
      · days_since  = 今天 - 版本链最新版本日期                        ← 来自 version_chain.json
      · author_exp  = 无数据源（TAPD/变更产物均不含作者工作量）→ **置中性 3 分**，
                      并在 `sources` 里标明 default:unavailable，便于报告如实提示。
    每一项都带 `sources` 溯源；只有 mod_count / unresolved_ratio 才是真实业务信号。

    返回 None 表示完全取不到数据（引擎退化为静态模式）。
    返回 dict 时额外带 `_sources`（字段级血缘）与 `_flat_share`（恒定偏移提示）。
    """
    base = analytics_root or os.path.join(workspace, ".workbuddy", "diff-analytics", service)
    fh = os.path.join(base, "file_history.json")
    sm = os.path.join(base, "service_metrics.json")
    vc = os.path.join(base, "version_chain.json")
    sources = {}
    try:
        # ---- 修改频率：file_history 平均 change_count ----
        mod_count, n = 0.0, 0
        if os.path.exists(fh):
            data = json.load(open(fh, encoding="utf-8"))
            for v in extract_files(data).values():
                mod_count += (v.get("change_count", 0) if isinstance(v, dict) else 0)
                n += 1
            if n:
                mod_count = round(mod_count / n, 1)
        sources["mod_count"] = f"file_history.json 均值（{n} 个文件）" if n else "unavailable"

        # ---- 未解决率（原 buggy_ratio，名实不符故更名）----
        # 2026-09-18: 支持项目级 Bug 池回退（服务级缺失时读 _project/）
        unresolved_ratio = 0.0
        _root = analytics_root or os.path.join(workspace, ".workbuddy", "diff-analytics")
        bugs_doc, _scope = load_bugs_doc(_root, service)
        if bugs_doc:
            bugs = bugs_doc.get("bugs", [])
            if bugs:
                unresolved_ratio = round(
                    sum(1 for b in bugs if b.get("status") not in ("closed", "已关闭")) / len(bugs), 3)
                scope_txt = "项目级池" if _scope == "project" else "服务级"
                sources["unresolved_ratio"] = f"version_bugs.json（{scope_txt}，{len(bugs)} 条，语义=未解决率）"

        # ---- 代码流失率：最新记录的 (增+删)/文件数 ----
        churn_rate = 0.0
        try:
            if os.path.exists(sm):
                recs = json.load(open(sm, encoding="utf-8")).get("records", [])
                if recs:
                    m = (recs[-1].get("metrics") or {})
                    fc = int(m.get("files_changed") or 0)
                    if fc > 0:
                        churn_rate = round((int(m.get("lines_added") or 0)
                                            + int(m.get("lines_removed") or 0)) / fc, 2)
                        sources["churn_rate"] = ("service_metrics 最新记录 (增+删)/文件数"
                                                 f"（{m.get('lines_added')}+{m.get('lines_removed')})/{fc}")
        except Exception:
            pass
        if "churn_rate" not in sources:
            sources["churn_rate"] = "unavailable"

        # ---- 距上次修改：今天 - 版本链最新版本日期 ----
        days_since = 0
        try:
            if os.path.exists(vc):
                vers = json.load(open(vc, encoding="utf-8")).get("versions", [])
                dates = [v.get("date") for v in vers if v.get("date")]
                if dates:
                    from datetime import date as _date
                    latest = max(dates)
                    y, mo, d = (int(x) for x in str(latest)[:10].split("-"))
                    days_since = max((_date.today() - _date(y, mo, d)).days, 0)
                    sources["days_since"] = f"version_chain 最新版本日期 {latest}"
        except Exception:
            pass
        if "days_since" not in sources:
            sources["days_since"] = "unavailable"

        # ---- 作者经验：无数据源 → 中性 3 分（不是 0！0 会被反向映射成最高风险）----
        author_exp = 3
        sources["author_exp"] = "default:unavailable（无作者工作量数据源，置中性分）"

        if mod_count or unresolved_ratio or churn_rate or days_since:
            return {
                "mod_count": mod_count,
                "unresolved_ratio": unresolved_ratio,
                "buggy_ratio": unresolved_ratio,      # 旧字段名兼容（语义=未解决率，勿当频率）
                "churn_rate": churn_rate,
                "author_exp": author_exp,
                "days_since": days_since,
                "_sources": sources,
                "_flat_fields": [k for k, v in sources.items()
                                 if str(v).startswith("default:")],
            }
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
