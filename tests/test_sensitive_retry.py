"""内容审核拦截（MiniMax 1027）的重试包装。"""

import pytest

from tradingagents.graph.sensitive_retry import (
    is_sensitive_rejection,
    with_sensitive_retry,
)


class FakeUnprocessableEntityError(Exception):
    """模拟 openai.UnprocessableEntityError（按类名匹配）。"""

    def __init__(self, message):
        super().__init__(message)
        self.__class__.__name__ = "UnprocessableEntityError"


def test_is_sensitive_rejection_detects_1027():
    exc = FakeUnprocessableEntityError("Error code: 422 - output new_sensitive (1027)")
    assert is_sensitive_rejection(exc)


def test_is_sensitive_rejection_ignores_other_errors():
    assert not is_sensitive_rejection(RuntimeError("boom"))
    assert not is_sensitive_rejection(FakeUnprocessableEntityError("Error code: 422 - token limit"))
    # 没有 422 状态码，不该当成审核拦截
    assert not is_sensitive_rejection(ValueError("output new_sensitive"))


def test_retry_on_sensitive_rejection_appends_guidance():
    seen_states = []

    def node(state):
        seen_states.append(state)
        if len(seen_states) == 1:
            raise FakeUnprocessableEntityError("Error code: 422 - output new_sensitive (1027)")
        return {"ok": True, "messages": state["messages"]}

    wrapped = with_sensitive_retry(node)
    out = wrapped({"messages": [{"role": "user", "content": "hi"}]})

    assert out["ok"] is True
    assert len(seen_states) == 2
    # 第一次是原状态，第二次追加了一条指引
    assert len(seen_states[0]["messages"]) == 1
    assert len(seen_states[1]["messages"]) == 2
    assert "客观中立" in seen_states[1]["messages"][-1]["content"]
    # 原 state 不被污染
    assert len(out["messages"]) == 2


def test_other_exceptions_propagate_without_retry():
    calls = []

    def node(state):
        calls.append(state)
        raise RuntimeError("network down")

    wrapped = with_sensitive_retry(node)
    with pytest.raises(RuntimeError, match="network down"):
        wrapped({"messages": []})
    assert len(calls) == 1


def test_sensitive_rejection_gives_up_after_max_attempts():
    calls = []

    def node(state):
        calls.append(state)
        raise FakeUnprocessableEntityError("Error code: 422 - output new_sensitive (1027)")

    wrapped = with_sensitive_retry(node, max_attempts=2)
    with pytest.raises(FakeUnprocessableEntityError):
        wrapped({"messages": []})
    assert len(calls) == 2


def test_node_result_passthrough():
    def node(state):
        return {"news_report": "内容"}

    wrapped = with_sensitive_retry(node)
    assert wrapped({"messages": []}) == {"news_report": "内容"}
