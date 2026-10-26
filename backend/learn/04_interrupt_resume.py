"""④ interrupt / resume 是什么 —— 用 20 行最小例子亲手暂停再恢复。

运行：
    .venv\\Scripts\\python.exe learn\\04_interrupt_resume.py

它复刻本项目里"删除前要你点确认"的机制，但完全不碰你的磁盘（只打印）。
看完你就理解 main.py 里那两个接口（/api/chat 发 confirm、/api/confirm 恢复）在干什么。
"""

import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict):
    target: str      # 要删除的目标（这里只是文字，不会真删）
    approved: bool   # 用户的决定
    deleted: bool    # 最终结果


def ask_user(state: State) -> dict:
    """这个节点会【暂停整个图】，把问题抛给外面的人。"""
    print("  [ask_user] 准备暂停，等待用户确认…")
    # interrupt() 一调用，图就停在这里。它返回的值 = 之后 resume 传进来的决定
    decision = interrupt({"question": f"确认要清理 {state['target']} 吗？"})
    print(f"  [ask_user] 图被恢复了！收到用户的决定: {decision}")
    return {"approved": decision}


def do_delete(state: State) -> dict:
    if not state["approved"]:
        print("  [do_delete] 用户拒绝了，什么都不删。")
        return {"deleted": False}
    print(f"  [do_delete] 用户同意 → 假装删除 {state['target']}")
    return {"deleted": True}


def build():
    g = StateGraph(State)
    g.add_node("ask_user", ask_user)
    g.add_node("do_delete", do_delete)
    g.add_edge(START, "ask_user")
    g.add_edge("ask_user", "do_delete")
    return g.compile(checkpointer=InMemorySaver())


def show_pending(graph, cfg) -> None:
    """怎么知道"图停在等确认"？查 state.tasks 里的 interrupts。"""
    snapshot = graph.get_state(cfg)
    problems = [i for task in snapshot.tasks for i in getattr(task, "interrupts", ())]
    if problems:
        print(f"  → 图处于【暂停】状态，抛出的问题: {problems[0].value}")
        print(f"  → 已执行完的节点: {snapshot.next}  <- 下一步本该是这些")
    else:
        print("  → 图已正常跑完，无待确认项")


def main() -> None:
    graph = build()
    cfg = {"configurable": {"thread_id": "learn-interrupt-1"}}

    print("\n========== 第一次请求：用户说「把临时目录清了」 ==========")
    state = graph.invoke({"target": "C:\\Temp\\垃圾文件", "approved": False, "deleted": False}, cfg)
    show_pending(graph, cfg)
    print("  （这一步在真实项目里 = 后端通过 SSE 发出 {'confirm': ...}，前端弹出确认卡片）")

    print("\n========== 用户点了【拒绝】→ 用 Command(resume=False) 恢复 ==========")
    graph.invoke(Command(resume=False), cfg)
    snap = graph.get_state(cfg)
    print(f"  最终状态: approved={snap.values['approved']}  deleted={snap.values['deleted']}")

    print("\n========== 换个线程，这次用户点【同意】 ==========")
    cfg2 = {"configurable": {"thread_id": "learn-interrupt-2"}}
    graph.invoke({"target": "C:\\Temp\\另一个垃圾", "approved": False, "deleted": False}, cfg2)
    show_pending(graph, cfg2)
    graph.invoke(Command(resume=True), cfg2)
    snap2 = graph.get_state(cfg2)
    print(f"  最终状态: approved={snap2.values['approved']}  deleted={snap2.values['deleted']}")

    print(
        "\n结论：\n"
        "  · interrupt() = 在节点内部踩刹车，把问题抛给外面的人\n"
        "  · 暂停期间，图的所有进度都存在 checkpointer 里（所以能跨请求、甚至跨重启恢复）\n"
        "  · Command(resume=值) = 踩油门，同时把答案交给那个 interrupt() 的返回值\n"
        "  · 本项目对应关系：\n"
        "      工具里的 interrupt()            → 诘问「确认删除吗」\n"
        "      main.py 流结束后查 interrupts   → 发 {'confirm': ...} 给前端\n"
        "      POST /api/confirm               → Command(resume=approved) 恢复\n"
    )


if __name__ == "__main__":
    main()
