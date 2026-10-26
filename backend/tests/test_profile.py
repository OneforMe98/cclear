"""用户画像测试：存取、上限、注入、以及"跨会话记住"的关键契约。"""

import pytest

from app import profile


@pytest.fixture(autouse=True)
def fresh_profile(tmp_path):
    """每个测试用独立的临时库，避免污染真实画像文件。"""
    profile.init(tmp_path / "profile.db")
    yield
    profile._cache.clear()


def test_set_and_get_preference():
    msg = profile.set_preference("大文件阈值", "500MB 以上才提醒我")
    assert "已记住" in msg
    assert profile.snapshot() == {"大文件阈值": "500MB 以上才提醒我"}


def test_overwrite_same_key_updates_value():
    profile.set_preference("大文件阈值", "500MB")
    msg = profile.set_preference("大文件阈值", "1GB")
    assert "已更新" in msg
    assert profile.snapshot()["大文件阈值"] == "1GB"
    assert len(profile.get_all()) == 1  # 同 key 不会产生第二条


def test_forget_preference():
    profile.set_preference("禁区", "别删下载文件夹")
    msg = profile.forget_preference("禁区")
    assert "已忘记" in msg
    assert profile.snapshot() == {}


def test_forget_missing_lists_existing_keys():
    """忘错了要能自愈：告诉模型现有哪些 key，它才能纠正。"""
    profile.set_preference("大文件阈值", "500MB")
    msg = profile.forget_preference("不存在的key")
    assert "没有找到" in msg
    assert "大文件阈值" in msg


def test_empty_key_or_value_rejected():
    assert "未记录" in profile.set_preference("", "值")
    assert "未记录" in profile.set_preference("键", "   ")


def test_value_too_long_rejected():
    assert "太长" in profile.set_preference("键", "x" * (profile.MAX_VALUE_LEN + 1))


def test_max_prefs_enforced():
    for i in range(profile.MAX_PREFS):
        assert "已记住" in profile.set_preference(f"k{i}", f"v{i}")
    msg = profile.set_preference("overflow", "多余")
    assert "上限" in msg
    assert "overflow" not in profile.snapshot()


def test_prompt_section_empty_when_no_prefs():
    """空画像不能往 Prompt 里塞空标题——那只会浪费 token 并干扰模型。"""
    assert profile.prompt_section() == ""


def test_prompt_section_contains_all_prefs():
    profile.set_preference("大文件阈值", "500MB")
    profile.set_preference("禁区", "别删下载文件夹")
    text = profile.prompt_section()
    assert "大文件阈值：500MB" in text
    assert "禁区：别删下载文件夹" in text
    assert "用户长期偏好" in text


def test_persistence_survives_reinit(tmp_path):
    """关键契约：画像必须跨会话/跨重启存在——这才是"长期记忆"。"""
    db = tmp_path / "p.db"
    profile.init(db)
    profile.set_preference("大文件阈值", "500MB")

    profile._cache.clear()  # 模拟进程重启（内存缓存没了）
    profile.init(db)        # 重新从磁盘加载
    assert profile.snapshot() == {"大文件阈值": "500MB"}


def test_system_prompt_injects_profile():
    """端到端契约：agent 构建的 System Prompt 里必须带上画像。"""
    from app.agent import build_system_prompt

    profile.set_preference("大文件阈值", "500MB 以上才提醒我")
    prompt = build_system_prompt()
    assert "用户长期偏好" in prompt
    assert "500MB 以上才提醒我" in prompt
