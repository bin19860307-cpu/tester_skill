#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_analytics.py — 数据沉淀确定性重建 + 完整性自检

对应 2026-09-18 体检缺陷 P0-4（file_history 非确定性丢失）：

  实测：3/5 服务严重丢失，2/5 完整 —— 是**非确定性缺陷**，不是"写入逻辑少写一段"
      main-frontend    累计 18 个变更文件 → file_history 只有 1 条（丢 94%）
      manage-frontend  累计 45 个          → 只有 2 条（丢 96%）
      portal-backend   累计 19 个          → 只有 6 条（丢 68%）
      trufar-frontend  累计 11 个          → 11 条（完整，但混入输入产物 tagdiff.txt）
      trufar-landing-page 7 个             → 7 条（完整）
  根因：SKILL.md Step 6.2.3 让 LLM **逐文件手工追加**，漏写不会被任何机制发现。

本脚本把这一步从「LLM 手工」改成「脚本确定性重建」：
  数据源 = service_metrics.json 各记录的 `files` 数组（LLM 只需给出文件清单，
  不再负责逐条维护 file_history）。重建幂等，可反复运行。

两条硬约束（自检）：
  1. 每个区间写入的条目数 == 该记录 metrics.files_changed
  2. 输入产物 / 临时文件绝不允许进 file_history（走 _common.JUNK_PATTERNS 硬排除）

兼容性：没有 `files` 清单的历史记录**不做破坏性重建**——其原有条目原样保留，
只在报告里标注「无法核验」，避免为了"整齐"而丢掉既有数据。

用法：
    python scripts/sync_analytics.py --service portal-backend              # 重建 + 自检
    python scripts/sync_analytics.py --service portal-backend --check      # 只自检不改动
    python scripts/sync_analytics.py --all                                 # 全部服务
    python scripts/sync_analytics.py --all --json                          # 机器可读输出
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # 统一友好错误层
from _common import (  # noqa: E402
    norm_version, version_key, version_series, normalize_path,
    is_junk_path, is_logic_path, filter_change_files,
)

DEFAULT_WORKSPACE = r"d:/workbuddy/测试日常"


def load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _range_key(rec):
    """记录 -> 统一的版本区间键（规范键，去前缀），file_history 的 appear_in 用它。"""
    vf = norm_version(rec.get("version_from")) or str(rec.get("version_from") or "?")
    vt = norm_version(rec.get("version_to")) or str(rec.get("version_to") or "?")
    return f"{vf}→{vt}"


def _extract_files(rec):
    """从记录里取变更文件清单（兼容 files / changed_files 两种写法）。

    返回 (kept, dropped, declared)：declared = metrics.files_changed
    """
    raw = rec.get("files") or rec.get("changed_files") or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace(",", "\n").splitlines()]
    kept, dropped = filter_change_files(raw)
    declared = (rec.get("metrics") or {}).get("files_changed")
    return kept, dropped, declared


def check_file_history(service, analytics_root):
    """只读自检：返回 {issues: [...], expected, actual, missing, junk, per_range}。

    检查项：
      C1 文件头 service / schema_version 是否齐全
      C2 条目是否写在 `files` 包裹层内（早期漏包裹层，导致读取失效）
      C3 是否混入输入产物 / 临时文件（JUNK）
      C4 每个有 `files` 清单的区间：条目数是否等于 metrics.files_changed
      C5 缺 `files` 清单的区间：标注「无法核验」而非判定失败
    """
    svc_dir = os.path.join(analytics_root, service)
    out = {"service": service, "issues": [], "expected": 0, "actual": 0,
           "missing": 0, "junk": [], "per_range": [], "unverifiable": []}

    fh = load_json(os.path.join(svc_dir, "file_history.json"))
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json"))
    if fh is None:
        out["issues"].append("C0 file_history.json 不存在")
        return out

    # C1 / C2
    if not fh.get("service"):
        out["issues"].append("C1 缺少文件头 `service`")
    if not fh.get("schema_version"):
        out["issues"].append("C1 缺少文件头 `schema_version`")
    files_obj = fh.get("files")
    if not isinstance(files_obj, dict):
        # 尝试旧扁平结构
        flat = {k: v for k, v in fh.items()
                if isinstance(v, dict) and "change_count" in v}
        if flat:
            out["issues"].append(
                "C2 条目未写在 `files` 包裹层内（旧扁平结构，%d 条）；"
                "quant_jit_risk 虽兼容读取，但新写入一律按规范结构" % len(flat))
            files_obj = flat
        else:
            out["issues"].append("C2 找不到任何文件条目（`files` 为空）")
            files_obj = {}

    out["actual"] = len(files_obj)

    # C3 脏项
    for path in files_obj:
        if is_junk_path(path):
            out["junk"].append(path)
    if out["junk"]:
        out["issues"].append(
            "C3 混入输入产物/临时文件 %d 条：%s" % (len(out["junk"]), ", ".join(out["junk"][:5])))

    # C4 / C5
    records = (metrics or {}).get("records", [])
    for rec in records:
        rk = _range_key(rec)
        declared = (rec.get("metrics") or {}).get("files_changed")
        raw_files = rec.get("files") or rec.get("changed_files")
        if raw_files:
            kept, _dropped, _dec = _extract_files(rec)
            # 统计 file_history 中 appear_in 覆盖该区间的条目数
            covered = sum(1 for v in files_obj.values()
                          if isinstance(v, dict) and rk in (v.get("appear_in") or []))
            out["expected"] += len(kept)
            ok = (covered == len(kept))
            if not ok:
                out["missing"] += max(0, len(kept) - covered)
                out["issues"].append(
                    "C4 区间 %s 条目数不符：file_history %d 条 vs 文件清单 %d 条"
                    % (rk, covered, len(kept)))
            elif declared is not None and declared != len(kept):
                out["issues"].append(
                    "C4 区间 %s 文件清单 %d 条 vs metrics.files_changed %s（清单本身不完整）"
                    % (rk, len(kept), declared))
            out["per_range"].append({"range": rk, "expected": len(kept),
                                     "covered": covered, "ok": ok})
        else:
            if declared:
                out["unverifiable"].append({"range": rk, "files_changed": declared})
                out["expected"] += declared
    if out["unverifiable"]:
        out["issues"].append(
            "C5 %d 个区间缺 `files` 清单，无法核验（共声明 %d 个变更文件）；"
            "这些区间不做破坏性重建，原条目保留"
            % (len(out["unverifiable"]), sum(x["files_changed"] for x in out["unverifiable"])))
    return out


def rebuild_file_history(service, analytics_root, dry_run=False):
    """确定性重建 file_history.json。

    算法（幂等）：
      1. 取 service_metrics 中**带 `files` 清单**的区间集合 R
      2. 从现有 file_history 中剥离属于 R 的贡献（appear_in / risk_history / change_types
         按位置同步剥离），appear_in 清空的条目删除
      3. 用 R 的清单重新写入条目（硬排除 JUNK，记录是否逻辑文件）
      4. 返回 (doc, report)

    没有 `files` 清单的历史区间**不参与重建**，其条目原样保留。
    """
    svc_dir = os.path.join(analytics_root, service)
    fh_path = os.path.join(svc_dir, "file_history.json")
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json")) or {"records": []}
    old = load_json(fh_path) or {}

    old_files = old.get("files")
    if not isinstance(old_files, dict):
        old_files = {k: v for k, v in old.items()
                     if isinstance(v, dict) and "change_count" in v}

    report = {"service": service, "rebuilt_ranges": [], "rebuilt_entries": 0,
              "preserved_entries": 0, "dropped_junk": [], "purged_junk": [],
              "mismatch": [], "removed_stale": []}

    # ---- 1) 待重建区间 ----
    plan = []           # [(range_key, [files])]
    for rec in metrics.get("records", []):
        raw_files = rec.get("files") or rec.get("changed_files")
        if not raw_files:
            continue
        rk = _range_key(rec)
        kept, dropped, declared = _extract_files(rec)
        report["dropped_junk"] += dropped
        plan.append((rk, kept))
        if declared is not None and declared != len(kept):
            report["mismatch"].append(
                {"range": rk, "files_list": len(kept), "metrics_files_changed": declared})

    rebuild_ranges = {p[0] for p in plan}

    # ---- 1.5) 无条件清除脏项 ----
    # 输入产物 / 临时文件**永远不是变更代码**，与所属区间无关 → 不参与"保留"逻辑。
    # 实例：trufar-frontend 里的 manage-5.1.0.5_tagdiff.txt（输入文件被当成变更文件）。
    purged_junk = []
    for path in list(old_files.keys()):
        if is_junk_path(path):
            purged_junk.append(path)
            old_files.pop(path, None)
    report["purged_junk"] = purged_junk

    # ---- 2) 剥离旧贡献 ----
    stripped = {}
    for path, entry in old_files.items():
        if not isinstance(entry, dict):
            continue
        appear = list(entry.get("appear_in") or [])
        rh = list(entry.get("risk_history") or [])
        ct = list(entry.get("change_types") or [])
        keep_idx = [i for i, a in enumerate(appear) if a not in rebuild_ranges]
        if len(keep_idx) == len(appear):
            stripped[path] = dict(entry)          # 未受影响，原样保留
            continue
        if not keep_idx:
            report["removed_stale"].append(path)
            continue
        stripped[path] = {
            "change_count": len(keep_idx),
            "appear_in": [appear[i] for i in keep_idx],
            "risk_history": [rh[i] for i in keep_idx if i < len(rh)] or ["unknown"] * len(keep_idx),
            "change_types": [ct[i] for i in keep_idx if i < len(ct)] or ["modified"] * len(keep_idx),
            "_logic": entry.get("_logic", True),
        }

    # ---- 3) 用清单写入新区间（含风险等级）----
    for rec in metrics.get("records", []):
        raw_files = rec.get("files") or rec.get("changed_files")
        if not raw_files:
            continue
        rk = _range_key(rec)
        kept, _d, _dec = _extract_files(rec)
        risk = _record_risk(rec)
        for path in kept:
            e = stripped.setdefault(path, {
                "change_count": 0, "appear_in": [], "risk_history": [], "change_types": [],
                "_logic": is_logic_path(path),
            })
            if rk in e["appear_in"]:              # 幂等保护
                continue
            e["appear_in"].append(rk)
            e["risk_history"].append(risk)
            e["change_types"].append("modified")
            e["change_count"] = len(e["appear_in"])
            e["_logic"] = is_logic_path(path)
        report["rebuilt_ranges"].append({"range": rk, "files": len(kept), "risk": risk})
        report["rebuilt_entries"] += len(kept)

    report["preserved_entries"] = len(stripped) - report["rebuilt_entries"]

    doc = {
        "service": service,
        "schema_version": "1.0",
        "files": dict(sorted(stripped.items())),
        "recent_changes": (old.get("recent_changes") or [])[-20:],
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synced_by": "sync_analytics.py（确定性重建；仅重建带 `files` 清单的区间）",
    }
    if not dry_run:
        write_json(fh_path, doc)
    return doc, report


def _record_risk(rec):
    """记录级风险等级（取 modules 最高等级，无 modules 时按高风险计数推断）。"""
    order = {"high": 3, "medium": 2, "low": 1}
    best, label = 0, "low"
    for mod in (rec.get("modules") or []):
        r = str((mod or {}).get("risk") or "").lower()
        if order.get(r, 0) > best:
            best, label = order[r], r
    m = rec.get("metrics") or {}
    if best == 0:
        if int(m.get("high_risk") or 0):
            label = "high"
        elif int(m.get("medium_risk") or 0):
            label = "medium"
    return label


# ----------------------------------------------------------------------------
# 从历史 HTML 报告回填 `files` 清单（只回填能完整还原的区间）
# ----------------------------------------------------------------------------
# 报告里的「变更总览表」是**聚合摘要**，常见通配/折叠写法，例如：
#     views/teachMng/* (33 文件)
#     packages/base/src/components/admin-layout/components/{index,layout-*}.vue
#     views/home/*、权益页、帮助页
# 这些**不可还原**为逐文件清单 —— 必须如实标注，绝不能凭 glob 猜文件名。
_LOSSY_MARKERS = ("*", "{", "}", "...", "…", "（", "(", "文件）", "、")
_OVERVIEW_RE = re.compile(r'<table class="overview-table">(.*?)</table>', re.S)
_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
# 看起来像文件路径的行（含扩展名或路径分隔符）
_FILEY_RE = re.compile(r"[\w./-]+\.[A-Za-z]{1,6}$")


def extract_report_file_list(html_path):
    """从报告 HTML 的变更总览表提取文件清单。

    返回 {"files": [...], "lossy": bool, "rows": int, "lossy_reason": str|None}
    lossy=True 表示该报告用了通配/折叠写法，**不可作为完整清单**。
    """
    try:
        h = open(html_path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return {"files": [], "lossy": True, "rows": 0, "lossy_reason": f"读取失败: {e}"}
    m = _OVERVIEW_RE.search(h)
    if not m:
        return {"files": [], "lossy": True, "rows": 0, "lossy_reason": "找不到变更总览表"}

    names, lossy_reason = [], None
    rows = _ROW_RE.findall(m.group(1))
    for r in rows:
        cells = _CELL_RE.findall(r)
        if not cells:
            continue
        raw = _TAG_RE.sub("", cells[0]).strip()
        if not raw or raw in ("文件", "文件路径"):
            continue
        # 通配 / 折叠 / 顿号并列 → 不可还原
        if any(mk in raw for mk in _LOSSY_MARKERS):
            lossy_reason = lossy_reason or f"含通配或折叠写法：{raw[:60]}"
            continue
        # 「A.java / B.java / C.java」形式可拆
        parts = [p.strip() for p in re.split(r"\s*/\s*", raw) if p.strip()]
        for p in parts:
            p = p.strip()
            if _FILEY_RE.search(p) and p not in names:
                names.append(p)
    return {"files": names, "lossy": bool(lossy_reason), "rows": len(rows),
            "lossy_reason": lossy_reason}


def find_report_for_range(service, report_root, rec):
    """按版本号在报告文件名中定位对应报告（规范键包含匹配，顺序敏感）。"""
    svc_dir = os.path.join(report_root, service)
    if not os.path.isdir(svc_dir):
        return None
    a = norm_version(rec.get("version_from"))
    b = norm_version(rec.get("version_to"))
    if not a or not b:
        return None
    cands = []
    for fn in os.listdir(svc_dir):
        if not fn.lower().endswith((".html", ".htm")):
            continue
        low = fn.lower()
        ia, ib = low.find(a), low.find(b)
        if ia >= 0 and ib >= 0 and ia < ib:
            cands.append(os.path.join(svc_dir, fn))
    return sorted(cands, key=lambda p: -os.path.getsize(p))[0] if cands else None


def backfill_files_from_reports(service, analytics_root, report_root):
    """为缺 `files` 清单的历史记录，尝试从报告回填。

    严格规则（宁缺勿造）：
      · 报告必须是「可完整还原」的（无通配/折叠）
      · 还原出的文件数必须**等于** metrics.files_changed
      只有同时满足才写入 `files`，并标 `files_source = backfill:report-html`。
      否则记为 unrecoverable，输出原因，交给 doctor 如实呈现。
    """
    svc_dir = os.path.join(analytics_root, service)
    mp = os.path.join(svc_dir, "service_metrics.json")
    metrics = load_json(mp)
    if not metrics:
        return {"service": service, "backfilled": [], "unrecoverable": []}

    backfilled, unrecoverable, changed = [], [], False
    for rec in metrics.get("records", []):
        if rec.get("files"):
            continue
        declared = (rec.get("metrics") or {}).get("files_changed")
        rk = _range_key(rec)
        rp = find_report_for_range(service, report_root, rec)
        if not rp:
            unrecoverable.append({"range": rk, "declared": declared,
                                  "reason": "未找到对应报告"})
            continue
        ex = extract_report_file_list(rp)
        kept, _dropped = filter_change_files(ex["files"])
        if ex["lossy"]:
            unrecoverable.append({"range": rk, "declared": declared,
                                  "reason": f"报告为聚合摘要，不可还原（{ex['lossy_reason']}）",
                                  "report": os.path.basename(rp)})
            continue
        if declared and len(kept) != int(declared):
            unrecoverable.append({
                "range": rk, "declared": declared, "extracted": len(kept),
                "reason": f"报告仅含 {len(kept)} 个文件，少于声明的 {declared}，视为不完整",
                "report": os.path.basename(rp)})
            continue
        rec["files"] = kept
        rec["files_source"] = "backfill:report-html"
        rec["files_source_ref"] = os.path.basename(rp)
        changed = True
        backfilled.append({"range": rk, "files": len(kept),
                           "report": os.path.basename(rp)})

    if changed:
        metrics["files_backfilled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_json(mp, metrics)
    return {"service": service, "backfilled": backfilled, "unrecoverable": unrecoverable}


def sync_version_chain(service, analytics_root, dry_run=False):
    """version_chain.json 规范键归一 + 去重（不新增版本，只清理写法）。"""
    svc_dir = os.path.join(analytics_root, service)
    path = os.path.join(svc_dir, "version_chain.json")
    chain = load_json(path)
    if chain is None:
        return None
    versions = chain.get("versions") or []
    seen, merged = set(), []
    for v in versions:
        ver = (v or {}).get("version")
        ck = norm_version(ver)
        if not ck or ck in seen:
            continue
        seen.add(ck)
        merged.append({
            "version": ck,                      # 统一写规范键，从源头消除写法分裂
            "date": (v or {}).get("date"),
            "parent": norm_version((v or {}).get("parent")),
            "_source_version_raw": ver,
        })
    merged.sort(key=lambda x: version_key(x["version"]))
    out = dict(chain)
    out["versions"] = merged
    out["version_key_policy"] = "写入前一律 norm_version()，禁止带业务前缀"
    if not dry_run:
        write_json(path, out)
    return {"service": service, "before": len(versions), "after": len(merged),
            "deduped": len(versions) - len(merged)}


def normalize_version_fields(service, analytics_root, dry_run=False):
    """存储层版本键归一：把各文件的版本字段改写为规范键，原文另存 `*_raw`。

    【为什么必须在存储层做】
      只在消费方归一（bug_correlate / bug_trend）能修好"算不对"，但**治不了根**：
      同一版本仍会在 service_metrics 写 `business-5.3.0.2`、在 version_chain 写 `v5.3.0.2`、
      在 version_bugs 写 `5.3.0.2` —— 下一个新脚本一旦忘了调 norm_version 就再次断裂。
      存储层归一后，「同一版本只有一种写法」成为**数据不变量**，靠 doctor D2 持续守门。

    改写范围：
      service_metrics.records[].version_from / version_to   → 规范键（原文存 version_*_raw）
      version_chain.versions[].version / parent             → 规范键（原文存 _source_version_raw / parent_raw）
      cross_reference.mappings[].version_to / version_range → 规范键
      version_bugs.bugs[].found_in_version / fixed_in_version → 规范键（原文存 *_raw）
      注：TAPD 导出的原始值一定保留在 *_raw，便于回溯与比对。
    """
    svc_dir = os.path.join(analytics_root, service)
    changed = {"service_metrics": 0, "version_chain": 0, "cross_reference": 0, "version_bugs": 0}

    # ---- service_metrics ----
    p = os.path.join(svc_dir, "service_metrics.json")
    doc = load_json(p)
    if doc:
        for r in doc.get("records", []):
            for k in ("version_from", "version_to"):
                v = r.get(k)
                nv = norm_version(v)
                if nv and nv != v:
                    r.setdefault(k + "_raw", v)
                    r[k] = nv
                    changed["service_metrics"] += 1
        if changed["service_metrics"]:
            doc["version_key_policy"] = "存储层已归一（norm_version），*_raw 保留原始写法"
            if not dry_run:
                write_json(p, doc)

    # ---- version_chain ----
    p = os.path.join(svc_dir, "version_chain.json")
    doc = load_json(p)
    if doc:
        for v in doc.get("versions", []):
            raw = (v or {}).get("version")
            nv = norm_version(raw)
            if nv and nv != raw:
                v.setdefault("_source_version_raw", raw)
                v["version"] = nv
                changed["version_chain"] += 1
            praw = (v or {}).get("parent")
            npv = norm_version(praw)
            if npv and npv != praw:
                v.setdefault("parent_raw", praw)
                v["parent"] = npv
                changed["version_chain"] += 1
        if changed["version_chain"]:
            doc["version_key_policy"] = "存储层已归一（norm_version）"
            if not dry_run:
                write_json(p, doc)

    # ---- cross_reference ----
    p = os.path.join(svc_dir, "cross_reference.json")
    doc = load_json(p)
    if doc:
        for m in doc.get("mappings", []):
            vt = m.get("version_to")
            nvt = norm_version(vt)
            if nvt and nvt != vt:
                m["version_to"] = nvt
                changed["cross_reference"] += 1
        if changed["cross_reference"]:
            if not dry_run:
                write_json(p, doc)

    # ---- version_bugs ----
    p = os.path.join(svc_dir, "version_bugs.json")
    doc = load_json(p)
    if doc:
        for b in doc.get("bugs", []):
            for k in ("found_in_version", "fixed_in_version"):
                v = b.get(k)
                nv = norm_version(v)
                if nv and nv != v:
                    b.setdefault(k + "_raw", v)
                    b[k] = nv
                    changed["version_bugs"] += 1
        if changed["version_bugs"]:
            doc["version_key_policy"] = "存储层已归一（norm_version），*_raw 保留 TAPD 原值"
            if not dry_run:
                write_json(p, doc)

    return {"service": service, "changed": changed,
            "total": sum(changed.values())}


def sync_service(service, analytics_root, check_only=False, report_root=None, backfill=False):
    """单服务：存储层归一 → 自检 (+ 可选回填) → 重建 → 重算分。"""
    result = {"service": service, "check": check_file_history(service, analytics_root)}
    if not check_only:
        # 顺序很重要：先归一（消除写法分裂），再回填/重建（按规范键归属区间）
        result["normalize"] = normalize_version_fields(service, analytics_root)
    if backfill and report_root and not check_only:
        result["backfill"] = backfill_files_from_reports(service, analytics_root, report_root)
    if not check_only:
        _doc, rep = rebuild_file_history(service, analytics_root)
        result["rebuild"] = rep
        result["chain"] = sync_version_chain(service, analytics_root)
        result["rescore"] = rescore_records(service, analytics_root)
        result["check_after"] = check_file_history(service, analytics_root)
    return result


# ----------------------------------------------------------------------------
# 统一 risk_score 口径（P1-6）
# ----------------------------------------------------------------------------
def rescore_records(service, analytics_root):
    """用脚本确定性重算并写回 service_metrics 的 risk_score。

    唯一口径（2026-09-18 定，替代原先「LLM 按文档公式手填」）：

      metrics.risk_score            ← **静态 5 维确定性分**（0-100）
                                      = scoring.canonical_risk_score(rec, historical=None)
                                      选它做趋势口径的原因：不依赖"历史度量是否可得"，
                                      因此跨版本 / 跨时间 / 跨模式**永远可比**，
                                      从根上消除「W5↔W10 权重迁移造成的伪波动」
                                      （实测同一 stats 静态 87.0 vs 增强 77.4）。
      metrics.risk_score_mode       ← 恒为 "static"（标明 risk_score 的口径）
      metrics.risk_score_enhanced   ← 增强 10 维分（仅在有历史度量时写入）
                                      用于"当前这次变更"的即时判断，**不参与趋势连线**。
      metrics.scoring_mode          ← 本次**报告展示**用的模式：static | enhanced
      metrics.risk_score_source     ← 血缘：脚本名 + 公式，杜绝再次出现"手填"
      metrics.risk_score_legacy     ← 旧公式值留档（不删除，便于审计）

    三者的关系一句话：`risk_score`（趋势，永远 static）≠ `risk_score_enhanced`（单次报告，
    有历史时用）≠ `risk_score_legacy`（旧公式，仅审计）。

    幂等：对同一数据重复运行结果恒定。
    """
    svc_dir = os.path.join(analytics_root, service)
    mp = os.path.join(svc_dir, "service_metrics.json")
    metrics = load_json(mp)
    if not metrics:
        return {"service": service, "rescored": 0, "note": "service_metrics.json 不存在"}

    try:
        import scoring
    except ImportError:
        return {"service": service, "rescored": 0, "note": "scoring.py 不可用"}

    hist = None
    try:
        import quant_jit_risk as qjr
        hist = qjr.auto_historical(service, os.path.dirname(os.path.dirname(analytics_root)))
    except Exception:
        hist = None

    rescored, detail = 0, []
    for rec in metrics.get("records", []):
        m = rec.setdefault("metrics", {})

        # ---- 旧值留档：只在「该值还不是脚本产出」且「尚未留档过」时抓一次 ----
        # 幂等关键（两处都必要）：
        #   ① 第二次运行时 m["risk_score"] 已是脚本产出 → 不能再当成 legacy
        #      （曾出现 legacy == risk_score 的自欺结果）
        #   ② 已存在 risk_score_legacy 时绝不覆盖 → 允许外部/备份恢复的原始值被尊重
        if ("risk_score_legacy" not in m
                and not m.get("risk_score_source")
                and m.get("risk_score") is not None):
            m["risk_score_legacy"] = m["risk_score"]
            m["risk_score_legacy_formula"] = scoring.LEGACY_FORMULA
            m["risk_score_legacy_note"] = ("LLM 按旧文档公式手填的原值；"
                                           "与量化分无关联，已弃用，仅留审计")

        static = scoring.canonical_risk_score(rec, historical=None, service=service)
        m["risk_score"] = static["risk_score"]
        m["risk_score_mode"] = "static"
        m["risk_score_source"] = "script:scoring.canonical_risk_score(静态5维)"
        m["rating_rules_version"] = static["rating_rules_version"]

        if hist:
            enh = scoring.canonical_risk_score(rec, historical=hist, service=service)
            m["risk_score_enhanced"] = enh["risk_score"]
            m["risk_score_enhanced_mode"] = enh["scoring_mode"]
            m["scoring_mode"] = enh["scoring_mode"]      # 报告展示模式
        else:
            m["risk_score_enhanced"] = None
            m["scoring_mode"] = "static"

        # 评级也一并确定性化（替代 LLM 现场判断）
        rating = scoring.rate_change(rec)
        rec["rating"] = rating
        rescored += 1
        detail.append({"range": _range_key(rec), "risk_score": m["risk_score"],
                       "display_mode": m.get("scoring_mode"),
                       "enhanced": m.get("risk_score_enhanced"),
                       "legacy": m.get("risk_score_legacy"),
                       "level": rating["code"]})

    metrics["rescored_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metrics["risk_score_policy"] = (
        "risk_score = 静态5维确定性分（趋势唯一口径，跨模式可比）；"
        "risk_score_enhanced = 增强10维分（不参与趋势连线）；"
        "risk_score_legacy = 旧公式值（仅审计）")
    write_json(mp, metrics)
    return {"service": service, "rescored": rescored, "detail": detail,
            "has_historical": bool(hist)}


def main():
    ap = argparse.ArgumentParser(description="diff-analytics 数据沉淀确定性重建 + 自检")
    ap.add_argument("--service", help="服务名")
    ap.add_argument("--all", action="store_true", help="处理 diff-analytics 下全部服务")
    ap.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--report-root", help="覆盖 report/code-diff 根目录（回填用）")
    ap.add_argument("--backfill", action="store_true",
                    help="先从历史 HTML 报告回填 `files` 清单（仅回填能完整还原的区间）")
    ap.add_argument("--check", action="store_true", help="只自检，不做任何改动")
    ap.add_argument("--dry-run", action="store_true", help="演练：不写盘")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")
    report_root = args.report_root or os.path.join(args.workspace, "report", "code-diff")
    if not os.path.isdir(analytics_root):
        print(f"[ERROR] diff-analytics 目录不存在: {analytics_root}")
        sys.exit(1)

    services = []
    if args.all:
        # 跳过 `_` 开头目录：_trash（本脚本移入的残留）、_bak_*、_archive 等都不是服务。
        # 不跳过的后果：_trash 被当成服务扫描，输出噪音，且可能被误建数据文件。
        services = sorted(d for d in os.listdir(analytics_root)
                          if os.path.isdir(os.path.join(analytics_root, d))
                          and not d.startswith("_"))
    elif args.service:
        services = [args.service]
    else:
        print("[ERROR] 需要 --service 或 --all")
        sys.exit(1)

    results = []
    for svc in services:
        if args.dry_run:
            r = {"service": svc, "check": check_file_history(svc, analytics_root)}
            if args.backfill:
                # 演练模式：复制记录后试跑，不落盘
                r["backfill_preview"] = _backfill_preview(svc, analytics_root, report_root)
            _doc, rep = rebuild_file_history(svc, analytics_root, dry_run=True)
            r["rebuild"] = rep
            results.append(r)
        else:
            results.append(sync_service(svc, analytics_root, check_only=args.check,
                                        report_root=report_root, backfill=args.backfill))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("数据沉淀同步报告  (%s%s)" % ("仅自检" if args.check else "重建 + 自检",
                                       " + 报告回填" if args.backfill and not args.check else ""))
        print("=" * 70)
        total_issues = 0
        for r in results:
            svc = r["service"]
            c = r.get("check_after") or r["check"]
            print(f"\n[{svc}]  file_history 条目 {c['actual']} 条")

            bf = r.get("backfill") or r.get("backfill_preview")
            if bf:
                for b in bf.get("backfilled", []):
                    print(f"  ✅ 回填成功 {b['range']}：{b['files']} 个文件（来源 {b['report']}）")
                for u in bf.get("unrecoverable", []):
                    print(f"  ⛔ 不可还原 {u['range']}（声明 {u.get('declared')} 个文件）：{u['reason']}")

            if "rebuild" in r:
                nb = r.get("normalize") or {}
                if nb.get("total"):
                    print(f"  存储层版本键归一 {nb['total']} 处：{nb['changed']}")
                rb = r["rebuild"]
                print(f"  重建区间 {len(rb['rebuilt_ranges'])} 个 / 写入条目 {rb['rebuilt_entries']} 条"
                      f" / 保留既有 {rb['preserved_entries']} 条")
                if rb["dropped_junk"]:
                    print(f"  硬排除输入产物/临时文件 {len(rb['dropped_junk'])} 条："
                          f"{', '.join(rb['dropped_junk'][:4])}")
                if rb.get("purged_junk"):
                    print(f"  清除历史脏项 {len(rb['purged_junk'])} 条（输入产物/临时文件，"
                          f"与区间无关）: {', '.join(rb['purged_junk'][:4])}")
                if rb["removed_stale"]:
                    print(f"  清理失效条目 {len(rb['removed_stale'])} 条")
                for mm in rb["mismatch"]:
                    print(f"  ⚠️ 清单不完整 {mm['range']}: files={mm['files_list']} "
                          f"vs files_changed={mm['metrics_files_changed']}")
                if r.get("chain") and r["chain"]["deduped"]:
                    ch = r["chain"]
                    print(f"  version_chain 去重 {ch['deduped']} 条（{ch['before']}→{ch['after']}）")
            if r.get("rescore"):
                rs = r["rescore"]
                if rs.get("detail"):
                    print(f"  risk_score 重算 {rs['rescored']} 条"
                          f"（{'有' if rs['has_historical'] else '无'}历史度量）：")
                    print(f"      {'区间':<22}{'趋势分(static)':>14}{'报告分(enhanced)':>18}{'旧公式':>9}")
                    for d in rs["detail"]:
                        enh = ("%.1f" % d["enhanced"]) if d.get("enhanced") is not None else "—"
                        lg = ("%s" % d["legacy"]) if d.get("legacy") is not None else "—"
                        print(f"      {d['range']:<22}{d['risk_score']:>14.1f}{enh:>18}{lg:>9}")
                else:
                    print(f"  risk_score 重算：{rs.get('note', '无记录')}")
            if c["issues"]:
                total_issues += len(c["issues"])
                for it in c["issues"]:
                    print(f"  ⚠️ {it}")
            else:
                print("  ✅ 完整性自检通过")
        print("\n" + "=" * 70)
        print(f"合计问题数：{total_issues}")
        if not args.check:
            print("提示：重建不会破坏缺 `files` 清单的历史区间（原条目保留）")
            print("      对不可还原的历史区间，只能靠后续分析按规范落盘补齐")
    return 0


def _backfill_preview(service, analytics_root, report_root):
    """演练：不写盘，只报告哪些区间能回填 / 哪些不可还原。"""
    svc_dir = os.path.join(analytics_root, service)
    metrics = load_json(os.path.join(svc_dir, "service_metrics.json")) or {"records": []}
    backfilled, unrecoverable = [], []
    for rec in metrics.get("records", []):
        if rec.get("files"):
            continue
        declared = (rec.get("metrics") or {}).get("files_changed")
        rk = _range_key(rec)
        rp = find_report_for_range(service, report_root, rec)
        if not rp:
            unrecoverable.append({"range": rk, "declared": declared, "reason": "未找到对应报告"})
            continue
        ex = extract_report_file_list(rp)
        kept, _d = filter_change_files(ex["files"])
        if ex["lossy"]:
            unrecoverable.append({"range": rk, "declared": declared,
                                  "reason": f"报告为聚合摘要，不可还原（{ex['lossy_reason']}）"})
        elif declared and len(kept) != int(declared):
            unrecoverable.append({"range": rk, "declared": declared, "extracted": len(kept),
                                  "reason": f"报告仅含 {len(kept)} 个，少于声明的 {declared}"})
        else:
            backfilled.append({"range": rk, "files": len(kept), "report": os.path.basename(rp)})
    return {"service": service, "backfilled": backfilled, "unrecoverable": unrecoverable}


if __name__ == "__main__":
    sys.exit(cdx_errors.guard(main))
