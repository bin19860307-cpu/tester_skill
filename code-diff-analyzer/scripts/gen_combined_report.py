# -*- coding: utf-8 -*-
"""
gen_combined_report.py — Code Diff Analyzer · 综合比对分析报告（多服务）

功能：
  当用户一次性上传/分析 ≥2 个服务的代码比对文件（如主框架 + 前端 + 后端），
  先各自走单服务 Step 1-7 分析（沉淀 diff-analytics/{service}/ 与独立报告），
  再用本脚本把多份分析结果汇总成一份「综合比对分析报告」HTML。

报告结构（已与用户确认：摘要卡 + 跨服务关联，不整篇拼装）：
  ① 综合总览（服务数 / 版本矩阵 / 版本批次 / 综合风险 / 总变更规模 / 总 Bug 数·已关闭·已解决）
  ② 各服务摘要卡（风险 / 变更版本 from→to / 变更规模 / Bug / 专项检测 / 独立报告链接）
  ③ 跨服务关联与级联风险（核心增值，启发式关键词匹配）
  ④ 统一测试优先级（合并各服务 high-risk 模块去重）
  ⑤ 各版本 Bug 数据明细（仅综合报告含 ≥2 服务时展示；按产生版本 / 解决版本分布）
  ⑥ 综合发布建议

设计决策（2026-08-10 确认）：
  - 内容深度：摘要卡 + 跨服务关联（不整篇拼装，避免篇幅爆炸）
  - 关联方式：启发式关键词匹配（STRONG_TOKENS 业务概念词典，零维护）
  - 风险聚合：综合 = max(各服务最新风险) + 级联升级（高风险服务且存在跨服务关联 → 升级标注）
  - 独立报告：综合模式下仍保留各服务独立报告，本综合报告作为总入口

数据源契约（来自 diff-analytics/{service}/）：
  - service_metrics.json：records[]（需按 version_from+version_to 去重）→ 最新版本对、metrics、modules[].risk、detections、bug_links
  - version_bugs.json：bugs[] → 按 severity/status 汇总
  - 各服务独立报告 HTML（report/code-diff/{service}/ 下最新 *_变更影响分析报告.html）

依赖：仅 Python 标准库。
"""
import argparse
import json
import os
import re
import glob
from datetime import datetime

import sys as _sys  # noqa: E402
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_bugs_doc, classify_bug_side, safe_write_report  # noqa: E402

RISK_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}
RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}
RISK_COLOR = {"high": "#d93025", "medium": "#f9ab00", "low": "#188038"}

# ---------------------------------------------------------------------------
# 跨服务关联：强关联业务概念词典（驼峰/下划线/斜杠拆词后匹配，零维护）
# 只有这些概念跨服务共现，才判定为「潜在关联」。过于通用的词（service/vue/
# rest/api/controller）不收录，避免噪声关联。
# ---------------------------------------------------------------------------
STRONG_TOKENS = {
    # 权益 / 套餐 / 账户
    "token", "单位", "万", "权益", "entitlement", "benefit", "套餐", "package",
    "rights", "account", "账户", "增量", "increment", "push", "推送",
    # 教学实体
    "班级", "class", "学生", "student", "学校", "school", "教师", "teacher",
    "组织", "organization", "lab",
    # 版本 / 发布
    "版本", "version", "发布", "release",
    # 运行时行为
    "降级", "switch", "到期", "expire", "生效", "active", "告警", "alert",
    "灰度", "灰度发布", "回滚", "rollback", "接口", "api", "校验", "validate",
}

# 驼峰拆分：EntitlementPushService -> entitlement push service
CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[\u4e00-\u9fff]+")


def tokenize(text):
    if not text:
        return set()
    parts = re.split(r"[/_.\\-]", str(text))
    toks = set()
    for p in parts:
        for m in CAMEL_RE.findall(p):
            w = m.lower().strip()
            if w:
                toks.add(w)
    return toks


def extract_concepts(module_names, bug_titles=None):
    """从模块名 + bug 标题中提取「强关联概念指纹」"""
    raw = set()
    for m in (module_names or []):
        raw |= tokenize(m)
    for t in (bug_titles or []):
        raw |= tokenize(t)
    return raw & STRONG_TOKENS  # 只保留强关联概念


# ---------------------------------------------------------------------------
# 版本排序
# ---------------------------------------------------------------------------
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
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 加载单服务数据
# ---------------------------------------------------------------------------
def load_service(service, analytics_root, report_root):
    svc_dir = os.path.join(analytics_root, service)
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json"))
    # 项目级 Bug 池回退：服务级缺失时读 _project/version_bugs.json（scope=project）
    bugs_doc, bugs_scope = load_bugs_doc(analytics_root, service)

    # —— 最新版本对（去重：按 version_from+version_to）——
    latest = None
    seen = set()
    if metrics and metrics.get("records"):
        for r in metrics["records"]:
            vf, vt = r.get("version_from"), r.get("version_to")
            key = (vf, vt)
            if key in seen:
                continue
            seen.add(key)
            if latest is None or version_key(vt) > version_key(latest.get("version_to")):
                latest = r

    # —— 风险 / 变更规模 / 专项检测 / bug_links ——
    risk = None
    metrics_now = None
    detections = {}
    bug_links = []
    module_names = []
    if latest:
        risk = "low"
        for m in latest.get("modules", []):
            mr = m.get("risk")
            if RISK_RANK.get(mr, 0) > RISK_RANK.get(risk, 0):
                risk = mr
            module_names.append(m.get("name", ""))
        metrics_now = latest.get("metrics", {})
        detections = latest.get("detections", {}) or {}
        bug_links = []
        for b in latest.get("bug_links", []) or []:
            bid = str(b).replace(".0", "").strip()
            if bid and bid not in bug_links:
                bug_links.append(bid)

    # —— Bug 汇总（来自 version_bugs.json）——
    bug_summary = {"total": 0, "closed": 0, "resolved": 0, "open": 0,
                   "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}}
    if bugs_doc and bugs_doc.get("bugs"):
        bs = bugs_doc["bugs"]
        bug_summary["total"] = len(bs)
        bug_summary["closed"] = sum(1 for b in bs if b.get("status") == "closed")
        bug_summary["resolved"] = sum(1 for b in bs if b.get("status") == "resolved")
        bug_summary["open"] = bug_summary["total"] - bug_summary["closed"] - bug_summary["resolved"]
        for b in bs:
            sv = b.get("severity", "medium")
            if sv in bug_summary["by_severity"]:
                bug_summary["by_severity"][sv] += 1

    # —— 各版本 Bug 分布（产生版本 / 解决版本），供综合报告「各版本 Bug 数据明细」节 ——
    bug_version = {"found": {}, "fixed": {}, "severity_by_found": {}}
    if bugs_doc and bugs_doc.get("bugs"):
        for b in bugs_doc["bugs"]:
            fv = b.get("found_in_version") or "(未填)"
            xv = b.get("fixed_in_version") or "(未填)"
            bug_version["found"][fv] = bug_version["found"].get(fv, 0) + 1
            bug_version["fixed"][xv] = bug_version["fixed"].get(xv, 0) + 1
            sv = b.get("severity_raw") or b.get("severity") or "medium"
            bug_version["severity_by_found"].setdefault(fv, {})
            bug_version["severity_by_found"][fv][sv] = bug_version["severity_by_found"][fv].get(sv, 0) + 1

    # —— 概念指纹（用于跨服务关联）——
    # 2026-09-18 项目级池改造：项目池的 Bug 标题被所有服务共享，若纳入指纹，
    # 会把「同一份 Bug 列表」误判成「跨服务概念关联」（实测 0→1 假关联）。
    # 故 scope=project 时只用模块名做指纹，不并入 Bug 标题。
    if (bugs_doc or {}).get("bugs") and bugs_scope == "service":
        bug_titles = [b.get("title", "") for b in bugs_doc["bugs"]]
    else:
        bug_titles = []
    concepts = extract_concepts(module_names, bug_titles)

    # —— 端归属预判分布（项目级口径下，让前端服务也能看到关联 Bug 构成）——
    side_pre_dist = {}
    if bugs_doc and bugs_doc.get("bugs"):
        for b in bugs_doc["bugs"]:
            side = b.get("side_pre") or classify_bug_side(b)[0]
            side_pre_dist[side] = side_pre_dist.get(side, 0) + 1

    # —— 独立报告路径（最新一份 *_变更影响分析报告.html）——
    report_path = None
    if report_root:
        pattern = os.path.join(report_root, service, "*_变更影响分析报告.html")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if files:
            report_path = files[0]

    return {
        "service": service,
        "latest": latest,
        "version_from": latest.get("version_from") if latest else None,
        "version_to": latest.get("version_to") if latest else None,
        "risk": risk,
        "metrics": metrics_now or {},
        "detections": detections,
        "bug_links": bug_links,
        "bug_summary": bug_summary,
        "bug_version": bug_version,
        "bugs_scope": bugs_scope or "service",
        "side_pre_dist": side_pre_dist,
        "concepts": concepts,
        "module_names": module_names,
        "report_path": report_path,
    }


# ---------------------------------------------------------------------------
# 跨服务关联检测
# ---------------------------------------------------------------------------
def find_cross_links(services):
    """两两匹配：若两服务概念指纹有交集 → 潜在关联"""
    links = []
    n = len(services)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = services[i], services[j]
            shared = a["concepts"] & b["concepts"]
            if shared:
                # 强度：共享概念数
                strength = len(shared)
                # 级联：任一方为高风险且存在关联 → 级联升级候选
                cascade = (a["risk"] == "high" or b["risk"] == "high")
                links.append({
                    "services": [a["service"], b["service"]],
                    "shared_concepts": sorted(shared),
                    "strength": strength,
                    "cascade": cascade,
                    "a_module": [m for m in a["module_names"] if extract_concepts([m]) & shared],
                    "b_module": [m for m in b["module_names"] if extract_concepts([m]) & shared],
                })
    # 按强度降序
    links.sort(key=lambda x: x["strength"], reverse=True)
    return links


def aggregate_risk(services, cross_links):
    base = "low"
    for s in services:
        if RISK_RANK.get(s["risk"], 0) > RISK_RANK.get(base, 0):
            base = s["risk"]
    # 级联升级：存在跨服务关联且涉及高风险服务 → 综合标注「级联高风险」
    cascade = any(l["cascade"] for l in cross_links) and base == "high"
    return base, cascade


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def badge(risk):
    c = RISK_COLOR.get(risk, "#5f6368")
    return f'<span style="display:inline-block;padding:3px 12px;border-radius:12px;color:#fff;background:{c};font-weight:600;font-size:13px">{RISK_LABEL.get(risk, risk)}风险</span>'


def render_service_card(s, absolute=False):
    global OUT_DIR
    m = s["metrics"]
    fc = m.get("files_changed", "—")
    la = m.get("lines_added", "—")
    lr = m.get("lines_removed", "—")
    det = s["detections"]
    det_tags = []
    if det.get("data_format_change"):
        det_tags.append('<span style="color:#d93025">⚠ 数据格式变更</span>')
    if det.get("version_rollback"):
        det_tags.append('<span style="color:#d93025">⚠ 版本回退</span>')
    if det.get("sensitive_info"):
        det_tags.append('<span style="color:#d93025">⚠ 敏感信息</span>')
    if det.get("test_sync_needed"):
        det_tags.append('<span style="color:#f9ab00">⚠ 测试同步</span>')
    if det.get("circular_dependency"):
        det_tags.append('<span style="color:#d93025">⚠ 循环依赖</span>')
    det_html = " ".join(det_tags) if det_tags else '<span style="color:#188038">无专项告警</span>'

    # Bug 口径（2026-09-18 项目级池改造 / 2026-09-19 归口规则）：
    #   项目级池 = 按提测版本整包关联，前后端共用同一份 Bug 列表。按用户决策，
    #   Bug 数据归口到综合报告第 ⑤ 节（各版本 Bug 数据明细）统一展示；
    #   此处摘要卡只做「指引」，不再重复铺开总数与端归属拆分，避免
    #   每个服务卡都挂着同一个 49 造成「每个服务都有 49 个 Bug」的误读。
    #   服务级（非项目池）仍保留原「关联 Bug」（metrics 记录的 bug_links）。
    if s.get("bugs_scope") == "project":
        bug_span = (f'<span>项目级 Bug：<b>{s["bug_summary"]["total"]}</b>'
                    f'<span style="color:#5f6368;font-size:12px">'
                    f'（前后端共用同一池；明细与前端/后端拆分见 ⑤）</span></span>')
    else:
        bug_span = f'<span>关联 Bug：<b>{len(s["bug_links"])}</b></span>'

    link = ""
    if s["report_path"]:
        # 跳转链接生成策略（2026-09-10 可移植化改造）：
        # - 默认【相对路径】relative：综合报告在 report/code-diff/_综合/，服务报告在
        #   report/code-diff/{service}/，二者同级，相对路径即 ../{service}/xxx.html。
        #   相对链接可随目录整体拷贝到任意机器直接点击，不依赖本机绝对路径，
        #   彻底解决「发给同事打不开」的问题（单文件 HTML 亦无外部依赖）。
        # - --absolute 时可回退旧【绝对 file:/// 路径】：仅本地预览用，路径写死本机
        #   d:/...，不可分享。仍遵守「不带 target 属性」约束（WorkBuddy 预览器拦截
        #   file:// 链接，带 target 点击失效，2026-08-13 实测）。
        if absolute:
            url_path = s["report_path"].replace("\\", "/")
            if url_path.startswith("/"):
                url_path = url_path.lstrip("/")
            href = f"file:///{url_path}"
        else:
            try:
                href = os.path.relpath(s["report_path"], OUT_DIR).replace("\\", "/")
            except ValueError:
                # 跨盘符等无法计算相对路径时回退绝对 file:///
                href = "file:///" + s["report_path"].replace("\\", "/").lstrip("/")
        link = f'<a href="{href}" style="color:#1a73e8;text-decoration:none">查看独立报告 →</a>'

    return f"""
    <div style="border:1px solid #e8eaed;border-radius:10px;padding:18px;margin-bottom:14px;background:#fff">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:16px;font-weight:700;color:#202124">{s['service']}</div>
        {badge(s['risk'])}
      </div>
      <div style="font-size:13px;color:#5f6368;margin-bottom:8px">版本：{s['version_from']} → <b>{s['version_to']}</b></div>
      <div style="display:flex;gap:18px;font-size:13px;color:#3c4043;margin-bottom:8px;flex-wrap:wrap">
        <span>变更文件：<b>{fc}</b></span>
        <span>新增 <span style="color:#188038">+{la}</span></span>
        <span>删除 <span style="color:#d93025">-{lr}</span></span>
        {bug_span}
      </div>
      <div style="font-size:13px;margin-bottom:8px">{det_html}</div>
      <div style="font-size:13px">{link}</div>
    </div>"""


def render_cross_links(links):
    if not links:
        return '<p style="color:#5f6368">未检测到显著的跨服务概念关联（基于业务概念词典匹配）。各服务变更相对独立。</p>'
    rows = []
    for l in links:
        cascade_tag = '<span style="color:#d93025;font-weight:600">🔥 级联高风险</span>' if l["cascade"] else ""
        shared = "、".join(l["shared_concepts"])
        rows.append(f"""
        <div style="border-left:4px solid #1a73e8;background:#f8f9fa;border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:12px">
          <div style="font-weight:600;color:#202124;margin-bottom:6px">
            {l['services'][0]} ⇄ {l['services'][1]} {cascade_tag}
          </div>
          <div style="font-size:13px;color:#3c4043">共享概念：<b>{shared}</b>（匹配强度 {l['strength']}）</div>
          <div style="font-size:12px;color:#5f6368;margin-top:4px">
            模块：{l['services'][0]} → {', '.join(l['a_module']) or '—'} ｜ {l['services'][1]} → {', '.join(l['b_module']) or '—'}
          </div>
          <div style="font-size:12px;color:#d93025;margin-top:4px">验证建议：确认两端对该概念的实现口径/单位/接口是否一致（如 token 单位、字段命名、接口路径）。</div>
        </div>""")
    return "".join(rows)


def render_test_priority(services):
    """合并各服务 high-risk 模块去重，作为 P1 必测清单"""
    items = []
    for s in services:
        for m in (s["latest"].get("modules", []) if s["latest"] else []):
            if m.get("risk") == "high":
                items.append((s["service"], m.get("name", "")))
    if not items:
        return '<p style="color:#5f6368">本次各服务无 high-risk 模块，P1 必测项较少，以 P2 建议项为主。</p>'
    rows = "".join(
        f'<tr><td>{svc}</td><td>{name}</td><td><span style="color:#d93025;font-weight:600">P1 必测</span></td></tr>'
        for svc, name in items
    )
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr style="background:#fafafa"><th style="padding:8px;text-align:left">服务</th><th style="padding:8px;text-align:left">高风险模块</th><th style="padding:8px;text-align:left">优先级</th></tr></thead><tbody>{rows}</tbody></table>'


def render_bug_version_section(services):
    """综合报告含 ≥2 服务时，汇总各版本 Bug 数据（单服务详见其独立报告）。

    规则（2026-09-16 用户建议）：综合报告展示「各版本 Bug 数据明细」，
    除非组合里只有一个服务（此时 Bug 数据已在单服务独立报告中）。
    """
    if len(services) < 2:
        return ""
    blocks = []
    any_data = False
    # 项目级池：所有服务共享同一份 Bug 池，只渲染一次，标「项目级」
    data_services = [s for s in services
                     if (s.get("bug_version", {}).get("found") or s.get("bug_version", {}).get("fixed"))]
    project_mode = bool(data_services) and all(s.get("bugs_scope") == "project" for s in data_services)
    # 项目级：所有服务共享同一份池 → 只渲染一次，且**只出一张精简汇总表**。
    # （2026-09-18）原本渲染「产生版本 / 解决版本」两张表、每行还重复 20 字的
    # 服务名标签，与同节上方 bug_trend 注入的「③ 版本维度明细」完全重复 → 展示冗长。
    # 现改为单表（版本 / 发现 / 修复），标签用短名「项目级」。
    if project_mode:
        # 项目级：本节只保留 intro + bug_trend 注入的区块（其「③ 版本维度明细」
        # 已含 版本/发现/修复/严重度/修复率/风险分 全量），不再另出汇总表重复渲染。
        if not data_services[0].get("bug_version", {}).get("found"):
            return ""
        return f"""
  <div class="section">
    <h2>⑤ 各版本 Bug 数据明细</h2>
    <p style="font-size:13px;color:#5f6368;margin-bottom:10px">Bug 采用<b>项目级关联口径</b>（按提测版本整包，含前后端全部缺陷，不区分、不归因到单一服务）。下表由 bug_trend.py 注入，含各版本发现/修复、严重度分布、修复率与风险分口径；单服务视角详见其独立报告。</p>
    <!-- BUG_TREND_COMBINED -->
  </div>"""
    render_list = data_services
    for s in render_list:
        bv = s.get("bug_version", {})
        if not bv.get("found") and not bv.get("fixed"):
            continue
        any_data = True
        svc = s["service"]
        found_rows = []
        for ver, cnt in sorted(bv.get("found", {}).items(), key=version_key):
            sev = bv.get("severity_by_found", {}).get(ver, {})
            sev_str = " / ".join(f"{k} {v}" for k, v in sev.items()) if sev else "—"
            found_rows.append(
                f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{svc}</td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{ver}</td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{cnt}</td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{sev_str}</td></tr>")
        fixed_rows = []
        for ver, cnt in sorted(bv.get("fixed", {}).items(), key=version_key):
            fixed_rows.append(
                f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{svc}</td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{ver}</td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #e8eaed'>{cnt}</td></tr>")
        if found_rows or fixed_rows:
            blocks.append(f"""
      <div style="margin:10px 0">
        <div style="font-size:14px;font-weight:700;margin:10px 0 6px">{svc}</div>
        <div style="font-size:13px;color:#5f6368;margin-bottom:4px">按「产生版本」（发现版本）</div>
        <table style="width:100%;border-collapse:collapse;font-size:12.5px;background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#fafafa"><th style="padding:6px 8px;text-align:left">服务</th><th style="padding:6px 8px;text-align:left">产生版本</th><th style="padding:6px 8px;text-align:left">Bug 数</th><th style="padding:6px 8px;text-align:left">严重度分布</th></tr></thead>
          <tbody>{''.join(found_rows)}</tbody></table>
        <div style="font-size:13px;color:#5f6368;margin:8px 0 4px">按「解决版本」（修复版本）</div>
        <table style="width:100%;border-collapse:collapse;font-size:12.5px;background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#fafafa"><th style="padding:6px 8px;text-align:left">服务</th><th style="padding:6px 8px;text-align:left">解决版本</th><th style="padding:6px 8px;text-align:left">Bug 数</th></tr></thead>
          <tbody>{''.join(fixed_rows)}</tbody></table>
      </div>""")
    if not any_data:
        return ""
    scope_hint = ("Bug 采用<b>项目级关联口径</b>（按提测版本整包，含前后端全部缺陷，"
                  "不区分、不归因到单一服务）。" if project_mode else "下表按服务展示产生版本 / 解决版本分布。")
    return f"""
  <div class="section">
    <h2>⑤ 各版本 Bug 数据明细</h2>
    <p style="font-size:13px;color:#5f6368;margin-bottom:10px">综合报告含 ≥2 服务时汇总各版本 Bug 数据（单服务详见其独立报告）。{scope_hint}</p>
    <!-- BUG_TREND_COMBINED -->
    {''.join(blocks)}
  </div>"""


def render_combined_html(services, cross_links, combined_risk, cascade, out_path, absolute=False):
    global OUT_PATH, OUT_DIR
    OUT_PATH = out_path
    OUT_DIR = os.path.dirname(out_path)
    # 综合总览
    total_files = sum(s["metrics"].get("files_changed", 0) or 0 for s in services)
    # 项目级池时 Bug 汇总只取一次（所有服务共享同一池，求和会重复计数）
    bug_data = [s for s in services if s["bug_summary"]["total"]]
    if bug_data and all(s.get("bugs_scope") == "project" for s in bug_data):
        pool_sum = bug_data[0]["bug_summary"]
        total_bugs, total_closed, total_resolved = (
            pool_sum["total"], pool_sum["closed"], pool_sum["resolved"])
    else:
        total_bugs = sum(s["bug_summary"]["total"] for s in services)
        total_closed = sum(s["bug_summary"]["closed"] for s in services)
        total_resolved = sum(s["bug_summary"]["resolved"] for s in services)
    versions = sorted({s["version_to"] for s in services if s["version_to"]}, key=version_key)
    batch = "、".join(versions) if versions else "—"

    cards = f"""
    <div style="display:flex;gap:14px;flex-wrap:wrap;margin:18px 0">
      <div style="flex:1;min-width:140px;background:#f8f9fa;border:1px solid #e8eaed;border-radius:10px;padding:14px"><div style="font-size:24px;font-weight:700">{len(services)}</div><div style="color:#5f6368;font-size:13px">涉及服务</div></div>
      <div style="flex:1;min-width:140px;background:#f8f9fa;border:1px solid #e8eaed;border-radius:10px;padding:14px"><div style="font-size:24px;font-weight:700">{batch}</div><div style="color:#5f6368;font-size:13px">版本批次</div></div>
      <div style="flex:1;min-width:140px;background:#f8f9fa;border:1px solid #e8eaed;border-radius:10px;padding:14px"><div style="font-size:24px;font-weight:700">{total_files}</div><div style="color:#5f6368;font-size:13px">总变更文件</div></div>
      <div style="flex:1;min-width:140px;background:#f8f9fa;border:1px solid #e8eaed;border-radius:10px;padding:14px"><div style="font-size:24px;font-weight:700">{total_bugs}</div><div style="color:#5f6368;font-size:13px">{'项目级 Bug' if (bug_data and all(s.get('bugs_scope')=='project' for s in bug_data)) else '总关联 Bug'}（已关闭 {total_closed} / 已解决 {total_resolved}）</div></div>
    </div>"""

    version_matrix_rows = "".join(
        f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #e8eaed;font-weight:600">{s['service']}</td>
            <td style="padding:8px;border-bottom:1px solid #e8eaed">{s['version_from'] or '—'}</td>
            <td style="padding:8px;border-bottom:1px solid #e8eaed">{s['version_to'] or '—'}</td>
            <td style="padding:8px;border-bottom:1px solid #e8eaed">{RISK_LABEL.get(s['risk'], s['risk'] or '—')}</td>
           </tr>"""
        for s in services
    )
    version_matrix = f"""
    <div style="margin:18px 0">
      <div style="font-size:14px;font-weight:700;margin-bottom:8px">各服务变更版本矩阵</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden">
        <thead><tr style="background:#fafafa"><th style="padding:8px;text-align:left">服务</th><th style="padding:8px;text-align:left">起始版本</th><th style="padding:8px;text-align:left">目标版本</th><th style="padding:8px;text-align:left">风险</th></tr></thead>
        <tbody>{version_matrix_rows}</tbody>
      </table>
    </div>"""

    risk_banner = badge(combined_risk)
    if cascade:
        risk_banner += ' <span style="display:inline-block;padding:3px 12px;border-radius:12px;color:#fff;background:#d93025;font-weight:600;font-size:13px;margin-left:8px">🔥 含级联高风险</span>'

    # 发布建议
    if combined_risk == "high":
        advice = "建议<b>分批灰度发布</b>：优先发布低风险服务，高风险服务（含级联影响）需配套回归测试与监控；跨服务强关联点（见③）须两端联调验证后再全量。"
    elif combined_risk == "medium":
        advice = "建议<b>正常发布 + 重点回归</b>：对 high-risk 模块（见④）执行 P1 必测，跨服务关联点做联调抽检。"
    else:
        advice = "建议<b>整体发布</b>：变更风险较低，按常规回归即可。"

    bug_version_section = render_bug_version_section(services)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>综合比对分析报告</title>
<style>
  body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:#f5f7fa;margin:0;padding:24px;color:#202124}}
  .wrap{{max-width:1080px;margin:0 auto}}
  .header{{background:#1a73e8;color:#fff;border-radius:12px;padding:24px;margin-bottom:20px}}
  .header h1{{margin:0 0 8px;font-size:24px}}
  .header .meta{{font-size:13px;opacity:.9}}
  .section{{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
  .section h2{{font-size:19px;font-weight:700;margin:0 0 16px;padding-bottom:10px;border-bottom:2px solid #1a73e8}}
  table{{border-collapse:collapse}}
</style></head>
<body><div class="wrap">
  <div class="header">
    <h1>📊 综合代码比对分析报告</h1>
    <div class="meta">服务：{'、'.join(s['service'] for s in services)} ｜ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ 模式：摘要卡 + 跨服务关联（启发式）</div>
  </div>

  <div class="section">
    <h2>① 综合总览</h2>
    <div style="margin-bottom:14px">综合风险等级：{risk_banner}</div>
    {cards}
    {version_matrix}
  </div>

  <div class="section">
    <h2>② 各服务摘要卡</h2>
    {''.join(render_service_card(s, absolute) for s in services)}
    <!-- QUANT_JIT_COMBINED -->
    <!-- BUG_PREDICT_COMBINED -->
  </div>

  <div class="section">
    <h2>③ 跨服务关联与级联风险</h2>
    {render_cross_links(cross_links)}
  </div>

  <div class="section">
    <h2>④ 统一测试优先级（P1 必测）</h2>
    {render_test_priority(services)}
  </div>

  {bug_version_section}

  <div class="section">
    <h2>⑥ 综合发布建议</h2>
    <p style="font-size:14px;line-height:1.8">{advice}</p>
  </div>
</div></body></html>"""
    return html


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    import sys
    ap = argparse.ArgumentParser(description="Code Diff Analyzer · 综合比对分析报告")
    ap.add_argument("--services", nargs="+", required=True, help="参与综合的服务名列表")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常", help="工作区根目录")
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--report-root", help="覆盖 report/code-diff 根目录")
    ap.add_argument("--out", help="综合报告输出路径（缺省自动生成到 report/code-diff/_综合/）")
    ap.add_argument("--absolute", action="store_true",
                    help="跳转链接使用绝对 file:/// 路径（仅本地预览，不可分享）；默认使用相对路径以支持跨机器分享")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")
    report_root = args.report_root or os.path.join(args.workspace, "report", "code-diff")

    services = []
    for svc in args.services:
        if not os.path.isdir(os.path.join(analytics_root, svc)):
            sys.stderr.write(f"[WARN] 跳过未找到 analytics 的服务: {svc}\n")
            continue
        services.append(load_service(svc, analytics_root, report_root))

    if not services:
        sys.stderr.write("[ERROR] 未加载到任何有效服务数据，请先对各服务运行单服务分析。\n")
        raise SystemExit(1)

    cross_links = find_cross_links(services)
    combined_risk, cascade = aggregate_risk(services, cross_links)

    out = args.out or os.path.join(
        report_root, "_综合",
        f"综合比对分析报告_{'_'.join(s['service'] for s in services)}_{datetime.now().strftime('%Y%m%d')}.html"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    safe_write_report(out, render_combined_html(services, cross_links, combined_risk, cascade, out, args.absolute))

    print(f"[OK] 综合比对报告已生成: {out}")
    print(f"     服务数={len(services)} 综合风险={RISK_LABEL.get(combined_risk, combined_risk)}"
          f"{' [含级联高风险]' if cascade else ''} 跨服务关联={len(cross_links)} 条")


if __name__ == "__main__":
    main()
