#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack_reports.py — 把本轮生成的 code-diff 报告打成「结构保真」的可分享 zip。

为什么需要它：
    综合报告（_综合/xxx.html）里的跨服务跳转链接是【相对路径】`../{service}/xxx.html`，
    设计前提是「服务报告在 {service}/、综合报告在 _综合/，二者同级」。
    如果打包时把文件拍平到根目录（arcname=basename），解压后 `../{service}/` 就指向
    不存在的目录，出现 ERR_FILE_NOT_FOUND（「无法访问您的文件」）。
    因此打包必须【保留相对目录结构】。

用法：
    python pack_reports.py \
        --root   "d:/workbuddy/测试日常/report/code-diff" \
        --bundle "码上5.3.0影响变更报告_20260918" \
        --out    "d:/workbuddy/测试日常/report/code-diff/码上5.3.0影响变更报告_20260918.zip" \
        --file "portal-backend/portal-backend_business-5.3.0.3_to_business-5.3.0.4_变更影响分析报告.html" \
        --file "manage-frontend/manage-frontend_v5.3.0.7_to_v5.3.0.8_变更影响分析报告.html" \
        --file "_综合/综合比对分析报告_portal-backend_manage-frontend_20260918.html"

要点：
    - `--file` 的路径是相对 `--root` 的，打包时原样保留（含 `_综合/` 等子目录）。
    - 自动写入 `使用说明.txt`，指明「先解压整包、从 _综合/ 打开综合报告」。
    - 打包后自动做一次「链接自检」：解压到临时目录，解析综合报告的相对链接，
      校验目标文件是否真实存在；有断链则以退出码 3 结束。
"""
import argparse
import cdx_errors  # 统一友好错误层
import os
import re
import shutil
import sys
import tempfile
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

README_NAME = "使用说明.txt"
README_BODY = """码上变更影响分析报告包 · 使用说明
==================================================

【重要】请先「全部解压」再打开，不要只从压缩包里直接双击预览。
         压缩包内保留了下述目录结构，综合报告的跨服务跳转链接依赖该结构。

目录结构
--------
{bundle}/
├── _综合/            综合比对分析报告（多服务汇总，入口建议从这里进）
├── {services}

打开方式
--------
1. 解压整个压缩包到一个文件夹；
2. 先打开 `_综合/` 下的综合比对分析报告；
3. 报告内的服务卡片可点击跳转到 `portal-backend/`、`manage-frontend/` 等
   对应服务的独立报告（相对路径跳转，只要三者保持同级即可正常打开）；
4. 各服务独立报告均为自包含单文件，也可单独双击打开或单独转发。

常见问题
--------
Q: 点服务链接提示「无法访问您的文件 / ERR_FILE_NOT_FOUND」？
A: 说明解压时把文件拍平了、或只解压了部分文件。请整包解压并保持
   `_综合/` 与各服务目录同级，再重新打开综合报告。

生成时间：{ts}
"""


def build_readme(bundle: str, files: list) -> str:
    services = sorted({os.path.dirname(f) for f in files if os.path.dirname(f) and os.path.dirname(f) != "_综合"})
    if services:
        svc_block = "\n".join(f"├── {s}/" + " " * max(1, 22 - len(s)) + "各服务独立报告" for s in services)
    else:
        svc_block = "└── {service}/         各服务独立报告"
    from datetime import datetime
    return README_BODY.format(bundle=bundle, services=svc_block,
                              ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def verify_links(extract_dir: str, bundle: str, files: list) -> list:
    """解析每份报告的相对链接，校验解压后目标是否存在。返回断链列表。"""
    broken = []
    for rel in files:
        rp = os.path.join(extract_dir, bundle, rel)
        if not os.path.exists(rp):
            broken.append((rel, "报告自身缺失"))
            continue
        if not rel.endswith(".html"):
            continue
        t = cdx_errors.read_text(rp)
        for m in re.finditer(r'(?:href|src)="([^"#]+)"', t):
            target = m.group(1)
            if target.startswith(("http://", "https://", "data:", "mailto:", "javascript:")):
                continue
            if re.search(r"\.(html?|css|js|png|jpe?g|gif|svg|webp|ico)$", target, re.I):
                tp = os.path.normpath(os.path.join(os.path.dirname(rp), target))
                if not os.path.exists(tp):
                    broken.append((rel, target))
    return broken


def main():
    ap = argparse.ArgumentParser(description="把 code-diff 报告打包成结构保真的可分享 zip")
    ap.add_argument("--root", required=True, help="报告根目录（相对链接的基准，如 report/code-diff）")
    ap.add_argument("--out", required=True, help="输出 zip 的绝对/相对路径")
    ap.add_argument("--bundle", required=True, help="解压后顶层文件夹名（如 码上5.3.0影响变更报告_20260918）")
    ap.add_argument("--file", action="append", required=True,
                    help="相对 --root 的报告路径（可多次传入），原样保留子目录")
    ap.add_argument("--no-readme", action="store_true", help="不写入 使用说明.txt")
    ap.add_argument("--no-verify", action="store_true", help="跳过打包后的链接自检")
    args = ap.parse_args()

    files = [f.replace("\\", "/").lstrip("/") for f in args.file]

    missing = [f for f in files if not os.path.exists(os.path.join(args.root, f))]
    if missing:
        print("[ERROR] 以下报告不存在，请检查 --root / --file：", file=sys.stderr)
        for f in missing:
            print("   -", f, file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(args.root, rel), arcname=f"{args.bundle}/{rel}")
        if not args.no_readme:
            z.writestr(f"{args.bundle}/{README_NAME}", build_readme(args.bundle, files))

    print("已打包（结构保真）:", args.out)
    print("大小:", os.path.getsize(args.out), "bytes")
    with zipfile.ZipFile(args.out) as z:
        for i in z.namelist():
            print("   ", i)

    if not args.no_verify:
        tmp = tempfile.mkdtemp(prefix="rsverify_")
        try:
            with zipfile.ZipFile(args.out) as z:
                z.extractall(tmp)
            broken = verify_links(tmp, args.bundle, files)
            if broken:
                print("\n[FAIL] 解压后存在断链：", file=sys.stderr)
                for src, tgt in broken:
                    print(f"   {src}  ->  {tgt}", file=sys.stderr)
                print("提示：确认已保留子目录结构（不要拍平 arcname）。", file=sys.stderr)
                return 3
            print("\n[OK] 链接自检通过：解压后所有相对链接均可解析。")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(cdx_errors.guard(main))
