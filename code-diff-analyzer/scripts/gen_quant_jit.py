#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_quant_jit.py — 把量化风险评分 + JIT 缺陷预测 注入报告（幂等）。apex 能力整合。

两种用法：
  【单服务报告】把分数环 + JIT 标签【合并进风险横幅】（与「综合风险等级」标签一体），
  详细维度表收为轻量卡放在「变更总览」前（QUANT_JIT_SECTION 占位符）。
    python scripts/gen_quant_jit.py --report 报告.html --stats stats.json
    python scripts/gen_quant_jit.py --report 报告.html --auto            # 从报告 HTML 自动派生 stats（零配置，默认每次都跑）
    python scripts/gen_quant_jit.py --report 报告.html --stats stats.json --service portal-backend --workspace <ws>  # 增强10维

  【综合报告】按服务注入「各服务量化风险 & JIT 预测」汇总表到 QUANT_JIT_COMBINED 占位符。
    python scripts/gen_quant_jit.py --report 综合.html --combined --services svc1 svc2 --workspace <ws>

stats JSON 结构（输入给引擎 quant_jit_risk.compute）：
{
  "base_risk": "high",          // high/medium/low（来自 code-diff Step5 定性结论）
  "total_lines": 8,             // diff 增+删总行数
  "file_count": 2,              // 变更文件数
  "core_file_count": 1,         // 核心模块文件数（用于核心模块占比）
  "avg_density": 4,             // 可选，缺省 = total_lines/file_count
  "description": "学校版本到期降级逻辑...",  // 用于 JIT 核心模式匹配
  "files": ["UniversityServiceImpl.java"],   // 可选，辅助 JIT 匹配
  "data_format_change": false,  // 可选，触发 JIT 数据格式红标
  "historical_metrics": { "buggy_ratio":0.2,"churn_rate":1.5,"mod_count":15,"author_exp":42,"days_since":3 }
}

--auto 派生逻辑（从已生成的单服务报告 HTML 解析，零配置）：
  - base_risk：风险横幅 class="risk-banner (high|medium|low)"
  - file_count：变更总览 tbody 行数
  - core_file_count：变更总览各行（文件路径+说明）命中 JIT 核心模式数
  - total_lines：代码块中 class="added"/"removed" 行数之和
  - description / files：变更总览各行文本拼接
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quant_jit_risk import compute, generate_jit, auto_historical, CORE_PATTERNS  # noqa
from scoring import derive_stats as derive_stats_from_metrics  # noqa
from _common import norm_version, safe_write_report  # noqa

# —— 单服务：注入守卫 ——
START = "<!-- QUANT_JIT_START -->"
END = "<!-- QUANT_JIT_END -->"
INLINE_START = "<!-- QJ_INLINE_START -->"
INLINE_END = "<!-- QJ_INLINE_END -->"
PLACEHOLDER = "<!-- QUANT_JIT_SECTION -->"
FALLBACK_MARKER = "<!-- ===== Section: 变更总览 ===== -->"

# —— 综合：守卫 ——
COMBINED_START = "<!-- QUANT_JIT_COMBINED_START -->"
COMBINED_END = "<!-- QUANT_JIT_COMBINED_END -->"
COMBINED_PLACEHOLDER = "<!-- QUANT_JIT_COMBINED -->"

LEVEL_COLOR = {"🔴 高风险": "#d93025", "🟡 中风险": "#f9ab00", "🟢 低风险": "#1e8e3e"}
JIT_COLOR = {"🔴 高风险预测": "#d93025", "🟡 中等风险预测": "#f9ab00", "🟢 低风险预测": "#1e8e3e"}
RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def dim_weight(q, name):
    """取维度权重。

    【2026-09-18 修复】原实现本地维护了一份「维度中文名 -> 权重键」的映射（wkey），
    与 quant_jit_risk.py 里那份重复 —— 改一处漏一处。现统一读 compute() 返回的
    `dimension_weights`（单一真源），并对旧维度名做别名兼容。
    """
    dw = q.get("dimension_weights")
    if isinstance(dw, dict) and name in dw:
        return dw[name]
    # 兼容：历史 stats 用旧维度名「历史Bug频率」
    alias = {"历史Bug频率": "Bug未解决率"}
    return (dw or {}).get(alias.get(name, name), 0)


# ============================================================
# 单服务：渲染
# ============================================================
def render_inline(q, jit):
    """合并进风险横幅标题行的分数环 + JIT 标签（inline 片段，带守卫）。

    用「彩色边框 + 白底」呈现，避免实心大色块像报错提示；与标题同一行不折断。
    """
    quant_color = LEVEL_COLOR.get(q["level"], "#f9ab00")
    jit_color = JIT_COLOR.get(jit["prediction"], "#f9ab00")
    return ("""%s<span class="risk-score-inline">
      <span class="risk-ring" style="border-color:%s;color:%s" title="量化风险评分(0-100)">
        <span class="rn">%s</span><span class="rc">/100</span>
      </span>
      <span class="risk-jit" style="border-color:%s;color:%s" title="JIT 缺陷预测">%s</span>
    </span>%s""" % (INLINE_START, quant_color, quant_color, q["percent"],
                  jit_color, jit_color, esc(jit["prediction"]), INLINE_END))


def render_detail(q, jit):
    """变更总览前的轻量详情卡（维度表 + JIT 依据），带守卫。"""
    mode_cn = "增强10维（含历史度量）" if q["mode"] == "enhanced" else "静态5维（无历史度量）"
    dim_rows = ""
    for name, sc in q["dimensions"].items():
        w = dim_weight(q, name)
        dim_rows += ("<tr><td>%s</td><td style='text-align:center'>%s</td>"
                     "<td style='text-align:center'>%s%%</td>"
                     "<td style='text-align:center'>+%s</td></tr>") % (
            esc(name), sc, int(w * 100), q["contributions"].get(name, 0))
    basis = "".join("<li>%s</li>" % esc(b) for b in jit["basis"]) or "<li>—</li>"
    eff = jit["effectiveness"]
    return """%s<div class="qj-detail">
      <style>
      .qj-detail{margin:0 0 24px;background:#fbfcfe;border:1px solid #e3e8ef;border-radius:10px;padding:14px 18px}
      .qj-dtitle{font-size:13px;font-weight:700;color:#334;margin-bottom:10px}
      .qj-dims{width:100%%;border-collapse:collapse;font-size:12.5px}
      .qj-dims th{background:#f1f5fb;color:#334;padding:6px 8px;text-align:center;border:1px solid #e3e8ef}
      .qj-dims td{padding:5px 8px;border:1px solid #e3e8ef}
      .qj-dims td:first-child{text-align:left;font-weight:600}
      .qj-basis{font-size:12.5px;color:#333;margin-top:10px;line-height:1.7}
      .qj-basis ul{margin:4px 0 0;padding-left:18px}
      .qj-eff{font-size:11.5px;color:#667;margin-top:8px;border-top:1px dashed #ddd;padding-top:6px}
      </style>
      <div class="qj-dtitle">📊 量化评分明细 &amp; JIT 缺陷预测依据（apex-diff-analyzer 能力整合 · %s）</div>
      <table class="qj-dims"><thead><tr><th>维度</th><th>得分(0-5)</th><th>权重</th><th>贡献</th></tr></thead><tbody>%s</tbody></table>
      <div class="qj-basis"><strong>JIT 预测依据：</strong><ul>%s</ul>
        <div class="qj-eff">%s；Top-20%% 高风险变更覆盖 %s 真实缺陷，AUC %s。<br>%s</div>
      </div>
    </div>%s""" % (START, mode_cn, dim_rows, basis, esc(eff["description"]),
                  esc(eff["top20_recall"]), esc(eff["auc"]), esc(eff["note"]), END)


def sync_banner_rating(html, rating):
    """把风险横幅评级同步为 metrics 的确定性评级（2026-09-18 用户反馈「结论不一致」）。

    背景：横幅 `class="risk-banner X"` / 「综合风险等级：X」是报告撰写时的**定性**
    正文；而确定性评级 `rate_change()`（rules 1.1）由 metrics 决定。两者不一致时
    报告内出现两个评级标签（实测：manage-frontend 横幅「低」 vs 确定性「中」）。

    策略：横幅（class + icon + 等级行）同步为确定性评级；原定性结论**不删除**，
    改写进括号内标注「原定性：X」，正文 <p> 末尾追加一句口径说明。确定性评级
    与原定性一致时为幂等 no-op。

    rating: metrics 记录的 rating dict（含 code / level），缺 code 时原样返回。
    """
    code = (rating or {}).get("code")
    if code not in ("high", "medium", "low"):
        return html, False
    emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[code]
    cn = {"high": "高", "medium": "中", "low": "低"}[code]
    rules = (rating or {}).get("rules_version") or "1.1"

    m = re.search(r'class="risk-banner (high|medium|low)"', html)
    if not m:
        return html, False
    old = m.group(1)
    changed = False
    if old != code:
        html = html.replace(m.group(0), f'class="risk-banner {code}"', 1)
        changed = True

    # icon
    old_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[old]
    if old != code and f'<div class="risk-icon">{old_emoji}</div>' in html:
        html = html.replace(f'<div class="risk-icon">{old_emoji}</div>',
                            f'<div class="risk-icon">{emoji}</div>', 1)
        changed = True

    # 等级行（保留原括号内容，标注原定性）
    def _strong_repl(mm):
        nonlocal changed
        old_cn, old_reason = mm.group(1), mm.group(2).strip()
        if old_cn == cn:
            # 等级已一致（含已同步过的报告）→ 幂等 no-op，不动括号内容
            return mm.group(0)
        changed = True
        reason = old_reason or "—"
        # 已同步过的报告：把旧「原定性：X」更新为当前定性表述
        reason = re.sub(r"；?量化确定性评级[^；]*原定性「[高中低]」", "", reason).strip("；； ")
        suffix = f"；量化确定性评级 rules {rules}，原定性「{old_cn}」"
        return f"<strong>综合风险等级：{cn}（{reason}{suffix}）</strong>"

    html2 = re.sub(r"<strong>综合风险等级：([高中低])（([^<]*)）</strong>", _strong_repl, html, count=1)
    if html2 != html:
        changed = True
        html = html2

    # 正文口径说明（只加一次）
    note = (f'<br><span style="color:#b06000;font-size:12.5px">⚠ 评级口径：确定性评级'
            f'（rate_change rules {rules}）=「{cn}」，横幅已同步；原定性「'
            f'{ {"high":"高","medium":"中","low":"低"}[old] }」保留于括号内供对照。</span>')
    if old != code and "评级口径：确定性评级" not in html:
        pm = re.search(r'(<strong>综合风险等级：[\s\S]*?</strong>[\s\S]*?)</p>', html)
        if pm:
            html = html[:pm.end(1)] + note + html[pm.end(1):]
            changed = True
    return html, changed


def inject(html, q, jit):
    """单服务注入：合并进风险横幅 + 占位符处放详情卡；幂等。"""
    # 清除旧 inline / 旧 detail
    html = re.sub(re.escape(INLINE_START) + r".*?" + re.escape(INLINE_END), "", html, flags=re.S)
    # 幂等：先清旧 inline 块与 detail 块
    html = re.sub(re.escape(INLINE_START) + r".*?" + re.escape(INLINE_END), "", html, flags=re.S)
    html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)

    inline = render_inline(q, jit)
    detail = render_detail(q, jit)

    # 合并 inline 进风险横幅标题行（与「综合风险等级」同一行，不折断）
    m = re.search(r'<strong>综合风险等级：[^<]*</strong>', html)
    if m:
        html = html[:m.end()] + inline + html[m.end():]
    else:
        # 兜底：inline 直接拼到 detail 前（老模板无 risk-banner 时）
        detail = inline + detail

    if PLACEHOLDER in html:
        return html.replace(PLACEHOLDER, detail)
    # 回退：放在「变更总览」章节之前（兼容有/无注释标记的报告）
    for mk in (FALLBACK_MARKER,
               '<div class="section-title"><span class="icon">📁</span> 变更总览',
               '<table class="overview-table">'):
        if mk in html:
            return html.replace(mk, detail + "\n\n    " + mk, 1)
    # 兜底：绝不 append 到文档末尾（会落到 </html> 之后），插到 </body>/</html> 之前
    return _insert_before_body_end(html, detail)


# ============================================================
# 综合：渲染
# ============================================================
def render_combined_table(rows):
    """rows: [(service, q, jit), ...]"""
    MODE_CN = {"enhanced": "增强10维", "static": "静态5维"}
    trs = ""
    for svc, q, jit in rows:
        quant_color = LEVEL_COLOR.get(q["level"], "#f9ab00")
        jit_color = JIT_COLOR.get(jit["prediction"], "#f9ab00")
        base = q["inputs"].get("base_risk") or "medium"
        mode_cn = MODE_CN.get(q.get("mode"), "")
        mode_span = (f"<span style='color:#888;font-size:11px'>{mode_cn}</span>"
                     if mode_cn else "")
        trs += ("<tr><td style='padding:8px;border-bottom:1px solid #e8eaed;font-weight:600'>%s</td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>%s</td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>"
                "<span style='display:inline-block;min-width:46px;text-align:center;padding:3px 10px;"
                "border-radius:12px;color:#fff;background:%s;font-weight:700'>%s</span> %s</td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>"
                "<span style='display:inline-block;padding:3px 10px;border-radius:12px;color:#fff;"
                "background:%s;font-weight:600;font-size:12px'>%s</span></td></tr>") % (
            esc(svc), RISK_LABEL.get(base, base), quant_color, q["percent"],
            mode_span, jit_color, esc(jit["prediction"]))
    return ("""%s<div style="margin-top:18px">
      <div style="font-size:14px;font-weight:700;margin-bottom:8px">各服务量化风险评分 &amp; JIT 缺陷预测（apex 能力整合）</div>
      <table style="width:100%%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden">
        <thead><tr style="background:#fafafa"><th style="padding:8px;text-align:left">服务</th><th style="padding:8px;text-align:left">定性风险</th><th style="padding:8px;text-align:left">量化评分(0-100)</th><th style="padding:8px;text-align:left">JIT 预测</th></tr></thead>
        <tbody>%s</tbody>
      </table>
      <div style="font-size:11px;color:#888;margin-top:6px">评分模型：静态5维 / 增强10维（依历史度量）；JIT 依据 CC2Vec/JITLine。详细维度见各服务独立报告。</div>
    </div>%s""" % (COMBINED_START, trs, COMBINED_END))


def _insert_before_body_end(html, frag):
    """兜底插入：在 </body> 之前插入；无 </body> 则在 </html> 之前；都没有才追加。

    ⚠️ 绝不能无脑 `html + frag` —— 那会把区块插到 </html> 之后（2026-09-18 实测：
    综合报告的量化/JIT 汇总表因此跑到「⑥ 综合发布建议」之后，文档结构损坏）。
    """
    for mark in ("</body>", "</html>"):
        i = html.rfind(mark)
        if i != -1:
            return html[:i] + frag + "\n" + html[i:]
    return html + "\n" + frag


def inject_combined(html, frag):
    """幂等注入综合量化/JIT 汇总表。

    2026-09-18 修复（幂等定位缺陷）：占位符只在**首次**存在，二次运行会被判定
    「无占位符」而走追加分支 —— 结果把区块插到 </html> 之后。现改为：
      ① 先记下旧块位置（若有）；
      ② 占位符在 → 直接替换；
      ③ 占位符不在但曾有旧块 → 插回旧块原位置；
      ④ 都没有 → 插到 </body> 之前（绝不追加到文档末尾）。
    """
    old_pos = -1
    m_old = re.search(re.escape(COMBINED_START) + r".*?" + re.escape(COMBINED_END), html, flags=re.S)
    if m_old:
        old_pos = m_old.start()
    html = re.sub(re.escape(COMBINED_START) + r".*?" + re.escape(COMBINED_END), "", html, flags=re.S)

    if COMBINED_PLACEHOLDER in html:
        return html.replace(COMBINED_PLACEHOLDER, frag)
    if old_pos != -1 and old_pos < len(html):
        return html[:old_pos] + frag + html[old_pos:]
    return _insert_before_body_end(html, frag)


# ============================================================
# stats 派生
# ============================================================
def derive_stats_from_report(html):
    """从单服务报告 HTML 零配置派生 stats。"""
    m = re.search(r'class="risk-banner (high|medium|low)"', html)
    base = {"high": "high", "medium": "medium", "low": "low"}.get(m.group(1), "medium") if m else "medium"

    files, descs = [], []
    mo = re.search(r'class="overview-table"[\s\S]*?<tbody>([\s\S]*?)</tbody>', html)
    if mo:
        for row in re.findall(r"<tr>([\s\S]*?)</tr>", mo.group(1)):
            tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
            if not tds:
                continue
            fp = re.sub(r"<[^>]+>", "", tds[0]).strip()
            desc = re.sub(r"<[^>]+>", "", tds[2]).strip() if len(tds) > 2 else ""
            files.append(fp)
            descs.append(desc)

    fc = len(files)
    core = 0
    for i in range(fc):
        if any(re.search(pat, files[i] + " " + descs[i], re.I) for pat, _ in CORE_PATTERNS):
            core += 1
    added = len(re.findall(r'class="added"', html))
    removed = len(re.findall(r'class="removed"', html))
    total = added + removed
    desc = " ".join(descs)
    return {"base_risk": base, "total_lines": total, "file_count": fc,
            "core_file_count": core, "description": desc, "files": files}


def derive_stats_for_combined(service, report_root):
    """综合模式：取该服务最新独立报告 HTML 派生 stats（HTML 兜底路径）。"""
    pat = os.path.join(report_root, service, "*_变更影响分析报告.html")
    files = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
    if not files:
        return None
    return derive_stats_from_report(open(files[0], encoding="utf-8").read())


# ============================================================
# 与趋势分同源：优先从 service_metrics.json 派生 stats
# ============================================================
def _report_version_range(report_path):
    """从报告文件名解析版本区间：`{svc}_{from}_to_{to}_变更影响分析报告.html`。

    返回 (from_raw, to_raw)，解析不出返回 (None, None)。
    """
    base = os.path.basename(report_path)
    m = re.search(r"_([^_]+)_to_([^_]+)_", base)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def stats_from_metrics(service, report_path, analytics_root):
    """从 `service_metrics.json` 派生 stats（**与趋势分同源**）。

    为什么必须有这条路（2026-09-18）：
      `derive_stats_from_report()` 是「在 HTML 里数 `class="added"/"removed"` 的行数」
      来估计 `total_lines`、数变更总览表行数来估计 `file_count`；
      而趋势分（`metrics.risk_score`）用的是 service_metrics 里**权威的**
      `lines_added` / `lines_removed` / `files_changed`。
      两边不同源 → **同一份变更，报告里一个分、趋势图里另一个分**。
      本函数让报告侧改吃同一份数据，口径才对得上。

    匹配规则：用报告文件名里的 version_to，与 metrics 记录 `norm_version(version_to)`
    比较（跨写法归一）；多条命中时取 `analysis_date` 最新的一条。

    返回 (stats, note) 或 (None, 失败原因)。
    """
    _, to_raw = _report_version_range(report_path)
    if not to_raw:
        return None, "报告文件名不含 `_X_to_Y_` 版本区间，无法定位 metrics 记录"
    want = norm_version(to_raw)
    path = os.path.join(analytics_root, service, "service_metrics.json")
    if not os.path.isfile(path):
        return None, "service_metrics.json 不存在：%s" % path
    try:
        records = (json.load(open(path, encoding="utf-8")) or {}).get("records", [])
    except Exception as e:
        return None, "service_metrics.json 解析失败：%s" % e

    hits = [r for r in records if norm_version(r.get("version_to")) == want]
    if not hits:
        return None, "service_metrics 里没有 version_to=%s 的记录（共 %d 条）" % (want, len(records))
    hits.sort(key=lambda r: str(r.get("analysis_date") or ""), reverse=True)
    rec = hits[0]
    st = derive_stats_from_metrics(rec, service=service)
    st["_source"] = "service_metrics.json:version_to=%s" % want
    st["_rating"] = rec.get("rating") or {}
    return st, "命中记录 %s→%s（analysis_date %s）" % (
        rec.get("version_from"), rec.get("version_to"), rec.get("analysis_date"))


# ============================================================
# 入口
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="报告 HTML（单服务或综合）")
    ap.add_argument("--stats", help="stats JSON 文件路径（单服务）")
    ap.add_argument("--stats-json", help="stats JSON 字符串（单服务）")
    ap.add_argument("--auto", action="store_true", help="单服务：从报告 HTML 自动派生 stats（零配置）")
    ap.add_argument("--from-metrics", action="store_true",
                    help="单服务：优先从 service_metrics.json 派生 stats（**与趋势分同源**，需 --service）")
    ap.add_argument("--service", help="服务名（配合 --from-metrics 定位 metrics 记录）")
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--combined", action="store_true", help="综合报告模式：按服务注入量化/JIT 汇总表")
    ap.add_argument("--services", nargs="+", help="综合模式服务列表 / 单服务增强模式的服务名")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常")
    ap.add_argument("--report-root", help="覆盖 report/code-diff 根目录（综合模式）")
    ap.add_argument("--no-metrics", action="store_true",
                    help="综合模式：强制用 HTML 派生（退回旧行为，仅排障用）")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(
        args.workspace, ".workbuddy", "diff-analytics")

    if args.combined:
        report_root = args.report_root or os.path.join(args.workspace, "report", "code-diff")
        if not args.services:
            print("ERROR: --combined 需提供 --services"); sys.exit(1)
        rows = []
        for svc in args.services:
            st, src = None, ""
            if not args.no_metrics:
                pat = os.path.join(report_root, svc, "*_变更影响分析报告.html")
                found = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
                if found:
                    st, reason = stats_from_metrics(svc, found[0], analytics_root)
                    if st:
                        src = "metrics"
                    else:
                        print("[WARN] %s 无法从 metrics 派生（%s），回退 HTML 派生" % (svc, reason))
            if st is None:
                st = derive_stats_for_combined(svc, report_root)
                src = "html"
            if not st:
                print("[WARN] 跳过 %s：未找到独立报告 HTML" % svc)
                continue
            # 2026-09-18 口径统一：综合表与单服务报告必须同一模式（增强10维，含历史度量），
            # 否则综合表显示静态分、单服务横幅显示增强分，同一服务两个量化分。
            if args.workspace and "historical_metrics" not in st:
                h = auto_historical(svc, args.workspace)
                if h:
                    st["historical_metrics"] = h
            rows.append((svc, compute(st), generate_jit(st)))
            print("INFO: %s stats 来源 = %s（%s 文件 / %s 行 / 模式 %s）"
                  % (svc, src, st.get("file_count"), st.get("total_lines"),
                     "增强10维" if "historical_metrics" in st else "静态5维"))
        if not rows:
            print("[ERROR] 未派生到任何服务量化数据"); sys.exit(1)
        html = open(args.report, encoding="utf-8").read()
        out = inject_combined(html, render_combined_table(rows))
        safe_write_report(args.report, out)
        print("OK: 综合报告注入 %d 个服务量化/JIT 汇总" % len(rows))
        return

    # —— 单服务 ——
    if not os.path.exists(args.report):
        print("ERROR: 报告不存在 %s" % args.report); sys.exit(1)
    html = open(args.report, encoding="utf-8").read()

    stats = None
    if args.stats:
        stats = json.load(open(args.stats, encoding="utf-8"))
    elif args.stats_json:
        stats = json.loads(args.stats_json)

    if stats is None and args.from_metrics:
        if not args.service:
            print("ERROR: --from-metrics 需同时提供 --service"); sys.exit(1)
        stats, note = stats_from_metrics(args.service, args.report, analytics_root)
        if stats:
            print("INFO: stats 来源 = service_metrics.json（%s）→ %d 文件 / %d 行"
                  % (note, stats["file_count"], stats["total_lines"]))
        else:
            print("[WARN] 无法从 metrics 派生（%s），回退 HTML 派生" % note)

    if stats is None:
        stats = derive_stats_from_report(html)
        print("INFO: HTML 派生 stats = %s" % json.dumps(stats, ensure_ascii=False))

    if args.services and args.workspace and "historical_metrics" not in stats:
        h = auto_historical(args.services[0], args.workspace)
        if h:
            stats["historical_metrics"] = h
            print("INFO: 已自动补历史度量: %s" % h)

    q = compute(stats)
    jit = generate_jit(stats)
    out = inject(html, q, jit)
    # 横幅评级同步（2026-09-18）：确定性评级与横幅定性不一致时，横幅跟随确定性评级
    if stats.get("_rating"):
        out, synced = sync_banner_rating(out, stats["_rating"])
        if synced:
            print("INFO: 风险横幅评级已同步为确定性评级 %s（原定性保留于括号内）"
                  % (stats["_rating"].get("code"),))
    safe_write_report(args.report, out)
    print("OK: 合并量化评分(%s分/%s)+JIT(%s) 进风险横幅，详情卡置于变更总览前 → %s" % (
        q["percent"], q["level"], jit["prediction"], args.report))


if __name__ == "__main__":
    main()
