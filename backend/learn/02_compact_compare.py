"""② 压缩前后对比 —— 同一份历史，"存档" vs "发给模型的视图"。

运行：
    .venv\\Scripts\\python.exe learn\\02_compact_compare.py

重点看两件事：
1. 存档（完整记录）一条都没少
2. 视图（发给模型的）里，旧轮次的工具原始输出被剪掉了
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compact import compact_messages, validate_tool_pairs
from learn._common import load_thread_with_tools, preview  # noqa: E402


def show(messages, title: str) -> None:
    total = sum(len(str(m.content)) for m in messages)
    print(f"\n--- {title}：{len(messages)} 条消息 / {total} 字符 ---")
    for i, m in enumerate(messages):
        kind = type(m).__name__.replace("Message", "")
        n = len(str(m.content))
        calls = getattr(m, "tool_calls", None) or []
        extra = f" [调用工具 {len(calls)} 次]" if calls else ""
        print(f"  [{i:2d}] {kind:8s} {n:5d} 字符{extra}  {preview(m.content, 40)}")


def main() -> None:
    thread_id, messages = load_thread_with_tools()
    if not messages:
        return
    print(f"会话 {thread_id}")

    show(messages, "① 存档里的完整记录（checkpointer 里存的，永不修改）")

    view, stats = compact_messages(messages)
    show(view, "② 真正发给模型的压缩视图")

    d = stats.as_dict()
    print("\n--- 压缩统计 ---")
    print(f"  轮次数      : {d['turns_total']}  保留 {d['turns_kept']}  剪掉 {d['turns_dropped']}")
    print(f"  消息条数    : {d['messages_before']} → {d['messages_after']}")
    print(f"  字符数      : {d['chars_before']} → {d['chars_after']}   省了 {d['saved_ratio'] * 100:.0f}%")
    print(f"  截断的工具  : {d['tool_msgs_truncated']} 条")

    # 把 note 也打出来 —— 它会拼进 System Prompt，告诉模型"历史不完整"
    print("\n--- 拼进 System Prompt 的说明 ---")
    print("  " + (stats.note or "（无需提示：没剪枝）"))

    problems = validate_tool_pairs(view)
    print("\n--- 配对体检（必须为空，否则真实请求会 400）---")
    print("  " + ("OK，所有 tool_calls 与 ToolMessage 都成对" if not problems else str(problems)))


if __name__ == "__main__":
    main()
