# -*- coding: utf-8 -*-
"""HTML 注释泄漏防护回归（2026-09-20）。

背景：模板指导性注释里出现「（<-- X_START/END -->）」嵌套写法时，
浏览器在嵌套的 ``-->`` 处提前终止注释，剩余文本（如「）。 -->」）以
裸文本泄漏到页面。2026-09-18 修过一次已生成报告，但**模板源头漏修**，
2026-09-20 从模板重建报告时复现（本轮 portal-backend 5.3.0.4→5.3.0.5）。

本文件锁死三件事：
  1. 模板 html-report-template.html 必须无注释泄漏；
  2. _common.scan_comment_leaks 能识别嵌套标记 / --!> 两种隐患，干净 HTML 不误报；
  3. _common.safe_write_report 对泄漏 HTML 拒绝落盘（防带病交付）。
"""
import os

import pytest

from _common import scan_comment_leaks, safe_write_report

TEMPLATE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "references", "html-report-template.html"
)

# 泄漏形态：注释体内嵌套「<-- X -->」标记写法（浏览器在第一个 --> 处终止注释）
BAD_NESTED = '<div><!-- 生成报告后运行：重复注入自动替换（<-- X_START/END -->）。 --><span>正文</span></div>'
# 泄漏形态：--!> 提前终止
BAD_LONG_DASH = '<div><!-- a --!> b --><span>正文</span></div>'
# 干净写法：标记对用文字表述，注释体内不含 --
GOOD = '<div><!-- 生成报告后运行：重复注入自动替换（X_START/END 标记对）。 --><!-- X_SECTION --><span>正文</span></div>'


class TestScanCommentLeaks:
    def test_template_is_clean(self):
        """模板源头必须干净（2026-09-20 曾漏修导致泄漏复现）。"""
        with open(TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        assert scan_comment_leaks(html) == []

    def test_detects_nested_marker(self):
        leaks = scan_comment_leaks(BAD_NESTED)
        assert len(leaks) == 1
        assert "X_START/END" in leaks[0]

    def test_detects_long_dash_terminator(self):
        assert len(scan_comment_leaks(BAD_LONG_DASH)) == 1

    def test_detects_comment_inside_comment(self):
        assert len(scan_comment_leaks("<!-- a <!-- b --> c -->")) == 1

    def test_clean_html_passes(self):
        assert scan_comment_leaks(GOOD) == []

    def test_command_line_args_in_comment_are_safe(self):
        """注释内的命令行参数（--report 等）不含 -->，不应误报。"""
        assert scan_comment_leaks("<!-- 运行：python scripts/x.py --report a.html -->") == []


class TestSafeWriteReport:
    def test_refuses_leaky_html(self, tmp_path):
        """发现泄漏必须拒绝落盘并 SystemExit（防带病交付）。"""
        p = tmp_path / "r.html"
        with pytest.raises(SystemExit):
            safe_write_report(str(p), BAD_NESTED)
        assert not p.exists()

    def test_refuses_long_dash_html(self, tmp_path):
        p = tmp_path / "r.html"
        with pytest.raises(SystemExit):
            safe_write_report(str(p), BAD_LONG_DASH)
        assert not p.exists()

    def test_writes_clean_html(self, tmp_path):
        p = tmp_path / "r.html"
        safe_write_report(str(p), GOOD)
        with open(str(p), encoding="utf-8") as f:
            assert f.read() == GOOD
