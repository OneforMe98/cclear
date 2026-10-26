import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from pydantic import BaseModel

from . import agent as agent_module
from . import profile
from .compact import compact_messages
from .config import MODEL_NAME, PROFILE_USER_ID


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动时初始化 Agent（打开 SQLite 存档），关闭时释放。"""
    await agent_module.init_agent()
    try:
        yield
    finally:
        await agent_module.close_agent()


app = FastAPI(title="CCLEAR API", version="0.6.0", lifespan=lifespan)

# 开发阶段允许前端（Vite 开发服务器）跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    # 只允许这两种角色（这是"给前端的视图"）；工具消息只存在于服务端
    role: Literal["user", "assistant"]
    content: str
    # 消息创建时间（ISO 8601）。取自 checkpointer 状态历史，刷新后也保留
    ts: str | None = None


class ChatRequest(BaseModel):
    # 会话 ID（前端生成并持久化）。历史记忆与暂停/恢复都按它存取。
    thread_id: str
    # 只发"这一轮的新消息"——历史已存在服务端 checkpointer 里（对话记忆）
    message: str


class ConfirmRequest(BaseModel):
    thread_id: str
    approved: bool


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[Message]
    # 历史中所有工具产出的结构化结果（artifact），前端用它恢复图表卡片
    artifacts: list[dict] = []
    pending_confirm: dict | None = None


def _chat_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": agent_module.MAX_STEPS,
    }


def _require_agent() -> None:
    if agent_module.agent is None:
        raise HTTPException(
            status_code=500,
            detail="后端还没配置 DeepSeek API Key：请打开 backend/.env 填入 DEEPSEEK_API_KEY，保存后重启后端。",
        )


def user_facing_error(exc: Exception) -> str:
    """把异常翻译成"用户能看懂的话"。

    原则：用户需要知道"发生了什么 + 该怎么办"，而不是看到 Python 堆栈。
    详细原因写日志（见调用处 print），不塞进前端文案。
    """
    if isinstance(exc, GraphRecursionError):
        return (
            f"这个问题需要太多步操作（超过 {agent_module.MAX_STEPS} 步），我先停下了。"
            "可以把它拆成更小的问题分别问我，比如先只扫描一个目录，再针对某项深入分析。"
        )
    return f"Agent 运行失败（{type(exc).__name__}），请稍后重试；若持续失败请查看后端日志。"


# 心跳间隔：多久没有新数据就发一次注释行，防止代理/浏览器掐断空闲连接
# 可用环境变量 HEARTBEAT_SECONDS 覆盖（便于测试）
HEARTBEAT_SECONDS = float(os.getenv("HEARTBEAT_SECONDS", "10"))


async def _stream_graph(graph_input, thread_id: str) -> AsyncIterator[str]:
    """运行（或恢复）Agent 图，把过程翻译成 SSE 事件流。

    - {"delta": "文本"}：模型的回答片段（只取最终回答节点的输出）
    - {"tool": "工具名"}：模型决定调用工具时通知前端
    - {"tool_result": {...}}：工具执行完成，结果摘要与结构化数据（artifact）
    - {"confirm": {...}}：图被 interrupt 暂停，等待用户确认（删除前必出现）
    - {"error": "原因"}：中途出错（HTTP 状态码已是 200，只能靠事件通知）
    - ": ping"：心跳注释行（SSE 规范：以 ":" 开头的行是注释，前端自动忽略）
    - [DONE]：本轮结束
    """
    config = _chat_config(thread_id)
    pending_task: asyncio.Task | None = None
    try:
        assert agent_module.agent is not None  # 调用方已保证 Key 已配置
        stream_iter = agent_module.agent.astream(
            graph_input,
            stream_mode="messages",  # 按"消息片段"流式输出
            config=config,
        ).__aiter__()
        pending_task = asyncio.create_task(stream_iter.__anext__())

        while True:
            # 等待下一个片段；超时就发心跳，而不是让连接干着
            # （不能用 wait_for——超时会取消掉取片段的协程，把流弄断）
            done, _ = await asyncio.wait({pending_task}, timeout=HEARTBEAT_SECONDS)
            if not done:
                yield ": ping\n\n"
                continue

            try:
                chunk, metadata = pending_task.result()
            except StopAsyncIteration:
                pending_task = None
                break
            pending_task = asyncio.create_task(stream_iter.__anext__())

            node = metadata.get("langgraph_node")

            if node != "agent":
                # 工具节点的产物（ToolMessage）：把结果摘要推给前端，用于时间线/图表
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    name = getattr(chunk, "name", None) or "工具"
                    result: dict = {
                        "name": name,
                        "chars": len(content),
                        "preview": content[:160],
                    }
                    # artifact：工具的"机器可读版"结果（如目录大小清单），供前端画图表
                    artifact = getattr(chunk, "artifact", None)
                    if artifact is not None:
                        result["artifact"] = artifact
                    yield f"data: {json.dumps({'tool_result': result}, ensure_ascii=False)}\n\n"
                continue

            # 模型决定调用工具时，chunk 里带 tool_call_chunks
            for tc in getattr(chunk, "tool_call_chunks", None) or []:
                name = tc.get("name")
                if name:
                    print(f"[agent] 调用工具: {name}")
                    yield f"data: {json.dumps({'tool': name}, ensure_ascii=False)}\n\n"
                    # 空出一行，把"调用工具前的自言自语"和"最终回答"自然分开
                    yield f"data: {json.dumps({'delta': chr(10) * 2}, ensure_ascii=False)}\n\n"

            text = getattr(chunk, "text", "")
            if text:
                yield f"data: {json.dumps({'delta': text}, ensure_ascii=False)}\n\n"
    except GraphRecursionError as exc:
        # 步数超限：这是"用户可理解的限制"，不该把原始异常文本丢给用户
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
        yield f"data: {json.dumps({'error': user_facing_error(exc)}, ensure_ascii=False)}\n\n"
        return
    except Exception as exc:  # noqa: BLE001 —— 其它异常给出简洁提示，详细原因打到后端日志
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
        print(f"[agent] 运行失败: {type(exc).__name__}: {exc}")
        yield f"data: {json.dumps({'error': user_facing_error(exc)}, ensure_ascii=False)}\n\n"
        return
    finally:
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()

    # 流结束后检查：图是不是停在了 interrupt 上（等待人工确认）？
    state = await agent_module.agent.aget_state(config)
    pending = [
        item
        for task in state.tasks
        for item in getattr(task, "interrupts", ())
    ]
    if pending:
        payload = {"confirm": pending[0].value}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"


async def _message_timestamps(config: dict) -> dict[str, str]:
    """给每条消息找出"它最早出现的那一步"的时间戳。

    aget_state_history 是从「最新」到「最旧」返回快照的，所以不断覆盖——
    最后一次写进去的就是"最旧的那份含它的快照"，即这条消息诞生的大致时间。
    """
    stamps: dict[str, str] = {}
    try:
        async for snap in agent_module.agent.aget_state_history(config):
            created = getattr(snap, "created_at", None)
            if not created:
                continue
            iso = created if isinstance(created, str) else created.isoformat()
            for m in snap.values.get("messages", []):
                mid = getattr(m, "id", None)
                if mid:
                    stamps[mid] = iso  # 覆盖：越往后越旧，最终留下最早时间
    except Exception:  # noqa: BLE001 —— 时间戳是锦上添花，取不到不影响主流程
        pass
    return stamps


async def _state_to_history(thread_id: str) -> HistoryResponse:
    """把 checkpointer 里的图状态，转换成前端能渲染的消息列表。

    过滤规则：只保留 Human/AI 的文本消息；工具消息（ToolMessage）不展示。
    连续的 AI 消息（前言 + 最终回答）合并成一条，避免历史里碎片化。
    """
    assert agent_module.agent is not None
    config = _chat_config(thread_id)
    state = await agent_module.agent.aget_state(config)
    stamps = await _message_timestamps(config)

    def ts_of(m) -> str | None:
        mid = getattr(m, "id", None)
        return stamps.get(mid) if mid else None

    messages: list[Message] = []
    artifacts: list[dict] = []
    for m in state.values.get("messages", []):
        if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content:
            messages.append(Message(role="user", content=m.content, ts=ts_of(m)))
        elif isinstance(m, AIMessage):
            text = getattr(m, "text", "") or (m.content if isinstance(m.content, str) else "")
            if not text:
                continue
            if messages and messages[-1].role == "assistant":
                messages[-1] = Message(
                    role="assistant",
                    content=messages[-1].content + "\n\n" + text,
                    ts=messages[-1].ts,  # 合并后保留更早那条的时间
                )
            else:
                messages.append(Message(role="assistant", content=text, ts=ts_of(m)))
        elif isinstance(m, ToolMessage):
            # 工具消息本身不展示，但它携带的 artifact 要收集起来（刷新后恢复图表用）
            artifact = getattr(m, "artifact", None)
            if artifact is not None:
                artifacts.append(artifact)

    pending = [
        item
        for task in state.tasks
        for item in getattr(task, "interrupts", ())
    ]
    return HistoryResponse(
        thread_id=thread_id,
        messages=messages,
        artifacts=artifacts,
        pending_confirm=pending[0].value if pending else None,
    )


class ProfileEntry(BaseModel):
    key: str
    value: str
    updated_at: str


class ProfileResponse(BaseModel):
    user_id: str
    entries: list[ProfileEntry]


# 改动画像的工具名：这两个工具跑完后要让前端刷新侧栏
PROFILE_TOOLS = {"remember_preference", "forget_preference"}


@app.get("/api/profile")
def get_profile() -> ProfileResponse:
    """当前用户的长期画像（跨会话偏好）。

    与 /api/history 的区别：history 是"这次聊了什么"（按 thread），
    profile 是"这个人什么样"（跨所有 thread），所以这里不需要 thread_id。
    """
    return ProfileResponse(user_id=PROFILE_USER_ID, entries=profile.get_all())


@app.delete("/api/profile/{key}")
def delete_profile_entry(key: str) -> dict:
    """手动删除一条画像条目（用户不想让 AI 再记得这件事）。"""
    return {"result": profile.forget_preference(key)}


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "phase": "7",
        "model": MODEL_NAME,
        "api_key_configured": agent_module.agent is not None,
    }


@app.get("/api/context/{thread_id}")
async def context_report(thread_id: str) -> dict:
    """上下文体检：这个会话的存档多大、压缩后会是多少。

    只读、不触发模型调用——用来回答"为什么它忘了前面说的"这类疑问。
    """
    _require_agent()
    state = await agent_module.agent.aget_state(_chat_config(thread_id))
    messages = state.values.get("messages", [])
    _, stats = compact_messages(messages)
    return {
        "thread_id": thread_id,
        "archived": {
            "messages": len(messages),
            "chars": sum(len(str(getattr(m, "content", ""))) for m in messages),
        },
        "after_compaction": stats.as_dict(),
    }


@app.get("/api/history")
async def history(thread_id: str) -> HistoryResponse:
    """取某个会话的完整历史（对话记忆的主查询口）。

    刷新页面、甚至重启后端后，只要 thread_id 相同就能恢复话题。
    """
    _require_agent()
    return await _state_to_history(thread_id)


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    _require_agent()
    # 只把"新消息"喂进图；历史由 checkpointer 里该 thread_id 的状态自动带上
    return StreamingResponse(
        _stream_graph({"messages": [HumanMessage(content=req.message)]}, req.thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/confirm")
def confirm(req: ConfirmRequest) -> StreamingResponse:
    """用户对"删除确认"作出决定后，恢复被暂停的 Agent 图并继续执行。"""
    _require_agent()
    return StreamingResponse(
        _stream_graph(Command(resume=req.approved), req.thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
