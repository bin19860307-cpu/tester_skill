# -*- coding: utf-8 -*-
"""Bug 预测区块不得落到 HTML 文档之外。"""

from gen_bug_predict import (
    COMBINED_END,
    COMBINED_START,
    END,
    START,
    inject,
    inject_combined,
)


def _assert_inside_document(html, start, end):
    assert html.index(start) < html.lower().index("</body>")
    assert html.index(end) < html.lower().index("</body>")
    assert html.lower().index("</body>") < html.lower().index("</html>")


def test_single_fallback_is_inside_document_and_idempotent():
    base = "<html><body><main>单服务报告</main></body></html>"
    fragment = f"{START}<div>预测</div>{END}"
    once = inject(base, fragment)
    twice = inject(once, fragment)

    _assert_inside_document(once, START, END)
    assert twice.count(START) == 1
    assert twice.count(END) == 1


def test_combined_fallback_is_inside_document_and_idempotent():
    base = "<html><body><main>综合报告</main></body></html>"
    fragment = f"{COMBINED_START}<div>汇总预测</div>{COMBINED_END}"
    once = inject_combined(base, fragment)
    twice = inject_combined(once, fragment)

    _assert_inside_document(once, COMBINED_START, COMBINED_END)
    assert twice.count(COMBINED_START) == 1
    assert twice.count(COMBINED_END) == 1
