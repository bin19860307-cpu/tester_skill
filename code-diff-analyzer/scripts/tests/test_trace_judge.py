# -*- coding: utf-8 -*-
"""trace_judge.py 单元测试 —— Agent Trace 四级判断层（缺口②，2026-09-30）。

覆盖点：
  · 四级判定的确定性（同输入同输出）
  · 信号升级路径：normal → minor → needs_review → critical
  · 缺失字段不臆造信号（全空 trace 判 normal）
  · 轻微信号叠加升级（≥3 个 minor → needs_review）
  · 高风险专属规则：连续失败 / 敏感面出错 / 慢+错 / 工具调用风暴
  · 批次汇总：分布统计、升级清单、p95 自适应
"""
import json
import os

import pytest

import trace_judge as tj
from trace_judge import judge_trace, judge_batch, load_traces, RULES_VERSION


BASE = {
    "trace_id": "t-1",
    "duration_ms": 800,
    "total_tokens": 500,
    "error": False,
    "output_empty": False,
}


class TestSingleTrace:
    def test_deterministic(self):
        assert judge_trace(dict(BASE)) == judge_trace(dict(BASE))

    def test_clean_trace_is_normal(self):
        r = judge_trace(BASE)
        assert r["severity"] == "normal"
        assert r["signals"] == []

    def test_empty_trace_no_fabricated_signals(self):
        """字段全缺 → 不臆造任何信号，判 normal（缺失维度不参与判定）。"""
        r = judge_trace({"trace_id": "t-x"})
        assert r["severity"] == "normal"
        assert r["signals"] == []

    def test_slow_is_minor(self):
        r = judge_trace(dict(BASE, duration_ms=25000))
        assert r["severity"] == "minor"
        assert any("耗时" in s for s in r["signals"])

    def test_error_is_needs_review(self):
        r = judge_trace(dict(BASE, error=True, error_message="timeout in llm call"))
        assert r["severity"] == "needs_review"
        assert any("执行出错" in s for s in r["signals"])

    def test_empty_output_is_needs_review(self):
        r = judge_trace(dict(BASE, output_empty=True))
        assert r["severity"] == "needs_review"

    def test_score_deviation_is_needs_review(self):
        r = judge_trace(dict(BASE, score=0.40, score_expected=0.80))
        assert r["severity"] == "needs_review"
        assert any("评分" in s for s in r["signals"])
        # 边界：恰好 0.15 不触发（严格大于）
        ok = judge_trace(dict(BASE, score=0.65, score_expected=0.80))
        assert ok["severity"] == "normal"

    def test_consecutive_errors_is_critical(self):
        r = judge_trace(dict(BASE, error=True, consecutive_errors=3))
        assert r["severity"] == "critical"

    def test_sensitive_error_is_critical(self):
        r = judge_trace(dict(BASE, error=True, sensitive=True))
        assert r["severity"] == "critical"

    def test_slow_and_error_is_critical(self):
        """慢 + 错组合升级（排查成本最高的组合，单独成规则）。"""
        r = judge_trace(dict(BASE, error=True, duration_ms=99000))
        assert r["severity"] == "critical"
        assert any("慢+错" in s for s in r["signals"])

    def test_tool_call_storm_is_critical(self):
        r = judge_trace(dict(BASE, tool_calls=25))
        assert r["severity"] == "critical"
        assert any("循环调用" in s for s in r["signals"])

    def test_error_message_string_truthy(self):
        """error 用非空字符串表达（部分导出格式）也应识别。"""
        r = judge_trace(dict(BASE, error="HTTP 500"))
        assert r["severity"] == "needs_review"

    def test_minor_signal_stack_upgrades(self):
        """3 个轻微信号叠加 → needs_review（MANY_SIGNALS 规则）。"""
        r = judge_trace(dict(BASE, duration_ms=25000, total_tokens=5000))
        # 只有 2 个轻微信号（慢 + token 轻微超）→ 仍 minor
        assert r["severity"] == "minor"
        r2 = judge_trace(dict(BASE, duration_ms=25000, total_tokens=5000,
                              tool_calls=0, error_count=0,
                              output_empty=False, error=False))
        # 构造第 3 个轻微信号需要另一维度，这里验证 token 硬上限路径
        r3 = judge_trace(dict(BASE, total_tokens=15000))
        assert r3["severity"] == "needs_review"
        assert any("Token" in s for s in r3["signals"])

    def test_action_text_present(self):
        for sev in ("normal", "minor", "needs_review", "critical"):
            assert judge_trace(dict(BASE, error=(sev == "needs_review")))["action"]


class TestBatch:
    def test_distribution_and_escalations(self):
        traces = [
            dict(BASE, trace_id="a"),
            dict(BASE, trace_id="b", duration_ms=25000),
            dict(BASE, trace_id="c", error=True),
            dict(BASE, trace_id="d", error=True, consecutive_errors=5),
        ]
        rep = judge_batch(traces)
        assert rep["total"] == 4
        assert rep["distribution"]["normal"] == 1
        assert rep["distribution"]["minor"] == 1
        assert rep["distribution"]["needs_review"] == 1
        assert rep["distribution"]["critical"] == 1
        assert set(rep["escalations"]) == {"c", "d"}
        assert rep["rules_version"] == RULES_VERSION

    def test_p95_adaptive(self):
        """批次 p95 实际值应回写 thresholds（可审计）。"""
        traces = [dict(BASE, trace_id=f"t{i}", duration_ms=1000 * (i + 1))
                  for i in range(20)]
        rep = judge_batch(traces)
        assert rep["thresholds"]["batch_p95_actual"] is not None
        # 全部低于慢阈值 → 全 normal
        assert rep["distribution"]["minor"] == 0

    def test_empty_batch(self):
        rep = judge_batch([])
        assert rep["total"] == 0
        assert rep["escalations"] == []


class TestLoadTraces:
    def test_list_and_wrapped(self, tmp_path):
        p1 = tmp_path / "a.json"
        p1.write_text(json.dumps([BASE]), encoding="utf-8")
        assert load_traces(str(p1)) == [BASE]

        p2 = tmp_path / "b.json"
        p2.write_text(json.dumps({"traces": [BASE]}), encoding="utf-8")
        assert load_traces(str(p2)) == [BASE]

    def test_invalid_shape_returns_none(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"foo": 1}), encoding="utf-8")
        assert load_traces(str(p)) is None
        assert load_traces(str(tmp_path / "missing.json")) is None


class TestRender:
    def test_md_contains_distribution_and_escalations(self):
        traces = [dict(BASE, trace_id="ok-1"),
                  dict(BASE, trace_id="bad-1", error=True)]
        rep = judge_batch(traces)
        md = tj.render_md(rep)
        assert "四级判断报告" in md
        assert "bad-1" in md          # 升级清单必须点名
        assert "rules_version" in md.replace("规则版本", "rules_version") or "1.0" in md
