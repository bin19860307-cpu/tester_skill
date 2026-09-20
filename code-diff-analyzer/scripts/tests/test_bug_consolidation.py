# -*- coding: utf-8 -*-
"""Bug 数据归口综合报告 + 端归属拆分（2026-09-19 用户决策）的回归测试。

用户规则原文：
    「把所有 bug 相关的数据都移至综合报告中，除非当前分析服务只有一个。
      那就展示在单服务中。」

由此固化的三条行为：
    1) 本次分析含 ≥2 个服务时，bug_trend.py 拒绝往单服务报告注入（SKIP，需 --force 才注入）；
    2) --strip 反向撤走单服务报告里已注入的区块，并留「已归口」提示（幂等）；
    3) 综合报告是 Bug 数据唯一归口，其中 ④ 表按发现版本拆出 前端/后端/通用。
"""
import io
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _common  # noqa: E402
import bug_trend  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def pool_root(tmp_path):
    """项目级池：跨 3 个发现版本，端归属可区分。"""
    root = tmp_path / "diff-analytics"
    proj = root / "_project"
    proj.mkdir(parents=True)
    bugs = [
        # 5.3.0.1：前端 2 / 后端 1
        {"bug_id": "1", "title": "列表页面样式错乱", "severity": "low", "status": "closed",
         "found_in_version": "5.3.0.1", "fixed_in_version": "5.3.0.2"},
        {"bug_id": "2", "title": "按钮悬浮提示不显示", "severity": "low", "status": "closed",
         "found_in_version": "5.3.0.1", "fixed_in_version": "5.3.0.2"},
        {"bug_id": "3", "title": "导出接口返回数据错误", "severity": "critical", "status": "open",
         "found_in_version": "5.3.0.1", "fixed_in_version": None},
        # 5.3.0.2：后端 2 / 通用 1
        {"bug_id": "4", "title": "查询请求参数校验缺失", "severity": "medium", "status": "closed",
         "found_in_version": "5.3.0.2", "fixed_in_version": "5.3.0.3"},
        {"bug_id": "5", "title": "批量导入接口返回数据为空", "severity": "high", "status": "closed",
         "found_in_version": "5.3.0.2", "fixed_in_version": "5.3.0.3"},
        {"bug_id": "6", "title": "工作台指标名称与需求不符", "severity": "low", "status": "open",
         "found_in_version": "5.3.0.2", "fixed_in_version": None},
    ]
    (proj / "version_bugs.json").write_text(json.dumps({
        "service": "_project", "scope": "project", "source_xlsx": "bug列表.xlsx",
        "bugs": bugs}, ensure_ascii=False), encoding="utf-8")

    for svc in ("portal-backend", "manage-frontend"):
        d = root / svc
        d.mkdir()
        (d / "service_metrics.json").write_text(json.dumps({
            "service": svc, "records": [{
                "version_from": "5.3.0.1", "version_to": "5.3.0.2",
                "analysis_date": "2026-09-19",
                "metrics": {"files_changed": 3, "lines_added": 10, "lines_removed": 5,
                            "risk_score": 40.0, "risk_score_mode": "static",
                            "scoring_mode": "static"},
                "modules": [], "detections": {}, "rating": {"level": "🟡 中", "code": "medium"},
            }]}, ensure_ascii=False), encoding="utf-8")
    return str(root)


# ---------------------------------------------------------------------------
# 1) 端归属：服务侧判定 + Bug 侧拆分
# ---------------------------------------------------------------------------
class TestServiceSide:
    def test_backend_by_name(self):
        assert _common.service_side("portal-backend") == ("后端", "name:backend")

    def test_frontend_by_name(self):
        assert _common.service_side("manage-frontend") == ("前端", "name:frontend")

    def test_unknown_service(self):
        assert _common.service_side("acme-login-script") == (None, None)

    def test_fallback_to_extension(self):
        side, rule = _common.service_side("svc-x", files=["a/B.java"])
        assert side == "后端" and "ext" in rule
        side, rule = _common.service_side("svc-y", files=["a/b.vue"])
        assert side == "前端" and "ext" in rule


class TestBugsSideBreakdown:
    def test_split_by_version(self, pool_root):
        doc, _ = _common.load_bugs_doc(pool_root, "portal-backend")
        bd = _common.bugs_side_breakdown(doc["bugs"])
        assert bd["5.3.0.1"] == {"前端": 2, "后端": 1, "通用": 0}
        assert bd["5.3.0.2"]["后端"] == 2
        assert bd["5.3.0.2"]["通用"] == 1

    def test_total_is_conserved(self, pool_root):
        doc, _ = _common.load_bugs_doc(pool_root, "portal-backend")
        bd = _common.bugs_side_breakdown(doc["bugs"])
        total = sum(sum(v.values()) for v in bd.values())
        assert total == len(doc["bugs"])

    def test_side_relevant_count(self, pool_root):
        doc, _ = _common.load_bugs_doc(pool_root, "portal-backend")
        bd = _common.bugs_side_breakdown(doc["bugs"])
        # 后端服务：后端 Bug + 通用（端归属待定）
        assert _common.side_relevant_count(bd["5.3.0.1"], "后端") == 1
        assert _common.side_relevant_count(bd["5.3.0.2"], "后端") == 3  # 2 后端 + 1 通用


# ---------------------------------------------------------------------------
# 2) 综合报告承载拆分表
# ---------------------------------------------------------------------------
class TestCombinedCarriesSplit:
    def test_combined_stats_has_breakdown(self, pool_root):
        st = bug_trend.build_stats_combined(["portal-backend", "manage-frontend"], pool_root)
        assert st["bugs_scope"] == "project"
        assert st["side_breakdown"]["5.3.0.1"]["前端"] == 2

    def test_render_includes_split_table(self, pool_root):
        st = bug_trend.build_stats_combined(["portal-backend", "manage-frontend"], pool_root)
        inner = bug_trend.render_inner(st)
        assert "④ 端归属预判拆分" in inner
        # 合计行：前端 2 / 后端 3 / 通用 1
        assert "前端</th>" in inner
        assert "<td>2</td><td>3</td><td>1</td>" in inner

    def test_no_split_table_for_service_scope(self):
        """服务级口径（无项目池）不渲染 ④ 表，避免误导成端归属。"""
        st = {"per_version": [], "total": 0, "closed_total": 0, "resolved_total": 0,
              "sev_total": {}, "fix_rate_total": 0.0, "avg_fix_interval": None,
              "versions_count": 0, "source_bugs": "", "service": "x",
              "generated_at": "2026-09-19 00:00:00", "bugs_scope": "service",
              "scope_label": "", "side_pre_dist": {}, "side_breakdown": {}}
        assert "④ 端归属预判拆分" not in bug_trend.render_inner(st)


# ---------------------------------------------------------------------------
# 3) --strip：撤走单服务报告里的 Bug 区块（幂等）
# ---------------------------------------------------------------------------
FAKE_REPORT = """<html><body>
<div class="section"><div class="section-title">变更总览</div><p>x</p></div>
<!-- BUG_TREND_START -->
<div class="section"><div class="section-title">📈 版本 Bug 趋势分析</div>
<div class="bt-wrap"><div class="bt-card"><div class="bt-num">49</div></div></div>
</div>
<!-- BUG_TREND_END -->
<div class="footer">footer</div>
</body></html>"""


@pytest.fixture
def report_file(tmp_path):
    p = tmp_path / "r.html"
    p.write_text(FAKE_REPORT, encoding="utf-8")
    return str(p)


class TestStripFromReport:
    def test_removes_block(self, report_file):
        assert bug_trend.strip_from_report(report_file) == "已移除"
        s = open(report_file, encoding="utf-8").read()
        assert "<!-- BUG_TREND_START -->" not in s
        assert "bt-card" not in s

    def test_leaves_consolidation_note(self, report_file):
        bug_trend.strip_from_report(report_file)
        s = open(report_file, encoding="utf-8").read()
        assert "已按归口规则统一移入综合比对分析报告" in s
        # 提示需落在 .section 容器内，不能是裸 <p>
        assert '<div class="section">' in s and "版本 Bug 趋势分析" in s

    def test_other_sections_preserved(self, report_file):
        bug_trend.strip_from_report(report_file)
        s = open(report_file, encoding="utf-8").read()
        assert "变更总览" in s and "footer" in s

    def test_idempotent_second_run(self, report_file):
        bug_trend.strip_from_report(report_file)
        assert bug_trend.strip_from_report(report_file) == "无区块（无需处理）"

    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            bug_trend.strip_from_report(str(tmp_path / "nope.html"))


# ---------------------------------------------------------------------------
# 4) 多服务时拒绝往单服务报告注入（SKIP），单服务场景放行
# ---------------------------------------------------------------------------
def _run_main(argv):
    old = sys.argv
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.argv = ["bug_trend.py"] + argv
    sys.stdout = buf
    try:
        bug_trend.main()
    finally:
        sys.argv = old
        sys.stdout = old_stdout
    return buf.getvalue()


class TestSkipRule:
    def test_multi_service_skips_single_report(self, pool_root, report_file):
        out = _run_main(["--service", "portal-backend",
                         "--services", "portal-backend", "manage-frontend",
                         "--report", report_file,
                         "--analytics-root", pool_root])
        assert "[SKIP]" in out
        # 没有被注入
        s = open(report_file, encoding="utf-8").read()
        assert "<!-- BUG_TREND_START -->" in s  # 原样保留（老区块还在）

    def test_force_overrides_skip(self, pool_root, report_file):
        out = _run_main(["--service", "portal-backend",
                         "--services", "portal-backend", "manage-frontend",
                         "--report", report_file, "--force",
                         "--analytics-root", pool_root])
        assert "[OK]" in out
        s = open(report_file, encoding="utf-8").read()
        assert "④ 端归属预判拆分" in s

    def test_single_service_allowed(self, pool_root, report_file):
        out = _run_main(["--service", "portal-backend",
                         "--report", report_file,
                         "--analytics-root", pool_root])
        assert "[OK]" in out
        s = open(report_file, encoding="utf-8").read()
        assert "<!-- BUG_TREND_START -->" in s
