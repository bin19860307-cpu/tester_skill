# -*- coding: utf-8 -*-
"""doctor.py 测试 —— 重点是 D8「分数可复现性」。

D8 的价值在于抓一类**沉默失真**：评分代码改了、数据没重算。
此时 D5「有没有血缘标记」依然全绿（标记是上一轮重算写的），
但报告里的分数已经和代码不一致。没有 D8 就只能靠人肉发现。
"""
import json
import os

import pytest

import doctor
import sync_analytics as sa


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _metrics_path(ar, svc="demo-svc"):
    return os.path.join(ar, svc, "service_metrics.json")


class TestD8Reproducible:
    def test_clean_after_rescore(self, workspace):
        """重算之后 D8 必须干净（这是「确定性」的正向断言）。"""
        ws, ar, rr = workspace
        sa.sync_service("demo-svc", ar)
        d8 = doctor.check_d8_reproducible("demo-svc", ar)
        assert d8["issues"] == [], d8["issues"]
        assert d8["detail"]["records_with_score"] == 2
        assert d8["detail"]["stale"] == 0

    def test_detects_score_drift(self, workspace):
        """评分代码变更后数据未重算 → 必须报出来（本次收窄 CORE_PATTERNS 就是这个场景）。"""
        ws, ar, rr = workspace
        sa.sync_service("demo-svc", ar)
        p = _metrics_path(ar)
        doc = _load(p)
        doc["records"][0]["metrics"]["risk_score"] = 99.0   # 模拟「手改 / 口径已变」
        _save(p, doc)
        d8 = doctor.check_d8_reproducible("demo-svc", ar)
        assert any("与当前评分代码不一致" in i for i in d8["issues"])
        assert d8["detail"]["stale"] == 1

    def test_detects_tampered_rating(self, workspace):
        """人工改等级同样要被抓出来（评级必须是规则算的，不是人写的）。"""
        ws, ar, rr = workspace
        sa.sync_service("demo-svc", ar)
        p = _metrics_path(ar)
        doc = _load(p)
        doc["records"][0]["rating"] = {"code": "low", "level": "🟢 低", "reasons": []}
        _save(p, doc)
        d8 = doctor.check_d8_reproducible("demo-svc", ar)
        assert any("rating 与 rate_change() 重算不一致" in i for i in d8["issues"])

    def test_detects_missing_legacy_archive(self, workspace):
        """旧公式值被静默覆盖（无留档）→ 审计链断了，要报。"""
        ws, ar, rr = workspace
        sa.sync_service("demo-svc", ar)
        p = _metrics_path(ar)
        doc = _load(p)
        for r in doc["records"]:
            r["metrics"].pop("risk_score_legacy", None)
        _save(p, doc)
        d8 = doctor.check_d8_reproducible("demo-svc", ar)
        assert any("risk_score_legacy" in i for i in d8["issues"])

    def test_detects_polluted_trend_mode(self, workspace):
        """趋势口径字段被改成 enhanced → 跨版本连线会失真，必须报。"""
        ws, ar, rr = workspace
        sa.sync_service("demo-svc", ar)
        p = _metrics_path(ar)
        doc = _load(p)
        doc["records"][0]["metrics"]["risk_score_mode"] = "enhanced"
        _save(p, doc)
        d8 = doctor.check_d8_reproducible("demo-svc", ar)
        assert any("risk_score_mode 不是 static" in i for i in d8["issues"])


class TestD2VersionKeys:
    def test_reports_inconsistency_with_variants(self, workspace):
        """夹具刻意让 metrics 带 business- 前缀、bugs 用裸号 → D2 必须报出两种写法。"""
        ws, ar, rr = workspace
        d2 = doctor.check_d2_version_keys("demo-svc", ar)
        assert d2["issues"], "应报出版本键写法不一致"
        assert any("5.3.0.2" in i for i in d2["issues"])


class TestD4CrossReference:
    def test_not_required_without_bugs(self, workspace):
        """没有 version_bugs.json 的服务不该被判定为「cross_reference 缺失」。"""
        ws, ar, rr = workspace
        os.remove(os.path.join(ar, "demo-svc", "version_bugs.json"))
        cr = os.path.join(ar, "demo-svc", "cross_reference.json")
        if os.path.isfile(cr):
            os.remove(cr)
        d4 = doctor.check_d4_cross_reference("demo-svc", ar)
        assert d4["issues"] == []

    def test_mapping_count_must_match_records(self, workspace):
        """mapping 数 != 记录数 → 有记录没被消费，join 没接通。"""
        ws, ar, rr = workspace
        import bug_correlate as bc
        bugs = _load(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        d4 = doctor.check_d4_cross_reference("demo-svc", ar)
        assert not any("映射" in i or "join" in i for i in d4["issues"]), d4["issues"]
        # 删掉一条 mapping 模拟「记录未被消费」
        p = os.path.join(ar, "demo-svc", "cross_reference.json")
        doc = _load(p)
        doc["mappings"].pop()
        _save(p, doc)
        d4 = doctor.check_d4_cross_reference("demo-svc", ar)
        assert any("!= service_metrics 记录数" in i for i in d4["issues"])


class TestD7Hygiene:
    def test_finds_root_level_temp_files(self, workspace):
        """报告根目录（不属于任何服务子目录）的临时产物也要能发现。"""
        ws, ar, rr = workspace
        hits = doctor.scan_temp_files(rr, "demo-svc")
        names = {os.path.basename(h) for h in hits}
        assert "temp_oe.txt" in names
        assert "_build_analytics.py" in names
