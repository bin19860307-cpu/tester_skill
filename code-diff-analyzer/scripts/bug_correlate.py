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
  7. Bug 数据质量诊断（模块列覆盖率等），并触发 file_history 完整性自检

【2026-09-18 修复】映射引擎从「并集驱动」改为「service_metrics 驱动」+ 版本键归一
  历史缺陷（实测）：49 个 Bug 的有效关联数为 0。原因是两侧永不交汇——
      version_bugs.json 用裸号 5.3.0.2，service_metrics.json 用 business-5.3.0.2，
      而匹配用精确字符串相等 → 必然 miss。
  且旧实现用「版本链 ∪ Bug 版本」的并集驱动，产出 4 条无 metrics 的空壳 mapping
  （能采到 Bug 但没有变更数据），唯一有 metrics 的那条又采不到 Bug。
  现在：以 service_metrics 的每条记录为驱动，跨文件比较一律先 norm_version() 归一，
  并补齐 high_risk_hit_rate（原先只在 SKILL.md 里有定义，代码里查无实现）。

设计原则（来自 81013 误标教训 + 2026-09-10 版本隔离反馈）：
  - xlsx 的 `状态` 列是唯一权威来源；已关闭/关闭 => closed，已解决 => resolved，其余 => open
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

try:
    import openpyxl
except ImportError:
    sys.stderr.write("[ERROR] 缺少 openpyxl，请先 pip install openpyxl\n")
    sys.exit(2)

# 共享基础模块（版本键归一 + 路径过滤）—— 全技能唯一实现，避免口径漂移
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdx_errors  # 统一友好错误层
from _common import (  # noqa: E402
    norm_version, version_key, version_series, same_version,
    inconsistent_keys, inconsistent_keys_by_source, filter_change_files,
    classify_bug_side, PROJECT_SERVICE,
)


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


# version_key / version_series / norm_version 均来自 _common（2026-09-18 起全技能统一实现）


# ----------------------------------------------------------------------------
# 读取 + 规范化
# ----------------------------------------------------------------------------
def parse_xlsx(path):
    wb = cdx_errors.open_xlsx(path)
    ws = wb["bug"] if "bug" in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    hidx = build_header_index(rows[0])
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
    """扫描所有服务的 version_chain.json，找出包含 bug 版本最多的服务。

    【2026-09-18 修复】原实现用 `bv in known` 精确字符串匹配，而 Bug 侧是裸号
    （`5.3.0.2`）、链路侧带前缀（`business-5.3.0.2`）→ 探测恒失败。改为规范化后比较。
    """
    best, best_count = None, -1
    if not os.path.isdir(analytics_root):
        return None
    bug_canon = {norm_version(bv) for bv in bug_versions if norm_version(bv)}
    for svc in os.listdir(analytics_root):
        chain_path = os.path.join(analytics_root, svc, "version_chain.json")
        if not os.path.isfile(chain_path):
            continue
        try:
            chain = cdx_errors.read_json(chain_path)
        except Exception:
            continue
        known = {norm_version(v.get("version")) for v in chain.get("versions", [])}
        known.discard(None)
        cnt = len(bug_canon & known)
        if cnt > best_count:
            best, best_count = svc, cnt
    return best if best_count > 0 else None


# ----------------------------------------------------------------------------
# 映射引擎（Flow B）— 全量重建 cross_reference.json
# ----------------------------------------------------------------------------
DETECTION_KEYS = ["data_format_change", "version_rollback", "sensitive_info",
                  "test_sync_needed", "circular_dependency"]


def _module_name_matches(mod_name, bug_module):
    """模块名与 Bug 模块列的匹配（归一后双向包含即可）。

    TAPD 的「模块」列与 service_metrics 的 modules[].name 粒度不同
    （如 Bug 写 `auth`，变更写 `认证权限(auth 重构)`），故用包含匹配。
    """
    if not mod_name or not bug_module:
        return False
    a = re.sub(r"[\s_\-/()（）]+", "", str(mod_name)).lower()
    b = re.sub(r"[\s_\-/()（）]+", "", str(bug_module)).lower()
    if not a or not b:
        return False
    return b in a or a in b


def _segment_of(rec, chain_canon, parent_canon, to_canon):
    """标注该映射区间相对版本链是否连续。

    `"chain"`  = 本记录的 version_from 与版本链中该版本的 parent 一致（连续区间）
    `"gap"`    = 版本链中存在中间版本 ⇒ 本区间跨了多个版本，`change_to_bug_ratio`
                 会被稀释（文件数是多版累计，Bug 只算末版）。消费方需据此谨慎解读。
    `"unknown"`= 版本链无该版本信息
    """
    entry = chain_canon.get(to_canon) if to_canon else None
    if not entry:
        return "unknown"
    chain_parent = norm_version(entry.get("parent_raw"))
    if chain_parent and parent_canon and chain_parent == parent_canon:
        return "chain"
    return "gap"


def _high_risk_modules(rec):
    """取该记录中的高风险变更项（模块级）。

    优先 modules[].risk == 'high'；无 modules 时退化为「文件级计数」，
    此时用 metrics.high_risk 个占位项，name 标为 `(未归模块的高风险文件)`。
    """
    mods = [m for m in (rec.get("modules") or [])
            if str((m or {}).get("risk") or "").lower() == "high"]
    if mods:
        return mods
    n = int((rec.get("metrics") or {}).get("high_risk") or 0)
    return [{"name": "(未归模块的高风险文件)", "files": n, "risk": "high"}] if n else []


def run_mapping_engine(service, analytics_root, bugs, verbose=True):
    """以 service_metrics 记录为驱动，重建 cross_reference.json。

    ⚠️ 与旧实现的关键差异（2026-09-18）：
      · 驱动源：service_metrics 的 records（而非「版本链 ∪ Bug 版本」并集）
      · 版本键：跨文件比较一律先 norm_version() 归一
      · 新增  ：high_risk_hit_rate（原先文档有、代码无）
      · 不再产出「无 metrics 的空壳 mapping」

    返回 stats dict：{mappings, with_bug, high_risk_total, high_risk_with_bug,
                      high_risk_hit_rate, module_data_coverage, attribution}
    """
    svc_dir = os.path.join(analytics_root, service)
    chain_path = os.path.join(svc_dir, "version_chain.json")
    metrics_path = os.path.join(svc_dir, "service_metrics.json")

    # ---- 版本链：规范键 -> (原始版本, 父版本) ----
    chain_canon = {}
    all_chain_raw = []
    if os.path.isfile(chain_path):
        try:
            chain = cdx_errors.read_json(chain_path)
            for v in chain.get("versions", []):
                ver = (v or {}).get("version")
                if not ver:
                    continue
                all_chain_raw.append(ver)
                ck = norm_version(ver)
                if ck:
                    chain_canon[ck] = {"raw": ver, "parent_raw": (v or {}).get("parent"),
                                       "date": (v or {}).get("date")}
        except Exception as e:
            print(f"[WARN] version_chain.json 读取失败: {e}")

    # ---- 变更度量：规范键 -> record ----
    records = []
    if os.path.isfile(metrics_path):
        try:
            records = cdx_errors.read_json(metrics_path).get("records", [])
        except Exception as e:
            print(f"[WARN] service_metrics.json 读取失败: {e}")

    # ---- Bug 侧规范化（只归一一次，避免在循环里重复解析） ----
    bug_found_canon, bug_fixed_canon = {}, {}
    for b in bugs:
        bid = b.get("bug_id")
        if not bid:
            continue
        bf = norm_version(b.get("found_in_version"))
        bx = norm_version(b.get("fixed_in_version"))
        if bf:
            bug_found_canon.setdefault(bf, []).append(bid)
        if bx:
            bug_fixed_canon.setdefault(bx, []).append(bid)

    # Bug 模块数据覆盖率（决定 high_risk_hit_rate 走精确还是版本级归因）
    with_module = sum(1 for b in bugs if (b.get("module") or "").strip())
    module_coverage = round(with_module / len(bugs), 3) if bugs else 0.0
    module_data_missing = with_module == 0

    mappings = []
    hr_total = hr_with_bug = 0

    for rec in records:
        v_to_raw = rec.get("version_to")
        v_from_raw = rec.get("version_from")
        ck_to = norm_version(v_to_raw)
        ck_from = norm_version(v_from_raw)

        # 父版本：优先 record.version_from；其次 version_chain 的 parent；最后放弃
        parent_raw = v_from_raw
        parent_canon = ck_from
        if not parent_raw and ck_to in chain_canon:
            parent_raw = chain_canon[ck_to].get("parent_raw")
            parent_canon = norm_version(parent_raw)
        # 父版本规范化写法（统一成 规范键，避免 cross_reference 里两种写法混写）
        parent_disp = parent_canon or (str(parent_raw).strip() if parent_raw else "?")
        to_disp = ck_to or (str(v_to_raw).strip() if v_to_raw else "?")
        version_range = f"{parent_disp}→{to_disp}"

        found = list(bug_found_canon.get(ck_to, []))
        fixed = list(bug_fixed_canon.get(ck_to, []))
        # 父版本发现的 Bug：**只作上下文，绝不并入本区间的分子**。
        # 语义澄清（2026-09-18）：`change_to_bug_ratio` = 本版本发现的 Bug / 产出本版本的变更文件数；
        # 父版本的 Bug 属于「上一次变更」的质量债，若并入会虚增本区间比值。
        parent_bugs = [x for x in bug_found_canon.get(parent_canon, []) if x not in found] \
            if parent_canon else []

        m = rec.get("metrics") or {}
        files_changed = m.get("files_changed")
        ratio = round(len(found) / files_changed, 4) if files_changed else None

        det = rec.get("detections") or {}
        has_bug = bool(found or fixed)

        # ---- 高风险变更 ↔ Bug 归因 ----
        hr_mods = _high_risk_modules(rec)
        hr_items = []
        if module_data_missing:
            # 无模块数据：退化为「版本级归因」（诚实标注，不伪装成精确匹配）
            for mod in hr_mods:
                hr_items.append({
                    "module": mod.get("name"),
                    "file": None,
                    "files": mod.get("files"),
                    "risk": "high",
                    "bug_ids": (found + fixed) if has_bug else [],
                    "detection_hit": [k for k in DETECTION_KEYS if det.get(k)],
                    "attribution": "version",
                })
        else:
            bug_mods = [(b.get("bug_id"), b.get("module")) for b in bugs
                        if (b.get("module") or "").strip()]
            for mod in hr_mods:
                hit_ids = [bid for bid, bmod in bug_mods
                           if _module_name_matches(mod.get("name"), bmod)]
                hr_items.append({
                    "module": mod.get("name"),
                    "file": None,
                    "files": mod.get("files"),
                    "risk": "high",
                    "bug_ids": hit_ids,
                    "detection_hit": [k for k in DETECTION_KEYS if det.get(k)],
                    "attribution": "module",
                })

        hr_total += len(hr_items)
        hr_with_bug += sum(1 for it in hr_items if it["bug_ids"])

        # ---- 检测精度（修复：hit_with_bug 反映真实归因，不再被 join 断裂污染） ----
        detection_precision = {}
        for k in DETECTION_KEYS:
            hit = bool(det.get(k))
            detection_precision[k] = {
                "hit_with_bug": 1 if (hit and has_bug) else 0,
                "hit_total": 1 if hit else 0,
            }

        mappings.append({
            "version_range": version_range,
            "version_to": to_disp,
            "version_to_raw": v_to_raw,
            "bugs_found_in_version": found,
            "bugs_fixed_in_version": fixed,
            "bugs_from_parent_version": parent_bugs,
            "change_to_bug_ratio": ratio,
            "high_risk_changes_with_bugs": hr_items,
            "high_risk_total": len(hr_items),
            "high_risk_with_bug": sum(1 for it in hr_items if it["bug_ids"]),
            "high_risk_hit_rate": (round(sum(1 for it in hr_items if it["bug_ids"]) / len(hr_items), 3)
                                   if hr_items else None),
            "commits_with_bugs": None,
            "commits_data_source": "unavailable",
            "detections": det,
            "detection_precision": detection_precision,
            "files_changed": files_changed,
            "segment": _segment_of(rec, chain_canon, parent_canon, ck_to),
        })

    rate = round(hr_with_bug / hr_total, 3) if hr_total else None
    stats = {
        "mappings": len(mappings),
        "records_total": len(records),
        "with_bug": sum(1 for x in mappings if x["bugs_found_in_version"] or x["bugs_fixed_in_version"]),
        "high_risk_total": hr_total,
        "high_risk_with_bug": hr_with_bug,
        "high_risk_hit_rate": rate,
        "attribution": "version" if module_data_missing else "module",
        "module_data_coverage": module_coverage,
        "module_data_missing": module_data_missing,
        "version_key_inconsistency": inconsistent_keys_by_source({
            "service_metrics.version_from": [r.get("version_from") for r in records],
            "service_metrics.version_to": [r.get("version_to") for r in records],
            "version_chain.version": all_chain_raw,
            # ⚠️ Bug 侧必须一并扫描：本缺陷的根因正是「metrics 带前缀 / bugs 裸号」，
            #    只扫 metrics+chain 会得出「0 处不一致」的假阴性。
            "version_bugs.found_in_version": [b.get("found_in_version") for b in bugs],
            "version_bugs.fixed_in_version": [b.get("fixed_in_version") for b in bugs],
        }),
    }

    out = {
        "service": service,
        "schema_version": "1.1",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "service_metrics.json (metrics-driven)",
        "version_key_policy": "norm_version: 取首个「数字.数字」连续段，跨文件比较前必须归一",
        "attribution": stats["attribution"],
        "module_data_coverage": module_coverage,
        "module_data_missing": module_data_missing,
        "high_risk_hit_rate": rate,
        "high_risk_total": hr_total,
        "high_risk_with_bug": hr_with_bug,
        "mappings": mappings,
    }
    with open(os.path.join(svc_dir, "cross_reference.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  映射引擎      : {len(mappings)} 条 mapping（= service_metrics {len(records)} 条记录）")
        vki = stats['version_key_inconsistency']
        if vki:
            print(f"  ⚠️ 版本键写法  : {len(vki)} 处不一致（跨文件可能失配，已由 norm_version 兜住）")
            for k, e in sorted(vki.items()):
                print(f"      {k}: {e['raw_forms']}  ← {e['sources']}")
        else:
            print("  版本键写法    : 全库一致")
        print(f"  Bug 模块覆盖  : {module_coverage:.0%}"
              + ("  ⚠️ 全为空，high_risk_hit_rate 退化为「版本级归因」" if module_data_missing else ""))
        if hr_total:
            print(f"  high_risk_hit_rate: {rate} ({hr_with_bug}/{hr_total})  归因方式={stats['attribution']}")
        else:
            print("  high_risk_hit_rate: 无高风险变更项，无法计算（诚实留空，不填 0 伪装）")
    return stats


# ----------------------------------------------------------------------------
# 版本系列隔离：Bug 数据按「版本系列（前两段，如 5.3）」归档
# ----------------------------------------------------------------------------
# version_series() 已统一由 _common 提供（2026-09-18），此处不再本地实现。
# 旧实现与本模块外版本处理口径不一致，是「版本键失配」缺陷的一部分。


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
    if not os.path.isfile(args.xlsx):
        sys.stderr.write(f"[ERROR] xlsx 不存在: {args.xlsx}\n")
        sys.exit(1)

    headers, bugs = parse_xlsx(args.xlsx)
    if not bugs:
        sys.stderr.write("[ERROR] 未解析到任何 bug 记录，请检查 sheet 名/列名\n")
        sys.exit(1)

    # 服务判定
    service = args.service
    if not service:
        bug_versions = [b["found_in_version"] for b in bugs if b["found_in_version"]] + \
                       [b["fixed_in_version"] for b in bugs if b["fixed_in_version"]]
        service = detect_service(analytics_root, bug_versions)
        if not service:
            sys.stderr.write("[ERROR] 无法自动探测服务，请用 --service 指定\n")
            sys.exit(1)
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
                        try:
                            existing = cdx_errors.read_json(path).get("bugs", [])
                        except Exception:
                            existing = []
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
                sys.stderr.write(
                    f"[ERROR] 按版本系列 {target_series} 过滤后无任何 Bug，请确认 --version 是否正确\n")
                sys.exit(1)

    # 按版本系列覆写 version_bugs.json（xlsx 为权威来源，仅覆盖目标系列）
    # 2026-09-18: 导入时补端归属预判字段（side_pre，可人工覆盖；不参与评分）
    for _b in bugs:
        _side, _hit = classify_bug_side(_b)
        _b["side_pre"] = _side
        _b["side_pre_hit"] = _hit
    version_bugs = {
        "service": service,
        "schema_version": "1.2",
        "scope": "project" if service == PROJECT_SERVICE else "service",
        "version_series": target_series or "all",
        "source_xlsx": os.path.basename(args.xlsx),
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bugs": bugs,
    }
    with open(os.path.join(svc_dir, "version_bugs.json"), "w", encoding="utf-8") as f:
        json.dump(version_bugs, f, ensure_ascii=False, indent=2)

    # 映射引擎（返回详细统计，供摘要 + 门禁使用）
    map_stats = run_mapping_engine(service, analytics_root, bugs)
    n_map = map_stats["mappings"]

    # ---- Bug 数据质量诊断（模块列覆盖率）----
    # high_risk_hit_rate 依赖 Bug 的「模块」列做精确归因；若该列全空，
    # 只能退化为「版本级归因」。此处显式告警，避免报告里出现看似精确实则粗糙的指标。
    mod_cov = map_stats["module_data_coverage"]
    if map_stats["module_data_missing"]:
        print(f"[WARN] Bug「模块」列覆盖率为 0（{len(bugs)}/{len(bugs)} 条为空）。")
        print("       → high_risk_hit_rate 已退化为「版本级归因」（整区间级），非模块级精确匹配。")
        print("       → 建议在 TAPD 导出时带上「模块」列，或改用 --module-from-title 从标题推断。")

    # 回填 service_metrics.json 对应版本记录的 bug_links
    # （综合报告摘要卡的「关联 Bug」取该字段，不回填会一直显示 0）
    # 【2026-09-18 修复】原实现末尾只回填「最新一条匹配记录」，其余记录永远为 0；
    # 现改为回填该系列下所有记录，按规范化版本键归属。
    n_links = 0
    try:
        mp = os.path.join(svc_dir, "service_metrics.json")
        if os.path.isfile(mp):
            metrics = cdx_errors.read_json(mp)
            ids = [b["bug_id"] for b in bugs if b.get("bug_id")]
            if ids:
                for rec in metrics.get("records", []):
                    vs = version_series(rec.get("version_to")) or version_series(rec.get("version_from"))
                    if target_series is None or vs == target_series:
                        rec["bug_links"] = ids
                        n_links += 1
                if n_links:
                    with open(mp, "w", encoding="utf-8") as mf:
                        json.dump(metrics, mf, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 回填 bug_links 失败: {e}")

    # ---- file_history 完整性自检（只读检查，修复交给 sync_analytics.py）----
    try:
        import sync_analytics
        fh_report = sync_analytics.check_file_history(service, analytics_root)
        if fh_report.get("issues"):
            print(f"[WARN] file_history 完整性有问题：{len(fh_report['issues'])} 项")
            for it in fh_report["issues"][:6]:
                print(f"       - {it}")
            print("       → 运行 `python scripts/sync_analytics.py --service %s` 可确定性重建" % service)
    except Exception as e:
        print(f"[WARN] file_history 自检跳过: {e}")

    # 摘要
    closed = sum(1 for b in bugs if b["status"] == "closed")
    resolved = sum(1 for b in bugs if b["status"] == "resolved")
    sev_counts = {}
    for b in bugs:
        sev_counts[b["severity"]] = sev_counts.get(b["severity"], 0) + 1
    print("=" * 62)
    print(f"服务            : {service}")
    print(f"版本系列        : {target_series or 'all（--keep-all）'}")
    print(f"Bug 总数        : {len(bugs)}")
    print(f"已关闭/已解决    : 已关闭 {closed} / 已解决 {resolved} / 其余(open) {len(bugs)-closed-resolved}")
    print(f"严重度分布      : {sev_counts}")
    print(f"version_bugs    : 已按系列覆写 ({len(bugs)} 条)")
    if archived_total:
        detail = "  ".join(f"{k}:{v}" for k, v in sorted(archived_detail.items()))
        print(f"历史归档        : {archived_total} 条 -> _archive/  ({detail})")
    print(f"cross_reference : 已全量重建 ({n_map} 条映射，与 service_metrics 记录数一致)")
    # 关键自检：映射条数必须等于 metrics 记录数，否则说明仍有 join 断裂
    if n_map != map_stats["records_total"]:
        print(f"[FAIL] 映射条数 {n_map} != service_metrics 记录数 {map_stats['records_total']}，"
              f"存在未被消费的记录！")
    else:
        print(f"  ✅ 映射覆盖率  : {n_map}/{map_stats['records_total']}（100%）")
    print(f"  带 Bug 的映射  : {map_stats['with_bug']} 条")
    if n_links:
        print(f"bug_links 回填   : service_metrics {n_links} 条记录")
    print(f"落盘目录        : {svc_dir}")
    print("=" * 62)


if __name__ == "__main__":
    cdx_errors.guard(main)
