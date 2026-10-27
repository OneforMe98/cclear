"""在终端里查看 LangSmith 的 trace，不用打开网页。

用法（在 backend 目录下执行）：

    python learn/07_langsmith_trace.py              列出所有对话（编号 + 摘要）
    python learn/07_langsmith_trace.py 3            看第 3 个对话的完整调用树
    python learn/07_langsmith_trace.py 3 --full     连每次 LLM 的输入输出也打印

为什么用"编号"而不是关键词：PowerShell 传中文参数容易乱码，
纯数字最稳，也不会因为手抖打错字而查不到。

前置条件：backend/.env 里已配置 LANGSMITH_TRACING=1 和 LANGSMITH_API_KEY。
"""

import json
import sys
import warnings

# langsmith 的 list_runs 会打弃用警告，噪音太大，这里关掉
warnings.filterwarnings("ignore")

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client  # noqa: E402

PROJECT = "cclear"


def load_runs() -> tuple[list, dict]:
    """一次性拉取项目里的 run，并按父子关系建索引（避免逐个查询）。"""
    client = Client()
    runs = list(client.list_runs(project_name=PROJECT, limit=100))
    by_parent: dict = {}
    for r in runs:
        by_parent.setdefault(r.parent_run_id, []).append(r)
    for children in by_parent.values():
        children.sort(key=lambda x: x.start_time)
    return runs, by_parent


def first_user_text(run) -> str:
    """从根 run 的输入里取出用户说的第一句话，用来当预览。"""
    inputs = run.inputs or {}
    messages = inputs.get("messages") or []
    for m in messages:
        if isinstance(m, dict) and m.get("type") in ("human", "user"):
            return str(m.get("content", "")).replace("\n", " ")[:40]
    return "(无法解析)"


def summarize(run) -> dict:
    """一次完整对话的概要：耗时、token、调了几次模型、几个工具。"""
    return {
        "secs": (run.end_time - run.start_time).total_seconds() if run.end_time and run.start_time else 0.0,
        "tokens": run.total_tokens or 0,
    }


def count_nodes(by_parent: dict, run) -> tuple[int, int, list[str]]:
    """递归统计这棵树里 LLM 调用次数、工具调用次数、用到的工具名。"""
    llm = 0
    tools: list[str] = []
    stack = [run]
    while stack:
        cur = stack.pop()
        if cur.run_type == "llm":
            llm += 1
        elif cur.run_type == "tool":
            tools.append(cur.name or "?")
        stack.extend(by_parent.get(cur.id, []))
    return llm, len(tools), tools


def print_tree(by_parent: dict, run, depth: int = 0, full: bool = False) -> None:
    secs = (run.end_time - run.start_time).total_seconds() if run.end_time and run.start_time else 0.0
    tokens = run.total_tokens or 0
    indent = "  " * depth
    print(f"{indent}[{run.run_type}] {run.name}  {secs:.2f}s  {tokens} tok")

    if full and run.run_type == "llm":
        # 模型收到的消息条数 + 模型输出的意图（有没有 tool_calls）
        inputs = run.inputs or {}
        messages = inputs.get("messages")
        if isinstance(messages, list):
            # 有些版本会嵌套一层
            msgs = messages[0] if messages and isinstance(messages[0], list) else messages
            print(f"{indent}    收到 {len(msgs)} 条消息")
        outputs = run.outputs or {}
        gens = outputs.get("generations")
        if gens:
            first = gens[0][0] if isinstance(gens[0], list) else gens[0]
            msg = first.get("message", {}) if isinstance(first, dict) else {}
            # 不同版本结构不一：有时 tool_calls 直接在 message 里，
            # 有时藏在 message.kwargs（LangChain 的序列化格式）里
            calls = msg.get("tool_calls") or msg.get("kwargs", {}).get("tool_calls") or []
            kind = "要调工具" if calls else "直接回答"
            names = [c.get("name") or c.get("function", {}).get("name") for c in calls]
            print(f"{indent}    意图: {kind} {names if names else ''}")

    for child in by_parent.get(run.id, []):
        print_tree(by_parent, child, depth + 1, full)


def main() -> None:
    runs, by_parent = load_runs()
    roots = by_parent.get(None, [])
    if not roots:
        print(f"项目 {PROJECT} 里还没有任何记录。先聊一句，等几秒再试。")
        return

    args = [a for a in sys.argv[1:] if a != "--full"]
    full = "--full" in sys.argv

    if not args:
        print(f"项目 {PROJECT} · 共 {len(roots)} 次对话（最新在前）\n")
        for idx, run in enumerate(reversed(roots), 1):
            s = summarize(run)
            llm, ntools, names = count_nodes(by_parent, run)
            preview = first_user_text(run)
            when = run.start_time.strftime("%m-%d %H:%M:%S")
            print(f"  {idx:>2}. [{when}] {s['secs']:5.1f}s  {s['tokens']:>5} tok  "
                  f"模型×{llm}  工具×{ntools}  «{preview}»")
        print("\n看详情：python learn/07_langsmith_trace.py <编号>")
        print("看输入输出：python learn/07_langsmith_trace.py <编号> --full")
        return

    try:
        pick = int(args[0])
    except ValueError:
        print("编号必须是数字，例如：python learn/07_langsmith_trace.py 1")
        return

    ordered = list(reversed(roots))
    if not (1 <= pick <= len(ordered)):
        print(f"编号超出范围（1~{len(ordered)}）")
        return

    target = ordered[pick - 1]
    s = summarize(target)
    llm, ntools, names = count_nodes(by_parent, target)
    print("=" * 68)
    print(f"对话 #{pick} · {target.start_time:%Y-%m-%d %H:%M:%S}")
    print(f"耗时 {s['secs']:.1f}s · {s['tokens']} tok · 模型调用 {llm} 次 · 工具 {ntools} 次")
    if names:
        print(f"用到的工具：{', '.join(names)}")
    print("=" * 68)
    print_tree(by_parent, target, full=full)


if __name__ == "__main__":
    main()
