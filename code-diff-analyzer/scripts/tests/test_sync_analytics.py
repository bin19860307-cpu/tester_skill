# -*- coding: utf-8 -*-
"""sync_analytics.py 测试 —— file_history 确定性重建 + 自检 + 回填严格性。"""
import json
import os

import pytest

import sync_analytics as sa


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestCheckFileHistory:
    def test_detects_junk_entry(self, workspace):
        """核心断言：输入产物（tagdiff.txt）必须被识别为脏项。"""
        ws, ar, rr = workspace
        r = sa.check_file_history("demo-svc", ar)
        assert any("tagdiff" in j for j in r["junk"])
        assert any("C3" in i for i in r["issues"])

    def test_detects_missing_entries(self, workspace):
        """18→1 / 45→2 那类丢失必须被检出（否则它就会一直潜伏）。"""
        ws, ar, rr = workspace
        r = sa.check_file_history("demo-svc", ar)
        # 5.3.0.1→5.3.0.2 声明 3 个文件，file_history 只有 1 条
        assert any("C4" in i and "条目数不符" in i for i in r["issues"])

    def test_unverifiable_ranges_flagged(self, workspace):
        ws, ar, rr = workspace
        r = sa.check_file_history("demo-svc", ar)
        assert r["expected"] > 0 or r["unverifiable"]

    def test_missing_file_reported(self, tmp_path):
        r = sa.check_file_history("nope", str(tmp_path))
        assert any("C0" in i for i in r["issues"])


class TestRebuild:
    def test_rebuild_writes_all_declared_files(self, workspace):
        """核心断言：3 个声明文件必须全部写入（原实现只写 1 条）。"""
        ws, ar, rr = workspace
        _doc, rep = sa.rebuild_file_history("demo-svc", ar)
        fh = _read(os.path.join(ar, "demo-svc", "file_history.json"))["files"]
        for p in ("src/main/java/AuthController.java",
                  "src/main/java/ExportTaskServiceImpl.java", "pom.xml"):
            assert p in fh, f"缺失 {p}"
        assert rep["rebuilt_entries"] == 5      # 3 + 2

    def test_junk_purged(self, workspace):
        """输入产物永远不是变更代码 → 与区间无关，无条件清除。"""
        ws, ar, rr = workspace
        _doc, rep = sa.rebuild_file_history("demo-svc", ar)
        fh = _read(os.path.join(ar, "demo-svc", "file_history.json"))["files"]
        assert "demo-5.1.0.5_tagdiff.txt" not in fh
        assert rep["purged_junk"] == ["demo-5.1.0.5_tagdiff.txt"]

    def test_files_wrapper_present(self, workspace):
        """早期漏 `files` 包裹层会让 quant_jit_risk 的读取失效。"""
        ws, ar, rr = workspace
        doc, _rep = sa.rebuild_file_history("demo-svc", ar)
        assert "files" in doc and isinstance(doc["files"], dict)
        assert doc["service"] == "demo-svc"
        assert doc["schema_version"]

    def test_idempotent(self, workspace):
        """幂等：重复重建结果恒定（否则每次分析都会把 change_count 叠加）。"""
        ws, ar, rr = workspace
        d1, _ = sa.rebuild_file_history("demo-svc", ar)
        d2, _ = sa.rebuild_file_history("demo-svc", ar)
        d1.pop("synced_at", None)
        d2.pop("synced_at", None)
        assert d1 == d2

    def test_preserves_unverifiable_ranges(self, workspace):
        """缺 `files` 清单的历史区间不得被破坏性重建（否则会丢已有数据）。"""
        ws, ar, rr = workspace
        svc = os.path.join(ar, "demo-svc")
        # 造一个没有 files 清单的记录，但 file_history 里已有它的条目
        sm = _read(os.path.join(svc, "service_metrics.json"))
        sm["records"].append({
            "version_from": "5.3.0.4", "version_to": "5.3.0.5",
            "analysis_date": "2026-09-19",
            "metrics": {"files_changed": 9, "lines_added": 5, "lines_removed": 1},
        })
        with open(os.path.join(svc, "service_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(sm, f, ensure_ascii=False)
        fh = _read(os.path.join(svc, "file_history.json"))
        fh["files"]["legacy/KeepMe.java"] = {
            "change_count": 1, "appear_in": ["5.3.0.4→5.3.0.5"],
            "risk_history": ["low"], "change_types": ["modified"]}
        with open(os.path.join(svc, "file_history.json"), "w", encoding="utf-8") as f:
            json.dump(fh, f, ensure_ascii=False)

        sa.rebuild_file_history("demo-svc", ar)
        after = _read(os.path.join(svc, "file_history.json"))["files"]
        assert "legacy/KeepMe.java" in after, "无 files 清单的区间原条目必须保留"

    def test_change_count_consistent_with_appear_in(self, workspace):
        ws, ar, rr = workspace
        sa.rebuild_file_history("demo-svc", ar)
        fh = _read(os.path.join(ar, "demo-svc", "file_history.json"))["files"]
        for path, e in fh.items():
            assert e["change_count"] == len(e["appear_in"]), f"{path} change_count 不一致"


class TestBackfillStrictness:
    def test_refuses_lossy_report(self, workspace):
        """报告是聚合摘要（views/home/* (33 文件)）→ 必须拒绝回填，绝不猜文件名。"""
        ws, ar, rr = workspace
        svc = os.path.join(ar, "demo-svc")
        sm = _read(os.path.join(svc, "service_metrics.json"))
        # 清掉 files 清单，迫使走回填
        sm["records"][0].pop("files", None)
        sm["records"][0]["metrics"]["files_changed"] = 12
        with open(os.path.join(svc, "service_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(sm, f, ensure_ascii=False)

        r = sa.backfill_files_from_reports("demo-svc", ar, rr)
        reasons = " ".join(u["reason"] for u in r["unrecoverable"])
        assert "聚合摘要" in reasons
        assert not any(b["range"].startswith("5.3.0.1") for b in r["backfilled"])

    def test_accepts_exact_report(self, workspace):
        """无通配且行数 == files_changed 的报告才回填。"""
        ws, ar, rr = workspace
        svc = os.path.join(ar, "demo-svc")
        sm = _read(os.path.join(svc, "service_metrics.json"))
        sm["records"][1].pop("files", None)     # 5.3.0.3→5.3.0.4，files_changed=2
        with open(os.path.join(svc, "service_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(sm, f, ensure_ascii=False)

        r = sa.backfill_files_from_reports("demo-svc", ar, rr)
        ok = [b for b in r["backfilled"] if b["range"] == "5.3.0.3→5.3.0.4"]
        assert ok and ok[0]["files"] == 2

    def test_extract_report_file_list(self, workspace):
        ws, ar, rr = workspace
        p = os.path.join(rr, "demo-svc", "demo-svc_5.3.0.3_to_5.3.0.4_变更影响分析报告.html")
        ex = sa.extract_report_file_list(p)
        assert ex["lossy"] is False
        assert ex["files"] == ["DorisStatisticServiceImpl.java", "pom.xml"]

    def test_lossy_marker_detected(self, workspace):
        ws, ar, rr = workspace
        p = os.path.join(rr, "demo-svc", "demo-svc_5.3.0.1_to_5.3.0.2_变更影响分析报告.html")
        ex = sa.extract_report_file_list(p)
        assert ex["lossy"] is True
        assert ex["lossy_reason"]


class TestNormalizeVersionFields:
    def test_storage_layer_normalization(self, workspace):
        """核心断言：存储层归一后，同一版本在各文件里只剩一种写法。"""
        ws, ar, rr = workspace
        sa.normalize_version_fields("demo-svc", ar)
        svc = os.path.join(ar, "demo-svc")
        sm = _read(os.path.join(svc, "service_metrics.json"))
        for r in sm["records"]:
            assert r["version_from"] == "5.3.0.1" or r["version_from"] == "5.3.0.3"
            assert r["version_to"] in ("5.3.0.2", "5.3.0.4")
        vb = _read(os.path.join(svc, "version_bugs.json"))
        for b in vb["bugs"]:
            assert b["found_in_version"] in ("5.3.0.1", "5.3.0.2")
        vc = _read(os.path.join(svc, "version_chain.json"))
        assert all(v["version"] == "5.3.0.2" or v["version"] == "5.3.0.4"
                   for v in vc["versions"])

    def test_raw_values_preserved(self, workspace):
        """原文必须保留在 *_raw，便于回溯。"""
        ws, ar, rr = workspace
        sa.normalize_version_fields("demo-svc", ar)
        sm = _read(os.path.join(ar, "demo-svc", "service_metrics.json"))
        assert sm["records"][0]["version_to_raw"] == "business-5.3.0.2"

    def test_idempotent(self, workspace):
        ws, ar, rr = workspace
        a = sa.normalize_version_fields("demo-svc", ar)
        b = sa.normalize_version_fields("demo-svc", ar)
        assert b["total"] == 0, "第二次运行不应再有改动（幂等）"


class TestRescore:
    def test_risk_score_becomes_script_produced(self, workspace):
        """核心断言：risk_score 必须带脚本血缘（原先是 LLM 手填）。"""
        ws, ar, rr = workspace
        sa.rescore_records("demo-svc", ar)
        sm = _read(os.path.join(ar, "demo-svc", "service_metrics.json"))
        for r in sm["records"]:
            m = r["metrics"]
            assert m["risk_score_source"].startswith("script:")
            assert m["risk_score_mode"] == "static"

    def test_legacy_preserved_but_not_overwritten(self, workspace):
        """旧公式值留档；重复运行不得把新值当旧值（曾出现 legacy==risk_score）。"""
        ws, ar, rr = workspace
        sa.rescore_records("demo-svc", ar)
        sa.rescore_records("demo-svc", ar)
        sm = _read(os.path.join(ar, "demo-svc", "service_metrics.json"))
        for r in sm["records"]:
            assert r["metrics"]["risk_score_legacy"] in (15, 11)

    def test_rating_attached(self, workspace):
        ws, ar, rr = workspace
        sa.rescore_records("demo-svc", ar)
        sm = _read(os.path.join(ar, "demo-svc", "service_metrics.json"))
        for r in sm["records"]:
            assert r["rating"]["code"] in ("high", "medium", "low")
            assert r["rating"]["rules_version"]

    def test_deterministic(self, workspace):
        ws, ar, rr = workspace
        sa.rescore_records("demo-svc", ar)
        a = [r["metrics"]["risk_score"] for r in
             _read(os.path.join(ar, "demo-svc", "service_metrics.json"))["records"]]
        sa.rescore_records("demo-svc", ar)
        b = [r["metrics"]["risk_score"] for r in
             _read(os.path.join(ar, "demo-svc", "service_metrics.json"))["records"]]
        assert a == b
