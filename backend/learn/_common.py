"""learn 目录共用的读取工具。"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

DB = Path(__file__).resolve().parents[1] / "data" / "cclear.db"


def preview(text, n: int = 60) -> str:
    text = str(text).replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "" if text else "")


def load_all_states() -> dict[str, list]:
    """读每个会话最新的消息列表。"""
    if not DB.exists():
        print(f"没有对话记录：{DB}")
        return {}
    serde = JsonPlusSerializer()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT thread_id, checkpoint FROM checkpoints ORDER BY rowid").fetchall()
    latest: dict[str, list] = {}
    for thread_id, blob in rows:
        try:
            cp = serde.loads_typed(("msgpack", blob)) if isinstance(blob, bytes) else None
        except Exception:
            continue
        if cp is None:
            continue
        latest[thread_id] = (cp.get("channel_values") or {}).get("messages") or []
    return latest


def load_thread_with_tools() -> tuple[str, list]:
    """挑一个含工具调用、消息最多的会话。"""
    states = load_all_states()
    has_tool = {tid: msgs for tid, msgs in states.items() if any(type(m).__name__ == "ToolMessage" for m in msgs)}
    if not has_tool:
        print("没有含工具调用的会话。先启动后端，让它扫描一次目录。")
        return "", []
    tid = max(has_tool, key=lambda k: len(has_tool[k]))
    return tid, has_tool[tid]
