#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
平台 官方导入模板生成器（excel-testcase-18col v2.1 / test-pipeline-mvp v2.13）

设计要点（★ 均为 2026-11-09 实测事故后的硬约束）：
  1. 以用户提供的**官方模板副本**为基底，保留「测试用例表 + 填写说明」双 sheet
     与 A/F/G/H/I/Q 六列数据验证，绝不另建工作簿（避免列序/枚举漂移）。
  2. 全部用例 可测试=Y（实验室可以测试） / 基础用例=Y（基础用例） / 状态=有效，
     验证话单=N（不检查）—— 用户 2026-11-09 明确确认，非推断、不提供开关。
     中文「是/否」「待评审」一律禁止。
  3. 类型只用 平台 8 类枚举；物理固定 18 列，无第 19 列覆盖路径。
  4. 套件树按**原有功能模块目录结构**组织：顶层套件 → 功能模块一级套件 → 用例。
  5. 套件行只填 A/B/C/D/O 五列；用例行 E/M/N/P/R 留空。
  6. 生成后执行 6 项机器校验，任一不过即阻塞（不产出可导入文件）。

用法：
  python gen_platform_import.py --template <官方模板.xlsx> --source <cases.json> --output <输出.xlsx>

source JSON 结构：
{
  "project": "示例模块 v1.0",
  "suites": [{"code": 101, "name": "示例套件", "desc": "…"}, ...],
  "cases": [
    {"code": 10101, "suite": 101, "name": "…", "type": "正常流程",
     "pre": ["…"], "steps": ["…"], "expected": ["…"], "desc": "…"}
  ]
}
  * code 必须为数字；用例 code // 100 == suite；suite 必须在 suites 中真实存在。
  * steps 与 expected 必须 1:1（纯导航步骤的 expected 可写 "-"）。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Side
from openpyxl.utils import get_column_letter

TYPE_ENUM = {"正常流程", "异常流程", "性能测试", "集成测试",
             "回归测试", "遍历测试", "冒烟测试", "其他"}
HEADERS = ["实体标识", "编号", "名称", "归属套件", "版本", "类型", "可测试", "基础用例",
           "状态", "预置条件", "测试过程", "接收标准", "创建人", "创建时间", "描述",
           "脚本名称", "验证话单", "信令流程"]
MERGE_PAT = re.compile(r"[（(]\s*合并验证\s*[:：][^）)]*[）)]")
PREFIX_PAT = re.compile(r"^【(?:基础用例|非基础用例)】\s*")
PLACEHOLDER_PAT = re.compile(r"\{\{[^}]+\}\}")


def numbered(items):
    """条列化：1. xxx\n2. xxx"""
    return "\n".join(f"{i}. {str(x).strip()}" for i, x in enumerate(items, 1))


def clean(text):
    """清除步骤/预期中的合并验证内部标注与名称前缀（18col 质量红线 17）"""
    return PREFIX_PAT.sub("", MERGE_PAT.sub("", str(text)).strip()).strip()


def load_source(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    suites = data["suites"]
    cases = data["cases"]
    codes = [int(s["code"]) for s in suites]
    assert len(codes) == len(set(codes)), "套件编号重复"
    assert 1 not in codes, "编号 1 保留给顶层套件"
    for c in cases:
        c["suite"] = int(c["suite"])
        c["code"] = int(c["code"])
        assert c["code"] // 100 == c["suite"], f"归属不一致: {c['code']} -> {c['suite']}"
        assert c["suite"] in codes, f"套件不存在: {c['code']} -> {c['suite']}"
        assert clean(c["type"]) in TYPE_ENUM, f"类型非 平台 枚举: {c['code']} {c['type']}"
        assert len(c["steps"]) == len(c["expected"]), f"步骤/预期未 1:1: {c['code']}"
        assert len(c["pre"]) > 0, f"预置条件为空: {c['code']}"
    ids = [c["code"] for c in cases]
    assert len(ids) == len(set(ids)), "用例编号重复"
    return data, suites, cases, codes


def build(template, output, data, suites, cases):
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, out)          # ★ 官方模板副本，保留双 sheet 与数据验证
    wb = openpyxl.load_workbook(out)
    assert "测试用例表" in wb.sheetnames and "填写说明" in wb.sheetnames, \
        "官方模板缺少必需 sheet"
    ws = wb["测试用例表"]
    assert [ws.cell(1, i).value for i in range(1, 19)] == HEADERS, \
        "模板表头与 18 列规范不一致"

    # 清空第 2 行起的旧数据（保留表头、数据验证、样式定义）
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    def put(row, values, is_suite=False):
        for col in range(1, 19):
            cell = ws.cell(row, col)
            cell.value = values.get(col, None)
            cell.border = border
            cell.alignment = wrap

    r = 2
    # 顶层套件：编号 1 / 归属 0（0 不在表中 → 根节点）
    put(r, {1: "用例套件", 2: 1, 3: data["project"], 4: 0,
            15: f"版本 {data.get('version', '')} 全量用例集；按原有功能模块目录结构组织".strip()}, True)
    r += 1
    for s in suites:
        put(r, {1: "用例套件", 2: int(s["code"]), 3: s["name"], 4: 1,
                15: s.get("desc", "")}, True)
        r += 1

    for c in cases:
        # 合并簇追溯从步骤中剥离后，去重收进描述列（不污染可执行步骤）
        merged_ids = []
        for token in re.findall(r"TP-[A-Z]+-\d+", " ".join(c["steps"]) + " " + c["name"]):
            if token not in merged_ids:
                merged_ids.append(token)
        desc = c.get("desc", "")
        if merged_ids:
            desc = (desc + " | 合并验证：" + "、".join(merged_ids)).strip(" |")
        vals = {
            1: "测试用例", 2: c["code"], 3: clean(c["name"]), 4: c["suite"],
            5: None, 6: clean(c["type"]), 7: "Y", 8: "Y", 9: "有效",
            10: numbered([clean(x) for x in c["pre"]]),
            11: numbered([clean(x) for x in c["steps"]]),
            12: numbered([clean(x) for x in c["expected"]]),
            13: None, 14: None, 15: desc, 16: None, 17: "N", 18: None,  # Q=N 不检查（用户确认）
        }
        put(r, vals)
        ws.row_dimensions[r].height = max(20, len(c["steps"]) * 15 + 6)
        r += 1

    widths = [10, 10, 46, 10, 8, 12, 9, 10, 9, 40, 56, 56, 9, 12, 34, 12, 10, 10]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    wb.save(out)
    return out


def verify(path, suites, cases):
    """Step 5.5 六项机器校验 + 平台 结构校验"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["测试用例表"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    recs = [dict(zip(HEADERS, r)) for r in rows if r[0] in ("用例套件", "测试用例")]
    suite_ids = {int(x["编号"]) for x in recs if x["实体标识"] == "用例套件"}
    tcs = [x for x in recs if x["实体标识"] == "测试用例"]

    # ① 归属一致性
    bad = [(t["编号"], t["归属套件"]) for t in tcs
           if t["归属套件"] != t["编号"] // 100 or t["归属套件"] not in suite_ids]
    assert not bad, f"① 归属套件错误: {bad[:5]}"
    # ② 占位符残留
    ph = [t["编号"] for t in tcs for k in ("预置条件", "测试过程", "接收标准", "名称")
          if PLACEHOLDER_PAT.search(str(t[k]))]
    assert not ph, f"② 占位符残留: {ph[:5]}"
    # ③ 步骤/预期 1:1
    b3 = [t["编号"] for t in tcs
          if len(str(t["测试过程"]).split("\n")) != len(str(t["接收标准"]).split("\n"))]
    assert not b3, f"③ 步骤预期未配对: {b3[:5]}"
    # ④ 编号唯一
    ids = [t["编号"] for t in tcs]
    assert len(ids) == len(set(ids)), "④ 用例编号重复"
    # ⑤ 无合并验证引用 / 无名称前缀
    b5 = [t["编号"] for t in tcs for k in ("测试过程", "接收标准")
          if MERGE_PAT.search(str(t[k])) or PREFIX_PAT.search(str(t[k]))]
    assert not b5, f"⑤ 步骤/预期含内部标注: {b5[:5]}"
    assert not [t["编号"] for t in tcs if PREFIX_PAT.search(str(t["名称"]))], \
        "⑤ 名称含【基础用例】/【非基础用例】前缀"
    # ⑥ 选型合规（★ v2.1）
    b6 = [t["编号"] for t in tcs
          if t["类型"] not in TYPE_ENUM or t["可测试"] != "Y"
          or t["基础用例"] != "Y" or t["状态"] != "有效" or t["验证话单"] != "N"]
    assert not b6, f"⑥ 选型不合规: {b6[:5]}"
    # 结构：物理 18 列、双 sheet、六列数据验证、套件行只填 5 列
    assert ws.max_column == 18, f"物理列数非 18: {ws.max_column}"
    assert "填写说明" in wb.sheetnames, "缺少填写说明 sheet"
    dvs = {str(d.sqref).split(":")[0].rstrip("0123456789")
           for d in ws.data_validations.dataValidation}
    for col in ("A", "F", "G", "H", "I", "Q"):
        assert col in dvs, f"缺少 {col} 列数据验证"
    for x in recs:
        if x["实体标识"] != "用例套件":
            continue
        filled = [k for k in HEADERS if k not in ("实体标识", "编号", "名称", "归属套件", "描述")
                  and x[k] not in (None, "")]
        assert not filled, f"套件行多填列: {x['编号']} {filled}"

    print(f"校验通过：①归属 ②占位符 ③1:1 ④编号 ⑤内部标注 ⑥平台选型 / 18列 / 双sheet / 6列验证 / 套件行")
    print(f"套件数：{len(suite_ids)}（含顶层）　测试用例数：{len(tcs)}")
    print(f"选型：可测试=Y / 基础用例=Y / 状态=有效 → {len(tcs)}/{len(tcs)} (100%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="平台 官方导入模板 xlsx")
    ap.add_argument("--source", required=True, help="用例数据 JSON")
    ap.add_argument("--output", required=True, help="输出 xlsx")
    args = ap.parse_args()

    data, suites, cases, _ = load_source(args.source)
    out = build(args.template, args.output, data, suites, cases)
    verify(out, suites, cases)
    print(f"已生成可导入文件：{out}")


if __name__ == "__main__":
    sys.exit(main())
