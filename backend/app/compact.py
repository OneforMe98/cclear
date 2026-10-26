"""上下文压缩（记忆压缩）：让长对话不撑爆上下文，又不丢关键信息。

先讲清楚它和"用户画像"的区别：
- 用户画像：跨会话的"长期偏好"（人是不吃香菜）
- 上下文压缩：**同一个会话内**，把"越来越长的历史"压小（这顿饭吃到哪了）

核心原则（最重要的一条）：
    压缩只发生在"发给模型之前"，**绝不修改 checkpointer 里的存档**。

为什么？因为存档要同时服务三件事：
1. /api/history —— 用户刷新页面看到的完整聊天记录
2. interrupt / resume —— 用户点"确认删除"时，图要从存档里恢复现场
3. 可追溯 —— 出了问题能查"当时模型到底看到了什么"
如果我们把存档改小了，这三件事全部受损。所以压缩是"视图层"的事：
    存档（完整真相）──压缩视图──> 发给模型的 messages

两层压缩策略：
① 旧轮次剪枝：更早的轮次只保留"用户问了什么 + 最终结论"，丢掉工具原始输出
   和中间过程。理由：最终回答本身就是对那堆数据的提炼，原始清单已经冗余。
② 工具输出限长：保留下来的工具输出超过上限就截断，并注明"已截断"。
   实测一次 find_large_files(limit=100) 能输出 1 万字符，不设限很危险。

一个必须守住的正确性约束（LangGraph / OpenAI API 都要求）：
    AIMessage(tool_calls) 和它的 ToolMessage **必须成对存在**。
    - 只留 ToolMessage 不留 AIMessage(tool_calls) → API 直接报错
    - 只留 AIMessage(tool_calls) 不留 ToolMessage → API 直接报错
所以剪枝只能"整段丢弃"（AIMessage + 它所有 ToolMessage 一起丢），
`validate_tool_pairs()` 就是用来验证这条不变量的。
"""

from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from .config import COMPACT_ENABLED, COMPACT_KEEP_TURNS, COMPACT_MAX_TOOL_CHARS

# 截断提示的前缀（真正拼进去时会带上"还剩多少行"）
TRUNCATE_MARK = "\n…（输出过长，后面还有"


def _truncate_note(remaining_lines: int) -> str:
    return f"{TRUNCATE_MARK} {remaining_lines} 行未显示）"


@dataclass
class CompactStats:
    """压缩前后的对比数据，供日志/接口展示。"""

    turns_total: int
    turns_kept: int
    turns_dropped: int
    messages_before: int
    messages_after: int
    tool_msgs_truncated: int
    chars_before: int
    chars_after: int
    note: str = ""  # 需要拼进 System Prompt 的"已省略"说明

    def as_dict(self) -> dict:
        return {
            "turns_total": self.turns_total,
            "turns_kept": self.turns_kept,
            "turns_dropped": self.turns_dropped,
            "messages_before": self.messages_before,
            "messages_after": self.messages_after,
            "tool_msgs_truncated": self.tool_msgs_truncated,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "saved_ratio": round(1 - self.chars_after / self.chars_before, 2)
            if self.chars_before
            else 0.0,
        }


def _text_len(message: BaseMessage) -> int:
    """一条消息的近似字符数（含工具调用参数）。"""
    content = message.content
    text = content if isinstance(content, str) else str(content)
    tool_calls = getattr(message, "tool_calls", None) or []
    return len(text) + len(str(tool_calls))


def _split_turns(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
    """按"用户每说一句话"切分成轮次。

    一个轮次 = 一条 HumanMessage + 它的后续所有消息（AI 思考、工具调用、工具结果…），
    直到下一条 HumanMessage 出现。开头的非人类消息（罕见）自成一"轮"。
    """
    turns: list[list[BaseMessage]] = []
    for m in messages:
        if isinstance(m, HumanMessage) or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)
    return turns


def _final_answer(turn: list[BaseMessage]) -> AIMessage | None:
    """找出一轮里"最终结论"那条 AI 消息（没有工具调用、有文本）。"""
    for m in reversed(turn):
        if isinstance(m, AIMessage) and not (getattr(m, "tool_calls", None) or []):
            content = m.content
            text = content if isinstance(content, str) else str(content)
            if text.strip():
                return m
    return None


def _compress_old_turn(turn: list[BaseMessage]) -> list[BaseMessage]:
    """压缩一轮旧对话：只留"问什么 + 结论"，丢掉过程和原始数据。

    注意这里**整段丢弃** AIMessage(tool_calls) 及其 ToolMessage——
    绝不能只丢一半，否则消息配对断裂，API 会报错。
    """
    kept: list[BaseMessage] = [m for m in turn if isinstance(m, HumanMessage)]
    answer = _final_answer(turn)
    if answer is not None:
        kept.append(answer)
    return kept


def _truncate_text(content: str, limit: int) -> str:
    """按**整行**截断文本，绝不把一行切成两半。

    为什么不能直接 content[:limit]：
        工具输出是"一行一个文件"的清单，按字符切会把最后一行切成
        `C:\\...\\Ollam` 这种半截路径——模型看到残缺路径会误判或复述错。

    策略：从第一行开始累加，下一行会超限就停，绝不切在行中间。
    """
    if len(content) <= limit:
        return content

    lines = content.split("\n")

    # 极端情况：第一行本身就超过上限（比如一整个 JSON 压成一行）。
    # 这时无法"按行"截断，只能退化成按字符切，并明确告知模型这是残行。
    if len(lines[0]) > limit:
        rest = len(lines) - 1
        note = "\n…（单行过长，已在此行中截断"
        if rest:
            note += f"，后面还有 {rest} 行未显示"
        return content[:limit] + note + "）"

    kept: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        cost = len(line) + 1  # +1 是换行符
        if used + cost > limit:
            # 这一行放不下 → 停在上一行的行尾，绝不切在行中间
            return "\n".join(kept) + _truncate_note(len(lines) - i)
        kept.append(line)
        used += cost

    return "\n".join(kept)


def _truncate_tools(messages: list[BaseMessage], limit: int) -> tuple[list[BaseMessage], int]:
    """把过长的工具输出按整行截断，返回 (新列表, 截断条数)。"""
    out: list[BaseMessage] = []
    truncated = 0
    for m in messages:
        if isinstance(m, ToolMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            if len(content) > limit:
                # model_copy 会保留 tool_call_id——少了它配对就断了
                m = m.model_copy(update={"content": _truncate_text(content, limit)})
                truncated += 1
        out.append(m)
    return out, truncated


def compact_messages(
    messages: list[BaseMessage],
    keep_turns: int | None = None,
    max_tool_chars: int | None = None,
) -> tuple[list[BaseMessage], CompactStats]:
    """把完整历史压成"发给模型的视图"。返回 (新消息列表, 统计)。

    纯函数：不读写数据库、不修改入参对象（用 model_copy 产生副本）。

    三层处理，力度递增：
    1. 最旧轮次 → 只留"问题 + 结论"，工具原始输出整段丢弃
    2. 较新的历史轮次 → 保留，但工具输出截断到上限
    3. **最后一轮（当前正在进行的）→ 原封不动**：模型正靠它干活，一个字都不能动
    """
    keep = COMPACT_KEEP_TURNS if keep_turns is None else keep_turns
    limit = COMPACT_MAX_TOOL_CHARS if max_tool_chars is None else max_tool_chars
    chars_before = sum(_text_len(m) for m in messages)
    turns = _split_turns(messages)
    truncated_total = 0

    if not COMPACT_ENABLED:
        return messages, CompactStats(
            turns_total=len(turns),
            turns_kept=len(turns),
            turns_dropped=0,
            messages_before=len(messages),
            messages_after=len(messages),
            tool_msgs_truncated=0,
            chars_before=chars_before,
            chars_after=chars_before,
        )

    note = ""
    if not messages:
        # 空历史（理论上不会走到，但函数要能安全处理边界）
        return [], CompactStats(
            turns_total=0,
            turns_kept=0,
            turns_dropped=0,
            messages_before=0,
            messages_after=0,
            tool_msgs_truncated=0,
            chars_before=0,
            chars_after=0,
        )

    if len(turns) <= keep:
        # 轮次不多，不用剪枝；但除最后一轮外仍要限长（单条也可能极长）
        head = messages[: -len(turns[-1])] if len(turns) > 1 else []
        head, truncated_total = _truncate_tools(head, limit)
        result = [*head, *turns[-1]]
    else:
        old_turns, recent_turns = turns[:-keep], turns[-keep:]
        result = []
        # 注意：这里不往 messages 里插 SystemMessage（多数 API 只允许它在开头）。
        # 改为把"已省略"的说明交给调用方拼进真正的 System Prompt。
        note = (
            f"本次会话更早的 {len(old_turns)} 轮对话已被压缩省略，"
            "只保留了其中的用户问题与结论。若用户提到更早的细节而你不知道，如实说明并提议重新扫描。"
        )
        for turn in old_turns:
            result.extend(_compress_old_turn(turn))

        # 最近 N 轮：最后一轮（正在进行的）原样保留，一个字都不动；前面的限长
        for turn in recent_turns[:-1]:
            trimmed, n = _truncate_tools(turn, limit)
            truncated_total += n
            result.extend(trimmed)
        result.extend(recent_turns[-1])

    return result, CompactStats(
        turns_total=len(turns),
        turns_kept=min(keep, len(turns)),
        turns_dropped=max(0, len(turns) - keep),
        messages_before=len(messages),
        messages_after=len(result),
        tool_msgs_truncated=truncated_total,
        chars_before=chars_before,
        chars_after=sum(_text_len(m) for m in result),
        note=note,
    )


def validate_tool_pairs(messages: list[BaseMessage]) -> list[str]:
    """检查工具调用配对是否完整，返回问题列表（空表示合法）。

    这是压缩后必须过的"体检"：宁可这里报错，也别让 API 在线上 400。
    """
    problems: list[str] = []
    pending: dict[str, int] = {}
    for idx, m in enumerate(messages):
        if isinstance(m, AIMessage):
            for call in getattr(m, "tool_calls", None) or []:
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
                if call_id:
                    pending[call_id] = idx
        elif isinstance(m, ToolMessage):
            call_id = getattr(m, "tool_call_id", None)
            if call_id not in pending:
                problems.append(f"第 {idx} 条 ToolMessage 找不到对应的 AIMessage(tool_calls)（id={call_id}）")
            else:
                pending.pop(call_id, None)
    for call_id, idx in pending.items():
        problems.append(f"第 {idx} 条 AIMessage 的 tool_call（id={call_id}）没有对应的 ToolMessage")
    return problems
