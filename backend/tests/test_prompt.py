"""System Prompt 外置的测试：模板能加载、占位符被替换、缺失文件时明确报错。

Prompt 是 Agent 的"人格"。它一旦悄悄变成空串或半截，模型的表现会莫名其妙地退化，
而且很难归因（你会以为是模型的问题、是网络的问题）。所以这里重点守两件事：
1. 文件真的加载到了，且不是空的
2. {{user_home}} 占位符确实被替换成了真实路径，而不是原样留在 Prompt 里
"""

from pathlib import Path

import pytest

from app import agent


def test_system_prompt_loads_non_empty():
    assert isinstance(agent.SYSTEM_PROMPT, str)
    assert len(agent.SYSTEM_PROMPT) > 200
    assert "CCLEAR" in agent.SYSTEM_PROMPT


def test_user_home_placeholder_is_replaced():
    """占位符必须被替换：模型看到的是真实路径，不是 {{user_home}} 字样。"""
    assert "{{user_home}}" not in agent.SYSTEM_PROMPT
    assert str(Path.home()) in agent.SYSTEM_PROMPT


def test_prompt_file_exists_and_readable():
    assert agent.PROMPT_FILE.exists()
    text = agent.PROMPT_FILE.read_text(encoding="utf-8")
    assert "{{user_home}}" in text  # 模板里保留占位符，替换发生在加载时


def test_missing_prompt_file_raises(monkeypatch, tmp_path):
    """模板缺失必须立刻炸，而不是让模型带着空人设上岗。"""
    missing = tmp_path / "nope.md"
    monkeypatch.setattr(agent, "PROMPT_FILE", missing)
    with pytest.raises(FileNotFoundError):
        agent._load_system_prompt()


def test_build_system_prompt_includes_profile_and_note(monkeypatch):
    """build_system_prompt 要把画像和压缩说明拼进去。"""
    monkeypatch.setattr("app.profile.prompt_section", lambda: "\n\n[画像占位]")
    prompt = agent.build_system_prompt("历史被压缩了")
    assert "[画像占位]" in prompt
    assert "上下文说明：历史被压缩了" in prompt


def test_build_system_prompt_empty_note_no_tail(monkeypatch):
    """note 为空时不该多出一句空的"上下文说明："。"""
    monkeypatch.setattr("app.profile.prompt_section", lambda: "")
    prompt = agent.build_system_prompt("")
    assert "上下文说明" not in prompt
