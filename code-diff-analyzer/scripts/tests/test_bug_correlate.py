# -*- coding: utf-8 -*-
"""bug_correlate.py 映射引擎测试 —— 锁定「版本键归一 + metrics 驱动 + 精度闭环」。

这是本次修复的**核心回归防线**：原实现产出 49 个 Bug 有效关联 0 个、
change_to_bug_ratio 全 null、high_risk_hit_rate 全代码库查无实现。
"""
import json
import os

import pytest

import bug_correlate as bc


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestMappingEngineBasics:
    def test_mapping_count_equals_records(self, workspace):
        """核心断言：mapping 条数必须等于 service_metrics 记录数（不再产出空壳行）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        st = bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        assert st["mappings"] == st["records_total"] == 2

    def test_cross_form_version_join_works(self, workspace):
        """核心断言：Bug 裸号 5.3.0.2 必须能关联到 business-5.3.0.2 的变更（原实现为 0/49）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        by_range = {m["version_range"]: m for m in cr["mappings"]}
        assert "5.3.0.1→5.3.0.2" in by_range
        m = by_range["5.3.0.1→5.3.0.2"]
        # 「本版本发现」= found_in_version 归一后 == 区间右端
        assert set(m["bugs_found_in_version"]) == {"1001", "1002"}
        # 「本区间修复」= fixed_in_version 归一后 == 区间右端（bug 1003 在父版本发现、本区间修掉）
        assert m["bugs_fixed_in_version"] == ["1003"]

    def test_bug_fixed_outside_any_interval_is_not_attributed(self, workspace):
        """修复版本不在任何受训区间右端时，不得硬塞给相邻区间（宁缺勿假）。

        夹具里 bug 1001 的 fixed_in_version = 5.3.0.3，而 records 只有
        5.3.0.1→5.3.0.2 与 5.3.0.3→5.3.0.4，没有以 5.3.0.3 为右端的区间 →
        两条 mapping 的 bugs_fixed_in_version 都不应包含 1001。
        """
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        assert all("1001" not in m["bugs_fixed_in_version"] for m in cr["mappings"])

    def test_change_to_bug_ratio_not_null(self, workspace):
        """核心断言：比值必须算得出（原实现全 null）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        assert all(m["change_to_bug_ratio"] is not None for m in cr["mappings"])

    def test_ratio_math(self, workspace):
        """ratio = 本版本发现的 Bug 数 / files_changed。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        m = [x for x in cr["mappings"] if x["version_range"] == "5.3.0.1→5.3.0.2"][0]
        assert m["files_changed"] == 3
        assert m["change_to_bug_ratio"] == pytest.approx(2 / 3, abs=1e-4)

    def test_parent_bugs_are_context_not_numerator(self, workspace):
        """父版本 Bug 只作上下文，**不得**并入本区间分子（否则虚增比值）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        m = [x for x in cr["mappings"] if x["version_range"] == "5.3.0.1→5.3.0.2"][0]
        # bug 1003 的 found_in_version = 5.3.0.1（父版本）
        assert "1003" not in m["bugs_found_in_version"]
        assert m["bugs_from_parent_version"] == ["1003"]


class TestHighRiskHitRate:
    def test_metric_is_computed(self, workspace):
        """high_risk_hit_rate 原先只在 SKILL.md:950 有定义、代码里查无实现。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        st = bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        assert st["high_risk_total"] > 0
        assert st["high_risk_hit_rate"] is not None

    def test_high_risk_changes_with_bugs_populated(self, workspace):
        """原实现是硬编码 []，从未实现。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        for m in cr["mappings"]:
            assert isinstance(m["high_risk_changes_with_bugs"], list)
            # 计数类字段必须与明细自洽（防止再次出现「明细空、计数非空」）
            assert m["high_risk_total"] == len(m["high_risk_changes_with_bugs"])
            assert m["high_risk_with_bug"] == sum(
                1 for it in m["high_risk_changes_with_bugs"] if it["bug_ids"])
            assert m["high_risk_with_bug"] <= m["high_risk_total"]
            # 高风险项结构完整
            for it in m["high_risk_changes_with_bugs"]:
                assert it["risk"] == "high"
                assert "bug_ids" in it and "attribution" in it

    def test_module_data_missing_degrades_honestly(self, workspace):
        """Bug 模块列全空时，必须退化为「版本级归因」并显式标注，不伪装成精确匹配。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        assert all(b["module"] is None for b in bugs)      # 夹具刻意复刻该现状
        st = bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        assert st["module_data_missing"] is True
        assert st["attribution"] == "version"

    def test_module_matching_when_data_present(self, workspace):
        """有模块数据时走精确匹配（归因方式自动升级）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        for b in bugs:
            if b["bug_id"] == "1001":
                b["module"] = "auth"       # 与 modules[0].name「auth 权限校验重构」包含匹配
        st = bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        assert st["attribution"] == "module"
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        m = [x for x in cr["mappings"] if x["version_range"] == "5.3.0.1→5.3.0.2"][0]
        auth_it = [i for i in m["high_risk_changes_with_bugs"] if "auth" in str(i["module"])]
        assert auth_it and auth_it[0]["bug_ids"] == ["1001"]

    def test_no_high_risk_yields_null_not_zero(self, workspace):
        """无高风险变更项时诚实留空（None），不填 0 伪装成"精度 0%"。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        m = [x for x in cr["mappings"] if x["version_range"] == "5.3.0.3→5.3.0.4"][0]
        assert m["high_risk_total"] == 1
        assert m["high_risk_hit_rate"] == 0.0    # 有高风险项但无 Bug → 真实的 0


class TestDetectionPrecision:
    def test_hit_with_bug_reflects_real_attribution(self, workspace):
        """原实现里 hit_with_bug 被 join 断裂污染 → 会把"Bug 归属断了"误读成"检测不准"。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        m = [x for x in cr["mappings"] if x["version_range"] == "5.3.0.1→5.3.0.2"][0]
        dp = m["detection_precision"]
        # 该区间有 Bug 且 data_format_change 命中 → hit_with_bug 必须为 1
        assert dp["data_format_change"] == {"hit_with_bug": 1, "hit_total": 1}
        assert dp["test_sync_needed"] == {"hit_with_bug": 1, "hit_total": 1}
        # 未命中的检测项计数为 0
        assert dp["version_rollback"] == {"hit_with_bug": 0, "hit_total": 0}

    def test_commits_declared_unavailable(self, workspace):
        """service_metrics 根本没有 commit 列表 → 属结构性缺源，如实标注。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        for m in cr["mappings"]:
            assert m["commits_with_bugs"] is None
            assert m["commits_data_source"] == "unavailable"


class TestHealthChecks:
    def test_inconsistent_keys_detected(self, workspace):
        """体检应能报出「同一版本多种写法」（即缺陷根因）。"""
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        st = bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        vki = st["version_key_inconsistency"]
        assert vki, "应检测到 business- 前缀与裸号混用"
        assert "5.3.0.2" in vki
        # 不能只说「有 1 处不一致」——要能指出是哪两种写法、来自哪些文件，
        # 否则修复时无法定位根因（这正是第一次体检漏掉的东西）。
        entry = vki["5.3.0.2"]
        assert entry["raw_forms"] == ["5.3.0.2", "business-5.3.0.2"]
        assert "version_bugs.found_in_version" in entry["sources"]
        assert "service_metrics.version_to" in entry["sources"]

    def test_output_schema_marks_provenance(self, workspace):
        ws, ar, rr = workspace
        bugs = _read(os.path.join(ar, "demo-svc", "version_bugs.json"))["bugs"]
        bc.run_mapping_engine("demo-svc", ar, bugs, verbose=False)
        cr = _read(os.path.join(ar, "demo-svc", "cross_reference.json"))
        assert cr["source"].startswith("service_metrics")
        assert "norm_version" in cr["version_key_policy"]
        assert cr["schema_version"] == "1.1"
