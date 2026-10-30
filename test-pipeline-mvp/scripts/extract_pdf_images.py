#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_pdf_images.py — 从需求 PDF 中提取内嵌图片（Phase 0.2）

用途：需求文档里的流程图/状态图/序列图/UI 原型是测试点的重要来源，但它们
在 PDF 里是图片对象，纯文本提取拿不到。本脚本把它们落盘成独立文件。

特性（按 SKILL.md 的约定实现）：
  - xref 优先：装了 PyMuPDF 就走 xref 精确提取（支持所有编码）
  - 零依赖降级：没装任何库时，用标准库直接扫描 DCTDecode(JPEG) 流，
    覆盖绝大多数截图/流程图类 PDF
  - MD5 去重：同一张图在多页重复出现只保留一份
  - 质量过滤：过滤装饰性小图（按最小字节数/最小宽高）

用法：
  python extract_pdf_images.py 需求.pdf
  python extract_pdf_images.py 需求.pdf --out ./figures --min-width 300 --min-height 200
  python extract_pdf_images.py 需求.pdf --dump-manifest manifest.json

输出：
  <out>/img-001.jpg ...   提取出的图片
  <out>/manifest.json     每张图的来源、尺寸、字节数、MD5（便于追溯）
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys


# ---------- JPEG 尺寸解析（降级后端用，标准库即可） ----------
def jpeg_size(data):
    """从 JPEG 字节流读取宽高；解析失败返回 (0, 0)。"""
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    return 0, 0


def png_size(data):
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return 0, 0


def image_size(data):
    if data[:3] == b"\xff\xd8\xff":
        return jpeg_size(data)
    return png_size(data)


# ---------- 后端 A：PyMuPDF（精确，需 pip install pymupdf） ----------
def extract_with_pymupdf(path):
    import fitz  # noqa: F401  (pymupdf)
    doc = fitz.open(path)
    out = []
    for pno in range(len(doc)):
        for img in doc.get_page_images(pno, full=True):
            xref = img[0]
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            if not info or not info.get("image"):
                continue
            out.append({"bytes": info["image"], "ext": info.get("ext", "png"),
                        "page": pno + 1, "source": "xref:%d" % xref})
    doc.close()
    return out, "pymupdf"


# ---------- 后端 B：标准库扫 DCTDecode 流（零依赖） ----------
_STREAM = re.compile(rb"stream\r?\n")


def extract_with_stdlib(path):
    data = open(path, "rb").read()
    out = []
    for m in _STREAM.finditer(data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        head = data[max(0, m.start() - 2000):m.start()]
        # 只收图像对象里的 JPEG（DCTDecode）；其余编码（Flate 原始位图）跳过
        if b"/Image" not in head or b"DCTDecode" not in head:
            continue
        blob = data[start:end]
        # 去掉流尾可能存在的 EOL，并校验 JPEG 完整性
        blob = blob.rstrip(b"\r\n")
        if not (blob.startswith(b"\xff\xd8") and blob.rstrip().endswith(b"\xff\xd9")):
            continue
        out.append({"bytes": blob, "ext": "jpg", "page": None,
                    "source": "stream-dct"})
    return out, "stdlib"


def choose_backend():
    """优先 PyMuPDF；不可用时降级，并把降级信息打到 stderr（不污染 stdout）。"""
    try:
        import fitz  # noqa: F401
        return "pymupdf"
    except ImportError:
        sys.stderr.write(
            "[提示] 未安装 PyMuPDF，改用标准库降级模式：\n"
            "       仅能提取 JPEG(DCTDecode) 内嵌图，PNG/Flate 位图会漏。\n"
            "       需要全格式提取请执行：pip install pymupdf\n\n")
        return "stdlib"


def main():
    ap = argparse.ArgumentParser(description="从需求 PDF 提取内嵌图片（xref + MD5 去重 + 质量过滤）")
    ap.add_argument("pdf", help="输入 PDF 路径")
    ap.add_argument("--out", default="pdf-images", help="输出目录，默认 ./pdf-images")
    ap.add_argument("--min-width", type=int, default=200, help="最小宽度像素，默认 200")
    ap.add_argument("--min-height", type=int, default=150, help="最小高度像素，默认 150")
    ap.add_argument("--min-bytes", type=int, default=3072, help="最小字节数，默认 3072（约 3KB）")
    ap.add_argument("--no-filter", action="store_true", help="关闭质量过滤，保留全部图片")
    ap.add_argument("--dump-manifest", default="", help="把 manifest 另存到指定路径")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        raise SystemExit("找不到 PDF：%s" % args.pdf)

    backend = choose_backend()
    raw, used = (extract_with_pymupdf if backend == "pymupdf" else extract_with_stdlib)(args.pdf)

    os.makedirs(args.out, exist_ok=True)
    seen, kept, skipped_dup, skipped_quality = {}, [], 0, []

    for item in raw:
        blob = item["bytes"]
        digest = hashlib.md5(blob).hexdigest()
        if digest in seen:
            skipped_dup += 1
            continue
        w, h = image_size(blob)
        if not args.no_filter and (len(blob) < args.min_bytes
                                   or w < args.min_width or h < args.min_height):
            skipped_quality.append((w, h, len(blob)))
            continue
        seen[digest] = True
        idx = len(kept) + 1
        fname = "img-%03d.%s" % (idx, item["ext"])
        with open(os.path.join(args.out, fname), "wb") as f:
            f.write(blob)
        kept.append({"file": fname, "page": item["page"], "source": item["source"],
                     "width": w, "height": h, "bytes": len(blob), "md5": digest})

    manifest = {"pdf": os.path.abspath(args.pdf), "backend": used,
                "found": len(raw), "kept": len(kept),
                "dropped_duplicate": skipped_dup,
                "dropped_low_quality": len(skipped_quality),
                "images": kept}
    mpath = args.dump_manifest or os.path.join(args.out, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("后端：%s" % ("PyMuPDF(xref)" if used == "pymupdf" else "标准库(JPEG 流扫描)"))
    print("发现 %d 张 → 保留 %d 张（去重丢弃 %d，质量过滤丢弃 %d）"
          % (len(raw), len(kept), skipped_dup, len(skipped_quality)))
    for k in kept:
        print("  %-14s %4dx%-4d %7d B  第 %s 页  %s"
              % (k["file"], k["width"], k["height"], k["bytes"],
                 k["page"] or "?", k["source"]))
    print("manifest：%s" % mpath)
    if not kept:
        print("\n没有可用图片。若文档确有配图，尝试：pip install pymupdf 后重跑。")


if __name__ == "__main__":
    main()
