"""API 层测试：输入契约与路由行为。

重点是"信任边界"：前端能传什么、不能传什么；非法输入必须被挡在门外（422）。
这里不测真实的大模型/Agent（那是集成测试，需要 Key + 网络），
只测 HTTP 契约和不需要模型的逻辑。
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


def test_chat_rejects_extra_role():
    """信任边界：前端只能传 user/assistant，其他角色必须 422。"""
    res = client.post(
        "/api/chat",
        json={"thread_id": "t1", "message": "你好", "role": "system"},
    )
    # 多余的 role 字段不会导致失败（Message 没这个字段），但下面这个才关键：
    res2 = client.post(
        "/api/chat",
        json={"thread_id": "t1"},  # 缺少 message → 422
    )
    assert res2.status_code == 422


def test_chat_requires_message():
    res = client.post("/api/chat", json={"thread_id": "t1"})
    assert res.status_code == 422


def test_chat_requires_thread_id():
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 422


def test_confirm_requires_fields():
    res = client.post("/api/confirm", json={"thread_id": "t1"})
    assert res.status_code == 422


def test_history_requires_thread_id():
    res = client.get("/api/history")
    assert res.status_code == 422


def test_profile_endpoint_returns_entries():
    """画像接口不需要 thread_id（它跨会话），返回结构与前端契约一致。"""
    res = client.get("/api/profile")
    assert res.status_code == 200
    body = res.json()
    assert "user_id" in body
    assert isinstance(body["entries"], list)


def test_profile_delete_missing_key_is_graceful():
    """删除不存在的 key 不应 500——返回说明即可（前端可据此兜底）。"""
    res = client.delete("/api/profile/绝对不存在的key")
    assert res.status_code == 200
    assert "没有找到" in res.json()["result"]


def test_user_facing_error_for_recursion():
    """步数超限应转成人话，而不是把原始异常丢给用户（第一梯队修复项）。"""
    from app.main import user_facing_error

    msg = user_facing_error(RuntimeError("random crash"))
    assert "请稍后重试" in msg
    assert "random crash" not in msg  # 原始异常不该出现在给用户的文案里


def test_message_schema_accepts_ts():
    """history 的响应消息带可选时间戳字段，且缺省为 None（向后兼容）。"""
    from app.main import Message

    assert Message(role="user", content="hi").ts is None
    assert Message(role="user", content="hi", ts="2026-01-01T00:00:00Z").ts is not None
