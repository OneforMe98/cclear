import type { ChatMessage } from './types'

/** 后端 interrupt 暂停时发来的"待确认"事件 */
export interface ConfirmPayload {
  type: string
  paths: string[]
  rejected?: string[]
}

/** 工具执行完成的事件（用于时间线展示） */
export interface ToolResultPayload {
  name: string
  chars?: number
  preview?: string
  artifact?: DirSizesArtifact | JunkArtifact
}

/** scan_directory_size 的结构化结果 */
export interface DirSizesArtifact {
  kind: 'dir_sizes'
  path?: string
  total_bytes: number
  entries: { name: string; bytes: number; is_dir?: boolean }[]
}

/** detect_junk_dirs 的结构化结果 */
export interface JunkArtifact {
  kind: 'junk'
  total_bytes: number
  entries: { label: string; path: string; bytes: number; risk: string }[]
}

export interface StreamHandlers {
  onDelta: (text: string) => void
  onConfirm?: (payload: ConfirmPayload) => void
  onTool?: (name: string) => void
  onToolResult?: (payload: ToolResultPayload) => void
}

interface SSEEvent {
  delta?: string
  error?: string
  tool?: string
  tool_result?: ToolResultPayload
  confirm?: ConfirmPayload
}

/**
 * 读取一个 SSE 响应流并分发事件。
 * 后端事件格式（每条以空行结尾；": ping" 是心跳注释，自动忽略）：
 *   data: {"delta": "文本"} | {"tool": "..."} | {"tool_result": {...}} | {"confirm": {...}} | {"error": "..."} | [DONE]
 */
async function readSSE(res: Response, handlers: StreamHandlers): Promise<void> {
  if (!res.body) {
    throw new Error('当前浏览器不支持流式读取响应')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 事件之间用空行分隔，逐个取出处理
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const eventBlock = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      for (const line of eventBlock.split('\n')) {
        // 以 ":" 开头的是 SSE 注释（心跳），直接跳过
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        if (payload === '[DONE]') return

        const event = JSON.parse(payload) as SSEEvent
        if (event.error) throw new Error(event.error)
        if (event.tool) handlers.onTool?.(event.tool)
        if (event.tool_result) handlers.onToolResult?.(event.tool_result)
        if (event.confirm) handlers.onConfirm?.(event.confirm)
        if (event.delta) handlers.onDelta(event.delta)
      }

      boundary = buffer.indexOf('\n\n')
    }
  }
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return
  // 后端的错误详情（如 "还没配置 API Key"）放在 detail 字段里，透传给用户看
  let detail = `HTTP ${res.status}`
  try {
    const data = await res.json()
    if (data?.detail) detail = String(data.detail)
  } catch {
    // 响应体不是 JSON 就忽略，保留默认信息
  }
  throw new Error(detail)
}

/**
 * 把"这一轮的新消息"发给后端（Agent），流式回调模型输出；
 * 历史记忆在服务端，无需重复发送。
 * 如果 Agent 中途暂停等待确认，会通过 onConfirm 通知。
 */
export async function streamMessage(
  threadId: string,
  message: string,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, message }),
  })
  await throwIfNotOk(res)
  await readSSE(res, handlers)
}

export interface HistoryResponse {
  thread_id: string
  messages: ChatMessage[]
  artifacts?: (DirSizesArtifact | JunkArtifact)[]
  pending_confirm: ConfirmPayload | null
}

/**
 * 取某个会话在服务端的历史（对话记忆）。
 * 刷新页面后调用它恢复对话；若当时正等待删除确认，也会一并带回。
 */
export async function fetchHistory(threadId: string): Promise<HistoryResponse> {
  const res = await fetch(`/api/history?thread_id=${encodeURIComponent(threadId)}`)
  await throwIfNotOk(res)
  return (await res.json()) as HistoryResponse
}

/** 一条长期偏好（用户画像） */
export interface ProfileEntry {
  key: string
  value: string
  updated_at: string
}

export interface ProfileResponse {
  user_id: string
  entries: ProfileEntry[]
}

/**
 * 取当前用户的长期画像。
 * 与 history 的区别：history 是"这次聊了什么"（按会话），画像是"这个人什么样"（跨会话）。
 */
export async function fetchProfile(): Promise<ProfileResponse> {
  const res = await fetch('/api/profile')
  await throwIfNotOk(res)
  return (await res.json()) as ProfileResponse
}

/** 手动让 AI 忘掉一条偏好。 */
export async function deleteProfileEntry(key: string): Promise<void> {
  const res = await fetch(`/api/profile/${encodeURIComponent(key)}`, { method: 'DELETE' })
  await throwIfNotOk(res)
}

/**
 * 对"删除确认"作出决定（批准/拒绝），恢复被暂停的 Agent 并继续流式输出。
 */
export async function confirmAction(
  threadId: string,
  approved: boolean,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch('/api/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, approved }),
  })
  await throwIfNotOk(res)
  await readSSE(res, handlers)
}
