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
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # noqa: E402  统一错误提示层（含缺失的 sys 兜底）

SEV_ORDER = ["critical", "high", "medium", "low"]
SEV_LABEL = {"critical": "严重", "high": "高", "medium": "一般/中", "low": "低/建议"}
SEV_COLOR = {"critical": "#c0392b", "high": "#e67e22", "medium": "#f1c40f", "low": "#27ae60"}


def version_key(v):
    if not v:
        return (0,)
    s = str(v).lower()
    parts = []
    for tok in "".join(c if c.isdigit() or c == "." else " " for c in s).split():
        for n in tok.split("."):
            if n.isdigit():
                parts.append(int(n))
    return tuple(parts) if parts else (0,)


def load_json(path):
    """读取 JSON：不存在→None（静默）；存在但格式异常→明确 WARN 并返回 None。"""
    return cdx_errors.try_json(path)


def build_stats(service, analytics_root):
    svc_dir = os.path.join(analytics_root, service)
    bugs_doc = load_json(os.path.join(svc_dir, "version_bugs.json"))
    chain = load_json(os.path.join(svc_dir, "version_chain.json"))
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json"))
    if not bugs_doc or not bugs_doc.get("bugs"):
        return None

    bugs = bugs_doc["bugs"]
    chain_versions = [v.get("version") for v in (chain or {}).get("versions", []) if v.get("version")]
    metrics_map = {r.get("version_to"): r for r in (metrics or {}).get("records", []) if r.get("version_to")}

    # 版本全集
    all_versions = set(chain_versions)
    for b in bugs:
        if b.get("found_in_version"):
            all_versions.add(b["found_in_version"])
        if b.get("fixed_in_version"):
            all_versions.add(b["fixed_in_version"])
    ordered = sorted(all_versions, key=version_key)
    idx = {v: i for i, v in enumerate(ordered)}

    per_version = []
    for v in ordered:
        found = [b for b in bugs if b.get("found_in_version") == v]
        fixed = [b for b in bugs if b.get("fixed_in_version") == v]
        sev = {s: 0 for s in SEV_ORDER}
        for b in found:
            sev[b.get("severity", "medium")] = sev.get(b.get("severity", "medium"), 0) + 1
        # 已关闭 / 已解决 均视为「已处理」，计入修复率分母
        done = sum(1 for b in found if b.get("status") in ("closed", "resolved"))
        rec = metrics_map.get(v)
        files_changed = rec.get("metrics", {}).get("files_changed") if rec else None
        per_version.append({
            "version": v,
            "found": len(found),
            "fixed": len(fixed),
            "sev": sev,
            "closed_among_found": done,
            "fix_rate": round(done / len(found), 3) if found else None,
            "files_changed": files_changed,
            "change_to_bug_ratio": round(len(found) / files_changed, 4) if files_changed else None,
        })

    # 修复版本间隔（发现版本 -> 修复版本）
    intervals = []
    for b in bugs:
        fv, fxv = b.get("found_in_version"), b.get("fixed_in_version")
        if fv in idx and fxv in idx:
            intervals.append(abs(idx[fxv] - idx[fv]))
    avg_interval = round(sum(intervals) / len(intervals), 2) if intervals else None

    total = len(bugs)
    closed_total = sum(1 for b in bugs if b.get("status") == "closed")
    resolved_total = sum(1 for b in bugs if b.get("status") == "resolved")
    done_total = closed_total + resolved_total
    sev_total = {s: 0 for s in SEV_ORDER}
    for b in bugs:
        sev_total[b.get("severity", "medium")] = sev_total.get(b.get("severity", "medium"), 0) + 1

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
    }


# ----------------------------------------------------------------------------
# 综合模式：跨服务聚合版本 Bug 趋势
# ----------------------------------------------------------------------------
def build_stats_combined(services, analytics_root):
    """跨服务聚合版本 Bug 趋势（综合报告用）。

    仅聚合各服务 version_bugs.json 中实际存在的 Bug；
    某服务无 version_bugs.json 时其贡献为 0（不影响其它服务）。
    返回结构与 build_stats 一致（per_version / total / closed_total /
    resolved_total / done_total / sev_total / fix_rate_total ...），
    供 svg_stacked_bar / render_inner / render_combined_section 复用。
    """
    all_bugs = []
    sources = []
    for svc in services:
        svc_dir = os.path.join(analytics_root, svc)
        bugs_doc = load_json(os.path.join(svc_dir, "version_bugs.json"))
        if bugs_doc and bugs_doc.get("bugs"):
            all_bugs.extend(bugs_doc["bugs"])
            sources.append(bugs_doc.get("source_xlsx") or svc)
    if not all_bugs:
        return None

    # 版本全集（跨服务 found + fixed 并集）
    all_versions = set()
    for b in all_bugs:
        if b.get("found_in_version"):
            all_versions.add(b["found_in_version"])
        if b.get("fixed_in_version"):
            all_versions.add(b["fixed_in_version"])
    ordered = sorted(all_versions, key=version_key)
    idx = {v: i for i, v in enumerate(ordered)}

    per_version = []
    for v in ordered:
        found = [b for b in all_bugs if b.get("found_in_version") == v]
        fixed = [b for b in all_bugs if b.get("fixed_in_version") == v]
        sev = {s: 0 for s in SEV_ORDER}
        for b in found:
            sev[b.get("severity", "medium")] = sev.get(b.get("severity", "medium"), 0) + 1
        done = sum(1 for b in found if b.get("status") in ("closed", "resolved"))
        per_version.append({
            "version": v,
            "found": len(found),
            "fixed": len(fixed),
            "sev": sev,
            "closed_among_found": done,
            "fix_rate": round(done / len(found), 3) if found else None,
            "files_changed": None,
            "change_to_bug_ratio": None,
        })

    intervals = []
    for b in all_bugs:
        fv, fxv = b.get("found_in_version"), b.get("fixed_in_version")
        if fv in idx and fxv in idx:
            intervals.append(abs(idx[fxv] - idx[fv]))
    avg_interval = round(sum(intervals) / len(intervals), 2) if intervals else None

    total = len(all_bugs)
    closed_total = sum(1 for b in all_bugs if b.get("status") == "closed")
    resolved_total = sum(1 for b in all_bugs if b.get("status") == "resolved")
    done_total = closed_total + resolved_total
    sev_total = {s: 0 for s in SEV_ORDER}
    for b in all_bugs:
        sev_total[b.get("severity", "medium")] = sev_total.get(b.get("severity", "medium"), 0) + 1

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
    }


def render_combined_section(stats):
    """综合报告注入用：不包外层 .section（由综合报告「各版本 Bug 数据明细」节包裹），
    仅返回 标题 + bt-wrap 内容 + 作用域样式，供 embed_combined_into_report 替换占位符。
    """
    inner = render_inner(stats)
    svc_note = (
        f'<p class="bt-note">＊综合跨服务汇总：参与服务 {len(stats.get("services", []))} 个，'
        f'仅含各自 version_bugs.json 中已关联的 Bug（未关联 Bug 列表的服务贡献为 0）。'
        f'本轮仅 portal-backend 关联 Bug 列表，故柱状图反映其 {stats["total"]} 条 Bug 的跨版本分布。</p>'
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
        rows.append(
            f"<tr><td>{p['version']}</td><td>{p['found']}</td><td>{p['fixed']}</td>"
            f"<td>{sev_cells}</td><td>{p['closed_among_found']}</td><td>{fr}</td>"
            f"<td>{p['files_changed'] if p['files_changed'] is not None else '—'}</td><td>{ratio}</td></tr>"
        )
    table = (
        '<table class="bt-table"><thead><tr><th>版本</th><th>发现Bug</th><th>修复Bug</th>'
        "<th>严重度(严/高/中/低)</th><th>已关闭/解决</th><th>修复率</th><th>变更文件数</th><th>Bug/变更比</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
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
<p class="bt-note">＊本区块由 code-diff-analyzer/scripts/bug_trend.py 生成，单文件无外部依赖。修复率=该版本发现的 Bug 中状态为已关闭或已解决的比例；综合报告中「已关闭 / 已解决」取各服务 version_bugs.json 汇总（无关联 Bug 的服务贡献为 0）。数据源：{stats['source_bugs'] or 'version_bugs.json'} ｜ 覆盖版本数：{stats['versions_count']} ｜ 生成时间：{stats['generated_at']}</p>
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


def embed_into_report(section_html, report_path):
    if not os.path.isfile(report_path):
        cdx_errors.die("比对报告不存在（--report）", "路径: %s" % os.path.abspath(report_path),
                       hint="先跑单服务分析生成 HTML 报告，或用 --out 直接输出趋势报告。", code=3)
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

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return mode


# 综合模式占位符 / 幂等块标记（由 gen_combined_report.py 在「各版本 Bug 数据明细」节写入占位符）
PLACEHOLDER_COMBINED = "<!-- BUG_TREND_COMBINED -->"
START_MARK_COMBINED = "<!-- BUG_TREND_COMBINED_START -->"
END_MARK_COMBINED = "<!-- BUG_TREND_COMBINED_END -->"


def embed_combined_into_report(section_html, report_path):
    if not os.path.isfile(report_path):
        cdx_errors.die("综合比对报告不存在（--report）", "路径: %s" % os.path.abspath(report_path),
                       hint="先用 gen_combined_report.py 生成综合报告，再注入趋势区块。", code=3)
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

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
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
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")

    # —— 综合模式：跨服务聚合注入 ——
    if args.combined:
        if not args.services:
            cdx_errors.die("综合模式需 --services", hint="例：--combined --services portal-backend manage-front", code=2)
        if not args.report:
            cdx_errors.die("综合模式需 --report", hint="指定要注入趋势区块的综合报告 HTML 路径。", code=2)
        stats = build_stats_combined(args.services, analytics_root)
        if not stats:
            cdx_errors.die("参与服务均无 version_bugs.json（无关联 Bug）",
                           "服务: %s" % ", ".join(args.services),
                           hint="先对各服务运行 bug_correlate.py 导入 Bug 数据。", code=4)
        section = render_combined_section(stats)
        mode = embed_combined_into_report(section, args.report)
        print(f"[OK] 综合趋势区块已{mode}注入: {args.report}")
        print(f"     聚合服务={len(args.services)} Bug 总数={stats['total']} "
              f"已关闭={stats['closed_total']} 已解决={stats['resolved_total']} "
              f"修复率={stats['fix_rate_total']*100:.0f}% 覆盖版本={stats['versions_count']}")
        return

    # —— 单服务模式 ——
    if not args.service:
        cdx_errors.die("需指定服务",
                       hint="单服务: --service <名>；综合: --combined --services <名1> <名2>", code=2)
    stats = build_stats(args.service, analytics_root)
    if not stats:
        cdx_errors.die("未找到服务 %s 的 version_bugs.json 或为空" % args.service,
                       "查找目录: %s" % os.path.join(analytics_root, args.service),
                       hint="先运行 bug_correlate.py 导入 Bug 数据；核对 --analytics-root 是否正确。", code=4)

    if args.report:
        section = render_embed_html(stats)
        mode = embed_into_report(section, args.report)
        print(f"[OK] 趋势区块已{mode}注入: {args.report}")
        print(f"     Bug 总数={stats['total']} 已关闭={stats['closed_total']} 已解决={stats['resolved_total']} "
              f"修复率={stats['fix_rate_total']*100:.0f}% 覆盖版本={stats['versions_count']}")
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
    cdx_errors.guard(main)
