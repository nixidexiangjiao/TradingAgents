"""内容审核拦截的容错包装。

MiniMax 的内容安全过滤会对**输出**做拦截，错误码 1027（``output new_sensitive``），
HTTP 422。官方说明是「修改 prompt 或上下文」，不支持原样重试。

实际表现是偶发的：同样的输入有时通过、有时被拦。被拦的那一次通常发生在
分析师写长报告时 —— 报告里复述了新闻里的敏感措辞，触发了输出侧过滤。

这里的处理方式是：捕获 1027，往消息历史里追加一条"保持客观中立、避免复述敏感
措辞"的指引，然后重跑同一个节点。因为模型上下文变了、措辞变了，重试通常能过；
实在过不了的，最后一次抛原始异常。

只用在这类明确的审核错误上，不吞掉其他异常（网络错误、解析错误照常抛出）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

# MiniMax 返回体里的形态：
#   "Error code: 422 - output new_sensitive (1027)"
#   {"type": "error", "error": {"message": "output new_sensitive (1027)", "http_code": 422}}

# 重试时追加的指引：让模型改用中性、克制的表述，而不是复述原文措辞。
_RETRY_GUIDANCE = (
    "注意：请保持客观中立，只陈述可核实的事实与市场影响，"
    "避免复述新闻原文中可能引起歧义或不适的措辞，"
    "改用中性、克制的财经表述。不要提及本条提示。"
)


def is_sensitive_rejection(exc: BaseException) -> bool:
    """True when the exception is a content-safety rejection (MiniMax 1027).

    Requires the 1027 marker *and* a 422 status — a bare mention of
    "sensitive" in an unrelated message must not trigger a retry.
    """
    text = str(exc)
    if "1027" not in text and "output new_sensitive" not in text.lower():
        return False
    return "422" in text or "unprocessable" in text.lower()


def with_sensitive_retry(node: Callable[[dict], Any], max_attempts: int = 2) -> Callable[[dict], Any]:
    """Wrap a graph node so a 1027 content-safety rejection is retried once.

    The retry appends a short neutrality instruction to the message history and
    re-invokes the node. Everything else behaves exactly like the original node.
    """

    def wrapped(state: dict) -> Any:
        attempt = 0
        current = state
        while True:
            try:
                return node(current)
            except Exception as exc:  # noqa: BLE001 — re-raised below
                attempt += 1
                if attempt >= max_attempts or not is_sensitive_rejection(exc):
                    raise
                log.warning(
                    "content-safety rejection (1027) on node %s — retrying with a neutrality hint",
                    getattr(node, "__name__", node),
                )
                current = _with_guidance(current)

    return wrapped


def _with_guidance(state: dict) -> dict:
    """Return a copy of the state with a neutrality hint appended to messages."""
    messages = list(state.get("messages") or [])
    guidance = {"role": "user", "content": _RETRY_GUIDANCE}
    new_state = dict(state)
    new_state["messages"] = messages + [guidance]
    return new_state
