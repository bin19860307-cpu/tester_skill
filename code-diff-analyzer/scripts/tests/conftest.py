# -*- coding: utf-8 -*-
"""
conftest.py — pytest 夹具

为 code-diff-analyzer 的脚本提供**合成工作区**，使测试不依赖真实业务数据
（真实数据在 d:/workbuddy/测试日常/.workbuddy/diff-analytics，会被日常分析不断改写，
不适合做断言基线）。

合成工作区刻意复刻了 2026-09-18 体检发现缺陷时的**关键特征**：
  · 版本号三处写法不一致（service_metrics 带前缀 / version_bugs 裸号 / version_chain 带前缀）
  · file_history 只写了部分文件（非确定性丢失）
  · file_history 里混入输入产物 `*_tagdiff.txt`
  · 报告 HTML 的变更总览表用聚合通配写法（不可还原）
"""
import json
import os
import sys

import pytest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


@pytest.fixture
def workspace(tmp_path):
    """构造一个含缺陷特征的合成工作区，返回 (workspace_root, analytics_root, report_root)。"""
    ws = str(tmp_path)
    ar = os.path.join(ws, ".workbuddy", "diff-analytics")
    rr = os.path.join(ws, "report", "code-diff")
    svc = os.path.join(ar, "demo-svc")
    os.makedirs(svc, exist_ok=True)
    os.makedirs(os.path.join(rr, "demo-svc"), exist_ok=True)

    # ---- service_metrics：版本号带 business- 前缀；只声明 files_changed 数量 ----
    _w(os.path.join(svc, "service_metrics.json"), {
        "service": "demo-svc", "schema_version": "1.0",
        "records": [
            {
                "version_from": "business-5.3.0.1", "version_to": "business-5.3.0.2",
                "direction": "forward", "analysis_date": "2026-09-10",
                "metrics": {"files_changed": 3, "lines_added": 120, "lines_removed": 40,
                            "high_risk": 1, "medium_risk": 1, "low_risk": 1,
                            "risk_score": 15},
                "modules": [
                    {"name": "auth 权限校验重构", "files": 1, "risk": "high"},
                    {"name": "导出格式 ExportTask", "files": 1, "risk": "medium"},
                    {"name": "版本号 pom", "files": 1, "risk": "low"},
                ],
                "detections": {"data_format_change": True, "version_rollback": False,
                               "sensitive_info": False, "test_sync_needed": True,
                               "circular_dependency": False},
                "files": ["src/main/java/AuthController.java",
                          "src/main/java/ExportTaskServiceImpl.java", "pom.xml"],
            },
            {
                "version_from": "business-5.3.0.3", "version_to": "business-5.3.0.4",
                "direction": "forward", "analysis_date": "2026-09-18",
                "metrics": {"files_changed": 2, "lines_added": 60, "lines_removed": 20,
                            "high_risk": 1, "medium_risk": 0, "low_risk": 1,
                            "risk_score": 11},
                "modules": [
                    {"name": "统计口径 DorisStatisticServiceImpl(已发布维度)", "files": 1, "risk": "high"},
                    {"name": "版本号 pom", "files": 1, "risk": "low"},
                ],
                "detections": {"data_format_change": False, "version_rollback": False,
                               "sensitive_info": False, "test_sync_needed": False,
                               "circular_dependency": False},
                "files": ["src/main/java/DorisStatisticServiceImpl.java", "pom.xml"],
            },
        ],
    })

    # ---- version_chain：版本号带 business- 前缀 ----
    _w(os.path.join(svc, "version_chain.json"), {
        "service": "demo-svc", "schema_version": "1.0",
        "versions": [
            {"version": "business-5.3.0.2", "date": "2026-09-10", "parent": "business-5.3.0.1"},
            {"version": "business-5.3.0.4", "date": "2026-09-18", "parent": "business-5.3.0.3"},
        ],
    })

    # ---- version_bugs：版本号**裸号**（这就是 P0-1 的根因）----
    _w(os.path.join(svc, "version_bugs.json"), {
        "service": "demo-svc", "schema_version": "1.1",
        "version_series": "5.3", "source_xlsx": "bug.xlsx",
        "imported_at": "2026-09-18 09:17:53",
        "bugs": [
            {"bug_id": "1001", "title": "权限校验异常", "severity": "high", "status": "closed",
             "module": None, "found_in_version": "5.3.0.2", "fixed_in_version": "5.3.0.3"},
            {"bug_id": "1002", "title": "导出合计行错", "severity": "medium", "status": "open",
             "module": None, "found_in_version": "5.3.0.2", "fixed_in_version": None},
            {"bug_id": "1003", "title": "统计维度已发布", "severity": "high", "status": "closed",
             "module": None, "found_in_version": "5.3.0.1", "fixed_in_version": "5.3.0.2"},
        ],
    })

    # ---- file_history：非确定性丢失（3 个文件只写了 1 条）+ 混入输入产物 ----
    _w(os.path.join(svc, "file_history.json"), {
        "service": "demo-svc", "schema_version": "1.0",
        "files": {
            "src/main/java/AuthController.java": {
                "change_count": 1, "appear_in": ["business-5.3.0.1→business-5.3.0.2"],
                "risk_history": ["high"], "change_types": ["modified"],
            },
            "demo-5.1.0.5_tagdiff.txt": {
                "change_count": 1, "appear_in": ["5.1.0.5→5.1.0.6"],
                "risk_history": ["low"], "change_types": ["modified"],
            },
        },
        "recent_changes": [],
    })

    # ---- 报告 HTML：变更总览表为聚合通配（不可还原）----
    report = os.path.join(rr, "demo-svc", "demo-svc_5.3.0.1_to_5.3.0.2_变更影响分析报告.html")
    with open(report, "w", encoding="utf-8") as f:
        f.write(
            "<html><body>"
            '<table class="overview-table"><thead><tr><th>文件</th><th>类型</th></tr></thead>'
            "<tbody><tr><td>views/home/* (33 文件)</td><td>修改</td></tr>"
            "<tr><td>src/a/AuthController.java</td><td>修改</td></tr></tbody></table>"
            "</body></html>")

    # ---- 另一个报告：可完整还原（无通配，行数 == files_changed）----
    report2 = os.path.join(rr, "demo-svc", "demo-svc_5.3.0.3_to_5.3.0.4_变更影响分析报告.html")
    with open(report2, "w", encoding="utf-8") as f:
        f.write(
            "<html><body>"
            '<table class="overview-table"><thead><tr><th>文件</th></tr></thead>'
            "<tbody><tr><td>DorisStatisticServiceImpl.java</td></tr>"
            "<tr><td>pom.xml</td></tr></tbody></table>"
            "</body></html>")

    # ---- 报告目录根部的临时产物（D7 应能发现）----
    for junk in ("temp_oe.txt", "_build_analytics.py"):
        with open(os.path.join(rr, junk), "w", encoding="utf-8") as f:
            f.write("x")

    return ws, ar, rr


@pytest.fixture
def svc_name():
    return "demo-svc"
