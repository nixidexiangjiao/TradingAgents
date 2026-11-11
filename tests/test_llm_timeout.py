"""LLM 请求超时：防止 provider 挂起把 worker 永久卡死。"""

import pytest

pytest.importorskip("tradingagents")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402


def test_default_config_has_bounded_timeout():
    """默认必须有超时上限 —— OpenAI SDK 默认永不超时。"""
    assert DEFAULT_CONFIG.get("llm_timeout") is not None
    assert float(DEFAULT_CONFIG["llm_timeout"]) > 0


def test_env_override_changes_timeout(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_LLM_TIMEOUT", "42")
    from tradingagents.default_config import _apply_env_overrides

    cfg = _apply_env_overrides({**DEFAULT_CONFIG, "llm_timeout": 600})
    assert float(cfg["llm_timeout"]) == 42.0


def test_timeout_reaches_the_chat_client(monkeypatch):
    """timeout 必须真的落到 ChatOpenAI 实例上，否则等于没设。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    graph = TradingAgentsGraph(
        selected_analysts=("market",),
        debug=False,
        config={**DEFAULT_CONFIG, "llm_provider": "openai", "llm_timeout": 123.0},
    )
    assert float(graph.deep_thinking_llm.request_timeout) == 123.0
    assert float(graph.quick_thinking_llm.request_timeout) == 123.0


def test_timeout_can_be_disabled_by_empty_value(monkeypatch):
    """空值表示不覆盖 —— 让 provider 用自己的默认值。"""
    from tradingagents.default_config import _apply_env_overrides

    cfg = _apply_env_overrides({**DEFAULT_CONFIG, "llm_timeout": 600})
    assert cfg["llm_timeout"] == 600
