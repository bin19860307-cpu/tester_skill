# -*- coding: utf-8 -*-
"""scoring.py 单元测试 —— 统一 risk_score 口径 + 可复现评级。

覆盖 2026-09-18 体检缺陷：
  P1-6 两套 risk_score 并存、且都没被脚本产出（grep risk_score scripts/*.py 零命中）
  P1-7 评级口径不可复现（Step 5 是伪代码，全靠 LLM 现场判断）
"""
import pytest

import scoring
from scoring import (derive_stats, canonical_risk_score, rate_change,
                     detect_data_format_change, RATING_RULES_VERSION)


REC = {
    "version_from": "business-5.3.0.1", "version_to": "business-5.3.0.2",
    "metrics": {"files_changed": 3, "lines_added": 120, "lines_removed": 40,
                "high_risk": 1, "medium_risk": 1, "low_risk": 1, "risk_score": 15},
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
}

LOW_REC = {
    "metrics": {"files_changed": 1, "lines_added": 4, "lines_removed": 1,
                "high_risk": 0, "medium_risk": 0, "low_risk": 1, "risk_score": 1},
    "modules": [{"name": "主题样式 theme", "files": 1, "risk": "low"}],
    "detections": {"data_format_change": False, "version_rollback": False,
                   "sensitive_info": False, "test_sync_needed": False,
                   "circular_dependency": False},
    "files": ["src/style/theme.scss"],
}


class TestDeriveStats:
    def test_base_risk_from_highest_module(self):
        assert derive_stats(REC)["base_risk"] == "high"

    def test_base_risk_falls_back_to_counts(self):
        """无 modules 时用 high/medium/low 计数反推，不能默认 low。"""
        rec = {"metrics": {"high_risk": 0, "medium_risk": 2, "low_risk": 1}}
        assert derive_stats(rec)["base_risk"] == "medium"

    def test_sizes_and_density(self):
        s = derive_stats(REC)
        assert s["total_lines"] == 160
        assert s["file_count"] == 3
        assert s["avg_density"] == pytest.approx(53.33, abs=0.01)

    def test_core_file_count_matches_core_patterns(self):
        """auth / 权限 命中 CORE_PATTERNS → 计入核心模块覆盖文件数。"""
        assert derive_stats(REC)["core_file_count"] == 1

    def test_zero_files_does_not_divide_by_zero(self):
        s = derive_stats({"metrics": {"files_changed": 0, "lines_added": 5}})
        assert s["file_count"] == 1


class TestCanonicalRiskScore:
    def test_deterministic(self):
        """同一记录重复计算必须完全一致（替代 LLM 手填的关键性质）。"""
        a = canonical_risk_score(dict(REC))
        b = canonical_risk_score(dict(REC))
        assert a["risk_score"] == b["risk_score"]
        assert a["dimensions"] == b["dimensions"]

    def test_returns_0_100(self):
        r = canonical_risk_score(REC)
        assert 0 <= r["risk_score"] <= 100

    def test_mode_static_without_history(self):
        assert canonical_risk_score(REC)["scoring_mode"] == "static"

    def test_mode_enhanced_with_history(self):
        hist = {"mod_count": 3.0, "unresolved_ratio": 0.3, "churn_rate": 2.0,
                "author_exp": 3, "days_since": 10}
        r = canonical_risk_score(REC, historical=hist)
        assert r["scoring_mode"] == "enhanced"
        assert "Bug未解决率" in r["dimensions"]

    def test_legacy_value_preserved_for_audit(self):
        """旧公式值必须留档，不静默覆盖。"""
        r = canonical_risk_score(REC)
        assert r["legacy"]["risk_score_legacy"] == 15
        assert r["legacy"]["risk_score_legacy_recomputed"] == 1 * 10 + 1 * 5 + 1 * 1
        assert "min(100" in r["legacy"]["formula"]

    def test_higher_change_scores_higher(self):
        """区分度：大变更必须比纯样式小变更得分高。"""
        assert canonical_risk_score(REC)["risk_score"] > canonical_risk_score(LOW_REC)["risk_score"]

    def test_cross_mode_scores_differ_documented(self):
        """跨模式不可比 —— 锁住这个已知性质，防止有人直接连线做趋势。

        同一 stats 下静态与增强权重不同（base 0.30→0.20、core 0.25→0.20），
        所以分数必然不同。趋势必须用 risk_score（永远 static 口径）。
        """
        hist = {"mod_count": 0, "unresolved_ratio": 0, "churn_rate": 0,
                "author_exp": 3, "days_since": 0}
        static = canonical_risk_score(dict(REC))
        enh = canonical_risk_score(dict(REC), historical=hist)
        assert static["scoring_mode"] == "static"
        assert enh["scoring_mode"] == "enhanced"
        # 两者都合法，但不可混入同一趋势序列
        assert static["risk_score"] != enh["risk_score"]


class TestRateChange:
    def test_deterministic(self):
        assert rate_change(REC) == rate_change(REC)

    def test_rules_version_exposed(self):
        assert rate_change(REC)["rules_version"] == RATING_RULES_VERSION

    def test_auth_core_is_high(self):
        r = rate_change(REC)
        assert r["code"] == "high"
        assert any("R1" in x for x in r["reasons"])

    def test_style_only_is_low(self):
        r = rate_change(LOW_REC)
        assert r["code"] == "low"

    def test_medium_scale(self):
        rec = {"metrics": {"files_changed": 6, "lines_added": 60, "lines_removed": 40,
                           "high_risk": 0}}
        r = rate_change(rec)
        assert r["code"] == "medium"
        assert any("R5" in x for x in r["reasons"])

    def test_data_format_triggers_high(self):
        rec = {"metrics": {"files_changed": 1, "lines_added": 1, "lines_removed": 0},
               "files": ["src/main/proto/user.proto"]}
        r = rate_change(rec)
        assert r["code"] == "high"
        assert any("R2" in x for x in r["reasons"])


class TestRateChangeRecalibration:
    """rules 1.0 → 1.1 的回归防线：原口径几乎无差别判「高」，评级失去区分度。

    真实反例（2026-09-18 实测，已写进 scoring.rate_change docstring）：
      · manage-frontend 5.3.0.7→5.3.0.8：6 文件 / 44 行 / 高风险模块 0 个 → 原判 🔴 高
      · trufar-landing-page 1.0.9→1.0.10：7 文件 / 37 行 / 高风险模块 0 个 → 原判 🔴 高
    两条唯一命中的都是「文件数 > 5」。
    """

    def test_small_multi_file_release_is_not_high(self):
        rec = {"metrics": {"files_changed": 6, "lines_added": 30, "lines_removed": 14,
                           "high_risk": 0, "medium_risk": 1, "low_risk": 5}}
        r = rate_change(rec)
        assert r["code"] != "high", "6 文件 / 44 行 / 零高风险模块 不应判高风险"
        assert r["code"] == "medium"

    def test_scale_threshold_matches_published_jit_scale(self):
        """R3 阈值必须与 quant_jit_risk 已公开的口径（400 行 / 10 文件）一致。"""
        import scoring as sc
        assert (sc.HIGH_LINES, sc.HIGH_FILES) == (400, 10)
        # 401 行 → 高；400 行且文件数 3 → 不高
        assert rate_change({"metrics": {"files_changed": 3, "lines_added": 250,
                                        "lines_removed": 151, "high_risk": 0}})["code"] == "high"
        assert rate_change({"metrics": {"files_changed": 3, "lines_added": 200,
                                        "lines_removed": 200, "high_risk": 0}})["code"] != "high"

    def test_eleven_files_is_high_on_size_alone(self):
        r = rate_change({"metrics": {"files_changed": 11, "lines_added": 5,
                                     "lines_removed": 0, "high_risk": 0}})
        assert r["code"] == "high"
        assert any("R3" in x for x in r["reasons"])

    def test_high_risk_ratio_below_threshold_not_high(self):
        """2/8 = 25% < 1/3 → 不触发 R4（「有高风险模块」≠「整区间高风险」）。"""
        rec = {"metrics": {"files_changed": 8, "lines_added": 100, "lines_removed": 50,
                           "high_risk": 2, "medium_risk": 3, "low_risk": 3}}
        r = rate_change(rec)
        assert r["code"] == "medium"
        assert not any("R4" in x for x in r["reasons"])

    def test_high_risk_ratio_meets_threshold_is_high(self):
        """6/11 = 55% ≥ 1/3 且 ≥2 个 → 触发 R4。"""
        rec = {"metrics": {"files_changed": 11, "lines_added": 175, "lines_removed": 132,
                           "high_risk": 6, "medium_risk": 3, "low_risk": 2}}
        r = rate_change(rec)
        assert r["code"] == "high"
        assert any("R4" in x for x in r["reasons"])

    def test_single_high_risk_module_is_medium_via_r6(self):
        rec = {"metrics": {"files_changed": 4, "lines_added": 30, "lines_removed": 10,
                           "high_risk": 1, "medium_risk": 1, "low_risk": 2}}
        r = rate_change(rec)
        assert r["code"] == "medium"
        assert any("R6" in x for x in r["reasons"])


class TestDetectDataFormat:
    def test_detects_proto_and_locale(self):
        assert detect_data_format_change({}, paths=["a/b/user.proto"]) is True
        assert detect_data_format_change({}, paths=["locale/zh.json"]) is True

    def test_plain_logic_is_false(self):
        assert detect_data_format_change({}, paths=["src/AuthController.java"]) is False

    def test_reads_detections_flag(self):
        rec = {"detections": {"data_format_change": True}}
        assert detect_data_format_change(rec) is True
