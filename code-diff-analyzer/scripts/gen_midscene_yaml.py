#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_midscene_yaml.py
把 code-diff-analyzer 产出的 P1 用例 JSON 转换成 Midscene YAML（UI 自动化可执行用例）。

映射规则（自然语言 → Midscene）：
  - case.scene / code     → 文件头注释（验证点 / 代码依据）
  - case.precondition     → 文件头注释「前置条件」
  - case.steps  (① ② …)  → 多条 aiAction（按带圈数字拆分）
  - case.expect (；…)     → 多条 aiAssert（按中文分号拆分）
  - case.kb_ref           → 文件头「状态: 命中知识库(XXX)」
  - case.estimated=True   → 文件头「状态: 预估新增」
  - 接口/数据层特征（"接口"/"查.*表"/"status="/"is_deleted"）→ 类型标 api，
    并在 flow 内注明「建议改用 API 自动化（pytest + api-tester）」，
    UI 层仅生成冒烟骨架（Midscene 难直接断言 DB 状态）。

用法:
  python gen_midscene_yaml.py \
      --data-file p1_cases.json \
      --out-dir auto-cases/midscene/权益控制 \
      --module 权益控制
"""
import argparse
import json
import os
import re

CIRCLED = re.compile(r'[①②③④⑤⑥⑦⑧⑨⑩]')
TRIM = ' 、,，;；.。\t'
API_HINT = re.compile(r'接口|查.*表|status\s*=|数据库|DB|is_deleted|返回含')


def split_steps(s: str):
    if not s:
        return []
    return [p.strip(TRIM) for p in CIRCLED.split(s) if p.strip(TRIM)]


def split_asserts(s: str):
    if not s:
        return []
    return [p.strip(TRIM) for p in re.split(r'[；;]', s) if p.strip(TRIM)]


def detect_type(case: dict) -> str:
    blob = ' '.join([
        case.get('steps', ''),
        case.get('expect', ''),
        case.get('code', ''),
    ])
    return 'api' if API_HINT.search(blob) else 'ui'


def yaml_q(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def gen_case_yaml(case: dict, module: str) -> str:
    cid = case.get('id', 'case')
    level = case.get('level', 'medium')
    scene = case.get('scene', '')
    steps = split_steps(case.get('steps', ''))
    asserts = split_asserts(case.get('expect', ''))
    ctype = detect_type(case)
    kb = case.get('kb_ref')
    status = (f'命中知识库({kb})' if kb
              else ('预估新增' if case.get('estimated') else '未标注'))
    pre = case.get('precondition', '')
    code = case.get('code', '')

    L = []
    L.append('# ' + '=' * 60)
    L.append(f'# 用例ID: {cid}')
    L.append('# 来源: code-diff-analyzer P1 预测')
    L.append(f'# 优先级: {level} | 状态: {status} | 类型: {ctype} | 模块: {module}')
    if pre:
        L.append(f'# 前置条件: {pre}')
    if code:
        L.append(f'# 代码依据: {code}')
    L.append('# ' + '=' * 60)
    L.append('target: "{{TARGET_URL}}"   # TODO: 替换为实际页面地址（如 /manage/my-rights）')
    L.append('tasks:')
    L.append(f'  - name: {yaml_q(f"{cid} {scene}")}')
    L.append('    flow:')
    if ctype == 'api':
        L.append('      # ⚠️ 本用例本质为接口/数据层，建议改用 API 自动化（pytest + api-tester）')
        L.append('      #   UI 层(Midscene)难以直接断言 DB status / is_deleted，此处仅生成 UI 视角冒烟骨架')
    for st in steps:
        L.append(f'      - aiAction: {yaml_q(st)}')
    for a in asserts:
        L.append(f'      - aiAssert: {yaml_q(a)}')
    if not steps and not asserts:
        L.append('      - aiAssert: "TODO: 补充可执行断言"')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-file', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--module', default='权益控制')
    args = ap.parse_args()

    with open(args.data_file, encoding='utf-8') as f:
        data = json.load(f)

    os.makedirs(args.out_dir, exist_ok=True)
    count = 0
    manifest = []
    for g in data.get('groups', []):
        for c in g.get('cases', []):
            cid = c.get('id', 'case')
            scene = re.sub(r'[\\/:*?"<>|]', '', c.get('scene', ''))[:18]
            fname = f"{cid}_{scene}.yaml"
            yml = gen_case_yaml(c, args.module)
            with open(os.path.join(args.out_dir, fname), 'w', encoding='utf-8') as f:
                f.write(yml)
            count += 1
            manifest.append({
                'file': fname,
                'id': cid,
                'type': detect_type(c),
                'kb': c.get('kb_ref'),
                'estimated': c.get('estimated', False),
            })

    with open(os.path.join(args.out_dir, '_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump({'module': args.module, 'count': count, 'cases': manifest},
                  f, ensure_ascii=False, indent=2)

    print(f"OK 生成 {count} 个 Midscene YAML → {args.out_dir}")


if __name__ == '__main__':
    main()
