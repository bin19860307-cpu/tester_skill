# -*- coding: utf-8 -*-
"""gen_p1_cases 的动态版本与 HTML 注入回归测试。"""

from gen_p1_cases import END, START, inject, render


def _data(version="5.3"):
    return {
        "kb_check": {
            "target_version": version,
            "kb_location": (
                f"D:/Obsidian知识库/knowledge/初发项目/v{version}/"
                f"03-测试用例/工作台/工作台_v{version}_测试用例.md"
            ),
            "note": "已逐条核对",
            "hit_count": 1,
            "est_count": 0,
        },
        "groups": [],
    }


def test_render_uses_dynamic_target_version():
    html = render(_data("5.4"))
    assert "定位到 v5.4 用例集" in html
    assert "定位到 v5.2 用例集" not in html


def test_render_can_infer_version_from_location():
    data = _data("5.6")
    data["kb_check"].pop("target_version")
    html = render(data)
    assert "定位到 v5.6 用例集" in html


def test_fallback_injects_before_body_and_is_idempotent():
    base = "<html><body><main>综合报告</main></body></html>"
    fragment = render(_data())

    once = inject(base, fragment)
    twice = inject(once, fragment)

    assert once.index(START) < once.lower().index("</body>")
    assert once.index(END) < once.lower().index("</body>")
    assert once.lower().index("</body>") < once.lower().index("</html>")
    assert once.count("P1 用例预测（基于影响范围）") == 1
    assert twice.count(START) == 1
    assert twice.count(END) == 1
    assert twice.count("P1 用例预测（基于影响范围）") == 1


def test_placeholder_does_not_add_duplicate_heading():
    base = "<html><body><h2>P1</h2><!-- P1_CASES_SECTION --></body></html>"
    out = inject(base, render(_data()))
    assert "P1_CASES_SECTION" not in out
    assert out.count(START) == 1
    assert "🎯 P1 用例预测（基于影响范围）" not in out
