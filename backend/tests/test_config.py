"""配置层测试：确认参数可以从环境变量覆盖（"参数入配置"的验收）。

这里只关心"默认值正确 + 能被覆盖"，不测具体业务。
"""

import importlib

from app import config


def test_temperature_default_is_low():
    # 清理建议类任务适合偏低温度，默认 0.3
    assert 0.0 <= config.MODEL_TEMPERATURE <= 1.0


def test_max_steps_default_is_sane():
    # 太小会误伤正常多步任务，太大有死循环风险
    assert 4 <= config.AGENT_MAX_STEPS <= 40


def test_config_reads_env_override(monkeypatch):
    monkeypatch.setenv("MODEL_TEMPERATURE", "0.85")
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MODEL_TEMPERATURE == 0.85
        assert reloaded.AGENT_MAX_STEPS == 7
    finally:
        # 还原，避免影响其它测试导入到的模块状态
        monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
        monkeypatch.delenv("AGENT_MAX_STEPS", raising=False)
        importlib.reload(config)


def test_agent_uses_config_temperature():
    """agent.MAX_STEPS 应与配置同源，避免两处各写一个数字。"""
    from app import agent

    assert agent.MAX_STEPS == config.AGENT_MAX_STEPS


def test_langsmith_disabled_by_default():
    """默认必须是关闭的——追踪会把对话内容上传云端，不能默认开。"""
    assert config.LANGSMITH_ENABLED is False


def test_langsmith_requires_both_switch_and_key(monkeypatch):
    """只开开关没填 Key、或只填 Key 没开开关，都不该启用（避免半配状态）。"""
    # 只有开关，没有 Key
    monkeypatch.setenv("LANGSMITH_TRACING", "1")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    reloaded = importlib.reload(config)
    assert reloaded.LANGSMITH_ENABLED is False

    # 只有 Key，没有开关
    monkeypatch.setenv("LANGSMITH_TRACING", "0")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_fake")
    reloaded = importlib.reload(config)
    assert reloaded.LANGSMITH_ENABLED is False

    # 两者齐备 → 启用
    monkeypatch.setenv("LANGSMITH_TRACING", "1")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_fake")
    reloaded = importlib.reload(config)
    assert reloaded.LANGSMITH_ENABLED is True
    # 且必须写回环境变量，LangChain 才认（它读 os.environ，不读 Python 变量）
    import os

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_pt_fake"

    # 还原
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(config)


def test_langsmith_off_clears_env(monkeypatch):
    """关闭时必须显式写回 false——防止"上次开过、这次忘了关"导致悄悄上报。"""
    import os

    monkeypatch.setenv("LANGSMITH_TRACING", "0")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    reloaded = importlib.reload(config)
    assert reloaded.LANGSMITH_ENABLED is False
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"

    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    importlib.reload(config)
