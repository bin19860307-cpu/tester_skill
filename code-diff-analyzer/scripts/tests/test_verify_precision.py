# -*- coding: utf-8 -*-
"""verify_precision.py 单元测试 —— 分级结论 + Wilson 区间（缺口③a，2026-09-30）。

旧版行为：样本 <30 一刀切拒答 —— 阈值无依据，且把 10-29 个样本能看出的
方向性信号也扔掉了。现改三级：
  full（≥30）完整建议 / temp（10-29）带 Wilson 区间的临时结论 / none（<10）只诊断。
"""
import pytest

import verify_precision as vp
from verify_precision import (wilson_interval, _conclusion_level,
                              suggest_weights, bucket_calibration,
                              MIN_SAMPLES_FOR_CALIBRATION,
                              MIN_SAMPLES_TEMP)


class TestWilsonInterval:
    def test_known_values(self):
        # 8/10 = 80% → Wilson 95% 约 [49%, 94%]（教科书值附近）
        lo, hi = wilson_interval(8, 10)
        assert lo is not None and hi is not None
        assert lo < 0.80 < hi
        assert 0.40 <= lo <= 0.55
        assert 0.90 <= hi <= 0.99

    def test_zero_denominator(self):
        assert wilson_interval(0, 0) == (None, None)

    def test_interval_contains_point_estimate(self):
        for k, n in [(1, 3), (3, 5), (7, 20), (25, 30), (0, 12)]:
            lo, hi = wilson_interval(k, n)
            p = k / n
            assert lo <= p <= hi, f"{k}/{n}: [{lo},{hi}] 不含点估计 {p}"

    def test_small_sample_wide_interval(self):
        """3/5 与 30/50 同为 60%：小样本区间必须显著更宽（诚实表达）。"""
        lo_s, hi_s = wilson_interval(3, 5)
        lo_l, hi_l = wilson_interval(30, 50)
        assert (hi_s - lo_s) > (hi_l - lo_l)

    def test_bounds_clamped(self):
        lo, hi = wilson_interval(0, 4)
        assert lo == 0.0
        lo, hi = wilson_interval(9, 9)
        assert hi == 1.0


class TestConclusionLevel:
    def test_three_levels(self):
        assert _conclusion_level(0) == "none"
        assert _conclusion_level(9) == "none"
        assert _conclusion_level(10) == "temp"
        assert _conclusion_level(29) == "temp"
        assert _conclusion_level(30) == "full"

    def test_thresholds_consistent(self):
        assert MIN_SAMPLES_TEMP < MIN_SAMPLES_FOR_CALIBRATION


def _mk_agg(n, high_total=10, high_bug=3):
    """构造 aggregate() 形状的桩：只填 suggest_weights 实际消费的字段。"""
    return {
        "samples": n,
        "changes_with_bug": max(n // 3, 0),
        "bug_rate": 0.3 if n else None,
        "high_risk_total": high_total,
        "high_risk_with_bug": high_bug,
        "high_risk_hit_rate": round(high_bug / high_total, 3) if high_total else None,
        "detection_precision": {
            "data_format_change": {"label": "数据格式变更", "hit_total": 5,
                                   "hit_with_bug": 1, "precision": 0.2,
                                   "support_enough": True},
        },
        "samples_enough": n >= MIN_SAMPLES_FOR_CALIBRATION,
    }


CALIB_OK = {"monotonic": True, "inversions": 0}
CALIB_BAD = {"monotonic": False, "inversions": 2}


class TestSuggestWeightsGraded:
    def test_none_level_refuses(self):
        s = suggest_weights(_mk_agg(5), CALIB_OK)
        assert s["available"] is False
        assert s["level"] == "none"
        assert "只提供诊断" in s["reason"]

    def test_temp_level_gives_directional_advice(self):
        """10-29 样本：给建议但显式声明临时性 + 提示区间。"""
        s = suggest_weights(_mk_agg(15), CALIB_OK)
        assert s["available"] is True
        assert s["level"] == "temp"
        assert "临时结论" in s["note"]
        assert "不得据此做最终权重调整" in s["note"]
        assert s["recommendations"], "临时级别也应有方向性建议"
        #Wilson 区间必须出现在理由里
        assert any("Wilson" in r["reason"] for r in s["recommendations"])

    def test_full_level_unchanged_behavior(self):
        s = suggest_weights(_mk_agg(40), CALIB_OK)
        assert s["available"] is True
        assert s["level"] == "full"
        assert "临时" not in s["note"]

    def test_low_precision_flagged_with_ci(self):
        """精度 0.2 + Wilson 区间下限仍低 → review 建议必须带区间。"""
        s = suggest_weights(_mk_agg(20), CALIB_OK)
        review = [r for r in s["recommendations"] if r["action"] == "review"]
        assert review and "Wilson" in review[0]["reason"]

    def test_monotonic_failure_propagates(self):
        s = suggest_weights(_mk_agg(15), CALIB_BAD)
        assert "单调性未通过" in s["note"] or "重估" in s["note"]


class TestBucketCalibration:
    def test_buckets_carry_ci(self):
        samples = [{"risk_score": 50 + (i % 3) * 15, "has_bug": i % 2 == 0}
                   for i in range(12)]
        calib = bucket_calibration(samples)
        nonempty = [b for b in calib["buckets"] if b["n"] > 0]
        assert nonempty
        for b in nonempty:
            assert b["bug_rate_ci"] is not None
            lo, hi = b["bug_rate_ci"]
            assert 0.0 <= lo <= b["bug_rate"] <= hi <= 1.0

    def test_empty_buckets_have_no_ci(self):
        calib = bucket_calibration([])
        for b in calib["buckets"]:
            assert b["n"] == 0
            assert b.get("bug_rate_ci") is None
