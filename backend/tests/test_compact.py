"""压缩模块测试：这是最容易引入"隐蔽 bug"的地方（消息配对断裂）。"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import compact
from app.compact import compact_messages, validate_tool_pairs


def _turn(i: int, tool_chars: int = 200) -> list:
    return [
        HumanMessage(content=f"第{i}轮问题"),
        AIMessage(content="", tool_calls=[{"name": "scan", "args": {}, "id": f"c{i}"}]),
        ToolMessage(content="x" * tool_chars, tool_call_id=f"c{i}", name="scan"),
        AIMessage(content=f"第{i}轮结论"),
    ]


def _history(n: int, tool_chars: int = 200) -> list:
    msgs: list = []
    for i in range(1, n + 1):
        msgs.extend(_turn(i, tool_chars))
    return msgs


def test_no_compaction_when_turns_within_limit():
    msgs = _history(2)
    out, stats = compact_messages(msgs, keep_turns=4)
    assert stats.turns_dropped == 0
    assert out == msgs


def test_old_turns_keep_only_question_and_conclusion():
    msgs = _history(6)
    out, stats = compact_messages(msgs, keep_turns=2, max_tool_chars=50)
    assert stats.turns_dropped == 4
    # 前 4 轮只剩 Human + 最终 AI，共 8 条
    humans = [m for m in out if isinstance(m, HumanMessage)]
    assert len(humans) == 6
    old_tool_msgs = [m for m in out if isinstance(m, ToolMessage) and str(m.content).startswith("第")]
    assert old_tool_msgs == []


def test_last_turn_is_never_modified():
    """最关键的不变量：当前正在进行的这一轮，工具输出必须原样保留。"""
    msgs = _history(6, tool_chars=5000)
    out, _ = compact_messages(msgs, keep_turns=2, max_tool_chars=100)
    last_tool = [m for m in out if isinstance(m, ToolMessage)][-1]
    assert len(str(last_tool.content)) == 5000  # 一点没动


def test_older_recent_turns_get_tool_truncated():
    msgs = _history(6, tool_chars=5000)
    out, stats = compact_messages(msgs, keep_turns=3, max_tool_chars=100)
    assert stats.tool_msgs_truncated >= 1
    # 单行长文本走"单行过长"分支；多行走"输出过长"分支
    assert "过长" in str([m for m in out if isinstance(m, ToolMessage)][0].content)


def test_truncation_never_cuts_a_line_in_half():
    """核心要求：按行截断——每一行都必须完整，绝不能出现半截路径。

    这是真实 bug 的回归测试：原来用 content[:limit] 把
    `C:\\...\\Ollama\\...` 切成了 `C:\\...\\Ollam`，模型会误判。
    """
    lines = [f"- {i:3d}.0 MB  C:\\Users\\ASUS\\some\\long\\path\\file_{i}.bin" for i in range(60)]
    content = "\n".join(lines)

    truncated = compact._truncate_text(content, 500)
    body_lines = truncated.split("\n")

    # 最后一行必须是提示语，前面每一行都得是原文里的完整行
    assert body_lines[-1].startswith("…（输出过长")
    for line in body_lines[:-1]:
        assert line in lines, f"出现残缺行: {line!r}"


def test_truncation_reports_remaining_line_count():
    """要告诉模型"还剩多少行"——它才知道数据不完整。"""
    content = "\n".join(f"line-{i}" for i in range(100))
    out = compact._truncate_text(content, 60)
    assert "行未显示" in out
    # 行数统计要对得上
    kept = out.split("\n")[:-1]
    assert f"{100 - len(kept)} 行未显示" in out


def test_short_content_not_touched():
    content = "完整的一行\n第二行"
    assert compact._truncate_text(content, 1500) == content


def test_single_huge_line_falls_back_with_warning():
    """一行就超限（如压缩成单行的 JSON）时只能按字符切，但必须标注清楚。"""
    out = compact._truncate_text("x" * 3000, 100)
    assert "单行过长" in out
    assert len(out) > 100  # 含提示语


def test_tool_pairs_never_break():
    """压缩后必须通过配对体检——否则 API 会直接 400。"""
    for n in (1, 3, 5, 10):
        for keep in (1, 2, 4):
            msgs = _history(n)
            out, _ = compact_messages(msgs, keep_turns=keep, max_tool_chars=50)
            assert validate_tool_pairs(out) == [], f"n={n} keep={keep} 配对断裂"


def test_validate_tool_pairs_detects_orphan_tool_message():
    """体检函数本身要有效：孤儿 ToolMessage 必须被抓出来。"""
    broken = [ToolMessage(content="x", tool_call_id="missing", name="scan")]
    assert validate_tool_pairs(broken)


def test_validate_tool_pairs_detects_unanswered_tool_call():
    broken = [
        AIMessage(content="", tool_calls=[{"name": "scan", "args": {}, "id": "nope"}]),
    ]
    assert validate_tool_pairs(broken)


def test_truncation_preserves_tool_call_id():
    """截断时若丢了 tool_call_id，配对就断了——这条专门守它。"""
    msgs = _turn(1, tool_chars=1000)
    out, _ = compact_messages(msgs, keep_turns=1, max_tool_chars=20)
    tool = [m for m in out if isinstance(m, ToolMessage)][0]
    assert tool.tool_call_id == "c1"


def test_saved_ratio_reported():
    msgs = _history(8, tool_chars=2000)
    _, stats = compact_messages(msgs, keep_turns=2, max_tool_chars=100)
    assert stats.chars_after < stats.chars_before
    assert stats.as_dict()["saved_ratio"] > 0.5


def test_compaction_disabled_returns_original(monkeypatch):
    monkeypatch.setattr(compact, "COMPACT_ENABLED", False)
    msgs = _history(10, tool_chars=3000)
    out, stats = compact_messages(msgs, keep_turns=1, max_tool_chars=10)
    assert out == msgs
    assert stats.turns_dropped == 0


def test_empty_history_is_safe():
    """边界：空历史不能让压缩逻辑炸掉（这正是"仅供模型用"的守卫路径）。"""
    out, stats = compact_messages([], keep_turns=4)
    assert out == []
    assert stats.messages_before == 0


def test_note_only_when_dropped():
    _, stats_small = compact_messages(_history(1), keep_turns=4)
    assert stats_small.note == ""
    _, stats_big = compact_messages(_history(6), keep_turns=2)
    assert "压缩" in stats_big.note
