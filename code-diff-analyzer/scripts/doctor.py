#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py — diff-analytics 一键体检 / 修复

把 2026-09-18 体检中「全靠人工肉眼比对」的检查项固化成一条命令。

检查项（默认只读，`--fix` 才动手）：

  D1 Schema 合规      三个业务文件 + 两个可选文件的文件头（service / schema_version / 业务键）
  D2 版本键一致性     同一版本在不同文件里是否出现多种写法（P0-1 的根因，必须归零）
  D3 file_history     条目完整性 / `files` 包裹层 / 是否混入输入产物（P0-4）
  D4 cross_reference  是否新鲜（落后于 service_metrics 最新记录即失效）+ mapping 数 == 记录数（P0-2）
  D5 risk_score 血缘  每条记录是否由脚本产出（原实现是 LLM 手填，`grep risk_score scripts/*.py` 零命中）
  D6 孤儿文件         version_bugs.json 不存在却还留着 cross_reference.json
  D7 报告目录卫生     report/code-diff 根目录的临时产物（temp_* / _build_*）
  D8 分数可复现性     落盘 risk_score 是否等于「用当前评分代码重算」的结果
                     （评分规则一改、数据没重算 → D5 全绿但分数已失真，故必须有此项）
  D9 数据目录卫生     服务数据目录里的 `*.json.bak` / `*.tmp` 残留（D7 的镜像）

修复动作（`--fix`）：
  · 重建 file_history（委托 sync_analytics，幂等，不破坏缺 `files` 清单的历史区间）
  · version_chain 规范键归一 + 去重
  · 重算 risk_score 与评级（委托 sync_analytics.rescore_records）
  · cross_reference 失效则重跑映射引擎
  · `--move-temp` 把报告目录临时产物**移动到 _trash/（可逆）**，不直接删除

用法：
    python scripts/doctor.py --all                 # 只读体检
    python scripts/doctor.py --all --fix           # 体检 + 自动修复
    python scripts/doctor.py --service portal-backend --fix --move-temp
    python scripts/doctor.py --all --json
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # noqa: E402
    norm_version, version_key, inconsistent_keys, is_junk_path, normalize_path,
    load_bugs_doc, PROJECT_POOL_DIR,
)
import sync_analytics as sa  # noqa: E402

DEFAULT_WORKSPACE = r"d:/workbuddy/测试日常"

# 文件 -> (业务键, 是否必填)
SCHEMA_FILES = {
    "service_metrics.json": ("records", True),
    "version_chain.json": ("versions", True),
    "file_history.json": ("files", True),
    "version_bugs.json": ("bugs", False),
    "cross_reference.json": ("mappings", False),
}
# 报告目录临时产物（移动到 _trash，不删除）
TEMP_PATTERNS = ("temp_", "_build_")
TEMP_EXTS = (".tmp", ".bak", ".orig", ".old")


def _collect_versions(service, analytics_root):
    """汇总一个服务内所有文件里出现的版本字符串（供 D2 检查）。

    ⚠️ 刻意**排除 `*_raw` 字段**：那些是归一化时有意保留的 TAPD/原始写法，
    用于回溯比对，不算「写法不一致」。若不排除，归一化本身会被误报为问题。
    """
    svc = os.path.join(analytics_root, service)
    vals = []
    sm = sa.load_json(os.path.join(svc, "service_metrics.json")) or {}
    for r in sm.get("records", []):
        vals += [r.get("version_from"), r.get("version_to")]
    vc = sa.load_json(os.path.join(svc, "version_chain.json")) or {}
    for v in vc.get("versions", []):
        vals += [(v or {}).get("version"), (v or {}).get("parent")]
    # Bug 侧含项目级池（2026-09-18 项目池改造）
    vb, _ = load_bugs_doc(analytics_root, service)
    vb = vb or {}
    for b in vb.get("bugs", []):
        vals += [b.get("found_in_version"), b.get("fixed_in_version")]
    cr = sa.load_json(os.path.join(svc, "cross_reference.json")) or {}
    for m in cr.get("mappings", []):
        vals += [m.get("version_to")]
        # version_range 是 "a→b" 组合串，拆开再检
        vr = str(m.get("version_range") or "")
        if "→" in vr:
            vals += vr.split("→")
    return [v for v in vals if v]


def check_d1_schema(service, analytics_root):
    """D1 文件头合规。"""
    svc = os.path.join(analytics_root, service)
    issues, files_checked = [], []
    for fn, (bizkey, required) in SCHEMA_FILES.items():
        p = os.path.join(svc, fn)
        if not os.path.isfile(p):
            if required:
                issues.append(f"D1 {fn} 缺失（必填）")
            continue
        files_checked.append(fn)
        doc = sa.load_json(p)
        if doc is None:
            issues.append(f"D1 {fn} 不是合法 JSON")
            continue
        if not doc.get("service"):
            issues.append(f"D1 {fn} 缺文件头 `service`")
        if not doc.get("schema_version"):
            issues.append(f"D1 {fn} 缺文件头 `schema_version`")
        if bizkey not in doc:
            issues.append(f"D1 {fn} 缺业务键 `{bizkey}`")
        elif not isinstance(doc[bizkey], (list, dict)):
            issues.append(f"D1 {fn} 业务键 `{bizkey}` 类型应为 list/object")
    return {"id": "D1", "name": "Schema 合规", "issues": issues,
            "detail": {"files_checked": files_checked}}


def check_d2_version_keys(service, analytics_root):
    """D2 版本键写法一致性（同一版本多种写法 = 关联断裂的根源）。"""
    vals = _collect_versions(service, analytics_root)
    bad = inconsistent_keys(vals)
    issues = []
    for ck, variants in sorted(bad.items()):
        issues.append(f"D2 版本 {ck} 存在 {len(variants)} 种写法：{variants}")
    return {"id": "D2", "name": "版本键一致性", "issues": issues,
            "detail": {"total_version_tokens": len(vals), "inconsistent": len(bad)}}


def check_d3_file_history(service, analytics_root):
    """D3 file_history 完整性（委托 sync_analytics）。"""
    r = sa.check_file_history(service, analytics_root)
    return {"id": "D3", "name": "file_history 完整性", "issues": list(r["issues"]),
            "detail": {"entries": r["actual"], "junk": r["junk"],
                       "unverifiable_ranges": len(r["unverifiable"])}}


def check_d4_cross_reference(service, analytics_root):
    """D4 cross_reference 新鲜度 + 覆盖率。

    注意：cross_reference 只在「有 Bug 数据」时才该存在 —— 没有 version_bugs.json 的
    服务不该被判定为缺失（那是设计如此，不是缺陷）。
    """
    svc = os.path.join(analytics_root, service)
    issues = []
    sm = sa.load_json(os.path.join(svc, "service_metrics.json")) or {}
    cr = sa.load_json(os.path.join(svc, "cross_reference.json"))
    # Bug 侧支持项目级池回退（2026-09-18 项目池改造）
    vb, _ = load_bugs_doc(analytics_root, service)
    vb = vb or {}
    has_bugs = bool(vb.get("bugs"))
    nrec = len(sm.get("records", []))

    if cr is None:
        if has_bugs:
            issues.append("D4 有 Bug 数据但 cross_reference.json 缺失 → 需重建映射")
        return {"id": "D4", "name": "cross_reference 新鲜度", "issues": issues,
                "detail": {"records": nrec, "mappings": 0, "has_bugs": has_bugs}}

    nmap = len(cr.get("mappings", []))
    if has_bugs and nmap != nrec:
        issues.append(f"D4 mapping 数 {nmap} != service_metrics 记录数 {nrec}"
                      f"（存在未被消费的记录，join 仍未接通）")
    # 新鲜度：cross_reference.generated_at 是否落后于 service_metrics 最新 analysis_date
    dates = [r.get("analysis_date") for r in sm.get("records", []) if r.get("analysis_date")]
    gen = str(cr.get("generated_at") or "")[:10]
    if dates and gen:
        latest = max(dates)
        if gen < latest:
            issues.append(f"D4 cross_reference 生成于 {gen}，落后于最新分析 {latest} → 已过期，需重建")
    # 语义健康度：是否仍有全 null 比值
    nulls = [m.get("version_range") for m in cr.get("mappings", [])
             if m.get("change_to_bug_ratio") is None]
    if nulls:
        issues.append(f"D4 {len(nulls)} 条 mapping 的 change_to_bug_ratio 仍为 null：{nulls[:4]}")
    return {"id": "D4", "name": "cross_reference 新鲜度", "issues": issues,
            "detail": {"records": nrec, "mappings": nmap, "has_bugs": has_bugs,
                       "high_risk_hit_rate": cr.get("high_risk_hit_rate"),
                       "attribution": cr.get("attribution")}}


def check_d5_risk_score(service, analytics_root):
    """D5 risk_score 血缘（必须由脚本产出，杜绝 LLM 手填）。"""
    svc = os.path.join(analytics_root, service)
    sm = sa.load_json(os.path.join(svc, "service_metrics.json")) or {}
    issues, n = [], 0
    for r in sm.get("records", []):
        m = r.get("metrics") or {}
        if m.get("risk_score") is None:
            issues.append(f"D5 记录 {r.get('version_to')} 缺 risk_score")
            continue
        n += 1
        if not m.get("risk_score_source"):
            issues.append(f"D5 记录 {r.get('version_to')} 的 risk_score 无血缘标记"
                          f"（疑似手填，需 rescore）")
        if not m.get("risk_score_mode"):
            issues.append(f"D5 记录 {r.get('version_to')} 缺 risk_score_mode（趋势无法判定口径）")
        if not r.get("rating"):
            issues.append(f"D5 记录 {r.get('version_to')} 无确定性评级 rating")
    return {"id": "D5", "name": "risk_score 血缘", "issues": issues,
            "detail": {"records_with_score": n}}


def check_d8_reproducible(service, analytics_root):
    """D8 分数可复现性（确定性 + 血缘一致）—— 口径漂移的探针。

    为什么必须有这一项：D5 只检查「有没有血缘标记」，标记是上次重算时写的，
    之后**评分代码改了、数据没重算**，D5 依然全绿，但报告里的分数已经和代码不一致。
    2026-09-18 收窄 CORE_PATTERNS（版本号 bump 不再算核心模块）就是这种情况，
    必须能被自动抓出来。

    三条断言：
      1. 落盘 risk_score == 用当前评分代码重算的结果（容差 0.01）
      2. risk_score_mode == "static"（趋势唯一口径，增强分不得占据该字段）
      3. 落盘 rating == rate_change() 重算结果（防止人工改等级）
      4. 旧公式值有留档（risk_score_legacy 存在）
    """
    try:
        import scoring
    except ImportError:
        return {"id": "D8", "name": "分数可复现性", "issues": ["D8 无法导入 scoring 模块"],
                "detail": {}}
    svc = os.path.join(analytics_root, service)
    sm = sa.load_json(os.path.join(svc, "service_metrics.json")) or {}
    issues, checked, stale, mode_bad, rating_bad, no_legacy = [], 0, [], [], [], []
    for r in sm.get("records", []):
        m = r.get("metrics") or {}
        if m.get("risk_score") is None:
            continue
        checked += 1
        tag = f"{r.get('version_from')}→{r.get('version_to')}"
        try:
            out = scoring.canonical_risk_score(dict(r))
        except Exception as e:
            issues.append(f"D8 {tag} 重算失败：{e}")
            continue
        if abs(float(out["risk_score"]) - float(m["risk_score"])) > 0.01:
            stale.append(f"{tag}(落盘 {m['risk_score']} / 重算 {out['risk_score']})")
        if m.get("risk_score_mode") != "static":
            mode_bad.append(f"{tag}({m.get('risk_score_mode')!r})")
        want_rating = scoring.rate_change(dict(r)).get("code")
        got_rating = ((r.get("rating") or {}) if isinstance(r.get("rating"), dict)
                      else {}).get("code") or r.get("rating")
        if got_rating != want_rating:
            rating_bad.append(f"{tag}(落盘 {got_rating!r} / 重算 {want_rating!r})")
        if m.get("risk_score_legacy") is None:
            no_legacy.append(tag)
    if stale:
        issues.append(f"D8 {len(stale)} 条 risk_score 与当前评分代码不一致"
                      f"（代码已变更但数据未重算 → 跑 --fix 或 sync_analytics）：{stale[:4]}")
    if mode_bad:
        issues.append(f"D8 {len(mode_bad)} 条 risk_score_mode 不是 static（趋势口径被污染）：{mode_bad[:4]}")
    if rating_bad:
        issues.append(f"D8 {len(rating_bad)} 条 rating 与 rate_change() 重算不一致：{rating_bad[:4]}")
    if no_legacy:
        issues.append(f"D8 {len(no_legacy)} 条记录缺 risk_score_legacy 留档（旧值被静默覆盖）：{no_legacy[:4]}")
    return {"id": "D8", "name": "分数可复现性", "issues": issues,
            "detail": {"records_with_score": checked, "stale": len(stale)}}


def check_d6_orphans(service, analytics_root):
    """D6 孤儿文件（version_bugs 不存在却留着 cross_reference）。

    2026-09-18 项目级池改造：服务级 version_bugs.json 缺失但项目级池存在时，
    cross_reference.json 不算孤儿（Bug 关联改为引用项目池）。
    """
    svc = os.path.join(analytics_root, service)
    issues = []
    has_bugs = (
        os.path.isfile(os.path.join(svc, "version_bugs.json"))
        or os.path.isfile(os.path.join(analytics_root, PROJECT_POOL_DIR, "version_bugs.json"))
    )
    has_cr = os.path.isfile(os.path.join(svc, "cross_reference.json"))
    if has_cr and not has_bugs:
        issues.append("D6 version_bugs.json（服务级与项目级池）均不存在，但 cross_reference.json 仍在（应同步删除）")
    if has_cr and not os.path.isfile(os.path.join(svc, "service_metrics.json")):
        issues.append("D6 cross_reference.json 存在但 service_metrics.json 缺失")
    return {"id": "D6", "name": "孤儿文件", "issues": issues, "detail": {}}


def scan_temp_files(report_root, service=None):
    """D7 扫描报告目录里的临时产物。

    扫描范围**始终包含 report_root 根目录**（历史脏文件主要堆在那里），
    给了 service 时额外扫该服务子目录。
    """
    roots = [report_root]
    if service:
        roots.append(os.path.join(report_root, service))
    found = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for fn in os.listdir(r):
            p = os.path.join(r, fn)
            if not os.path.isfile(p):
                continue
            if str(fn).startswith(TEMP_PATTERNS) or str(fn).lower().endswith(TEMP_EXTS):
                found.append(p)
    return sorted(set(found))


def check_d7_hygiene(report_root, service=None):
    """D7 报告目录卫生。"""
    temp = scan_temp_files(report_root, service)
    issues = [f"D7 临时产物 {os.path.basename(p)}（{os.path.relpath(p, report_root)}）" for p in temp]
    return {"id": "D7", "name": "报告目录卫生", "issues": issues,
            "detail": {"temp_files": temp}}


def move_temp_files(report_root, paths):
    """把临时产物**移动到 _trash/{date}/**（可逆），不直接删除。"""
    dst_root = os.path.join(report_root, "_trash", datetime.now().strftime("%Y%m%d"))
    moved = []
    for p in paths:
        if not os.path.isfile(p):
            continue
        os.makedirs(dst_root, exist_ok=True)
        rel = os.path.relpath(p, report_root).replace("\\", "_").replace("/", "_")
        dst = os.path.join(dst_root, rel)
        shutil.move(p, dst)
        moved.append({"from": p, "to": dst})
    return moved


def fix_service(service, analytics_root, report_root, move_temp=False):
    """执行可自动化的修复动作（全部幂等）。"""
    actions = []
    # D3/D5：重建 file_history + 归一 version_chain + 重算 risk_score
    r = sa.sync_service(service, analytics_root)
    rb = r.get("rebuild") or {}
    if rb.get("rebuilt_ranges"):
        actions.append(f"重建 file_history：{len(rb['rebuilt_ranges'])} 个区间 / "
                       f"{rb['rebuilt_entries']} 条条目")
    if rb.get("purged_junk"):
        actions.append(f"清除历史脏项 {len(rb['purged_junk'])} 条")
    rs = r.get("rescore") or {}
    if rs.get("rescored"):
        actions.append(f"重算 risk_score + 评级：{rs['rescored']} 条记录")

    # D4：cross_reference 失效则重建（Bug 侧支持项目级池回退）
    d4 = check_d4_cross_reference(service, analytics_root)
    if d4["issues"]:
        try:
            import bug_correlate as bc
            vb, _ = load_bugs_doc(analytics_root, service)
            if vb and vb.get("bugs"):
                st = bc.run_mapping_engine(service, analytics_root, vb["bugs"], verbose=False)
                actions.append(f"重建 cross_reference：{st['mappings']} 条 mapping，"
                               f"high_risk_hit_rate={st['high_risk_hit_rate']}")
        except Exception as e:
            actions.append(f"[WARN] cross_reference 重建失败：{e}")

    # D6：孤儿文件（项目级池存在时 cross_reference 不算孤儿）
    svc = os.path.join(analytics_root, service)
    has_bugs_anywhere = (
        os.path.isfile(os.path.join(svc, "version_bugs.json"))
        or os.path.isfile(os.path.join(analytics_root, PROJECT_POOL_DIR, "version_bugs.json"))
    )
    if not has_bugs_anywhere \
            and os.path.isfile(os.path.join(svc, "cross_reference.json")):
        os.remove(os.path.join(svc, "cross_reference.json"))
        actions.append("删除孤儿 cross_reference.json（服务级与项目级池均无 version_bugs）")

    # D7/D9：临时产物与数据目录残留转移（可逆）
    if move_temp and report_root:
        temp = scan_temp_files(report_root, service)
        moved = move_temp_files(report_root, temp)
        if moved:
            actions.append(f"临时产物移入 _trash/：{len(moved)} 个文件")
        junk = scan_service_junk(analytics_root, service)
        moved2 = move_service_junk(analytics_root, service, junk)
        if moved2:
            actions.append(f"数据目录残留移入 _trash/：{len(moved2)} 个文件")
    return actions


# 数据目录内的备份/临时残留：不是数据本身，但会让人（以及任何按 `*.json` 通配的脚本）
# 误把旧快照当作当前数据。
SERVICE_JUNK_SUFFIXES = (".bak", ".bak2", ".bak3", ".tmp", ".orig", ".old", "~")


def scan_service_junk(analytics_root, service):
    """扫描服务数据目录里的备份/临时残留（只扫一层，不进 _archive 等子目录）。"""
    svc_dir = os.path.join(analytics_root, service)
    if not os.path.isdir(svc_dir):
        return []
    hits = []
    for name in sorted(os.listdir(svc_dir)):
        p = os.path.join(svc_dir, name)
        if not os.path.isfile(p):
            continue
        if name.endswith(SERVICE_JUNK_SUFFIXES) or name.startswith("~$"):
            hits.append(p)
    return hits


def move_service_junk(analytics_root, service, paths):
    """把数据目录残留移入 analytics_root/_trash/<service>/（可逆，不删除）。"""
    if not paths:
        return []
    dst_dir = os.path.join(analytics_root, "_trash", service)
    os.makedirs(dst_dir, exist_ok=True)
    moved = []
    for p in paths:
        base, ext = os.path.splitext(os.path.basename(p))
        dst = os.path.join(dst_dir, base + ext)
        i = 1
        while os.path.exists(dst):
            dst = os.path.join(dst_dir, "%s.%d%s" % (base, i, ext))
            i += 1
        shutil.move(p, dst)
        moved.append({"from": p, "to": dst})
    return moved


def check_d9_data_dir_hygiene(analytics_root, service):
    """D9 数据目录卫生（D7 的镜像：一个管报告目录，一个管数据目录）。

    残留的 `service_metrics.json.bak` 之类不会进 file_history（is_junk_path 已硬排除），
    但躺在数据目录里会误导后续重建与人工排查。默认只报告，`--move-temp` 才移走。
    """
    hits = scan_service_junk(analytics_root, service)
    issues = []
    if hits:
        names = [os.path.basename(h) for h in hits]
        issues.append(f"D9 数据目录残留 {len(hits)} 个备份/临时文件"
                      f"（建议加 --move-temp 移入 _trash/）：{names[:6]}")
    return {"id": "D9", "name": "数据目录卫生", "issues": issues,
            "detail": {"junk_files": len(hits)}}


def run_doctor(services, analytics_root, report_root, fix=False, move_temp=False):
    results = []
    for svc in services:
        checks = [
            check_d1_schema(svc, analytics_root),
            check_d2_version_keys(svc, analytics_root),
            check_d3_file_history(svc, analytics_root),
            check_d4_cross_reference(svc, analytics_root),
            check_d5_risk_score(svc, analytics_root),
            check_d6_orphans(svc, analytics_root),
            check_d7_hygiene(report_root, svc),
            check_d8_reproducible(svc, analytics_root),
            check_d9_data_dir_hygiene(analytics_root, svc),
        ]
        entry = {"service": svc, "checks": checks,
                 "issues_total": sum(len(c["issues"]) for c in checks)}
        if fix:
            entry["actions"] = fix_service(svc, analytics_root, report_root, move_temp)
            entry["checks_after"] = [
                check_d1_schema(svc, analytics_root),
                check_d2_version_keys(svc, analytics_root),
                check_d3_file_history(svc, analytics_root),
                check_d4_cross_reference(svc, analytics_root),
                check_d5_risk_score(svc, analytics_root),
                check_d6_orphans(svc, analytics_root),
                check_d7_hygiene(report_root, svc),
                check_d8_reproducible(svc, analytics_root),
                check_d9_data_dir_hygiene(analytics_root, svc),
            ]
            entry["issues_after"] = sum(len(c["issues"]) for c in entry["checks_after"])
        results.append(entry)
    return results


def main():
    ap = argparse.ArgumentParser(description="diff-analytics 一键体检 / 修复")
    ap.add_argument("--service")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    ap.add_argument("--analytics-root")
    ap.add_argument("--report-root")
    ap.add_argument("--fix", action="store_true", help="执行自动修复（幂等）")
    ap.add_argument("--move-temp", action="store_true",
                    help="把报告目录临时产物移入 _trash/（可逆，不删除）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")
    report_root = args.report_root or os.path.join(args.workspace, "report", "code-diff")
    if not os.path.isdir(analytics_root):
        print(f"[ERROR] diff-analytics 不存在: {analytics_root}")
        sys.exit(1)

    if args.all:
        services = sorted(d for d in os.listdir(analytics_root)
                          if os.path.isdir(os.path.join(analytics_root, d))
                          and not d.startswith("_"))   # 跳过 _bak_* / _archive 等非服务目录
    elif args.service:
        services = [args.service]
    else:
        print("[ERROR] 需要 --service 或 --all")
        sys.exit(1)

    results = run_doctor(services, analytics_root, report_root,
                         fix=args.fix, move_temp=args.move_temp)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    print("=" * 74)
    print("diff-analytics 体检报告%s" % ("（含自动修复）" if args.fix else "（只读）"))
    print("=" * 74)
    grand_before = grand_after = 0
    for r in results:
        print(f"\n■ {r['service']}   问题 {r['issues_total']} 项")
        grand_before += r["issues_total"]
        if r.get("actions"):
            for a in r["actions"]:
                print(f"  [FIX] {a}")
        shown = r.get("checks_after") or r["checks"]
        for c in shown:
            if c["issues"]:
                for it in c["issues"]:
                    print(f"  ⚠️  {it}")
            else:
                print(f"  ✅  {c['id']} {c['name']}")
        if "issues_after" in r:
            grand_after += r["issues_after"]
            print(f"  → 修复后剩余问题 {r['issues_after']} 项")
    print("\n" + "=" * 74)
    if args.fix:
        print(f"修复前合计 {grand_before} 项 → 修复后 {grand_after} 项")
    else:
        print(f"合计问题 {grand_before} 项（加 --fix 自动修复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
