"""① 看清"消息"到底长什么样 —— 打印一个真实会话的原始消息结构。

运行方式（在 backend 目录下）：
    .venv\\Scripts\\python.exe learn\\01_messages_dump.py

你会看到每一轮 Agent 内部到底存了哪些消息、它们之间靠什么 id 对应。
这是理解"工具原始输出""tool_calls""ToolMessage"最直观的方式。
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

DB = Path(__file__).resolve().parents[1] / "data" / "cclear.db"


def load_latest_states() -> dict[str, list]:
    """读出每个会话的最新消息列表（这就是 checkpointer 里存的"完整记录"）。"""
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
        msgs = (cp.get("channel_values") or {}).get("messages") or []
        latest[thread_id] = msgs  # 后写的覆盖先写的 → 留下最新一份
    return latest


def preview(text: str, n: int = 70) -> str:
    text = str(text).replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "")


def dump(thread_id: str, messages: list) -> None:
    print("=" * 78)
    print(f"会话 thread_id = {thread_id}")
    print(f"共 {len(messages)} 条消息")
    print("=" * 78)
    for i, m in enumerate(messages):
        kind = type(m).__name__
        print(f"\n[{i}] {kind}   msg_id={getattr(m, 'id', None)}")

        if kind == "AIMessage":
            calls = getattr(m, "tool_calls", None) or []
            if calls:
                for c in calls:
                    # 关键：每一批工具调用都带一个唯一的 id
                    print(f"    要调用工具: name={c.get('name')}  tool_call_id={c.get('id')}")
                    print(f"    参数: {c.get('args')}")
            if m.content:
                print(f"    正文({len(str(m.content))} 字符): {preview(m.content)}")

        elif kind == "ToolMessage":
            # 关键：ToolMessage 用 tool_call_id 回去认领"我是谁调出来的"
            print(f"    工具返回 tool_call_id={getattr(m, 'tool_call_id', None)}")
            print(f"    工具名={getattr(m, 'name', None)}")
            print(f"    内容({len(str(m.content))} 字符) ← 这就是【工具原始输出】")
            print(f"    {preview(m.content, 120)}")
            art = getattr(m, "artifact", None)
            if art:
                print(f"    附带结构化数据 artifact.kind={art.get('kind')}（给图表用，不进 Prompt）")

        else:
            print(f"    {preview(m.content, 100)}")
    print()


def main() -> None:
    if not DB.exists():
        print(f"还没对话记录：{DB} 不存在。先启动后端聊几句再来。")
        return

    states = load_latest_states()
    if not states:
        print("没有可读的快照，先聊几句。")
        return

    # 优先挑"带工具调用"的会话，那才能看到 ToolMessage
    def has_tool(msgs: list) -> bool:
        return any(type(m).__name__ == "ToolMessage" for m in msgs)

    candidates = [(tid, msgs) for tid, msgs in states.items() if has_tool(msgs)]
    candidates.sort(key=lambda x: len(x[1]), reverse=True)

    if candidates:
        dump(*candidates[0])
        print(f"（另有 {len(candidates) - 1} 个会话也含工具调用，改脚本里的索引可看别的）")
    else:
        print("没有含工具调用的会话，先让它扫描一次目录。")
        dump(*next(iter(states.items())))


if __name__ == "__main__":
    main()
