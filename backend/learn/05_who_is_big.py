"""⑤ 到底谁在占上下文？——把"人和人聊天"vs"工具输出"分开统计。

运行：
    .venv\\Scripts\\python.exe learn\\05_who_is_big.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compact import compact_messages
from learn._common import load_all_states  # noqa: E402
from app.tools import find_large_files, scan_directory_size


def kind_of(m) -> str:
    name = type(m).__name__
    if name == "HumanMessage":
        return "你打的字"
    if name == "AIMessage":
        return "AI 说的话"
    if name == "ToolMessage":
        return "工具原始输出"
    return name


def main() -> None:
    states = load_all_states()
    if not states:
        return

    buckets: dict[str, list[int]] = {}
    for msgs in states.values():
        for m in msgs:
            k = kind_of(m)
            buckets.setdefault(k, []).append(len(str(m.content)))

    print("=== 现有全部会话（16 个）里各类消息的体积 ===")
    total = sum(sum(v) for v in buckets.values()) or 1
    for k, vals in sorted(buckets.items(), key=lambda x: -sum(x[1])):
        s = sum(vals)
        print(
            f"  {k:10s} 条数={len(vals):3d}  合计={s:6d} 字符  占比={s / total * 100:5.1f}%  "
            f"平均={s // len(vals):4d}  最大={max(vals):5d}"
        )

    print("\n=== 单条工具输出能有多大（真实扫描，limit 越大越夸张）===")
    home = str(Path.home())
    for limit in (20, 50, 100):
        out = find_large_files.func(directory=home, min_size_mb=50, limit=limit)
        text = out if isinstance(out, str) else out[0]
        print(f"  find_large_files(limit={limit:3d}) → {len(text):6d} 字符   {text.count(chr(10)) + 1:4d} 行")
    out = scan_directory_size.func(path=home)
    text = out if isinstance(out, str) else out[0]
    print(f"  scan_directory_size(home)      → {len(text):6d} 字符")

    print("\n=== 一个典型会话：压缩前 vs 压缩后 ===")
    tid, msgs = max(states.items(), key=lambda x: len(x[1]))
    before = {}
    for m in msgs:
        k = kind_of(m)
        before[k] = before.get(k, 0) + len(str(m.content))
    _, stats = compact_messages(msgs)
    print(f"  会话 {tid}（{len(msgs)} 条）")
    for k, v in sorted(before.items(), key=lambda x: -x[1]):
        print(f"    {k:10s} {v:6d} 字符")
    print(f"  压缩后总字符: {stats.chars_after}（原 {stats.chars_before}，省 {stats.as_dict()['saved_ratio'] * 100:.0f}%）")

    print(
        "\n结论：\n"
        "  · 你打的字通常只有几十字符，AI 的回答几百字符\n"
        "  · 工具原始输出平均和 AI 回答差不多，但【上限极高】：一条能到上万字符\n"
        "  · 所以「对话历史太长」不是真问题，「某一条工具输出极长 + 每轮都被重发」才是\n"
    )


if __name__ == "__main__":
    main()
