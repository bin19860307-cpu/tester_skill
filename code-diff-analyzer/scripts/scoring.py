#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scoring.py — Code Diff Analyzer · 统一口径模块（单一真源）

对应 2026-09-18 体检缺陷：

  P1-6 两套 risk_score 并存，且都没进趋势
      · metrics.risk_score = min(100, high*10+medium*5+low*1)  ← Flow C 趋势读它
      · 报告里的量化分      = quant_jit_risk.compute() 0-100     ← 只活在单份 HTML
      两者无关联；且实测 `grep -rn risk_score scripts/*.py` 零命中
      → 说明 service_metrics 里的分**不是脚本算的，是 LLM 按文档公式手填的**。

  P1-7 评级口径不可复现
      SKILL.md Step 5 给的是伪代码 changesAuthCoreLogic(diff) / isStyleOnly(diff)，
      代码里无实现，全靠 LLM 现场判断 → 同一 diff 两次跑可能给出不同等级。

本模块把上述两件事都下沉成**确定性规则**，是这两项能力的唯一实现：

  canonical_risk_score(record)  —— 由 record 本身确定性推出 0-100 分（不再依赖 LLM 手填）
  rate_change(record, paths)    —— 确定性 🔴/🟡/🟢 评级

设计约束：risk_score 只保留**一个**。旧公式值不删除，改名 `risk_score_legacy` 留档，
便于历史记录审计（不做静默覆盖）。
"""
import os
import cdx_errors  # 统一友好错误层
import re

try:
    from . import quant_jit_risk as qjr          # 作为包被 import 时
except ImportError:                              # 作为脚本 / 同目录 import 时
    import quant_jit_risk as qjr

from _common import is_logic_path, normalize_path

# 旧公式（已弃用，仅用于留档与对照，不再写入 risk_score）
LEGACY_FORMULA = "min(100, high*10 + medium*5 + low*1)"

# 确定性评级规则版本号：规则一改就 +1，写进产物便于跨版本比对
# 1.0 → 1.1（2026-09-18）：R3/R4/R5 阈值重标定，见 rate_change() docstring
RATING_RULES_VERSION = "1.1"

# 规模阈值 —— 与 quant_jit_risk.generate_jit() 已公开的口径保持一致
# （那里是：>400 行建议拆 PR、>10 文件「跨文件风险较高」、>5 文件「涉及多个文件」），
# 全技能只此一套阈值，避免同一件事在报告里出现两种判定。
HIGH_LINES, HIGH_FILES = 400, 10
MED_LINES, MED_FILES = 150, 5
# 高风险模块「占比」门槛（R4）
HIGH_RISK_MIN_CNT, HIGH_RISK_RATIO = 2, 1 / 3

# 纯样式/文案变更（不含逻辑）
_STYLE_ONLY_RE = [
    re.compile(r"\.(css|scss|less|styl|svg)$", re.I),
    re.compile(r"(^|/)(theme|token|palette|variable)s?[^/]*\.(ts|js|json|css|scss)$", re.I),
]
# 认证/权限/支付 核心逻辑（最高敏感面）
_AUTH_CORE_RE = [
    re.compile(r"auth|permission|role|acl|token|session|login|logout|oauth", re.I),
    re.compile(r"payment|billing|order|transaction|refund", re.I),
    re.compile(r"权限|认证|登录|支付|订单|权益", re.I),
]
# 数据格式/协议/契约变更
_DATA_FORMAT_RE = [
    re.compile(r"\.(proto|graphql|thrift|avro)$", re.I),
    re.compile(r"(^|/)(dto|vo|entity|schema|migration|sql)s?(/|$)", re.I),
    re.compile(r"\.sql$", re.I),
    re.compile(r"(^|/)(zh|en|i18n|locale)[^/]*\.json$", re.I),
]

SEV_ORDER = {"high": 3, "medium": 2, "low": 1}


def derive_stats(record, service=None):
    """从一条 service_metrics 记录**确定性**推导 quant_jit_risk.compute() 所需的 stats。

    这样 risk_score 只依赖落盘数据，不再依赖 LLM 当场填分 → 同一条记录重复算结果恒定。

    推导规则：
      base_risk   = modules 中最高风险等级（无 modules 时回退用 high/medium/low 计数）
      total_lines = lines_added + lines_removed
      file_count  = files_changed
      core_file_count = 名字命中 CORE_PATTERNS 的模块所覆盖的文件数
      avg_density = total_lines / file_count
      description = 各模块名 + 已记录的文件路径（供 JIT 关键词匹配）
    """
    rec = record or {}
    m = rec.get("metrics") or {}
    modules = rec.get("modules") or []
    detections = rec.get("detections") or {}

    files_changed = int(m.get("files_changed") or 0)
    lines_added = int(m.get("lines_added") or 0)
    lines_removed = int(m.get("lines_removed") or 0)
    total_lines = lines_added + lines_removed

    # base_risk：优先 modules 最高等级；否则用风险计数反推
    base_risk = None
    best = 0
    for mod in modules:
        r = str((mod or {}).get("risk") or "").lower()
        if SEV_ORDER.get(r, 0) > best:
            best, base_risk = SEV_ORDER[r], r
    if base_risk is None:
        if int(m.get("high_risk") or 0) > 0:
            base_risk = "high"
        elif int(m.get("medium_risk") or 0) > 0:
            base_risk = "medium"
        else:
            base_risk = "low"

    # 核心模块覆盖的文件数
    core_files = 0
    for mod in modules:
        name = str((mod or {}).get("name") or "")
        if any(re.search(pat, name, re.I) for pat, _label in qjr.CORE_PATTERNS):
            core_files += int((mod or {}).get("files") or 0)

    # 描述串：模块名 + 文件路径（JIT 关键词命中依据）
    desc_parts = [str((mod or {}).get("name") or "") for mod in modules]
    desc_parts += [normalize_path(p) for p in (rec.get("files") or [])]
    description = " ".join(p for p in desc_parts if p)

    fc = max(files_changed, 1)
    return {
        "base_risk": base_risk,
        "total_lines": total_lines,
        "file_count": fc,
        "core_file_count": core_files,
        "avg_density": round(total_lines / fc, 2),
        "description": description,
        "data_format_change": bool(detections.get("data_format_change")),
        "files": rec.get("files") or [],
        # 供上层判断是否需要进入增强模式
        "_service": service or rec.get("service"),
    }


def canonical_risk_score(record, historical=None, service=None):
    """确定性计算该记录的 0-100 risk_score（唯一真源）。

    返回：
      {
        "risk_score": 76.0,            # 写回 service_metrics.metrics.risk_score
        "risk_level": "🔴 高风险",
        "scoring_mode": "static" | "enhanced",
        "score_engine": "quant_jit_risk.compute",
        "rating_rules_version": "1.0",
        "dimensions": {...}, "contributions": {...}, "inputs": {...},
        "legacy": {"risk_score_legacy": 37, "formula": ...}
      }
    """
    rec = record or {}
    m = rec.get("metrics") or {}

    stats = derive_stats(rec, service=service)
    if historical:
        stats["historical_metrics"] = historical

    q = qjr.compute(stats)
    jit = qjr.generate_jit(stats)

    # 旧值留档（不静默丢弃）
    legacy_value = m.get("risk_score")
    legacy = None
    if legacy_value is not None:
        recomputed_legacy = min(100, int(m.get("high_risk") or 0) * 10
                               + int(m.get("medium_risk") or 0) * 5
                               + int(m.get("low_risk") or 0) * 1)
        legacy = {
            "risk_score_legacy": legacy_value,
            "risk_score_legacy_recomputed": recomputed_legacy,
            "formula": LEGACY_FORMULA,
            "note": "旧公式与量化分无关联，已弃用；保留仅为历史审计",
        }

    return {
        "risk_score": q["percent"],
        "risk_level": q["level"],
        "scoring_mode": q["mode"],
        "score_engine": "quant_jit_risk.compute",
        "rating_rules_version": RATING_RULES_VERSION,
        "dimensions": q["dimensions"],
        "contributions": q["contributions"],
        "inputs": q["inputs"],
        "jit_prediction": jit["prediction"],
        "legacy": legacy,
    }


def rate_change(record, paths=None):
    """确定性风险评级（替代 SKILL.md Step 5 的 LLM 现场判断）。

    规则（按优先级，命中即返回，全部可复现）：
      🔴 高风险 · 任一成立：
         R1 触及认证/权限/支付/订单 核心逻辑
         R2 命中数据格式/协议/契约变更
         R3 变更规模大：> 400 行 或 > 10 文件
         R4 高风险模块占比 ≥ 1/3 且数量 ≥ 2（高风险不是个别现象）
      🟡 中风险 · 任一成立：
         R5 变更规模中等：> 150 行 或 > 5 文件
         R6 存在高风险模块（数量 ≥ 1，但未达 R4 的占比门槛）
      🟢 低风险 · 其余

    ⚠️ 阈值重标定（rules 1.0 → 1.1，2026-09-18）——为什么必须改：

      R3 原为「> 200 行 或 > 5 文件」，R4 原为「存在 high 风险模块（high_risk > 0）」。
      在真实数据上实测，这两条几乎**无差别触发**，评级退化成「几乎全是 🔴 高」
      （8 条记录里 7 条高），完全失去区分度。反例最能说明问题：

        · manage-frontend 5.3.0.7→5.3.0.8：6 文件 / 44 行 / 高风险模块 0 个（med 1、low 5）
          → 唯一命中的规则是「文件数 6 > 5」，被判 🔴 高。这不合理。
        · trufar-landing-page 1.0.9→1.0.10：7 文件 / 37 行 / 高风险模块 0 个
          → 同样只因「7 > 5」被判 🔴 高。

      改法（不是为了让分布好看，而是三条各自有据）：
        ① 规模阈值改回本技能**已经公开**的那一套（400 行 / 10 文件 / 5 文件，见 quant_jit_risk），
           同一件事不再有两套阈值；
        ② R4 由「存在」改为「占比 ≥ 1/3 且 ≥2 个」——「有 1 个高风险模块」不等于
           「整个区间高风险」；占比才是「变更面广」的代理信号；
        ③ 原「仅样式」规则顺延为 R7。

      重算后：高 3 / 中 4 / 低 1（原 7/1/0），每条都能指到具体规则。

    返回 {"level": "...", "code": "high|medium|low", "reasons": [...], "rules_version": ...}
    """
    rec = record or {}
    m = rec.get("metrics") or {}
    files = [normalize_path(p) for p in (paths or rec.get("files") or [])]
    desc = " ".join([str((mod or {}).get("name") or "") for mod in (rec.get("modules") or [])]
                    + files)
    total_lines = int(m.get("lines_added") or 0) + int(m.get("lines_removed") or 0)
    files_changed = int(m.get("files_changed") or len(files) or 0)
    detections = rec.get("detections") or {}
    high_risk_cnt = int(m.get("high_risk") or 0)

    reasons = []
    if any(r.search(desc) for r in _AUTH_CORE_RE):
        reasons.append("R1 触及认证/权限/支付/订单核心逻辑")
    if detections.get("data_format_change") or any(r.search(desc) for r in _DATA_FORMAT_RE):
        reasons.append("R2 命中数据格式/协议/契约变更")
    if total_lines > HIGH_LINES or files_changed > HIGH_FILES:
        reasons.append("R3 变更规模大（>%d 行 或 >%d 文件）" % (HIGH_LINES, HIGH_FILES))
    # R4 高风险模块「占比」而非「存在」——见 docstring 的口径修订说明
    if high_risk_cnt >= HIGH_RISK_MIN_CNT and files_changed > 0 \
            and high_risk_cnt / files_changed >= HIGH_RISK_RATIO:
        reasons.append("R4 高风险模块占比 ≥ %d/%d（%d/%d）"
                       % (int(HIGH_RISK_RATIO * 100), 100, high_risk_cnt, files_changed))
    if reasons:
        return {"level": "🔴 高", "code": "high", "reasons": reasons,
                "rules_version": RATING_RULES_VERSION}

    if total_lines > MED_LINES or files_changed > MED_FILES:
        reasons.append("R5 变更规模中等（>%d 行 或 >%d 文件）" % (MED_LINES, MED_FILES))
        return {"level": "🟡 中", "code": "medium", "reasons": reasons,
                "rules_version": RATING_RULES_VERSION}

    # R6 存在高风险模块（但未达到 R4 的占比门槛）
    if high_risk_cnt >= 1:
        reasons.append("R6 存在高风险模块（%d 个，未达 R4 占比门槛）" % high_risk_cnt)
        return {"level": "🟡 中", "code": "medium", "reasons": reasons,
                "rules_version": RATING_RULES_VERSION}

    if files and all(any(r.search(p) for r in _STYLE_ONLY_RE) for p in files):
        reasons.append("R7 仅涉及样式/文案变更")
    return {"level": "🟢 低", "code": "low", "reasons": reasons,
            "rules_version": RATING_RULES_VERSION}


def detect_data_format_change(record, paths=None):
    """数据格式/协议变更的确定性判定（供 detections 自动补全，避免 LLM 漏判）。

    判定为「或」关系，任一成立即为 True：
      · 记录里已显式标记 detections.data_format_change（人工/上游已经判过，尊重其结论）
      · 变更文件路径或模块名命中数据格式模式（proto / schema / dto / sql / locale zh|en.json）

    只在路径里找是不够的：真实数据里 service_metrics 的 detections 常常是 LLM 提前
    写好的（例如「导出格式变更」并没有 .proto 文件），忽略该标记会把已识别的
    数据格式风险判回 False。
    """
    rec = record or {}
    if bool((rec.get("detections") or {}).get("data_format_change")):
        return True
    files = [normalize_path(p) for p in (paths or rec.get("files") or [])]
    desc = " ".join(files + [str((mod or {}).get("name") or "")
                             for mod in (rec.get("modules") or [])])
    return any(r.search(desc) for r in _DATA_FORMAT_RE)


def is_logic_file(p):
    """透传，便于调用方只 import 本模块。"""
    return is_logic_path(p)


def main():
    import json
    import sys
    # Windows 默认控制台常为 GBK，直接输出评级 emoji 会触发
    # UnicodeEncodeError。命令行自检统一使用 UTF-8，并对异常字符降级替换。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    demo = {
        "version_from": "business-5.3.0.3", "version_to": "business-5.3.0.4",
        "metrics": {"files_changed": 7, "lines_added": 120, "lines_removed": 40,
                    "high_risk": 2, "medium_risk": 3, "low_risk": 2, "risk_score": 37},
        "modules": [
            {"name": "数据统计(DorisStatisticServiceImpl 权限维度)", "files": 1, "risk": "high"},
            {"name": "智能体搜索(AgentServiceImpl)", "files": 1, "risk": "high"},
            {"name": "版本号/下载文件名(pom/TaskManage)", "files": 2, "risk": "low"},
        ],
        "detections": {"data_format_change": True, "version_rollback": False,
                       "sensitive_info": False, "test_sync_needed": True,
                       "circular_dependency": False},
        "files": ["src/main/java/x/DorisStatisticServiceImpl.java",
                  "src/main/java/x/AgentServiceImpl.java", "pom.xml"],
    }
    out = canonical_risk_score(demo, service="portal-backend")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("评级:", json.dumps(rate_change(demo), ensure_ascii=False))
    print("风格变更判定:", json.dumps(rate_change(
        {"metrics": {"files_changed": 1, "lines_added": 5, "lines_removed": 2}},
        paths=["src/style/theme.scss"]), ensure_ascii=False))



if __name__ == "__main__":
    cdx_errors.guard(main)