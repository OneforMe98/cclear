"""③ 亲手制造 "API 400" —— 看懂 tool_calls 与 ToolMessage 为什么必须成对。

运行：
    .venv\\Scripts\\python.exe learn\\03_break_tool_pairs.py

它会故意发两种"错配"的消息给模型，把服务器返回的 400 原文打印出来。
看完你就明白 compact.py 里为什么必须"整段丢弃"、为什么截断要用 model_copy。

（会消耗 2 次极小的 API 调用，花费可忽略。）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL_NAME
from app.compact import validate_tool_pairs


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL_NAME,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        max_retries=0,  # 关键：不重试，快速暴露错误
    )


def try_send(llm: ChatOpenAI, label: str, messages: list) -> None:
    print("\n" + "=" * 76)
    print(f"【{label}】")
    for i, m in enumerate(messages):
        kind = type(m).__name__
        cid = getattr(m, "tool_call_id", None)
        calls = [c.get("id") for c in (getattr(m, "tool_calls", None) or [])]
        print(f"  [{i}] {kind:12s} tool_call_id={cid}  tool_calls={calls}")
    print(f"  本地体检结果: {validate_tool_pairs(messages) or 'OK'}")

    try:
        resp = llm.invoke(messages)
        print(f"  ✅ 居然成功了: {str(resp.content)[:50]}")
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        print(f"  ❌ 请求失败: {type(exc).__name__}")
        # 把服务器原文里的关键部分挑出来打印
        for line in text.splitlines():
            low = line.lower()
            if any(k in low for k in ("error", "400", "tool", "message", "invalid")):
                print("     |", line.strip()[:190])


def main() -> None:
    if not DEEPSEEK_API_KEY:
        print("没配置 DEEPSEEK_API_KEY，无法演示（先填 backend/.env）")
        return

    llm = build_llm()

    # ---- 错误 1：有 ToolMessage，但没有对应的 AIMessage(tool_calls) ----
    orphan_tool = [
        HumanMessage(content="帮我扫描一下"),
        ToolMessage(content="扫描完成：AppData 占 20GB", tool_call_id="call_不存在的id", name="scan"),
    ]
    try_send(llm, "错误示范 1：孤儿 ToolMessage（没人调用它，它却返回了结果）", orphan_tool)

    # ---- 错误 2：有 AIMessage(tool_calls)，但没有 ToolMessage ----
    unanswered = [
        HumanMessage(content="帮我扫描一下"),
        AIMessage(
            content="",
            tool_calls=[{"name": "scan_directory_size", "args": {"path": "C:\\"}, "id": "call_abc123"}],
        ),
    ]
    try_send(llm, "错误示范 2：工具被调用了，但没把结果喂回去", unanswered)

    # ---- 正确示范 ----
    correct = [
        HumanMessage(content="帮我扫描一下"),
        AIMessage(
            content="",
            tool_calls=[{"name": "scan_directory_size", "args": {"path": "C:\\"}, "id": "call_abc123"}],
        ),
        ToolMessage(content="扫描完成：AppData 占 20GB", tool_call_id="call_abc123", name="scan_directory_size"),
    ]
    try_send(llm, "正确示范：成对出现（tool_call_id 完全一致）", correct)

    print(
        "\n结论：\n"
        "  · tool_call_id 就是「这两个消息是一对」的凭证，必须完全一致\n"
        "  · 少了任何一半，服务器直接 400（Bad Request），整个请求作废\n"
        "  · 所以压缩旧的工具轮次时只能【整段丢弃】——AIMessage + 它所有 ToolMessage 一起删\n"
    )


if __name__ == "__main__":
    main()
