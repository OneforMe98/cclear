"""用户画像：跨会话记住"这个人是什么样"。

与 checkpointer 的分工（重要，别混）：
- checkpointer 按 thread_id 存 → "这次聊了什么"（会话记忆，换会话就看不见）
- 画像按 user_id 存           → "这个人什么样"（长期记忆，跨会话可见，注入每次的 System Prompt）

实现刻意做得小而稳：一张 key-value 表 + 进程内缓存。

为什么要有缓存：
每轮对话都要把画像拼进 System Prompt。如果每次都查库，就是把一次本地 IO
放进最热的路径；而画像数据量极小（几十条），缓存在内存里成本几乎为零。
写入时同步更新缓存，所以"读永远是最新的"。

为什么不用向量库：
现在的画像是结构化的"偏好键值对"（阈值、禁区、习惯）。
键值对能精确命中、可读、可让人直接改——比向量检索更合适。
向量库适合"语义模糊检索"，那是另一个问题，别为了高级而高级。
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import PROFILE_DB, PROFILE_USER_ID

# 上限保护：画像会被拼进每一轮 Prompt，无节制增长会吃掉上下文和 token
MAX_PREFS = 50
MAX_KEY_LEN = 48
MAX_VALUE_LEN = 400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
)
"""

_db_path: Path | None = None
_cache: dict[str, str] = {}  # key -> value，进程内缓存


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    global _db_path
    if _db_path is None:  # 兜底：忘记 init 时按默认路径自初始化，而不是抛异常
        init(PROFILE_DB)
    assert _db_path is not None
    conn = sqlite3.connect(_db_path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")  # 允许读写并发，减少锁冲突
    return conn


def init(db_path: Path) -> None:
    """应用启动时调用：建表并把画像读进缓存。"""
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(_SCHEMA)
    _reload()


def _reload() -> None:
    """从数据库重新加载缓存（启动时、以及任何写入之后）。"""
    _cache.clear()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value FROM preferences WHERE user_id = ? ORDER BY key",
            (PROFILE_USER_ID,),
        ).fetchall()
    for key, value in rows:
        _cache[key] = value


def snapshot() -> dict[str, str]:
    """当前画像的只读快照（给 System Prompt 和 API 用）。"""
    return dict(_cache)


def get_all() -> list[dict]:
    """给前端展示用：带更新时间的完整列表。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value, updated_at FROM preferences WHERE user_id = ? ORDER BY key",
            (PROFILE_USER_ID,),
        ).fetchall()
    return [{"key": k, "value": v, "updated_at": u} for k, v, u in rows]


def set_preference(key: str, value: str) -> str:
    """记住一条偏好。返回给模型看的结果说明。"""
    key = (key or "").strip()
    value = (value or "").strip()
    if not key or not value:
        return "偏好需要同时提供 key 和 value，本次未记录。"
    if len(key) > MAX_KEY_LEN:
        return f"key 太长（上限 {MAX_KEY_LEN} 字符），请用简短的短标签，如「大文件阈值」。"
    if len(value) > MAX_VALUE_LEN:
        return f"value 太长（上限 {MAX_VALUE_LEN} 字符），请提炼成一句话。"

    is_new = key not in _cache
    if is_new and len(_cache) >= MAX_PREFS:
        return f"画像条目已达上限 {MAX_PREFS} 条。请先用 forget_preference 清理不再需要的偏好。"

    with _connect() as conn:
        conn.execute(
            "INSERT INTO preferences (user_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (PROFILE_USER_ID, key, value, _now()),
        )
    _cache[key] = value
    return f"已{'记住' if is_new else '更新'}偏好「{key}」= {value}（当前共 {len(_cache)} 条）。"


def forget_preference(key: str) -> str:
    """忘掉一条偏好。"""
    key = (key or "").strip()
    if key not in _cache:
        existing = "、".join(sorted(_cache)) or "（空）"
        return f"没有找到偏好「{key}」。当前已有的偏好：{existing}"

    with _connect() as conn:
        conn.execute(
            "DELETE FROM preferences WHERE user_id = ? AND key = ?", (PROFILE_USER_ID, key)
        )
    _cache.pop(key, None)
    return f"已忘记偏好「{key}」（剩余 {len(_cache)} 条）。"


def prompt_section() -> str:
    """把画像渲染成要注入 System Prompt 的一段文字。空画像返回空串。"""
    if not _cache:
        return ""
    lines = [f"- {k}：{v}" for k, v in sorted(_cache.items())]
    return (
        "\n\n用户长期偏好（来自此前会话的记录，与本轮对话无关时不要强行套用）：\n"
        + "\n".join(lines)
        + "\n\n这些偏好是重要参考：给建议时优先遵守它们；如与用户本轮明确要求冲突，以本轮要求为准。\n"
        "当用户表达新的长期偏好（例如「以后 500MB 以上再问我」「永远别删我的下载文件夹」），"
        "用 remember_preference 记下来；用户说不用记了，用 forget_preference 删掉。"
    )
