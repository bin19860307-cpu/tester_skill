#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_bug_predict.py — 把「Bug 预测（缺陷倾向预判）」维度注入变更影响分析报告（幂等）。

为何存在：
  Bug 预测是「向前看」的缺陷倾向预判，与 gen_p1_cases.py 产出的「测试范围/P1 可执行用例」
  是互补双维度（用户 2026-08-18 明确：应合并进回归用例集）。本报告在 P1 用例章节之前
  嵌入 Bug 预测总览 + 「P1 → Bug 预测」映射表，使回归测试者在同一章节拿到「预判缺陷」与
  「可执行用例」两个视角。

用法：
  python scripts/gen_bug_predict.py --report 报告.html --data-file bug_predict.json
  python scripts/gen_bug_predict.py --report 报告.html --data '{...}'

data JSON 结构（见 bug_predict_52015_52016.json 样例）：
{
  "meta": {"service","range","note"},
  "items": [
    {"id":"H1-01","priority":"H1|H2|H3","defect_type":...,"root":...,"trigger":...,
     "affected":...,"confidence":"high|mid|low","verify":...}
  ],
  "p1_map": [{"p1":"P (id)","scene":...,"bug":"对应 Hx 项"}],
  "confirm": ["待产品/开发确认项1", "..."]
}

注入规则：
- 片段以 <!-- BUG_PREDICT_START --> ... <!-- BUG_PREDICT_END --> 包裹，重复注入自动替换（幂等）。
- 优先替换模板占位符 <!-- BUG_PREDICT_SECTION -->；
- 若报告无占位符，则插入到 「P1 用例预测」章节注释之前（即 P1 块之前）。
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # noqa: E402  统一错误提示层

START = "<!-- BUG_PREDICT_START -->"
END = "<!-- BUG_PREDICT_END -->"
PLACEHOLDER = "<!-- BUG_PREDICT_SECTION -->"
P1_MARKER = "<!-- ===== Section: P1 用例预测"

PRI_COLOR = {"H1": "#e74c3c", "H2": "#e67e22", "H3": "#2c82c9"}
CONF_LABEL = {"high": ("高", "#e74c3c", "#fdecea"),
              "mid": ("中", "#e67e22", "#fef3e7"),
              "low": ("低", "#2c82c9", "#eaf3fb")}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_item(it):
    pri = it.get("priority", "H3")
    color = PRI_COLOR.get(pri, "#2c82c9")
    conf = it.get("confidence", "mid")
    clabel, ccolor, cbg = CONF_LABEL.get(conf, ("中", "#e67e22", "#fef3e7"))
    rows = []
    if it.get("defect_type"):
        rows.append("<div class='bp-kv'><b>预测缺陷</b>%s</div>" % esc(it["defect_type"]))
    if it.get("root"):
        rows.append("<div class='bp-kv'><b>根因（diff）</b>%s</div>" % esc(it["root"]))
    if it.get("trigger"):
        rows.append("<div class='bp-kv'><b>触发条件</b>%s</div>" % esc(it["trigger"]))
    if it.get("affected"):
        rows.append("<div class='bp-kv'><b>影响模块</b>%s</div>" % esc(it["affected"]))
    if it.get("verify"):
        rows.append("<div class='bp-kv'><b>验证建议</b>%s</div>" % esc(it["verify"]))
    return """          <div class="bp-card bp-%s">
            <div class="bp-ch"><span>%s ｜ %s</span><span class="bp-pill" style="color:%s;background:%s">置信度 %s</span></div>
            <div class="bp-cbody">%s</div>
          </div>""" % (pri.lower(), esc(it.get("id", "")), esc(it.get("defect_type", "")),
                      ccolor, cbg, clabel, "".join(rows))


def render(data):
    meta = data.get("meta", {})
    items = data.get("items", [])
    p1_map = data.get("p1_map", [])
    confirm = data.get("confirm", [])

    # 概览表
    ov_rows = []
    for it in items:
        pri = it.get("priority", "H3")
        color = PRI_COLOR.get(pri, "#2c82c9")
        conf = it.get("confidence", "mid")
        clabel, ccolor, cbg = CONF_LABEL.get(conf, ("中", "#e67e22", "#fef3e7"))
        ov_rows.append(
            "<tr><td><span class='bp-pill' style='color:#fff;background:%s'>%s</span></td>"
            "<td class='bp-word'>%s</td><td class='bp-word'>%s</td>"
            "<td class='bp-word'>%s</td>"
            "<td><span class='bp-pill' style='color:%s;background:%s'>%s</span></td></tr>"
            % (color, esc(pri), esc(it.get("defect_type", "")), esc(it.get("trigger", "")),
               esc(it.get("affected", "")), ccolor, cbg, clabel))
    overview = ("<table class='bp-ov'><tr><th style='width:56px'>优先级</th>"
                "<th style='width:170px'>预测缺陷类型</th><th>触发条件（简述）</th>"
                "<th style='width:130px'>影响模块</th><th style='width:78px'>置信度</th></tr>"
                "%s</table>") % "".join(ov_rows)

    detail = "".join(render_item(it) for it in items)

    # P1 映射表
    map_rows = []
    for m in p1_map:
        map_rows.append("<tr><td class='bp-word'><b>%s</b></td><td class='bp-word'>%s</td>"
                        "<td class='bp-word'>%s</td></tr>"
                        % (esc(m.get("p1", "")), esc(m.get("scene", "")), esc(m.get("bug", ""))))
    mapping = ""
    if map_rows:
        mapping = ("<div class='bp-sub'>📌 P1 用例 ↔ Bug 预测映射（合并进同一回归用例集）</div>"
                   "<table class='bp-ov'><tr><th style='width:90px'>P1 用例</th>"
                   "<th style='width:300px'>测试场景</th><th>Bug 预测对应</th></tr>"
                   "%s</table>") % "".join(map_rows)

    # 确认项
    flags = ""
    if confirm:
        lis = "".join("<li>%s</li>" % esc(c) for c in confirm)
        flags = ("<div class='bp-flag'><b>⚠️ 待产品 / 开发确认项：</b><ul>%s</ul></div>" % lis)

    note = meta.get("note", "")
    note_html = "<p class='bp-muted'>%s</p>" % esc(note) if note else ""

    body = """    <div class="bp-wrap">
      <div class="bp-h">🐞 Bug 预测（缺陷倾向预判）— 与 P1 用例合并呈现</div>
      %s
      <div class="bp-sub">一、预测总览（H1/H2/H3 缺陷倾向）</div>
      %s
      <div class="bp-sub">二、逐条 Bug 预测详情</div>
      %s
      %s
      %s
    </div>""" % (note_html, overview, detail, mapping, flags)

    style = """<style>
.bp-wrap{background:#fbfcfe;border:1px solid #d7e0ea;border-left:5px solid #e74c3c;border-radius:12px;padding:18px 22px;margin:16px 0}
.bp-h{font-size:17px;font-weight:700;color:#1f2d3d;margin:0 0 10px}
.bp-sub{font-size:14px;font-weight:700;color:#34495e;margin:16px 0 8px;padding-left:8px;border-left:3px solid #e74c3c}
.bp-ov{width:100%%;border-collapse:collapse;font-size:13px;margin-top:4px}
.bp-ov th,.bp-ov td{border:1px solid #e3e8ef;padding:8px 10px;text-align:left;vertical-align:top}
.bp-ov th{background:#f0f3f7;color:#5a6b7b;font-weight:600}
.bp-word{word-break:break-word;white-space:normal}
.bp-pill{padding:2px 9px;border-radius:20px;font-size:12px;font-weight:700;display:inline-block}
.bp-card{border:1px solid #e3e8ef;border-left:5px solid #ccc;border-radius:10px;padding:14px 16px;margin:12px 0;background:#fff}
.bp-card.bp-h1{border-left-color:#e74c3c}
.bp-card.bp-h2{border-left-color:#e67e22}
.bp-card.bp-h3{border-left-color:#2c82c9}
.bp-ch{font-size:14.5px;font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.bp-cbody{font-size:13px;line-height:1.65;color:#333}
.bp-kv{margin:4px 0}
.bp-kv b{color:#5a6b7b;font-weight:600;min-width:84px;display:inline-block}
.bp-flag{background:#fff8e6;border:1px dashed #e0b84a;border-radius:8px;padding:12px 16px;margin:14px 0;font-size:13px}
.bp-flag ul{margin:6px 0 0 2px;padding-left:20px}
.bp-flag li{margin:3px 0}
.bp-muted{color:#5a6b7b;font-size:12.5px;margin:0 0 6px}
</style>"""
    return "%s\n    %s\n    %s\n%s" % (START, style, body, END)


def inject(html, fragment):
    # 幂等：先删旧块
    html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)
    if PLACEHOLDER in html:
        return html.replace(PLACEHOLDER, fragment)
    if P1_MARKER in html:
        return html.replace(P1_MARKER, fragment + "\n\n    " + P1_MARKER, 1)
    return html + "\n" + fragment


# ---------------------------------------------------------------------------
# 综合报告聚合（与 gen_quant_jit.py --combined 同套路）
# ---------------------------------------------------------------------------
COMBINED_START = "<!-- BUG_PREDICT_COMBINED_START -->"
COMBINED_END = "<!-- BUG_PREDICT_COMBINED_END -->"
COMBINED_PLACEHOLDER = "<!-- BUG_PREDICT_COMBINED -->"


def _latest_bug_predict(report_root, service):
    """取某服务目录下最新的 bug_predict*.json（按 mtime）"""
    import glob
    pat = os.path.join(report_root, service, "bug_predict*.json")
    files = glob.glob(pat)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


def render_combined(services_data):
    """services_data: list of (service, data_dict)"""
    rows = []
    for svc, d in services_data:
        meta = d.get("meta", {})
        items = d.get("items", [])
        h1 = sum(1 for it in items if it.get("priority") == "H1")
        h2 = sum(1 for it in items if it.get("priority") == "H2")
        h3 = sum(1 for it in items if it.get("priority") == "H3")
        conf = len(d.get("confirm", []))
        # 高优先摘要：取 H1/H2 缺陷类型，最多 2 条
        top = [it.get("defect_type", "") for it in items if it.get("priority") in ("H1", "H2")]
        top = top[:2]
        top_html = "<br>".join("· " + esc(t) for t in top) if top else "—"
        rng = meta.get("range", "")
        rows.append(
            "<tr><td style='font-weight:600'>%s</td><td class='bp-word'>%s</td>"
            "<td style='text-align:center'><span class='bp-pill' style='color:#e74c3c;background:#fdecea'>%d</span></td>"
            "<td style='text-align:center'><span class='bp-pill' style='color:#e67e22;background:#fef3e7'>%d</span></td>"
            "<td style='text-align:center'><span class='bp-pill' style='color:#2c82c9;background:#eaf3fb'>%d</span></td>"
            "<td style='text-align:center'>%s</td><td class='bp-word'>%s</td></tr>"
            % (esc(svc), esc(rng), h1, h2, h3, (str(conf) if conf else "—"), top_html))
    table = ("<table class='bp-ov'><tr><th>服务</th><th>版本区间</th><th>H1</th><th>H2</th>"
             "<th>H3</th><th>待确认</th><th>高优先缺陷摘要</th></tr>%s</table>" % "".join(rows))
    body = ("<div class='bp-wrap'>"
            "<div class='bp-h'>🐞 各服务 Bug 预测汇总（缺陷倾向预判 · 与 P1 用例合并呈现）</div>"
            "<p class='bp-muted'>本表汇总各服务「向前看」缺陷倾向（H1/H2/H3）。完整逐项与 P1↔Bug 映射见各服务独立报告。</p>"
            + table +
            "</div>")
    style = """<style>
.bp-wrap{background:#fbfcfe;border:1px solid #d7e0ea;border-left:5px solid #e74c3c;border-radius:12px;padding:18px 22px;margin:16px 0}
.bp-h{font-size:17px;font-weight:700;color:#1f2d3d;margin:0 0 10px}
.bp-ov{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.bp-ov th,.bp-ov td{border:1px solid #e3e8ef;padding:8px 10px;text-align:left;vertical-align:top}
.bp-ov th{background:#f0f3f7;color:#5a6b7b;font-weight:600}
.bp-word{word-break:break-word;white-space:normal}
.bp-pill{padding:2px 9px;border-radius:20px;font-size:12px;font-weight:700;display:inline-block}
.bp-muted{color:#5a6b7b;font-size:12.5px;margin:0 0 6px}
</style>"""
    return "%s\n    %s\n    %s\n%s" % (COMBINED_START, style, body, COMBINED_END)


def inject_combined(html, fragment):
    html = re.sub(re.escape(COMBINED_START) + r".*?" + re.escape(COMBINED_END), "", html, flags=re.S)
    if COMBINED_PLACEHOLDER in html:
        return html.replace(COMBINED_PLACEHOLDER, fragment)
    # 兜底：若量化块存在，插到它之后
    if "<!-- QUANT_JIT_COMBINED -->" in html:
        return html.replace("<!-- QUANT_JIT_COMBINED -->",
                            "<!-- QUANT_JIT_COMBINED -->\n\n" + fragment, 1)
    return html + "\n" + fragment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="目标报告 HTML（单服务或综合）")
    ap.add_argument("--data", help="Bug 预测 JSON 字符串（单服务模式）")
    ap.add_argument("--data-file", help="Bug 预测 JSON 文件路径（单服务模式）")
    ap.add_argument("--combined", action="store_true", help="综合报告模式：按服务汇总各服务 bug_predict.json")
    ap.add_argument("--services", nargs="+", help="综合模式：服务名列表（与 --combined 配合）")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常", help="工作区根目录（综合模式取 report/code-diff 下数据）")
    args = ap.parse_args()
    html = cdx_errors.read_text(args.report, "目标报告 HTML（--report）",
                                hint="先由上游生成报告 HTML，再注入 Bug 预测。")

    if args.combined:
        report_root = os.path.join(args.workspace, "report", "code-diff")
        if not args.services:
            cdx_errors.die("--combined 需配合 --services", hint="例：--combined --services a b c", code=2)
        svc_data = []
        missing = []
        for svc in args.services:
            p = _latest_bug_predict(report_root, svc)
            if not p:
                missing.append(svc)
                continue
            svc_data.append((svc, cdx_errors.read_json(p, "bug_predict（%s）" % svc)))
        if missing:
            cdx_errors.warn("以下服务无 bug_predict*.json，已跳过：%s" % ", ".join(missing))
        if not svc_data:
            cdx_errors.die("无任何服务含 bug_predict 数据",
                           "服务: %s\n查找根目录: %s" % (", ".join(args.services), report_root),
                           hint="确认已生成各服务的 bug_predict*.json。", code=4)
        frag = render_combined(svc_data)
        out = inject_combined(html, frag)
        open(args.report, "w",  encoding="utf-8").write(out)
        print("OK: 注入 %d 个服务的 Bug 预测汇总（综合报告）→ %s" % (len(svc_data), args.report))
        return

    # 单服务模式
    if args.data_file:
        data = cdx_errors.read_json(args.data_file, "Bug 预测 JSON（--data-file）")
    elif args.data:
        data = cdx_errors.parse_json_arg(args.data, "Bug 预测 JSON（--data）")
    else:
        cdx_errors.die("缺少 Bug 预测数据（单服务模式）",
                       hint="提供 --data-file <路径> 或 --data '<JSON>'。", code=2)
    frag = render(data)
    out = inject(html, frag)
    open(args.report, "w", encoding="utf-8").write(out)
    print("OK: 注入 %d 条 Bug 预测（H1/H2/H3）+ P1 映射表 到 %s"
          % (len(data.get("items", [])), args.report))


if __name__ == "__main__":
    cdx_errors.guard(main)
