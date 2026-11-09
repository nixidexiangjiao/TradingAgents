"""集成验证：真实图里的分析师节点遇到 1027 审核拦截会重试并恢复。"""

import pytest

pytest.importorskip("tradingagents")

from tradingagents.graph.sensitive_retry import with_sensitive_retry  # noqa: E402


class FakeUnprocessableEntityError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.__class__.__name__ = "UnprocessableEntityError"


def test_wrapped_node_recovers_after_1027():
    """节点第一次抛 1027，第二次成功 —— 包装后整轮不应中断。"""

    calls = []

    def node(state):
        calls.append(state)
        if len(calls) == 1:
            raise FakeUnprocessableEntityError("Error code: 422 - output new_sensitive (1027)")
        return {"news_report": "中性表述的报告", "messages": state["messages"]}

    wrapped = with_sensitive_retry(node)
    result = wrapped({"messages": [{"role": "user", "content": "分析新闻"}]})

    assert result["news_report"] == "中性表述的报告"
    assert len(calls) == 2
    # 重试时上下文变了：多了一条中立化指引
    assert len(calls[0]["messages"]) == 1
    assert len(calls[1]["messages"]) == 2


def test_wrapped_node_propagates_after_exhausting_retries():
    """连续 1027 时最终仍抛原始异常，不静默吞掉。"""

    calls = []

    def node(state):
        calls.append(state)
        raise FakeUnprocessableEntityError("Error code: 422 - output new_sensitive (1027)")

    wrapped = with_sensitive_retry(node, max_attempts=2)
    with pytest.raises(FakeUnprocessableEntityError):
        wrapped({"messages": []})
    assert len(calls) == 2


def test_wrapper_is_transparent_for_normal_nodes():
    """正常节点的行为完全不变。"""

    def node(state):
        return {"market_report": "技术面正常", "messages": []}

    wrapped = with_sensitive_retry(node)
    assert wrapped({"messages": []}) == {"market_report": "技术面正常", "messages": []}
