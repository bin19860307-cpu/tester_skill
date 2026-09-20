# -*- coding: utf-8 -*-
"""项目级 Bug 池 + 端归属预判 + 横幅评级同步（2026-09-18 用户反馈三问题）的回归测试。"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _common  # noqa: E402
import bug_trend  # noqa: E402
from gen_quant_jit import sync_banner_rating  # noqa: E402


@pytest.fixture
def pool_root(tmp_path):
    """构造含项目级池 + 一个服务的 analytics 根目录。"""
    root = tmp_path / "diff-analytics"
    proj = root / "_project"
    proj.mkdir(parents=True)
    bugs = [
        {"bug_id": "9001", "title": "页面表格样式错乱", "severity": "low",
         "status": "closed", "found_in_version": "5.3.0.1", "fixed_in_version": "5.3.0.2"},
        {"bug_id": "9002", "title": "导出接口返回数据错误", "severity": "critical",
         "status": "open", "found_in_version": "5.3.0.2", "fixed_in_version": None},
    ]
    (proj / "version_bugs.json").write_text(json.dumps({
        "service": "_project", "scope": "project", "source_xlsx": "bug列表.xlsx",
        "bugs": bugs}, ensure_ascii=False), encoding="utf-8")
    svc = root / "svc-a"
    svc.mkdir()
    (svc / "service_metrics.json").write_text(json.dumps({
        "service": "svc-a", "records": [{
            "version_from": "5.3.0.1", "version_to": "5.3.0.2",
            "analysis_date": "2026-09-18",
            "metrics": {"files_changed": 3, "lines_added": 10, "lines_removed": 5,
                        "high_risk": 0, "medium_risk": 1, "low_risk": 2,
                        "risk_score": 40.0, "risk_score_mode": "static",
                        "scoring_mode": "static"},
            "modules": [], "detections": {}, "rating": {"level": "🟡 中", "code": "medium"},
        }]}, ensure_ascii=False), encoding="utf-8")
    return str(root)


class TestLoadBugsDoc:
    def test_service_level_preferred(self, pool_root):
        root = pool_root
        svc_file = os.path.join(root, "svc-a", "version_bugs.json")
        with open(svc_file, "w", encoding="utf-8") as f:
            json.dump({"service": "svc-a", "bugs": [{"bug_id": "1"}]}, f)
        doc, scope = _common.load_bugs_doc(root, "svc-a")
        assert scope == "service"
        assert doc["bugs"][0]["bug_id"] == "1"

    def test_fallback_to_project_pool(self, pool_root):
        doc, scope = _common.load_bugs_doc(pool_root, "svc-a")
        assert scope == "project"
        assert len(doc["bugs"]) == 2

    def test_missing_everywhere(self, tmp_path):
        doc, scope = _common.load_bugs_doc(str(tmp_path), "nope")
        assert doc is None and scope is None

    def test_project_service_reads_pool_directly(self, pool_root):
        doc, scope = _common.load_bugs_doc(pool_root, "_project")
        assert scope == "project"


class TestClassifyBugSide:
    def test_frontend_keywords(self):
        side, kw = _common.classify_bug_side({"title": "班级名称过长建议悬浮展示"})
        assert side == "前端" and kw

    def test_backend_keywords(self):
        side, _ = _common.classify_bug_side({"title": "实训发布导出失败"})
        assert side == "后端"

    def test_backend_priority_over_frontend(self):
        # 「请求参数」在后端规则且顺序在前 → 后端
        side, _ = _common.classify_bug_side({"title": "下拉列表未请求参数导致返回数据异常"})
        assert side == "后端"

    def test_generic_when_no_hit(self):
        side, kw = _common.classify_bug_side({"title": "工作台指标名称与需求不符"})
        assert side == "通用" and kw == ""

    def test_empty(self):
        assert _common.classify_bug_side(None)[0] == "通用"
        assert _common.classify_bug_side({})[0] == "通用"


class TestProjectScopeTrend:
    def test_build_stats_falls_back_to_pool(self, pool_root):
        st = bug_trend.build_stats("svc-a", pool_root)
        assert st is not None
        assert st["bugs_scope"] == "project"
        assert st["total"] == 2
        # 项目级口径下：单服务的 Bug/变更比不可用
        assert all(p["change_to_bug_ratio"] is None for p in st["per_version"])

    def test_combined_uses_pool_once(self, pool_root):
        st = bug_trend.build_stats_combined(["svc-a", "svc-b"], pool_root)
        assert st["bugs_scope"] == "project"
        # 池只计一次（不因参与服务数翻倍）
        assert st["total"] == 2
        # 项目级口径：文件数为参与服务求和（svc-a 5.3.0.2 → 3）
        by_key = {p["version_key"]: p for p in st["per_version"]}
        assert by_key["5.3.0.2"]["files_changed"] == 3
        assert by_key["5.3.0.2"]["change_to_bug_ratio"] is not None

    def test_scope_note_rendered(self, pool_root):
        st = bug_trend.build_stats("svc-a", pool_root)
        inner = bug_trend.render_inner(st)
        assert "项目级" in inner
        assert "端归属预判" in inner


BANNER_MF = '''
<div class="risk-banner low">
    <div class="risk-icon">🟢</div>
    <div class="risk-text">
        <strong>综合风险等级：低（以 UI 样式回退 + 单点功能修复为主）</strong>
        <p>本次变更以样式为主，综合风险低。</p>
    </div>
</div>
'''


class TestSyncBannerRating:
    def test_sync_low_to_medium(self):
        html, changed = sync_banner_rating(BANNER_MF, {"code": "medium", "level": "🟡 中"})
        assert changed
        assert 'class="risk-banner medium"' in html
        assert "综合风险等级：中" in html
        assert "原定性「低」" in html
        assert "评级口径：确定性评级" in html
        assert 'class="risk-icon">🟡' in html

    def test_idempotent_when_same(self):
        html = BANNER_MF.replace("low", "high").replace("🟢", "🔴").replace("低（", "高（")
        html = html.replace("综合风险等级：高（以 UI 样式回退", "综合风险等级：高（核心重构")
        html, changed = sync_banner_rating(html, {"code": "high"})
        assert not changed

    def test_second_run_no_dup_note(self):
        html, _ = sync_banner_rating(BANNER_MF, {"code": "medium"})
        html2, changed2 = sync_banner_rating(html, {"code": "medium"})
        assert not changed2
        assert html2.count("评级口径：确定性评级") == 1

    def test_no_banner_noop(self):
        html, changed = sync_banner_rating("<p>x</p>", {"code": "medium"})
        assert not changed and html == "<p>x</p>"

    def test_bad_rating_noop(self):
        html, changed = sync_banner_rating(BANNER_MF, {"code": "bogus"})
        assert not changed
