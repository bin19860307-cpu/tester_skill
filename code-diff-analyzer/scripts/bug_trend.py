# -*- coding: utf-8 -*-
"""
bug_trend.py  —  Code Diff Analyzer · Flow C.2 版本 Bug 趋势统计（固化脚本）

功能：
  读取某服务的 version_bugs.json + version_chain.json + service_metrics.json，
  按版本统计：Bug 数 / 严重度分布 / 修复率 / 发现→修复版本间隔，
  生成「单文件、无外部依赖（内联 SVG 图表，不依赖 CDN）」的 HTML 趋势区块。

两种输出模式：
  1) 独立报告（默认 / --out）：
      生成一份完整 HTML 文件（含 <html> 外壳），可直接打开。
  2) 注入比对报告（--report <比对报告.html>）：
      将趋势区块嵌入已有的「代码变更影响分析报告」HTML 中：
        - 若报告含 <!-- BUG_TREND_SECTION --> 占位符 → 替换该占位符
        - 若报告已含注入区块（<!-- BUG_TREND_START -->）→ 整块替换（幂等，可重复执行）
        - 否则 → 回退注入到 </body> 之前
     样式使用 bt- 前缀作用域，避免与比对报告模板的全局样式冲突。

用法：
  # 单服务报告（默认）
  python bug_trend.py --service portal-backend
  python bug_trend.py --service portal-backend \
        --report "report/code-diff/portal-backend/portal-backend_xxx_变更影响分析报告.html"

  # 综合报告（跨服务聚合注入，与 --service 互斥）
  #   先由 gen_combined_report.py 在「各版本 Bug 数据明细」节写入 <!-- BUG_TREND_COMBINED --> 占位符，
  #   再由本命令聚合各服务 version_bugs.json 并替换该占位符。
  python bug_trend.py --combined --services portal-backend main-frontend manage-frontend \
        --report "report/code-diff/_综合/综合比对分析报告_xxx.html"

依赖：仅 Python 标准库

【2026-09-18 修复】
  · 版本键：改用 _common.norm_version 归一（原实现 metrics_map.get(v) 是精确字符串匹配，
    而 Bug 侧裸号 `5.3.0.2` / 链路侧带前缀 `business-5.3.0.2` → 必然 miss）
  · 每版本新增 `risk_score` / `scoring_mode`，并**按 scoring_mode 分段禁止跨模式连线**
    （静态 87.0 vs 增强 77.4 是权重迁移造成的伪波动，不是真实风险变化）
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # noqa: E402
    norm_version, version_key as _version_key, version_series, same_version,
    load_bugs_doc, classify_bug_side, PROJECT_SERVICE, PROJECT_POOL_DIR,
    bugs_side_breakdown, safe_write_report,
)

SEV_ORDER = ["critical", "high", "medium", "low"]
SEV_LABEL = {"critical": "严重", "high": "高", "medium": "一般/中", "low": "低/建议"}
SEV_COLOR = {"critical": "#c0392b", "high": "#e67e22", "medium": "#f1c40f", "low": "#27ae60"}
MODE_LABEL = {"static": "静态5维", "enhanced": "增强10维"}

SCOPE_LABEL = {
    "service": "服务级（仅该服务关联的 Bug）",
    "project": "项目级（按提测版本整包关联，不区分前后端服务）",
}


def version_key(v):
    """（2026-09-18 起委托 _common，全技能统一实现）"""
    return _version_key(v)


def load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_stats(service, analytics_root):
    svc_dir = os.path.join(analytics_root, service)
    # 项目级 Bug 池回退：服务级缺失时读 _project/version_bugs.json（scope=project）
    bugs_doc, bugs_scope = load_bugs_doc(analytics_root, service)
    chain = load_json(os.path.join(svc_dir, "version_chain.json"))
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json"))
    if not bugs_doc or not bugs_doc.get("bugs"):
        return None

    bugs = bugs_doc["bugs"]
    chain_versions = [v.get("version") for v in (chain or {}).get("versions", []) if v.get("version")]
    # 【2026-09-18 修复】metrics 索引按**规范键**建立，消费时同样归一 —— 原实现
    # 用 rec["version_to"] 原文当 key、再用裸号去 get()，两边写法不同 → 恒 miss。
    metrics_map = {}
    for r in (metrics or {}).get("records", []):
        ck = norm_version(r.get("version_to"))
        if ck:
            metrics_map[ck] = r

    # 版本全集（按规范键去重，保留首次出现的原始标签用于展示）
    label_of, all_keys = {}, set()
    for v in chain_versions + [b.get("found_in_version") for b in bugs] \
            + [b.get("fixed_in_version") for b in bugs]:
        ck = norm_version(v)
        if ck:
            all_keys.add(ck)
            label_of.setdefault(ck, ck)
    ordered = sorted(all_keys, key=_version_key)
    idx = {ck: i for i, ck in enumerate(ordered)}

    # Bug 侧按规范键分组，避免在循环里反复 norm
    found_by, fixed_by = {}, {}
    for b in bugs:
        fk, xk = norm_version(b.get("found_in_version")), norm_version(b.get("fixed_in_version"))
        if fk:
            found_by.setdefault(fk, []).append(b)
        if xk:
            fixed_by.setdefault(xk, []).append(b)

    per_version = []
    for ck in ordered:
        found = found_by.get(ck, [])
        fixed = fixed_by.get(ck, [])
        sev = {s: 0 for s in SEV_ORDER}
        for b in found:
            sev[b.get("severity", "medium")] = sev.get(b.get("severity", "medium"), 0) + 1
        # 已关闭 / 已解决 均视为「已处理」，计入修复率分母
        done = sum(1 for b in found if b.get("status") in ("closed", "resolved"))
        rec = metrics_map.get(ck)
        m = (rec or {}).get("metrics") or {}
        files_changed = m.get("files_changed")
        # Bug/变更比仅在「服务级」口径下有效；项目级 Bug 不能归因到单服务的变更量
        ratio = (round(len(found) / files_changed, 4)
                 if (bugs_scope == "service" and files_changed) else None)
        per_version.append({
            "version": label_of.get(ck, ck),
            "version_key": ck,
            "found": len(found),
            "fixed": len(fixed),
            "sev": sev,
            "closed_among_found": done,
            "fix_rate": round(done / len(found), 3) if found else None,
            "files_changed": files_changed,
            "change_to_bug_ratio": ratio,
            # 风险分（趋势口径）+ 展示模式：两者必须一起消费，禁止跨模式连线
            "risk_score": m.get("risk_score"),
            "risk_score_mode": m.get("risk_score_mode"),
            "risk_score_enhanced": m.get("risk_score_enhanced"),
            "scoring_mode": m.get("scoring_mode"),
            "risk_score_source": m.get("risk_score_source"),
        })

    # 修复版本间隔（发现版本 -> 修复版本）
    intervals = []
    for b in bugs:
        fk, xk = norm_version(b.get("found_in_version")), norm_version(b.get("fixed_in_version"))
        if fk in idx and xk in idx:
            intervals.append(abs(idx[xk] - idx[fk]))
    avg_interval = round(sum(intervals) / len(intervals), 2) if intervals else None

    total = len(bugs)
    closed_total = sum(1 for b in bugs if b.get("status") == "closed")
    resolved_total = sum(1 for b in bugs if b.get("status") == "resolved")
    done_total = closed_total + resolved_total
    sev_total = {s: 0 for s in SEV_ORDER}
    for b in bugs:
        sev_total[b.get("severity", "medium")] = sev_total.get(b.get("severity", "medium"), 0) + 1

    # 趋势可比性说明：若各版本 risk_score 用了不同模式，则趋势不可直接连线
    modes = {p["scoring_mode"] for p in per_version if p.get("scoring_mode")}
    mode_mixed = len(modes) > 1

    # 端归属预判分布（项目级口径下尤其重要：让前端服务也能看到关联 Bug 的构成）
    side_dist = {}
    for b in bugs:
        side = b.get("side_pre") or classify_bug_side(b)[0]
        side_dist[side] = side_dist.get(side, 0) + 1

    # 端归属拆分（按发现版本）：单服务场景（本次只分析 1 个服务）时 Bug 数据就在本报告，
    # 同样要能拆出前端/后端/通用 —— 对应用户「每份报告都能输出关联关系」的诉求。
    side_breakdown = bugs_side_breakdown(bugs)

    return {
        "service": service,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "per_version": per_version,
        "total": total,
        "closed_total": closed_total,
        "resolved_total": resolved_total,
        "done_total": done_total,
        "fix_rate_total": round(done_total / total, 3) if total else None,
        "sev_total": sev_total,
        "avg_fix_interval": avg_interval,
        "versions_count": len(ordered),
        "source_bugs": bugs_doc.get("source_xlsx"),
        "scoring_modes": sorted(modes),
        "mode_mixed": mode_mixed,
        "bugs_scope": bugs_scope or "service",
        "scope_label": SCOPE_LABEL.get(bugs_scope or "service", ""),
        "side_pre_dist": side_dist,
        "side_breakdown": side_breakdown,
        "attribution_note": bugs_doc.get("attribution_note"),
    }


# ----------------------------------------------------------------------------
# 综合模式：跨服务聚合版本 Bug 趋势
# ----------------------------------------------------------------------------
def build_stats_combined(services, analytics_root):
    """跨服务聚合版本 Bug 趋势（综合报告用）。

    【2026-09-18 项目级池改造】优先读项目级池 `_project/version_bugs.json`
    （scope=project，按提测版本整包关联、不区分前后端服务）；池不存在时才
    退回旧逻辑（聚合各服务 version_bugs.json，无数据的服务贡献为 0）。
    变更文件数改为**参与服务 metrics 求和**（项目级事实），使 Bug/变更比在
    项目口径下重新有效。

    返回结构与 build_stats 一致，供 svg/render 复用。
    """
    all_bugs = []
    sources = []
    bugs_scope = None
    attribution_note = None
    # ① 项目级池优先（只要存在且非空，就用它，避免与服务级副本重复计数）
    pool_path = os.path.join(analytics_root, PROJECT_POOL_DIR, "version_bugs.json")
    pool = load_json(pool_path)
    if pool and pool.get("bugs"):
        all_bugs = pool["bugs"]
        sources.append(pool.get("source_xlsx") or "_project/version_bugs.json")
        bugs_scope = "project"
        attribution_note = pool.get("attribution_note")
    else:
        # ② 旧逻辑：按服务聚合
        for svc in services:
            svc_dir = os.path.join(analytics_root, svc)
            bugs_doc = load_json(os.path.join(svc_dir, "version_bugs.json"))
            if bugs_doc and bugs_doc.get("bugs"):
                all_bugs.extend(bugs_doc["bugs"])
                sources.append(bugs_doc.get("source_xlsx") or svc)
        bugs_scope = "service" if all_bugs else None
    if not all_bugs:
        return None

    # 项目级口径下：参与服务的 metrics 按规范键求和（变更文件数是项目事实）
    files_sum = {}
    for svc in services:
        m_doc = load_json(os.path.join(analytics_root, svc, "service_metrics.json"))
        for r in (m_doc or {}).get("records", []):
            ck = norm_version(r.get("version_to"))
            if not ck:
                continue
            fc = ((r or {}).get("metrics") or {}).get("files_changed")
            if isinstance(fc, (int, float)):
                files_sum[ck] = files_sum.get(ck, 0) + int(fc)

    # 版本全集（跨服务 found + fixed 并集，按规范键归一去重，保留首见标签）
    label_of, all_keys = {}, set()
    for b in all_bugs:
        for v in (b.get("found_in_version"), b.get("fixed_in_version")):
            ck = norm_version(v)
            if ck:
                all_keys.add(ck)
                label_of.setdefault(ck, ck)
    ordered = sorted(all_keys, key=_version_key)
    idx = {ck: i for i, ck in enumerate(ordered)}

    found_by, fixed_by = {}, {}
    for b in all_bugs:
        fk, xk = norm_version(b.get("found_in_version")), norm_version(b.get("fixed_in_version"))
        if fk:
            found_by.setdefault(fk, []).append(b)
        if xk:
            fixed_by.setdefault(xk, []).append(b)

    per_version = []
    for ck in ordered:
        found = found_by.get(ck, [])
        fixed = fixed_by.get(ck, [])
        sev = {s: 0 for s in SEV_ORDER}
        for b in found:
            sev[b.get("severity", "medium")] = sev.get(b.get("severity", "medium"), 0) + 1
        done = sum(1 for b in found if b.get("status") in ("closed", "resolved"))
        fc = files_sum.get(ck)
        per_version.append({
            "version": label_of.get(ck, ck),
            "version_key": ck,
            "found": len(found),
            "fixed": len(fixed),
            "sev": sev,
            "closed_among_found": done,
            "fix_rate": round(done / len(found), 3) if found else None,
            "files_changed": fc,
            "change_to_bug_ratio": (round(len(found) / fc, 4) if fc else None),
        })

    intervals = []
    for b in all_bugs:
        fk, xk = norm_version(b.get("found_in_version")), norm_version(b.get("fixed_in_version"))
        if fk in idx and xk in idx:
            intervals.append(abs(idx[xk] - idx[fk]))
    avg_interval = round(sum(intervals) / len(intervals), 2) if intervals else None

    total = len(all_bugs)
    closed_total = sum(1 for b in all_bugs if b.get("status") == "closed")
    resolved_total = sum(1 for b in all_bugs if b.get("status") == "resolved")
    done_total = closed_total + resolved_total
    sev_total = {s: 0 for s in SEV_ORDER}
    for b in all_bugs:
        sev_total[b.get("severity", "medium")] = sev_total.get(b.get("severity", "medium"), 0) + 1

    side_dist = {}
    for b in all_bugs:
        side = b.get("side_pre") or classify_bug_side(b)[0]
        side_dist[side] = side_dist.get(side, 0) + 1
    # 端归属预判拆分（按版本）—— 综合报告是 Bug 数据的唯一归口，前后端区分在此体现
    side_breakdown = bugs_side_breakdown(all_bugs)

    return {
        "service": "综合（" + " + ".join(services) + "）",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "per_version": per_version,
        "total": total,
        "closed_total": closed_total,
        "resolved_total": resolved_total,
        "done_total": done_total,
        "fix_rate_total": round(done_total / total, 3) if total else None,
        "sev_total": sev_total,
        "avg_fix_interval": avg_interval,
        "versions_count": len(ordered),
        "source_bugs": "、".join(sources) if sources else "version_bugs.json",
        "services": services,
        "bugs_scope": bugs_scope or "service",
        "scope_label": SCOPE_LABEL.get(bugs_scope or "service", ""),
        "side_pre_dist": side_dist,
        "side_breakdown": side_breakdown,
        "attribution_note": attribution_note,
    }


def render_combined_section(stats):
    """综合报告注入用：不包外层 .section（由综合报告「各版本 Bug 数据明细」节包裹），
    仅返回 标题 + bt-wrap 内容 + 作用域样式，供 embed_combined_into_report 替换占位符。
    """
    inner = render_inner(stats)
    scope = stats.get("bugs_scope", "service")
    if scope == "project":
        svc_note = (
            f'<p class="bt-note">＊综合跨服务汇总：Bug 采用<b>项目级关联口径</b>'
            f'（按提测版本整包，不区分前后端服务），共 {stats["total"]} 条。'
            f'参与服务 {len(stats.get("services", []))} 个的变更文件数已按版本求和，'
            f'故 Bug/变更比在项目口径下有效。</p>'
        )
    else:
        svc_note = (
            f'<p class="bt-note">＊综合跨服务汇总：参与服务 {len(stats.get("services", []))} 个，'
            f'仅含各自 version_bugs.json 中已关联的 Bug（未关联 Bug 列表的服务贡献为 0）。</p>'
        )
    return (
        f"{SECTION_STYLE}\n"
        f'<div style="margin:10px 0 4px">\n'
        f'  <div class="bt-section-title"><span>📈</span> 版本 Bug 趋势分析（综合跨服务累计）</div>\n'
        f'  <div class="bt-wrap">{inner}{svc_note}</div>\n'
        f"</div>"
    )


# ----------------------------------------------------------------------------
# 内联 SVG 图表（无 CDN 依赖）
# ----------------------------------------------------------------------------
def svg_stacked_bar(stats, width=920, height=300):
    cats = [p["version"] for p in stats["per_version"]]
    n = max(len(cats), 1)
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 60
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_val = max(
        (sum(p["sev"].values()) for p in stats["per_version"]), default=1
    )
    max_val = max(max_val, 1)
    bar_w = plot_w / n * 0.6
    gap = plot_w / n * 0.4
    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="12">']
    # y 轴网格
    for g in range(0, max_val + 1, max(1, max_val // 5 + 1) if max_val > 5 else 1):
        y = pad_t + plot_h - (g / max_val) * plot_h
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" stroke="#eee"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" text-anchor="end" fill="#888">{g}</text>')
    for i, p in enumerate(stats["per_version"]):
        x = pad_l + i * (bar_w + gap) + gap / 2
        y_cursor = pad_t + plot_h
        for s in SEV_ORDER:
            val = p["sev"].get(s, 0)
            if val == 0:
                continue
            h = (val / max_val) * plot_h
            y_cursor -= h
            svg.append(f'<rect x="{x:.1f}" y="{y_cursor:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{SEV_COLOR[s]}"><title>{p["version"]} · {SEV_LABEL[s]}: {val}</title></rect>')
        # x 标签
        svg.append(f'<text x="{x+bar_w/2:.1f}" y="{pad_t+plot_h+18:.1f}" text-anchor="middle" fill="#333">{p["version"]}</text>')
        svg.append(f'<text x="{x+bar_w/2:.1f}" y="{pad_t+plot_h+36:.1f}" text-anchor="middle" fill="#999" font-size="10">发现 {p["found"]}</text>')
    svg.append(f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{width-pad_r}" y2="{pad_t+plot_h}" stroke="#ccc"/>')
    svg.append("</svg>")
    return "".join(svg)


def svg_fix_rate_bar(stats, width=920, height=260):
    cats = [p["version"] for p in stats["per_version"] if p["fix_rate"] is not None]
    vals = [p["fix_rate"] for p in stats["per_version"] if p["fix_rate"] is not None]
    n = max(len(cats), 1)
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 60
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_val = 1.0
    bar_w = plot_w / n * 0.5
    gap = plot_w / n * 0.5
    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="12">']
    for g in range(0, 101, 25):
        y = pad_t + plot_h - (g / 100) * plot_h
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" stroke="#eee"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" text-anchor="end" fill="#888">{g}%</text>')
    for i, (c, v) in enumerate(zip(cats, vals)):
        x = pad_l + i * (bar_w + gap) + gap / 2
        h = (v / max_val) * plot_h
        y = pad_t + plot_h - h
        color = "#27ae60" if v >= 0.8 else ("#e67e22" if v >= 0.5 else "#c0392b")
        svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}"><title>{c}: {v*100:.0f}%</title></rect>')
        svg.append(f'<text x="{x+bar_w/2:.1f}" y="{y-5:.1f}" text-anchor="middle" fill="#333">{v*100:.0f}%</text>')
        svg.append(f'<text x="{x+bar_w/2:.1f}" y="{pad_t+plot_h+18:.1f}" text-anchor="middle" fill="#333">{c}</text>')
    svg.append(f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{width-pad_r}" y2="{pad_t+plot_h}" stroke="#ccc"/>')
    svg.append("</svg>")
    return "".join(svg)


# ----------------------------------------------------------------------------
# 趋势区块（作用域样式，bt- 前缀，避免与比对报告模板冲突）
# ----------------------------------------------------------------------------
SECTION_STYLE = """<style>
.bt-wrap{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#202124}
.bt-section{background:#fff;border-radius:12px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e8eaed}
.bt-section-title{font-size:20px;font-weight:700;color:#202124;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #1a73e8;display:flex;align-items:center;gap:10px}
.bt-cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.bt-card{background:#f8f9fa;border-radius:10px;padding:16px 20px;flex:1;min-width:150px;border:1px solid #e8eaed}
.bt-num{font-size:28px;font-weight:700}
.bt-lbl{color:#5f6368;font-size:13px;margin-top:4px}
.bt-panel{background:#fff;border-radius:10px;padding:20px;margin-bottom:22px;border:1px solid #eef0f2}
.bt-panel-title{font-size:16px;font-weight:600;margin:0 0 14px;color:#3c4043}
.bt-legend{font-size:13px;color:#555;margin-bottom:10px}
.bt-table{width:100%;border-collapse:collapse;font-size:13px}
.bt-table th,.bt-table td{padding:8px 10px;border-bottom:1px solid #eee;text-align:center}
.bt-table th{background:#fafafa;color:#666;font-weight:600;text-transform:none;white-space:nowrap}
.bt-table tr:hover{background:#fcfcfc}
.bt-note{color:#999;font-size:12px;margin-top:8px;line-height:1.6}
</style>"""


def render_inner(stats):
    total = stats["total"]
    sev_total = stats["sev_total"]
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:14px"><span style="width:12px;height:12px;background:{SEV_COLOR[s]};display:inline-block;border-radius:2px;margin-right:5px"></span>{SEV_LABEL[s]} ({sev_total.get(s,0)})</span>'
        for s in SEV_ORDER
    )
    # 版本表格
    rows = []
    for p in stats["per_version"]:
        sev_cells = " ".join(
            f'<span style="color:{SEV_COLOR[s]};font-weight:600">{p["sev"].get(s,0)}</span>' for s in SEV_ORDER
        )
        fr = f'{p["fix_rate"]*100:.0f}%' if p["fix_rate"] is not None else "—"
        ratio = p["change_to_bug_ratio"] if p["change_to_bug_ratio"] is not None else "—"
        # 风险分（趋势口径 = 静态5维，跨版本可比）；另附本次报告展示模式
        rs = p.get("risk_score")
        rs_txt = f"{rs:.1f}" if isinstance(rs, (int, float)) else "—"
        md = p.get("risk_score_mode") or p.get("scoring_mode")
        md_txt = MODE_LABEL.get(md, md or "—")
        rows.append(
            f"<tr><td>{p['version']}</td><td>{p['found']}</td><td>{p['fixed']}</td>"
            f"<td>{sev_cells}</td><td>{p['closed_among_found']}</td><td>{fr}</td>"
            f"<td>{p['files_changed'] if p['files_changed'] is not None else '—'}</td>"
            f"<td>{ratio}</td><td><b>{rs_txt}</b> <span style='color:#888;font-size:11px'>{md_txt}</span></td></tr>"
        )
    table = (
        '<table class="bt-table"><thead><tr><th>版本</th><th>发现Bug</th><th>修复Bug</th>'
        "<th>严重度(严/高/中/低)</th><th>已关闭/解决</th><th>修复率</th><th>变更文件数</th>"
        "<th>Bug/变更比</th><th>风险分/口径</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )

    # ④ 端归属预判拆分（2026-09-19）：项目级池的前后端区分在此体现
    side_table = ""
    bd = stats.get("side_breakdown") or {}
    if bd and stats.get("bugs_scope") == "project":
        srows = ""
        tot = {"前端": 0, "后端": 0, "通用": 0}
        for ck in sorted(bd, key=_version_key):
            d = bd[ck]
            for k in tot:
                tot[k] += d.get(k, 0)
            srows += (f"<tr><td>{ck}</td><td>{d.get('前端',0)}</td>"
                      f"<td>{d.get('后端',0)}</td><td>{d.get('通用',0)}</td></tr>")
        srows += (f"<tr style='background:#fafafa;font-weight:600'><td>合计</td>"
                  f"<td>{tot['前端']}</td><td>{tot['后端']}</td><td>{tot['通用']}</td></tr>")
        side_table = f"""
<div class="bt-panel">
  <div class="bt-panel-title">④ 端归属预判拆分（按发现版本）</div>
  <table class="bt-table"><thead><tr><th>版本</th><th>前端</th><th>后端</th>
  <th>通用（端归属待定）</th></tr></thead><tbody>{srows}</tbody></table>
  <p class="bt-note">「端归属」为<b>关键词预判</b>（非源数据字段）：源缺陷表无所属端/模块列，
  按标题关键词推断前端 / 后端，未命中归「通用」。可在
  <code>_project/version_bugs.json</code> 中人工修正 <code>side_pre</code> 字段后重跑本区块；
  若缺陷导出能补「所属端/模块」列，重跑 bug_correlate.py 即为精确归因。</p>
</div>"""

    # 跨模式可比性提示（禁止跨模式连线做趋势）
    mode_warn = ""
    if stats.get("mode_mixed"):
        mode_warn = (
            '<p class="bt-note" style="color:#b06000;background:#fff8e6;'
            'border-left:3px solid #f0b429;padding:8px 10px;border-radius:4px">'
            '⚠️ 本服务各版本的风险分口径不一致（'
            + "、".join(MODE_LABEL.get(m, m) for m in stats.get("scoring_modes", []))
            + '）。不同口径的权重不同（静态 base 0.30/core 0.25 ↔ 增强 base 0.20/core 0.20），'
            '直接连线会产生**与变更无关的伪波动**，故趋势请以「风险分（静态5维）」列为准；'
            '「报告分（增强）」仅供单次判断。</p>'
        )

    # 关联口径提示（2026-09-18 项目级池改造）
    scope = stats.get("bugs_scope", "service")
    scope_warn = ""
    if scope == "project":
        side = stats.get("side_pre_dist") or {}
        side_txt = " / ".join(f"{k} {side[k]}" for k in ("前端", "后端", "通用") if k in side) or "—"
        scope_warn = (
            '<p class="bt-note" style="color:#0b5394;background:#eef4fb;'
            'border-left:3px solid #1a73e8;padding:8px 10px;border-radius:4px">'
            '📌 <b>Bug 关联口径：项目级</b> —— Bug 列表按「提测版本整包」关联，'
            '包含前后端全部缺陷，<b>不区分、也不归因到单一服务</b>。'
            f'端归属预判（关键词预判，可人工修正）：{side_txt}。'
            '因此单服务视角下「Bug/变更比」列不适用（标 —）；'
            '如需精确归因，请在缺陷导出中补充「所属端/模块」字段。</p>'
        )

    avg_interval = stats["avg_fix_interval"]
    inner = f"""
<div class="bt-cards">
  <div class="bt-card"><div class="bt-num">{stats['total']}</div><div class="bt-lbl">Bug 总数</div></div>
  <div class="bt-card"><div class="bt-num" style="color:#27ae60">{stats['closed_total']}<span style="font-size:15px;color:#888"> / {stats['resolved_total']}</span></div><div class="bt-lbl">已关闭 / 已解决</div></div>
  <div class="bt-card"><div class="bt-num" style="color:#e67e22">{stats['fix_rate_total']*100:.0f}%</div><div class="bt-lbl">整体修复率</div></div>
  <div class="bt-card"><div class="bt-num">{avg_interval if avg_interval is not None else '—'}</div><div class="bt-lbl">平均修复版本间隔</div></div>
</div>
<div class="bt-panel">
  <div class="bt-panel-title">① 各版本 Bug 数（按严重度堆叠）</div>
  <div class="bt-legend">{legend}</div>
  {svg_stacked_bar(stats)}
</div>
<div class="bt-panel">
  <div class="bt-panel-title">② 各版本修复率（发现版本内已关闭/已解决占比）</div>
  {svg_fix_rate_bar(stats)}
</div>
<div class="bt-panel">
  <div class="bt-panel-title">③ 版本维度明细</div>
  {table}
</div>
{side_table}
{mode_warn}
{scope_warn}
<p class="bt-note">＊本区块由 code-diff-analyzer/scripts/bug_trend.py 生成，单文件无外部依赖。修复率=该版本发现的 Bug 中状态为已关闭或已解决的比例；「风险分」为**静态5维确定性分**（趋势唯一口径，跨版本可比，由 scripts/scoring.py 产出并回写 service_metrics），"报告分（增强10维）"见各版本影响分析报告。关联口径：{stats.get('scope_label') or '服务级'}。数据源：{stats['source_bugs'] or 'version_bugs.json'} ｜ 覆盖版本数：{stats['versions_count']} ｜ 生成时间：{stats['generated_at']}</p>
"""
    return inner


def render_embed_html(stats):
    """注入到比对报告时使用：外层沿用报告模板的 .section / .section-title 样式，内层用 bt- 作用域。"""
    inner = render_inner(stats)
    return (
        f'{SECTION_STYLE}\n'
        f'<div class="section">\n'
        f'  <div class="section-title"><span class="icon">📈</span> 版本 Bug 趋势分析（跨版本累计）</div>\n'
        f'  <div class="bt-wrap">{inner}</div>\n'
        f'</div>'
    )


def render_full_html(stats):
    """独立报告：自带 <html> 外壳 + bt-section 样式。"""
    inner = render_inner(stats)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{stats['service']} 版本 Bug 趋势统计</title>
{SECTION_STYLE}
<style>body{{background:#f5f7fa;margin:0;padding:24px}}</style>
</head>
<body>
<div class="bt-section">
  <div class="bt-section-title"><span>📈</span> {stats['service']} · 版本 Bug 趋势分析（跨版本累计）</div>
  <div class="bt-wrap">{inner}</div>
</div>
</body></html>"""


# ----------------------------------------------------------------------------
# 注入逻辑（幂等：可重复执行）
# ----------------------------------------------------------------------------
START_MARK = "<!-- BUG_TREND_START -->"
END_MARK = "<!-- BUG_TREND_END -->"
PLACEHOLDER = "<!-- BUG_TREND_SECTION -->"


def strip_from_report(report_path, note=None):
    """从报告中移除已注入的 Bug 趋势区块（可逆：只在有 START/END 标记时删除）。

    用途（2026-09-19 用户决策）：Bug 数据归口到综合报告；本次分析含 ≥2 个服务时，
    单服务报告里的 Bug 区块一律撤走，避免同一份数据在两处重复展示。
    撤走后留一行「数据已归口」提示（note），读者不会以为漏做了 Bug 分析。
    返回 "已移除" / "无区块（无需处理）"。
    """
    if not os.path.isfile(report_path):
        raise SystemExit(f"[ERROR] 比对报告不存在: {report_path}")
    with open(report_path, encoding="utf-8") as f:
        html = f.read()
    if note is None:
        # 注意：区块移除后 .bt-note 样式（SECTION_STYLE）也一并消失，故这里用内联样式；
        # 并沿用报告模板的 .section / .section-title，避免裸 <p> 落在两个 section 之间。
        note = (
            '<div class="section">\n'
            '  <div class="section-title"><span class="icon">📈</span> 版本 Bug 趋势分析</div>\n'
            '  <p style="color:#5f6368;font-size:13px;line-height:1.8;margin:0">'
            '＊<b>Bug 数据已按归口规则统一移入综合比对分析报告</b>'
            '（本次分析含多个服务，Bug 按提测版本整包关联，不区分前后端服务）。'
            '单服务报告不再重复展示 Bug 列表与趋势；如需单服务视角，'
            '请把本次分析仅保留该服务后重跑，或对单服务场景执行 bug_trend.py --force。</p>\n'
            '</div>'
        )
    new = re.sub(re.escape(START_MARK) + r"\s*.*?" + re.escape(END_MARK) + r"\s*",
                 note + "\n", html, flags=re.DOTALL)
    if new == html:
        return "无区块（无需处理）"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(new)
    return "已移除"


def embed_into_report(section_html, report_path):
    if not os.path.isfile(report_path):
        raise SystemExit(f"[ERROR] 比对报告不存在: {report_path}")
    with open(report_path, encoding="utf-8") as f:
        html = f.read()

    wrapped = f"{START_MARK}\n{section_html}\n{END_MARK}"

    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, wrapped, 1)
        mode = "占位符替换"
    elif START_MARK in html:
        html = re.sub(re.escape(START_MARK) + r".*?" + re.escape(END_MARK),
                      wrapped, html, flags=re.DOTALL)
        mode = "整块替换(幂等)"
    else:
        # fallback：注入到 </body> 之前
        if "</body>" in html:
            html = html.replace("</body>", wrapped + "\n</body>", 1)
        else:
            html = html + "\n" + wrapped
        mode = "回退注入(</body>前)"

    safe_write_report(report_path, html)
    return mode


# 综合模式占位符 / 幂等块标记（由 gen_combined_report.py 在「各版本 Bug 数据明细」节写入占位符）
PLACEHOLDER_COMBINED = "<!-- BUG_TREND_COMBINED -->"
START_MARK_COMBINED = "<!-- BUG_TREND_COMBINED_START -->"
END_MARK_COMBINED = "<!-- BUG_TREND_COMBINED_END -->"


def embed_combined_into_report(section_html, report_path):
    if not os.path.isfile(report_path):
        raise SystemExit(f"[ERROR] 综合比对报告不存在: {report_path}")
    with open(report_path, encoding="utf-8") as f:
        html = f.read()

    wrapped = f"{START_MARK_COMBINED}\n{section_html}\n{END_MARK_COMBINED}"

    if PLACEHOLDER_COMBINED in html:
        html = html.replace(PLACEHOLDER_COMBINED, wrapped, 1)
        mode = "占位符替换"
    elif START_MARK_COMBINED in html:
        html = re.sub(re.escape(START_MARK_COMBINED) + r".*?" + re.escape(END_MARK_COMBINED),
                      wrapped, html, flags=re.DOTALL)
        mode = "整块替换(幂等)"
    else:
        # fallback：注入到 </body> 之前
        if "</body>" in html:
            html = html.replace("</body>", wrapped + "\n</body>", 1)
        else:
            html = html + "\n" + wrapped
        mode = "回退注入(</body>前)"

    safe_write_report(report_path, html)
    return mode


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
def main():
    import sys
    ap = argparse.ArgumentParser(description="Code Diff Analyzer · 版本 Bug 趋势统计")
    ap.add_argument("--service", help="服务名（单服务模式，与 --combined 互斥）")
    ap.add_argument("--combined", action="store_true",
                    help="综合模式：跨服务聚合注入（需 --services + --report）")
    ap.add_argument("--services", nargs="+", help="综合模式参与服务列表")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常", help="工作区根目录")
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--out", help="独立报告输出 HTML 路径（缺省自动生成）")
    ap.add_argument("--report", help="将趋势区块注入到此比对报告 HTML（与 --out 互斥，优先级更高）")
    ap.add_argument("--strip", action="store_true",
                    help="反向操作：从 --report 中移除已注入的 Bug 趋势区块")
    ap.add_argument("--force", action="store_true",
                    help="忽略「≥2 服务时 Bug 数据归口综合报告」规则，强制注入单服务报告")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")

    # —— 移除模式（Bug 归口综合报告后，清理单服务报告里的旧区块）——
    if args.strip:
        if not args.report:
            sys.stderr.write("[ERROR] --strip 需 --report\n")
            raise SystemExit(1)
        print(f"[OK] Bug 趋势区块{strip_from_report(args.report)}: {args.report}")
        return

    # —— 综合模式：跨服务聚合注入 ——
    if args.combined:
        if not args.services:
            sys.stderr.write("[ERROR] 综合模式需 --services 指定参与服务\n")
            raise SystemExit(1)
        if not args.report:
            sys.stderr.write("[ERROR] 综合模式需 --report 指定综合报告 HTML\n")
            raise SystemExit(1)
        stats = build_stats_combined(args.services, analytics_root)
        if not stats:
            sys.stderr.write("[ERROR] 所有参与服务均无 version_bugs.json（无关联 Bug），跳过综合注入\n")
            raise SystemExit(1)
        section = render_combined_section(stats)
        mode = embed_combined_into_report(section, args.report)
        print(f"[OK] 综合趋势区块已{mode}注入: {args.report}")
        print(f"     聚合服务={len(args.services)} Bug 总数={stats['total']} "
              f"已关闭={stats['closed_total']} 已解决={stats['resolved_total']} "
              f"修复率={stats['fix_rate_total']*100:.0f}% 覆盖版本={stats['versions_count']}")
        return

    # —— 单服务模式 ——
    if not args.service:
        sys.stderr.write("[ERROR] 请指定 --service（单服务）或 --combined --services（综合）\n")
        raise SystemExit(1)

    # 【2026-09-19 用户决策】Bug 数据归口规则：
    #   本次分析含 ≥2 个服务时，Bug 相关数据只放在综合报告；单服务报告不再展示，
    #   避免同一份 Bug 在 N+1 份报告里重复出现。仅当分析对象是 1 个服务时才注入。
    #   判定依据：显式 --services（本次分析的服务清单）；缺省视为单服务。
    batch = args.services or [args.service]
    if len(batch) > 1 and args.report and not args.force:
        print(f"[SKIP] 本次分析含 {len(batch)} 个服务（{'、'.join(batch)}），"
              f"Bug 数据归口综合报告，单服务报告不注入 —— {args.report}")
        print("       （确需注入请加 --force；如需清理已注入区块用 --strip）")
        return

    stats = build_stats(args.service, analytics_root)
    if not stats:
        sys.stderr.write("[ERROR] 未找到该服务的 version_bugs.json，且项目级池 _project/version_bugs.json 也不存在或为空；"
                         "请先运行 bug_correlate.py --xlsx <bug列表.xlsx> 导入（服务级用 --service <svc>，"
                         "项目级用 --service _project）\n")
        raise SystemExit(1)

    if args.report:
        section = render_embed_html(stats)
        mode = embed_into_report(section, args.report)
        scope_txt = "项目级池回退" if stats.get("bugs_scope") == "project" else "服务级"
        print(f"[OK] 趋势区块已{mode}注入: {args.report}")
        print(f"     [口径={scope_txt}] Bug 总数={stats['total']} 已关闭={stats['closed_total']} "
              f"已解决={stats['resolved_total']} "
              f"修复率={stats['fix_rate_total']*100:.0f}% 覆盖版本={stats['versions_count']} "
              f"端归属预判={stats.get('side_pre_dist')}")
        return

    out = args.out or os.path.join(
        args.workspace, "report", "code-diff", args.service,
        f"{args.service}_bug趋势统计_{datetime.now().strftime('%Y%m%d')}.html"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_full_html(stats))
    print(f"[OK] 趋势报告已生成: {out}")
    print(f"     Bug 总数={stats['total']} 已关闭={stats['closed_total']} 已解决={stats['resolved_total']} "
          f"修复率={stats['fix_rate_total']*100:.0f}% 覆盖版本={stats['versions_count']}")


if __name__ == "__main__":
    main()
