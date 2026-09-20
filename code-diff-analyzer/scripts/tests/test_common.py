# -*- coding: utf-8 -*-
"""_common.py 单元测试 —— 版本键归一化 + 变更文件路径过滤。

这两件事是 2026-09-18 体检中「两端永不交汇（0/49）」与「file_history 混入输入产物」
两个缺陷的根因所在，必须锁死行为。
"""
import pytest

from _common import (
    norm_version, version_key, version_segments, version_series, same_version,
    build_canon_index, inconsistent_keys, inconsistent_keys_by_source,
    is_junk_path, is_logic_path, filter_change_files, normalize_path,
)


class TestNormVersion:
    """跨文件比较的前提：三种写法必须归一到同一键。"""

    @pytest.mark.parametrize("raw,expected", [
        ("business-5.3.0.2", "5.3.0.2"),      # service_metrics / version_chain 的写法
        ("v5.3.0.2", "5.3.0.2"),
        ("5.3.0.2", "5.3.0.2"),               # version_bugs（TAPD）的写法
        ("release-5.3.0.2-hotfix", "5.3.0.2"),
        ("BUSINESS-5.3.0.4", "5.3.0.4"),
        ("mashang-5.2.0.6", "5.2.0.6"),
        ("1.2.44", "1.2.44"),
        ("5.3", "5.3"),
        ("  business-5.3.0.2  ", "5.3.0.2"),
    ])
    def test_known_forms(self, raw, expected):
        assert norm_version(raw) == expected

    def test_prefix_variants_map_to_same_key(self):
        """核心断言：裸号与带前缀必须相等（原实现此处必然 miss → 0/49）。"""
        assert norm_version("5.3.0.2") == norm_version("business-5.3.0.2")
        assert norm_version("5.3.0.2") == norm_version("v5.3.0.2")

    @pytest.mark.parametrize("empty", [None, "", "  ", "-", "—", "/", "None", "nan"])
    def test_empty_returns_none(self, empty):
        assert norm_version(empty) is None

    def test_non_version_returns_cleaned(self):
        """无版本段时不静默丢弃，返回清洗串以便诊断。"""
        assert norm_version("Sprint A") == "sprinta"

    def test_does_not_confuse_partial_numbers(self):
        """5.3.0.2 与 5.3.0.20 必须不同（不能取前缀了事）。"""
        assert norm_version("5.3.0.2") != norm_version("5.3.0.20")


class TestVersionKey:
    def test_pads_to_four_segments(self):
        """5.3 / 5.3.0 / 5.3.0.0 必须排序等价（原实现长度不同 → 比较语义混乱）。"""
        assert version_key("5.3") == version_key("5.3.0")
        assert version_key("5.3") == version_key("5.3.0.0")
        assert version_key("5.3") == version_key("business-5.3.0.0")

    def test_ordering(self):
        vs = ["business-5.3.0.4", "5.3.0.1", "v5.3.0.2", "5.3.0.10", "5.3.1.0"]
        assert sorted(vs, key=version_key) == \
            ["5.3.0.1", "v5.3.0.2", "business-5.3.0.4", "5.3.0.10", "5.3.1.0"]

    def test_invalid_is_zero_tuple(self):
        assert version_key(None) == (0, 0, 0, 0)
        assert version_key("abc") == (0, 0, 0, 0)

    def test_segments(self):
        assert version_segments("business-5.3.0.2") == [5, 3, 0, 2]


class TestSameVersion:
    def test_cross_form_equality(self):
        assert same_version("5.3.0.2", "business-5.3.0.2")
        assert not same_version("5.3.0.2", "5.3.0.3")

    def test_both_none(self):
        assert same_version(None, None)
        assert not same_version(None, "5.3.0.2")


class TestVersionSeries:
    @pytest.mark.parametrize("raw,expected", [
        ("business-5.3.0.2", "5.3"), ("5.3.0.0", "5.3"), ("release-5.3.0.2-hotfix", "5.3"),
        ("1.2.44", "1.2"),
    ])
    def test_series(self, raw, expected):
        assert version_series(raw) == expected

    def test_insufficient_segments(self):
        assert version_series("5") is None
        assert version_series(None) is None


class TestCanonIndex:
    def test_detects_inconsistent_spellings(self):
        vals = ["business-5.3.0.2", "5.3.0.2", "v5.3.0.2", "5.3.0.3"]
        idx = build_canon_index(vals)
        assert sorted(idx["5.3.0.2"]) == ["5.3.0.2", "business-5.3.0.2", "v5.3.0.2"]
        bad = inconsistent_keys(vals)
        assert set(bad.keys()) == {"5.3.0.2"}

    def test_consistent_input_has_no_issue(self):
        assert inconsistent_keys(["5.3.0.2", "5.3.0.2"]) == {}


class TestInconsistentKeysBySource:
    """按来源定位写法不一致 —— 修复时必须知道根因在哪个文件。"""

    def test_locates_both_sources(self):
        got = inconsistent_keys_by_source({
            "service_metrics.version_to": ["business-5.3.0.2"],
            "version_bugs.found_in_version": ["5.3.0.2", None],
        })
        assert set(got.keys()) == {"5.3.0.2"}
        assert got["5.3.0.2"]["raw_forms"] == ["5.3.0.2", "business-5.3.0.2"]
        assert got["5.3.0.2"]["sources"] == [
            "service_metrics.version_to", "version_bugs.found_in_version"]

    def test_uniform_spelling_reports_nothing(self):
        got = inconsistent_keys_by_source({
            "a": ["5.3.0.2"], "b": ["5.3.0.2", " 5.3.0.2 "],
        })
        assert got == {}

    def test_ignores_none_and_empty(self):
        got = inconsistent_keys_by_source({"a": [None, "", "-", "5.3.0.2"]})
        assert got == {}


class TestPathFilter:
    @pytest.mark.parametrize("p", [
        "manage-5.1.0.5_tagdiff.txt",           # 本技能上游输入产物
        "svcB_tagdiff_v5.3.0.3_path-apps_manage.txt",
        "report/temp_oe.txt",
        "_build_analytics.py",
        "a/b/__pycache__/x.pyc",
        "node_modules/react/index.js",
        "compare_a_to_b.md",                     # 另一类输入产物
        "x.tmp", "x.bak", "x.old",
    ])
    def test_junk_detected(self, p):
        assert is_junk_path(p) is True

    @pytest.mark.parametrize("p", [
        "src/main/java/AuthController.java",
        "apps/manage/src/views/home/myClass.vue",
        "index.html", "zh.json", "tsconfig.json", "package.json",
    ])
    def test_not_junk(self, p):
        """非逻辑代码**不是**垃圾 —— 它们是真实变更，应计入 files_changed。"""
        assert is_junk_path(p) is False

    @pytest.mark.parametrize("p", [
        "package.json", "pnpm-lock.yaml", "tsconfig.app.json", "README.md",
        "logo.svg", "style.css", "app.d.ts", "index.html",
    ])
    def test_non_logic_flagged_but_kept(self, p):
        assert is_logic_path(p) is False

    def test_logic_detected(self):
        assert is_logic_path("src/main/java/AuthController.java") is True
        assert is_logic_path("apps/manage/src/views/home/myClass.vue") is True

    def test_filter_keeps_order_and_dedups(self):
        kept, dropped = filter_change_files([
            "src/a.py", "manage-5.1.0.5_tagdiff.txt", "src/a.py", "src/b.py",
        ])
        assert kept == ["src/a.py", "src/b.py"]
        assert dropped == ["manage-5.1.0.5_tagdiff.txt"]

    def test_normalize_path(self):
        assert normalize_path(".\\a\\b\\c.py") == "a/b/c.py"
        assert normalize_path("./x/y") == "x/y"
        assert normalize_path(None) == ""
