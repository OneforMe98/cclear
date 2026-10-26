"""Agent 本体：用 LangGraph 组装"模型 ↔ 工具"的循环。

这就是 Agent 和"聊天机器人"的本质区别：
- 聊天机器人：模型只会说话
- Agent：模型可以输出"我要调用工具"的意图 → 框架执行工具 → 把结果喂回模型 →
  模型继续思考 → 直到给出最终回答（这个圈就是所谓的 ReAct 循环）

LangGraph 用一张"图"来表达这个循环：
    START → agent（模型思考） ──有工具调用──→ tools（执行工具） → 回到 agent
                            └──没有工具调用──→ 结束
"""

from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from . import profile
from .compact import compact_messages
from .config import (
    AGENT_MAX_STEPS,
    CHECKPOINT_DB,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LANGSMITH_ENABLED,
    LANGSMITH_PROJECT,
    MODEL_NAME,
    MODEL_TEMPERATURE,
    PROFILE_DB,
)
from .tools import TOOLS

# 整个循环最多跑多少步（模型思考 + 调工具都算一步），防止失控死循环
# 数值放进了配置文件，可用环境变量 AGENT_MAX_STEPS 覆盖
MAX_STEPS = AGENT_MAX_STEPS

# 把本机的真实路径写进 Prompt —— 模型不知道你的电脑长什么样，
# 需要什么"现场信息"，就由我们从程序这边动态注入。这是 Agent 工程里很常用的手法。
USER_HOME = Path.home()

SYSTEM_PROMPT = f"""你是 CCLEAR，一个帮助用户分析和清理 Windows C 盘空间的 AI 助手。

你的三条原则：
1. 透明：结论必须基于真实数据，不猜测、不编造
2. 安全：你只做只读分析，永远不建议用户直接删除系统关键文件
3. 克制：先用工具拿到真实数据再下结论；工具扫描不到的内容，如实说明而不是编造

工具使用说明（你有五个工具）：
- scan_directory_size：看"某个文件夹总共多大"、"某目录下各项内容的占用排行"。不传 path 时默认扫描用户主目录 {USER_HOME}。
- find_large_files：递归找出指定目录下"单个最大的文件"（可按最小大小过滤）。适合"哪些文件最占地方""找出最大的安装包/视频"。
- detect_junk_dirs：盘点常见的系统垃圾目录（临时文件、缓存、回收站、Windows.old 等）并统计大小，不需要参数。适合"有什么垃圾可以清理""能释放多少空间"。
- delete_to_recycle_bin：把用户明确要求清理的路径删除到回收站（可恢复）。调用后系统会暂停并请用户确认，用户拒绝则不会删除任何东西。
- remember_preference / forget_preference：记住或忘记用户的**长期偏好**（跨会话有效）。

选择原则：问"哪个文件夹占空间"→ 用 scan_directory_size；问"哪个文件最大"→ 用 find_large_files；问"有什么垃圾可清理/能释放多少空间"→ 用 detect_junk_dirs。可以组合使用，例如先 detect_junk_dirs 盘点，再对某个目录用 scan_directory_size 下钻。工具返回的是真实扫描结果，回答时引用其中的具体名称和数字，绝不编造路径或数字。

删除纪律（最高优先级）：
1. 删除前必须先扫描分析，向用户说明要删什么、为什么安全，再调用 delete_to_recycle_bin
2. 只删除用户明确要求清理的路径；用户没点名的用户资料（文档、桌面、下载等）一律不主动删
3. 永远不要把系统目录（Windows、Program Files、ProgramData）或用户主目录本身放进删除清单
4. 用户拒绝确认后，立即停止删除，并询问用户还需要什么帮助

回答要求：简洁的中文，适当使用列表和标题。"""


def build_system_prompt(compact_note: str = "") -> str:
    """System Prompt 每次调用时现拼：基础人设 + 当前用户画像 + 压缩说明。

    为什么不在模块加载时算一次就好：画像是会变的（用户随时可能新增偏好），
    如果启动时拼接、之后永不更新，就会出现"刚记住的偏好这轮还不生效"的怪现象。
    每次拼一次字符串的开销可以忽略（纯内存操作）。

    compact_note：历史被压缩时的一句说明——告诉模型"你看到的历史不完整"，
    避免它以为对话只有这么短、或者编造更早的细节。
    """
    from .profile import prompt_section

    prompt = SYSTEM_PROMPT + prompt_section()
    if compact_note:
        prompt += f"\n\n上下文说明：{compact_note}"
    return prompt


def _build_graph(llm_with_tools: ChatOpenAI, checkpointer):
    """组装 LangGraph 有向图。"""

    def call_model(state: MessagesState):
        # ① 压缩：把完整历史压成"发给模型的视图"（存档一个字不改）
        view, stats = compact_messages(state["messages"])
        if stats.turns_dropped or stats.tool_msgs_truncated:
            print(
                f"[compact] {stats.messages_before}→{stats.messages_after} 条消息，"
                f"{stats.chars_before}→{stats.chars_after} 字符，"
                f"丢弃 {stats.turns_dropped} 轮，截断 {stats.tool_msgs_truncated} 条工具输出"
            )

        # ② System Prompt 现拼（含画像 + 压缩说明），拼在最前面
        messages = [SystemMessage(content=build_system_prompt(stats.note)), *view]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))

    graph.add_edge(START, "agent")
    # 这个条件分支决定"下一步去哪"：
    #   tools_condition 看最后一条 AI 消息里有没有 tool_calls
    #     ├─ 有  → 返回 "tools"     → 去执行工具，然后绕回 agent
    #     └─ 没有 → 返回 "__end__"   → 图结束，把回答返回给前端
    #
    # "__end__" 就是 END。它是 LangGraph 的内部常量，等价于 `from langgraph.graph import END`。
    # 这里用字典把两条路都显式写出来（比只写一个字符串更清楚：一眼看到"结束"这条分支）。
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    # 工具执行完一定回到 agent（模型要看结果再决定下一步）
    graph.add_edge("tools", "agent")

    # checkpointer：把每一步对话状态存起来，是 interrupt（暂停等确认）和
    # "对话记忆"的共同基石。由 init_agent 传入（SQLite 持久化，重启不丢）。
    return graph.compile(checkpointer=checkpointer)


# 没配 Key 时先不建 Agent，服务照常启动，等请求进来再给出清晰报错。
# 图在应用启动时初始化（init_agent）——因为异步 checkpointer 需要运行中的事件循环。
agent = None
_saver_cm = None  # AsyncSqliteSaver 的连接上下文（保持打开，应用关闭时释放）


async def init_agent() -> None:
    """应用启动时调用：创建模型客户端、打开 SQLite 存档、编译 Agent 图。"""
    global agent, _saver_cm
    # 画像要先初始化：即使没配 Key，用户也应该能在界面上看到已存的偏好
    profile.init(PROFILE_DB)
    if LANGSMITH_ENABLED:
        # 明确打出来：追踪会把对话内容和扫描路径上传到云端，不能悄悄开
        print(f"[langsmith] 已启用链路追踪 → 项目 {LANGSMITH_PROJECT}（对话内容将上报云端）")
    if not DEEPSEEK_API_KEY:
        return
    _llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=MODEL_TEMPERATURE,
    )
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    # 必须用异步版 SqliteSaver：图通过 astream/aget_state 走异步接口，
    # 同步版会直接报 "does not support async methods"
    _saver_cm = AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB))
    saver = await _saver_cm.__aenter__()
    # bind_tools：把工具"说明书"一起交给模型，模型才知道自己有哪些工具可用
    agent = _build_graph(_llm.bind_tools(TOOLS), saver)


async def close_agent() -> None:
    """应用关闭时调用：释放数据库连接。"""
    global _saver_cm
    if _saver_cm is not None:
        await _saver_cm.__aexit__(None, None, None)
        _saver_cm = None
