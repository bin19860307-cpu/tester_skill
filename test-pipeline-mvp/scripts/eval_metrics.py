#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_metrics.py — AI 用例生成评测：留存率 / 修改率 / 删除率

对比「首跑生成用例」(first-pass) 与「封版 final 用例」(final) 两版 xlsx，
以用例名称(或用例编号)对齐，统计测试人员对首跑用例的 改/删 操作，
输出量化指标，支撑版本基线与控制变量迭代。

指标（分母 = 首跑生成用例总数 N）：
  - 留存率(retention) = 首跑采纳率 = 首跑到封版未被改、未被删的占比（注：≠有效率，含漏检风险）
  - 修改率(modification)          = 首跑到封版被改动的占比
  - 删除率(deletion)             = 首跑到封版被删除的占比
  - 缺口率(gap) = 封版新增数 / 封版总数 = AI 漏生成的覆盖盲区占比
  - 修改严重度：轻改(内容字段差异 < 阈值) / 重改(≥阈值)，阈值默认 0.5

用法：
  python eval_metrics.py --first 首跑.xlsx --final 封版.xlsx
  python eval_metrics.py --first a.xlsx --final b.xlsx --group-col 测试套件 --out ../baseline/eval-result.json

依赖：openpyxl（系统 Python 3.12 已带；managed venv 需 pip install openpyxl）
"""
import argparse
import json
import os
import re
import sys

try:
    from openpyxl import load_workbook
except ImportError:
    sys.stderr.write("缺少 openpyxl，请先安装：pip install openpyxl\n")
    sys.exit(2)


def _norm(v):
    """归一化单元格值用于比较：去空白、折叠空白、转字符串。"""
    if v is None:
        return ""
    return " ".join(str(v).split())


def _col_index(header, names):
    """在表头行中按候选列名顺序找第一个存在的列索引(0-based)。"""
    for n in names:
        if n in header:
            return header.index(n)
    return -1


def _read_cases(path, name_cols, content_cols, group_col, entity_col="", entity_val="", name_strip=""):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], {}
    header = [str(c) if c is not None else "" for c in rows[0]]
    name_idx = _col_index(header, name_cols)
    if name_idx < 0:
        raise SystemExit(f"[{path}] 未找到名称列（候选：{name_cols}），请检查表头。")
    content_idx = [_col_index(header, [c]) for c in content_cols]
    content_idx = [i for i in content_idx if i >= 0]
    group_idx = _col_index(header, [group_col]) if group_col else -1
    entity_idx = _col_index(header, [entity_col]) if entity_col else -1
    strip_re = re.compile(name_strip) if name_strip else None

    cases = []
    for r in rows[1:]:
        raw = _norm(r[name_idx]) if name_idx < len(r) else ""
        name = strip_re.sub("", raw).strip() if strip_re else raw
        if not name:
            continue
        # 按实体标识过滤（仅统计用例行，排除用例套件行；兼容 18 列 AITest 模板）
        if entity_idx >= 0:
            ev = _norm(r[entity_idx]) if entity_idx < len(r) else ""
            if ev != entity_val:
                continue
        content = tuple(_norm(r[i]) if i < len(r) else "" for i in content_idx)
        group = _norm(r[group_idx]) if (group_idx >= 0 and group_idx < len(r)) else ""
        cases.append({"name": name, "content": content, "group": group})
    return cases, {c: i for i, c in enumerate(header)}


def _bigrams(text):
    """中文/混合文本字符 bigram 集合，用作轻量内容指纹。"""
    text = _norm(text)
    if len(text) <= 1:
        return set(text)
    return set(text[i:i + 2] for i in range(len(text) - 1))


def _content_sig(content_tuple):
    """由内容字段元组生成 bigram 指纹集合。"""
    toks = set()
    for field in content_tuple:
        toks |= _bigrams(field)
    return toks


def _sim(a_sig, b_sig):
    """Jaccard 相似度（内容指纹交集/并集）。"""
    if not a_sig or not b_sig:
        return 0.0
    inter = len(a_sig & b_sig)
    union = len(a_sig | b_sig)
    return inter / union if union else 0.0


def _field_diff_ratio(a, b):
    """内容字段差异比例：a,b 为内容字段元组（长度可不同，按 max 对齐）。"""
    n = max(len(a), len(b))
    if n == 0:
        return 0.0
    diff = 0
    for i in range(n):
        va = a[i] if i < len(a) else ""
        vb = b[i] if i < len(b) else ""
        if va != vb:
            diff += 1
    return diff / n


def _classify(first, final, fuzzy=True, sim_threshold=0.55, heavy_threshold=0.5):
    """配对首跑与封版用例，分类为 留存/修改/删除/新增。

    两阶段：
      1) 名称精确匹配 → 留存(内容一致) / 修改(内容变，按字段差异比例定轻/重)
      2) 孤儿首跑用例(名称无匹配) → 模糊匹配封版剩余用例：
         内容相似度 ≥ 阈值 判为「改名/合并=修改」(重大改写)，否则判为「删除」
    这样评审的「合并重写」操作不会虚增删除率。

    返回：retained(str列表), modified((name,severity)元组列表), deleted, added, fuzzy_modified
    """
    final_pool = list(final)
    final_sigs = [_content_sig(c["content"]) for c in final_pool]
    final_used = [False] * len(final_pool)
    retained, modified, deleted = [], [], []
    fuzzy_modified = 0
    orphan_first = []

    # Pass 1: 名称精确匹配
    for fc in first:
        idx = next((i for i, x in enumerate(final_pool)
                    if (not final_used[i]) and x["name"] == fc["name"]), None)
        if idx is None:
            orphan_first.append(fc)
            continue
        final_used[idx] = True
        if final_pool[idx]["content"] == fc["content"]:
            retained.append(fc["name"])
        else:
            ratio = _field_diff_ratio(fc["content"], final_pool[idx]["content"])
            sev = "heavy" if ratio >= heavy_threshold else "light"
            modified.append((fc["name"], sev))

    # Pass 2: 孤儿用例模糊匹配（合并/改名检测）
    if fuzzy:
        for fc in orphan_first:
            fc_sig = _content_sig(fc["content"])
            best_i, best_s = -1, 0.0
            for i, x in enumerate(final_pool):
                if final_used[i]:
                    continue
                s = _sim(fc_sig, final_sigs[i])
                if s > best_s:
                    best_s, best_i = s, i
            if best_i >= 0 and best_s >= sim_threshold:
                final_used[best_i] = True
                modified.append((fc["name"], "heavy"))   # 改名/合并 → 重大改写
                fuzzy_modified += 1
            else:
                deleted.append(fc["name"])               # 真正删除
    else:
        for fc in orphan_first:
            deleted.append(fc["name"])

    added = [final_pool[i]["name"] for i in range(len(final_pool)) if not final_used[i]]
    return retained, modified, deleted, added, fuzzy_modified


def _rate(n, total):
    return round(n / total, 4) if total else 0.0


def main():
    ap = argparse.ArgumentParser(description="AI 用例生成评测：留存率/修改率/删除率")
    ap.add_argument("--first", required=True, help="首跑生成用例 xlsx")
    ap.add_argument("--final", required=True, help="封版 final 用例 xlsx（标准答案）")
    ap.add_argument("--name-cols", default="用例名称,用例编号,名称", help="名称列候选(逗号分隔)，兼容 12列/18列模板")
    ap.add_argument("--content-cols",
                    default="预置条件,测试过程,接收标准,优先级,用例类型,用例性质,状态,类型,可测试,基础用例",
                    help="用于判定「是否被修改」的内容列(逗号分隔)，兼容 12列/18列模板")
    ap.add_argument("--group-col", default="", help="可选：按某列(如 测试套件/模块)分组统计")
    ap.add_argument("--entity-col", default="", help="可选：按实体标识列过滤(如 实体标识)，仅统计用例行")
    ap.add_argument("--entity-val", default="测试用例", help="实体标识过滤值(如 测试用例)")
    ap.add_argument("--fuzzy", dest="fuzzy", action="store_true", default=True,
                    help="开启模糊匹配(合并/改名检测)，默认开；名字对不上的首跑用例按内容相似度重新归类")
    ap.add_argument("--no-fuzzy", dest="fuzzy", action="store_false",
                    help="关闭模糊匹配，名字对不上的首跑用例一律判为删除")
    ap.add_argument("--sim-threshold", type=float, default=0.55,
                    help="模糊匹配相似度阈值(字符bigram Jaccard)，默认0.55")
    ap.add_argument("--heavy-threshold", type=float, default=0.5,
                    help="修改严重度阈值：内容字段差异比例≥此值判为「重改」，否则「轻改」，默认0.5")
    ap.add_argument("--name-strip", default="",
                    help="名称正则剥离(匹配前先去除)，用于处理命名规范差异，如终版加 '【非基础用例】' 前缀： --name-strip \"【[^】]*】\"")
    ap.add_argument("--out", default="", help="输出 eval-result.json 路径（默认打印不写文件）")
    args = ap.parse_args()

    name_cols = [x.strip() for x in args.name_cols.split(",") if x.strip()]
    content_cols = [x.strip() for x in args.content_cols.split(",") if x.strip()]

    first, _ = _read_cases(args.first, name_cols, content_cols, args.group_col,
                           args.entity_col, args.entity_val, args.name_strip)
    final, _ = _read_cases(args.final, name_cols, content_cols, args.group_col,
                           args.entity_col, args.entity_val, args.name_strip)

    retained, modified, deleted, added, fuzzy_modified = _classify(
        first, final, args.fuzzy, args.sim_threshold, args.heavy_threshold)
    N = len(first)
    final_total = len(final)
    light_mod = sum(1 for _, sev in modified if sev == "light")
    heavy_mod = sum(1 for _, sev in modified if sev == "heavy")

    summary = {
        "total_first_pass_cases": N,
        "retained": len(retained),
        "modified": len(modified),
        "light_modified": light_mod,
        "heavy_modified": heavy_mod,
        "deleted": len(deleted),
        "added": len(added),
        "final_total": final_total,
        "fuzzy_merged_renamed": fuzzy_modified,
        "retention_rate": _rate(len(retained), N),
        "modification_rate": _rate(len(modified), N),
        "deletion_rate": _rate(len(deleted), N),
        "gap_rate": _rate(len(added), final_total),
        "per_requirement": {},
    }

    # 分组统计（若提供 group-col）
    if args.group_col:
        from collections import defaultdict
        g_first = defaultdict(list)
        g_final = defaultdict(list)
        for c in first:
            g_first[c["group"]].append(c)
        for c in final:
            g_final[c["group"]].append(c)
        for g in sorted(set(g_first) | set(g_final)):
            rf, mf, df, _, _, _, _ = _classify(g_first.get(g, []), g_final.get(g, []),
                                              args.fuzzy, args.sim_threshold, args.heavy_threshold)
            gn = len(g_first.get(g, []))
            summary["per_requirement"][g] = {
                "total": gn, "retained": len(rf), "modified": len(mf),
                "deleted": len(df),
                "retention_rate": _rate(len(rf), gn),
                "modification_rate": _rate(len(mf), gn),
                "deletion_rate": _rate(len(df), gn),
            }

    # 控制台摘要
    print("=" * 56)
    print(f"首跑用例总数 N      : {N}")
    print(f"留存(首跑采纳率) {len(retained):>4}  | 留存率   : {summary['retention_rate']*100:.1f}%")
    print(f"修改        {len(modified):>4}  | 修改率   : {summary['modification_rate']*100:.1f}%")
    print(f"  ├ 轻改(小修) {light_mod:>4}  | 重改(大改) {heavy_mod:>4}  (阈值 {args.heavy_threshold})")
    print(f"删除        {len(deleted):>4}  | 删除率   : {summary['deletion_rate']*100:.1f}%")
    print(f"封版新增(缺口) {len(added):>4}  | 缺口率   : {summary['gap_rate']*100:.1f}%")
    print(f"模糊匹配(合并/改名检测) : {'开' if args.fuzzy else '关'} "
          f"(阈值 {args.sim_threshold}) | 合并/改名误删已挽回 {fuzzy_modified} 例")
    if args.group_col:
        print("-" * 56)
        print(f"分组({args.group_col})明细：")
        for g, d in summary["per_requirement"].items():
            print(f"  {g or '(空)':<20} N={d['total']:>3} 留存 {d['retention_rate']*100:5.1f}% "
                  f"修改 {d['modification_rate']*100:5.1f}% 删除 {d['deletion_rate']*100:5.1f}%")
    print("=" * 56)
    if modified:
        print(f"[修改] {', '.join(m[0] for m in modified)}")
    if deleted:
        print(f"[删除] {', '.join(deleted)}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n已写入: {args.out}")
    else:
        print("\n（未指定 --out，未写文件；加 --out 路径可生成 eval-result.json）")


if __name__ == "__main__":
    main()
