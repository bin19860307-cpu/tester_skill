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


def wkey(name):
    return (name.lower()
            .replace("历史bug频率", "buggy").replace("代码流失率", "churn")
            .replace("修改频率", "modfreq").replace("作者经验", "authorexp")
            .replace("距上次修改", "dormancy").replace("基础风险", "base")
            .replace("变更规模", "size").replace("模块跨度", "span")
            .replace("核心模块占比", "core").replace("变更密度", "density"))


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
        w = q["weights"].get(wkey(name), 0)
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
    return html + "\n" + detail


# ============================================================
# 综合：渲染
# ============================================================
def render_combined_table(rows):
    """rows: [(service, q, jit), ...]"""
    trs = ""
    for svc, q, jit in rows:
        quant_color = LEVEL_COLOR.get(q["level"], "#f9ab00")
        jit_color = JIT_COLOR.get(jit["prediction"], "#f9ab00")
        base = q["inputs"].get("base_risk") or "medium"
        trs += ("<tr><td style='padding:8px;border-bottom:1px solid #e8eaed;font-weight:600'>%s</td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>%s</td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>"
                "<span style='display:inline-block;min-width:46px;text-align:center;padding:3px 10px;"
                "border-radius:12px;color:#fff;background:%s;font-weight:700'>%s</span></td>"
                "<td style='padding:8px;border-bottom:1px solid #e8eaed'>"
                "<span style='display:inline-block;padding:3px 10px;border-radius:12px;color:#fff;"
                "background:%s;font-weight:600;font-size:12px'>%s</span></td></tr>") % (
            esc(svc), RISK_LABEL.get(base, base), quant_color, q["percent"],
            jit_color, esc(jit["prediction"]))
    return ("""%s<div style="margin-top:18px">
      <div style="font-size:14px;font-weight:700;margin-bottom:8px">各服务量化风险评分 &amp; JIT 缺陷预测（apex 能力整合）</div>
      <table style="width:100%%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden">
        <thead><tr style="background:#fafafa"><th style="padding:8px;text-align:left">服务</th><th style="padding:8px;text-align:left">定性风险</th><th style="padding:8px;text-align:left">量化评分(0-100)</th><th style="padding:8px;text-align:left">JIT 预测</th></tr></thead>
        <tbody>%s</tbody>
      </table>
      <div style="font-size:11px;color:#888;margin-top:6px">评分模型：静态5维 / 增强10维（依历史度量）；JIT 依据 CC2Vec/JITLine。详细维度见各服务独立报告。</div>
    </div>%s""" % (COMBINED_START, trs, COMBINED_END))


def inject_combined(html, frag):
    html = re.sub(re.escape(COMBINED_START) + r".*?" + re.escape(COMBINED_END), "", html, flags=re.S)
    if COMBINED_PLACEHOLDER in html:
        return html.replace(COMBINED_PLACEHOLDER, frag)
    return html + "\n" + frag


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
    """综合模式：取该服务最新独立报告 HTML 派生 stats。"""
    pat = os.path.join(report_root, service, "*_变更影响分析报告.html")
    files = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
    if not files:
        return None
    return derive_stats_from_report(open(files[0], encoding="utf-8").read())


# ============================================================
# 入口
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="报告 HTML（单服务或综合）")
    ap.add_argument("--stats", help="stats JSON 文件路径（单服务）")
    ap.add_argument("--stats-json", help="stats JSON 字符串（单服务）")
    ap.add_argument("--auto", action="store_true", help="单服务：从报告 HTML 自动派生 stats（零配置）")
    ap.add_argument("--combined", action="store_true", help="综合报告模式：按服务注入量化/JIT 汇总表")
    ap.add_argument("--services", nargs="+", help="综合模式服务列表 / 单服务增强模式的服务名")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常")
    ap.add_argument("--report-root", help="覆盖 report/code-diff 根目录（综合模式）")
    args = ap.parse_args()

    if args.combined:
        report_root = args.report_root or os.path.join(args.workspace, "report", "code-diff")
        if not args.services:
            print("ERROR: --combined 需提供 --services"); sys.exit(1)
        rows = []
        for svc in args.services:
            st = derive_stats_for_combined(svc, report_root)
            if not st:
                print("[WARN] 跳过 %s：未找到独立报告 HTML" % svc)
                continue
            rows.append((svc, compute(st), generate_jit(st)))
        if not rows:
            print("[ERROR] 未派生到任何服务量化数据"); sys.exit(1)
        html = open(args.report, encoding="utf-8").read()
        out = inject_combined(html, render_combined_table(rows))
        open(args.report, "w", encoding="utf-8").write(out)
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
    if stats is None:
        stats = derive_stats_from_report(html)
        print("INFO: --auto 派生 stats = %s" % json.dumps(stats, ensure_ascii=False))

    if args.services and args.workspace and "historical_metrics" not in stats:
        h = auto_historical(args.services[0], args.workspace)
        if h:
            stats["historical_metrics"] = h
            print("INFO: 已自动补历史度量: %s" % h)

    q = compute(stats)
    jit = generate_jit(stats)
    out = inject(html, q, jit)
    open(args.report, "w", encoding="utf-8").write(out)
    print("OK: 合并量化评分(%s分/%s)+JIT(%s) 进风险横幅，详情卡置于变更总览前 → %s" % (
        q["percent"], q["level"], jit["prediction"], args.report))


if __name__ == "__main__":
    main()
