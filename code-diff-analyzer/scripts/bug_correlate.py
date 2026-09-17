# -*- coding: utf-8 -*-
"""
bug_correlate.py  —  Code Diff Analyzer · Flow A + Flow B 固化脚本

功能：
  1. 读取固定格式的 TAPD Bug 导出 Excel（sheet 名 `bug`，17 列）
  2. 按权威字段规范化（编号去 .0、状态/严重程度映射）
  3. 全量覆写对应服务的 version_bugs.json（以 xlsx 权威状态为准，杜绝"凭推断标未解决"）
  4. 按「版本系列（前两段，如 5.3）」隔离：仅保留本次分析目标系列的 Bug，
     其余自动归档到 _archive/version_bugs_{系列}.json，避免跨版本历史噪音堆积
  5. 运行映射引擎，全量重建 cross_reference.json
  6. 回填 service_metrics.json 对应版本记录的 bug_links（综合报告摘要卡「关联 Bug」取该字段）

设计原则（来自 81013 误标教训 + 2026-09-10 版本隔离反馈）：
  - xlsx 的 `状态` 列是唯一权威来源；已关闭/已解决/关闭 => closed，其余 => open
  - 每次运行都从 xlsx 重新生成目标系列的全部 bug 记录，不 append、不保留"记忆中的旧状态"
  - 版本数据按系列隔离，分析 5.3 时不混入 5.2 等历史（Bug 应按版本走，而非全量平铺）
  - 列名采用"精确匹配 + 关键词兜底"双策略，但本脚本首要服务已固化的 17 列格式

用法：
  python bug_correlate.py --xlsx "路径/5.3.0.0bug列表.xlsx" --service portal-backend --version 5.3.0.2
  python bug_correlate.py --xlsx "路径/5.3.0.0bug列表.xlsx"            # 自动探测服务 + 版本系列
依赖：openpyxl（仅读 xlsx 时需要）
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # noqa: E402  统一错误提示层（路径/格式错误友好化）


# ----------------------------------------------------------------------------
# 列名映射：精确列名（已固化格式） + 关键词兜底
# ----------------------------------------------------------------------------
COLUMN_MAP = {
    "bug_id":            ["编号", "Bug ID", "缺陷ID", "ID"],
    "title":             ["标题", "缺陷标题", "描述", "摘要"],
    "creator":           ["创建人"],
    "found_date":        ["创建日期", "发现日期"],
    "resolver":          ["解决者"],
    "fixed_date":        ["解决日期"],
    "closed_date":       ["关闭日期"],
    "status":            ["状态", "缺陷状态"],
    "found_in_version":  ["产生版本", "发现版本", "影响版本", "版本"],
    "fixed_in_version":  ["解决版本", "修复版本"],
    "bug_type":          ["bug类型", "类型"],
    "severity":          ["严重程度", "严重级别", "优先级", "等级", "Severity"],
    "activation":        ["激活次数"],
    "disposition":       ["处置方式"],
    "plan":              ["方案"],
    "detail":            ["详细处理方式"],
    "module":            ["模块", "所属模块", "功能模块"],
}


def build_header_index(headers):
    """根据表头行构建 标准字段 -> 列下标 的映射（精确优先，关键词兜底）。"""
    idx = {}
    norm_headers = [(str(h).strip() if h is not None else "") for h in headers]
    for field, variants in COLUMN_MAP.items():
        # 1) 精确匹配
        hit = None
        for v in variants:
            if v in norm_headers:
                hit = norm_headers.index(v)
                break
        # 2) 关键词兜底（包含即可，忽略大小写/空格）
        if hit is None:
            for vi, hraw in enumerate(norm_headers):
                if hraw:
                    low = hraw.replace(" ", "").lower()
                    if any(v.replace(" ", "").lower() in low for v in variants):
                        hit = vi
                        break
        if hit is not None:
            idx[field] = hit
    return idx


# ----------------------------------------------------------------------------
# 规范化辅助
# ----------------------------------------------------------------------------
def norm_str(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "—", "/", "None", "nan"):
        return None
    return s


def to_id(v):
    if v is None:
        return None
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def to_iso(v):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s or s in ("-", "—", "/", "None", "nan"):
        return None
    # 截断时间部分只留日期（如 "2026-07-21 14:32:44"）
    return s.split(" ")[0]


STATUS_CLOSED = {"已关闭", "关闭"}
STATUS_RESOLVED = {"已解决"}
SEV_MAP = {
    "严重": "critical", "高": "high", "一般": "medium",
    "中": "medium", "轻微": "low", "低": "low", "建议": "low",
}


def map_status(raw):
    s = norm_str(raw)
    if s and s in STATUS_CLOSED:
        return "closed"
    if s and s in STATUS_RESOLVED:
        return "resolved"
    return "open"


def map_severity(raw):
    s = norm_str(raw)
    return SEV_MAP.get(s, "medium") if s else "medium"


def version_key(v):
    """把版本号转成可排序的元组。支持 5.2.0.9 / v1.2.34 / business-5.2.0.8 等。"""
    if not v:
        return (0,)
    s = str(v).lower()
    parts = []
    for tok in "".join(c if c.isdigit() or c == "." else " " for c in s).split():
        for n in tok.split("."):
            if n.isdigit():
                parts.append(int(n))
    return tuple(parts) if parts else (0,)


# ----------------------------------------------------------------------------
# 读取 + 规范化
# ----------------------------------------------------------------------------
def parse_xlsx(path):
    wb = cdx_errors.open_xlsx(path, "TAPD Bug Excel")
    if "bug" in wb.sheetnames:
        ws = wb["bug"]
    else:
        ws = wb.worksheets[0]
        cdx_errors.warn("Excel 未找到名为 'bug' 的工作表，改用第一个工作表 '%s'（可选工作表: %s）"
                        % (ws.title, ", ".join(wb.sheetnames)))
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        cdx_errors.die("Excel 首个工作表为空: %s" % path,
                       "工作表 '%s' 无任何行。" % ws.title,
                       hint="确认导出的是含表头 + 数据行的 TAPD Bug 列表。", code=4)
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    hidx = build_header_index(rows[0])
    # 必需列校验：缺『编号』列必然解析不出记录，提前报明确原因（而非返回空列表）
    cdx_errors.check_headers(rows[0], {"bug_id": COLUMN_MAP["bug_id"]}, "TAPD Bug Excel")
    bugs = []
    for r in rows[1:]:
        bid = to_id(r[hidx["bug_id"]]) if "bug_id" in hidx else None
        if not bid:
            continue
        raw_sev = r[hidx["severity"]] if "severity" in hidx else None
        bugs.append({
            "bug_id": bid,
            "title": norm_str(r[hidx["title"]]) if "title" in hidx else None,
            "severity": map_severity(raw_sev),
            "severity_raw": norm_str(raw_sev),
            "status": map_status(r[hidx["status"]]) if "status" in hidx else "open",
            "module": norm_str(r[hidx["module"]]) if "module" in hidx else None,
            "bug_type": norm_str(r[hidx["bug_type"]]) if "bug_type" in hidx else None,
            "found_in_version": norm_str(r[hidx["found_in_version"]]) if "found_in_version" in hidx else None,
            "fixed_in_version": norm_str(r[hidx["fixed_in_version"]]) if "fixed_in_version" in hidx else None,
            "creator": norm_str(r[hidx["creator"]]) if "creator" in hidx else None,
            "resolver": norm_str(r[hidx["resolver"]]) if "resolver" in hidx else None,
            "found_date": to_iso(r[hidx["found_date"]]) if "found_date" in hidx else None,
            "fixed_date": to_iso(r[hidx["fixed_date"]]) if "fixed_date" in hidx else None,
            "closed_date": to_iso(r[hidx["closed_date"]]) if "closed_date" in hidx else None,
            "activation": to_id(r[hidx["activation"]]) if "activation" in hidx else None,
            "disposition": norm_str(r[hidx["disposition"]]) if "disposition" in hidx else None,
            "plan": norm_str(r[hidx["plan"]]) if "plan" in hidx else None,
            "detail": norm_str(r[hidx["detail"]]) if "detail" in hidx else None,
            "related_files": [],
            "related_commits": [],
            "tags": [],
        })
    return headers, bugs


# ----------------------------------------------------------------------------
# 自动探测服务
# ----------------------------------------------------------------------------
def detect_service(analytics_root, bug_versions):
    """扫描所有服务的 version_chain.json，找出包含 bug 版本最多的服务。"""
    best, best_count = None, -1
    if not os.path.isdir(analytics_root):
        return None
    for svc in os.listdir(analytics_root):
        chain_path = os.path.join(analytics_root, svc, "version_chain.json")
        if not os.path.isfile(chain_path):
            continue
        chain = cdx_errors.try_json(chain_path, "version_chain.json")
        if not isinstance(chain, dict):
            continue
        known = {v.get("version") for v in chain.get("versions", []) if isinstance(v, dict)}
        cnt = sum(1 for bv in bug_versions if bv in known)
        if cnt > best_count:
            best, best_count = svc, cnt
    return best if best_count > 0 else None


# ----------------------------------------------------------------------------
# 映射引擎（Flow B）— 全量重建 cross_reference.json
# ----------------------------------------------------------------------------
def run_mapping_engine(service, analytics_root, bugs):
    svc_dir = os.path.join(analytics_root, service)
    chain_path = os.path.join(svc_dir, "version_chain.json")
    metrics_path = os.path.join(svc_dir, "service_metrics.json")

    versions_in_chain = []
    parent_map = {}
    if os.path.isfile(chain_path):
        chain = cdx_errors.try_json(chain_path, "version_chain.json")
        if isinstance(chain, dict):
            for v in chain.get("versions", []):
                if not isinstance(v, dict):
                    continue
                ver = v.get("version")
                if ver:
                    versions_in_chain.append(ver)
                    if v.get("parent"):
                        parent_map[ver] = v["parent"]

    metrics_map = {}
    if os.path.isfile(metrics_path):
        m = cdx_errors.try_json(metrics_path, "service_metrics.json")
        if isinstance(m, dict):
            for rec in m.get("records", []):
                if isinstance(rec, dict) and rec.get("version_to"):
                    metrics_map[rec["version_to"]] = rec

    # 版本全集 = 链路版本 ∪ bug 涉及版本
    all_versions = set(versions_in_chain)
    for b in bugs:
        if b.get("found_in_version"):
            all_versions.add(b["found_in_version"])
        if b.get("fixed_in_version"):
            all_versions.add(b["fixed_in_version"])
    ordered = sorted(all_versions, key=version_key)

    # 补全 parent：链路没有的版本，取排序中前一个版本
    for i, v in enumerate(ordered):
        if v not in parent_map and i > 0:
            parent_map[v] = ordered[i - 1]

    DETECTION_KEYS = ["data_format_change", "version_rollback", "sensitive_info",
                      "test_sync_needed", "circular_dependency"]

    mappings = []
    for i, v in enumerate(ordered):
        if i == 0:
            continue  # 首个版本无父版本，跳过
        parent = parent_map.get(v, ordered[i - 1])
        found = [b["bug_id"] for b in bugs if b.get("found_in_version") == v]
        fixed = [b["bug_id"] for b in bugs if b.get("fixed_in_version") == v]
        rec = metrics_map.get(v)
        files_changed = rec.get("metrics", {}).get("files_changed") if rec else None
        ratio = round(len(found) / files_changed, 4) if files_changed else None
        det = rec.get("detections", {}) if rec else {}
        has_bug = bool(found or fixed)
        detection_precision = {}
        for k in DETECTION_KEYS:
            hit = bool(det.get(k))
            detection_precision[k] = {
                "hit_with_bug": 1 if (hit and has_bug) else 0,
                "hit_total": 1 if hit else 0,
            }
        mappings.append({
            "version_range": f"{parent}→{v}",
            "bugs_found_in_version": found,
            "bugs_fixed_in_version": fixed,
            "change_to_bug_ratio": ratio,
            "high_risk_changes_with_bugs": [],
            "commits_with_bugs": [],
            "detection_precision": detection_precision,
        })

    out = {
        "service": service,
        "schema_version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mappings": mappings,
    }
    with open(os.path.join(svc_dir, "cross_reference.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return len(mappings)


# ----------------------------------------------------------------------------
# 版本系列隔离：Bug 数据按「版本系列（前两段，如 5.3）」归档
# ----------------------------------------------------------------------------
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def version_series(version):
    """提取版本系列（前两段）。
    business-5.3.0.2 / v5.3.0.3 / 5.3.0.0 / release-5.3.0.2-hotfix -> '5.3'；空或非法 -> None
    用正则取首个「数字.数字」片段，兼容前缀（business-/v/release-）与后缀（-hotfix）。
    """
    if not version:
        return None
    m = _VER_RE.search(str(version).strip().lower())
    return f"{m.group(1)}.{m.group(2)}" if m else None


def detect_series(bugs, analytics_root, service):
    """推断本次分析的目标版本系列。
    优先级：① xlsx 中出现频次最高的系列；② 服务 version_chain.json 最新版本系列。
    """
    counter = {}
    for b in bugs:
        for key in ("found_in_version", "fixed_in_version"):
            s = version_series(b.get(key))
            if s:
                counter[s] = counter.get(s, 0) + 1
    if counter:
        return max(counter.items(), key=lambda kv: kv[1])[0]
    # 回退：从版本链取最新版本
    try:
        chain = json.load(open(os.path.join(analytics_root, service, "version_chain.json"),
                               encoding="utf-8"))
        vers = [v.get("version") for v in chain.get("versions", []) if v.get("version")]
        for v in reversed(vers):
            s = version_series(v)
            if s:
                return s
    except Exception:
        pass
    return None


def split_by_series(bugs, target_series):
    """按版本系列分流。
    保留条件：found_in_version 或 fixed_in_version 属于目标系列
    （后者用于保留「历史 Bug 但在本轮版本修复」的场景，如产生版本 5.0.0.0、解决版本 5.3.0.0）。
    返回 (保留列表, {系列: 归档列表})
    """
    keep, archive = [], {}
    for b in bugs:
        found_s = version_series(b.get("found_in_version"))
        fixed_s = version_series(b.get("fixed_in_version"))
        if target_series and (found_s == target_series or fixed_s == target_series):
            keep.append(b)
        else:
            s = found_s or fixed_s or "unknown"
            archive.setdefault(s, []).append(b)
    return keep, archive


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Code Diff Analyzer · Bug 关联固化脚本")
    ap.add_argument("--xlsx", required=True, help="TAPD Bug 导出 Excel 路径")
    ap.add_argument("--service", help="服务名（缺省时自动探测）")
    ap.add_argument("--workspace", default=r"d:/workbuddy/测试日常", help="工作区根目录")
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--version", help="本次分析的目标版本（如 5.3.0.2 / v5.3.0.3）；"
                                      "缺省时自动探测。用于按版本系列隔离 Bug 数据")
    ap.add_argument("--keep-all", action="store_true",
                    help="保留全部版本系列的 Bug 不做归档（旧行为，不推荐）")
    args = ap.parse_args()

    analytics_root = args.analytics_root or os.path.join(args.workspace, ".workbuddy", "diff-analytics")
    cdx_errors.require_file(args.xlsx, "TAPD Bug Excel（--xlsx）",
                            hint="传入 TAPD 导出的 .xlsx 绝对路径；路径含空格/中文请加英文引号。")

    headers, bugs = parse_xlsx(args.xlsx)
    if not bugs:
        cdx_errors.die("未从 Excel 解析到任何 Bug 记录",
                       "已识别表头: %s" % (", ".join(h for h in headers if h)[:200] or "（空）"),
                       hint="确认工作表含『编号』列、且数据行非空（空行会被跳过）。", code=4)

    # 服务判定
    service = args.service
    if not service:
        bug_versions = [b["found_in_version"] for b in bugs if b["found_in_version"]] + \
                       [b["fixed_in_version"] for b in bugs if b["fixed_in_version"]]
        service = detect_service(analytics_root, bug_versions)
        if not service:
            cdx_errors.die("无法自动探测服务",
                           "已扫描 %s 下各服务的 version_chain.json，均未匹配到 Bug 版本。" % analytics_root,
                           hint="用 --service <服务名> 显式指定。", code=4)
        print(f"[INFO] 自动探测服务: {service}")

    svc_dir = os.path.join(analytics_root, service)
    os.makedirs(svc_dir, exist_ok=True)

    # ---- 按版本系列隔离（默认启用）----
    target_series = None
    archived_total = 0
    archived_detail = {}
    if not args.keep_all:
        target_series = version_series(args.version) if args.version else detect_series(bugs, analytics_root, service)
        if target_series is None:
            print("[WARN] 未能确定目标版本系列，回退为保留全部（可显式传 --version）")
        else:
            keep, archive = split_by_series(bugs, target_series)
            if archive:
                arc_dir = os.path.join(svc_dir, "_archive")
                os.makedirs(arc_dir, exist_ok=True)
                for series, items in archive.items():
                    path = os.path.join(arc_dir, f"version_bugs_{series}.json")
                    # 同系列已有归档则合并去重（按 bug_id）
                    existing = []
                    if os.path.isfile(path):
                        doc_existing = cdx_errors.try_json(path, "version_bugs_%s.json" % series)
                        existing = doc_existing.get("bugs", []) if isinstance(doc_existing, dict) else []
                    merged = {b["bug_id"]: b for b in existing}
                    for b in items:
                        merged[b["bug_id"]] = b
                    doc = {
                        "service": service,
                        "version_series": series,
                        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "archived_reason": f"非本次分析版本系列（目标系列 {target_series}），已从 version_bugs.json 移出归档",
                        "bugs": list(merged.values()),
                    }
                    with open(path, "w", encoding="utf-8") as af:
                        json.dump(doc, af, ensure_ascii=False, indent=2)
                    archived_detail[series] = len(items)
                    archived_total += len(items)
            bugs = keep
            if not bugs:
                cdx_errors.die("按版本系列 %s 过滤后无任何 Bug" % target_series,
                               "Excel 中的 Bug 版本系列均不属于 %s。" % target_series,
                               hint="确认 --version 是否正确，或用 --keep-all 保留全部系列。", code=4)

    # 按版本系列覆写 version_bugs.json（xlsx 为权威来源，仅覆盖目标系列）
    version_bugs = {
        "service": service,
        "schema_version": "1.1",
        "version_series": target_series or "all",
        "source_xlsx": os.path.basename(args.xlsx),
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bugs": bugs,
    }
    with open(os.path.join(svc_dir, "version_bugs.json"), "w", encoding="utf-8") as f:
        json.dump(version_bugs, f, ensure_ascii=False, indent=2)

    # 映射引擎
    n_map = run_mapping_engine(service, analytics_root, bugs)

    # 回填 service_metrics.json 对应版本记录的 bug_links
    # （综合报告摘要卡的「关联 Bug」取该字段，不回填会一直显示 0）
    n_links = 0
    try:
        mp = os.path.join(svc_dir, "service_metrics.json")
        if os.path.isfile(mp):
            metrics = cdx_errors.try_json(mp, "service_metrics.json")
            if not isinstance(metrics, dict):
                raise ValueError("service_metrics.json 结构不是对象（无法回填 bug_links）")
            ids = [b["bug_id"] for b in bugs if b.get("bug_id")]
            target_rec = None
            for rec in reversed(metrics.get("records", [])):
                vs = version_series(rec.get("version_from")) or version_series(rec.get("version_to"))
                if target_series is None or vs == target_series:
                    target_rec = rec
                    break
            if target_rec is not None and ids:
                target_rec["bug_links"] = ids
                n_links = len(ids)
                with open(mp, "w", encoding="utf-8") as mf:
                    json.dump(metrics, mf, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 回填 bug_links 失败: {e}")

    # 摘要
    closed = sum(1 for b in bugs if b["status"] == "closed")
    resolved = sum(1 for b in bugs if b["status"] == "resolved")
    sev_counts = {}
    for b in bugs:
        sev_counts[b["severity"]] = sev_counts.get(b["severity"], 0) + 1
    print("=" * 56)
    print(f"服务            : {service}")
    print(f"版本系列        : {target_series or 'all（--keep-all）'}")
    print(f"Bug 总数        : {len(bugs)}")
    print(f"已关闭/已解决    : 已关闭 {closed} / 已解决 {resolved} / 其余(open) {len(bugs)-closed-resolved}")
    print(f"严重度分布      : {sev_counts}")
    print(f"version_bugs    : 已按系列覆写 ({len(bugs)} 条)")
    if archived_total:
        detail = "  ".join(f"{k}:{v}" for k, v in sorted(archived_detail.items()))
        print(f"历史归档        : {archived_total} 条 -> _archive/  ({detail})")
    print(f"cross_reference : 已全量重建 ({n_map} 条映射)")
    if n_links:
        print(f"bug_links 回填   : service_metrics 最新版本记录 {n_links} 条")
    print(f"落盘目录        : {svc_dir}")
    print("=" * 56)


if __name__ == "__main__":
    cdx_errors.guard(main)
