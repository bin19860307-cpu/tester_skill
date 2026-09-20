# -*- coding: utf-8 -*-
"""gen_quant_jit.py 的「stats 同源」测试 + CORE_PATTERNS 过宽匹配回归。

背景（2026-09-18）：报告里的量化分与趋势里的 risk_score 用的**不是同一组输入** ——
报告侧走 `derive_stats_from_report()`（在 HTML 里数 class="added"/"removed" 的行数），
趋势侧走 `service_metrics.json` 的权威 lines_added/lines_removed。
实测同一份变更两边能差 5 倍（portal-backend 54 行 vs 271 行），
`base_risk` 甚至不同（manage-frontend low vs medium）→ 报告与趋势自相矛盾。

本文件锁死「报告侧改吃 service_metrics」这条路径。
"""
import json
import os

import pytest

import gen_quant_jit as g
from quant_jit_risk import CORE_PATTERNS
import re


def _report_path(rr, name="demo-svc_5.3.0.1_to_5.3.0.2_变更影响分析报告.html"):
    return os.path.join(rr, "demo-svc", name)


class TestReportVersionRange:
    def test_parses_from_filename(self, workspace):
        ws, ar, rr = workspace
        frm, to = g._report_version_range(_report_path(rr))
        assert (frm, to) == ("5.3.0.1", "5.3.0.2")

    def test_parses_prefixed_forms(self):
        frm, to = g._report_version_range("/x/svc_business-5.3.0.3_to_business-5.3.0.4_变更影响分析报告.html")
        assert (frm, to) == ("business-5.3.0.3", "business-5.3.0.4")

    def test_returns_none_when_unparsable(self):
        assert g._report_version_range("/x/svc_report.html") == (None, None)


class TestStatsFromMetrics:
    def test_hits_record_across_version_spelling(self, workspace):
        """报告文件名用裸号，metrics 记录用 business- 前缀 → 必须能匹配上。"""
        ws, ar, rr = workspace
        st, note = g.stats_from_metrics("demo-svc", _report_path(rr), ar)
        assert st is not None, note
        assert "5.3.0.2" in note

    def test_reads_authoritative_numbers_from_metrics(self, workspace):
        """必须是 service_metrics 的权威数字，不是 HTML 数出来的行数。"""
        ws, ar, rr = workspace
        st, _ = g.stats_from_metrics("demo-svc", _report_path(rr), ar)
        assert st["file_count"] == 3                 # metrics.files_changed
        assert st["total_lines"] == 160              # 120 + 40
        assert st["base_risk"] == "high"             # modules 最高等级

    def test_marks_source_for_traceability(self, workspace):
        ws, ar, rr = workspace
        st, _ = g.stats_from_metrics("demo-svc", _report_path(rr), ar)
        assert st["_source"] == "service_metrics.json:version_to=5.3.0.2"

    def test_fails_gracefully_when_no_matching_record(self, workspace):
        ws, ar, rr = workspace
        p = _report_path(rr, "demo-svc_9.9.9.8_to_9.9.9.9_变更影响分析报告.html")
        st, reason = g.stats_from_metrics("demo-svc", p, ar)
        assert st is None
        assert "没有 version_to" in reason

    def test_fails_when_report_name_lacks_range(self, workspace):
        ws, ar, rr = workspace
        st, reason = g.stats_from_metrics("demo-svc", _report_path(rr, "无版本区间.html"), ar)
        assert st is None and "_X_to_Y_" in reason

    def test_fails_when_metrics_missing(self, workspace):
        ws, ar, rr = workspace
        st, reason = g.stats_from_metrics("no-such-svc", _report_path(rr), ar)
        assert st is None and "不存在" in reason

    def test_picks_latest_when_multiple_records_share_version(self, workspace):
        """同一 version_to 有多条记录时取 analysis_date 最新的一条。"""
        ws, ar, rr = workspace
        p = os.path.join(ar, "demo-svc", "service_metrics.json")
        doc = json.load(open(p, encoding="utf-8"))
        old = json.loads(json.dumps(doc["records"][0]))
        old["analysis_date"] = "2026-01-01"
        old["metrics"]["files_changed"] = 999        # 旧记录：明显不同的值
        doc["records"].append(old)
        json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        st, _ = g.stats_from_metrics("demo-svc", _report_path(rr), ar)
        assert st["file_count"] == 3, "应取 analysis_date 最新的记录，而不是旧的 999"


class TestCorePatternsOverMatch:
    """CORE_PATTERNS 的「版本」条目曾两次过宽，两次都在真实数据上造成误判。"""

    @pytest.mark.parametrize("name", [
        "版本号/下载文件名(pom/TaskManage)",     # 版本 bump 不是核心模块（修正 ①）
        "版本号 pom",
        "我的班级表格样式(myClass.vue 回退)",     # 样式回退 ≠ 版本回退（修正 ②）
        "学生列表表格样式(studentList.vue/studentCol.ts 回退)",
        "未入班表格样式(unHaveClass.vue 回退)",
        "需求回退",
    ])
    def test_not_core(self, name):
        hit = [lab for pat, lab in CORE_PATTERNS if re.search(pat, name, re.I)]
        assert hit == [], "%s 不应被判为核心模块，实际命中 %s" % (name, hit)

    @pytest.mark.parametrize("name", [
        "学校版本到期降级逻辑", "版本回退处理", "版本降级", "rollback 处理", "订单回滚",
    ])
    def test_is_core(self, name):
        hit = [lab for pat, lab in CORE_PATTERNS if re.search(pat, name, re.I)]
        assert hit, "%s 应被判为核心模块" % name


class TestInjectIdempotentPlacement:
    """2026-09-18 缺陷回归：综合报告量化表被追加到 </html> 之后（跑到 ⑥ 之后）。

    占位符只在首次存在；二次运行判定「无占位符」后走了 `html + frag` 分支，
    区块落到 </html> 之后，文档结构损坏。
    """

    DOC = ('<html><body>'
           '<div class="section"><h2>② 各服务摘要卡</h2><!-- QUANT_JIT_COMBINED --></div>'
           '<div class="section"><h2>⑥ 综合发布建议</h2><p>x</p></div>'
           '</body></html>')
    FRAG = "<!-- QUANT_JIT_COMBINED_START --><div>QUANT</div><!-- QUANT_JIT_COMBINED_END -->"

    def _inside(self, html):
        q = html.find("QUANT_JIT_COMBINED_START")
        return q != -1 and q < html.rfind("</body>")

    def test_first_run_replaces_placeholder(self):
        out = g.inject_combined(self.DOC, self.FRAG)
        assert self._inside(out)
        assert "<!-- QUANT_JIT_COMBINED -->" not in out

    def test_second_run_stays_inside_document(self):
        h1 = g.inject_combined(self.DOC, self.FRAG)
        h2 = g.inject_combined(h1, self.FRAG)
        assert self._inside(h2), "二次运行后区块必须仍在 </body> 之前"
        # </html> 之后不允许残留内容
        assert h2.rstrip().endswith("</html>")

    def test_third_run_unchanged_position(self):
        h = self.DOC
        for _ in range(3):
            h = g.inject_combined(h, self.FRAG)
        assert h.count("QUANT_JIT_COMBINED_START") == 1
        assert self._inside(h)

    def test_no_placeholder_inserts_before_body(self):
        doc = "<html><body><p>no placeholder</p></body></html>"
        out = g.inject_combined(doc, self.FRAG)
        assert out.find("QUANT_JIT_COMBINED_START") < out.rfind("</body>")
        assert out.rstrip().endswith("</html>")

    def test_never_appends_after_html(self):
        for doc in (self.DOC, "<html><body></body></html>", "<div>plain</div>"):
            out = g.inject_combined(doc, self.FRAG)
            i = out.rfind("</html>")
            assert i == -1 or out[i + len("</html>"):].strip() == ""
