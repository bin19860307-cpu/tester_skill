#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_p1_cases.py — 把结构化 P1 用例预测注入单服务/综合报告（幂等）。

用法：
  python scripts/gen_p1_cases.py --report 报告.html --data-file p1_cases.json
  python scripts/gen_p1_cases.py --report 报告.html --data '{...}'

data JSON 结构：
{
  "kb_check": {
    "kb_location": "知识库用例集路径（位于 v5.2 对应模块，如 .../测试用例/v5.2/权益控制/用例/全量测试用例.md）",
    "note": "逐条核对结论（由 AI 填写，例如：已按修改内容定位到 v5.2/权益控制 用例集，P1-02/P1-03 命中既有用例，其余为新增场景预估）",
    "hit_count": 2,            # 命中知识库既有用例的条数
    "est_count": 7             # 未命中、需新增的预估用例条数
  },
  "groups": [
    {
      "title": "① 分组标题（模块 + 风险 + 覆盖 bug）",
      "cases": [
        {
          "id": "P1-01",
          "level": "high|medium|low",   # 决定颜色与标签
          "scene": "测试场景名",
          "kb_ref": "10204/20105",       # 命中知识库用例编号（命中时不标预估，与 estimated 互斥）
          "estimated": true,             # 未命中知识库时为预估新增用例（命中时省略或设 false）
          "code": "对应代码点/类.方法",
          "precondition": "具体前置（含测试数据）",
          "steps": "步骤",
          "expect": "预期结果"
        }
      ]
    }
  ]
}

知识库命中核对规则（用户 2026-08-14 明确）：
- 所有服务都基于「教学管理域」；用例集按【版本】划分，每轮提测按当前分析的「目标版本」动态确定要核对的用例集版本（并非固定 v5.2）。
- 确定版本后，按【修改内容】去该版本对应模块定位用例集：
    D:/Obsidian知识库/knowledge/测试用例/v{目标版本}/{对应模块}/用例/全量测试用例.md
- 逐条核对每条 P1 用例：
    · 命中既有用例 → 填 kb_ref（关联的编号），卡片显示绿色「✅ 已命中·关联 XXX」
    · 未命中（新增场景） → 设 estimated:true，卡片显示红色「预估」
- 不再使用「域差异全未命中红框」，改为绿色「已定位知识库用例集」框 + 逐条核对结论。

注入规则：
- 片段以 <!-- P1_CASES_START --> ... <!-- P1_CASES_END --> 包裹，重复注入自动替换（幂等）。
- 优先替换模板占位符 <!-- P1_CASES_SECTION -->；若报告无占位符（旧报告），
  则插入到「开发者建议」章节之前。
"""
import argparse
import json
import os
import re
import sys

START = "<!-- P1_CASES_START -->"
END = "<!-- P1_CASES_END -->"
PLACEHOLDER = "<!-- P1_CASES_SECTION -->"
DEV_MARKER = "<!-- ===== Section: 开发者建议 ===== -->"

LEVEL_COLOR = {"high": "#d93025", "medium": "#f9ab00", "low": "#1a73e8"}
LEVEL_LABEL = {"high": "P1 必测", "medium": "P2 建议", "low": "P3 可选"}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_case(c):
    lvl = c.get("level", "medium")
    color = LEVEL_COLOR.get(lvl, "#f9ab00")
    label = LEVEL_LABEL.get(lvl, "P2 建议")
    kb_ref = c.get("kb_ref")
    if kb_ref:
        tag = " · <span style='color:#1e7a1e;font-size:11px;font-weight:700'>✅ 已命中·关联 %s</span>" % esc(kb_ref)
    elif c.get("estimated"):
        tag = " · <span style='color:#d93025;font-size:11px;font-weight:700'>预估</span>"
    else:
        tag = ""
    rows = []
    if c.get("code"):
        rows.append("<div class='p1-row'><b>对应代码</b>：%s</div>" % esc(c["code"]))
    if c.get("precondition"):
        rows.append("<div class='p1-row'><b>前置</b>：%s</div>" % esc(c["precondition"]))
    if c.get("steps"):
        rows.append("<div class='p1-row'><b>步骤</b>：%s</div>" % esc(c["steps"]))
    if c.get("expect"):
        rows.append("<div class='p1-row'><b>预期</b>：%s</div>" % esc(c["expect"]))
    return """            <div class="p1-card">
                <div class="p1-chead"><span class="p1-cid" style="background:%s">%s</span> %s%s</div>
                <div class="p1-cbody">
                    %s
                </div>
            </div>""" % (color, esc(c.get("id", "")), esc(c.get("scene", "")), tag, "".join(rows))


def render_kb(kb):
    loc = kb.get("kb_location", "")
    note = kb.get("note", "")
    hit = kb.get("hit_count", 0)
    est = kb.get("est_count", 0)
    stat = ""
    if hit or est:
        stat = "<br>&nbsp;&nbsp;• 逐条核对：命中 <b>%s</b> 条（关联既有用例集，可直接复用） / 预估 <b>%s</b> 条（新增场景）" % (hit, est)
    return ("<div class='p1-kb hit'>📚 <b>知识库用例集核对</b>：已按修改内容定位到 v5.2 用例集。<br>"
            "&nbsp;&nbsp;• 用例集位置：%s<br>"
            "&nbsp;&nbsp;• 核对结论：%s%s</div>") % (esc(loc), esc(note), stat)


def render(data):
    kb = data.get("kb_check", {})
    groups = data.get("groups", [])
    g_html = ""
    for g in groups:
        cases = "".join(render_case(c) for c in g.get("cases", []))
        g_html += """        <div class="p1-group">
            <div class="p1-gtitle">%s</div>
            %s
        </div>
""" % (esc(g.get("title", "")), cases)
    style = """<style>
.p1-kb{font-size:12.5px;line-height:1.6;padding:10px 12px;border-radius:8px;margin:0 0 14px}
.p1-kb.miss{background:#fff4f4;border:1px solid #f5c2c2;color:#a50e0e}
.p1-kb.hit{background:#f0f9f0;border:1px solid #bfe3bf;color:#1e7a1e}
.p1-group{margin:0 0 18px}
.p1-gtitle{font-size:14px;font-weight:700;color:#1a73e8;margin:0 0 8px;padding-left:8px;border-left:3px solid #1a73e8}
.p1-card{border:1px solid #e3e8ef;border-radius:8px;margin:0 0 8px;overflow:hidden}
.p1-chead{background:#f8fafc;padding:8px 12px;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.p1-cid{color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:700}
.p1-cbody{padding:8px 12px;font-size:12.5px;line-height:1.65;color:#333}
.p1-cbody b{color:#1a1a1a}
.p1-row{margin:2px 0}
</style>"""
    return "%s\n    %s\n    %s\n%s    %s" % (START, style, render_kb(kb), g_html, END)


def inject(html, fragment):
    # 幂等：先删旧块
    html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)
    if PLACEHOLDER in html:
        return html.replace(PLACEHOLDER, fragment)
    if DEV_MARKER in html:
        return html.replace(DEV_MARKER, fragment + "\n\n    " + DEV_MARKER, 1)
    return html + "\n" + fragment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="目标报告 HTML")
    ap.add_argument("--data", help="P1 用例 JSON 字符串")
    ap.add_argument("--data-file", help="P1 用例 JSON 文件路径")
    args = ap.parse_args()
    if args.data_file:
        data = json.load(open(args.data_file, encoding="utf-8"))
    elif args.data:
        data = json.loads(args.data)
    else:
        print("ERROR: 需提供 --data 或 --data-file")
        sys.exit(1)
    if not os.path.exists(args.report):
        print("ERROR: 报告不存在 %s" % args.report)
        sys.exit(1)
    html = open(args.report, encoding="utf-8").read()
    frag = render(data)
    out = inject(html, frag)
    open(args.report, "w", encoding="utf-8").write(out)
    n = sum(len(g.get("cases", [])) for g in data.get("groups", []))
    print("OK: 注入 %d 条 P1 用例（%d 组）到 %s" % (n, len(data.get("groups", [])), args.report))


if __name__ == "__main__":
    main()
