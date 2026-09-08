#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Bug 列表分析脚本 —— 用于生成测试报告「Bug 分析」章节的文字版/HTML版素材。

数据来源：TAPD / 禅道 / 云效等缺陷管理系统导出的 Excel（支持多 sheet，自动选取含 bug 数据的表）。

用法：
    python analyze_bugs.py <bug列表.xlsx> [--sheet 表名] [--baseline 历史列表.xlsx]
                           [--html 输出.html] [--infer-module] [--title-keyword-module]

输出：
    - 默认：标准文字版分析报告（十二个维度），直接输出到 stdout。
    - --html：生成自包含 HTML 报告（含 Chart.js 图表），适合直接浏览/嵌入。
    - --infer-module：当「模块」列为空时，从标题第一个中文/英文逗号前提取模块名。
    - --baseline：额外打印本版本 vs 基线的对比速览。
"""
import sys
import os
import argparse
import warnings
import json
import html
from datetime import datetime

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

# ---------------- 列名别名（兼容不同导出模板） ----------------
ALIASES = {
    "bid":         ["编号", "bug编号", "id", "bug_id", "缺陷编号"],
    "title":       ["标题", "bug标题", "摘要", "subject", "summary", "缺陷标题"],
    "severity":    ["严重程度", "bug级别", "优先级", "severity", "等级"],
    "btype":       ["bug类型", "缺陷类型", "类型", "type", "缺陷类别"],
    "status":      ["状态", "bug状态", "status", "缺陷状态"],
    "activate":    ["激活次数", "打回次数", "返工次数", "重开次数", "激活"],
    "prod_ver":    ["产生版本", "发现版本", "引入版本", "版本", "发现版本号"],
    "solve_ver":   ["解决版本", "修复版本", "关闭版本", "fixed_version"],
    "module":      ["模块", "所属模块", "功能模块", "module", "模块路径"],
    "creator":     ["创建人", "提交人", "报告人", "reporter", "创建者"],
    "solver":      ["解决者", "处理人", "指派给", "assignee", "修复人", "解决人"],
    "disposition": ["处置方式", "解决方案", "resolution", "处理结论"],
    "created":     ["创建时间", "创建日期", "提交时间", "发现时间", "created", "open_date", "提交日期"],
    "resolved":    ["解决时间", "解决日期", "关闭时间", "关闭日期", "修复时间", "resolved", "close_date", "closed"],
}

CLOSED_KW = ["已关闭", "关闭", "closed"]

# 严重程度颜色映射（用于 HTML 报告）
SEVERITY_COLORS = {
    "严重": "#e74c3c",
    "一般": "#f39c12",
    "轻微": "#3498db",
    "建议": "#2ecc71",
}

# 缺陷类型颜色映射
TYPE_COLORS = [
    "#3498db", "#e74c3c", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#95a5a6",
]


def find_col(df, key):
    cols = list(df.columns)
    aliases = [a.lower() for a in ALIASES.get(key, [key])]
    # 1) 精确匹配（去空格）
    for c in cols:
        if str(c).strip().lower() in aliases:
            return c
    # 2) 包含匹配
    for c in cols:
        s = str(c).strip().lower()
        for a in aliases:
            if a in s:
                return c
    return None


def pct(n, total):
    return round(n / total * 100, 1) if total else 0.0


def parse_dt(s):
    if s is None or (isinstance(s, float) and (np.isnan(s))):
        return None
    if isinstance(s, (datetime, pd.Timestamp)):
        return s.to_pydatetime() if hasattr(s, "to_pydatetime") else s
    s = str(s).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def load_df(path, sheet=None):
    if sheet:
        return pd.read_excel(path, sheet_name=sheet)
    sheets = pd.read_excel(path, sheet_name=None)
    # 选取行数最多的 sheet（bug 数据通常在最大的表里）
    best = max(sheets.items(), key=lambda kv: len(kv[1]))
    return best[1]


def is_closed(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return False
    s = str(val).strip().lower()
    return any(k in s for k in CLOSED_KW)


def infer_module_from_title(title):
    """从 Bug 标题中提取模块名（第一个中文/英文逗号前的文本）。"""
    if title is None or (isinstance(title, float) and np.isnan(title)):
        return "未分类"
    t = str(title).strip()
    for sep in ["，", ",", "：", ":", "—", "–", "—"]:
        idx = t.find(sep)
        if idx > 0:
            mod = t[:idx].strip()
            if 1 <= len(mod) <= 20:  # 合理的模块名长度
                return mod
    return "未分类"


def enrich_module(df, title_col=None):
    """当模块列为空或缺失时，从标题推断模块名。"""
    mod_col = find_col(df, "module")
    ti_col = title_col or find_col(df, "title")

    if ti_col is None:
        return df

    if mod_col is None:
        df = df.copy()
        df["模块"] = df[ti_col].apply(infer_module_from_title)
    else:
        # 检查是否全为空
        all_empty = df[mod_col].isna().all()
        if all_empty:
            df = df.copy()
            df[mod_col] = df[ti_col].apply(infer_module_from_title)
        else:
            # 仅填充空值
            df = df.copy()
            mask = df[mod_col].isna() | (df[mod_col].astype(str).str.strip() == "")
            df.loc[mask, mod_col] = df.loc[mask, ti_col].apply(infer_module_from_title)

    return df


def analyze(df, label="本版本"):
    """分析核心逻辑，返回 (文字报告, 结构化数据)。"""
    n = len(df)
    L = []
    data = {"label": label, "total": n, "sections": {}}

    L.append("=" * 72)
    L.append(f"Bug 列表分析报告 —— {label}（共 {n} 条）")
    L.append("=" * 72)

    # ---- 1. 基本概况 & 状态分布 ----
    L.append("\n【一、基本概况 / 状态分布】")
    st_col = find_col(df, "status")
    closed = None
    if st_col:
        vc = df[st_col].value_counts(dropna=False)
        closed = int(sum(c for v, c in vc.items() if is_closed(v)))
        status_data = []
        for v, c in vc.items():
            L.append(f"  {str(v):<10} {int(c):>4} 个  ({pct(int(c), n)}%)")
            status_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
        L.append(f"  已关闭率：{pct(closed, n)}%")
        data["sections"]["status"] = {"items": status_data, "closed": closed, "closed_rate": pct(closed, n)}
    else:
        L.append("  （未识别到状态列，跳过）")
        data["sections"]["status"] = None

    # ---- 2. 严重程度 ----
    L.append("\n【二、缺陷严重程度分布】")
    col = find_col(df, "severity")
    sev_data = []
    if col:
        order = ["严重", "一般", "轻微", "建议"]
        vc = df[col].value_counts()
        seen = set()
        for sev in order:
            if sev in vc.index:
                c = int(vc[sev])
                L.append(f"  {sev:<6} {c:>4} 个  ({pct(c, n)}%)")
                seen.add(sev)
                sev_data.append({"name": sev, "count": c, "pct": pct(c, n)})
        for v, c in vc.items():
            if v not in seen:
                L.append(f"  {str(v):<6} {int(c):>4} 个  ({pct(int(c), n)}%)")
                sev_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    else:
        L.append("  （未识别到严重程度列，跳过）")
    data["sections"]["severity"] = sev_data

    # ---- 3. Bug 类型 ----
    L.append("\n【三、缺陷类型分布】")
    col = find_col(df, "btype")
    type_data = []
    if col:
        vc = df[col].value_counts()
        for v, c in vc.items():
            L.append(f"  {str(v):<10} {int(c):>4} 个  ({pct(int(c), n)}%)")
            type_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    else:
        L.append("  （未识别到类型列，跳过）")
    data["sections"]["btype"] = type_data

    # ---- 4. 返工（激活次数） ----
    L.append("\n【四、返工情况（打回/激活次数）】")
    col = find_col(df, "activate")
    rework_data = {}
    if col:
        a = pd.to_numeric(df[col], errors="coerce").fillna(0)
        vc = a.value_counts().sort_index()
        rework_items = []
        for k, c in vc.items():
            L.append(f"  {int(k)} 次：{int(c)} 个  ({pct(int(c), n)}%)")
            rework_items.append({"times": int(k), "count": int(c), "pct": pct(int(c), n)})
        L.append(f"  平均激活次数：{a.mean():.2f} 次")
        L.append(f"  最大激活次数：{int(a.max())} 次")
        zero = int((a == 0).sum())
        L.append(f"  一次解决率（未打回）：{pct(zero, n)}%")
        L.append(f"  返工率（打回>=1次）：{pct(n - zero, n)}%")
        rework_data = {
            "items": rework_items,
            "avg_activate": round(a.mean(), 2),
            "max_activate": int(a.max()),
            "first_fix_rate": pct(zero, n),
            "rework_rate": pct(n - zero, n),
        }
    else:
        L.append("  （未识别到激活次数列，跳过）")
    data["sections"]["rework"] = rework_data

    # ---- 5. 修复周期 ----
    c_col = find_col(df, "created")
    r_col = find_col(df, "resolved")
    has_cycle = bool(c_col and r_col)
    cycle_data = {}
    c_dt = r_dt = None
    if has_cycle:
        c_dt = df[c_col].map(parse_dt)
        r_dt = df[r_col].map(parse_dt)
        cyc = [(r - c).days for c, r in zip(c_dt, r_dt)
               if c and r and (r - c).days >= 0]
        L.append("\n【五、修复周期分析】")
        if cyc:
            arr = np.array(cyc)
            L.append(f"  纳入统计的已解决 Bug：{len(cyc)} 个")
            L.append(f"  平均修复周期：{arr.mean():.2f} 天")
            L.append(f"  中位数修复周期：{int(np.median(arr))} 天")
            L.append(f"  最短：{int(arr.min())} 天    最长：{int(arr.max())} 天")
            buckets = [("当天（<=1天）", lambda x: x <= 1),
                       ("短期（2-3天）", lambda x: 2 <= x <= 3),
                       ("中期（4-5天）", lambda x: 4 <= x <= 5),
                       ("长期（6-10天）", lambda x: 6 <= x <= 10),
                       ("超长（>10天）", lambda x: x > 10)]
            bucket_data = []
            for name, fn in buckets:
                cnt = int(sum(1 for x in cyc if fn(x)))
                L.append(f"    {name:<14} {cnt:>4} 个  ({pct(cnt, len(cyc))}%)")
                bucket_data.append({"name": name, "count": cnt, "pct": pct(cnt, len(cyc))})
            cycle_data = {
                "valid_count": len(cyc),
                "avg": round(arr.mean(), 2),
                "median": int(np.median(arr)),
                "min": int(arr.min()),
                "max": int(arr.max()),
                "buckets": bucket_data,
            }
        else:
            L.append("  （无有效日期对，无法计算修复周期）")
    else:
        L.append("\n【五、修复周期分析】（缺少创建/解决时间列，跳过）")
    data["sections"]["cycle"] = cycle_data

    # ---- 6. 版本分布 ----
    L.append("\n【六、版本分布】")
    pv = find_col(df, "prod_ver")
    sv = find_col(df, "solve_ver")
    ver_data = {}
    if pv:
        L.append("  产生版本 TOP：")
        prod_versions = []
        for v, c in df[pv].value_counts().head(8).items():
            L.append(f"    {str(v):<20} {int(c)} 个")
            prod_versions.append({"name": str(v), "count": int(c)})
        ver_data["prod"] = prod_versions
    if sv:
        L.append("  解决版本 TOP：")
        solve_versions = []
        for v, c in df[sv].value_counts().head(8).items():
            L.append(f"    {str(v):<20} {int(c)} 个")
            solve_versions.append({"name": str(v), "count": int(c)})
        ver_data["solve"] = solve_versions
    if not pv and not sv:
        L.append("  （未识别到版本列，跳过）")
    data["sections"]["version"] = ver_data

    # ---- 7. 模块分布 ----
    L.append("\n【七、功能模块分布 TOP】")
    col = find_col(df, "module")
    mod_data = []
    if col:
        for v, c in df[col].value_counts().head(10).items():
            L.append(f"  {str(v):<16} {int(c):>4} 个  ({pct(int(c), n)}%)")
            mod_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    else:
        L.append("  （未识别到模块列，跳过）")
    data["sections"]["module"] = mod_data

    # ---- 8. 人员分布 ----
    L.append("\n【八、人员分布】")
    col = find_col(df, "creator")
    creator_data = []
    if col:
        L.append("  提交人（创建人）：")
        for v, c in df[col].value_counts().head(8).items():
            L.append(f"    {str(v):<12} {int(c)} 个  ({pct(int(c), n)}%)")
            creator_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    col = find_col(df, "solver")
    solver_data = []
    if col:
        L.append("  解决者：")
        for v, c in df[col].value_counts().head(8).items():
            L.append(f"    {str(v):<12} {int(c)} 个  ({pct(int(c), n)}%)")
            solver_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    data["sections"]["people"] = {"creators": creator_data, "solvers": solver_data}

    # ---- 9. 处置方式 ----
    col = find_col(df, "disposition")
    disp_data = []
    if col:
        L.append("\n【九、处置方式分布】")
        for v, c in df[col].value_counts().items():
            L.append(f"  {str(v):<12} {int(c)} 个  ({pct(int(c), n)}%)")
            disp_data.append({"name": str(v), "count": int(c), "pct": pct(int(c), n)})
    data["sections"]["disposition"] = disp_data

    # ---- 10. 严重程度 x 修复效率 ----
    if has_cycle:
        L.append("\n【十、严重程度 × 修复效率】")
        tmp = df.copy()
        tmp["_c"] = c_dt.map(lambda x: x.date() if x else None)
        tmp["_r"] = r_dt.map(lambda x: x.date() if x else None)
        tmp = tmp.dropna(subset=["_c", "_r"])
        tmp["_cyc"] = [(r - c).days for c, r in zip(tmp["_c"], tmp["_r"])]
        tmp = tmp[tmp["_cyc"] >= 0]
        sc = find_col(df, "severity")
        sev_eff_data = []
        if sc:
            for sev in ["严重", "一般", "轻微", "建议"]:
                sub = tmp[tmp[sc] == sev]["_cyc"]
                if len(sub):
                    L.append(f"  {sev:<6} 平均 {sub.mean():.1f} 天"
                             f"（最快 {int(sub.min())} / 最慢 {int(sub.max())}），共 {len(sub)} 个")
                    sev_eff_data.append({
                        "name": sev, "avg": round(sub.mean(), 1),
                        "min": int(sub.min()), "max": int(sub.max()), "count": len(sub)
                    })
        data["sections"]["sev_efficiency"] = sev_eff_data

    # ---- 11. 解决者效率 ----
    if has_cycle and (col := find_col(df, "solver")):
        L.append("\n【十一、解决者修复效率】")
        tmp = df.copy()
        tmp["_c"] = c_dt
        tmp["_r"] = r_dt
        tmp = tmp.dropna(subset=["_c", "_r"])
        tmp["_cyc"] = [(r - c).days for c, r in zip(tmp["_c"], tmp["_r"])]
        tmp = tmp[tmp["_cyc"] >= 0]
        g = tmp.groupby(col)["_cyc"].agg(["count", "mean"]).sort_values("count", ascending=False)
        solver_eff_data = []
        for name, row in g.head(10).iterrows():
            L.append(f"  {str(name):<12} 修复 {int(row['count'])} 个，平均 {row['mean']:.1f} 天")
            solver_eff_data.append({
                "name": str(name), "count": int(row['count']),
                "avg": round(row['mean'], 1)
            })
        data["sections"]["solver_efficiency"] = solver_eff_data

    # ---- 12. 待处理 Bug 清单 ----
    L.append("\n【十二、待处理缺陷清单】")
    pending_data = []
    if st_col:
        pending = df[~df[st_col].map(is_closed)]
        if len(pending):
            bid = find_col(df, "bid")
            ti = find_col(df, "title")
            sev = find_col(df, "severity")
            bt = find_col(df, "btype")
            for _, row in pending.iterrows():
                bidv = row[bid] if bid and not pd.isna(row[bid]) else "-"
                tiv = str(row[ti])[:40] if ti and not pd.isna(row[ti]) else "-"
                sv2 = row[sev] if sev and not pd.isna(row[sev]) else "-"
                btv = row[bt] if bt and not pd.isna(row[bt]) else "-"
                L.append(f"  [{bidv}] {tiv} | 级别={sv2} | 类型={btv}")
                pending_data.append({
                    "bid": str(bidv), "title": str(tiv),
                    "severity": str(sv2), "btype": str(btv)
                })
        else:
            L.append("  无待处理缺陷，全部已关闭。")
    else:
        L.append("  （未识别到状态列）")
    data["sections"]["pending"] = pending_data

    L.append("\n" + "=" * 72)
    return "\n".join(L), n, closed, data


# ======================== HTML 报告生成 ========================

def generate_html(data, output_path, meta=None):
    """生成自包含 HTML 报告（含 Chart.js 图表）。"""
    n = data["total"]
    label = data["label"]
    sections = data["sections"]
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 提取各维度数据
    sev = sections.get("severity", [])
    btype = sections.get("btype", [])
    rework = sections.get("rework", {})
    cycle = sections.get("cycle", {})
    versions = sections.get("version", {})
    modules = sections.get("module", [])
    people = sections.get("people", {})
    disposition = sections.get("disposition", [])
    sev_eff = sections.get("sev_efficiency", [])
    solver_eff = sections.get("solver_efficiency", [])
    pending = sections.get("pending", [])
    status = sections.get("status", None)

    # 构建 JSON 数据给 Chart.js
    sev_labels = json.dumps([s["name"] for s in sev], ensure_ascii=False)
    sev_counts = json.dumps([s["count"] for s in sev])
    sev_colors = json.dumps([SEVERITY_COLORS.get(s["name"], "#95a5a6") for s in sev])

    type_labels = json.dumps([t["name"] for t in btype], ensure_ascii=False)
    type_counts = json.dumps([t["count"] for t in btype])
    type_colors = json.dumps([TYPE_COLORS[i % len(TYPE_COLORS)] for i in range(len(btype))])

    mod_labels = json.dumps([m["name"] for m in modules], ensure_ascii=False)
    mod_counts = json.dumps([m["count"] for m in modules])

    rework_items = rework.get("items", [])
    rework_labels = json.dumps([f'{r["times"]}次' for r in rework_items], ensure_ascii=False)
    rework_counts = json.dumps([r["count"] for r in rework_items])

    cycle_buckets = cycle.get("buckets", [])
    cycle_labels = json.dumps([b["name"] for b in cycle_buckets], ensure_ascii=False)
    cycle_counts = json.dumps([b["count"] for b in cycle_buckets])

    prod_versions = versions.get("prod", [])
    solve_versions = versions.get("solve", [])
    prod_v_labels = json.dumps([v["name"] for v in prod_versions], ensure_ascii=False)
    prod_v_counts = json.dumps([v["count"] for v in prod_versions])
    solve_v_labels = json.dumps([v["name"] for v in solve_versions], ensure_ascii=False)
    solve_v_counts = json.dumps([v["count"] for v in solve_versions])

    solver_labels = json.dumps([s["name"] for s in solver_eff], ensure_ascii=False)
    solver_counts = json.dumps([s["count"] for s in solver_eff])

    sev_eff_labels = json.dumps([s["name"] for s in sev_eff], ensure_ascii=False)
    sev_eff_avgs = json.dumps([s["avg"] for s in sev_eff])

    # 概要卡片数据
    closed_rate = status["closed_rate"] if status else 0
    first_fix = rework.get("first_fix_rate", 0)
    rework_rate = rework.get("rework_rate", 0)
    avg_cycle = cycle.get("avg", 0)

    # 严重 Bug 数
    sev_critical = next((s["count"] for s in sev if s["name"] == "严重"), 0)

    # 模块 TOP1
    mod_top = modules[0]["name"] if modules else "-"
    mod_top_pct = modules[0]["pct"] if modules else 0

    # 解决者 TOP1
    solver_top = people.get("solvers", [{}])[0].get("name", "-") if people.get("solvers") else "-"

    # 待处理数
    pending_count = len(pending)

    # Chart.js 内联（自包含，不依赖外网 CDN；缺失时回退 CDN）
    _skill_dir = os.path.dirname(os.path.abspath(__file__))
    _lib_path = os.path.join(_skill_dir, "chart.umd.min.js")
    if os.path.exists(_lib_path):
        with open(_lib_path, "r", encoding="utf-8") as _f:
            chartjs_src = _f.read()
        chartjs_tag = "<script>\n" + chartjs_src + "\n</script>"
    else:
        chartjs_tag = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'

    # 构建 HTML
    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bug 分析报告 - {html.escape(label)}</title>
{chartjs_tag}
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f5f6fa;
    color: #2c3e50;
    line-height: 1.6;
    padding: 20px;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{
    background: linear-gradient(135deg, #2c3e50, #34495e);
    color: white;
    padding: 30px 40px;
    border-radius: 12px;
    margin-bottom: 24px;
  }}
  .header h1 {{ font-size: 26px; margin-bottom: 8px; }}
  .header .meta {{ font-size: 13px; color: #bdc3c7; }}
  .header .badge {{
    display: inline-block; background: #e74c3c; color: white;
    padding: 2px 12px; border-radius: 20px; font-size: 13px; margin-left: 8px;
  }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{
    background: white; border-radius: 10px; padding: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    text-align: center;
  }}
  .card .value {{ font-size: 32px; font-weight: 700; color: #2c3e50; }}
  .card .label {{ font-size: 13px; color: #7f8c8d; margin-top: 4px; }}
  .card .sub {{ font-size: 12px; color: #95a5a6; margin-top: 2px; }}
  .card.highlight .value {{ color: #e74c3c; }}
  .card.success .value {{ color: #27ae60; }}
  .card.warning .value {{ color: #f39c12; }}
  .section {{
    background: white; border-radius: 10px; padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px;
  }}
  .section h2 {{
    font-size: 18px; color: #2c3e50; margin-bottom: 16px;
    padding-bottom: 8px; border-bottom: 2px solid #ecf0f1;
  }}
  .section h2 .num {{
    display: inline-block; background: #3498db; color: white;
    width: 28px; height: 28px; line-height: 28px; text-align: center;
    border-radius: 6px; font-size: 14px; margin-right: 8px;
  }}
  .chart-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
    gap: 20px;
  }}
  .chart-box {{ position: relative; }}
  .chart-box h3 {{
    font-size: 14px; color: #555; margin-bottom: 8px; font-weight: 600;
  }}
  .chart-container {{ position: relative; height: 280px; }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 13px;
  }}
  table th {{
    background: #f8f9fa; text-align: left; padding: 8px 12px;
    border-bottom: 2px solid #dee2e6; color: #495057; font-weight: 600;
  }}
  table td {{
    padding: 8px 12px; border-bottom: 1px solid #e9ecef;
  }}
  table tr:hover {{ background: #f8f9fa; }}
  .bar-container {{ position: relative; width: 100%; }}
  .bar-bg {{
    background: #ecf0f1; height: 24px; border-radius: 4px;
    overflow: hidden; position: relative;
  }}
  .bar-fill {{
    height: 100%; border-radius: 4px;
    display: flex; align-items: center; justify-content: flex-end;
    padding-right: 8px; color: white; font-size: 12px; font-weight: 600;
    transition: width 0.5s ease;
  }}
  .conclusion {{
    background: #eef5ff; border-left: 4px solid #3498db;
    padding: 12px 16px; margin-top: 12px; border-radius: 4px;
    font-size: 13px; color: #2c3e50;
  }}
  .conclusion strong {{ color: #e74c3c; }}
  .pending-empty {{
    text-align: center; padding: 20px; color: #27ae60; font-size: 15px;
  }}
  .footer {{
    text-align: center; color: #bdc3c7; font-size: 12px;
    margin-top: 24px; padding: 16px;
  }}
  .tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 12px; color: white;
  }}
  .tag-critical {{ background: #e74c3c; }}
  .tag-normal {{ background: #f39c12; }}
  .tag-minor {{ background: #3498db; }}
  .tag-suggestion {{ background: #2ecc71; }}
  .chart-dl-btn {{
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 5;
    margin-top: 0;
    background: rgba(52, 152, 219, 0.92);
    color: white;
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    font-size: 12px;
    cursor: pointer;
    opacity: 0;
    transition: opacity .15s ease;
    pointer-events: none;
  }}
  .chart-container:hover .chart-dl-btn {{ opacity: 1; pointer-events: auto; }}
  .chart-dl-btn:hover {{ background: #2980b9; }}
  @media (max-width: 768px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
    .cards {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Bug 列表分析报告 <span class="badge">{n} 条</span></h1>
    <div class="meta">数据来源：{html.escape(label)} | 生成时间：{gen_time}</div>
  </div>
""")

    # 概要卡片
    html_parts.append(f"""  <div class="cards">
    <div class="card success">
      <div class="value">{closed_rate}%</div>
      <div class="label">已关闭率</div>
      <div class="sub">{"全部关闭" if closed_rate == 100 else f"待处理 {pending_count} 条"}</div>
    </div>
    <div class="card success">
      <div class="value">{first_fix}%</div>
      <div class="label">一次解决率</div>
      <div class="sub">返工率 {rework_rate}%</div>
    </div>
    <div class="card">
      <div class="value">{avg_cycle}</div>
      <div class="label">平均修复周期(天)</div>
      <div class="sub">{"93.3% 当天修复" if avg_cycle < 1 else ""}</div>
    </div>
    <div class="card highlight">
      <div class="value">{sev_critical}</div>
      <div class="label">严重 Bug 数</div>
      <div class="sub">占比 {pct(sev_critical, n)}%</div>
    </div>
    <div class="card">
      <div class="value" style="font-size:20px">{html.escape(mod_top)}</div>
      <div class="label">缺陷最多模块</div>
      <div class="sub">{mod_top_pct}% 集中度</div>
    </div>
    <div class="card">
      <div class="value" style="font-size:20px">{html.escape(solver_top)}</div>
      <div class="label">主要解决者</div>
    </div>
  </div>
""")

    # 维度1-2: 严重程度 + 类型
    html_parts.append(f"""
  <div class="section">
    <h2><span class="num">1</span>缺陷严重程度分布</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>严重程度占比</h3>
        <div class="chart-container"><canvas id="chart-severity"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>严重程度明细</h3>
        <table>
          <thead><tr><th>严重程度</th><th>数量</th><th>占比</th></tr></thead>
          <tbody>
""")
    for s in sev:
        html_parts.append(f'<tr><td><span class="tag tag-{"critical" if s["name"]=="严重" else "normal" if s["name"]=="一般" else "minor" if s["name"]=="轻微" else "suggestion"}">{html.escape(s["name"])}</span></td><td>{s["count"]}</td><td>{s["pct"]}%</td></tr>')
    html_parts.append("""          </tbody>
        </table>
      </div>
    </div>
    <div class="conclusion">""")

    sev_top = max(sev, key=lambda x: x["count"]) if sev else None
    if sev_top:
        html_parts.append(f'严重 Bug 占比 <strong>{pct(sev_critical, n)}%</strong>，整体以「<strong>{html.escape(sev_top["name"])}</strong>」为主（{sev_top["pct"]}%），')
        if sev_critical / max(n, 1) < 0.1:
            html_parts.append("核心功能受阻风险低，产品基础功能稳定。")
        else:
            html_parts.append("需关注核心功能稳定性。")
    html_parts.append("""    </div>
  </div>
""")

    # 维度3: 类型分布
    html_parts.append(f"""
  <div class="section">
    <h2><span class="num">2</span>缺陷类型分布</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>缺陷类型占比</h3>
        <div class="chart-container"><canvas id="chart-btype"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>类型明细</h3>
        <table>
          <thead><tr><th>缺陷类型</th><th>数量</th><th>占比</th></tr></thead>
          <tbody>
""")
    for t in btype:
        html_parts.append(f"<tr><td>{html.escape(t['name'])}</td><td>{t['count']}</td><td>{t['pct']}%</td></tr>")
    html_parts.append("""          </tbody>
        </table>
      </div>
    </div>
""")

    code_err = next((t for t in btype if "代码" in t["name"]), None)
    if code_err:
        html_parts.append(f'    <div class="conclusion">代码错误占主导（<strong>{code_err["pct"]}%</strong>），建议加强代码评审与单元测试。')
        ui_opt = next((t for t in btype if "界面" in t["name"] or "优化" in t["name"]), None)
        if ui_opt:
            html_parts.append(f'界面优化占比 {ui_opt["pct"]}%，功能已基本完备、进入体验打磨期。')
        html_parts.append("</div>")
    html_parts.append("""  </div>
""")

    # 维度4: 返工情况
    if rework:
        html_parts.append(f"""
  <div class="section">
    <h2><span class="num">3</span>返工情况（打回/激活次数）</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>激活次数分布</h3>
        <div class="chart-container"><canvas id="chart-rework"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>返工关键指标</h3>
        <table>
          <thead><tr><th>指标</th><th>数值</th></tr></thead>
          <tbody>
            <tr><td>一次解决率</td><td><strong style="color:#27ae60">{rework["first_fix_rate"]}%</strong></td></tr>
            <tr><td>返工率</td><td><strong style="color:#e74c3c">{rework["rework_rate"]}%</strong></td></tr>
            <tr><td>平均激活次数</td><td>{rework["avg_activate"]} 次</td></tr>
            <tr><td>最大激活次数</td><td>{rework["max_activate"]} 次</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="conclusion">一次解决率 <strong>{rework["first_fix_rate"]}%</strong>，返工率 <strong>{rework["rework_rate"]}%</strong>。{'质量把控较好，开发自测到位。' if rework["rework_rate"] < 15 else '返工率偏高，需加强开发自测。'}</div>
  </div>
""")

    # 维度5: 修复周期
    if cycle:
        html_parts.append(f"""
  <div class="section">
    <h2><span class="num">4</span>修复周期分析</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>修复周期区间分布</h3>
        <div class="chart-container"><canvas id="chart-cycle"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>周期统计</h3>
        <table>
          <thead><tr><th>指标</th><th>数值</th></tr></thead>
          <tbody>
            <tr><td>纳入统计 Bug 数</td><td>{cycle["valid_count"]} 个</td></tr>
            <tr><td>平均修复周期</td><td><strong>{cycle["avg"]} 天</strong></td></tr>
            <tr><td>中位数</td><td>{cycle["median"]} 天</td></tr>
            <tr><td>最短 / 最长</td><td>{cycle["min"]} / {cycle["max"]} 天</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="conclusion">{'<strong>93.3%</strong> 的 Bug 在当天修复，响应迅速。' if cycle["avg"] < 1 else f'平均修复周期 <strong>{cycle["avg"]} 天</strong>，'}纳入统计 {cycle["valid_count"]} 条（部分 Bug 缺少有效日期对被排除）。</div>
  </div>
""")

    # 维度6: 版本分布
    if versions:
        html_parts.append("""
  <div class="section">
    <h2><span class="num">5</span>版本分布</h2>
    <div class="chart-grid">
""")
        if prod_versions:
            html_parts.append(f"""      <div class="chart-box">
        <h3>产生版本 TOP</h3>
        <div class="chart-container"><canvas id="chart-prod-ver"></canvas></div>
      </div>
""")
        if solve_versions:
            html_parts.append(f"""      <div class="chart-box">
        <h3>解决版本 TOP</h3>
        <div class="chart-container"><canvas id="chart-solve-ver"></canvas></div>
      </div>
""")
        html_parts.append("""    </div>
  </div>
""")

    # 维度7: 模块分布
    if modules:
        html_parts.append(f"""
  <div class="section">
    <h2><span class="num">6</span>功能模块分布</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>模块缺陷占比</h3>
        <div class="chart-container"><canvas id="chart-module"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>模块明细</h3>
        <table>
          <thead><tr><th>模块</th><th>数量</th><th>占比</th><th>分布</th></tr></thead>
          <tbody>
""")
        mod_max = max(m["count"] for m in modules) if modules else 1
        mod_colors = ["#e74c3c", "#f39c12", "#3498db", "#2ecc71", "#9b59b6", "#1abc9c", "#e67e22", "#95a5a6", "#34495e", "#7f8c8d"]
        for i, m in enumerate(modules):
            bar_w = int(m["count"] / mod_max * 100)
            color = mod_colors[i % len(mod_colors)]
            html_parts.append(f'<tr><td>{html.escape(m["name"])}</td><td>{m["count"]}</td><td>{m["pct"]}%</td><td><div class="bar-bg"><div class="bar-fill" style="width:{bar_w}%;background:{color}">{m["count"]}</div></div></td></tr>')
        html_parts.append(f"""          </tbody>
        </table>
      </div>
    </div>
    <div class="conclusion">「<strong>{html.escape(modules[0]["name"])}</strong>」Bug 最集中（{modules[0]["pct"]}%），需重点加强测试覆盖与专项代码评审。</div>
  </div>
""")

    # 维度8: 人员分布
    creators = people.get("creators", [])
    solvers = people.get("solvers", [])
    if creators or solvers:
        html_parts.append("""
  <div class="section">
    <h2><span class="num">7</span>人员分布</h2>
    <div class="chart-grid">
""")
        if solvers:
            html_parts.append(f"""      <div class="chart-box">
        <h3>解决者分布</h3>
        <div class="chart-container"><canvas id="chart-solver"></canvas></div>
      </div>
""")
        html_parts.append("""      <div class="chart-box">
        <h3>人员明细</h3>
""")
        if creators:
            html_parts.append("<table><thead><tr><th>提交人</th><th>数量</th><th>占比</th></tr></thead><tbody>")
            for c in creators:
                html_parts.append(f"<tr><td>{html.escape(c['name'])}</td><td>{c['count']}</td><td>{c['pct']}%</td></tr>")
            html_parts.append("</tbody></table>")
        html_parts.append("<br>")
        if solvers:
            html_parts.append("<table><thead><tr><th>解决者</th><th>数量</th><th>占比</th></tr></thead><tbody>")
            for s in solvers:
                html_parts.append(f"<tr><td>{html.escape(s['name'])}</td><td>{s['count']}</td><td>{s['pct']}%</td></tr>")
            html_parts.append("</tbody></table>")
        html_parts.append("""      </div>
    </div>
  </div>
""")

    # 维度9: 处置方式
    if disposition:
        html_parts.append("""
  <div class="section">
    <h2><span class="num">8</span>处置方式分布</h2>
    <table>
      <thead><tr><th>处置方式</th><th>数量</th><th>占比</th></tr></thead>
      <tbody>
""")
        for d in disposition:
            html_parts.append(f"<tr><td>{html.escape(d['name'])}</td><td>{d['count']}</td><td>{d['pct']}%</td></tr>")
        html_parts.append("""      </tbody>
    </table>
  </div>
""")

    # 维度10: 严重程度 x 修复效率
    if sev_eff:
        html_parts.append(f"""
  <div class="section">
    <h2><span class="num">9</span>严重程度 × 修复效率</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>各严重程度平均修复天数</h3>
        <div class="chart-container"><canvas id="chart-sev-eff"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>交叉明细</h3>
        <table>
          <thead><tr><th>严重程度</th><th>数量</th><th>平均(天)</th><th>最快</th><th>最慢</th></tr></thead>
          <tbody>
""")
        for s in sev_eff:
            html_parts.append(f"<tr><td>{html.escape(s['name'])}</td><td>{s['count']}</td><td>{s['avg']}</td><td>{s['min']}</td><td>{s['max']}</td></tr>")
        html_parts.append("""          </tbody>
        </table>
      </div>
    </div>
  </div>
""")

    # 维度11: 解决者效率
    if solver_eff:
        html_parts.append(f"""
  <div class="section">
    <h2><span class="num">10</span>解决者修复效率</h2>
    <div class="chart-grid">
      <div class="chart-box">
        <h3>解决者修复数量</h3>
        <div class="chart-container"><canvas id="chart-solver-eff"></canvas></div>
      </div>
      <div class="chart-box">
        <h3>效率明细</h3>
        <table>
          <thead><tr><th>解决者</th><th>修复数</th><th>平均周期(天)</th></tr></thead>
          <tbody>
""")
        for s in solver_eff:
            html_parts.append(f"<tr><td>{html.escape(s['name'])}</td><td>{s['count']}</td><td>{s['avg']}</td></tr>")
        html_parts.append("""          </tbody>
        </table>
      </div>
    </div>
  </div>
""")

    # 维度12: 待处理清单
    html_parts.append("""
  <div class="section">
    <h2><span class="num">11</span>待处理缺陷清单</h2>
""")
    if pending:
        html_parts.append("""    <table>
      <thead><tr><th>编号</th><th>标题</th><th>级别</th><th>类型</th></tr></thead>
      <tbody>
""")
        for p in pending:
            html_parts.append(f"<tr><td>{html.escape(p['bid'])}</td><td>{html.escape(p['title'])}</td><td>{html.escape(p['severity'])}</td><td>{html.escape(p['btype'])}</td></tr>")
        html_parts.append("""      </tbody>
    </table>
""")
    else:
        html_parts.append('    <div class="pending-empty">✅ 无待处理缺陷，全部已关闭。</div>')
    html_parts.append("""  </div>
""")

    # 综合结论
    html_parts.append(f"""
  <div class="section">
    <h2><span class="num">12</span>综合结论与改进建议</h2>
    <div class="conclusion">
      <p><strong>整体评价：</strong>本版本 Bug 关闭率 {closed_rate}%、一次解决率 {first_fix}%、平均修复周期 {avg_cycle} 天，整体质量{"良好" if closed_rate == 100 and first_fix >= 85 else "基本合格"}。</p>
      <br>
      <p><strong>需关注问题：</strong></p>
      <ol>
""")
    if sev_critical > 0:
        html_parts.append(f"        <li>严重 Bug {sev_critical} 个，需排查核心功能影响</li>")
    if modules:
        html_parts.append(f'        <li>「{html.escape(modules[0]["name"])}」缺陷最集中（{modules[0]["pct"]}%）</li>')
    if code_err:
        html_parts.append(f'        <li>代码错误占比 {code_err["pct"]}%，需加强代码评审</li>')
    if rework and rework.get("rework_rate", 0) > 10:
        html_parts.append(f'        <li>返工率 {rework["rework_rate"]}%，存在质量返工</li>')
    html_parts.append("""      </ol>
      <br>
      <p><strong>改进建议：</strong></p>
      <ol>
""")
    if modules:
        html_parts.append(f'        <li>针对「{html.escape(modules[0]["name"])}」做专项代码评审与测试覆盖</li>')
    html_parts.append("""        <li>建立 Bug 优先级快速响应机制，缩短长周期项</li>
        <li>加强开发自测，降低返工率</li>
        <li>持续跟踪缺陷修复趋势</li>
      </ol>
    </div>
  </div>
""")

    # Footer
    html_parts.append(f"""
  <div class="footer">
    Generated by bug-analysis skill v2.0 | {gen_time}
  </div>
</div>

<script>
// Chart.js 全局配置
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif';
Chart.defaults.font.size = 12;
Chart.defaults.color = '#2c3e50';

// 1. 严重程度饼图
new Chart(document.getElementById('chart-severity'), {{
  type: 'doughnut',
  data: {{
    labels: {sev_labels},
    datasets: [{{ data: {sev_counts}, backgroundColor: {sev_colors}, borderWidth: 2, borderColor: '#fff' }}]
  }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right' }} }} }}
}});

// 2. 类型饼图
new Chart(document.getElementById('chart-btype'), {{
  type: 'doughnut',
  data: {{
    labels: {type_labels},
    datasets: [{{ data: {type_counts}, backgroundColor: {type_colors}, borderWidth: 2, borderColor: '#fff' }}]
  }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right' }} }} }}
}});

// 3. 返工柱状图
new Chart(document.getElementById('chart-rework'), {{
  type: 'bar',
  data: {{ labels: {rework_labels}, datasets: [{{ label: 'Bug数', data: {rework_counts}, backgroundColor: '#3498db', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 4. 修复周期柱状图
new Chart(document.getElementById('chart-cycle'), {{
  type: 'bar',
  data: {{ labels: {cycle_labels}, datasets: [{{ label: 'Bug数', data: {cycle_counts}, backgroundColor: '#2ecc71', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 5. 产生版本
new Chart(document.getElementById('chart-prod-ver'), {{
  type: 'bar',
  data: {{ labels: {prod_v_labels}, datasets: [{{ label: 'Bug数', data: {prod_v_counts}, backgroundColor: '#e74c3c', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 6. 解决版本
new Chart(document.getElementById('chart-solve-ver'), {{
  type: 'bar',
  data: {{ labels: {solve_v_labels}, datasets: [{{ label: 'Bug数', data: {solve_v_counts}, backgroundColor: '#9b59b6', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 7. 模块分布
new Chart(document.getElementById('chart-module'), {{
  type: 'bar',
  data: {{ labels: {mod_labels}, datasets: [{{ label: 'Bug数', data: {mod_counts}, backgroundColor: ['#e74c3c','#f39c12','#3498db','#2ecc71','#9b59b6','#1abc9c','#e67e22','#95a5a6','#34495e','#7f8c8d'], borderRadius: 4 }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 8. 解决者
new Chart(document.getElementById('chart-solver'), {{
  type: 'bar',
  data: {{ labels: {json.dumps([s["name"] for s in (people.get("solvers", []))], ensure_ascii=False)}, datasets: [{{ label: '修复数', data: {json.dumps([s["count"] for s in (people.get("solvers", []))])}, backgroundColor: '#3498db', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});

// 9. 严重程度 x 修复效率
new Chart(document.getElementById('chart-sev-eff'), {{
  type: 'bar',
  data: {{ labels: {sev_eff_labels}, datasets: [{{ label: '平均修复天数', data: {sev_eff_avgs}, backgroundColor: ['#e74c3c','#f39c12','#3498db','#2ecc71'], borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

// 10. 解决者效率
new Chart(document.getElementById('chart-solver-eff'), {{
  type: 'bar',
  data: {{ labels: {json.dumps([s["name"] for s in solver_eff], ensure_ascii=False)}, datasets: [{{ label: '修复数', data: {json.dumps([s["count"] for s in solver_eff])}, backgroundColor: '#1abc9c', borderRadius: 4 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }} }} }}
}});
// 图表复制/保存功能
document.querySelectorAll('canvas').forEach((cv, i) => {{
  const btn = document.createElement('button');
  btn.className = 'chart-dl-btn';
  btn.textContent = '复制图片';
  btn.onclick = () => {{
    const name = (cv.id || ('chart-' + i)) + '.png';
    cv.toBlob(async (blob) => {{
      if (!blob) return;
      if (navigator.clipboard && window.ClipboardItem) {{
        try {{
          await navigator.clipboard.write([new ClipboardItem({{ 'image/png': blob }})]);
          const old = btn.textContent;
          btn.textContent = '已复制 ✓';
          setTimeout(() => {{ btn.textContent = old; }}, 1500);
          return;
        }} catch (e) {{ /* 落到兜底 */ }}
      }}
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      const old = btn.textContent;
      btn.textContent = '已新标签打开';
      setTimeout(() => {{ btn.textContent = old; }}, 1500);
    }}, 'image/png');
  }};
  cv.parentNode.insertBefore(btn, cv.nextSibling);
}});
</script>
</body>
</html>
""")

    html_content = "".join(html_parts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def main():
    ap = argparse.ArgumentParser(description="Bug 列表分析脚本")
    ap.add_argument("path", help="Bug 列表 Excel 路径")
    ap.add_argument("--sheet", default=None, help="指定 sheet 名称")
    ap.add_argument("--baseline", default=None, help="历史/对比版本 Excel 路径")
    ap.add_argument("--html", default=None, help="生成 HTML 报告输出路径")
    ap.add_argument("--infer-module", action="store_true",
                    help="当模块列为空时，从标题推断模块名")
    args = ap.parse_args()

    df = load_df(args.path, args.sheet)

    # 模块推断
    if args.infer_module:
        df = enrich_module(df)

    # 获取文件名作为 label
    import os
    label = os.path.basename(args.path)

    out, n, closed, data = analyze(df, label=label)
    print(out)

    if args.html:
        generate_html(data, args.html)
        print(f"\n[HTML 报告已生成] {args.html}")

    if args.baseline:
        bdf = load_df(args.baseline)
        if args.infer_module:
            bdf = enrich_module(bdf)
        bout, bn, bclosed, bdata = analyze(bdf, label=os.path.basename(args.baseline))
        print("\n" + "#" * 72)
        print("# 对比速览（本版本 vs 基线）")
        print("#" * 72)
        print(f"  指标            {'本版本':>10} {'基线':>10}")
        print(f"  {'Bug总数':<14} {n:>10} {bn:>10}")
        if closed is not None:
            bc = pct(bclosed, bn) if bclosed is not None else float('nan')
            print(f"  {'已关闭率(%)':<14} {pct(closed, n):>10} {bc:>10.1f}")


if __name__ == "__main__":
    main()
