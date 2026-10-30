#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_testcases.py — 测试用例资产的机械评审脚本（Phase 6.1）

定位：Agent 自动评审里「能靠确定性规则判掉的」这一层先跑掉，把人的注意力
留给语义判断。纯标准库、零第三方依赖、结果可复现。

用法：
  python review_testcases.py testcases.json stats
  python review_testcases.py testcases.json duplicates
  python review_testcases.py testcases.json all          # stats + duplicates
  python review_testcases.py testcases.json stats --json-out report.json

输入格式（宽松，自动识别）：
  - 顶层数组： [ {...}, {...} ]
  - 顶层对象： {"testcases": [...]} / {"cases": [...]} / {"items": [...]} / {"data": [...]}
  单条用例的字段名兼容中英文，见 FIELD_ALIASES。

子命令：
  stats       总量、优先级/套件/类型分布、字段缺失、步骤与预期编号配对检查
  duplicates  完全重名 + 近似重复（名称与步骤的字符 bigram Jaccard）
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict

FIELD_ALIASES = {
    "id":       ["用例编号", "编号", "id", "case_id", "caseId", "case_no"],
    "name":     ["用例名称", "名称", "name", "title", "case_name", "summary"],
    "pre":      ["预置条件", "前置条件", "precondition", "preconditions", "pre_condition"],
    "steps":    ["测试过程", "操作步骤", "步骤", "steps", "step", "procedure"],
    "expected": ["接收标准", "预期结果", "预期", "expected", "expected_result", "expectation"],
    "priority": ["优先级", "priority", "pri", "level"],
    "suite":    ["测试套件", "所属套件", "模块", "suite", "module", "feature", "component"],
    "type":     ["用例类型", "类型", "type", "case_type", "category"],
}


def norm(v):
    """归一化单元格值：去空白、折叠空白、转字符串。"""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v)
    return " ".join(str(v).split())


def pick(row, field):
    for k in FIELD_ALIASES[field]:
        if k in row:
            return norm(row[k])
    return ""


def load_cases(path):
    """读入并归一化为统一结构；格式不对时给出可执行的报错。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"找不到文件：{path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} 不是合法 JSON：第 {e.lineno} 行第 {e.colno} 列 —— {e.msg}\n"
                         f"提示：Excel/CSV 需先转成 JSON；可参考 README 里的最小示例。")

    if isinstance(raw, dict):
        for key in ("testcases", "cases", "items", "data", "用例", "list"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raise SystemExit("顶层是对象但找不到用例数组（支持键：testcases / cases / items / data / 用例 / list）")
    if not isinstance(raw, list):
        raise SystemExit(f"顶层结构应为数组或用例数组对象，实际是 {type(raw).__name__}")

    cases, skipped = [], 0
    for r in raw:
        if not isinstance(r, dict):
            skipped += 1
            continue
        c = {f: pick(r, f) for f in FIELD_ALIASES}
        if not c["name"]:
            skipped += 1
            continue
        cases.append(c)

    if not cases:
        raise SystemExit("没有解析出任何用例：至少需要「用例名称」（或 name/title）字段。")
    if skipped:
        print(f"[提示] 跳过 {skipped} 条无效记录（非对象或缺用例名称）\n", file=sys.stderr)
    return cases


def _num_marks(text):
    """取文本里 "1." "2." 这类编号的行号集合，用于步骤↔预期配对检查。

    注意：norm() 会把换行折成空格，所以不能只按行首 ^ 匹配，需允许前置空白/分号。
    """
    return [int(m.group(1)) for m in re.finditer(r"(?:^|[\s；;])(\d{1,2})\s*[.、)]", text)]


def cmd_stats(cases):
    n = len(cases)
    print("=" * 60)
    print(f"用例总数：{n}")

    for field, label in (("priority", "优先级"), ("type", "用例类型"), ("suite", "测试套件")):
        cnt = Counter(c[field] or "(未填)" for c in cases)
        if len(cnt) == 1 and "(未填)" in cnt:
            print(f"{label}分布：(全部未填)")
        else:
            detail = " / ".join(f"{k}:{v}" for k, v in cnt.most_common(8))
            print(f"{label}分布：{detail}" + (" …" if len(cnt) > 8 else ""))

    # 字段完整率
    print("\n字段完整率：")
    for field, label in (("pre", "预置条件"), ("steps", "测试过程"),
                         ("expected", "接收标准"), ("priority", "优先级")):
        filled = sum(1 for c in cases if c[field])
        flag = "" if filled == n else "  ← 缺失"
        print(f"  {label:<6} {filled}/{n} ({filled * 100 // n}%){flag}")

    # 步骤 ↔ 预期 编号配对
    mismatch = []
    for c in cases:
        s, e = _num_marks(c["steps"]), _num_marks(c["expected"])
        if s and e and s != e:
            mismatch.append((c["name"], s, e))
    print(f"\n步骤↔预期编号配对：{n - len(mismatch)}/{n} 一致")
    for name, s, e in mismatch[:10]:
        print(f"  ✗ {name[:36]}  步骤{s} vs 预期{e}")
    if len(mismatch) > 10:
        print(f"  …另有 {len(mismatch) - 10} 条")

    # 步骤条数分布
    steps_cnt = Counter(len(_num_marks(c["steps"])) for c in cases)
    print("\n步骤条数分布：" + " / ".join(f"{k}步:{v}条" for k, v in sorted(steps_cnt.items())))
    thin = [c["name"] for c in cases if 0 < len(_num_marks(c["steps"])) <= 1]
    if thin:
        print(f"  ⚠ 仅 1 步（可能描述过粗）{len(thin)} 条：{', '.join(x[:24] for x in thin[:5])}")

    return {"total": n,
            "priority": dict(Counter(c["priority"] or "(未填)" for c in cases)),
            "type": dict(Counter(c["type"] or "(未填)" for c in cases)),
            "suite": dict(Counter(c["suite"] or "(未填)" for c in cases)),
            "numbering_mismatch": [{"name": x[0], "steps": x[1], "expected": x[2]} for x in mismatch]}


def _bigrams(text):
    t = norm(text)
    if len(t) <= 1:
        return set(t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cmd_duplicates(cases, threshold):
    print("=" * 60)
    # 1. 完全重名
    by_name = defaultdict(list)
    for c in cases:
        by_name[c["name"]].append(c)
    exact = {k: v for k, v in by_name.items() if len(v) > 1}
    print(f"完全重名：{len(exact)} 组")
    for name, group in list(exact.items())[:10]:
        ids = ", ".join(c["id"] or "(无编号)" for c in group)
        print(f"  ✗ {name[:40]}  ×{len(group)}  [{ids}]")

    # 2. 近似重复：名称或步骤 bigram 相似度过阈值
    sig = [(c, _bigrams(c["name"]), _bigrams(c["steps"])) for c in cases]
    near = []
    for i in range(len(sig)):
        ci, ni, si = sig[i]
        for j in range(i + 1, len(sig)):
            cj, nj, sj = sig[j]
            if ci["name"] == cj["name"]:
                continue
            score = max(_jaccard(ni, nj), _jaccard(si, sj))
            if score >= threshold:
                near.append((score, ci, cj))
    near.sort(key=lambda x: -x[0])
    print(f"\n近似重复（阈值 {threshold}）：{len(near)} 对")
    for score, a, b in near[:10]:
        print(f"  ~ {score:.2f}  {a['name'][:30]}  ⇄  {b['name'][:30]}")
    if len(near) > 10:
        print(f"  …另有 {len(near) - 10} 对")

    # 3. 同名跨套件（可能是同功能不同路径，需人工判断，不算错）
    cross = []
    for name, group in by_name.items():
        if len(group) > 1:
            suites = {c["suite"] for c in group if c["suite"]}
            if len(suites) > 1:
                cross.append((name, sorted(suites)))
    if cross:
        print(f"\n同名跨套件（{len(cross)} 组，需人工判断是否为场景差异）：")
        for name, suites in cross[:5]:
            print(f"  ? {name[:30]}  →  {' / '.join(suites)}")

    return {"exact_duplicate_groups": len(exact),
            "near_duplicate_pairs": len(near),
            "near_duplicate_detail": [{"score": round(s, 3), "a": a["name"], "b": b["name"]}
                                      for s, a, b in near[:50]]}


def main():
    ap = argparse.ArgumentParser(description="测试用例资产机械评审（零依赖）")
    ap.add_argument("json_file", help="用例 JSON（数组，或含 testcases/cases/items/data 键的对象）")
    ap.add_argument("command", choices=["stats", "duplicates", "all"], help="stats / duplicates / all")
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="近似重复判定阈值（字符 bigram Jaccard），默认 0.75")
    ap.add_argument("--json-out", default="", help="把结果另存为 JSON")
    args = ap.parse_args()

    cases = load_cases(args.json_file)
    result = {}
    if args.command in ("stats", "all"):
        result.update(cmd_stats(cases))
    if args.command in ("duplicates", "all"):
        if result:
            print()
        result.update(cmd_duplicates(cases, args.threshold))
    print("=" * 60)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入：{args.json_out}")


if __name__ == "__main__":
    main()
