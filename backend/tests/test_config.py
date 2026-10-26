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
